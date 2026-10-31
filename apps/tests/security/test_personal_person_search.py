"""
Personal dashboard — live person search (security batch N0, H1).

Before: any logged-in user could run a live HQ personsdata LIKE (2-char minimum, 25 names+codes
per call, unthrottled, unaudited) and got raw SOFTECH error text back. Now: 3-char minimum, no
delivery role, 30/hour, every search audited, errors sanitised.
"""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.tests.factories import make_user

URL = '/api/personal/persons/search/'
TARGET = 'apps.personal.queries.search_persons'
ROWS = [{'person_code': '1', 'name': 'Acme', 'ptcode': '20', 'ptclassifcode': ''}]


class PersonSearchTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _, self.profile, self.me = make_user('h1_user', role='pharmacist')

    def test_short_query_does_not_hit_softech(self):
        with mock.patch(TARGET, return_value=ROWS) as m:
            r = self.me.get(URL, {'q': 'ab '})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {'results': []})
        m.assert_not_called()

    def test_delivery_role_refused(self):
        _, _, rider = make_user('h1_rider', role='delivery')
        with mock.patch(TARGET, return_value=ROWS) as m:
            r = rider.get(URL, {'q': 'acme'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()['detail'], 'غير مصرّح')
        m.assert_not_called()

    def test_inactive_profile_refused(self):
        self.profile.is_active = False
        self.profile.save()
        with mock.patch(TARGET, return_value=ROWS) as m:
            r = self.me.get(URL, {'q': 'acme'})
        self.assertEqual(r.status_code, 403)
        m.assert_not_called()

    def test_throttled_after_30_per_hour(self):
        with mock.patch(TARGET, return_value=ROWS):
            for _ in range(30):
                self.assertEqual(self.me.get(URL, {'q': 'acme'}).status_code, 200)
            self.assertEqual(self.me.get(URL, {'q': 'acme'}).status_code, 429)

    def test_error_text_not_leaked(self):
        with mock.patch(TARGET, return_value=[{'_error': 'JZ0T3 secret host 192.168.1.8'}]):
            r = self.me.get(URL, {'q': 'acme'})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(r.json()['detail'], 'تعذّر البحث في SOFTECH')
        self.assertNotIn('192.168.1.8', r.content.decode())
        self.assertNotIn('JZ0T3', r.content.decode())

    def test_search_is_audited(self):
        with mock.patch(TARGET, return_value=ROWS):
            r = self.me.get(URL, {'q': 'acme', 'kind': 'supplier'}, REMOTE_ADDR='10.1.2.3')
        self.assertEqual(r.status_code, 200)
        log = AuditLog.objects.get(action='personal_person_search')
        self.assertEqual(log.user, self.profile)
        self.assertEqual(log.ip_address, '10.1.2.3')
        self.assertEqual(log.extra, {'q': 'acme', 'kind': 'supplier', 'count': 1})
