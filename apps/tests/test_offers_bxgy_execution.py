"""
apps/tests/test_offers_bxgy_execution.py

Phase-3 Step 1 (PG-only, NO SOFTECH writes): the real offer mechanic —
cross-item "cheapest-unit" BXGY where the discount MAGNITUDE is the item card's
posdiscp (a genuine 1+1 = items with posdiscp=100), plus the dry-run attach
service that converts the plan to per-line cust_discp and reconciles it against
SOFTECH's own line math.
"""
from decimal import Decimal
from django.test import TestCase

from apps.offers.models import Offer
from apps.offers.engine import evaluate_offers
from apps.offers.attach import build_attach_plan, cust_discp_for
from .factories import make_item


def item(code, pos_discp):
    it = make_item(name=code, softech_id=code)
    it.pos_discp = Decimal(str(pos_discp))
    it.save(update_fields=['pos_discp'])
    return it


def bxgy(**kw):
    d = dict(name='BXGY', offer_type='bxgy', status='active', target_all=True,
             buy_qty=1, get_qty=1, bxgy_scope='group_cheapest',
             authorization_source='item_card', require_stock=False)
    d.update(kw)
    return Offer.objects.create(**d)


def line(it, qty, price):
    return {'softech_id': it.softech_id, 'item': it, 'qty': qty, 'unit_price': price}


class CrossItemCheapestTests(TestCase):
    def test_one_plus_one_free_cheaper_unit(self):
        a = item('A', 100)   # posdiscp 100 → a genuine 1+1
        b = item('B', 100)
        o = bxgy()
        # buy A@100 + B@60 → cheaper (B) is free (100% of its posdiscp)
        plan = evaluate_offers([line(a, 1, 100), line(b, 1, 60)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('60.00'))
        # the discount lands on B's line (index 1), not A
        disc_lines = {l['index']: l['discount'] for l in plan['applied'][0]['lines']}
        self.assertEqual(disc_lines.get(1), Decimal('60.00'))
        self.assertNotIn(0, disc_lines)

    def test_one_plus_half_uses_posdiscp_50(self):
        a = item('A', 50)    # posdiscp 50 → "1 + ½ off the 2nd"
        b = item('B', 50)
        o = bxgy()
        plan = evaluate_offers([line(a, 1, 100), line(b, 1, 60)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('30.00'))   # 50% of cheaper 60

    def test_magnitude_is_per_item_posdiscp(self):
        # the promo (cheaper) unit is discounted at ITS OWN posdiscp
        a = item('A', 100)
        b = item('B', 20)    # cheaper item authorizes only 20%
        o = bxgy()
        plan = evaluate_offers([line(a, 1, 100), line(b, 1, 60)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('12.00'))   # 20% of 60

    def test_multi_group_two_cheapest_free(self):
        a = item('A', 100)
        o = bxgy()
        # four units of one item @ [40] each, 1+1 → 2 groups → 2 promo units free
        plan = evaluate_offers([line(a, 4, 40)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('80.00'))   # 2 × 40 free

    def test_incomplete_group_no_discount(self):
        a = item('A', 100)
        o = bxgy()   # need 2 units, only 1
        plan = evaluate_offers([line(a, 1, 50)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))


class SameItemScopeTests(TestCase):
    def test_same_item_buy2get1(self):
        a = item('A', 100)
        o = bxgy(bxgy_scope='same_item', buy_qty=2, get_qty=1)
        plan = evaluate_offers([line(a, 3, 50)], offers=[o])   # 1 free unit
        self.assertEqual(plan['total_discount'], Decimal('50.00'))


class OfferModeTests(TestCase):
    def test_offer_mode_uses_offer_percent_and_needs_approval(self):
        a = item('A', 0)     # item card authorizes 0 …
        b = item('B', 0)
        o = bxgy(authorization_source='offer', get_discount_percent=100)  # … offer overrides
        plan = evaluate_offers([line(a, 1, 100), line(b, 1, 60)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('60.00'))  # 100% of cheaper, from offer
        self.assertTrue(plan['requires_approval'])

    def test_item_card_mode_no_approval(self):
        a = item('A', 100); b = item('B', 100)
        o = bxgy()   # item_card
        plan = evaluate_offers([line(a, 1, 100), line(b, 1, 60)], offers=[o])
        self.assertFalse(plan['requires_approval'])


class ItemCardCapTests(TestCase):
    def test_percent_offer_capped_at_posdiscp(self):
        a = item('A', 10)    # item card authorizes only 10%
        o = Offer.objects.create(name='P', offer_type='percent', status='active',
                                 target_all=True, value=50, authorization_source='item_card')
        plan = evaluate_offers([line(a, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('10.00'))   # 50% capped to 10%


class AttachReconciliationTests(TestCase):
    def test_cust_discp_conversion_rounds_customer_favour(self):
        # 33.335% → 2dp HALF_UP = 33.34 (favours customer)
        self.assertEqual(cust_discp_for(Decimal('33.335'), Decimal('100')), Decimal('33.34'))

    def test_attach_reconciles_softech_math(self):
        a = item('A', 100); b = item('B', 100)
        bxgy()   # 1+1
        basket = [line(a, 1, 100), line(b, 1, 60)]
        out = build_attach_plan(basket)
        # B's line gets cust_discp 100 → SOFTECH discount = 60, delta 0
        bline = out['lines'][1]
        self.assertEqual(bline['cust_discp'], Decimal('100.00'))
        self.assertEqual(bline['softech_discount'], Decimal('60.00'))
        self.assertEqual(out['reconciliation']['max_line_delta'], Decimal('0.00'))
        self.assertTrue(out['dry_run'])

    def test_blended_line_reconciles(self):
        # 2 units same item @33, 1 promo (posdiscp 100) → eng 33, cust_discp 50%,
        # SOFTECH: 33×(1-0.5)=16.5 ×2 = 33 net → discount 33, delta 0
        a = item('A', 100)
        bxgy()
        out = build_attach_plan([line(a, 2, 33)])
        self.assertEqual(out['lines'][0]['cust_discp'], Decimal('50.00'))
        self.assertEqual(out['lines'][0]['softech_discount'], Decimal('33.00'))
        self.assertLessEqual(out['reconciliation']['max_line_delta'], Decimal('0.01'))

    def test_rounding_delta_within_tolerance(self):
        # gross 100, promo cheaper unit 100% at posdiscp 100 but with an odd price
        a = item('A', 100); b = item('B', 100)
        bxgy()
        out = build_attach_plan([line(a, 1, 100), line(b, 1, 33.33)])
        self.assertLessEqual(out['reconciliation']['max_line_delta'], Decimal('0.01'))


class AttachApiTests(TestCase):
    def test_attach_preview_is_dry_run(self):
        from .factories import make_user
        item('A', 100); item('B', 100)
        bxgy()
        _, _, client = make_user('attach_user', role='pharmacist')
        r = client.post('/api/offers/evaluate/', {
            'basket': [{'softech_id': 'A', 'qty': 1, 'unit_price': 100},
                       {'softech_id': 'B', 'qty': 1, 'unit_price': 60}],
            'attach_preview': True,
        }, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['dry_run'])
        self.assertIn('reconciliation', r.data)
        self.assertEqual(r.data['lines'][1]['cust_discp'], 100.0)   # cheaper unit free
