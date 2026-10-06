"""
apps/tests/test_offers_new_types.py

The four new Odoo-level offer types (PG-only, deterministic, no SOFTECH):
gift item, spend-threshold reward, bundle fixed price, mix & match.
"""
from decimal import Decimal
from django.test import TestCase

from apps.offers.models import Offer
from apps.offers.engine import evaluate_offers
from .factories import make_item


def _item(code, pos_discp=0):
    it = make_item(name=code, softech_id=code)
    it.pos_discp = Decimal(str(pos_discp))
    it.save(update_fields=['pos_discp'])
    return it


def line(it, qty, price):
    return {'softech_id': it.softech_id, 'item': it, 'qty': qty, 'unit_price': price}


def offer(**kw):
    kw.setdefault('status', 'active')
    kw.setdefault('require_stock', False)
    kw.setdefault('authorization_source', 'offer')
    return Offer.objects.create(**kw)


class GiftItemTests(TestCase):
    def setUp(self):
        self.tgt = _item('T')
        self.gift = _item('Z', pos_discp=100)

    def test_gift_free_when_in_basket(self):
        o = offer(name='buy2 get Z', offer_type='gift', buy_qty=2, get_qty=1,
                  get_discount_percent=100, gift_item=self.gift)
        o.items.add(self.tgt)
        plan = evaluate_offers([line(self.tgt, 2, 50), line(self.gift, 1, 30)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('30.00'))   # Z (30) free

    def test_gift_not_in_basket_suggests_it(self):
        o = offer(name='buy2 get Z', offer_type='gift', buy_qty=2, get_qty=1,
                  get_discount_percent=100, gift_item=self.gift)
        o.items.add(self.tgt)
        plan = evaluate_offers([line(self.tgt, 2, 50)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))
        self.assertEqual(len(plan['suggestions']), 1)
        self.assertEqual(plan['suggestions'][0]['item_id'], self.gift.id)
        self.assertEqual(plan['suggestions'][0]['qty'], 1)

    def test_condition_not_met_no_gift(self):
        o = offer(name='buy2 get Z', offer_type='gift', buy_qty=2, get_qty=1,
                  get_discount_percent=100, gift_item=self.gift)
        o.items.add(self.tgt)
        plan = evaluate_offers([line(self.tgt, 1, 50), line(self.gift, 1, 30)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))   # only bought 1, need 2

    def test_item_card_gift_uses_gift_posdiscp(self):
        o = offer(name='g', offer_type='gift', buy_qty=1, get_qty=1,
                  gift_item=self.gift, authorization_source='item_card')
        o.items.add(self.tgt)
        plan = evaluate_offers([line(self.tgt, 1, 50), line(self.gift, 1, 30)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('30.00'))   # gift posdiscp=100


class SpendThresholdTests(TestCase):
    def setUp(self):
        self.tgt = _item('T')
        self.gift = _item('Z')

    def test_free_gift_over_threshold(self):
        o = offer(name='spend100 get Z', offer_type='spend_threshold', target_all=True,
                  min_basket_amount=Decimal('100'), get_discount_percent=100, gift_item=self.gift)
        plan = evaluate_offers([line(self.tgt, 1, 120), line(self.gift, 1, 30)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('30.00'))

    def test_below_threshold_nothing(self):
        o = offer(name='spend100 get Z', offer_type='spend_threshold', target_all=True,
                  min_basket_amount=Decimal('100'), get_discount_percent=100, gift_item=self.gift)
        plan = evaluate_offers([line(self.tgt, 1, 50), line(self.gift, 1, 30)], offers=[o])  # 80 < 100
        self.assertEqual(plan['total_discount'], Decimal('0.00'))


class BundleTests(TestCase):
    def setUp(self):
        self.a = _item('A'); self.b = _item('B')

    def test_bundle_fixed_price(self):
        o = offer(name='A+B for 70', offer_type='bundle', bundle_price=Decimal('70'))
        o.items.add(self.a, self.b)
        plan = evaluate_offers([line(self.a, 1, 50), line(self.b, 1, 40)], offers=[o])  # 90 → 70
        self.assertEqual(plan['total_discount'], Decimal('20.00'))

    def test_missing_member_no_bundle(self):
        o = offer(name='A+B for 70', offer_type='bundle', bundle_price=Decimal('70'))
        o.items.add(self.a, self.b)
        plan = evaluate_offers([line(self.a, 1, 50)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))

    def test_bundle_not_cheaper_no_discount(self):
        o = offer(name='A+B for 100', offer_type='bundle', bundle_price=Decimal('100'))
        o.items.add(self.a, self.b)
        plan = evaluate_offers([line(self.a, 1, 50), line(self.b, 1, 40)], offers=[o])  # 90 < 100
        self.assertEqual(plan['total_discount'], Decimal('0.00'))


class MixMatchTests(TestCase):
    def setUp(self):
        self.a = _item('A'); self.b = _item('B'); self.c = _item('C')

    def test_any_n_cheapest_discounted(self):
        o = offer(name='any 2 = 20%', offer_type='mix_match', min_qty=2, value=Decimal('20'))
        o.items.add(self.a, self.b, self.c)
        # cheapest 2 of {10,20,30} = 10,20 at 20% = 2 + 4 = 6
        plan = evaluate_offers([line(self.a, 1, 10), line(self.b, 1, 20), line(self.c, 1, 30)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('6.00'))

    def test_below_n_nothing(self):
        o = offer(name='any 2 = 20%', offer_type='mix_match', min_qty=2, value=Decimal('20'))
        o.items.add(self.a, self.b, self.c)
        plan = evaluate_offers([line(self.a, 1, 10)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))

    def test_two_sets(self):
        o = offer(name='any 2 = 50%', offer_type='mix_match', min_qty=2, value=Decimal('50'))
        o.items.add(self.a, self.b, self.c)
        # 4 units → 2 sets → cheapest 4 discounted 50%
        plan = evaluate_offers([line(self.a, 2, 10), line(self.b, 2, 20)], offers=[o])
        # units [10,10,20,20], all 4 promo, 50% → (10+10+20+20)*0.5 = 30
        self.assertEqual(plan['total_discount'], Decimal('30.00'))
