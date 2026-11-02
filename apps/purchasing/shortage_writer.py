"""
apps/purchasing/shortage_writer.py

Writes the market-shortage flag back to SOFTECH, mirroring exactly what the ERP
item card does when you tick صنف نواقص and type a تحذير:

    UPDATE SOFTECHDB9.dbo.items
       SET itemmodified = '1'|'0',        -- صنف نواقص checkbox
           itemcode_alt2 = <warning|''>,  -- تحذير free text
           usercode = ?, itemlastupdate = GETDATE()
     WHERE itemcode = ?

itemlastupdate = GETDATE() makes SSB9 replicate the row to every branch (same path
the discount module uses). Confirm → flag on + warning text; revert → flag off +
clear the warning.

OFFLINE-SAFE: the caller sets the desired state locally (Item.in_shortage) and marks
Item.shortage_softech_synced = False. push_item() tries the write immediately; if
SOFTECH is unreachable it just leaves the item unsynced and a scheduled retry
(sync_pending / manage.py sync_shortage_softech) pushes it later. Nothing is lost.

Guarded by settings.SHORTAGE_SOFTECH_WRITE_ENABLED (default False) so it stays local
until validated on the TEST host with the demo item.
"""
import logging
from django.conf import settings
from config.writers import writer_allowed
from django.utils import timezone

logger = logging.getLogger(__name__)

SHORTAGE_FLAG_COL = 'itemmodified'    # صنف نواقص
WARNING_COL       = 'itemcode_alt2'   # تحذير
SUPPLY_COL        = 'itemnomoreuse'   # أوامر التوريد ('1' = موقوف)
DEFAULT_WARNING   = 'نقص بالسوق'      # written to تحذير on confirm
# dismiss reasons that suspend SOFTECH ordering (أوامر التوريد → موقوف)
SUSPEND_REASONS   = ('on_request', 'obsolete')


def _enabled():
    return writer_allowed('SHORTAGE_SOFTECH_WRITE_ENABLED')


def _usercode():
    return getattr(settings, 'ERP_SERVICE_USERCODE', '') or '00001'


def _warning_text():
    return getattr(settings, 'SHORTAGE_WARNING_TEXT', DEFAULT_WARNING)


def _cp1256_out(s: str) -> str:
    """
    Encode Arabic for SOFTECH over the default (iso_1) connection: cp1256 bytes
    reinterpreted as latin-1 chars, so the driver ships the exact cp1256 bytes the
    server stores. Mirrors the read-side latin-1→cp1256 decode in config.sybase.
    """
    if not s:
        return s
    return s.encode('cp1256', 'replace').decode('latin-1')


def _desired_state(item):
    """
    Compute the SOFTECH state this module wants for the item, from its local state:
      on_shortage — صنف نواقص (itemmodified) + تحذير text
      suspend     — أوامر التوريد (itemnomoreuse) → موقوف, or restore, or leave alone (None)
    """
    on_shortage = bool(item.in_shortage)
    if item.shortage_dismissed and item.shortage_dismiss_reason in SUSPEND_REASONS:
        suspend = True
    elif item.shortage_supply_suspended:      # we had suspended it; item no longer on-request → restore
        suspend = False
    else:
        suspend = None                        # don't touch أوامر التوريد
    return on_shortage, suspend


class ShortageItemMissing(Exception):
    """The item code is not in SOFTECH HQ (renamed / deleted) — nothing was written."""


def _read_state(cur, itemcode):
    cur.execute(f"SELECT {SHORTAGE_FLAG_COL}, {WARNING_COL}, {SUPPLY_COL} "
                f"FROM SOFTECHDB9.dbo.items WHERE itemcode = ?", [str(itemcode)])
    r = cur.fetchone()
    if not r:
        return None
    return {SHORTAGE_FLAG_COL: str(r[0] or '0').strip() or '0',
            WARNING_COL: str(r[1] or ''),
            SUPPLY_COL: str(r[2] or '0').strip() or '0'}


