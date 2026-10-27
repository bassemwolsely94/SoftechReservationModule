"""
apps/tests/test_offers_targeting.py

Flexible Odoo-style product selector for offers (PG-only): pick by any whitelisted
items-master field, booleans, price ranges; manual include/exclude; overridable
stock gate. Both evaluators (DB Q + Python) must agree, and the engine must apply
an offer only to the resolved set.
"""
from decimal import Decimal
from django.test import TestCase

from apps.catalog.models import Item, ItemStock
from apps.offers.models import Offer
from apps.offers.engine import evaluate_offers
from apps.offers.targeting import (
    build_target_q, item_matches_spec, preview_items, resolve_offer_items,
)
from .factories import make_branch, make_item, make_user


def _item(code, **fields):
    it = make_item(name=code, softech_id=code)
    for k, v in fields.items():
        setattr(it, k, v)
    it.save()
    return it


def line(it, qty, price):
    return {'softech_id': it.softech_id, 'item': it, 'qty': qty, 'unit_price': price}


class SpecMatchTests(TestCase):
    def setUp(self):
        self.p1 = _item('P1', producer_code='100', pack_price=Decimal('50'), requires_fridge=True)
        self.p2 = _item('P2', producer_code='200', pack_price=Decimal('150'), requires_fridge=False)

    def test_producer_in(self):
        spec = {'match': 'all', 'rules': [{'field': 'producer_code', 'op': 'in', 'value': ['100']}]}
        self.assertTrue(item_matches_spec(spec, self.p1))
        self.assertFalse(item_matches_spec(spec, self.p2))
        # DB path agrees
        ids = set(Item.objects.filter(build_target_q(spec)).values_list('id', flat=True))
        self.assertEqual(ids, {self.p1.id})

    def test_price_range(self):
        spec = {'rules': [{'field': 'pack_price', 'op': 'range', 'value': [100, 200]}]}
        self.assertFalse(item_matches_spec(spec, self.p1))   # 50 outside
        self.assertTrue(item_matches_spec(spec, self.p2))    # 150 inside

    def test_boolean(self):
        spec = {'rules': [{'field': 'requires_fridge', 'op': 'is_true'}]}
        self.assertTrue(item_matches_spec(spec, self.p1))
        self.assertFalse(item_matches_spec(spec, self.p2))

    def test_match_any_vs_all(self):
        spec_all = {'match': 'all', 'rules': [
            {'field': 'producer_code', 'op': 'eq', 'value': '100'},
            {'field': 'requires_fridge', 'op': 'is_false'}]}
        self.assertFalse(item_matches_spec(spec_all, self.p1))   # fridge True fails AND
        spec_any = {**spec_all, 'match': 'any'}
        self.assertTrue(item_matches_spec(spec_any, self.p1))    # producer matches OR

    def test_unknown_field_ignored(self):
        spec = {'rules': [{'field': 'DROP TABLE', 'op': 'eq', 'value': 'x'}]}
        self.assertFalse(item_matches_spec(spec, self.p1))
        self.assertIsNone(build_target_q(spec))                  # produced no query


class ResolveAndExcludeTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        # a "Parkville" producer with two packs; one is a promo-pack to exclude
        self.a = _item('A', producer_code='PARK', pack_price=Decimal('30'))
        self.b = _item('B', producer_code='PARK', pack_price=Decimal('40'))
        self.promo = _item('PROMO', producer_code='PARK', pack_price=Decimal('99'))

    def test_manual_exclude_wins(self):
        o = Offer.objects.create(name='Parkville 1+½', offer_type='percent', status='active',
                                 target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]})
        o.excluded_items.add(self.promo)
        ids = set(resolve_offer_items(o).values_list('id', flat=True))
        self.assertEqual(ids, {self.a.id, self.b.id})            # promo pack left out

    def test_require_stock_gate(self):
        o = Offer.objects.create(name='X', offer_type='percent', status='active', require_stock=True,
                                 target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]})
        ItemStock.objects.create(item=self.a, branch=self.branch, softech_store_code='01', quantity_on_hand=5)
        # only A has stock at the branch
        ids = set(resolve_offer_items(o, branch_id=self.branch.id).values_list('id', flat=True))
        self.assertEqual(ids, {self.a.id})
        # override: require_stock off → all resolve
        o.require_stock = False; o.save(update_fields=['require_stock'])
        ids2 = set(resolve_offer_items(o, branch_id=self.branch.id).values_list('id', flat=True))
        self.assertEqual(ids2, {self.a.id, self.b.id, self.promo.id})

    def test_preview_items(self):
        qs = preview_items(target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]},
                           exclude_ids=[self.promo.id])
        self.assertEqual(qs.count(), 2)


class EngineIntegrationTests(TestCase):
    def setUp(self):
        self.match = _item('M', producer_code='PARK', pack_price=Decimal('100'))
        self.other = _item('O', producer_code='OTHER', pack_price=Decimal('100'))

    def test_offer_applies_only_to_spec(self):
        o = Offer.objects.create(name='Parkville 25%', offer_type='percent', status='active',
                                 value=25, authorization_source='offer',
                                 target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]})
        plan = evaluate_offers([line(self.match, 1, 100), line(self.other, 1, 100)], offers=[o])
        # only the PARK item is discounted (25 of 100)
        self.assertEqual(plan['total_discount'], Decimal('25.00'))
        idxs = {ln['index'] for ap in plan['applied'] for ln in ap['lines']}
        self.assertEqual(idxs, {0})

    def test_excluded_item_not_discounted(self):
        o = Offer.objects.create(name='Parkville 25%', offer_type='percent', status='active',
                                 value=25, authorization_source='offer',
                                 target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]})
        o.excluded_items.add(self.match)
        plan = evaluate_offers([line(self.match, 1, 100)], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))

    def test_stock_gate_in_engine(self):
        branch = make_branch()
        o = Offer.objects.create(name='X', offer_type='percent', status='active', value=25,
                                 authorization_source='offer', require_stock=True,
                                 target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]})
        # no stock row → gated out at this branch
        plan = evaluate_offers([line(self.match, 1, 100)], offers=[o], branch_id=branch.id)
        self.assertEqual(plan['total_discount'], Decimal('0.00'))


class TargetApiTests(TestCase):
    def test_fields_and_preview(self):
        _item('A', producer_code='PARK'); _item('B', producer_code='OTHER')
        _, _, client = make_user('tgt_user', role='pharmacist')
        r = client.get('/api/offers/target-fields/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(f['field'] == 'producer_code' for f in r.data))
        r2 = client.post('/api/offers/target-preview/', {
            'target_spec': {'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]}}, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data['count'], 1)
