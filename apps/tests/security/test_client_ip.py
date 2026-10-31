"""
Authentication — the client address can't be forged (Batch 3, A-6; owner decision 2026-10-27:
NUM_PROXIES=1 on the VPS, where nginx appends the real peer to X-Forwarded-For).

Before: the DRF throttles (login 10/min, portal links, public demand) keyed on the WHOLE
X-Forwarded-For string, so a new made-up first entry per request was a fresh bucket — no limit
at all. The audit IP (UserActivityLog, AuditLog) was the FIRST entry, which the client writes,
so a login could be logged from any address the attacker chose — even with no proxy in front.
"""
from django.conf import settings
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from apps.tests.factories import make_user
from apps.users.models import UserActivityLog


LOGIN = '/api/auth/login/'
NGINX = '127.0.0.1'                 # Daphne's peer when nginx is in front
REAL = '203.0.113.9'                # the address nginx saw and appended


def _behind_proxy():
    return override_settings(NUM_PROXIES=1, REST_FRAMEWORK={**settings.REST_FRAMEWORK, 'NUM_PROXIES': 1})


class LoginThrottleTests(TestCase):

    def setUp(self):
        cache.clear()
        make_user('a6_user', role='pharmacist', password='A6-Strong-pw-26')

    def _try(self, forwarded, remote=NGINX, username='a6_user'):
        return APIClient().post(LOGIN, {'username': username, 'password': 'wrong-password'},
                                format='json', REMOTE_ADDR=remote, HTTP_X_FORWARDED_FOR=forwarded)

    def test_made_up_forwarded_for_does_not_dodge_the_limit(self):
        codes = [self._try(f'10.66.{i}.1, {REAL}').status_code for i in range(11)]
        self.assertEqual(codes[-1], 429, f'11 tries in a minute, none throttled: {codes}')

    def test_settings_hand_num_proxies_to_drf(self):
        self.assertEqual(settings.REST_FRAMEWORK.get('NUM_PROXIES'), settings.NUM_PROXIES)

    def test_behind_proxy_the_real_client_is_limited(self):
        with _behind_proxy():
            codes = [self._try(f'10.66.{i}.1, {REAL}').status_code for i in range(11)]
        self.assertEqual(codes[-1], 429)

    def test_behind_proxy_other_clients_are_not_blocked(self):
        with _behind_proxy():
            for i in range(10):
                self._try(f'10.66.{i}.1, {REAL}')
            # another account: ten misses on a6_user now lock THAT account too (N0/H8)
            self.assertNotEqual(self._try('198.51.100.20', username='a6_other').status_code, 429)


class AuditAddressTests(TestCase):

    def setUp(self):
        cache.clear()
        self.user, self.profile, _ = make_user('a6_audit', role='pharmacist', password='A6-Strong-pw-26')

    def _login_ip(self, forwarded, remote):
        APIClient().post(LOGIN, {'username': 'a6_audit', 'password': 'A6-Strong-pw-26'}, format='json',
                         REMOTE_ADDR=remote, HTTP_X_FORWARDED_FOR=forwarded)
        return UserActivityLog.objects.filter(target_user=self.profile).latest('id').ip_address

    def test_behind_proxy_login_is_logged_from_the_real_address(self):
        with _behind_proxy():
            self.assertEqual(self._login_ip(f'6.6.6.6, {REAL}', NGINX), REAL)

    def test_without_proxy_forwarded_for_is_ignored(self):
        with override_settings(NUM_PROXIES=0):
            self.assertEqual(self._login_ip('6.6.6.6', '198.51.100.7'), '198.51.100.7')

    def test_audit_log_address_is_the_real_one(self):
        from apps.audit.models import _get_ip
        request = RequestFactory().get('/', REMOTE_ADDR=NGINX, HTTP_X_FORWARDED_FOR=f'6.6.6.6, {REAL}')
        with override_settings(NUM_PROXIES=1):
            self.assertEqual(_get_ip(request), REAL)


# --- N0 / H6: one trusted client IP, from the code through to nginx ---------------------------------

import re
from pathlib import Path

_ROOT = Path(settings.BASE_DIR)
_PROXY_INCLUDE = 'include /etc/nginx/elrezeiky-proxy-headers.conf;'


def _location_blocks(text):
    """(header, body) for every `location ... {` block, tracked by brace depth."""
    blocks = []
    for m in re.finditer(r'^\s*location\s[^{]*\{', text, re.M):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {'{': 1, '}': -1}.get(text[i], 0)
            i += 1
        blocks.append((m.group(0).strip(), text[m.end():i - 1]))
    return blocks


class TrustedClientIpTests(TestCase):

    def test_no_remote_addr_reads_outside_helper(self):
        offenders = []
        for top in ('apps', 'core', 'config'):
            for path in (_ROOT / top).rglob('*.py'):
                parts = path.relative_to(_ROOT).parts
                if 'tests' in parts or 'migrations' in parts or parts[-2:] == ('core', 'client_ip.py'):
                    continue
                if 'REMOTE_ADDR' in path.read_text(encoding='utf-8', errors='ignore'):
                    offenders.append('/'.join(parts))
        self.assertEqual(offenders, [])

    def test_nginx_overwrites_forwarded_for(self):
        text = (_ROOT / 'deploy' / 'nginx-proxy-headers.conf').read_text(encoding='utf-8')
        self.assertIn('proxy_set_header X-Forwarded-For $remote_addr;', text)
        self.assertNotIn('$proxy_add_x_forwarded_for', text)

    def test_every_proxy_location_uses_trusted_headers(self):
        text = (_ROOT / 'deploy' / 'nginx.conf').read_text(encoding='utf-8')
        self.assertNotIn('proxy_params', text)
        proxied = [(h, b) for h, b in _location_blocks(text) if 'proxy_pass' in b]
        self.assertTrue(any('/ws/' in h for h, _ in proxied))
        for header, body in proxied:
            self.assertIn(_PROXY_INCLUDE, body, header)

    def test_login_failure_logs_proxy_ip_not_forged(self):
        cache.clear()
        make_user('n0_user', role='pharmacist', password='A6-Strong-pw-26')
        with _behind_proxy():
            APIClient().post(LOGIN, {'username': 'n0_user', 'password': 'wrong-password'}, format='json',
                             REMOTE_ADDR='6.6.6.6', HTTP_X_FORWARDED_FOR='6.6.6.6, 41.32.31.187')
        row = UserActivityLog.objects.filter(action='login_failed').latest('id')
        self.assertEqual(row.ip_address, '41.32.31.187')
