"""
apps/offers/channel_a.py — flat-rate offer → item posdiscp (Channel A).

For a FLAT-RATE percent offer (a plain "these items are X% off"), resolve its
target items via the flexible selector and compute the posdiscp change each item
needs. This is the only offer shape that maps to posdiscp, because posdiscp is
UNCONDITIONAL (it discounts every unit of that item on every cashier sale) —
buy-X-get-Y conditions stay on the indirect POS (Channel C).

This module is a PLANNER (dry-run, PG-only): it reads the synced `Item.pos_discp`
mirror and returns the diff. The LIVE write (reuse `discount_approvals` items-UPDATE
→ SSB9 replication) is a SEPARATE gated step (A2), guarded by
POS_OFFERS_POSDISCP_WRITE_ENABLED + owner sign-off + a readback. Nothing here
writes to SOFTECH.
"""
from decimal import Decimal

from django.conf import settings

from .targeting import resolve_offer_items


def write_enabled():
    return bool(getattr(settings, 'POS_OFFERS_POSDISCP_WRITE_ENABLED', False))


def is_channel_a_eligible(offer):
    """
    Only a FLAT-RATE percent offer maps to posdiscp. Fixed-amount can't (posdiscp
    is a %); conditional types (bxgy/gift/bundle/mix_match/spend) need the POS.
    """
    if offer.offer_type != 'percent':
        return False, 'نوع العرض لا يُطبَّق عبر posdiscp (فقط النسبة المئوية الثابتة)'
    v = Decimal(str(offer.value or 0))
    if v <= 0 or v > 100:
        return False, 'نسبة غير صالحة (0 < value ≤ 100)'
    return True, ''


def plan_posdiscp(offer, *, branch_id=None):
    """
    Dry-run: the exact posdiscp changes this flat-rate offer implies. Reads the PG
    mirror only; writes nothing. Returns {eligible, target, changes[], summary}.
    """
    ok, why = is_channel_a_eligible(offer)
    if not ok:
        return {'eligible': False, 'reason': why, 'changes': [], 'summary': {}}

    new_pct = Decimal(str(offer.value)).quantize(Decimal('0.01'))
    items = (resolve_offer_items(offer, branch_id=branch_id)
             .only('id', 'softech_id', 'name', 'pos_discp'))

    changes, unchanged = [], 0
    for it in items.iterator(chunk_size=2000):
        current = Decimal(str(it.pos_discp or 0)).quantize(Decimal('0.01'))
        if current == new_pct:
            unchanged += 1
            continue
        changes.append({
            'item_id': it.id, 'softech_id': it.softech_id, 'name': it.name,
            'current_posdiscp': float(current), 'new_posdiscp': float(new_pct),
            'delta': float(new_pct - current),
        })

    return {
        'eligible': True,
        'offer_id': offer.id, 'offer_name': offer.name_ar or offer.name,
        'target_percent': float(new_pct),
        'require_stock': offer.require_stock,
        'changes': changes,
        'summary': {'to_change': len(changes), 'unchanged': unchanged,
                    'total_targeted': len(changes) + unchanged},
    }


def revert_plan(offer, *, restore_to=Decimal('0'), branch_id=None):
    """Dry-run of restoring posdiscp (e.g. offer ended) back to `restore_to`."""
    items = resolve_offer_items(offer, branch_id=branch_id).only('id', 'softech_id', 'name', 'pos_discp')
    target = Decimal(str(restore_to)).quantize(Decimal('0.01'))
    changes = []
    for it in items.iterator(chunk_size=2000):
        cur = Decimal(str(it.pos_discp or 0)).quantize(Decimal('0.01'))
        if cur != target:
            changes.append({'item_id': it.id, 'softech_id': it.softech_id, 'name': it.name,
                            'current_posdiscp': float(cur), 'new_posdiscp': float(target)})
    return {'changes': changes, 'summary': {'to_change': len(changes)}}


def _actor_usercode(actor):
    """The author's SOFTECH usercode (stamped on items.usercode). None if unlinked."""
    uc = (getattr(actor, 'softech_user_id', '') or '').strip()
    return uc or None


def apply_posdiscp(offer, *, actor=None, commit=False, confirm=False):
    """
    A2 — the LIVE Channel-A write, GATED four ways so it can never fire by accident:
      1. settings.POS_OFFERS_POSDISCP_WRITE_ENABLED (default False)
      2. commit=True (caller intent)
      3. confirm=True (anti-fat-finger token from the UI)
      4. the actor has a linked SOFTECH usercode (author stamp)
    Without all four it returns the dry-run plan and writes NOTHING. The write itself
    mirrors discount_approvals.alignment: UPDATE items.posdiscp + usercode +
    itemlastupdate=GETDATE() → SSB9 replicates HQ→branches, read-back verified per
    item, PG mirror updated only on a verified write.
    """
    plan = plan_posdiscp(offer)
    if not plan['eligible']:
        return {'applied': False, 'plan': plan}
    if not (commit and write_enabled()):
        return {'applied': False, 'enabled': write_enabled(), 'plan': plan,
                'detail': 'تخطيط فقط — كتابة posdiscp إلى سوفتك مُقيَّدة بمفتاح.'}
    if not confirm:
        return {'applied': False, 'requires_confirm': True, 'plan': plan}
    usercode = _actor_usercode(actor)
    if not usercode:
        return {'applied': False, 'error': 'no_softech_user', 'plan': plan,
                'detail': 'يجب ربط رقم المستخدم في سوفتك بحسابك أولاً.'}

    results = _write_posdiscp(plan['changes'], usercode)
    written = sum(1 for r in results if r.get('ok'))
    return {'applied': True, 'written': written, 'total': len(results),
            'results': results[:500], 'offer_id': offer.id}


def _write_posdiscp(changes, usercode):
    """
    Live SOFTECH write of items.posdiscp (HQ → SSB9 replicates). Read-back verified;
    PG Item.pos_discp updated only when SOFTECH confirms. Called ONLY from
    apply_posdiscp after all four gates pass — never at import/eval time.
    """
    from config.sybase import get_sybase_connection
    from apps.catalog.models import Item

    results = []
    conn = get_sybase_connection()
    cur = conn.cursor()
    try:
        for c in changes:
            code = c['softech_id']
            new = float(c['new_posdiscp'])
            try:
                cur.execute(
                    'UPDATE SOFTECHDB9.dbo.items SET posdiscp = ?, usercode = ?, '
                    'itemlastupdate = GETDATE() WHERE itemcode = ?',
                    [new, str(usercode), code])
                cur.execute('SELECT posdiscp FROM SOFTECHDB9.dbo.items WHERE itemcode = ?', [code])
                row = cur.fetchone()
                ok = bool(row) and abs(float(row[0] or 0) - new) < 0.005
                if ok:
                    Item.objects.filter(id=c['item_id']).update(pos_discp=new)
                results.append({'softech_id': code, 'ok': ok,
                                'posdiscp': new, **({} if ok else {'error': 'readback mismatch'})})
            except Exception as e:   # per-item isolation — one failure doesn't abort the batch
                results.append({'softech_id': code, 'ok': False, 'error': str(e)[:200]})
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return results
