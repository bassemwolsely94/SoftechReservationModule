"""config.settings_uat must be a reader copy that cannot reach SOFTECH, the tax authority or any
messaging channel, and must refuse any database that is not a UAT copy
(docs/superpowers/specs/2026-11-16-role-uat-design.md §5.1)."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]

PROBE = r'''
import json, django
django.setup()
from django.conf import settings as s
from config.writers import WRITER_FLAGS
print("UATJSON" + json.dumps({
    "uat": getattr(s, "UAT_SETTINGS", False),
    "writer": s.WRITER_INSTANCE, "read_only": s.SOFTECH_READ_ONLY,
    "sybase": s.SYBASE_HOST, "flags_on": [f for f in WRITER_FLAGS if getattr(s, f, False)],
    "send_on": [n for n in dir(s) if n.isupper() and n.endswith(("_SEND_ENABLED", "_WRITE_ENABLED", "_WRITER_ENABLED", "_POSTING_ENABLED")) and getattr(s, n)],
    "wa": s.WHATSAPP_TOKEN, "ami": s.AMI_HOST, "sched": s.SCHEDULER_AUTOSTART,
    "rbac": s.RBAC_ENFORCEMENT, "db": s.DATABASES["default"]["NAME"],
    "login_rate": s.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["login"],
}))
'''


def _probe(**env):
    full = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings_uat', 'PYTHONIOENCODING': 'utf-8', **env}
    # A hostile process environment must not switch anything on.
    full.update({'WRITER_INSTANCE': 'True', 'SOFTECH_READ_ONLY': 'False', 'SYBASE_HOST': '10.0.0.1',
                 'POS_WRITER_ENABLED': 'True', 'WHATSAPP_TOKEN': 'live-token'})
    full.update(env)
    return subprocess.run([sys.executable, '-c', PROBE], cwd=ROOT, env=full,
                          capture_output=True, text=True, encoding='utf-8', timeout=180)


class UatSettingsGuardTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.res = _probe(UAT_PG_NAME='elrezeiky_uat')

    def _values(self):
        self.assertEqual(self.res.returncode, 0, self.res.stderr[-2000:])
        line = next(ln for ln in self.res.stdout.splitlines() if ln.startswith('UATJSON'))
        return json.loads(line[len('UATJSON'):])

    def test_reader_copy_without_softech(self):
        v = self._values()
        self.assertTrue(v['uat'])
        self.assertIs(v['writer'], False)
        self.assertIs(v['read_only'], True)
        self.assertEqual(v['sybase'], '')

    def test_every_writer_and_send_switch_off(self):
        v = self._values()
        self.assertEqual(v['flags_on'], [])
        self.assertEqual(v['send_on'], [])

    def test_no_messaging_and_no_scheduler(self):
        v = self._values()
        self.assertEqual(v['wa'], '')
        self.assertEqual(v['ami'], '')
        self.assertIs(v['sched'], False)

    def test_enforce_mode_and_uat_database(self):
        v = self._values()
        self.assertEqual(v['rbac'], 'enforce')
        self.assertEqual(v['db'], 'elrezeiky_uat')

    def test_login_throttle_raised_for_many_test_users(self):
        self.assertEqual(self._values()['login_rate'], '1000/min')

    def test_refuses_the_dev_database(self):
        res = _probe(UAT_PG_NAME='elrezeiky_db')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('must not use', res.stderr)

    def test_refuses_any_non_uat_database(self):
        res = _probe(UAT_PG_NAME='elrezeiky_e2e')
        self.assertNotEqual(res.returncode, 0)
        self.assertIn('must not use', res.stderr)
