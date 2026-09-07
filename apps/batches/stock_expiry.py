"""
apps/batches/stock_expiry.py

Multi-node sweep of SOFTECH `stkbalexpiry` (current on-hand per-batch expiry) into
the local `StockExpiryBalance` mirror — HQ/central + every operational branch's
own Sybase node — so the FEFO tabs show live near-expiry / expired stock chain-
wide without hitting 6 flaky nodes on every page load.

Resilient per node: an unreachable branch is skipped (its previously-synced rows
are kept) and recorded in the run detail; the others still refresh. Each node's
rows are REPLACED atomically (current-balance snapshot, not additive).
"""
import datetime as _dt
import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger('elrezeiky.batches')

_QUARANTINE_STORES = {'102', '103', '105'}

# All on-hand expiry rows on a node (near-future AND already-expired backlog).
_SQL = (
    "SET ROWCOUNT 0 "
    "SELECT sbe.itemcode, sbe.itemexpirydate, sbe.itemqty, sbe.storecode, "
    "       sbe.batchno, i.itemname "
    "FROM SOFTECHDB9.dbo.stkbalexpiry sbe "
    "JOIN SOFTECHDB9.dbo.items i ON i.itemcode = sbe.itemcode "
    "WHERE sbe.itemqty > 0"
)


def _s(v):
    return '' if v is None else str(v).strip()


def _to_date(v):
    if v is None:
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    s = str(v)[:10]
    try:
        return _dt.datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return None


