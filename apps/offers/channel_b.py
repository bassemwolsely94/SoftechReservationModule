"""
apps/offers/channel_b.py — write our offer into SOFTECH's NATIVE promo table
(`specialoffers`), so gift / spend-threshold / single-item-percent promos run at
the cashier automatically, as a legitimate native offer with a real `offersno`
serial (this is what resolves the "orphan discount, no serial" worry).

Schema verified live 2026-08-30 (`investigate_promo_table`):
  specialoffers(branchcode, specialoffer_startdate, specialoffer_finishdate,
    specialoffertype, specialoffer_itemcode, itemqty_from, itemqty_to,
    bonus_itemcode, bonus_itemqty, offer_by_percent, offersno, classifcode,
    offer_lastupdate, storecode, producercode)
  specialoffertype: 1 = خصم خاص على صنف (percent on item),
                    2 = صنف بونص على صنف (buy item → bonus item),
                    3 = صنف بونص على إجمالي مبيعات (spend range → bonus item).

PLANNER is PG-only (dry-run). The INSERT is a SEPARATE gated step
(POS_OFFERS_PROMO_WRITE_ENABLED, default OFF) + confirm + linked usercode, mirroring
Channel A. Nothing writes to SOFTECH until all gates pass.
"""
from datetime import datetime, timedelta

from django.conf import settings

from .targeting import resolve_offer_items

# our offer_type → native specialoffertype. VERIFIED from real rows (offer 6457):
# the type integers do NOT match the screen's dropdown order —
#   1 = صنف بونص على صنف (buy item → bonus item; bonus is FREE, offer_by_percent='0')
#   2 = خصم خاص على صنف  (special discount %, the % is stored in ITEMQTY_FROM, not offer_by_percent)
#   3 = بونص على إجمالي مبلغ (spend from-to range → bonus item)
# offer_by_percent is a percent(0)/amount(1) FLAG, always '0' in the data → keep '0'.
_TYPE_MAP = {'gift': 1, 'spend_threshold': 3, 'percent': 2}
_FAR_FUTURE = datetime(2099, 12, 31)


def promo_write_enabled():
    return bool(getattr(settings, 'POS_OFFERS_PROMO_WRITE_ENABLED', False))


def is_channel_b_eligible(offer):
    t = offer.offer_type
    if t not in _TYPE_MAP:
        return False, 'النوع لا يُطبَّق عبر جدول عروض سوفتك (فقط هدية/مكافأة مبلغ/خصم صنف واحد)'
    if t in ('gift', 'spend_threshold') and not offer.gift_item_id:
        return False, 'يجب تحديد صنف الهدية'
    if t == 'spend_threshold' and not offer.min_basket_amount:
        return False, 'يجب تحديد حد المبلغ (min_basket_amount)'
    # native bonus is FREE-only; a partial gift (2nd at 50%) can't be a native promo.
    if t == 'gift' and float(offer.get_discount_percent or 0) != 100:
        return False, 'عرض الهدية الأصلي يدعم الهدية المجانية فقط (100%) — الجزئي يبقى عبر نقطة البيع'
    return True, ''


def _dates(offer):
    start = offer.starts_at or datetime.now()
    finish = offer.ends_at or _FAR_FUTURE
    return start.strftime('%Y-%m-%d'), finish.strftime('%Y-%m-%d')


