"""
apps/tests/test_writer_instance.py

P-54 (docs/product-review/06_SPEC_P-54): ONE instance writes to SOFTECH.
  • WRITER_INSTANCE=False closes every writer gate even with every feature flag True
  • no gate reads a writer flag directly — all go through config.writers.writer_allowed
  • a non-writer scheduler does not register the writer jobs
  • a duplicated .env key, or WRITER_INSTANCE + SOFTECH_READ_ONLY together, refuse startup
  • GET /api/sync/writer-switches/ lists every flag; admin only
"""
import pathlib
import tempfile
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, TestCase, override_settings

from config import writers
from .factories import make_admin, make_pharmacist

ALL_ON = {flag: True for flag in writers.WRITER_FLAGS}

# every module-level gate function a writer service calls before touching SOFTECH
GATES = [
    ('apps.customers.branch_copy', 'write_enabled'),
    ('apps.customers.merge_write', 'write_enabled'),
    ('apps.customers.points_removal', 'write_enabled'),
    ('apps.finance.recon_writer', 'writer_enabled'),
    ('apps.insurance.reprice_service', 'write_enabled'),
    ('apps.invoices.supplier_items', 'write_enabled'),
    ('apps.invoices.writer', 'writer_enabled'),
    ('apps.offers.channel_a', 'write_enabled'),
    ('apps.offers.channel_b', 'promo_write_enabled'),
    ('apps.offers.order_attach', 'execution_enabled'),
    ('apps.pos_orders.pos_cancel_writer', 'write_enabled'),
    ('apps.pos_orders.writer', 'writer_enabled'),
    ('apps.purchasing.coverage_writer', 'coverage_writer_enabled'),
    ('apps.purchasing.isr_writer', 'writer_enabled'),
    ('apps.purchasing.rate_writer', 'writer_enabled'),
    ('apps.purchasing.rate_writer', '_refresh_maxqty'),
    ('apps.purchasing.shortage_writer', '_enabled'),
]


class WriterAllowedTests(SimpleTestCase):

    @override_settings(WRITER_INSTANCE=False, ISR_WRITER_ENABLED=True)
    def test_non_writer_instance_closes_the_gate(self):
        self.assertFalse(writers.writer_allowed('ISR_WRITER_ENABLED'))

    @override_settings(WRITER_INSTANCE=True, ISR_WRITER_ENABLED=True)
    def test_writer_instance_with_flag_opens(self):
        self.assertTrue(writers.writer_allowed('ISR_WRITER_ENABLED'))

    @override_settings(WRITER_INSTANCE=True, ISR_WRITER_ENABLED=False)
    def test_flag_off_stays_closed(self):
        self.assertFalse(writers.writer_allowed('ISR_WRITER_ENABLED'))

    def test_unknown_flag_refused(self):
        with self.assertRaises(KeyError):
            writers.writer_allowed('NOT_A_WRITER_FLAG')

    def test_sybase_reexports_the_helper(self):
        from config.sybase import writer_allowed
        self.assertIs(writer_allowed, writers.writer_allowed)

    def test_every_gate_closed_off_instance(self):
        import importlib
        with override_settings(WRITER_INSTANCE=False, **ALL_ON):
            for mod, fn in GATES:
                with self.subTest(gate=f'{mod}.{fn}'):
                    self.assertFalse(getattr(importlib.import_module(mod), fn)())
            from apps.purchasing import coverage_writer
            self.assertFalse(coverage_writer.topup_settings()['enabled'])

    def test_every_gate_open_on_instance(self):
        import importlib
        with override_settings(WRITER_INSTANCE=True, **ALL_ON):
            for mod, fn in GATES:
                with self.subTest(gate=f'{mod}.{fn}'):
                    self.assertTrue(getattr(importlib.import_module(mod), fn)())

    def test_replacement_posting_closed_off_instance(self):
        from apps.replacement import legs
        with override_settings(WRITER_INSTANCE=False, **ALL_ON):
            self.assertFalse(legs.posting_enabled())

    def test_no_gate_reads_a_writer_flag_directly(self):
        """Code (not docstrings) never reads <x>.FLAG or getattr(<x>, 'FLAG', …) for a writer flag."""
        import ast
        root = pathlib.Path(__file__).resolve().parents[2]
        flags = set(writers.WRITER_FLAGS)
        offenders = []
        for path in (root / 'apps').rglob('*.py'):
            rel = path.relative_to(root).as_posix()
            if '/tests/' in rel or rel.startswith('apps/help/'):
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
                if isinstance(node, ast.Attribute) and node.attr in flags:
                    offenders.append(f'{rel}:{node.lineno}')
                elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                      and node.func.id == 'getattr' and len(node.args) >= 2
                      and isinstance(node.args[1], ast.Constant) and node.args[1].value in flags):
                    offenders.append(f'{rel}:{node.lineno}')
        self.assertEqual(offenders, [], 'read writer flags through config.writers.writer_allowed')

    def test_registry_matches_settings(self):
        from django.conf import settings
        for flag, info in writers.WRITER_FLAGS.items():
            with self.subTest(flag=flag):
                self.assertTrue(hasattr(settings, flag))
                self.assertTrue(info['protects'])


