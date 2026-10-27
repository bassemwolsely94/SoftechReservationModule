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

from django.contrib.auth.models import User
from django.db import transaction
from django.test import TestCase
from rest_framework.test import APIClient

from .factories import make_branch, make_user
from .security.routes import (   # shared with the security suite
    Offline as _Offline,
    api_routes as _api_routes,
    is_public as _is_public,
    known_public as _known,
    view_id as _view_id,
)


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
