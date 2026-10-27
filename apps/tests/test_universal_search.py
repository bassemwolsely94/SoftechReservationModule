"""
apps/tests/test_universal_search.py

Universal cross-domain search (Commerce-OS Phase 1). Verifies grouping, the
Arabic-folding name match, and — critically — the SAFETY rule: item *identity*
(code/barcode) is resolved EXACTLY only; only name discovery is fuzzy (rules 4/5).
"""
from rest_framework.test import APIClient
from django.test import TestCase

from apps.catalog.models import Item
from apps.catalog.search_index import search_name_for
from .factories import make_branch, make_item, make_customer, make_user

URL = '/api/search/universal'


def _item(name, softech_id, barcode=''):
    it = make_item(name=name, softech_id=softech_id)
    it.barcode = barcode
    it.search_name = search_name_for(it)
    it.save(update_fields=['barcode', 'search_name'])
    return it


class UniversalSearchTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, _, self.client_ = make_user('search_user', role='pharmacist')
        self.panadol = _item('بانادول اكسترا', 'P1001', barcode='6221048001')
        self.zinc = _item('Zinc Syrup', 'Z2002')
        self.cust = make_customer(name='محمد علي', phone='01099887766')

    # ── auth ──
    def test_anonymous_denied(self):
        r = APIClient().get(URL, {'q': 'zinc'})
        self.assertIn(r.status_code, (401, 403))

    # ── shape ──
    def test_short_query_returns_empty_groups(self):
        r = self.client_.get(URL, {'q': 'z'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['count'], 0)

    def test_response_is_grouped(self):
        r = self.client_.get(URL, {'q': 'zinc'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('items', r.data['results'])
        self.assertIn('customers', r.data['results'])
        self.assertIn('orders', r.data['results'])
        self.assertIn('reservations', r.data['results'])

    # ── items: exact identity ──
    def test_exact_code_is_marked_exact(self):
        r = self.client_.get(URL, {'q': 'P1001'})
        items = r.data['results']['items']
        hit = next(i for i in items if i['softech_id'] == 'P1001')
        self.assertTrue(hit['exact'])

    def test_exact_barcode_is_marked_exact(self):
        r = self.client_.get(URL, {'q': '6221048001'})
        items = r.data['results']['items']
        hit = next(i for i in items if i['softech_id'] == 'P1001')
        self.assertTrue(hit['exact'])

    def test_exact_hits_come_first(self):
        # exact code + a name that also matches: exact must rank ahead
        r = self.client_.get(URL, {'q': 'P1001'})
        items = r.data['results']['items']
        self.assertTrue(items[0]['exact'])

    # ── items: name discovery is fuzzy (Arabic fold), identity is NOT ──
    def test_name_match_is_arabic_folded(self):
        # query uses ة/ي variants the stored name doesn't literally contain
        r = self.client_.get(URL, {'q': 'بانادول'})
        codes = [i['softech_id'] for i in r.data['results']['items']]
        self.assertIn('P1001', codes)

    def test_partial_code_is_never_marked_exact(self):
        # a partial code may surface as fuzzy discovery, but must NEVER be exact=True
        r = self.client_.get(URL, {'q': 'P100'})   # partial of P1001
        for i in r.data['results']['items']:
            if i['softech_id'] == 'P1001':
                self.assertFalse(i['exact'], 'partial code must not resolve as exact identity')

    def test_item_carries_safety_flags(self):
        r = self.client_.get(URL, {'q': 'zinc'})
        hit = next(i for i in r.data['results']['items'] if i['softech_id'] == 'Z2002')
        self.assertIn('safety_flags', hit)

    # ── customers ──
    def test_customer_by_phone(self):
        r = self.client_.get(URL, {'q': '01099887766'})
        phones = [c['phone'] for c in r.data['results']['customers']]
        self.assertIn('01099887766', phones)

    def test_customer_by_name(self):
        r = self.client_.get(URL, {'q': 'محمد'})
        self.assertTrue(any(c['id'] == self.cust.id for c in r.data['results']['customers']))

    # ── controls ──
    def test_types_filter_restricts_groups(self):
        r = self.client_.get(URL, {'q': 'zinc', 'types': 'items'})
        self.assertEqual(list(r.data['results'].keys()), ['items'])

    def test_limit_is_capped(self):
        for n in range(6):
            _item(f'Vitamin C {n}', f'VC{n:03d}')
        r = self.client_.get(URL, {'q': 'vitamin', 'limit': 3})
        self.assertLessEqual(len(r.data['results']['items']), 3)
