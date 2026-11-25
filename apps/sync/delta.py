"""
apps/sync/delta.py — SOFTECH delta sync, SHADOW mode (doc 40 §3, §4.1, §6.1).

Read-only against SOFTECH. In `shadow` the full read (sync_stock) still writes exactly as today; this module
then runs a small "rows stamped since the watermark" read and records which real changes it would have
missed. It never writes a row it reads. `off` (the default) does nothing here.

Watermark rules (§3.1): a SOFTECH-side stamp taken from the rows' own column, never our clock; reads use it
minus a 10-minute overlap with `>=`; it only moves forward. A SOFTECH maximum below the stored watermark
(clock or sequence reset) re-seeds and is noted (S6). No watermark = seed only, never a delta from nothing.
"""
import datetime
import logging
import time

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger('elrezeiky.sync')

STOCK_STREAM = 'stkbal'
OVERLAP = datetime.timedelta(minutes=10)
SAMPLE_MAX = 20
FULL_HOUR = 4          # `on`: the first fast run at/after 04:00 Cairo each day is a full read (doc 40 §3.3)
_MODES = ('off', 'shadow', 'on')


def stock_mode():
    """off | shadow | on (doc 40 §3.2). `on` is switched only after 7 clean days of SHADOW and the owner's
    sign-off (S2); the switch itself lives in the server's .env."""
    mode = str(getattr(settings, 'SYNC_DELTA_STOCK', 'off') or 'off').strip().lower()
    return mode if mode in _MODES else 'off'


def _aware(naive):
    """A SOFTECH stamp (naive Cairo time) → aware datetime for storage."""
    if naive is None:
        return None
    if timezone.is_aware(naive):
        return naive
    return timezone.make_aware(naive, timezone.get_default_timezone())


def _naive(aware):
    return timezone.localtime(aware, timezone.get_default_timezone()).replace(tzinfo=None)


def _stamp(val):
    """A stamp from the cursor (datetime, or text from the driver) → naive datetime, or None."""
    if val is None:
        return None
    if isinstance(val, datetime.datetime):
        return val.replace(tzinfo=None) if timezone.is_aware(val) else val
    try:
        return datetime.datetime.fromisoformat(str(val).strip()[:19])
    except ValueError:
        return None


def max_stamp(rows, index=6):
    stamps = [s for s in (_stamp(r[index]) for r in rows if len(r) > index) if s is not None]
    return max(stamps) if stamps else None


