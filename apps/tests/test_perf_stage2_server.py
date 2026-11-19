"""
Performance Stage 2 — server setup (docs/superpowers/plans/2026-11-19-perf-stage2-server-setup.md).

Shared Redis caches: `default` fails OPEN (a Redis error is a cache miss), `limits` fails CLOSED
(a Redis error refuses the request with 503 + Arabic "try again shortly"; owner decision §9).
Web-only statement timeout: off by default, set on request threads only when the flag is on.
"""
import threading
from unittest import mock

from django.conf import settings
from django.core.cache import caches
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from config.cache_config import build_caches
from core import limits
from core.cache_backends import FailClosedRedisCache, FailOpenRedisCache

# Nothing listens on port 1; a short timeout and no retries keep each refused call quick.
DEAD = 'redis://127.0.0.1:1/0'


def _dead_options():
    from redis.backoff import NoBackoff
    from redis.retry import Retry
    return {'socket_connect_timeout': 0.2, 'socket_timeout': 0.2, 'retry': Retry(NoBackoff(), 0)}


def _caches_with_dead_limits():
    return {
        'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                    'LOCATION': 'perf-s2-default'},
        'limits': {'BACKEND': 'core.cache_backends.FailClosedRedisCache', 'LOCATION': DEAD,
                   'OPTIONS': _dead_options()},
    }


class CacheConfigTests(SimpleTestCase):

    def test_no_env_is_locmem_pair_sharing_storage(self):
        c = build_caches(cache_url='', limits_url='', max_entries=50000)
        self.assertEqual(c['default']['BACKEND'], 'django.core.cache.backends.locmem.LocMemCache')
        self.assertEqual(c['limits']['BACKEND'], 'django.core.cache.backends.locmem.LocMemCache')
        # same LOCATION = same storage, so cache.clear() in tests still resets the throttles
        self.assertEqual(c['default']['LOCATION'], c['limits']['LOCATION'])
        self.assertEqual(c['default']['OPTIONS']['MAX_ENTRIES'], 50000)

    def test_both_urls_give_fail_open_and_fail_closed_redis(self):
        c = build_caches(cache_url='redis://127.0.0.1:6379/1',
                         limits_url='redis://127.0.0.1:6379/2', max_entries=50000)
        self.assertEqual(c['default']['BACKEND'], 'core.cache_backends.FailOpenRedisCache')
        self.assertEqual(c['limits']['BACKEND'], 'core.cache_backends.FailClosedRedisCache')
        self.assertEqual(c['default']['LOCATION'], 'redis://127.0.0.1:6379/1')
        self.assertEqual(c['limits']['LOCATION'], 'redis://127.0.0.1:6379/2')
        for alias in ('default', 'limits'):
            opts = c[alias]['OPTIONS']
            self.assertLessEqual(opts['socket_connect_timeout'], 1)
            self.assertLessEqual(opts['socket_timeout'], 1)

    def test_one_url_alone_is_refused(self):
        with self.assertRaises(ImproperlyConfigured):
            build_caches(cache_url='redis://127.0.0.1:6379/1', limits_url='', max_entries=1)
        with self.assertRaises(ImproperlyConfigured):
            build_caches(cache_url='', limits_url='redis://127.0.0.1:6379/2', max_entries=1)

    def test_same_url_for_both_is_refused(self):
        # a full plain cache must never be able to evict a limit (separate DB, noeviction)
        with self.assertRaises(ImproperlyConfigured):
            build_caches(cache_url='redis://127.0.0.1:6379/1',
                         limits_url='redis://127.0.0.1:6379/1', max_entries=1)

    def test_settings_define_both_aliases(self):
        self.assertIn('default', settings.CACHES)
        self.assertIn('limits', settings.CACHES)


