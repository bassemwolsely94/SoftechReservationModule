"""N6 / Task 1 - anonymous allow-list gate for /api/."""
import re
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny

from apps.access import preflight
from apps.access.checks import public_api_settings_check
from apps.access.public_middleware import DENY_MESSAGE, PublicApiMiddleware, mode
from apps.access.public_paths import PUBLIC_GET_ONLY, PUBLIC_PREFIXES, is_public

BASE = Path(settings.BASE_DIR)


def _gate(request_path='/api/customers/', method='get', user_id=None, access=True):
    """Run the middleware alone; returns (response, whether the view was reached)."""
    reached = []

    def view(req):
        reached.append(1)
        return HttpResponse('ok')

    req = getattr(RequestFactory(), method)(request_path)
    if access:
        req.access = SimpleNamespace(user_id=user_id, network=SimpleNamespace(ip='41.1.1.1'))
    return PublicApiMiddleware(view)(req), bool(reached)


def _not_gate_refusal(response):
    """True when the response is not the gate's own 401."""
    if response.status_code != 401:
        return True
    return DENY_MESSAGE not in response.content.decode('utf-8')


@override_settings(PUBLIC_API_ENFORCEMENT='enforce')
class PublicGateTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_anonymous_unlisted_api_refused_in_enforce(self):
        resp = self.client.get('/api/customers/')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json(), {'detail': DENY_MESSAGE})

    def test_anonymous_unlisted_logged_in_log_mode(self):
        with override_settings(PUBLIC_API_ENFORCEMENT='log'):
            with self.assertLogs('elrezeiky.access', 'WARNING') as cm:
                resp, reached = _gate('/api/customers/')
                _gate('/api/customers/')   # deduped: still one line
        self.assertTrue(reached)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(cm.output), 1)
        self.assertIn('public gate would-deny GET /api/customers/ ip=41.1.1.1', cm.output[0])

    def test_off_mode_does_nothing(self):
        with override_settings(PUBLIC_API_ENFORCEMENT='off'):
            resp, reached = _gate('/api/customers/')
        self.assertTrue(reached)

    def test_listed_public_paths_reach_their_views(self):
        for method, path, kw in (
            ('get', '/api/demand/public/item/?id=0', {}),
            ('get', '/api/demand/public/branches/', {}),
            ('get', '/api/delivery/track/nope/', {}),
            ('post', '/api/portal/request-link/', {'data': {'phone': 'x'}, 'content_type': 'application/json'}),
            ('get', '/api/config/theme/', {}),
            ('post', '/api/csp-report/', {'data': '{}', 'content_type': 'application/csp-report'}),
            ('get', '/api/access/whoami/', {}),
            ('post', '/api/auth/login/', {'data': {}, 'content_type': 'application/json'}),
            ('get', '/api/whatsapp/webhook/', {}),
            ('get', '/api/social/webhook/meta/', {}),
        ):
            cache.clear()
            resp = getattr(self.client, method)(path, **kw)
            self.assertTrue(_not_gate_refusal(resp), f'{method} {path} refused by the gate')

    def test_theme_put_anonymous_refused(self):
        resp = self.client.put('/api/config/theme/', data={'primary': '#112233'},
                               content_type='application/json')
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json(), {'detail': DENY_MESSAGE})
        self.assertTrue(is_public('/api/config/theme/', 'GET'))
        self.assertFalse(is_public('/api/config/theme/', 'PUT'))
        self.assertFalse(is_public('/api/config/theme/', 'POST'))

    def test_signed_in_staff_never_gated(self):
        resp, reached = _gate('/api/customers/', user_id=7)
        self.assertTrue(reached)
        self.assertEqual(resp.status_code, 200)
        resp, reached = _gate('/api/config/theme/', method='put', user_id=7)
        self.assertTrue(reached)

    def test_missing_access_is_anonymous(self):
        resp, reached = _gate('/api/customers/', access=False)
        self.assertFalse(reached)
        self.assertEqual(resp.status_code, 401)

    def test_non_api_paths_untouched(self):
        resp, reached = _gate('/media/x.png')
        self.assertTrue(reached)

    def test_portal_session_paths_allowed(self):
        for path in ('/api/portal/me/', '/api/portal/orders/', '/api/portal/loyalty/',
                     '/api/portal/refills/', '/api/portal/reorder/', '/api/portal/logout/'):
            resp, reached = _gate(path)
            self.assertTrue(reached, path)

    def test_internal_error_refuses_in_enforce_passes_in_log(self):
        from unittest import mock
        with mock.patch('apps.access.public_middleware.is_public', side_effect=RuntimeError('boom')):
            with self.assertLogs('elrezeiky.access', 'ERROR'):
                resp, reached = _gate('/api/customers/')
            self.assertEqual(resp.status_code, 401)
            self.assertFalse(reached)
            with override_settings(PUBLIC_API_ENFORCEMENT='log'):
                with self.assertLogs('elrezeiky.access', 'ERROR'):
                    resp, reached = _gate('/api/customers/')
                self.assertTrue(reached)

    def test_unknown_mode_is_log_and_w005(self):
        with override_settings(PUBLIC_API_ENFORCEMENT='enfroce'):
            self.assertEqual(mode(), 'log')
            self.assertIn('access.W005', [m.id for m in public_api_settings_check(None)])
            resp, reached = _gate('/api/customers/')
            self.assertTrue(reached)
        with override_settings(PUBLIC_API_ENFORCEMENT='enforce'):
            self.assertEqual(public_api_settings_check(None), [])

    def test_preflight_item(self):
        items = preflight.check_public_api()
        self.assertEqual([i.code for i in items], ['public_api_mode'])
        self.assertEqual(items[0].level, preflight.OK)
        with override_settings(PUBLIC_API_ENFORCEMENT='log'):
            self.assertEqual(preflight.check_public_api()[0].level, preflight.WARN)

    def test_middleware_sits_right_after_access_context(self):
        mw = settings.MIDDLEWARE
        self.assertEqual(mw.index('apps.access.public_middleware.PublicApiMiddleware'),
                         mw.index('apps.access.middleware.AccessContextMiddleware') + 1)


