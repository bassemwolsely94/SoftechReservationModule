"""
apps/tests/test_endpoint_sweep.py

System-wide sweeps over EVERY URL pattern the project serves:

  1. Public-surface inventory — the set of views that accept anonymous callers
     (AllowAny / empty permission_classes) must equal KNOWN_PUBLIC_VIEWS. Adding a
     new public endpoint fails this test until it is reviewed and listed here.
  2. Anonymous sweep — every other API route, called without credentials (GET and
     POST), must answer 401/403/404/405: never 2xx (data leak) and never 500.
  3. Authenticated GET smoke — every API route, called as an admin while SOFTECH,
     the JVM and the internet are unreachable, must not answer 500. (Reads only:
     no POST/PUT/DELETE is sent, so nothing is created or pushed anywhere.)

Routes are rendered from their patterns with placeholder arguments (ids → 1), so
detail routes mostly answer 404 — that still exercises auth and dispatch.
"""
import re
from unittest import mock

from django.contrib.auth.models import User
from django.db import transaction
from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny
from rest_framework.test import APIClient

from .factories import make_branch, make_user


# Reviewed public endpoints (anonymous access is intentional). Keep in sync with
# docs/architecture/04_API_REGISTRY.md when adding one.
KNOWN_PUBLIC_VIEWS = {
    # staff auth + 2FA login steps
    'apps.users.views.login_view', 'apps.users.views.refresh_view',
    # customer self-service portal (own magic-link auth inside the views)
    'apps.portal.views',
    # inbound webhooks (signature / secret-token checked inside the views)
    'apps.whatsapp.views.WebhookView', 'apps.social.views.MetaGraphWebhookView',
    'apps.social.views.TelegramWebhookView', 'apps.social.views.TikTokWebhookView',
    # public appearance theme (PUT checks admin inside), public demand capture,
    # tokenised delivery tracking, signed PBX recording links
    'apps.config.views.theme',
    'apps.demand.views.public_item_lookup', 'apps.demand.views.public_branches',
    'apps.demand.views.public_demand_interest',
    'apps.delivery.views.delivery_public_track',
    'apps.pbx.views.RecordingView',
    'apps.users.mfa',
}

_CONVERTERS = {
    'int': '1', 'str': 'x', 'slug': 'x', 'path': 'x',
    'uuid': '00000000-0000-0000-0000-000000000000',
}


def _render(pattern_str):
    """Turn a route/regex pattern into a concrete path, or None if not renderable."""
    s = pattern_str
    if s.startswith('^'):
        if 'format' in s:
            return None                         # DRF format-suffix duplicates
        s = s.lstrip('^').rstrip('$')
        s = re.sub(r'\(\?P<[^>]+>[^)]*\)', '1', s)
        s = s.replace('\\.', '.').replace('\\/', '/')
        if re.search(r'[()\[\]*+?|\\]', s):
            return None
        return s
    s = re.sub(r'<(?:(\w+):)?\w+>', lambda m: _CONVERTERS.get(m.group(1) or 'str', 'x'), s)
    return s


def _walk(patterns, prefix=''):
    for p in patterns:
        part = _render(str(p.pattern))
        if part is None:
            continue
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + part)
        elif isinstance(p, URLPattern):
            yield '/' + prefix + part, p.callback


def _view_id(callback):
    cls = getattr(callback, 'cls', None) or getattr(callback, 'view_class', None)
    if cls is not None:
        return f'{cls.__module__}.{cls.__name__}', cls
    return f'{callback.__module__}.{callback.__name__}', cls


def _is_public(cls):
    perms = list(getattr(cls, 'permission_classes', None) or [])
    return cls is not None and (not perms or AllowAny in perms)


def _api_routes():
    seen = set()
    for path, cb in _walk(get_resolver().url_patterns):
        if path.startswith('/api/') and path not in seen:
            seen.add(path)
            yield path, cb


def _known(view_id):
    return any(view_id == k or view_id.startswith(k + '.') for k in KNOWN_PUBLIC_VIEWS)


class _Offline:
    """SOFTECH / JVM / outbound HTTP all unreachable for the duration."""

    def __enter__(self):
        boom = ConnectionError('offline in tests')
        self._patches = [
            mock.patch('config.sybase._ensure_jvm', side_effect=boom),
            mock.patch('requests.sessions.Session.request', side_effect=boom),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class PublicSurfaceInventoryTests(TestCase):

    def test_public_views_are_exactly_the_reviewed_set(self):
        public = sorted({vid for _, cb in _api_routes()
                         for vid, cls in [_view_id(cb)] if _is_public(cls)})
        unexpected = [v for v in public if not _known(v)]
        self.assertEqual(unexpected, [], 'New anonymous endpoint(s) — review, then add to '
                                         'KNOWN_PUBLIC_VIEWS:\n' + '\n'.join(unexpected))

    def test_sweep_sees_the_whole_api(self):
        self.assertGreater(len(list(_api_routes())), 500)


class AnonymousSweepTests(TestCase):

    def test_protected_routes_reject_anonymous_callers(self):
        client = APIClient()
        problems = []
        with _Offline():
            for path, cb in _api_routes():
                vid, cls = _view_id(cb)
                if _is_public(cls) or _known(vid):
                    continue
                for method in ('get', 'post'):
                    try:
                        with transaction.atomic():   # one failing view must not poison the rest
                            r = client.post(path, {}, format='json') if method == 'post' \
                                else client.get(path)
                        code = r.status_code
                    except Exception as exc:
                        code = f'raised {type(exc).__name__}: {str(exc)[:80]}'
                    # 301 = trailing-slash redirect, 503 = feature switched off
                    # before auth (commerce docs) — neither returns data.
                    if code not in (301, 401, 403, 404, 405, 503):
                        problems.append(f'{method.upper()} {path} → {code} ({vid})')
        self.assertEqual(problems, [], '\n'.join(problems))

    def test_django_admin_requires_login(self):
        r = self.client.get('/admin/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('/admin/login/', r['Location'])


class AuthenticatedGetSmokeTests(TestCase):
    """No GET endpoint may crash (500) when SOFTECH / the internet are down."""

    def test_no_get_endpoint_crashes_while_softech_offline(self):
        branch = make_branch()
        user, _, client = make_user('sweep_admin', role='admin', branch=branch, access_all=True)
        User.objects.filter(pk=user.pk).update(is_staff=True, is_superuser=True)
        user.refresh_from_db()
        client.force_authenticate(user=user)
        crashes = []
        with _Offline():
            for path, cb in _api_routes():
                vid, _ = _view_id(cb)
                if 'webhook' in path:
                    continue
                try:
                    with transaction.atomic():       # one failing view must not poison the rest
                        r = client.get(path)
                    code = r.status_code
                except Exception as exc:          # raised through the test client
                    code = f'raised {type(exc).__name__}: {str(exc)[:80]}'
                if code == 500 or isinstance(code, str):
                    crashes.append(f'GET {path} → {code} ({vid})')
        self.assertEqual(crashes, [], f'{len(crashes)} GET endpoint(s) crash:\n' + '\n'.join(crashes))