def plan_channel_b(offer, *, branch_id=None):
    """Dry-run: the exact specialoffers row(s) we'd write. Reads PG only."""
    ok, why = is_channel_b_eligible(offer)
    if not ok:
        return {'eligible': False, 'reason': why, 'rows': []}

    stype = _TYPE_MAP[offer.offer_type]
    start, finish = _dates(offer)
    branchcode = '-1'   # all branches (v1; per-branch would be one row each)
    base = {
        'specialoffertype': stype, 'branchcode': branchcode,
        'specialoffer_startdate': start, 'specialoffer_finishdate': finish,
        'itemqty_from': 0, 'itemqty_to': 0, 'specialoffer_itemcode': '0',
        'bonus_itemcode': '0', 'bonus_itemqty': 0, 'offer_by_percent': '0',
        'classifcode': '', 'storecode': '', 'producercode': '',
    }
    rows, extra_items, notes = [], [], []

    if offer.offer_type == 'gift':
        gift = offer.gift_item
        triggers = list(resolve_offer_items(offer, branch_id=branch_id)
                        .exclude(id=offer.gift_item_id).values_list('softech_id', flat=True))
        if not triggers:
            return {'eligible': False, 'reason': 'لا أصناف تحفيز (الشراء)', 'rows': []}
        head, *rest = triggers
        # type 1 = buy `itemqty_from` of the item → get `bonus_itemqty` of bonus FREE.
        rows.append({**base, 'specialoffer_itemcode': head,
                     'itemqty_from': int(offer.buy_qty or 1), 'itemqty_to': 0,
                     'bonus_itemcode': gift.softech_id, 'bonus_itemqty': int(offer.get_qty or 1),
                     'offer_by_percent': '0'})
        extra_items = rest   # → specialoffersitems (additional trigger items)
        if rest:
            notes.append(f'{len(rest)} صنف تحفيز إضافي → specialoffersitems')

    elif offer.offer_type == 'spend_threshold':
        gift = offer.gift_item
        rows.append({**base, 'specialoffer_itemcode': '0',
                     'itemqty_from': float(offer.min_basket_amount),
                     'itemqty_to': 999999.0,   # ≥ threshold (native stores a from-to range)
                     'bonus_itemcode': gift.softech_id, 'bonus_itemqty': int(offer.get_qty or 1)})
        notes.append('itemqty_from/to يمثّلان مدى المبلغ؛ الحد الأعلى مفتوح (999999)')

    elif offer.offer_type == 'percent':
        items = list(resolve_offer_items(offer, branch_id=branch_id).values_list('softech_id', flat=True))
        if len(items) != 1:
            return {'eligible': False,
                    'reason': f'خصم النسبة عبر جدول العروض يدعم صنفًا واحدًا فقط (وجد {len(items)}) — استخدم قناة posdiscp للمجموعات',
                    'rows': []}
        code = items[0]
        # type 2 = special discount %, with the PERCENT stored in itemqty_from
        # (verified on offer 6457: 25% → itemqty_from=25, offer_by_percent='0'=percent-mode).
        rows.append({**base, 'specialoffer_itemcode': code, 'bonus_itemcode': '0',
                     'itemqty_from': float(offer.value or 0), 'itemqty_to': 0, 'bonus_itemqty': 0,
                     'offer_by_percent': '0'})
        notes.append('نسبة الخصم مخزّنة في itemqty_from (وضع نسبة مئوية offer_by_percent=0)')

    return {'eligible': True, 'offer_id': offer.id, 'softech_type': stype,
            'rows': rows, 'extra_items': extra_items, 'notes': notes}


def apply_channel_b(offer, *, actor=None, commit=False, confirm=False):
    """
    Gated live INSERT into specialoffers(+specialoffersitems). Four gates (like
    Channel A): flag + commit + confirm + linked SOFTECH usercode. Otherwise returns
    the dry-run plan only.
    """
    plan = plan_channel_b(offer)
    if not plan['eligible']:
        return {'applied': False, 'plan': plan}
    if not (commit and promo_write_enabled()):
        return {'applied': False, 'enabled': promo_write_enabled(), 'plan': plan,
                'detail': 'تخطيط فقط — الكتابة إلى جدول عروض سوفتك مُقيَّدة بمفتاح.'}
    if not confirm:
        return {'applied': False, 'requires_confirm': True, 'plan': plan}
    uc = (getattr(actor, 'softech_user_id', '') or '').strip()
    if not uc:
        return {'applied': False, 'error': 'no_softech_user', 'plan': plan}
    return _write_specialoffer(plan, uc)


def _write_specialoffer(plan, usercode):
    """Live INSERT — called ONLY after all four gates pass. Read-back verified."""
    from config.sybase import get_sybase_connection

    conn = get_sybase_connection()
    cur = conn.cursor()
    written = []
    try:
        cur.execute('SELECT ISNULL(MAX(offersno),0) FROM SOFTECHDB9.dbo.specialoffers')
        offersno = int(cur.fetchone()[0]) + 1
        for row in plan['rows']:
            cols = ('branchcode, specialoffer_startdate, specialoffer_finishdate, specialoffertype, '
                    'specialoffer_itemcode, itemqty_from, itemqty_to, bonus_itemcode, bonus_itemqty, '
                    'offer_by_percent, offersno, offer_lastupdate, storecode, producercode, classifcode')
            cur.execute(
                f'INSERT INTO SOFTECHDB9.dbo.specialoffers ({cols}) '
                f'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, GETDATE(), ?, ?, ?)',
                [row['branchcode'], row['specialoffer_startdate'], row['specialoffer_finishdate'],
                 row['specialoffertype'], row['specialoffer_itemcode'], row['itemqty_from'],
                 row['itemqty_to'], row['bonus_itemcode'], row['bonus_itemqty'],
                 row['offer_by_percent'], offersno, row['storecode'], row['producercode'],
                 row['classifcode']])
            for code in plan.get('extra_items', []):
                cur.execute(
                    'INSERT INTO SOFTECHDB9.dbo.specialoffersitems '
                    '(offersno, itemcode, itemtype, usercode, trans_time) VALUES (?, ?, 1, ?, GETDATE())',
                    [offersno, code, str(usercode)])
            cur.execute('SELECT COUNT(*) FROM SOFTECHDB9.dbo.specialoffers WHERE offersno = ?', [offersno])
            ok = int(cur.fetchone()[0]) > 0
            written.append({'offersno': offersno, 'ok': ok})
            offersno += 1
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {'applied': True, 'written': written}
