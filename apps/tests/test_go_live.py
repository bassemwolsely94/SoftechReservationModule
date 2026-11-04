"""
apps/tests/test_go_live.py

Go-live safety (docs/GO_LIVE_CHECKLIST.md):
  • deploy/production.env.example and staging.env.example start as readers: WRITER_INSTANCE=False,
    SOFTECH_READ_ONLY=True, every writer flag in config/writers.py listed and False, no duplicate key,
    no key the code never reads (a typo would silently fall back to the code default)
  • manage.py writer_status reports the role and --expect fails on a mismatch
  • GET /api/public/health/ is anonymous, 200 with a reachable DB, 503 without, and discloses nothing else
"""
import io
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase, override_settings

from config.writers import WRITER_FLAGS, duplicate_env_keys

BASE = Path(settings.BASE_DIR)
TEMPLATES = ('deploy/production.env.example', 'deploy/staging.env.example')
# read by a child process from the environment, not by Django settings
NON_SETTINGS_KEYS = {'OMP_THREAD_LIMIT'}
_LINE = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)\s*=\s*([^#\s]*)')


def _env(rel):
    out = {}
    for line in (BASE / rel).read_text(encoding='utf-8').splitlines():
        m = _LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _code_text():
    parts = []
    for folder in ('config', 'apps', 'core'):
        for p in (BASE / folder).rglob('*.py'):
            if 'tests' in p.parts or 'migrations' in p.parts:
                continue
            parts.append(p.read_text(encoding='utf-8', errors='ignore'))
    return '\n'.join(parts)


class EnvTemplateTests(SimpleTestCase):

    def test_templates_start_as_readers_with_every_writer_flag_off(self):
        for rel in TEMPLATES:
            env = _env(rel)
            self.assertEqual(env.get('WRITER_INSTANCE'), 'False', rel)
            self.assertEqual(env.get('SOFTECH_READ_ONLY'), 'True', rel)
            for flag in WRITER_FLAGS:
                self.assertEqual(env.get(flag), 'False', f'{rel}: {flag} missing or not False')

    def test_templates_have_no_duplicate_key(self):
        for rel in TEMPLATES:
            self.assertEqual(duplicate_env_keys(BASE / rel), [], rel)

    def test_every_template_key_is_read_by_the_code(self):
        code = _code_text()
        for rel in TEMPLATES:
            for key in _env(rel):
                if key in NON_SETTINGS_KEYS:
                    continue
                self.assertIn(f"'{key}'", code, f'{rel}: {key} is never read — typo?')

    def test_production_template_has_no_windows_path(self):
        for key, value in _env('deploy/production.env.example').items():
            self.assertNotRegex(value, r'^[A-Za-z]:[\\/]', key)


class WriterStatusCommandTests(SimpleTestCase):

    def _run(self, *args):
        out = io.StringIO()
        with mock.patch('apps.sync.management.commands.writer_status.duplicate_env_keys', return_value=[]):
            call_command('writer_status', *args, stdout=out)
        return out.getvalue()

    @override_settings(WRITER_INSTANCE=False, SOFTECH_READ_ONLY=True, ISR_WRITER_ENABLED=True)
    def test_office_reader_passes_expect_reader(self):
        out = self._run('--expect', 'reader')
        self.assertIn('ROLE = reader', out)
        self.assertRegex(out, r'ISR_WRITER_ENABLED\s+value=True\s+effective=False')

    @override_settings(WRITER_INSTANCE=True, SOFTECH_READ_ONLY=True)
    def test_writer_instance_behind_kill_switch_is_still_a_reader(self):
        self.assertIn('ROLE = reader', self._run('--expect', 'reader'))

    @override_settings(WRITER_INSTANCE=True, SOFTECH_READ_ONLY=False)
    def test_writer_fails_expect_reader(self):
        with self.assertRaises(CommandError):
            self._run('--expect', 'reader')
        self.assertIn('ROLE = writer', self._run('--expect', 'writer'))

    @override_settings(WRITER_INSTANCE=False, SOFTECH_READ_ONLY=False)
    def test_reader_fails_expect_writer(self):
        with self.assertRaises(CommandError):
            self._run('--expect', 'writer')

    @override_settings(WRITER_INSTANCE=False, SOFTECH_READ_ONLY=True)
    def test_duplicate_env_key_fails(self):
        with mock.patch('apps.sync.management.commands.writer_status.duplicate_env_keys',
                        return_value=[('ISR_WRITER_ENABLED', 3, 9)]):
            with self.assertRaises(CommandError):
                call_command('writer_status', stdout=io.StringIO())


@override_settings(PUBLIC_API_ENFORCEMENT='enforce')
class HealthEndpointTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_anonymous_ok(self):
        resp = self.client.get('/api/public/health/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {'status': 'ok'})
        self.assertEqual(resp['Cache-Control'], 'no-store')

    def test_database_down_is_503(self):
        with mock.patch('django.db.backends.utils.CursorWrapper.execute', side_effect=Exception('down')):
            resp = self.client.get('/api/public/health/')
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json(), {'status': 'error'})

    def test_get_only(self):
        self.assertEqual(self.client.post('/api/public/health/').status_code, 405)
