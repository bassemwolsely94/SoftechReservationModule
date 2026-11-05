"""
Pricing approvals — the HQ↔branch replication scan (R7, role_crashes).

Before: with SOFTECH unreachable the scan raised through the view (500), and a non-number
`days` raised ValueError (500). Now: 503 with the failed scan stored, and 400 for a bad window.
"""
from unittest import mock

from django.test import TestCase, override_settings

from apps.discount_approvals.models import ReplicationScan
from apps.tests.factories import make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

SCAN = '/api/pricing-approvals/replication/scan/'


@override_settings(RBAC_ENFORCEMENT='log')
class ReplicationScanViewTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role):
        return bearer_client(make_user(f'r7rs_{role}', role=role, access_all=(role == 'admin'))[0])

    def test_softech_down_answers_503_and_keeps_the_failed_scan(self):
        boom = ConnectionError('softech offline')
        with mock.patch('config.sybase.get_sybase_connection', side_effect=boom):
            r = self._client('admin').post(SCAN, {'days': 7}, format='json')
        self.assertEqual(r.status_code, 503)
        scan = ReplicationScan.objects.get()
        self.assertEqual(scan.status, ReplicationScan.STATUS_FAILED)
        self.assertEqual(scan.days_window, 7)
        self.assertIn('softech offline', scan.error)

    def test_bad_days_is_400_and_starts_no_scan(self):
        r = self._client('admin').post(SCAN, {'days': 'abc'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ReplicationScan.objects.exists())

    def test_pharmacist_cannot_run_a_scan(self):
        r = self._client('pharmacist').post(SCAN, {}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ReplicationScan.objects.exists())
