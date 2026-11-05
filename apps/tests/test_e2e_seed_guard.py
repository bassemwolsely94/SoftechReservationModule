"""R8: the e2e seed command runs only under config.settings_e2e (its own database, no SOFTECH)."""
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings


class SeedE2EUsersGuardTests(TestCase):
    def test_refuses_under_the_normal_settings(self):
        with self.assertRaisesMessage(CommandError, 'config.settings_e2e'):
            call_command('seed_e2e_users')

    @override_settings(E2E_SETTINGS=True, WRITER_INSTANCE=True, SOFTECH_READ_ONLY=False)
    def test_refuses_a_writer_copy_even_when_flagged_e2e(self):
        with self.assertRaisesMessage(CommandError, 'reader copy'):
            call_command('seed_e2e_users')

    def test_e2e_settings_file_pins_the_reader_copy(self):
        # read as text: importing it here would re-run the settings under the test runner
        from pathlib import Path
        src = (Path(__file__).resolve().parents[2] / 'config' / 'settings_e2e.py').read_text(encoding='utf-8')
        for line in ('WRITER_INSTANCE = False', 'SOFTECH_READ_ONLY = True', "SYBASE_HOST = ''",
                     'decouple.config = decouple.Config(decouple.RepositoryEmpty())',
                     "SCHEDULER_AUTOSTART = False"):
            self.assertIn(line, src)
