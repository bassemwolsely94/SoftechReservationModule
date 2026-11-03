"""N6 / Task 3 - /notify form: guarded, write-only, no SOFTECH from the public page."""
import hashlib
import time
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.branches.models import Branch
from apps.catalog.models import Item
from apps.customers.models import Customer
from apps.demand.models import DemandItem, DemandRecord
from core import public_guard

NOTIFY = '/api/public/notify/interest/'
OLD = '/api/demand/public/interest/'


def _solve(challenge, difficulty):
    n = 0
    while public_guard.leading_zero_bits(
            hashlib.sha256(f'{challenge}:{n}'.encode()).digest()) < difficulty:
        n += 1
    return str(n)


@override_settings(PUBLIC_POW_DIFFICULTY=4, PUBLIC_MIN_FILL_SECONDS=0, PUBLIC_NOTIFY_DAILY_MAX=3)
class PublicNotifyTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.c = APIClient()
        self.item = Item.objects.create(softech_id='940001', name='Panadol', pack_price=10)
        self.branch = Branch.objects.create(softech_branch_id='171', name='Abbasia')

    def _body(self, **over):
        ch = public_guard.issue_challenge('notify')
        body = {'phone': '01012345678', 'name': 'Ali', 'item': self.item.id,
                'branch': self.branch.id, 'challenge': ch['challenge'],
                'nonce': _solve(ch['challenge'], ch['difficulty']), 'website': ''}
        body.update(over)
        return body

    def _post(self, url=NOTIFY, **over):
        return self.c.post(url, self._body(**over), format='json')

    def test_double_submit_same_response_one_record(self):
        r1, r2 = self._post(), self._post()
        self.assertEqual((r1.status_code, r1.json()), (200, {'ok': True}))
        self.assertEqual((r2.status_code, r2.json()), (200, {'ok': True}))
        self.assertEqual(DemandRecord.objects.filter(source='self_service').count(), 1)

    def test_existing_phone_item_same_response_as_new(self):
        new = self._post()
        existing = self._post()
        self.assertEqual(new.status_code, existing.status_code)
        self.assertEqual(new.json(), existing.json())

    def test_no_softech_on_public_create(self):
        with mock.patch('config.sybase.get_sybase_connection',
                        side_effect=AssertionError('SOFTECH called')) as conn:
            r = self._post()
        self.assertEqual(r.status_code, 200)
        conn.assert_not_called()
        self.assertEqual(DemandRecord.objects.count(), 1)

    def test_self_service_demand_not_linked_to_customer(self):
        Customer.objects.create(name='Known', phone='01012345678')
        self._post()
        self.assertIsNone(DemandRecord.objects.get().customer)

    def test_item_lookup_has_no_softech_id(self):
        r = self.c.get('/api/public/notify/item/', {'id': self.item.id})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {'found', 'id', 'name'})

    def test_long_name_rejected(self):
        r = self._post(name='x' * 81)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(DemandRecord.objects.count(), 0)
        self.assertEqual(self._post(name='x' * 80).status_code, 200)

    def test_bot_gets_success_but_no_record(self):
        r = self._post(website='http://spam.example')
        self.assertEqual((r.status_code, r.json()), (200, {'ok': True}))
        self.assertEqual(DemandRecord.objects.count(), 0)

    def test_invalid_form_does_not_burn_phone_limit(self):
        for _ in range(4):
            self.assertEqual(self._post(branch=999999).status_code, 400)
        self.assertEqual(self._post().status_code, 200)
        self.assertEqual(DemandRecord.objects.count(), 1)

    def test_phone_limit_looks_like_success_no_record(self):
        items = [Item.objects.create(softech_id=f'9401{i}', name=f'I{i}', pack_price=1)
                 for i in range(4)]
        for it in items[:3]:
            self.assertEqual(self._post(item=it.id).status_code, 200)
        r = self._post(item=items[3].id)
        self.assertEqual((r.status_code, r.json()), (200, {'ok': True}))
        self.assertEqual(DemandRecord.objects.count(), 3)

    def test_missing_challenge_is_400(self):
        body = self._body()
        body.pop('challenge')
        r = self.c.post(NOTIFY, body, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(DemandRecord.objects.count(), 0)

    def test_non_numeric_ids_never_500(self):
        for junk in ('abc', '1.5', '-3', '99999999999999999999', '', ' '):
            r = self.c.get('/api/public/notify/item/', {'id': junk})
            self.assertEqual((r.status_code, r.json()), (200, {'found': False}), junk)
        r = self._post(item='abc')
        self.assertEqual((r.status_code, r.json()['detail']), (400, 'الصنف غير متاح'))
        r = self._post(item=[1])
        self.assertEqual((r.status_code, r.json()['detail']), (400, 'الصنف غير متاح'))
        r = self._post(branch='x1')
        self.assertEqual((r.status_code, r.json()['detail']), (400, 'الفرع غير صحيح'))
        r = self._post(branch='99999999999999999999')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(DemandRecord.objects.count(), 0)

    def test_ten_items_a_day_per_phone_by_default(self):
        with override_settings(PUBLIC_NOTIFY_DAILY_MAX=10):
            items = [Item.objects.create(softech_id=f'9402{i:02d}', name=f'J{i}', pack_price=1)
                     for i in range(11)]
            for it in items:
                self.assertEqual(self._post(item=it.id).status_code, 200)
        self.assertEqual(DemandRecord.objects.count(), 10)

    def test_canonical_and_old_routes_both_work(self):
        self.assertEqual(self._post(NOTIFY).status_code, 200)
        self.assertEqual(self._post(OLD, phone='01099999999').status_code, 200)
        self.assertEqual(self.c.get('/api/public/notify/branches/').status_code, 200)
        self.assertEqual(self.c.get('/api/demand/public/branches/').status_code, 200)
        self.assertEqual(self.c.get('/api/demand/public/item/', {'id': self.item.id}).status_code, 200)
