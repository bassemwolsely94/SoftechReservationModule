"""
Platform & abuse — browser security headers (Batch 6, W-9; owner 2026-11-01).

Before: SECURE_HSTS_SECONDS defaulted to 0 (no HSTS — a first plain-HTTP visit on hostile Wi-Fi
could be downgraded), and no Content-Security-Policy at all.

Now (owner): HSTS for 1 day, no sub-domains, no preload — raised later. CSP shipped REPORT-ONLY on
the SPA (nginx) with reports sent to /api/csp-report/; D-04 (owner 2026-11-19) ENFORCES it, with one
switch back to report-only in deploy/nginx-csp.conf and the report URI kept in both modes.
"""
import re
import tempfile
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from core.csp import summarize

REPORT = b'{"csp-report": {"document-uri": "https://erp/x", "violated-directive": "script-src", ' \
         b'"blocked-uri": "https://evil.example/a.js"}}'
ENFORCED_REPORT = b'{"csp-report": {"document-uri": "https://erp/x", "effective-directive": "img-src", ' \
                  b'"blocked-uri": "https://evil.example/p.png", "disposition": "enforce"}}'


def _read(*parts):
    return (Path(settings.BASE_DIR).joinpath(*parts)).read_text(encoding='utf-8')


class HstsTests(TestCase):

    def test_hsts_is_one_day_without_subdomains_or_preload(self):
        r = self.client.get('/api/auth/me/', secure=True)
        self.assertEqual(r.get('Strict-Transport-Security'), 'max-age=86400')


class CspTests(TestCase):

    def setUp(self):
        cache.clear()

    def _spa_block(self):
        conf = _read('deploy', 'nginx.conf')
        start = conf.index('location / {')
        return conf[start:conf.index('}', start)]

    def test_the_spa_includes_the_csp_file_and_sends_both_mapped_headers(self):
        block = self._spa_block()
        self.assertIn('include /etc/nginx/elrezeiky-csp.conf;', block)
        self.assertRegex(block, r'add_header Content-Security-Policy\s+\$elr_csp_enforce always;')
        self.assertRegex(block, r'add_header Content-Security-Policy-Report-Only\s+\$elr_csp_report_only always;')
        self.assertNotIn('default-src', block, 'the policy is written once, in deploy/nginx-csp.conf')

    def test_the_mode_maps_send_exactly_one_header(self):
        conf = _read('deploy', 'nginx.conf')
        enforce = re.search(r'map \$elr_csp_mode \$elr_csp_enforce \{(.*?)\}', conf, re.S).group(1)
        report = re.search(r'map \$elr_csp_mode \$elr_csp_report_only \{(.*?)\}', conf, re.S).group(1)
        self.assertRegex(enforce, r'enforce\s+\$elr_csp_policy;')
        self.assertRegex(enforce, r'default\s+"";')                 # empty value → nginx sends no header
        self.assertRegex(report, r'enforce\s+"";')
        self.assertRegex(report, r'default\s+\$elr_csp_policy;')   # anything but "enforce" = report-only

    def test_reports_are_taken_and_logged(self):
        with self.assertLogs('elrezeiky.csp', level='WARNING') as logs:
            r = self.client.post('/api/csp-report/', REPORT, content_type='application/csp-report')
        self.assertEqual(r.status_code, 204)
        self.assertIn('evil.example', ' '.join(logs.output))

    def test_enforced_reports_are_taken_and_logged_as_enforce(self):
        with self.assertLogs('elrezeiky.csp', level='WARNING') as logs:
            r = self.client.post('/api/csp-report/', ENFORCED_REPORT, content_type='application/csp-report')
        self.assertEqual(r.status_code, 204)
        self.assertIn('CSP (enforce)', ' '.join(logs.output))

    def test_oversized_or_wrong_method_reports_are_refused(self):
        self.assertEqual(self.client.post('/api/csp-report/', b'x' * 20_000,
                                          content_type='application/csp-report').status_code, 413)
        self.assertEqual(self.client.get('/api/csp-report/').status_code, 405)


