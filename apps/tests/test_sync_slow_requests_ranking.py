"""
Performance stage 1, Task 3: the /sync slow-request report ranks routes by p95
(default, today's behaviour) or by TOTAL time spent (`sort=total`), so a route that is
a little slow but called all day shows above a rare very slow one.
"""
from django.test import TestCase, override_settings

from apps.sync.models import SlowRequest
from .factories import make_admin, make_pharmacist

URL = '/api/sync/slow-requests/'


# Threshold far above any test request, so the report calls themselves are never logged.
@override_settings(SLOW_REQUEST_MS=600_000)
class SlowRequestRankingTests(TestCase):

    def setUp(self):
        _, _, self.client = make_admin('admin_rank')

    def _add(self, path, ms, n):
        SlowRequest.objects.bulk_create(
            SlowRequest(path=path, method='GET', status_code=200, duration_ms=ms) for _ in range(n))

    def _paths(self, **params):
        r = self.client.get(URL, params)
        self.assertEqual(r.status_code, 200)
        return [row['path'] for row in r.json()['endpoints']]

    def test_sort_total_orders_by_total_time(self):
        self._add('api/rare-slow/', 10_000, 2)     # 20 s total, p95 10 000
        self._add('api/busy/', 1_200, 30)          # 36 s total, p95 1 200
        self.assertEqual(self._paths(sort='total')[:2], ['api/busy/', 'api/rare-slow/'])
        self.assertEqual(self._paths(sort='p95')[:2], ['api/rare-slow/', 'api/busy/'])
        self.assertEqual(self._paths()[:2], ['api/rare-slow/', 'api/busy/'])  # default = p95
        self.assertEqual(self.client.get(URL, {'sort': 'total'}).json()['sort'], 'total')

    def test_fields_present(self):
        for ms in (1_000, 2_000, 3_000):
            self._add('api/x/', ms, 1)
        row = self.client.get(URL).json()['endpoints'][0]
        for key in ('path', 'method', 'count', 'p50_ms', 'p95_ms', 'max_ms', 'total_s'):
            self.assertIn(key, row)
        self.assertEqual(row['p50_ms'], 2_000)
        self.assertEqual(row['total_s'], 6.0)
        self.assertEqual(row['count'], 3)

    def test_limit_clamped(self):
        for i in range(60):
            self._add(f'api/r{i}/', 1_500, 1)
        self.assertEqual(len(self._paths()), 10)                # default limit
        self.assertEqual(len(self._paths(limit=25)), 25)
        self.assertEqual(len(self._paths(limit=999)), 50)       # clamped high
        self.assertEqual(len(self._paths(limit=0)), 1)          # clamped low

    def test_empty_and_garbage_params(self):
        r = self.client.get(URL, {'days': 'abc', 'sort': 'zzz', 'limit': 'x'})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['endpoints'], [])
        self.assertEqual(body['sort'], 'p95')
        self.assertEqual(body['days'], 14)

    def test_non_admin_403(self):
        _, _, client = make_pharmacist('pharma_rank')
        self.assertEqual(client.get(URL, {'sort': 'total'}).status_code, 403)
