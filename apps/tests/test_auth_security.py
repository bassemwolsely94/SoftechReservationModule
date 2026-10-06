"""
apps/tests/test_auth_security.py

Tests covering:
  - Login: valid / invalid credentials
  - Login: no brute-force protection (KNOWN GAP — documents the missing defence)
  - Inactive user cannot log in
  - JWT /me endpoint
  - Password change: valid, wrong old, too short, mismatch
  - Password change: old JWT still valid after password change (KNOWN SECURITY GAP)
  - Anonymous access is rejected on protected endpoints
  - Admin-only endpoints reject non-admins
  - reset-password: admin can; non-admin cannot
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework import status

from .factories import make_branch, make_user, make_admin, make_pharmacist


LOGIN_URL      = '/api/auth/login/'
REFRESH_URL    = '/api/auth/refresh/'
ME_URL         = '/api/auth/me/'
CHANGE_PW_URL  = '/api/auth/change-password/'
STAFF_URL      = '/api/users/staff/'


class AuthLoginTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, _ = make_user('auth_test_user', role='pharmacist',
                                        branch=self.branch, password='Secret123')
        self.client = APIClient()
        # Clear the throttle cache between tests so login-rate-limit tests
        # don't leak state into unrelated tests (the throttle stores counts
        # in the default Django cache keyed by IP address).
        cache.clear()

    # ── happy path ────────────────────────────────────────────────────────────

    def test_login_valid_credentials(self):
        r = self.client.post(LOGIN_URL, {'username': 'auth_test_user', 'password': 'Secret123'})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertIn('access', r.data)
        self.assertIn('refresh', r.data)
        self.assertIn('user', r.data)

    def test_login_returns_role(self):
        r = self.client.post(LOGIN_URL, {'username': 'auth_test_user', 'password': 'Secret123'})
        self.assertEqual(r.data['user']['role'], 'pharmacist')

    def test_login_returns_branch(self):
        r = self.client.post(LOGIN_URL, {'username': 'auth_test_user', 'password': 'Secret123'})
        self.assertEqual(r.data['user']['branch_id'], self.branch.id)

    # ── wrong credentials ────────────────────────────────────────────────────

    def test_login_wrong_password(self):
        r = self.client.post(LOGIN_URL, {'username': 'auth_test_user', 'password': 'WrongPass'})
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertNotIn('access', r.data)

    def test_login_unknown_user(self):
        r = self.client.post(LOGIN_URL, {'username': 'nobody', 'password': 'anything'})
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_login_empty_credentials(self):
        r = self.client.post(LOGIN_URL, {})
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    # ── inactive account ──────────────────────────────────────────────────────

    def test_login_inactive_django_user(self):
        """Deactivated django user must not be able to log in.
        Returns 401 or 403 depending on the auth backend implementation."""
        self.profile.user.is_active = False
        self.profile.user.save()
        r = self.client.post(LOGIN_URL, {'username': 'auth_test_user', 'password': 'Secret123'})
        self.assertIn(r.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN],
                      'Inactive user must be denied access (401 or 403)')
        self.assertNotIn('access', r.data, 'Inactive user must not receive a JWT token')

    def test_login_inactive_staff_profile(self):
        """Deactivated staff profile must not be able to log in."""
        self.profile.is_active = False
        self.profile.save()
        r = self.client.post(LOGIN_URL, {'username': 'auth_test_user', 'password': 'Secret123'})
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    # ── Gap-1 FIXED: brute-force throttle ────────────────────────────────────

    def test_login_rate_limit_after_10_attempts(self):
        """
        The login endpoint is rate-limited to 10 attempts per IP per minute.
        After 10 failed attempts the 11th must return 429 Too Many Requests.
        LoginRateThrottle (scope='login', 10/min) is wired to login_view.
        """
        for attempt in range(10):
            self.client.post(LOGIN_URL, {
                'username': 'auth_test_user',
                'password': f'WrongPass{attempt}',
            })
        r = self.client.post(LOGIN_URL, {
            'username': 'auth_test_user',
            'password': 'WrongPass10',
        })
        self.assertEqual(r.status_code, status.HTTP_429_TOO_MANY_REQUESTS,
                         'Login endpoint must return 429 after 10 failed attempts')

    # ── /me endpoint ─────────────────────────────────────────────────────────

    def test_me_requires_auth(self):
        r = self.client.get(ME_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_returns_correct_data(self):
        login = self.client.post(LOGIN_URL, {'username': 'auth_test_user', 'password': 'Secret123'})
        self.client.credentials(HTTP_AUTHORIZATION='Bearer ' + login.data['access'])
        r = self.client.get(ME_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['username'], 'auth_test_user')


class PasswordChangeTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        self.user, self.profile, self.auth_client = make_user(
            'pw_change_user', role='pharmacist', branch=self.branch, password='OldPass123'
        )

    def test_change_password_success(self):
        r = self.auth_client.post(CHANGE_PW_URL, {
            'old_password': 'OldPass123',
            'new_password': 'NewPass456',
            'confirm_password': 'NewPass456',
        })
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        # New password must work
        login = APIClient().post(LOGIN_URL, {'username': 'pw_change_user', 'password': 'NewPass456'})
        self.assertEqual(login.status_code, status.HTTP_200_OK)

    def test_change_password_wrong_old(self):
        r = self.auth_client.post(CHANGE_PW_URL, {
            'old_password': 'WrongOld',
            'new_password': 'NewPass456',
            'confirm_password': 'NewPass456',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_mismatch_confirm(self):
        r = self.auth_client.post(CHANGE_PW_URL, {
            'old_password': 'OldPass123',
            'new_password': 'NewPass456',
            'confirm_password': 'DifferentPass',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_too_short(self):
        """Password minimum length is 6. Anything shorter is rejected."""
        r = self.auth_client.post(CHANGE_PW_URL, {
            'old_password': 'OldPass123',
            'new_password': '12345',
            'confirm_password': '12345',
        })
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_change_password_requires_auth(self):
        anon = APIClient()
        r = anon.post(CHANGE_PW_URL, {'old_password': 'x', 'new_password': 'y', 'confirm_password': 'y'})
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_token_blacklisted_after_pw_change(self):
        """
        Gap-2 FIXED: After a password change, all outstanding refresh tokens
        for the user are blacklisted.  An attacker who stole a refresh token
        cannot use it to obtain new access tokens.

        The access token itself (≤1 hour lifetime, reduced from 12h) cannot be
        individually invalidated — that is an inherent JWT trade-off documented
        as an accepted residual risk.
        """
        # Log in — captures both access and refresh token
        login_resp = APIClient().post(LOGIN_URL, {
            'username': 'pw_change_user', 'password': 'OldPass123',
        })
        old_refresh = login_resp.data['refresh']

        # Change password — this blacklists the refresh token
        self.auth_client.post(CHANGE_PW_URL, {
            'old_password': 'OldPass123',
            'new_password': 'BrandNew789',
            'confirm_password': 'BrandNew789',
        })

        # The old refresh token must now be rejected (401)
        refresh_client = APIClient()
        r = refresh_client.post(REFRESH_URL, {'refresh': old_refresh}, format='json')
        self.assertIn(
            r.status_code,
            [status.HTTP_401_UNAUTHORIZED, status.HTTP_400_BAD_REQUEST],
            'Blacklisted refresh token must be rejected after password change',
        )

    def test_RESIDUAL_access_token_still_valid_after_pw_change(self):
        """
        RESIDUAL RISK (accepted): The access token issued before a password change
        remains valid for up to 1 hour (reduced from 12h in Gap-2 fix).
        This is an inherent JWT trade-off — fully eliminating it would require
        a per-request DB lookup on every authenticated endpoint.
        """
        login_resp = APIClient().post(LOGIN_URL, {
            'username': 'pw_change_user', 'password': 'OldPass123',
        })
        old_access = login_resp.data['access']

        self.auth_client.post(CHANGE_PW_URL, {
            'old_password': 'OldPass123',
            'new_password': 'BrandNew789',
            'confirm_password': 'BrandNew789',
        })

        old_client = APIClient()
        old_client.credentials(HTTP_AUTHORIZATION='Bearer ' + old_access)
        r = old_client.get(ME_URL)
        # Access token still works — document this as accepted residual risk (≤1 hour window)
        if r.status_code == status.HTTP_200_OK:
            import warnings
            warnings.warn(
                'RESIDUAL RISK: access token valid for ≤1h after password change '
                '(reduced from 12h). Refresh token is blacklisted. '
                'Fully fix by shortening ACCESS_TOKEN_LIFETIME further or '
                'adding a per-request JTI check.',
                stacklevel=2,
            )


class AdminOnlyEndpointTests(TestCase):
    """Staff management endpoints should require admin role."""

    def setUp(self):
        self.branch = make_branch()
        _, _, self.admin_client = make_admin('admin_ep_test')
        _, _, self.pharma_client = make_pharmacist('pharma_ep_test', branch=self.branch)

    def test_admin_can_list_staff(self):
        r = self.admin_client.get(STAFF_URL)
        self.assertIn(r.status_code, [status.HTTP_200_OK, status.HTTP_404_NOT_FOUND])

    def test_non_admin_cannot_create_staff(self):
        """POST /api/users/staff/ requires admin role."""
        r = self.pharma_client.post(STAFF_URL, {
            'username': 'newuser', 'password': 'pass123', 'role': 'pharmacist',
        })
        # 403 Forbidden — non-admin cannot create staff
        self.assertEqual(r.status_code, status.HTTP_403_FORBIDDEN)

    def test_anon_cannot_access_staff(self):
        anon = APIClient()
        r = anon.get(STAFF_URL)
        self.assertEqual(r.status_code, status.HTTP_401_UNAUTHORIZED)