class FailOpenTests(SimpleTestCase):
    """Cache-miss path: Redis down = compute without the cache."""

    def setUp(self):
        self.c = FailOpenRedisCache(DEAD, {'OPTIONS': _dead_options()})

    def test_reads_are_misses(self):
        self.assertIsNone(self.c.get('k'))
        self.assertEqual(self.c.get('k', 'fallback'), 'fallback')
        self.assertEqual(self.c.get_many(['a', 'b']), {})
        self.assertFalse(self.c.has_key('k'))

    def test_writes_do_not_raise(self):
        self.c.set('k', 1, 10)
        self.c.set_many({'a': 1}, 10)
        self.c.delete('k')
        self.c.delete_many(['a'])
        self.assertFalse(self.c.touch('k'))

    def test_add_lets_the_caller_compute(self):
        # add() guards "compute once" / dedupe: True = go ahead and compute
        self.assertTrue(self.c.add('lock', 1, 10))

    def test_incr_is_a_missing_key(self):
        with self.assertRaises(ValueError):
            self.c.incr('n')

    def test_get_or_set_computes(self):
        self.assertEqual(self.c.get_or_set('k', lambda: 42, 10), 42)


class FailClosedTests(SimpleTestCase):

    def setUp(self):
        self.c = FailClosedRedisCache(DEAD, {'OPTIONS': _dead_options()})

    def test_every_operation_refuses(self):
        for call in (lambda: self.c.get('k'), lambda: self.c.add('k', 1, 10),
                     lambda: self.c.set('k', 1, 10), lambda: self.c.incr('k')):
            with self.assertRaises(limits.LimitsUnavailable):
                call()

    def test_refusal_is_503_arabic(self):
        exc = limits.LimitsUnavailable()
        self.assertEqual(exc.status_code, 503)
        self.assertEqual(str(exc.detail), limits.LIMITS_UNAVAILABLE_MESSAGE)
        self.assertIn('حاول', limits.LIMITS_UNAVAILABLE_MESSAGE)


class ThrottleGuardTests(SimpleTestCase):
    """Every rate throttle in our code keeps its counters in the fail-closed `limits` cache."""

    def test_all_project_throttles_use_limits_cache(self):
        from django.urls import get_resolver
        from rest_framework.throttling import SimpleRateThrottle
        get_resolver().url_patterns      # import every view module (and its throttles)

        def subclasses(cls):
            for sub in cls.__subclasses__():
                yield sub
                yield from subclasses(sub)

        ours = [c for c in subclasses(SimpleRateThrottle)
                if c.__module__.startswith(('apps.', 'core.'))]
        self.assertGreaterEqual(len(ours), 10)
        wrong = [f'{c.__module__}.{c.__name__}' for c in ours if c.cache is not limits.limits_cache]
        self.assertEqual(wrong, [])


@override_settings(CACHES=_caches_with_dead_limits())
class RefusePathTests(TestCase):
    """Redis for the limits is down: the security endpoints refuse, never run without a limit."""

    def setUp(self):
        caches['default'].clear()

    def _assert_refused(self, r):
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data['detail'], limits.LIMITS_UNAVAILABLE_MESSAGE)
        self.assertEqual(r.data['code'], 'limits_unavailable')

    def test_login_refused(self):
        r = APIClient().post('/api/auth/login/', {'username': 'x', 'password': 'y'}, format='json')
        self._assert_refused(r)

    def test_login_lockout_counter_refuses_past_the_throttle(self):
        from apps.users.views import LoginRateThrottle
        with mock.patch.object(LoginRateThrottle, 'allow_request', return_value=True):
            r = APIClient().post('/api/auth/login/', {'username': 'nobody-s2', 'password': 'y'},
                                 format='json')
        self._assert_refused(r)

    def test_public_guard_refuses(self):
        from core import public_guard
        with self.assertRaises(limits.LimitsUnavailable):
            # a valid-looking submission reaches the replay key first
            with mock.patch.object(public_guard, 'leading_zero_bits', return_value=64), \
                    mock.patch('core.public_guard.time.time', return_value=10_000.0):
                challenge = public_guard.signing.dumps(
                    {'id': 'x1', 'form': 'notify', 'iat': 9_990}, salt=public_guard.SALT)
                public_guard.check_submission(
                    {'challenge': challenge, 'nonce': '1'}, 'notify', phone='01000000000')

    def test_mfa_code_replay_check_refuses(self):
        from apps.users import mfa
        profile = mock.Mock(pk=1, mfa_secret='JBSWY3DPEHPK3PXP')
        with mock.patch.object(mfa, '_totp_step', return_value=5):
            with self.assertRaises(limits.LimitsUnavailable):
                mfa.verify_login_code(profile, '123456')

    def test_plain_cache_still_works(self):
        caches['default'].set('plain', 1, 10)
        self.assertEqual(caches['default'].get('plain'), 1)


