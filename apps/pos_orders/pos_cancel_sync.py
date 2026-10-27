"""
apps/pos_orders/pos_cancel_sync.py — Wave 3 inc2.

Nightly sweep of SOFTECH `pos_cancel` (the «المبيعات غير المخزنة» / lost-sale log) from every
operational node into the `PosCancelDaily` Postgres rollup — one row per (branch, day, item,
doccode). Read-only against SOFTECH; window-replace per branch so re-runs are idempotent.

Grain rationale: procurement/demand needs "how much genuine demand did we lose for item X over
period P", and trend charts need per-day series — a daily item rollup serves both while staying
tiny. Per-cashier audit + per-customer recovery stay on the live read (pos_cancel_read); this
mirror is history/trends only.
"""
import logging
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.pos_orders')

# aggregate pos_cancel to (day, doccode, itemcode). 111 = 'yyyy/mm/dd' (standard ASE style).
_AGG_SQL = (
    "SELECT convert(char(10), trans_time, 111) AS d, doccode, itemcode, max(mitemname), "
    "       count(*), sum(CASE WHEN transqty>0 THEN 1 ELSE 0 END), sum(transprice_total) "
    "  FROM pos_cancel "
    " WHERE branchcode=? AND trans_time >= ? AND itemcode IS NOT NULL AND itemcode<>'' "
    " GROUP BY convert(char(10), trans_time, 111), doccode, itemcode"
)


def _parse_day(v):
    s = str(v).strip()[:10]
    for fmt in ('%Y/%m/%d', '%Y-%m-%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _dec(v):
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(str(v or 0)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0.00')


def sync_pos_cancel_all(only_branch=None, days=30, timeout=180):
    """Sweep every operational node's pos_cancel into PosCancelDaily for the last `days`.
    Window-replace per branch (idempotent). Returns a summary dict."""
    from apps.branches.models import Branch
    from apps.catalog.models import Item
    from .models import PosCancelDaily
    from config.sybase import get_branch_connection

    since_dt = timezone.now() - timedelta(days=max(1, int(days)))
    since_s = since_dt.strftime('%Y-%m-%d %H:%M:%S')
    window_start = since_dt.date()

    qs = Branch.objects.filter(is_operational=True)
    if only_branch:
        qs = qs.filter(softech_branch_id=str(only_branch))
    branches = list(qs)

    detail, total_rows, ok, failed = {}, 0, 0, 0
    for b in branches:
        bc = b.softech_branch_id
        try:
            conn = get_branch_connection(b.effective_db_host, b.effective_db_port,
                                         b.db_name or 'SOFTECHDB9')
            try:
                cur = conn.cursor()
                cur.execute(_AGG_SQL, [str(bc), since_s], timeout=timeout)
                rows = cur.fetchall()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            failed += 1
            detail[bc] = {'ok': False, 'error': str(e)[:200]}
            logger.warning('[pos_cancel_sync] branch %s node failed: %s', bc, e)
            continue

        # resolve item FKs + full names from our catalog in one query
        codes = {str(r[2]).strip() for r in rows if r[2]}
        item_map = {str(c).strip(): (iid, nm) for c, iid, nm in
                    Item.objects.filter(softech_id__in=codes).values_list('softech_id', 'id', 'name')}

        objs = []
        for r in rows:
            day = _parse_day(r[0])
            code = str(r[2]).strip()
            if day is None or not code:
                continue
            iid, iname = item_map.get(code, (None, None))
            objs.append(PosCancelDaily(
                branch_code=bc, day=day, doccode=str(r[1] or '115').strip()[:3],
                item_id=iid, item_code=code[:6],
                item_name=(iname or (str(r[3]).strip() if r[3] else code))[:255],
                events=int(r[4] or 0),
                priced_events=int(r[5] or 0),
                lost_value=_dec(r[6]),
            ))

        with transaction.atomic():
            PosCancelDaily.objects.filter(branch_code=bc, day__gte=window_start).delete()
            PosCancelDaily.objects.bulk_create(objs, batch_size=1000)
        ok += 1
        total_rows += len(objs)
        detail[bc] = {'ok': True, 'rows': len(objs)}
        logger.info('[pos_cancel_sync] branch %s synced %d daily rows', bc, len(objs))

    return {'nodes': len(branches), 'ok': ok, 'failed': failed,
            'rows': total_rows, 'window_start': window_start.isoformat(), 'detail': detail}
