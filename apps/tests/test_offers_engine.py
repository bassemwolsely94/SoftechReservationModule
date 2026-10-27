"""
apps/tests/test_offers_engine.py

MONEY-MATH lock for the Phase-3 offers engine. Every offer type, every gate, and
the conflict-resolution rules are pinned here so a refactor can never silently
change a discount. Deterministic; no SOFTECH; no persistence.
"""
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from apps.offers.models import Offer
from apps.offers.engine import evaluate_offers
from apps.catalog.models import Category, ItemTag
from .factories import make_item, make_branch, make_customer, make_user


def mk_offer(offer_type='percent', **kw):
    # These tests validate the RAW per-type magnitude math, so they use offer-mode
    # (magnitude = the offer's own value/get%). item_card-mode capping vs posdiscp
    # is covered separately in test_offers_bxgy_execution.
    defaults = dict(name=f'O-{offer_type}', offer_type=offer_type, status='active',
                    value=0, authorization_source='offer', bxgy_scope='same_item',
                    require_stock=False)
    defaults.update(kw)
    return Offer.objects.create(**defaults)


def line(item, qty, price):
    return {'softech_id': item.softech_id, 'item': item, 'qty': qty, 'unit_price': price}


class PercentTests(TestCase):
    def setUp(self):
        self.it = make_item(name='A', softech_id='PA1')

    def test_basic_percent(self):
        o = mk_offer('percent', value=10, target_all=True)
        plan = evaluate_offers([line(self.it, 2, 100)], offers=[o])
        self.assertEqual(plan['basket_total'], Decimal('200.00'))
        self.assertEqual(plan['total_discount'], Decimal('20.00'))
        self.assertEqual(plan['net_total'], Decimal('180.00'))

    def test_percent_with_cap(self):
        o = mk_offer('percent', value=50, target_all=True, max_discount_amount=Decimal('30'))
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('30.00'))   # 50 capped to 30

    def test_percent_cap_distributes_across_lines(self):
        a = make_item(name='A', softech_id='PA2')
        b = make_item(name='B', softech_id='PA3')
        o = mk_offer('percent', value=50, target_all=True, max_discount_amount=Decimal('40'))
        plan = evaluate_offers([line(a, 1, 100), line(b, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('40.00'))


class FixedTests(TestCase):
    def setUp(self):
        self.it = make_item(name='A', softech_id='FX1')

    def test_basic_fixed(self):
        o = mk_offer('fixed', value=25, target_all=True)
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('25.00'))

    def test_fixed_capped_at_subtotal(self):
        o = mk_offer('fixed', value=500, target_all=True)
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('100.00'))   # never below zero net


