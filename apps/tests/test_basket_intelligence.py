"""
apps/tests/test_basket_intelligence.py

Basket-Intelligence / Sales-Opportunity service (Commerce-OS Phase 2): composes
FBT + customer recs + bundle completion into ONE deterministic ranked list.
Safety wins — blocked items are never suggested (rule 4). No item already in the
basket is suggested.
"""
from django.test import TestCase

from apps.customers.models import Customer
from apps.catalog.models import Item, ProductBundle, BundleItem
from apps.recommendations.models import (
    RecommendationEngineRun, FrequentlyBoughtTogether, CustomerRecommendation,
)
from apps.recommendations.basket_intelligence import basket_intelligence
from .factories import make_item, make_user


class BasketIntelligenceTests(TestCase):
    def setUp(self):
        self.run = RecommendationEngineRun.objects.create(status='success')
        self.anchor = make_item(name='Anchor', softech_id='BI1')     # in basket
        self.fbt = make_item(name='FbtRec', softech_id='BI2')
        self.personal = make_item(name='Personal', softech_id='BI3')
        self.bundle_mate = make_item(name='BundleMate', softech_id='BI4')
        self.blocked = make_item(name='Blocked', softech_id='BI5')

    def _fbt(self, a, b, score):
        return FrequentlyBoughtTogether.objects.create(
            run=self.run, item_a=a, item_b=b, item_a_occurrences=10,
            confidence=0.5, lift=1.2, score=score)

    def test_fbt_suggestion(self):
        self._fbt(self.anchor, self.fbt, 0.9)
        out = basket_intelligence(['BI1'])
        codes = [r['softech_id'] for r in out]
        self.assertIn('BI2', codes)
        self.assertIn('fbt', next(r for r in out if r['softech_id'] == 'BI2')['reasons'])

    def test_never_suggests_basket_item(self):
        self._fbt(self.anchor, self.anchor, 5.0)   # degenerate self-pair
        out = basket_intelligence(['BI1'])
        self.assertNotIn('BI1', [r['softech_id'] for r in out])

    def test_blocked_item_never_suggested(self):
        self.blocked.item_archive = True            # blocks_sale → True
        self.blocked.save(update_fields=['item_archive'])
        self._fbt(self.anchor, self.blocked, 9.0)   # highest score, but blocked
        out = basket_intelligence(['BI1'])
        self.assertNotIn('BI5', [r['softech_id'] for r in out])

    def test_personal_rec_ranks_above_fbt(self):
        self._fbt(self.anchor, self.fbt, 0.4)
        cust = Customer.objects.create(name='C', phone='0111')
        CustomerRecommendation.objects.create(
            run=self.run, customer=cust, item=self.personal, score=0.4, is_chronic_related=False)
        out = basket_intelligence(['BI1'], customer_id=cust.id)
        self.assertEqual(out[0]['softech_id'], 'BI3')   # personal weight beats fbt

    def test_bundle_completion(self):
        b = ProductBundle.objects.create(name='B')
        BundleItem.objects.create(bundle=b, item=self.anchor, quantity=1)
        BundleItem.objects.create(bundle=b, item=self.bundle_mate, quantity=1)
        out = basket_intelligence(['BI1'])
        row = next((r for r in out if r['softech_id'] == 'BI4'), None)
        self.assertIsNotNone(row)
        self.assertIn('bundle', row['reasons'])

    def test_deterministic_order(self):
        self._fbt(self.anchor, self.fbt, 0.9)
        self._fbt(self.anchor, self.bundle_mate, 0.3)
        out1 = [r['softech_id'] for r in basket_intelligence(['BI1'])]
        out2 = [r['softech_id'] for r in basket_intelligence(['BI1'])]
        self.assertEqual(out1, out2)

    def test_api(self):
        self._fbt(self.anchor, self.fbt, 0.9)
        _, _, client = make_user('bi_user', role='pharmacist')
        r = client.get('/api/recommendations/basket-intel/', {'items': 'BI1'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('BI2', [x['softech_id'] for x in r.data['results']])


class SegmentWeightingTests(TestCase):
    """VIP/loyal → premium cross-sell ranked up; at-risk → own repeat items ranked up."""

    def setUp(self):
        self.run = RecommendationEngineRun.objects.create(status='success')
        self.anchor = self._priced('Anchor', 'SW1', 100)     # basket avg = 100
        self.cheap = self._priced('Alpha', 'SW2', 50)        # < avg (sorts first by name)
        self.premium = self._priced('Zeta', 'SW3', 200)      # > avg (sorts last by name)

    def _priced(self, name, code, price):
        from decimal import Decimal
        it = make_item(name=name, softech_id=code)
        it.pack_price = Decimal(str(price)); it.save(update_fields=['pack_price'])
        return it

    def _fbt(self, b, score):
        FrequentlyBoughtTogether.objects.create(
            run=self.run, item_a=self.anchor, item_b=b, item_a_occurrences=10,
            confidence=0.5, lift=1.2, score=score)

    def test_vip_boosts_premium_above_cheaper(self):
        self._fbt(self.cheap, 0.5)
        self._fbt(self.premium, 0.5)               # equal fbt score
        base = [r['softech_id'] for r in basket_intelligence(['SW1'])]
        self.assertEqual(base, ['SW2', 'SW3'])      # tie → by name (Alpha before Zeta)
        cust = Customer.objects.create(name='V', phone='07', segment='vip')
        vip = basket_intelligence(['SW1'], customer_id=cust.id)
        self.assertEqual(vip[0]['softech_id'], 'SW3')          # premium boosted to top
        self.assertEqual(vip[0]['boost'], 'premium')

    def test_at_risk_boosts_own_repeat_item(self):
        self._fbt(self.premium, 0.5)                # premium fbt candidate (price 200)
        cust = Customer.objects.create(name='R', phone='08', segment='at_risk')
        CustomerRecommendation.objects.create(
            run=self.run, customer=cust, item=self.cheap, score=0.1, is_chronic_related=False)
        out = basket_intelligence(['SW1'], customer_id=cust.id)
        row = next(r for r in out if r['softech_id'] == 'SW2')
        self.assertEqual(row['boost'], 'retention')            # their personal item boosted

    def test_regular_segment_no_boost(self):
        self._fbt(self.premium, 0.5)
        cust = Customer.objects.create(name='N', phone='09', segment='regular')
        out = basket_intelligence(['SW1'], customer_id=cust.id)
        self.assertIsNone(next(r for r in out if r['softech_id'] == 'SW3')['boost'])