@override_settings(CACHES=_caches_with_dead_limits())
class BulkReadFailClosedTests(TestCase):

    def _run(self, mode):
        from apps.access import bulk_read
        from apps.access.export_middleware import ExportAuditMiddleware
        mw = ExportAuditMiddleware(lambda r: HttpResponse('[]'))
        user = mock.Mock(is_authenticated=True, pk=7, is_superuser=False)
        request = RequestFactory().get('/api/customers/')
        request.user = user
        with override_settings(BULK_READ_ENFORCEMENT=mode), \
                mock.patch('apps.access.policy_middleware._user', return_value=user), \
                mock.patch.object(bulk_read, 'rows_in', return_value=5), \
                mock.patch.object(bulk_read, 'blocked', return_value=False):
            return mw(request)

    def test_enforce_refuses_when_counter_cannot_be_written(self):
        r = self._run('enforce')
        self.assertEqual(r.status_code, 503)
        self.assertIn(limits.LIMITS_UNAVAILABLE_MESSAGE, r.content.decode())

    def test_log_mode_keeps_the_response(self):
        r = self._run('log')
        self.assertEqual(r.status_code, 200)


class StatementTimeoutTests(TestCase):

    def _show_inside_request(self):
        from core.middleware.statement_timeout import WebStatementTimeoutMiddleware
        seen = {}

        def view(request):
            with connection.cursor() as cur:
                cur.execute('SHOW statement_timeout')
                seen['value'] = cur.fetchone()[0]
            return HttpResponse('ok')

        WebStatementTimeoutMiddleware(view)(RequestFactory().get('/api/x/'))
        return seen['value']

    def test_off_by_default(self):
        self.assertFalse(settings.WEB_STATEMENT_TIMEOUT_ENABLED)
        self.assertEqual(settings.WEB_STATEMENT_TIMEOUT_MS, 30000)
        self.assertEqual(self._show_inside_request(), '0')

    @override_settings(WEB_STATEMENT_TIMEOUT_ENABLED=True)
    def test_flag_on_sets_30s_inside_a_request(self):
        self.assertEqual(self._show_inside_request(), '30s')

    @override_settings(WEB_STATEMENT_TIMEOUT_ENABLED=True)
    def test_new_connection_outside_a_request_gets_no_limit(self):
        from core.middleware import statement_timeout as st
        cur = mock.Mock()
        conn = mock.MagicMock(alias='default')
        conn.cursor.return_value.__enter__.return_value = cur
        result = {}

        def background():
            st.on_connection_created(sender=None, connection=conn)
            result['calls'] = cur.execute.call_count

        t = threading.Thread(target=background)
        t.start()
        t.join()
        self.assertEqual(result['calls'], 0)

    @override_settings(WEB_STATEMENT_TIMEOUT_ENABLED=True)
    def test_new_connection_on_a_request_thread_gets_the_limit(self):
        from core.middleware import statement_timeout as st
        cur = mock.Mock()
        conn = mock.MagicMock(alias='default')
        conn.cursor.return_value.__enter__.return_value = cur
        with st.web_request_scope(30000):
            st.on_connection_created(sender=None, connection=conn)
        cur.execute.assert_called_once_with('SET statement_timeout = %s', [30000])

    def test_middleware_is_first_in_chain(self):
        self.assertIn('core.middleware.statement_timeout.WebStatementTimeoutMiddleware',
                      settings.MIDDLEWARE[:3])

    def test_timeout_answers_503_arabic(self):
        from django.db.utils import OperationalError
        from core.exceptions import STATEMENT_TIMEOUT_MESSAGE, api_exception_handler
        r = api_exception_handler(
            OperationalError('canceling statement due to statement timeout'), {})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.data['detail'], STATEMENT_TIMEOUT_MESSAGE)


class ConnectionSettingsTests(SimpleTestCase):

    def test_conn_max_age_defaults_to_zero_with_health_checks(self):
        db = settings.DATABASES['default']
        self.assertEqual(db['CONN_MAX_AGE'], 0)
        self.assertTrue(db['CONN_HEALTH_CHECKS'])
        self.assertEqual(settings.DATABASES['audit_log']['CONN_MAX_AGE'], 0)
