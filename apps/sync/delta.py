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
_MODES = ('off', 'shadow')


def stock_mode():
    """off | shadow. `on` is not built: it needs 7 days of SHADOW with 0 misses + owner sign-off (S2)."""
    mode = str(getattr(settings, 'SYNC_DELTA_STOCK', 'off') or 'off').strip().lower()
    if mode == 'on':
        logger.error('SYNC_DELTA_STOCK=on is not built yet (doc 40 S2) — running as shadow')
        return 'shadow'
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
