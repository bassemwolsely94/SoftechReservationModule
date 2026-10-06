"""
apps/purchasing/lead_time.py

Estimate per-supplier replenishment lead time from SOFTECH purchase history and
populate purchasing.SupplierLeadTime — consumed by the advanced engine's ROP/JIT
math (falls back to the per-ABC default for suppliers with no estimate).

SOFTECH purchase document = stktransm/stktrans doccode '10' (goods receipt).
Because the exact purchase-header schema varies, the estimator DISCOVERS the
columns at runtime (like the tier-preview flow):
  • a date column  (prefer an explicit order-date if present → true lead time;
    otherwise use the receipt docdate → cadence proxy between consecutive
    receipts, which approximates the effective replenishment interval).
  • a supplier column (personcode / suppcode / custcode).

READ-ONLY on SOFTECH. Safe to re-run; upserts SupplierLeadTime.
Unverified against the live schema while SOFTECH is unreachable — run when up.
"""
import logging
import statistics

logger = logging.getLogger('elrezeiky.purchasing')

_DATE_HINTS_ORDER = ('orderdate', 'order_date', 'orderdatetime', 'podate')
_DATE_HINTS_RECV  = ('docdate', 'recdate', 'receiptdate')
_SUPP_HINTS       = ('supp_main_code', 'suppcode', 'supp', 'personcode', 'custcode',
                     'supplier', 'vendorcode')


def _pick(cols, hints):
    low = {c.lower(): c for c in cols}
    for h in hints:
        if h in low:
            return low[h]
    # fuzzy contains
    for h in hints:
        for lc, orig in low.items():
            if h in lc:
                return orig
    return None


def estimate_lead_times(days_back: int = 365, min_samples: int = 3) -> dict:
    """
    Returns {suppliers, updated, method, error?}. Upserts SupplierLeadTime.
    """
    from django.utils import timezone
    from config.sybase import get_sybase_connection
    from apps.purchasing.models import SupplierLeadTime

    try:
        conn = get_sybase_connection()
        cur = conn.cursor()
    except Exception as exc:
        return {'error': f'SOFTECH unreachable: {exc}', 'suppliers': 0, 'updated': 0}

    try:
        # Schema only (zero rows) — TOP is unreliable on this large table.
        cur.execute("SELECT * FROM SOFTECHDB9.dbo.stktransm WHERE 1 = 0")
        cols = [d[0] for d in cur.description]
        cur.fetchall()

        supp_col  = _pick(cols, _SUPP_HINTS)
        order_col = _pick(cols, _DATE_HINTS_ORDER)
        recv_col  = _pick(cols, _DATE_HINTS_RECV)
        if not supp_col or not recv_col:
            return {'error': f'لم يمكن تحديد أعمدة المورد/التاريخ. الأعمدة: {cols}',
                    'suppliers': 0, 'updated': 0, 'columns': cols}

        # True lead time if an order date exists on the same doc; else cadence.
        method = 'order_to_receive' if order_col else 'receipt_interval'
        since = (timezone.localdate() - timezone.timedelta(days=days_back)).isoformat() \
            if hasattr(timezone, 'timedelta') else None
        import datetime as _dt
        since = (_dt.date.today() - _dt.timedelta(days=days_back)).isoformat()

        if method == 'order_to_receive':
            cur.execute(
                f"SELECT {supp_col}, {order_col}, {recv_col} FROM SOFTECHDB9.dbo.stktransm "
                f"WHERE doccode='10' AND {recv_col} >= ? AND {order_col} IS NOT NULL",
                [since])
            per_supp = {}
            for supp, od, rd in cur.fetchall():
                try:
                    od = od.date() if hasattr(od, 'date') else od
                    rd = rd.date() if hasattr(rd, 'date') else rd
                    d = (rd - od).days
                    if 0 <= d <= 180:
                        per_supp.setdefault(str(supp).strip(), []).append(d)
                except Exception:
                    pass
        else:
            cur.execute(
                f"SELECT {supp_col}, {recv_col} FROM SOFTECHDB9.dbo.stktransm "
                f"WHERE doccode='10' AND {recv_col} >= ? ORDER BY {supp_col}, {recv_col}",
                [since])
            dates = {}
            for supp, rd in cur.fetchall():
                try:
                    rd = rd.date() if hasattr(rd, 'date') else rd
                    dates.setdefault(str(supp).strip(), []).append(rd)
                except Exception:
                    pass
            per_supp = {}
            for supp, ds in dates.items():
                ds = sorted(set(ds))
                gaps = [(ds[i] - ds[i - 1]).days for i in range(1, len(ds))]
                gaps = [g for g in gaps if 0 < g <= 180]
                if gaps:
                    per_supp[supp] = gaps
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Resolve supplier names from catalog for readability.
    from apps.catalog.models import Item
    name_map = dict(
        Item.objects.exclude(supplier_code='')
        .values_list('supplier_code', 'supplier_name').distinct()
    )

    updated = 0
    for supp, samples in per_supp.items():
        if len(samples) < min_samples:
            continue
        lt = round(statistics.median(samples), 1)
        SupplierLeadTime.objects.update_or_create(
            supplier_code=supp,
            defaults={
                'supplier_name': name_map.get(supp, ''),
                'lead_time_days': lt,
                'sample_count': len(samples),
                'method': method,
            },
        )
        updated += 1

    logger.info('[lead_time] method=%s suppliers=%d updated=%d', method, len(per_supp), updated)
    return {'method': method, 'suppliers': len(per_supp), 'updated': updated,
            'supplier_col': supp_col, 'recv_col': recv_col, 'order_col': order_col}
