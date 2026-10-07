"""
apps/tests/test_auth_cookies.py

Staff session in httpOnly cookies (core/auth_cookies.py):
  login / 2FA set the cookies; refresh rotates from the cookie without exposing
  tokens to page script; logout blacklists + clears; cookie-authenticated writes
  need X-Requested-With (CSRF); Bearer header keeps working; WebSocket handshake
  authenticates from the cookie; legacy body-refresh migrates old browsers.
"""
from asgiref.sync import async_to_sync
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from core.auth_cookies import ACCESS_COOKIE, REFRESH_COOKIE, REFRESH_COOKIE_PATH

from .factories import make_branch, make_user

XHR = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


class CookieSessionTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.user, self.profile, _ = make_user('cookie_user', role='admin', branch=self.branch,
                                               password='Secret123', access_all=True)
        self.client = APIClient()

    def _login(self):
        r = self.client.post('/api/auth/login/', {'username': 'cookie_user', 'password': 'Secret123'},
                             format='json')
        self.assertEqual(r.status_code, 200)
        return r

    def test_login_sets_httponly_strict_cookies(self):
        r = self._login()
        access, refresh = r.cookies[ACCESS_COOKIE], r.cookies[REFRESH_COOKIE]
        for c in (access, refresh):
            self.assertTrue(c['httponly'])
            self.assertEqual(c['samesite'], 'Strict')
        self.assertEqual(access['path'], '/')
        self.assertEqual(refresh['path'], REFRESH_COOKIE_PATH)

    @override_settings(AUTH_COOKIE_SECURE=True)
    def test_secure_flag_when_https(self):
        self.assertTrue(self._login().cookies[ACCESS_COOKIE]['secure'])

    def test_cookie_alone_authenticates_reads(self):
        self._login()
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 200)

    def test_cookie_write_requires_xhr_header(self):
        self._login()
        body = {'old_password': 'Secret123', 'new_password': 'Secret456', 'confirm_password': 'Secret456'}
        r = self.client.post('/api/auth/change-password/', body, format='json')
        self.assertIn(r.status_code, (401, 403))           # forged cross-site POST → anonymous
        r = self.client.post('/api/auth/change-password/', body, format='json', **XHR)
        self.assertEqual(r.status_code, 200)

    def test_bearer_header_still_works_without_xhr(self):
        token = RefreshToken.for_user(self.user).access_token
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        self.assertEqual(c.get('/api/auth/me/').status_code, 200)

    def test_cookie_refresh_rotates_without_exposing_tokens(self):
        self._login()
        old_refresh = self.client.cookies[REFRESH_COOKIE].value
        r = self.client.post('/api/auth/refresh/', {}, format='json', **XHR)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('access', r.json())
        self.assertNotIn('refresh', r.json())
        self.assertNotEqual(r.cookies[REFRESH_COOKIE].value, old_refresh)     # rotated
        # the old refresh token is blacklisted after rotation
        c = APIClient()
        c.cookies[REFRESH_COOKIE] = old_refresh
        self.assertEqual(c.post('/api/auth/refresh/', {}, format='json', **XHR).status_code, 401)

    def test_legacy_body_refresh_migrates_to_cookies(self):
        legacy = str(RefreshToken.for_user(self.user))
        r = APIClient().post('/api/auth/refresh/', {'refresh': legacy}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.json())                 # old clients keep their contract
        self.assertIn(ACCESS_COOKIE, r.cookies)           # …and the browser gets cookies

    def test_refresh_without_session(self):
        self.assertEqual(APIClient().post('/api/auth/refresh/', {}, format='json').status_code, 401)

    def test_logout_blacklists_and_clears(self):
        self._login()
        refresh = self.client.cookies[REFRESH_COOKIE].value
        r = self.client.post('/api/auth/logout/', {}, format='json', **XHR)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.cookies[ACCESS_COOKIE].value, '')
        self.assertEqual(r.cookies[REFRESH_COOKIE].value, '')
        c = APIClient()
        c.cookies[REFRESH_COOKIE] = refresh
        self.assertEqual(c.post('/api/auth/refresh/', {}, format='json').status_code, 401)

    def test_public_form_still_works_from_logged_in_browser(self):
        self._login()   # cookie present, plain fetch → no X-Requested-With
        r = self.client.post('/api/demand/public/interest/', {}, format='json')
        self.assertNotIn(r.status_code, (401, 403, 500))

    def test_invalid_cookie_is_401_not_500(self):
        c = APIClient()
        c.cookies[ACCESS_COOKIE] = 'garbage'
        self.assertEqual(c.get('/api/auth/me/').status_code, 401)


class WebSocketCookieAuthTests(TestCase):
    """Which token the handshake hands to the validator (user lookup itself runs
    on another thread via database_sync_to_async, outside the test transaction)."""

    def _token_seen(self, scope):
        from unittest import mock
        from apps.notifications.middleware import JWTAuthMiddleware
        seen = {}

        async def fake(self_, token):
            seen['token'] = token
            return 'USER'

        with mock.patch.object(JWTAuthMiddleware, '_get_user_from_token', fake):
            result = async_to_sync(JWTAuthMiddleware(None)._authenticate)(scope)
        return seen.get('token'), result

    def test_cookie_handshake_uses_access_cookie(self):
        scope = {'type': 'websocket', 'query_string': b'',
                 'headers': [(b'cookie', f'other=1; {ACCESS_COOKIE}=tok123'.encode())]}
        self.assertEqual(self._token_seen(scope), ('tok123', 'USER'))

    def test_legacy_query_token_still_accepted(self):
        scope = {'type': 'websocket', 'query_string': b'token=legacy9', 'headers': []}
        self.assertEqual(self._token_seen(scope), ('legacy9', 'USER'))

    def test_no_credentials_is_anonymous(self):
        token, user = self._token_seen({'type': 'websocket', 'query_string': b'', 'headers': []})
        self.assertIsNone(token)
        self.assertFalse(user.is_authenticated)
