"""
N0 / H5 — the live SOFTECH network probe.

Before: GET /api/sync/branch-health/?probe=1 let ANY logged-in user start a live login to all
6 SOFTECH nodes, as often as they liked. Now only an admin can, at most once a minute across
all users; everyone else gets the stored snapshot plus a `probe` reason (HTTP 200 either way,
so the panel still renders).
"""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.tests.factories import make_admin, make_user

URL = '/api/sync/branch-health/'
PROBE = 'apps.sync.network_health.probe_all_nodes'


class SyncProbeGateTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_non_admin_probe_refused(self):
        _, _, client = make_user('n0_h5_pharm', role='pharmacist')
        with mock.patch(PROBE) as probe:
            resp = client.get(URL, {'probe': 1})
        probe.assert_not_called()
        self.assertEqual(resp.status_code, 200)        # path is OPEN_READ; RBAC is off in tests
        self.assertEqual(resp.data['probe'], 'refused')

    def test_admin_probe_runs_once_per_minute(self):
        _, _, client = make_admin('n0_h5_admin')
        with mock.patch(PROBE) as probe:
            first = client.get(URL, {'probe': 1})
            second = client.get(URL, {'probe': 1})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(first.data['probe'], 'ran')
        self.assertEqual(second.data['probe'], 'cooldown')

    def test_cooldown_is_shared_across_admins(self):
        _, _, a = make_admin('n0_h5_admin_a')
        _, _, b = make_admin('n0_h5_admin_b')
        with mock.patch(PROBE) as probe:
            a.get(URL, {'probe': 1})
            resp = b.get(URL, {'probe': 1})
        self.assertEqual(probe.call_count, 1)
        self.assertEqual(resp.data['probe'], 'cooldown')

    def test_snapshot_still_returned(self):
        _, _, client = make_admin('n0_h5_admin_snap')
        with mock.patch(PROBE):
            client.get(URL, {'probe': 1})
            resp = client.get(URL, {'probe': 1})
        self.assertEqual(resp.status_code, 200)
        for key in ('summary', 'nodes', 'branches'):
            self.assertIn(key, resp.data)

    def test_plain_read_does_not_probe(self):
        _, _, client = make_admin('n0_h5_admin_plain')
        with mock.patch(PROBE) as probe:
            resp = client.get(URL)
        probe.assert_not_called()
        self.assertNotIn('probe', resp.data)
