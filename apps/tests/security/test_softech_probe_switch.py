"""
SOFTECH write safety — diagnostic / rehearsal writes (Batch 2, P-7).

Every writer-level rehearsal ("probe_*": real DML on SOFTECH, then roll back or restore)
and every management-command mode that writes to SOFTECH runs only when
SOFTECH_PROBES_ENABLED is on. The refusal happens before any SOFTECH connection.
Owner decision 2026-10-26: keep every diagnostic command, gate each writing mode.
"""
from types import SimpleNamespace

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from .routes import Tripwire

DUMMY = SimpleNamespace(pk=1, branch=None, softech_branchcode='100')

# (module, function, args, kwargs) — confirm=True so only the switch can refuse
FUNCTIONS = [
    ('apps.pos_orders.writer', 'probe_order', (DUMMY,), {'confirm': True}),
    ('apps.pos_orders.writer', 'probe_cancel', ('h', 5000, 'db', '100', '115', 1), {'confirm': True}),
    ('apps.pos_orders.reservation', 'probe_reservation', (DUMMY, 1), {}),
    ('apps.purchasing.isr_writer', 'probe_isr_write', ('130',), {'confirm': True}),
    ('apps.purchasing.isr_writer', 'probe_approve_isr', ('130', '2613000001'), {'confirm': True}),
    ('apps.purchasing.rate_writer', 'probe_write', ('130', 'IT001'), {'confirm': True}),
    ('apps.purchasing.coverage_writer', 'probe_coverage_write', ('130', 'IT001'), {'confirm': True}),
]

# (command, options) — each a mode that writes to SOFTECH
COMMANDS = [
    ('diag_blocked_purchase', {}),
    ('diag_chained', {}),
    ('diag_newqty', {}),
    ('diag_purchase3', {'branch': '100', 'docnumber': 1}),
    ('diag_purchase_insert', {'branch': '100', 'docnumber': 1}),
    ('diag_purchase_verbatim', {'branch': '100', 'docnumber': 1}),
    ('investigate_britems', {}),
    ('investigate_britems2', {}),
    ('investigate_replication', {}),
    ('probe_itemlastupdate', {}),
    ('probe_repl_queue', {}),
    ('probe_replication_source', {}),
    ('test_replication_cycle', {'mode': 'plant'}),
    ('test_sybase_vps', {'write_test': True}),
    ('capture_save_sql', {'enable_monitoring': True}),
    ('probe_ap_writeback', {'rehearse': True, 'confirm_rollback_rehearsal': True}),
    ('test_pic_points', {'pic': '01HD14'}),
]


# writer gates on (coverage checks its own COVERAGE_WRITER_ENABLED first) — only the probes switch refuses
@override_settings(SOFTECH_PROBES_ENABLED=False, COVERAGE_WRITER_ENABLED=True)
class ProbeSwitchOffTests(SimpleTestCase):

    def test_rehearsal_functions_refuse_before_softech(self):
        import importlib
        for module, name, args, kwargs in FUNCTIONS:
            fn = getattr(importlib.import_module(module), name)
            with self.subTest(name), Tripwire() as tw:
                with self.assertRaisesMessage(ValueError, 'SOFTECH_PROBES_ENABLED'):
                    fn(*args, **kwargs)
                self.assertEqual(tw.softech_calls, [], name)

    def test_writing_command_modes_refuse_before_softech(self):
        for name, options in COMMANDS:
            with self.subTest(name), Tripwire() as tw:
                with self.assertRaisesMessage(CommandError, 'SOFTECH_PROBES_ENABLED'):
                    call_command(name, **options)
                self.assertEqual(tw.softech_calls, [], name)