class CspPolicyFileTests(SimpleTestCase):
    """D-04: deploy/nginx-csp.conf — the one policy, enforcing, with the report URI kept."""

    def _value(self, name):
        m = re.search(r'^set \$' + name + r' "([^"]+)";$', _read('deploy', 'nginx-csp.conf'), re.M)
        self.assertIsNotNone(m, f'{name} must be set on one line')
        return m.group(1)

    def _directives(self):
        parts = (x.strip() for x in self._value('elr_csp_policy').split(';'))
        return {p.split()[0]: p.split()[1:] for p in parts if p}

    def test_the_mode_is_enforce(self):
        self.assertEqual(self._value('elr_csp_mode'), 'enforce')

    def test_violations_are_still_reported(self):
        self.assertEqual(self._directives()['report-uri'], ['/api/csp-report/'])

    def test_scripts_stay_strict(self):
        d = self._directives()
        for directive, value in (('default-src', ["'self'"]), ('script-src', ["'self'"]),
                                 ('object-src', ["'none'"]), ('base-uri', ["'self'"]),
                                 ('frame-ancestors', ["'self'"]), ('form-action', ["'self'"])):
            self.assertEqual(d[directive], value, directive)
        self.assertNotIn("'unsafe-eval'", self._value('elr_csp_policy'))

    def test_the_allow_list_has_what_the_app_loads(self):
        d = self._directives()
        # Cairo web font (index.html, print windows)
        self.assertIn('https://fonts.googleapis.com', d['style-src'])
        self.assertIn('https://fonts.gstatic.com', d['font-src'])
        # print windows write <style> blocks; VoiceNoteRecorder / PrintReceiptModal inject <style>
        self.assertIn("'unsafe-inline'", d['style-src'])
        # upload previews (blob:), QR images, map tiles, Leaflet markers (https:)
        for src in ('data:', 'blob:', 'https:'):
            self.assertIn(src, d['img-src'])
        # voice-note preview (blob:); call recordings may redirect to the PBX host (https:)
        for src in ("'self'", 'blob:', 'https:'):
            self.assertIn(src, d['media-src'])
        self.assertIn('wss:', d['connect-src'])          # /ws channels, softphone SIP over WSS
        self.assertIn("'self'", d['worker-src'])         # sw.js, portal-sw.js
        self.assertIn("'self'", d['manifest-src'])

    def test_the_vite_preview_reads_the_same_file(self):
        vite = _read('frontend', 'vite.config.js')
        self.assertIn('../deploy/nginx-csp.conf', vite)
        self.assertIn('headers: { [CSP.header]: CSP.policy }', vite)


class CspReportSummaryTests(SimpleTestCase):
    LINES = [
        'WARNING 2026-11-19 10:00:00,123 csp CSP (enforce) document-uri=https://erp/reservations/12?token=x'
        ' · effective-directive=script-src-elem · blocked-uri=inline',
        'WARNING 2026-11-19 11:30:00,001 csp CSP (enforce) document-uri=https://erp/reservations/99'
        ' · effective-directive=script-src-elem · blocked-uri=inline',
        'Nov 19 web[9]: WARNING 2026-11-18 08:00:00,000 csp CSP (report-only) document-uri=https://erp/pos'
        ' · violated-directive=script-src · blocked-uri=chrome-extension://abc/x.js',
        'INFO 2026-11-19 10:00:00,000 apps something else',
    ]

    def test_groups_by_directive_source_and_page(self):
        rows = summarize(self.LINES)
        self.assertEqual(len(rows), 2)
        top = rows[0]
        self.assertEqual((top['count'], top['directive'], top['blocked'], top['page'], top['mode']),
                         (2, 'script-src-elem', 'inline', '/reservations/:id', 'enforce'))
        self.assertEqual((top['first'], top['last']), ('2026-11-19 10:00:00', '2026-11-19 11:30:00'))
        self.assertEqual(top['verdict'], 'review')
        self.assertEqual(rows[1]['verdict'], 'ignore — extension / browser')
        self.assertNotIn('token', str(rows))               # pages lose their query string

    def test_the_command_prints_a_markdown_table(self):
        with tempfile.NamedTemporaryFile('w', suffix='.log', delete=False, encoding='utf-8') as fh:
            fh.write('\n'.join(self.LINES))
        try:
            out = StringIO()
            call_command('csp_report_summary', fh.name, '--markdown', stdout=out)
        finally:
            Path(fh.name).unlink()
        self.assertIn('| 2 | script-src-elem | inline | /reservations/:id | enforce |', out.getvalue())
        self.assertIn('3 reports in 2 groups.', out.getvalue())