# --- the scan: every view an anonymous request can reach must be listed -----------------------

# A decorator / attribute that lets a request through without a staff session, followed by the
# name of the function or class it applies to.
_ANON_MARKERS = re.compile(
    r'AllowAny|authentication_classes\(\[\]\)|permission_classes\(\[\]\)|'
    r'permission_classes\s*=\s*(\[\s*\]|\(\s*\))|csrf_exempt')
_DEF = re.compile(r'^(?:async\s+)?(?:def|class)\s+(\w+)')


def _anonymous_view_names():
    """(file, name) of every def/class in apps/**/views*.py, apps/**/mfa.py, core/*.py that carries
    an anonymous marker in its decorators or class body. Imports and `permission_classes` assigned
    to something other than a view are ignored by requiring a def/class to own the marker."""
    files = sorted(set(BASE.glob('apps/**/views*.py')) | set(BASE.glob('apps/users/mfa.py'))
                   | set(BASE.glob('core/*.py')))
    found = []
    for f in files:
        if 'tests' in f.parts:
            continue
        lines = f.read_text(encoding='utf-8').splitlines()
        for i, line in enumerate(lines):
            if line.lstrip().startswith(('from ', 'import ', '#')) or not _ANON_MARKERS.search(line):
                continue
            if line.startswith((' ', '\t')) and 'permission_classes' not in line:
                continue
            # decorator form: owner is the next def/class below; class-body form: nearest above
            owner = None
            if line.startswith('@'):
                for nxt in lines[i + 1:i + 12]:
                    m = _DEF.match(nxt)
                    if m:
                        owner = m.group(1)
                        break
            else:
                for prev in reversed(lines[:i]):
                    m = _DEF.match(prev)
                    if m:
                        owner = m.group(1)
                        break
            if owner:
                found.append((f.relative_to(BASE).as_posix(), owner))
    return found


def _walk(patterns, prefix=''):
    for p in patterns:
        route = prefix + str(p.pattern)
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, route)
        elif isinstance(p, URLPattern):
            yield route, p.callback


def _sample(route):
    route = re.sub(r'<(?:\w+:)?\w+>', '1', route)
    route = re.sub(r'\(\?P<\w+>[^)]*\)', '1', route)
    route = route.replace('^', '').replace('$', '').replace('\\Z', '').replace('\\.', '.')
    return '/' + route.lstrip('/')


def _view_class(callback):
    return getattr(callback, 'cls', None) or getattr(callback, 'view_class', None)


class EveryAnonymousViewIsListedTests(SimpleTestCase):
    """If this fails for a new view: it can be reached without a staff session, so either list it
    in apps/access/public_paths.py (with a comment naming it) or give it real authentication."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.routes = [(r, cb) for r, cb in _walk(get_resolver().url_patterns)
                      if r.startswith('api/')]

    def test_scan_finds_the_known_views(self):
        names = {n for _, n in _anonymous_view_names()}
        for expected in ('login_view', 'whoami', 'theme', 'csp_report', 'request_link',
                         'public_item_lookup', 'delivery_public_track', 'RecordingView',
                         'MetaGraphWebhookView', 'TelegramWebhookView', 'WebhookView',
                         'verify_2fa_view'):
            self.assertIn(expected, names)

    def test_every_anonymous_view_by_source_is_listed(self):
        by_name = {}
        for route, cb in self.routes:
            by_name.setdefault(getattr(cb, '__name__', ''), []).append(route)
            klass = _view_class(cb)
            if klass is not None:
                by_name.setdefault(klass.__name__, []).append(route)
        for file, name in _anonymous_view_names():
            routes = by_name.get(name)
            if not routes:
                # Not mounted under /api/ (e.g. core.media is outside /api/) - nothing to gate.
                continue
            self.assertTrue(
                any(is_public(_sample(r), m) for r in routes for m in ('GET', 'POST')),
                f'{file}:{name} is reachable anonymously at {routes} but not in PUBLIC_PREFIXES')

    def test_every_anonymous_view_by_permission_classes_is_listed(self):
        """Independent of the source text: ask each mounted DRF view what it lets through."""
        for route, cb in self.routes:
            klass = _view_class(cb)
            perms = getattr(klass, 'permission_classes', None)
            if perms is None:
                continue
            if perms and not any(issubclass(p, AllowAny) for p in perms):
                continue
            methods = [m.upper() for m in ('get', 'post', 'put', 'patch', 'delete') if hasattr(klass, m)]
            path = _sample(route)
            self.assertTrue(any(is_public(path, m) for m in methods),
                            f'{klass.__name__} at {path} lets anonymous requests through '
                            'but is not in PUBLIC_PREFIXES')

    def test_every_listed_entry_is_a_real_route(self):
        paths = [_sample(r) for r, _ in self.routes]
        for prefix in PUBLIC_PREFIXES:
            self.assertTrue(any(p.startswith(prefix) for p in paths), f'{prefix} matches no route')
        for prefix in PUBLIC_GET_ONLY:
            self.assertIn(prefix, PUBLIC_PREFIXES)
