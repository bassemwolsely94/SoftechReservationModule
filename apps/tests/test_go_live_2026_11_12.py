"""
Go-live re-check 2026-11-12 (docs/deploy/2026-11-12-go-live-status.md):
- channel credentials move from the SECRET_KEY-derived key to OMNI_CREDENTIALS_KEY without a gap, and after
  `omni_credentials --rekey --apply` they open on a server with another SECRET_KEY (the VPS);
- `check --deploy` refuses a placeholder OMNI_CREDENTIALS_KEY and warns on the public counselling hash key;
- release.sh builds and checks before it migrates, and restarts every Django process after.
"""
import re
from io import StringIO
from pathlib import Path

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

from apps.audit.models import AuditLog
from apps.counselling.checks import PUBLIC_DEFAULT, counsel_phone_hash_key_check
from apps.omni.checks import omni_credentials_key_check
from apps.omni.crypto import decrypt_credentials, encrypt_credentials, key_state
from apps.omni.models import ChannelAccount

ROOT = Path(settings.BASE_DIR)
OFFICE_SECRET = 'office-secret-' + 'x' * 40
VPS_SECRET = 'vps-secret-' + 'y' * 40
KEY = Fernet.generate_key().decode()
CREDS = {'token': 'tok-123', 'phone_number_id': '42'}


class CredentialKeyMoveTests(TestCase):

    def _office_row(self):
        with override_settings(SECRET_KEY=OFFICE_SECRET, OMNI_CREDENTIALS_KEY=''):
            return ChannelAccount.objects.create(channel='whatsapp', name='main',
                                                 credentials=encrypt_credentials(CREDS))

    def test_derived_row_still_opens_once_the_env_key_is_set(self):
        acc = self._office_row()
        with override_settings(SECRET_KEY=OFFICE_SECRET, OMNI_CREDENTIALS_KEY=KEY):
            self.assertEqual(key_state(acc.credentials), 'derived')
            self.assertEqual(decrypt_credentials(acc.credentials), CREDS)

    def test_without_rekey_the_vps_cannot_open_it(self):
        acc = self._office_row()
        with override_settings(SECRET_KEY=VPS_SECRET, OMNI_CREDENTIALS_KEY=KEY):
            self.assertEqual(key_state(acc.credentials), 'unreadable')
            self.assertEqual(decrypt_credentials(acc.credentials), {})

    def test_status_fails_until_rekeyed_then_vps_opens_it(self):
        acc = self._office_row()
        ChannelAccount.objects.create(channel='sms', name='empty')
        with override_settings(SECRET_KEY=OFFICE_SECRET, OMNI_CREDENTIALS_KEY=KEY):
            with self.assertRaises(CommandError):
                call_command('omni_credentials', stdout=StringIO())
            out = StringIO()
            call_command('omni_credentials', '--rekey', stdout=out)            # dry run
            self.assertIn('Dry run', out.getvalue())
            acc.refresh_from_db()
            self.assertEqual(key_state(acc.credentials), 'derived')
            self.assertFalse(AuditLog.objects.filter(action='omni_credentials_rekeyed').exists())

            out = StringIO()
            call_command('omni_credentials', '--rekey', '--apply', stdout=out)
            self.assertIn('Re-keyed 1', out.getvalue())
            self.assertNotIn('tok-123', out.getvalue())
            call_command('omni_credentials', stdout=StringIO())                # now OK, no error
        acc.refresh_from_db()
        with override_settings(SECRET_KEY=VPS_SECRET, OMNI_CREDENTIALS_KEY=KEY):
            self.assertEqual(key_state(acc.credentials), 'env')
            self.assertEqual(decrypt_credentials(acc.credentials), CREDS)
        log = AuditLog.objects.get(action='omni_credentials_rekeyed')
        self.assertEqual(log.new_data['account_ids'], [acc.pk])

    def test_rekey_refuses_without_env_key(self):
        self._office_row()
        with override_settings(SECRET_KEY=OFFICE_SECRET, OMNI_CREDENTIALS_KEY=''):
            with self.assertRaises(CommandError):
                call_command('omni_credentials', '--rekey', '--apply', stdout=StringIO())

    def test_new_rows_are_written_under_the_env_key(self):
        with override_settings(SECRET_KEY=OFFICE_SECRET, OMNI_CREDENTIALS_KEY=KEY):
            stored = encrypt_credentials(CREDS)
        with override_settings(SECRET_KEY=VPS_SECRET, OMNI_CREDENTIALS_KEY=KEY):
            self.assertEqual(decrypt_credentials(stored), CREDS)


