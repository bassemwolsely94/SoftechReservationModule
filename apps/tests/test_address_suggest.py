"""
apps/tests/test_address_suggest.py — address autocomplete for the POS new-customer form
(POS speed wave, Task 7). Values come only from addresses already stored.
"""
from django.test import TestCase

from apps.customers.address_suggest import address_suggest
from apps.customers.models import Customer
from apps.delivery.models import CustomerLocation, DeliveryOrder
from .factories import make_branch, make_user


class AddressSuggestTests(TestCase):
    def setUp(self):
        self.c = Customer.objects.create(name='عميل', phone='01012345678')

    def _loc(self, **kw):
        return CustomerLocation.objects.create(customer=self.c, **kw)

    def test_address_suggest_ranks_by_use(self):
        self._loc(area='المعادي')
        self._loc(area='المعادي')
        self._loc(area='المقطم')
        self._loc(area='المنيل')
        self._loc(area='')
        self.assertEqual(address_suggest('area', 'م'), ['المعادي', 'المقطم', 'المنيل'])
        self.assertEqual(address_suggest('area', 'مع'), ['المعادي'])

    def test_address_suggest_counts_order_level_values(self):
        self._loc(area='الهرم')
        o = DeliveryOrder(customer=self.c, branch=make_branch(), delivery_area='الهرم')
        DeliveryOrder.objects.bulk_create([o])
        self.assertEqual(address_suggest('area', 'هرم'), ['الهرم'])

    def test_address_suggest_arabic_variants(self):
        self._loc(area='الإسكندرية')
        self._loc(area='الاسكندريه')
        self._loc(area='القاهرة')
        out = address_suggest('area', 'اسكندريه')
        self.assertEqual(len(out), 1)               # variants merged
        self.assertIn(out[0], ('الإسكندرية', 'الاسكندريه'))
        self.assertEqual(address_suggest('area', 'قاهره'), ['القاهرة'])

    def test_address_suggest_wildcard(self):
        self._loc(area='مدينة نصر')
        self.assertEqual(address_suggest('area', 'مدينة*'), ['مدينة نصر'])
        self.assertEqual(address_suggest('area', 'نصر*مدينة'), ['مدينة نصر'])  # any order

    def test_address_suggest_rejects_field(self):
        with self.assertRaises(ValueError):
            address_suggest('phone', 'x')

    def test_address_suggest_narrows_by_area(self):
        self._loc(area='المعادي', district='دجلة')
        self._loc(area='المعادي', district='دجلة')
        self._loc(area='المعادي', district='زهراء')
        self._loc(area='الهرم', district='فيصل')
        self.assertEqual(address_suggest('district', '', area='المعادي'), ['دجلة', 'زهراء'])
        self.assertEqual(address_suggest('district', '', area='معادي*'), ['دجلة', 'زهراء'])
        self.assertEqual(set(address_suggest('district', '')), {'دجلة', 'زهراء', 'فيصل'})

    def test_address_suggest_limit(self):
        for i in range(5):
            self._loc(landmark=f'علامة {i}')
        self.assertEqual(len(address_suggest('landmark', '', limit=3)), 3)


class AddressSuggestEndpointTests(TestCase):
    def test_endpoint(self):
        _, _, client = make_user('addr_user')
        c = Customer.objects.create(name='ع', phone='01000000001')
        CustomerLocation.objects.create(customer=c, area='الزمالك')
        r = client.get('/api/customers/address-suggest/', {'field': 'area', 'q': 'زم'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['results'], ['الزمالك'])
        self.assertEqual(client.get('/api/customers/address-suggest/', {'field': 'bad'}).status_code, 400)