def _write_softech(itemcode: str, on_shortage: bool, suspend, before=None):
    """
    One surgical UPDATE on SOFTECH HQ, between a read and a verify on the same
    connection. Only touches the fields this module owns:
      itemmodified (صنف نواقص) — '1' on shortage; on clear, the value SOFTECH had
        before we first changed it (`before`), not a fixed '0';
      itemcode_alt2 (تحذير) — set on shortage, cleared only if it still equals OUR text;
      itemnomoreuse (أوامر التوريد) — only when suspend is not None; a restore puts
        back the value from `before`.
    Returns (prev, now) — SOFTECH's values just before and just after the write.
    Raises ShortageItemMissing when the item is not there, RuntimeError when the
    re-read does not show what was written.
    """
    from config.sybase import get_sybase_connection
    before = before or {}
    warning = _cp1256_out(_warning_text())   # Arabic → cp1256-bytes-as-latin1
    flag = '1' if on_shortage else before.get(SHORTAGE_FLAG_COL, '0')
    sets = [f"{SHORTAGE_FLAG_COL} = ?"]
    params = [flag]
    if on_shortage:
        sets.append(f"{WARNING_COL} = ?"); params.append(warning)
    else:   # clear the warning ONLY if it's still ours
        sets.append(f"{WARNING_COL} = CASE WHEN {WARNING_COL} = ? THEN '' ELSE {WARNING_COL} END")
        params.append(warning)
    supply = None
    if suspend is not None:
        supply = '1' if suspend else before.get(SUPPLY_COL, '0')
        sets.append(f"{SUPPLY_COL} = ?"); params.append(supply)
    params += [_usercode(), str(itemcode)]
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        prev = _read_state(cur, itemcode)
        if prev is None:
            raise ShortageItemMissing(f'الصنف {itemcode} غير موجود فى سوفتك — لم يُكتب شىء')
        cur.execute(
            f"UPDATE SOFTECHDB9.dbo.items SET {', '.join(sets)}, "
            f"usercode = ?, itemlastupdate = GETDATE() WHERE itemcode = ?",
            params,
        )
        conn.commit()
        now = _read_state(cur, itemcode) or {}
        if now.get(SHORTAGE_FLAG_COL) != flag or (supply is not None and now.get(SUPPLY_COL) != supply):
            raise RuntimeError(f'سوفتك لا يعرض القيمة المكتوبة للصنف {itemcode}: {now}')
        return prev, now
    finally:
        try:
            conn.close()
        except Exception:
            pass


def push_item(item, actor=None) -> bool:
    """
    Best-effort push of this item's desired state (item.in_shortage) to SOFTECH.
    Updates the item's sync-state fields. Returns True if SOFTECH now matches.
    Never raises — an offline SOFTECH just leaves the item queued (synced=False).
    """
    if not _enabled():
        # Writer disabled → treat as "local only"; don't mark unsynced forever.
        return False
    on_shortage, suspend = _desired_state(item)
    was_suspended = item.shortage_supply_suspended
    before = item.shortage_softech_before
    try:
        prev, now = _write_softech(item.softech_id, on_shortage, suspend, before)
    except Exception as exc:
        item.shortage_softech_synced = False
        item.shortage_softech_error = str(exc)[:300]
        item.save(update_fields=['shortage_softech_synced', 'shortage_softech_error'])
        logger.warning('[SHORTAGE-WRITE] queued %s (%s): %s', item.softech_id,
                       'missing in SOFTECH' if isinstance(exc, ShortageItemMissing) else 'SOFTECH unavailable',
                       str(exc)[:120])
        return False
    from core.softech_audit import audit_softech_write          # who / real before→after (P-16, W2)
    keys = (SHORTAGE_FLAG_COL, SUPPLY_COL)
    audit_softech_write('softech_shortage_written', actor=actor, obj=item,
                        before={**{k: prev.get(k) for k in keys}, 'supply_suspended_by_us': was_suspended},
                        after={**{k: now.get(k) for k in keys}, 'on_shortage': on_shortage, 'suspend': suspend},
                        softech_id=item.softech_id, retry=actor is None)
    # remember whether أوامر التوريد is currently suspended by us (for later restore)
    if suspend is True:
        item.shortage_supply_suspended = True
    elif suspend is False:
        item.shortage_supply_suspended = False
    # keep SOFTECH's own values from before our FIRST change; forget them once we no
    # longer hold the item (not on shortage and not suspended by us)
    if on_shortage or item.shortage_supply_suspended:
        if item.shortage_softech_before is None:
            item.shortage_softech_before = {k: prev.get(k) for k in keys}
    else:
        item.shortage_softech_before = None
    item.shortage_softech_synced = True
    item.shortage_softech_synced_at = timezone.now()
    item.shortage_softech_error = ''
    item.save(update_fields=['shortage_softech_synced', 'shortage_softech_synced_at',
                             'shortage_softech_error', 'shortage_supply_suspended',
                             'shortage_softech_before'])
    logger.info('[SHORTAGE-WRITE] pushed %s → نواقص=%s موقوف=%s (was %s)',
                item.softech_id, on_shortage, suspend, prev)
    return True


def mark_dirty(item):
    """Mark an item as needing a SOFTECH push (call after changing in_shortage)."""
    if item.shortage_softech_synced:
        item.shortage_softech_synced = False
        item.save(update_fields=['shortage_softech_synced'])


def sync_pending(limit=500) -> dict:
    """
    Retry every item whose local state hasn't reached SOFTECH. Called by the
    scheduled command. Returns a small summary.
    """
    from apps.catalog.models import Item
    if not _enabled():
        return {'enabled': False, 'pushed': 0, 'failed': 0, 'pending': 0}
    pending = list(Item.objects.filter(shortage_softech_synced=False).order_by('id')[:limit])
    pushed = failed = 0
    for it in pending:
        if push_item(it):
            pushed += 1
        else:
            failed += 1
    remaining = Item.objects.filter(shortage_softech_synced=False).count()
    logger.info('[SHORTAGE-WRITE] sync_pending pushed=%d failed=%d remaining=%d',
                pushed, failed, remaining)
    return {'enabled': True, 'pushed': pushed, 'failed': failed, 'pending': remaining}
