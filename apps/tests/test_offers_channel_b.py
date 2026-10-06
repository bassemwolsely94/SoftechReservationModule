"""
apps/tests/test_offers_channel_b.py

Channel B — write our offer into SOFTECH's native `specialoffers` promo table.
PLANNER is PG-only (dry-run) mapping our offer → the native row; the INSERT is
gated four ways. Schema verified live: type 2=gift, 3=spend, 1=percent. No SOFTECH
contact in tests.
"""
from decimal import Decimal
from django.test import TestCase, override_settings

from apps.offers.models import Offer
from apps.offers.channel_b import is_channel_b_eligible, plan_channel_b, apply_channel_b
from .factories import make_item, make_user


def _item(code):
    return make_item(name=code, softech_id=code)


def _offer(**kw):
    kw.setdefault('require_stock', False)
    return Offer.objects.create(status='active', **kw)


class EligibilityTests(TestCase):
    def test_gift_needs_gift_item(self):
        o = _offer(name='g', offer_type='gift')
        self.assertFalse(is_channel_b_eligible(o)[0])

    def test_bxgy_not_eligible(self):
        o = _offer(name='b', offer_type='bxgy')
        self.assertFalse(is_channel_b_eligible(o)[0])


class GiftPlanTests(TestCase):
    def setUp(self):
        self.trigger = _item('TRIG')
        self.gift = _item('GIFT')

    def test_gift_maps_to_type1_free(self):
        o = _offer(name='buy2 get GIFT', offer_type='gift', buy_qty=2, get_qty=1,
                   get_discount_percent=100, gift_item=self.gift)
        o.items.add(self.trigger)
        plan = plan_channel_b(o)
        self.assertTrue(plan['eligible'])
        self.assertEqual(plan['softech_type'], 1)          # bonus-item = native type 1
        row = plan['rows'][0]
        self.assertEqual(row['specialoffer_itemcode'], 'TRIG')
        self.assertEqual(row['itemqty_from'], 2)           # buy qty
        self.assertEqual(row['bonus_itemcode'], 'GIFT')
        self.assertEqual(row['bonus_itemqty'], 1)
        self.assertEqual(row['offer_by_percent'], '0')     # bonus is free

    def test_partial_gift_not_native(self):
        o = _offer(name='buy1 get 50% off GIFT', offer_type='gift', buy_qty=1, get_qty=1,
                   get_discount_percent=50, gift_item=self.gift)
        o.items.add(self.trigger)
        self.assertFalse(plan_channel_b(o)['eligible'])    # partial → Channel C only

    def test_extra_trigger_items_go_to_items_table(self):
        t2 = _item('TRIG2')
        o = _offer(name='g', offer_type='gift', buy_qty=1, get_qty=1, gift_item=self.gift)
        o.items.add(self.trigger, t2)
        plan = plan_channel_b(o)
        self.assertEqual(len(plan['extra_items']), 1)     # one goes to specialoffersitems


class SpendPlanTests(TestCase):
    def test_spend_maps_to_type3(self):
        gift = _item('GIFT')
        o = _offer(name='spend100 get GIFT', offer_type='spend_threshold', target_all=True,
                   min_basket_amount=Decimal('100'), get_qty=1, gift_item=gift)
        plan = plan_channel_b(o)
        self.assertEqual(plan['softech_type'], 3)
        row = plan['rows'][0]
        self.assertEqual(row['specialoffer_itemcode'], '0')
        self.assertEqual(row['itemqty_from'], 100.0)      # amount range
        self.assertEqual(row['bonus_itemcode'], 'GIFT')


class PercentPlanTests(TestCase):
    def test_single_item_percent_maps_to_type2(self):
        it = _item('ONE')
        o = _offer(name='ONE 25%', offer_type='percent', value=Decimal('25'))
        o.items.add(it)
        plan = plan_channel_b(o)
        self.assertEqual(plan['softech_type'], 2)              # special-discount = native type 2
        self.assertEqual(plan['rows'][0]['itemqty_from'], 25.0)  # % lives in itemqty_from
        self.assertEqual(plan['rows'][0]['offer_by_percent'], '0')

    def test_multi_item_percent_rejected(self):
        a, b = _item('A'), _item('B')
        o = _offer(name='2 items 25%', offer_type='percent', value=Decimal('25'))
        o.items.add(a, b)
        plan = plan_channel_b(o)
        self.assertFalse(plan['eligible'])                # use Channel A (posdiscp) for groups


class GateTests(TestCase):
    def setUp(self):
        self.gift = _item('GIFT'); self.trig = _item('TRIG')
        self.o = _offer(name='g', offer_type='gift', buy_qty=1, get_qty=1, gift_item=self.gift)
        self.o.items.add(self.trig)

    def test_flag_off_writes_nothing(self):
        res = apply_channel_b(self.o, commit=True)
        self.assertFalse(res['applied'])
        self.assertIn('plan', res)

    @override_settings(POS_OFFERS_PROMO_WRITE_ENABLED=True)
    def test_flag_on_needs_confirm(self):
        res = apply_channel_b(self.o, commit=True, confirm=False)
        self.assertTrue(res['requires_confirm'])

    @override_settings(POS_OFFERS_PROMO_WRITE_ENABLED=True)
    def test_flag_on_confirm_no_usercode_blocked(self):
        _, profile, _ = make_user('cb_admin', role='admin')   # no softech_user_id
        res = apply_channel_b(self.o, actor=profile, commit=True, confirm=True)
        self.assertEqual(res['error'], 'no_softech_user')


class ApiTests(TestCase):
    def test_promo_plan_endpoint(self):
        gift, trig = _item('GIFT'), _item('TRIG')
        o = _offer(name='g', offer_type='gift', buy_qty=1, get_qty=1, gift_item=gift)
        o.items.add(trig)
        _, _, admin = make_user('cb_admin2', role='admin')
        r = admin.get(f'/api/offers/{o.id}/promo-plan/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['softech_type'], 1)   # gift = native type 1
