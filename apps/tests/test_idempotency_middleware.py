"""Full audit 2026-11-15, FE-1: the /m offline queue's X-Idempotency-Key is honoured on its endpoints."""
from django.http import JsonResponse
from django.test import RequestFactory, TestCase

from apps.config.models import IdempotentRequest
from core.middleware.idempotency import IdempotencyKeyMiddleware

KEY = 'q_1731760000000_ab12cd'


class IdempotencyKeyMiddlewareTests(TestCase):
    def setUp(self):
        self.calls = 0
        self.status = 201

    def _view(self, request):
        self.calls += 1
        return JsonResponse({'id': self.calls}, status=self.status)

    def _post(self, path='/api/demand/', key=KEY):
        rf = RequestFactory()
        headers = {'HTTP_X_IDEMPOTENCY_KEY': key} if key else {}
        return IdempotencyKeyMiddleware(self._view)(rf.post(path, {}, **headers))

    def test_a_replay_after_success_writes_nothing(self):
        first, second = self._post(), self._post()
        self.assertEqual((first.status_code, second.status_code), (201, 201))
        self.assertEqual(self.calls, 1)
        self.assertIn(b'idempotent_replay', second.content)
        self.assertEqual(IdempotentRequest.objects.get().status, 201)

    def test_a_failure_frees_the_key_for_the_retry(self):
        self.status = 503
        self.assertEqual(self._post().status_code, 503)
        self.assertFalse(IdempotentRequest.objects.exists())
        self.status = 201
        self.assertEqual(self._post().status_code, 201)
        self.assertEqual(self.calls, 2)

    def test_a_replay_while_the_first_runs_is_processing(self):
        IdempotentRequest.objects.create(key=KEY, path='/api/demand/')       # status 0 = in flight
        self.assertEqual(self._post().status_code, 202)
        self.assertEqual(self.calls, 0)

    def test_other_paths_methods_and_missing_keys_are_untouched(self):
        self._post(path='/api/transfers/')
        self._post(key=None)
        self._post(key='bad key!')
        self.assertEqual(self.calls, 3)
        self.assertFalse(IdempotentRequest.objects.exists())

    def test_covered_paths(self):
        for path in ('/api/reservations/', '/api/stockcount/daily/my/count/',
                     '/api/stockcount/sessions/7/count-item/', '/api/shortage/lists/3/add-item/',
                     '/api/shortage/lists/3/bulk-import/'):
            self._post(path=path)
            self._post(path=path)
        self.assertEqual(self.calls, 5)
