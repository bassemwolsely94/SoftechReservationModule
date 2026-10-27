"""
apps/tests/test_offers_margin.py

Margin protection for the offers engine (Commerce-OS Phase 3). A discount that
pushes a line's margin below the configurable floor flags the plan for approval;
cost/margin fields are role-masked. Deterministic; no SOFTECH; no persistence.
"""
from decimal import Decimal
from django.test import TestCase

from apps.offers.models import Offer, MarginConfig
from apps.offers.engine import evaluate_offers
from .factories import make_item, make_user


def mk_offer(**kw):
    d = dict(name='O', offer_type='percent', status='active', value=0, target_all=True,
             require_stock=False)
    d.update(kw)
    return Offer.objects.create(**d)


def line(item, qty, price):
    return {'softech_id': item.softech_id, 'item': item, 'qty': qty, 'unit_price': price}


class MarginComputeTests(TestCase):
    def setUp(self):
        self.it = make_item(name='A', softech_id='MG1')
        self.it.cost_price = Decimal('80.00')   # sells 100 → 20% margin at full price
        self.it.pos_discp = Decimal('100.00')   # item card authorizes the offer % fully
        self.it.save(update_fields=['cost_price', 'pos_discp'])
        self.cfg = MarginConfig.get_solo()       # floor 10%, enforce True

    def test_margin_ok_no_approval(self):
        # 5% off → net 95, cogs 80 → margin (95-80)/95 = 15.8% > 10% floor
        o = mk_offer(value=5)
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o], margin_cfg=self.cfg)
        self.assertFalse(plan['margin']['breached'])
        self.assertFalse(plan['requires_approval'])

    def test_item_card_margin_breach_reported_not_gated(self):
        # item_card offers are pre-authorized by posdiscp → breach is REPORTED but
        # does NOT force approval (a real 1+1 is free by design).
        o = mk_offer(value=20)
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o], margin_cfg=self.cfg)
        self.assertTrue(plan['margin']['breached'])
        self.assertFalse(plan['requires_approval'])

    def test_offer_mode_margin_breach_requires_approval(self):
        # offer-mode magnitude is NOT authorized by the item card → breach gates.
        o = mk_offer(value=20, authorization_source='offer')
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o], margin_cfg=self.cfg)
        self.assertTrue(plan['margin']['breached'])
        self.assertTrue(plan['requires_approval'])

    def test_below_cost_is_breach(self):
        o = mk_offer(value=50)   # net 50 < cogs 80 → margin negative
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o], margin_cfg=self.cfg)
        self.assertTrue(plan['margin']['breached'])
        self.assertLess(plan['margin']['lines'][0]['margin_pct'], Decimal('0'))

    def test_enforce_false_no_gate(self):
        self.cfg.enforce = False
        self.cfg.save()
        o = mk_offer(value=50)   # would breach, but enforcement off
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o], margin_cfg=self.cfg)
        self.assertFalse(plan['margin']['breached'])
        self.assertFalse(plan['requires_approval'])

    def test_no_margin_cfg_backward_compatible(self):
        o = mk_offer(value=50)
        plan = evaluate_offers([line(self.it, 1, 100)], offers=[o])   # no cfg
        self.assertFalse(plan['margin']['breached'])
        self.assertFalse(plan['requires_approval'])


class RoleMaskingApiTests(TestCase):
    def setUp(self):
        self.it = make_item(name='A', softech_id='MG2')
        self.it.cost_price = Decimal('80.00')
        self.it.pos_discp = Decimal('100.00')   # item card authorizes the offer % fully
        self.it.save(update_fields=['cost_price', 'pos_discp'])
        mk_offer(value=20, authorization_source='offer')  # offer-mode breach → gated + masked
        MarginConfig.get_solo()
        self.body = {'basket': [{'softech_id': 'MG2', 'qty': 1, 'unit_price': 100}]}

    def test_purchasing_sees_cost(self):
        _, _, client = make_user('mg_purch', role='purchasing')
        r = client.post('/api/offers/evaluate/', self.body, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('cogs', r.data['margin']['lines'][0])
        self.assertNotIn('cost_masked', r.data['margin'])

    def test_salesperson_cost_masked(self):
        _, _, client = make_user('mg_sales', role='salesperson')
        r = client.post('/api/offers/evaluate/', self.body, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['margin'].get('cost_masked'))
        self.assertNotIn('cogs', r.data['margin']['lines'][0])
        self.assertNotIn('margin_pct', r.data['margin']['lines'][0])
        # operational signal still visible
        self.assertTrue(r.data['margin']['breached'])
        self.assertTrue(r.data['requires_approval'])


class MarginConfigApiTests(TestCase):
    def test_get(self):
        _, _, client = make_user('mc_user', role='pharmacist')
        r = client.get('/api/offers/margin-config/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('min_margin_percent', r.data)

    def test_non_admin_cannot_patch(self):
        _, _, client = make_user('mc_ph', role='supervisor')
        r = client.patch('/api/offers/margin-config/', {'min_margin_percent': 25}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_admin_patch(self):
        _, _, admin = make_user('mc_admin', role='admin')
        r = admin.patch('/api/offers/margin-config/', {'min_margin_percent': 25}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(float(r.data['min_margin_percent']), 25.0)
        self.assertEqual(float(MarginConfig.get_solo().min_margin_percent), 25.0)