class BxgyTests(TestCase):
    def setUp(self):
        self.it = make_item(name='A', softech_id='BX1')

    def test_buy2get1_free(self):
        # buy 2 get 1 free, qty 3 → 1 free unit @50 = 50 off
        o = mk_offer('bxgy', target_all=True, buy_qty=2, get_qty=1, get_discount_percent=100)
        plan = evaluate_offers([line(self.it, 3, 50)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('50.00'))

    def test_partial_group_no_discount(self):
        o = mk_offer('bxgy', target_all=True, buy_qty=2, get_qty=1, get_discount_percent=100)
        plan = evaluate_offers([line(self.it, 2, 50)], offers=[o])   # only 2, need 3
        self.assertEqual(plan['total_discount'], Decimal('0.00'))

    def test_get_at_half_off(self):
        o = mk_offer('bxgy', target_all=True, buy_qty=1, get_qty=1, get_discount_percent=50)
        # qty 4 → 2 groups of (1+1), 2 discounted units @ 50% of 50 = 25*2 = 50
        plan = evaluate_offers([line(self.it, 4, 50)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('50.00'))


class QtyTierTests(TestCase):
    def setUp(self):
        self.it = make_item(name='A', softech_id='QT1')

    def test_tier_selected_by_qty(self):
        o = mk_offer('qty_tier', target_all=True,
                     qty_tiers=[{'min_qty': 3, 'percent': 5}, {'min_qty': 6, 'percent': 10}])
        # qty 6 → 10% of 600 = 60
        plan = evaluate_offers([line(self.it, 6, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('60.00'))

    def test_below_first_tier_no_discount(self):
        o = mk_offer('qty_tier', target_all=True, qty_tiers=[{'min_qty': 3, 'percent': 5}])
        plan = evaluate_offers([line(self.it, 2, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))


class TargetingTests(TestCase):
    def setUp(self):
        self.cat = Category.objects.create(softech_id='C1', name='Cat')
        self.a = make_item(name='A', softech_id='TG1')
        self.a.category = self.cat
        self.a.save(update_fields=['category'])
        self.b = make_item(name='B', softech_id='TG2')

    def test_specific_item_only(self):
        o = mk_offer('percent', value=10)
        o.items.add(self.a)
        plan = evaluate_offers([line(self.a, 1, 100), line(self.b, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('10.00'))   # only A

    def test_category_targeting(self):
        o = mk_offer('percent', value=10)
        o.categories.add(self.cat)
        plan = evaluate_offers([line(self.a, 1, 100), line(self.b, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('10.00'))   # only A (in cat)

    def test_tag_targeting(self):
        tag = ItemTag.objects.create(slug='promo', name='Promo')
        self.b.tags.add(tag)
        o = mk_offer('percent', value=20)
        o.tags.add(tag)
        plan = evaluate_offers([line(self.a, 1, 100), line(self.b, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('20.00'))   # only B (tagged)


class EligibilityTests(TestCase):
    def setUp(self):
        self.it = make_item(name='A', softech_id='EL1')
        self.branch = make_branch()

    def test_inactive_offer_ignored(self):
        o = mk_offer('percent', value=10, target_all=True, status='paused')
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))
        self.assertEqual(plan['applied'], [])

    def test_window_not_started(self):
        o = mk_offer('percent', value=10, target_all=True,
                     starts_at=timezone.now() + timedelta(days=1))
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))

    def test_segment_gate(self):
        vip = make_customer(name='V', phone='0100'); vip.segment = 'vip'; vip.save()
        reg = make_customer(name='R', phone='0200'); reg.segment = 'regular'; reg.save()
        o = mk_offer('percent', value=10, target_all=True, segments=['vip'])
        self.assertEqual(evaluate_offers([line(self.it, 1, 100)], customer=reg, offers=[o])['total_discount'], Decimal('0.00'))
        self.assertEqual(evaluate_offers([line(self.it, 1, 100)], customer=vip, offers=[o])['total_discount'], Decimal('10.00'))

    def test_min_basket_gate(self):
        o = mk_offer('percent', value=10, target_all=True, min_basket_amount=Decimal('500'))
        self.assertEqual(evaluate_offers([line(self.it, 1, 100)], offers=[o])['total_discount'], Decimal('0.00'))
        self.assertEqual(evaluate_offers([line(self.it, 6, 100)], offers=[o])['total_discount'], Decimal('60.00'))

    def test_branch_gate(self):
        other = make_branch(name='Other', softech_id='B99')
        o = mk_offer('percent', value=10, target_all=True)
        o.branches.add(self.branch)
        self.assertEqual(evaluate_offers([line(self.it, 1, 100)], branch_id=other.id, offers=[o])['total_discount'], Decimal('0.00'))
        self.assertEqual(evaluate_offers([line(self.it, 1, 100)], branch_id=self.branch.id, offers=[o])['total_discount'], Decimal('10.00'))


class ConflictTests(TestCase):
    def setUp(self):
        self.it = make_item(name='A', softech_id='CF1')

    def test_two_nonstackable_best_wins(self):
        low = mk_offer('percent', value=10, target_all=True, stackable=False, priority=1)
        high = mk_offer('fixed', value=30, target_all=True, stackable=False, priority=1)
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[low, high])
        self.assertEqual(plan['total_discount'], Decimal('30.00'))   # best saving
        self.assertEqual(len(plan['applied']), 1)
        self.assertEqual(len(plan['rejected']), 1)

    def test_stackable_combine(self):
        a = mk_offer('percent', value=10, target_all=True, stackable=True)
        b = mk_offer('fixed', value=5, target_all=True, stackable=True)
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[a, b])
        self.assertEqual(plan['total_discount'], Decimal('15.00'))   # 10 + 5

    def test_stack_beats_single_nonstack_when_bigger(self):
        s1 = mk_offer('percent', value=10, target_all=True, stackable=True)
        s2 = mk_offer('percent', value=10, target_all=True, stackable=True)
        ns = mk_offer('fixed', value=15, target_all=True, stackable=False)
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[s1, s2, ns])
        self.assertEqual(plan['total_discount'], Decimal('20.00'))   # 10+10 > 15

    def test_single_nonstack_beats_smaller_stack(self):
        s1 = mk_offer('percent', value=5, target_all=True, stackable=True)
        ns = mk_offer('fixed', value=40, target_all=True, stackable=False)
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[s1, ns])
        self.assertEqual(plan['total_discount'], Decimal('40.00'))

    def test_per_line_cap_never_below_zero(self):
        # two stackable offers that together exceed the line gross → cap at gross
        a = mk_offer('percent', value=70, target_all=True, stackable=True)
        b = mk_offer('percent', value=70, target_all=True, stackable=True)
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[a, b])
        self.assertEqual(plan['total_discount'], Decimal('100.00'))   # not 140
        self.assertEqual(plan['net_total'], Decimal('0.00'))


class DeterminismTests(TestCase):
    def test_same_input_same_plan(self):
        it = make_item(name='A', softech_id='DT1')
        offers = [mk_offer('percent', value=10, target_all=True, stackable=True),
                  mk_offer('fixed', value=5, target_all=True, stackable=True)]
        b = [line(it, 2, 100)]
        p1 = evaluate_offers(b, offers=offers)
        p2 = evaluate_offers(b, offers=offers)
        self.assertEqual(p1['total_discount'], p2['total_discount'])
        self.assertEqual([a['offer_id'] for a in p1['applied']],
                         [a['offer_id'] for a in p2['applied']])


class ApiTests(TestCase):
    def test_evaluate_endpoint(self):
        it = make_item(name='A', softech_id='AP1')
        mk_offer('percent', value=10, target_all=True)
        _, _, client = make_user('offer_user', role='pharmacist')
        r = client.post('/api/offers/evaluate/',
                        {'basket': [{'softech_id': 'AP1', 'qty': 1, 'unit_price': 100}]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['total_discount'], 10.0)

    def test_offer_create_gated(self):
        _, _, viewer = make_user('offer_viewer', role='viewer')
        r = viewer.post('/api/offers/', {'name': 'X', 'offer_type': 'percent', 'value': 10}, format='json')
        self.assertEqual(r.status_code, 403)
        _, _, admin = make_user('offer_admin', role='admin')
        r2 = admin.post('/api/offers/', {'name': 'X', 'offer_type': 'percent', 'value': 10}, format='json')
        self.assertEqual(r2.status_code, 201)