def _to_dec(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0')


def _node_conn(branch):
    """Open the Sybase connection for a branch's node (HQ falls back to central)."""
    from config.sybase import get_sybase_connection, get_branch_connection
    host = (branch.db_host or '').strip()
    if not host:                       # HQ / central
        return get_sybase_connection()
    return get_branch_connection(host, branch.effective_db_port(),
                                 branch.db_name or 'SOFTECHDB9')


def sync_stock_expiry_all(run=None, only_branch=None, timeout=180):
    """Sweep every operational node's stkbalexpiry into StockExpiryBalance.
    Returns a summary dict; updates `run` (StockExpirySyncRun) if given."""
    from django.db import transaction
    from apps.branches.models import Branch
    from .models import StockExpiryBalance

    qs = Branch.objects.filter(is_operational=True)
    if only_branch:
        qs = qs.filter(softech_branch_id=str(only_branch))
    branches = list(qs)

    detail, total_rows, ok, failed = {}, 0, 0, 0
    for b in branches:
        bc = b.softech_branch_id
        try:
            conn = _node_conn(b)
            try:
                cur = conn.cursor()
                cur.execute(_SQL, timeout=timeout)
                rows = cur.fetchall()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            failed += 1
            detail[bc] = {'ok': False, 'error': str(e)[:200]}
            logger.warning('[StockExpiry] branch %s node unreachable/failed: %s', bc, e)
            continue

        objs = []
        for r in rows:
            ic = _s(r[0])
            exp = _to_date(r[1])
            if not ic or exp is None:
                continue
            store = _s(r[3])
            objs.append(StockExpiryBalance(
                branch_code=bc, store_code=store[:10], item_code=ic[:6],
                item_name=_s(r[5])[:255], batch_no=_s(r[4])[:50],
                expiry_date=exp, qty=_to_dec(r[2]),
                is_quarantine=store in _QUARANTINE_STORES,
            ))
        with transaction.atomic():
            StockExpiryBalance.objects.filter(branch_code=bc).delete()
            StockExpiryBalance.objects.bulk_create(objs, batch_size=1000)
        ok += 1
        total_rows += len(objs)
        detail[bc] = {'ok': True, 'rows': len(objs)}
        logger.info('[StockExpiry] branch %s synced %d rows', bc, len(objs))

    if run is not None:
        run.nodes_total = len(branches)
        run.nodes_ok = ok
        run.nodes_failed = failed
        run.rows_synced = total_rows
        run.detail = detail
        run.finish('success' if failed == 0 else ('partial' if ok else 'failed'))

    return {'nodes': len(branches), 'ok': ok, 'failed': failed,
            'rows': total_rows, 'detail': detail}


# ── Read side: report + KPI summary over the mirror ───────────────────────────

def _expiry_tier(days):
    if days is None:
        return None
    if days < 0:
        return 'expired'
    if days <= 30:
        return 'critical'
    if days <= 90:
        return 'high'
    if days <= 180:
        return 'watch'
    return 'ok'


def stock_expiry_report(mode='near', within_days=180, branch_codes=None,
                        store_codes=None, exp_from=None, exp_to=None,
                        include_quarantine=False, imported_only=False,
                        fridge_only=False, medicine_type=None, sort=None, limit=3000):
    """
    Per-item near-expiry / expired report over the StockExpiryBalance mirror,
    enriched with economics + attributes (reuses the audit's item map).

    mode : 'near' (today … today+within_days) | 'expired' (< today) |
           'range' (expiry between exp_from … exp_to — the active on-hand batch
           expiry) | 'all'.
    store_codes : optional list of storecodes (HQ/branch warehouses) to include.
    Rows are the per-batch mirror rows filtered by expiry, then aggregated per item
    (so total_qty / batch_count / earliest-latest reflect only the matching batches).
    """
    import datetime as _d
    from django.db.models import Sum, Min, Max, Count
    from .models import StockExpiryBalance
    from .expiry_audit import _item_attr_map

    today = _d.date.today()
    qs = StockExpiryBalance.objects.all()
    if not include_quarantine:
        qs = qs.filter(is_quarantine=False)
    if branch_codes:
        qs = qs.filter(branch_code__in=list(branch_codes))
    if store_codes:
        qs = qs.filter(store_code__in=list(store_codes))
    if mode == 'expired':
        qs = qs.filter(expiry_date__lt=today)
    elif mode == 'near':
        qs = qs.filter(expiry_date__gte=today,
                       expiry_date__lte=today + _d.timedelta(days=int(within_days)))
    elif mode == 'range':
        if exp_from:
            qs = qs.filter(expiry_date__gte=exp_from)
        if exp_to:
            qs = qs.filter(expiry_date__lte=exp_to)
    # mode == 'all' → no expiry filter

    agg = (qs.values('item_code')
             .annotate(total_qty=Sum('qty'), earliest=Min('expiry_date'),
                       latest=Max('expiry_date'), batch_count=Count('id')))
    per = {r['item_code']: r for r in agg}
    if not per:
        return []

    codes = list(per.keys())
    # branches / stores per item
    br_by_item, st_by_item = {}, {}
    for ic, bc in qs.values_list('item_code', 'branch_code').distinct():
        br_by_item.setdefault(ic, set()).add(bc)
    for ic, sc in qs.values_list('item_code', 'store_code').distinct():
        if sc:
            st_by_item.setdefault(ic, set()).add(sc)
    names = dict(qs.exclude(item_name='').values_list('item_code', 'item_name').distinct())
    attrs = _item_attr_map(codes)

    out = []
    for ic, r in per.items():
        a = attrs.get(ic, {})
        if imported_only and not a.get('is_imported'):
            continue
        if fridge_only and not a.get('is_fridge'):
            continue
        if medicine_type and a.get('medicine_type') != medicine_type:
            continue
        qf = float(r['total_qty'] or 0)
        unit_cost = a.get('unit_cost')
        earliest = r['earliest']
        d2e = (earliest - today).days if earliest else None
        var = round(qf * unit_cost, 2) if unit_cost else None
        out.append({
            'item_code':   ic,
            'item_name':   names.get(ic, '') or a.get('name', ''),
            'total_qty':   qf,
            'batch_count': r['batch_count'],
            'branches':    sorted(br_by_item.get(ic, [])),
            'stores':      sorted(st_by_item.get(ic, [])),
            'earliest_expiry': earliest.isoformat() if earliest else None,
            'latest_expiry':   r['latest'].isoformat() if r['latest'] else None,
            'days_to_expiry':  d2e,
            'tier':        _expiry_tier(d2e),
            'unit_cost':   unit_cost,
            'pack_price':  a.get('pack_price'),
            'value_at_risk': var,
            'is_imported': a.get('is_imported', False),
            'is_fridge':   a.get('is_fridge', False),
            'origin':      a.get('origin', ''),
            'medicine_type': a.get('medicine_type', ''),
            'producer':    a.get('producer', ''),
        })

    key = sort or ('value_at_risk' if mode != 'expired' else 'total_qty')
    if key == 'expiry':
        out.sort(key=lambda x: (x['earliest_expiry'] or '9999-12-31', x['item_code']))
    else:
        out.sort(key=lambda x: (x.get(key) is None, -(x.get(key) or 0), x['item_code']))
    return out[:int(limit)]


def stock_expiry_stores(branch_codes=None):
    """Distinct (branch_code, store_code) present in the mirror — powers the store
    filter dropdown. Returns [{branch_code, store_code, is_quarantine}]."""
    from .models import StockExpiryBalance
    qs = StockExpiryBalance.objects.all()
    if branch_codes:
        qs = qs.filter(branch_code__in=list(branch_codes))
    seen = {}
    for bc, sc, quar in qs.values_list('branch_code', 'store_code', 'is_quarantine').distinct():
        seen[(bc, sc)] = quar
    return sorted(
        [{'branch_code': bc, 'store_code': sc, 'is_quarantine': bool(seen[(bc, sc)])}
         for (bc, sc) in seen],
        key=lambda x: (x['branch_code'], x['store_code']),
    )


def stock_expiry_summary(branch_codes=None, store_codes=None, include_quarantine=False):
    """KPI cards for the FEFO tabs, from the mirror: value-at-risk + counts by band."""
    import datetime as _d
    from django.db.models import Sum, Count
    from .models import StockExpiryBalance
    from .expiry_audit import _item_attr_map

    today = _d.date.today()
    base = StockExpiryBalance.objects.all()
    if not include_quarantine:
        base = base.filter(is_quarantine=False)
    if branch_codes:
        base = base.filter(branch_code__in=list(branch_codes))
    if store_codes:
        base = base.filter(store_code__in=list(store_codes))

    def band(d_from, d_to):
        q = base.filter(expiry_date__gte=today + _d.timedelta(days=d_from),
                        expiry_date__lt=today + _d.timedelta(days=d_to))
        agg = q.aggregate(qty=Sum('qty'), items=Count('item_code', distinct=True))
        codes = list(q.values_list('item_code', flat=True).distinct())
        attrs = _item_attr_map(codes)
        # value at risk needs per-item qty × cost
        val = 0.0
        for row in q.values('item_code').annotate(qq=Sum('qty')):
            uc = attrs.get(row['item_code'], {}).get('unit_cost') or 0
            val += float(row['qq'] or 0) * uc
        return {'items': agg['items'] or 0, 'qty': float(agg['qty'] or 0),
                'value': round(val, 2)}

    expired_q = base.filter(expiry_date__lt=today)
    exp_codes = list(expired_q.values_list('item_code', flat=True).distinct())
    exp_attrs = _item_attr_map(exp_codes)
    exp_val = 0.0
    for row in expired_q.values('item_code').annotate(qq=Sum('qty')):
        uc = exp_attrs.get(row['item_code'], {}).get('unit_cost') or 0
        exp_val += float(row['qq'] or 0) * uc

    b30, b90, b180 = band(0, 30), band(30, 90), band(90, 180)
    return {
        'lt_30':  b30,
        'lt_90':  b90,
        'lt_180': b180,
        'expired': {'items': expired_q.values('item_code').distinct().count(),
                    'qty': float(expired_q.aggregate(q=Sum('qty'))['q'] or 0),
                    'value': round(exp_val, 2)},
        'total_at_risk_value': round(b30['value'] + b90['value'] + b180['value'], 2),
    }
