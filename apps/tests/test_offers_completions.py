"""
apps/tests/test_offers_completions.py — near-completion hints ("this offer can be completed with
another item"). Read-only: a near-miss offer adds NO discount, only a `completions[]` entry telling
the cashier what to add. A reject that a cashier CAN'T fix (wrong channel/segment) must NOT appear.
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


class CompletionHintTests(TestCase):
    def test_bxgy_needs_one_more(self):
        # buy 2 get 1 → a full group is 3 units; with 2, one more completes it
        t = _item('T')
        o = offer(name='2+1', offer_type='bxgy', buy_qty=2, get_qty=1, get_discount_percent=100)
        o.items.add(t)
        plan = evaluate_offers([line(t, 2, 50)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))
        self.assertEqual(len(plan['completions']), 1)
        c = plan['completions'][0]
        self.assertEqual(c['offer_id'], o.id)
        self.assertEqual(c['need'], 1)   # 3 − 2

    def test_bxgy_met_no_completion(self):
        # a full group of 3 (buy 2 + get 1) applies the discount → no completion
        t = _item('T')
        o = offer(name='2+1', offer_type='bxgy', buy_qty=2, get_qty=1, get_discount_percent=100)
        o.items.add(t)
        plan = evaluate_offers([line(t, 3, 50)], offers=[o])
        self.assertGreater(plan['total_discount'], Decimal('0'))
        self.assertEqual(plan['completions'], [])

    def test_qty_tier_needs_more_for_first_tier(self):
        t = _item('T')
        o = offer(name='tiers', offer_type='qty_tier',
                  qty_tiers=[{'min_qty': 3, 'percent': 5}, {'min_qty': 6, 'percent': 10}])
        o.items.add(t)
        plan = evaluate_offers([line(t, 2, 50)], offers=[o])
        self.assertEqual(len(plan['completions']), 1)
        self.assertEqual(plan['completions'][0]['need'], 1)   # 3 − 2

    def test_spend_threshold_gap(self):
        t = _item('T')
        g = _item('G', pos_discp=100)
        o = offer(name='spend500', offer_type='spend_threshold',
                  min_basket_amount=Decimal('500'), gift_item=g)
        o.items.add(t)
        plan = evaluate_offers([line(t, 1, 300)], offers=[o])   # basket 300 < 500
        self.assertEqual(len(plan['completions']), 1)
        self.assertIn('200', plan['completions'][0]['message'])  # spend 200 more

    def test_bundle_missing_member(self):
        a = _item('A')
        b = _item('B')
        o = offer(name='bundle AB', offer_type='bundle', bundle_price=Decimal('80'))
        o.items.add(a, b)
        plan = evaluate_offers([line(a, 1, 60)], offers=[o])    # only A present
        self.assertEqual(len(plan['completions']), 1)
        self.assertIn('B', plan['completions'][0]['message'])

    def test_wrong_channel_is_not_completable(self):
        t = _item('T')
        o = offer(name='2+1 cash-only', offer_type='bxgy', buy_qty=2, get_qty=1,
                  get_discount_percent=100, channels=['cash'])
        o.items.add(t)
        plan = evaluate_offers([line(t, 1, 50)], offers=[o], channel='home_delivery')
        # wrong channel → rejected, but adding items can't fix it → NO completion hint
        self.assertEqual(plan['completions'], [])

    def test_no_qualifying_items_no_completion(self):
        t = _item('T')
        other = _item('X')
        o = offer(name='2+1', offer_type='bxgy', buy_qty=2, get_qty=1, get_discount_percent=100)
        o.items.add(t)
        plan = evaluate_offers([line(other, 1, 50)], offers=[o])   # offer item not in basket
        self.assertEqual(plan['completions'], [])
