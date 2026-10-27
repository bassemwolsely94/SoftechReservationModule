"""
apps/tests/test_offers_config_boost.py

Boosted offers config: new targeting fields (name / general classification),
the `not_in` (لا يتضمن) operator, the field-values dropdown source, and the
contradiction validator (no-items / sell-at-loss / overlap / priority).
"""
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from apps.catalog.models import Item
from apps.offers.models import Offer
from apps.offers.targeting import item_matches_spec, build_target_q
from apps.offers.validation import validate_offer
from .factories import make_item, make_user


def _item(code, **f):
    it = make_item(name=f.pop('name', code), softech_id=code)
    for k, v in f.items():
        setattr(it, k, v)
    it.save()
    return it


class NotInAndNameTests(TestCase):
    def setUp(self):
        self.a = _item('A', name='بانادول اطفال', producer_code='P1')
        self.b = _item('B', name='فيتامين سي', producer_code='P2')

    def test_not_in_operator(self):
        spec = {'rules': [{'field': 'producer_code', 'op': 'not_in', 'value': ['P2']}]}
        self.assertTrue(item_matches_spec(spec, self.a))    # P1 not in [P2]
        self.assertFalse(item_matches_spec(spec, self.b))   # P2 is in [P2]
        # DB path agrees
        ids = set(Item.objects.filter(build_target_q(spec)).values_list('id', flat=True))
        self.assertIn(self.a.id, ids)
        self.assertNotIn(self.b.id, ids)

    def test_name_contains(self):
        spec = {'rules': [{'field': 'name', 'op': 'contains', 'value': 'بانادول'}]}
        self.assertTrue(item_matches_spec(spec, self.a))
        self.assertFalse(item_matches_spec(spec, self.b))


class FieldValuesApiTests(TestCase):
    def test_field_values(self):
        _item('A', producer_code='P1', producer_name='شركة أولى')
        _item('B', producer_code='P2', producer_name='شركة ثانية')
        _, _, client = make_user('fv_user', role='pharmacist')
        r = client.get('/api/offers/field-values/?field=producer_code')
        self.assertEqual(r.status_code, 200)
        vals = {x['value']: x['label'] for x in r.data}
        self.assertEqual(vals.get('P1'), 'شركة أولى')
        # q filter (regression: `Q` must be importable in the view)
        rq = client.get('/api/offers/field-values/?field=producer_code&q=ثانية')
        self.assertEqual(rq.status_code, 200)
        self.assertEqual({x['value'] for x in rq.data}, {'P2'})

    def test_unsupported_field_rejected(self):
        _, _, client = make_user('fv_user2', role='pharmacist')
        r = client.get('/api/offers/field-values/?field=pack_price')
        self.assertEqual(r.status_code, 400)


class ValidationTests(TestCase):
    def test_no_matching_items(self):
        o = Offer.objects.create(name='x', offer_type='percent', status='active', value=10,
                                 require_stock=False,
                                 target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'NOPE'}]})
        w = validate_offer(o)
        self.assertTrue(any(x['code'] == 'no_items' for x in w))

    def test_sell_at_loss(self):
        it = _item('L', producer_code='PL', pack_price=Decimal('100'), cost_price=Decimal('90'))
        o = Offer.objects.create(name='loss', offer_type='percent', status='active', value=20,
                                 authorization_source='offer', require_stock=False,
                                 target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'PL'}]})
        # 20% off 100 → net 80 < cost 90 → loss
        self.assertTrue(any(x['code'] == 'loss' for x in validate_offer(o)))

    def test_overlap_and_priority(self):
        _item('O', producer_code='POV', pack_price=Decimal('50'), cost_price=Decimal('10'))
        common = {'offer_type': 'percent', 'status': 'active', 'value': 5, 'require_stock': False,
                  'authorization_source': 'offer', 'priority': 1, 'stackable': False,
                  'target_spec': {'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'POV'}]}}
        Offer.objects.create(name='first', **common)
        o2 = Offer.objects.create(name='second', **common)
        w = validate_offer(o2)
        self.assertTrue(any(x['code'] == 'overlap' for x in w))
        self.assertTrue(any(x['code'] == 'priority' for x in w))   # same priority, non-stackable

    def test_validate_endpoint(self):
        o = Offer.objects.create(name='x', offer_type='percent', status='active', value=10,
                                 require_stock=False,
                                 target_spec={'rules': [{'field': 'producer_code', 'op': 'eq', 'value': 'NOPE'}]})
        _, _, admin = make_user('val_admin', role='admin')
        r = admin.get(f'/api/offers/{o.id}/validate/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(x['code'] == 'no_items' for x in r.data['warnings']))
