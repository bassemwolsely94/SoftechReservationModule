"""
apps/tests/test_customer_recognition.py

Recognize-on-type + duplicate detection for the POS customer field (Commerce-OS
Phase 2). Phone matching is digits-only; duplicates (same normalized phone) are
surfaced so staff merge instead of creating a third copy.
"""
from django.test import TestCase

from apps.customers.models import Customer
from apps.customers.recognition import recognize, _digits
from .factories import make_user

URL = '/api/customers/recognize/'


class RecognitionUnitTests(TestCase):
    def setUp(self):
        self.a = Customer.objects.create(name='أحمد', phone='01012345678', segment='vip')
        self.b = Customer.objects.create(name='سميرة', phone='01099999999', whatsapp_phone='01088887777')

    def test_digits_strips_formatting(self):
        self.assertEqual(_digits('+20 100-123 4567'), '201001234567')

    def test_short_query_returns_nothing(self):
        self.assertEqual(recognize('01'), {'matches': [], 'duplicates': []})

    def test_exact_phone_recognized(self):
        out = recognize('01012345678')
        self.assertEqual(out['matches'][0]['id'], self.a.id)
        self.assertIn('segment_label', out['matches'][0])

    def test_prefix_phone_recognized(self):
        out = recognize('0101234')
        self.assertTrue(any(m['id'] == self.a.id for m in out['matches']))

    def test_whatsapp_phone_recognized(self):
        out = recognize('01088887777')
        self.assertTrue(any(m['id'] == self.b.id for m in out['matches']))

    def test_name_path(self):
        out = recognize('سميرة')
        self.assertTrue(any(m['id'] == self.b.id for m in out['matches']))

    def test_ignores_formatting_in_query(self):
        out = recognize('0101-234-5678')
        self.assertTrue(any(m['id'] == self.a.id for m in out['matches']))


class DuplicateDetectionTests(TestCase):
    def test_same_phone_flagged_as_duplicate(self):
        Customer.objects.create(name='محمد ١', phone='01055556666')
        Customer.objects.create(name='محمد ٢', phone='01055556666')   # duplicate
        out = recognize('01055556666')
        self.assertEqual(len(out['duplicates']), 1)
        self.assertEqual(len(out['duplicates'][0]['customers']), 2)

    def test_distinct_phones_not_flagged(self):
        Customer.objects.create(name='x', phone='01011112222')
        Customer.objects.create(name='y', phone='01033334444')
        out = recognize('0101111')
        self.assertEqual(out['duplicates'], [])


class RecognitionApiTests(TestCase):
    def setUp(self):
        _, _, self.client_ = make_user('recog_user', role='pharmacist')
        Customer.objects.create(name='عميل', phone='01234567890')

    def test_requires_auth(self):
        from rest_framework.test import APIClient
        r = APIClient().get(URL, {'q': '0123'})
        self.assertIn(r.status_code, (401, 403))

    def test_returns_matches(self):
        r = self.client_.get(URL, {'q': '01234567890'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('matches', r.data)
        self.assertIn('duplicates', r.data)
        self.assertTrue(len(r.data['matches']) >= 1)