def shadow_stock(conn, *, changed_keys, new_keys, item_map, branch_map, full_max, rows_full, full_ms):
    """Compare one stock run's real changes with what a delta read returns. Never raises: a delta problem
    is recorded on the run and today's full sync carries on.

    changed_keys / new_keys: {(item_id, branch_id, store)} that changed / appeared this run (value change,
    sold-out zeroing, new row). item_map / branch_map: SOFTECH code → our id (as sync_stock built them).
    full_max: the largest modif_lastupdate in the full read (naive)."""
    from apps.sync.models import DeltaShadowRun, SyncWatermark
    from apps.sync.sybase_queries import QUERY_STOCK_DELTA

    now = timezone.now()
    wm, _ = SyncWatermark.objects.get_or_create(stream=STOCK_STREAM)
    wm.mode, wm.last_full_at, wm.last_full_ok = 'shadow', now, True
    stored = _naive(wm.value_ts) if wm.value_ts else None
    shadow = DeltaShadowRun(stream=STOCK_STREAM, rows_full=rows_full, rows_changed=len(changed_keys) + len(new_keys),
                            full_ms=int(full_ms), watermark_from=wm.value_ts)

    if stored is None or full_max is None:
        wm.value_ts = _aware(full_max)
        shadow.note, shadow.watermark_to = 'seed', wm.value_ts
        wm.save()
        shadow.save()
        return shadow
    # A small step back is normal: the full read only sees nowqty > 0, so when the newest-stamped row has just
    # sold out its maximum falls a little (43 s on 2026-11-22). Only a move further back than the overlap is a
    # SOFTECH clock or sequence reset (S6); within it the delta read still covers the gap.
    if full_max < stored - OVERLAP:
        logger.error('stkbal watermark moved backwards (stored %s, SOFTECH max %s) — re-seeded (doc 40 S6)',
                     stored, full_max)
        wm.value_ts = _aware(full_max)
        shadow.note = f'S6: SOFTECH max {full_max:%Y-%m-%d %H:%M:%S} < watermark {stored:%Y-%m-%d %H:%M:%S}; re-seeded'
        shadow.watermark_to = wm.value_ts
        wm.save()
        shadow.save()
        return shadow

    since = (stored - OVERLAP).strftime('%Y%m%d %H:%M:%S')
    t0 = time.monotonic()
    try:
        cur = conn.cursor()
        cur.execute(QUERY_STOCK_DELTA, [since])
        rows = cur.fetchall()
    except Exception as exc:                        # the shadow read must never break the real sync
        shadow.delta_ms = int((time.monotonic() - t0) * 1000)
        shadow.note = f'delta read error: {str(exc)[:150]}'
        logger.warning('stock delta shadow read failed: %s', exc)
        wm.save()
        shadow.save()
        return shadow
    shadow.delta_ms = int((time.monotonic() - t0) * 1000)

    delta_keys = set()
    for r in rows:
        item_id, branch_id = item_map.get(str(r[0])), branch_map.get(str(r[1]))
        if item_id and branch_id:
            delta_keys.add((item_id, branch_id, str(r[2])))
    missed = changed_keys - delta_keys
    missed_new = new_keys - delta_keys
    item_code = {v: k for k, v in item_map.items()}
    branch_code = {v: k for k, v in branch_map.items()}
    sample = sorted(f'{item_code.get(i, i)}/{branch_code.get(b, b)}/{s}' for i, b, s in missed)[:SAMPLE_MAX]

    shadow.rows_delta, shadow.missed, shadow.missed_new, shadow.missed_sample = (
        len(rows), len(missed), len(missed_new), sample)
    new_wm = max(s for s in (stored, max_stamp(rows), full_max) if s is not None)
    wm.value_ts = _aware(new_wm)
    shadow.watermark_to = wm.value_ts
    wm.last_delta_at, wm.rows_last_delta, wm.misses_last_shadow = now, len(rows), len(missed)
    wm.save()
    shadow.save()
    if missed:
        logger.warning('stock delta SHADOW missed %d changed rows (e.g. %s) — doc 40 S9', len(missed), sample[:3])
    return shadow


# ── ON mode (doc 40 §3.2–§3.4, §4.1) ─────────────────────────────────────────────────────────────────────────

def stock_full_due():
    """Why this `on` run must be a full read, or None for a delta run: 'first' (no usable watermark or the last
    full failed) or 'nightly' (no full read since the most recent 04:00 Cairo — a PC that slept through 04:00
    catches up on its first run after waking)."""
    from apps.sync.models import SyncWatermark
    wm = SyncWatermark.objects.filter(stream=STOCK_STREAM).first()
    if wm is None or wm.value_ts is None or not wm.last_full_ok or wm.last_full_at is None:
        return 'first'
    now = timezone.localtime(timezone.now(), timezone.get_default_timezone())
    boundary = now.replace(hour=FULL_HOUR, minute=0, second=0, microsecond=0)
    if now < boundary:
        boundary -= datetime.timedelta(days=1)
    return 'nightly' if wm.last_full_at < boundary else None


