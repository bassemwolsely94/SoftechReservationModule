"""N4 / Task 3 - every SOFTECH connection follows the gate: refuse, read-only or full.

The choke point is config.sybase._connect_with_retry (and probe_connection for the health
sweep). No real Sybase: the driver and the java connection are Mock()s.
"""
from unittest import mock

from django.core.cache import cache
from django.db import connection, transaction
from django.test import TestCase, override_settings

from apps.access import softech_gate as gate
from apps.access.softech_gate import GateDecision
from apps.audit.models import AuditLog
from config import sybase
from config.sybase import SoftechAccessDenied, SoftechReadOnlyError, SoftechZoneWriteDenied

CHECK = 'apps.access.softech_gate.check'
MODE = 'apps.access.softech_gate.mode'


def decision(grant, reason=None):
    return GateDecision(grant, reason, 'web:external:x', 'Z3')


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.raw = mock.Mock(name='java_conn')
        self.driver = mock.Mock(name='driver')
        self.driver.connect.return_value = self.raw
        self.load = mock.Mock(name='softech_load')
        patches = [mock.patch('config.sybase._load', return_value=self.load),
                   mock.patch('config.sybase.time.sleep')]
        self.sleep = None
        for p in patches:
            started = p.start()
            self.addCleanup(p.stop)
            if p.attribute == 'sleep':
                self.sleep = started

    def tearDown(self):
        cache.clear()

    def connect(self, grant, mode, reason=None):
        with mock.patch(CHECK, return_value=decision(grant, reason)), \
                mock.patch(MODE, return_value=mode):
            return sybase._connect_with_retry(self.driver, 'jdbc:x', mock.Mock(), label='HQ')


@override_settings(SOFTECH_READ_ONLY=False)
class ConnectGateTests(_Base):

    def test_denied_raises_before_driver_connect(self):
        with self.assertRaises(SoftechAccessDenied) as cm:
            self.connect(gate.NONE, 'enforce', 'zone_no_read')
        self.assertEqual(str(cm.exception), gate.DENY_MESSAGE)
        self.assertEqual(cm.exception.reason, 'zone_no_read')
        self.driver.connect.assert_not_called()
        self.sleep.assert_not_called()
        self.load.record_connect.assert_not_called()

    def test_read_grant_refuses_write_sql(self):
        conn = self.connect(gate.READ, 'enforce', 'zone_no_write')
        with self.assertRaises(SoftechZoneWriteDenied) as cm:
            conn.prepareStatement('UPDATE items SET x=1')
        self.assertEqual(str(cm.exception), gate.WRITE_DENY_MESSAGE)
        self.assertIsInstance(cm.exception, SoftechReadOnlyError)
        conn.prepareStatement('SELECT 1')
        self.raw.prepareStatement.assert_called_once_with('SELECT 1')
        with self.assertRaises(SoftechZoneWriteDenied):
            conn.createStatement().executeUpdate('DELETE FROM stktrans5')
        with self.assertRaises(SoftechZoneWriteDenied):
            conn.setReadOnly(False)
        self.raw.setReadOnly.assert_called_once_with(True)

    def test_read_grant_log_mode_observes_but_allows_write(self):
        conn = self.connect(gate.READ, 'log', 'zone_no_write')
        conn.prepareStatement('UPDATE items SET x=1')
        conn.createStatement().executeUpdate('UPDATE items SET x=2')
        self.raw.prepareStatement.assert_called_once_with('UPDATE items SET x=1')
        self.raw.setReadOnly.assert_not_called()
        rows = AuditLog.objects.filter(action=gate.AUDIT_ACTION)
        self.assertEqual(rows.count(), 1)
        self.assertFalse(rows.get().extra['enforced'])
        self.assertEqual(rows.get().extra['reason'], 'zone_no_write')

    @override_settings(SOFTECH_READ_ONLY=True)
    def test_global_read_only_wins_and_wraps_once(self):
        conn = self.connect(gate.READ, 'enforce', 'zone_no_write')
        with self.assertRaises(SoftechReadOnlyError) as cm:
            conn.prepareStatement('UPDATE items SET x=1')
        self.assertNotIsInstance(cm.exception, SoftechZoneWriteDenied)
        self.assertIn('SOFTECH_READ_ONLY', str(cm.exception))
        self.assertIs(conn._jc, self.raw)                 # one proxy, straight over the raw conn
        self.raw.setReadOnly.assert_called_once_with(True)

    def test_full_grant_returns_raw_connection(self):
        conn = self.connect(gate.FULL, 'enforce')
        self.assertIs(conn, self.raw)
        self.driver.connect.assert_called_once()
        self.load.record_connect.assert_called_once()
        self.assertTrue(self.load.record_connect.call_args.args[2])

    def test_log_mode_refusal_comes_back_full(self):
        # check() already turns a log-mode refusal into FULL (reason kept): raw connection
        conn = self.connect(gate.FULL, 'log', 'zone_no_read')
        self.assertIs(conn, self.raw)