class DeployCheckTests(SimpleTestCase):

    def test_placeholder_key_is_an_error_and_never_echoed(self):
        with override_settings(OMNI_CREDENTIALS_KEY='CHANGE'):
            msgs = omni_credentials_key_check(None)
        self.assertEqual([m.id for m in msgs], ['omni.E001'])
        self.assertNotIn('CHANGE', msgs[0].msg)

    def test_empty_key_warns_in_production_only(self):
        with override_settings(OMNI_CREDENTIALS_KEY='', DEBUG=False):
            self.assertEqual([m.id for m in omni_credentials_key_check(None)], ['omni.W001'])
        with override_settings(OMNI_CREDENTIALS_KEY='', DEBUG=True):
            self.assertEqual(omni_credentials_key_check(None), [])

    def test_valid_key_passes(self):
        with override_settings(OMNI_CREDENTIALS_KEY=KEY, DEBUG=False):
            self.assertEqual(omni_credentials_key_check(None), [])

    def test_counsel_public_default_warns_in_production(self):
        with override_settings(COUNSEL_PHONE_HASH_KEY=PUBLIC_DEFAULT, DEBUG=False):
            self.assertEqual([m.id for m in counsel_phone_hash_key_check(None)], ['counselling.W001'])
        with override_settings(COUNSEL_PHONE_HASH_KEY='', DEBUG=False):
            self.assertEqual([m.id for m in counsel_phone_hash_key_check(None)], ['counselling.W001'])
        with override_settings(COUNSEL_PHONE_HASH_KEY='a' * 64, DEBUG=False):
            self.assertEqual(counsel_phone_hash_key_check(None), [])

    def test_templates_hold_no_placeholder_omni_key(self):
        for name in ('production.env.example', 'staging.env.example'):
            text = (ROOT / 'deploy' / name).read_text(encoding='utf-8')
            m = re.search(r'^OMNI_CREDENTIALS_KEY=(.*)$', text, re.M)
            self.assertIsNotNone(m, name)
            self.assertEqual(m.group(1).strip(), '', name)


class ReleaseScriptOrderTests(SimpleTestCase):

    def setUp(self):
        self.lines = (ROOT / 'deploy' / 'release.sh').read_text(encoding='utf-8').splitlines()

    def _at(self, pattern):
        hits = [i for i, line in enumerate(self.lines) if re.search(pattern, line) and not line.lstrip().startswith('#')]
        self.assertEqual(len(hits), 1, pattern)
        return hits[0]

    def test_build_and_deploy_check_run_before_migrate(self):
        migrate = self._at(r'manage\.py migrate$')
        self.assertLess(self._at(r'npm run build'), migrate)
        self.assertLess(self._at(r'manage\.py check --deploy'), migrate)
        self.assertLess(self._at(r'read -p'), migrate)
        self.assertLess(migrate, self._at(r'collectstatic'))

    def test_every_django_process_restarts_after_migrate(self):
        migrate = self._at(r'manage\.py migrate$')
        for unit in ('elrezeiky-web', 'elrezeiky-scheduler', 'elrezeiky-ami-bridge'):
            self.assertLess(migrate, self._at(rf'systemctl restart {unit}$|systemctl restart {unit};'), unit)