class SchedulerTests(SimpleTestCase):

    def _ids(self):
        from apps.sync import tasks
        from .test_scheduler_jobs import _FakeScheduler
        with mock.patch.object(tasks, 'BackgroundScheduler', _FakeScheduler), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
            return {j[1] for j in tasks._scheduler.jobs}

    def test_non_writer_registers_no_writer_job(self):
        with override_settings(WRITER_INSTANCE=False, **ALL_ON):
            ids = self._ids()
        self.assertFalse(set(writers.WRITER_JOBS) & ids)
        self.assertIn('softech_sync_fast', ids)            # reading jobs still run

    def test_writer_registers_them(self):
        with override_settings(WRITER_INSTANCE=True):
            ids = self._ids()
        self.assertTrue(set(writers.WRITER_JOBS) <= ids)


class StartupGuardTests(SimpleTestCase):

    def _env(self, text):
        f = tempfile.NamedTemporaryFile('w', suffix='.env', delete=False, encoding='utf-8')
        f.write(text)
        f.close()
        return f.name

    def test_duplicate_key_named_with_both_lines(self):
        path = self._env('A=1\n# comment\nISR_WRITER_ENABLED=True\nB=2\nexport ISR_WRITER_ENABLED = False\n')
        dups = writers.duplicate_env_keys(path)
        self.assertEqual(dups, [('ISR_WRITER_ENABLED', 3, 5)])
        with override_settings(WRITER_INSTANCE=False, SOFTECH_READ_ONLY=True):
            with self.assertRaisesMessage(ImproperlyConfigured, 'ISR_WRITER_ENABLED'):
                writers.run_startup_checks(env_path=path)

    def test_clean_env_starts(self):
        path = self._env('A=1\nB=2\n')
        with override_settings(WRITER_INSTANCE=True, SOFTECH_READ_ONLY=False):
            writers.run_startup_checks(env_path=path)       # no exception

    def test_writer_plus_read_only_refused(self):
        path = self._env('A=1\n')
        with override_settings(WRITER_INSTANCE=True, SOFTECH_READ_ONLY=True):
            with self.assertRaisesMessage(ImproperlyConfigured, 'SOFTECH_READ_ONLY'):
                writers.run_startup_checks(env_path=path)

    def test_boot_log_lists_flags_on(self):
        path = self._env('A=1\n')
        with override_settings(WRITER_INSTANCE=False, SOFTECH_READ_ONLY=True, ISR_WRITER_ENABLED=True):
            with self.assertLogs('elrezeiky.writers', 'INFO') as logs:
                writers.run_startup_checks(env_path=path)
        text = '\n'.join(logs.output)
        self.assertIn('WRITER_INSTANCE=False', text)
        self.assertIn('ISR_WRITER_ENABLED', text)


class SwitchTableEndpointTests(TestCase):

    def test_admin_sees_every_flag(self):
        _, _, admin = make_admin('ws_admin')
        with override_settings(WRITER_INSTANCE=False, SOFTECH_READ_ONLY=True, ISR_WRITER_ENABLED=True):
            d = admin.get('/api/sync/writer-switches/').json()
        self.assertFalse(d['writer_instance'])
        self.assertTrue(d['softech_read_only'])
        rows = {r['flag']: r for r in d['flags']}
        self.assertEqual(set(rows), set(writers.WRITER_FLAGS))
        isr = rows['ISR_WRITER_ENABLED']
        self.assertTrue(isr['value'])
        self.assertFalse(isr['effective'])                  # not the writer instance
        self.assertFalse(isr['code_default'])
        self.assertTrue(isr['protects'])

    def test_non_admin_refused(self):
        _, _, pharm = make_pharmacist()
        self.assertEqual(pharm.get('/api/sync/writer-switches/').status_code, 403)
