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
from django.utils import timezone

logger = logging.getLogger(__name__)

SHORTAGE_FLAG_COL = 'itemmodified'    # صنف نواقص
WARNING_COL       = 'itemcode_alt2'   # تحذير
SUPPLY_COL        = 'itemnomoreuse'   # أوامر التوريد ('1' = موقوف)
DEFAULT_WARNING   = 'نقص بالسوق'      # written to تحذير on confirm
# dismiss reasons that suspend SOFTECH ordering (أوامر التوريد → موقوف)
SUSPEND_REASONS   = ('on_request', 'obsolete')


def _enabled():
    return bool(getattr(settings, 'SHORTAGE_SOFTECH_WRITE_ENABLED', False))


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


def _write_softech(itemcode: str, on_shortage: bool, suspend):
    """
    One surgical UPDATE on SOFTECH HQ. Only touches the fields this module owns:
    itemmodified (صنف نواقص) always; itemcode_alt2 (تحذير) — set on shortage, and on
    clear only if it still equals OUR warning (never clobber a manual warning);
    itemnomoreuse (أوامر التوريد) only when suspend is not None. Raises on any error.
    """
    from config.sybase import get_sybase_connection
    warning = _cp1256_out(_warning_text())   # Arabic → cp1256-bytes-as-latin1
    sets = [f"{SHORTAGE_FLAG_COL} = ?"]
    params = ['1' if on_shortage else '0']
    if on_shortage:
        sets.append(f"{WARNING_COL} = ?"); params.append(warning)
    else:   # clear the warning ONLY if it's still ours
        sets.append(f"{WARNING_COL} = CASE WHEN {WARNING_COL} = ? THEN '' ELSE {WARNING_COL} END")
        params.append(warning)
    if suspend is not None:
        sets.append(f"{SUPPLY_COL} = ?"); params.append('1' if suspend else '0')
    params += [_usercode(), str(itemcode)]
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE SOFTECHDB9.dbo.items SET {', '.join(sets)}, "
            f"usercode = ?, itemlastupdate = GETDATE() WHERE itemcode = ?",
            params,
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def push_item(item) -> bool:
    """
    Best-effort push of this item's desired state (item.in_shortage) to SOFTECH.
    Updates the item's sync-state fields. Returns True if SOFTECH now matches.
    Never raises — an offline SOFTECH just leaves the item queued (synced=False).
    """
    if not _enabled():
        # Writer disabled → treat as "local only"; don't mark unsynced forever.
        return False
    on_shortage, suspend = _desired_state(item)
    try:
        _write_softech(item.softech_id, on_shortage, suspend)
    except Exception as exc:
        item.shortage_softech_synced = False
        item.shortage_softech_error = str(exc)[:300]
        item.save(update_fields=['shortage_softech_synced', 'shortage_softech_error'])
        logger.warning('[SHORTAGE-WRITE] queued %s (SOFTECH unavailable): %s',
                       item.softech_id, str(exc)[:120])
        return False
    # remember whether أوامر التوريد is currently suspended by us (for later restore)
    if suspend is True:
        item.shortage_supply_suspended = True
    elif suspend is False:
        item.shortage_supply_suspended = False
    item.shortage_softech_synced = True
    item.shortage_softech_synced_at = timezone.now()
    item.shortage_softech_error = ''
    item.save(update_fields=['shortage_softech_synced', 'shortage_softech_synced_at',
                             'shortage_softech_error', 'shortage_supply_suspended'])
    logger.info('[SHORTAGE-WRITE] pushed %s → نواقص=%s موقوف=%s',
                item.softech_id, on_shortage, suspend)
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