@override_settings(SOFTECH_READ_ONLY=False)
class ProbeGateTests(_Base):

    def test_probe_denied_does_not_connect(self):
        with mock.patch(CHECK, return_value=decision(gate.NONE, 'zone_no_read')), \
                mock.patch('config.sybase._ensure_jvm') as jvm:
            r = sybase.probe_connection('10.0.0.9', 5000)
        self.assertEqual(r, {'ok': False, 'elapsed_ms': 0.0, 'error': gate.DENY_MESSAGE,
                             'denied': True})
        jvm.assert_not_called()
        self.load.record_connect.assert_not_called()

    def test_health_sweep_skips_denied_results(self):
        from apps.sync import network_health
        nodes = [('100', 'hq.local', 5000, 'SOFTECHDB9', True),
                 ('130', '10.0.0.30', 5000, 'SOFTECHDB9', False)]
        with mock.patch(CHECK, return_value=decision(gate.NONE, 'zone_no_read')), \
                mock.patch.object(network_health, '_node_list', return_value=nodes), \
                mock.patch('config.sybase._ensure_jvm'), \
                mock.patch('jpype.isThreadAttachedToJVM', return_value=True), \
                mock.patch('apps.delivery.branch_watchdog.record_run') as record_run:
            results = network_health.probe_all_nodes(record=True)
        record_run.assert_not_called()
        self.assertEqual(set(results), {'hq.local', '10.0.0.30'})
        self.assertTrue(all(r['denied'] and not r['ok'] for r in results.values()))

    def test_health_sweep_records_only_probed_nodes(self):
        from apps.sync import network_health
        nodes = [('100', 'hq.local', 5000, 'SOFTECHDB9', True),
                 ('130', '10.0.0.30', 5000, 'SOFTECHDB9', False)]

        def fake_probe(host, port, db_name, login_timeout=None):
            if host == 'hq.local':
                return {'ok': True, 'elapsed_ms': 3.0, 'error': None}
            return {'ok': False, 'elapsed_ms': 0.0, 'error': gate.DENY_MESSAGE, 'denied': True}
        with mock.patch.object(network_health, '_node_list', return_value=nodes), \
                mock.patch('config.sybase._ensure_jvm'), \
                mock.patch('config.sybase.probe_connection', side_effect=fake_probe), \
                mock.patch('jpype.isThreadAttachedToJVM', return_value=True), \
                mock.patch('apps.delivery.branch_watchdog.record_run') as record_run:
            results = network_health.probe_all_nodes(record=True)
        record_run.assert_called_once()
        self.assertEqual(set(record_run.call_args.args[0]), {'hq.local'})
        self.assertTrue(results['10.0.0.30']['denied'])


class NoteSavepointTests(TestCase):
    """A connect happens inside a writer's atomic block: a failed audit INSERT in note() must
    not poison the caller's transaction."""

    def setUp(self):
        cache.clear()

    def test_failed_audit_write_does_not_poison_outer_transaction(self):
        def broken_log(*a, **k):
            with connection.cursor() as cur:
                cur.execute('SELECT * FROM n4_no_such_table')

        with transaction.atomic():
            with mock.patch.object(AuditLog, 'log', side_effect=broken_log):
                gate.note(decision(gate.NONE, 'zone_no_read'), 'HQ', enforced=True)
            AuditLog.objects.create(action='n4_after_note', note='still usable')
        self.assertTrue(AuditLog.objects.filter(action='n4_after_note').exists())