def delta_write_stock(conn, sync_run):
    """One `on` delta run: read the rows stamped since the watermark (minus the overlap, sold-out rows included as
    0) and write the ones that changed, with the watermark, in one transaction. Never runs the sold-out zeroing
    step. Returns rows read, or None when the caller must fall back to a full read (no watermark, read error)."""
    from django.db import transaction
    from apps.branches.models import Branch
    from apps.catalog.models import Item, ItemStock
    from apps.sync.models import SyncLog, SyncWatermark
    from apps.sync.sybase_queries import QUERY_STOCK_DELTA
    from apps.sync.tasks import _to_stock_qty

    wm = SyncWatermark.objects.filter(stream=STOCK_STREAM).first()
    if wm is None or wm.value_ts is None:
        return None
    stored = _naive(wm.value_ts)
    try:
        cur = conn.cursor()
        cur.execute(QUERY_STOCK_DELTA, [(stored - OVERLAP).strftime('%Y%m%d %H:%M:%S')])
        rows = cur.fetchall()
    except Exception as exc:
        logger.warning('stock delta read failed, falling back to a full read: %s', exc)
        return None

    item_map = {i.softech_id: i.id for i in Item.objects.only('id', 'softech_id')}
    branch_map = {b.softech_branch_id: b.id for b in Branch.objects.only('id', 'softech_branch_id')}
    snapshot = {}
    for r in rows:
        item_id, branch_id = item_map.get(str(r[0])), branch_map.get(str(r[1]))
        if item_id and branch_id:
            o = ItemStock(item_id=item_id, branch_id=branch_id, softech_store_code=str(r[2]),
                          quantity_on_hand=_to_stock_qty(r[3]), monthly_qty=_to_stock_qty(r[4]),
                          on_order_qty=_to_stock_qty(r[5]))
            snapshot[(item_id, branch_id, o.softech_store_code)] = o
    current = {}
    if snapshot:
        items = {k[0] for k in snapshot}
        branches = {k[1] for k in snapshot}
        for i, b, s, q, m, o in ItemStock.objects.filter(item_id__in=items, branch_id__in=branches).values_list(
                'item_id', 'branch_id', 'softech_store_code', 'quantity_on_hand', 'monthly_qty', 'on_order_qty'):
            current[(i, b, s)] = (q, m, o)
    changed = [o for key, o in snapshot.items()
               if (key in current and current[key] != (o.quantity_on_hand, o.monthly_qty, o.on_order_qty))
               or (key not in current and o.quantity_on_hand > 0)]
    new_max = max_stamp(rows)
    with transaction.atomic():               # the watermark moves with the rows it covers (§3.1)
        if changed:
            ItemStock.objects.bulk_create(
                changed, update_conflicts=True, unique_fields=['item', 'branch', 'softech_store_code'],
                update_fields=['quantity_on_hand', 'monthly_qty', 'on_order_qty', 'last_synced'], batch_size=1000)
        if new_max is not None and new_max > stored:
            wm.value_ts = _aware(new_max)
        wm.mode, wm.last_delta_at, wm.rows_last_delta = 'on', timezone.now(), len(rows)
        wm.save()
    SyncLog.objects.create(sync_run=sync_run, table_name='stkbal', records_processed=len(changed))
    logger.info('Stock delta: %d rows read, %d changed', len(rows), len(changed))
    return len(rows)


def record_full_on(*, reason, changed_keys, zeroed_keys, branch_map, full_max, rows_full, full_ms):
    """After a full read in `on` mode: reset the watermark from the rows' own stamps (re-seed on a real SOFTECH
    clock reset beyond the overlap, S6) and store how many rows the full read had to correct (§6.2 for ON)."""
    from apps.sync.models import StockFullCheck, SyncWatermark

    wm, _ = SyncWatermark.objects.get_or_create(stream=STOCK_STREAM)
    stored = _naive(wm.value_ts) if wm.value_ts else None
    note = ''
    if stored is not None and full_max is not None and full_max < stored - OVERLAP:
        logger.error('stkbal watermark moved backwards (stored %s, SOFTECH max %s) — re-seeded (doc 40 S6)',
                     stored, full_max)
        note = f'S6: SOFTECH max {full_max:%Y-%m-%d %H:%M:%S} < watermark {stored:%Y-%m-%d %H:%M:%S}; re-seeded'
        wm.value_ts = _aware(full_max)
    elif full_max is not None:
        wm.value_ts = _aware(max(s for s in (stored, full_max) if s is not None))
    now = timezone.now()
    wm.mode, wm.last_full_at, wm.last_full_ok = 'on', now, True
    wm.save()

    code = {v: k for k, v in branch_map.items()}
    per_branch = {}
    for key in changed_keys:
        per_branch.setdefault(str(code.get(key[1], key[1])), {'corrected': 0, 'zeroed': 0})['corrected'] += 1
    for key in zeroed_keys:
        per_branch.setdefault(str(code.get(key[1], key[1])), {'corrected': 0, 'zeroed': 0})['zeroed'] += 1
    return StockFullCheck.objects.create(
        at=now, reason=reason, rows_full=rows_full, corrected=len(changed_keys), zeroed=len(zeroed_keys),
        per_branch=per_branch, ok=not changed_keys and not zeroed_keys, full_ms=int(full_ms), note=note)
