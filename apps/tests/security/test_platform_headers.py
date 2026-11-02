"""
Platform & abuse — browser security headers (Batch 6, W-9; owner 2026-11-01).

Before: SECURE_HSTS_SECONDS defaulted to 0 (no HSTS — a first plain-HTTP visit on hostile Wi-Fi
could be downgraded), and no Content-Security-Policy at all.

Now (owner): HSTS for 1 day, no sub-domains, no preload — raised later. CSP ships REPORT-ONLY on the
SPA (nginx) with reports sent to /api/csp-report/, logged so the policy can be tuned before it is
enforced.
"""
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

REPORT = b'{"csp-report": {"document-uri": "https://erp/x", "violated-directive": "script-src", ' \
         b'"blocked-uri": "https://evil.example/a.js"}}'


class HstsTests(TestCase):

    def test_hsts_is_one_day_without_subdomains_or_preload(self):
        r = self.client.get('/api/auth/me/', secure=True)
        self.assertEqual(r.get('Strict-Transport-Security'), 'max-age=86400')


class CspTests(TestCase):

    def setUp(self):
        cache.clear()

    def _spa_block(self):
        conf = (Path(settings.BASE_DIR) / 'deploy' / 'nginx.conf').read_text(encoding='utf-8')
        start = conf.index('location / {')
        return conf[start:conf.index('}', start)]

    def test_the_spa_ships_a_report_only_policy(self):
        block = self._spa_block()
        self.assertIn('Content-Security-Policy-Report-Only', block)
        for directive in ("default-src 'self'", "object-src 'none'", "frame-ancestors 'self'",
                          "base-uri 'self'", 'report-uri /api/csp-report/'):
            self.assertIn(directive, block)

    def test_reports_are_taken_and_logged(self):
        with self.assertLogs('elrezeiky.csp', level='WARNING') as logs:
            r = self.client.post('/api/csp-report/', REPORT, content_type='application/csp-report')
        self.assertEqual(r.status_code, 204)
        self.assertIn('evil.example', ' '.join(logs.output))

    def test_oversized_or_wrong_method_reports_are_refused(self):
        self.assertEqual(self.client.post('/api/csp-report/', b'x' * 20_000,
                                          content_type='application/csp-report').status_code, 413)
        self.assertEqual(self.client.get('/api/csp-report/').status_code, 405)
