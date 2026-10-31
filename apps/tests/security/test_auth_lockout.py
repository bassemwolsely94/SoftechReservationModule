"""
Authentication — per-account login lockout (security batch N0, H8).

Before: only a per-IP throttle (10/min), so a guesser rotating addresses could try passwords
at will. Now 5 wrong passwords / wrong 2FA codes in 15 minutes lock the ACCOUNT for 15 minutes;
an unknown identifier behaves the same; an admin can lift the lock.
"""
from datetime import timedelta
from unittest import mock

import pyotp
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.notifications.models import Notification
from apps.tests.factories import make_user
from apps.users.models import UserActivityLog
from apps.users.views import LoginRateThrottle

PASSWORD = 'Lockout-H8-pw!'
LOCKED = 'تم إيقاف الدخول مؤقتاً بسبب محاولات خاطئة متكررة. حاول بعد 15 دقيقة أو تواصل مع المدير'
BAD = 'بيانات الدخول غير صحيحة'


class LoginLockoutTests(TestCase):

    def setUp(self):
        cache.clear()
        # the per-IP throttle (10/min) is not what these tests exercise
        patcher = mock.patch.object(LoginRateThrottle, 'allow_request', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user, self.profile, self.me = make_user('h8_user', role='pharmacist', password=PASSWORD)
        self.admin_user, self.admin_profile, self.admin = make_user('h8_admin', role='admin', password=PASSWORD)

    def _login(self, username='h8_user', password=PASSWORD):
        return APIClient().post('/api/auth/login/', {'username': username, 'password': password}, format='json')

    def _bad(self, n, username='h8_user'):
        for _ in range(n):
            self.assertEqual(self._login(username, 'wrong-pw').status_code, 401)

    def _actions(self, action):
        return UserActivityLog.objects.filter(target_user=self.profile, action=action)

    def test_fifth_wrong_password_locks(self):
        self._bad(5)
        r = self._login()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.data['error'], LOCKED)
        self.assertEqual(self._actions('login_locked').count(), 1)

    def test_lock_expires_after_15_minutes(self):
        self._bad(5)
        self.assertEqual(self._login().status_code, 429)
        UserActivityLog.objects.filter(target_user=self.profile).update(
            created_at=timezone.now() - timedelta(minutes=16))
        self.assertEqual(self._login().status_code, 200)

    def test_success_resets_counter(self):
        self._bad(4)
        self.assertEqual(self._login().status_code, 200)
        self._bad(4)
        self.assertEqual(self._login('h8_user', 'wrong-pw').status_code, 401)   # 5th since the good login

    def test_wrong_2fa_codes_count(self):
        user, profile, me = make_user('h8_mfa', role='purchasing', password=PASSWORD)
        me.post('/api/auth/2fa/setup/', {}, format='json')
        profile.refresh_from_db()
        totp = pyotp.TOTP(profile.mfa_secret)
        me.post('/api/auth/2fa/enable/', {'code': totp.now()}, format='json')
        cache.clear()
        wrong = '000000' if totp.now() != '000000' else '111111'
        token = APIClient().post('/api/auth/login/', {'username': 'h8_mfa', 'password': PASSWORD},
                                 format='json').data['mfa_token']
        for _ in range(5):
            r = APIClient().post('/api/auth/2fa/verify/', {'mfa_token': token, 'code': wrong}, format='json')
            self.assertEqual(r.status_code, 401)
        r = APIClient().post('/api/auth/login/', {'username': 'h8_mfa', 'password': PASSWORD}, format='json')
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.data['error'], LOCKED)
        self.assertEqual(UserActivityLog.objects.filter(target_user=profile, action='login_locked').count(), 1)

    def test_unknown_identifier_same_response(self):
        real_bad = self._login('h8_user', 'wrong-pw')
        for _ in range(5):
            r = self._login('no-such-user', 'wrong-pw')
            self.assertEqual(r.status_code, 401)
            self.assertEqual(r.data, real_bad.data)
        self.assertEqual(r.data['error'], BAD)
        r = self._login('no-such-user', 'wrong-pw')
        self.assertEqual(r.status_code, 429)
        self.assertEqual(r.data['error'], LOCKED)
        self._bad(4)
        real = self._login()
        self.assertEqual((real.status_code, real.data), (r.status_code, r.data))

    def test_admin_unlock(self):
        self._bad(5)
        self.assertEqual(self._login().status_code, 429)
        denied = self.me.post(f'/api/users/{self.profile.id}/unlock-login/', {}, format='json')
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self._login().status_code, 429)
        ok = self.admin.post(f'/api/users/{self.profile.id}/unlock-login/', {}, format='json')
        self.assertEqual(ok.status_code, 200)
        row = self._actions('login_unlocked').get()
        self.assertEqual(row.changed_by, self.admin_profile)
        self.assertEqual(self._login().status_code, 200)

    def test_locked_until_is_exposed_to_the_users_screen(self):
        self._bad(5)
        r = self.admin.get(f'/api/users/staff/{self.profile.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['login_locked_until'])
        listing = self.admin.get('/api/users/staff/', {'search': 'h8_user'})
        row = next(x for x in listing.data['results'] if x['id'] == self.profile.id)
        self.assertTrue(row['login_locked_until'])
        self.admin.post(f'/api/users/{self.profile.id}/unlock-login/', {}, format='json')
        r = self.admin.get(f'/api/users/staff/{self.profile.id}/')
        self.assertIsNone(r.data['login_locked_until'])

    def test_mfa_challenge_not_logged_as_success(self):
        user, profile, me = make_user('h8_chal', role='purchasing', password=PASSWORD)
        me.post('/api/auth/2fa/setup/', {}, format='json')
        profile.refresh_from_db()
        me.post('/api/auth/2fa/enable/', {'code': pyotp.TOTP(profile.mfa_secret).now()}, format='json')
        UserActivityLog.objects.all().delete()
        cache.clear()
        r = APIClient().post('/api/auth/login/', {'username': 'h8_chal', 'password': PASSWORD}, format='json')
        self.assertTrue(r.data['mfa_required'])
        logs = UserActivityLog.objects.filter(target_user=profile)
        self.assertEqual(logs.filter(action='mfa_challenge').count(), 1)
        self.assertFalse(logs.filter(action='login_success').exists())

    def test_admins_notified_once_per_lock(self):
        for _ in range(5):
            self._login('h8_user', 'wrong-pw')
        for _ in range(3):
            self._login('h8_user', 'wrong-pw')       # already locked: 429s, no second alert
        n = Notification.objects.filter(dedup_key=f'login-lock:{self.profile.id}')
        self.assertEqual(n.count(), 1)
        self.assertEqual(n.get().recipient, self.admin_profile)

    # ── the lock must run to last miss + 15 min, for real and unknown accounts alike ──

    def _spread(self, username):
        """Misses at t=0,1,2,3,14 min; then the status at t=16 (wrong pw) and t=30."""
        base = timezone.now()
        out = {}
        for minute in (0, 1, 2, 3, 14):
            with mock.patch('django.utils.timezone.now', return_value=base + timedelta(minutes=minute)):
                self.assertEqual(self._login(username, 'wrong-pw').status_code, 401)
        for minute in (16, 30):
            with mock.patch('django.utils.timezone.now', return_value=base + timedelta(minutes=minute)):
                out[minute] = self._login(username, 'wrong-pw')
        return out

    def test_spread_misses_real_account(self):
        out = self._spread('h8_user')
        self.assertEqual(out[16].status_code, 429)
        self.assertEqual(out[16].data['error'], LOCKED)
        self.assertEqual(out[30].status_code, 401)

    def test_spread_misses_unknown_identifier_matches_real(self):
        out = self._spread('no-such-user')
        self.assertEqual(out[16].status_code, 429)
        self.assertEqual(out[16].data['error'], LOCKED)
        self.assertEqual(out[30].status_code, 401)
