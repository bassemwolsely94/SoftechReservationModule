"""N4 "before enforce" items - the SOFTECH gate's last gaps before SOFTECH_GATE_ENFORCEMENT=enforce.

  1. getMetaData().getConnection() and ResultSet.getStatement().getConnection() reached the raw
     connection through the read-only proxy's __getattr__.
  2. mode() ran twice per READ connect (the second call unguarded, repeating the unsafe ERROR):
     the mode now rides on the decision.
  3. An enforced write refusal was logged twice (note() + a second line in config/sybase.py).
  4. The health sweep's "reachable x/y" counted the nodes the gate refused.
  5. Missing tests: enforce unwrap / prepareCall / addBatch, log-mode pass-through, a failing
     note(), end to end through get_branch_connection / SoftechConnector.

No real Sybase: the driver and the java connection are Mock()s.
"""
import logging
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.access import softech_gate as gate
from apps.access.network import INTERNAL
from apps.access.softech_gate import GateDecision
from apps.audit.models import AuditLog
from config import sybase
from config.sybase import SoftechAccessDenied, SoftechReadOnlyError, SoftechZoneWriteDenied

CHECK = 'apps.access.softech_gate.check'
MODE = 'apps.access.softech_gate.mode'
NOTE = 'apps.access.softech_gate.note'
WRITE = 'DELETE FROM stktrans5 WHERE docnumber = 1'


def decision(grant, mode, reason='zone_no_write'):
    return GateDecision(grant, reason, 'web:external:x', 'Z3', mode)


class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.raw = mock.Mock(name='java_conn')
        self.driver = mock.Mock(name='driver')
        self.driver.connect.return_value = self.raw
        for p in (mock.patch('config.sybase._load'), mock.patch('config.sybase.time.sleep')):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        cache.clear()

    def connect(self, grant, mode, reason='zone_no_write'):
        # gate.mode() must not be asked again: the decision carries the mode
        with mock.patch(CHECK, return_value=decision(grant, mode, reason)), \
                mock.patch(MODE, side_effect=AssertionError('mode() called twice')):
            return sybase._connect_with_retry(self.driver, 'jdbc:x', mock.Mock(), label='HQ')


@override_settings(SOFTECH_READ_ONLY=False)
class RawConnectionEscapeTests(_Base):
    """Item 1 - nothing a guarded connection hands out leads back to the raw connection."""

    def test_metadata_get_connection_is_the_guarded_connection(self):
        conn = self.connect(gate.READ, 'enforce')
        again = conn.getMetaData().getConnection()
        self.assertIs(again, conn)
        with self.assertRaises(SoftechZoneWriteDenied):
            again.createStatement().execute(WRITE)

    def test_result_set_statement_is_guarded(self):
        conn = self.connect(gate.READ, 'enforce')
        stmt = conn.createStatement()
        for rs in (stmt.executeQuery('SELECT 1'), stmt.getResultSet(), stmt.getGeneratedKeys(),
                   conn.prepareStatement('SELECT 1').executeQuery()):
            back = rs.getStatement()
            self.assertIs(back.getConnection(), conn)
            with self.assertRaises(SoftechZoneWriteDenied):
                back.executeUpdate(WRITE)

    def test_metadata_result_sets_are_guarded(self):
        conn = self.connect(gate.READ, 'enforce')
        tables = conn.getMetaData().getTables(None, None, '%', None)
        self.assertIs(tables.getStatement().getConnection(), conn)
        with self.assertRaises(SoftechZoneWriteDenied):
            tables.getStatement().execute(WRITE)

    def test_fetch_getters_go_straight_through_and_are_cached(self):
        conn = self.connect(gate.READ, 'enforce')
        rs = conn.createStatement().executeQuery('SELECT 1')
        raw_rs = self.raw.createStatement.return_value.executeQuery.return_value
        raw_rs.getString.return_value = 'x'
        self.assertEqual(rs.getString(1), 'x')
        self.assertIs(rs.getString, raw_rs.getString)       # cached, no wrapper per row

    def test_enforce_refuses_unwrap_everywhere(self):
        conn = self.connect(gate.READ, 'enforce')
        stmt = conn.createStatement()
        rs = stmt.executeQuery('SELECT 1')
        for obj in (conn, stmt, rs, rs.getStatement(), conn.getMetaData()):
            with self.assertRaises(SoftechZoneWriteDenied):
                obj.unwrap(object)
        self.raw.unwrap.assert_not_called()

    def test_enforce_refuses_prepare_call_and_write_batches(self):
        conn = self.connect(gate.READ, 'enforce')
        with self.assertRaises(SoftechZoneWriteDenied):
            conn.prepareCall('sp_updatestock ?')
        self.raw.prepareCall.assert_not_called()
        stmt = conn.createStatement()
        with self.assertRaises(SoftechZoneWriteDenied):
            stmt.addBatch('UPDATE items SET x = 1')
        self.raw.createStatement.return_value.addBatch.assert_not_called()
        stmt.addBatch('SELECT 1')

    @override_settings(SOFTECH_READ_ONLY=True)
    def test_global_read_only_proxy_is_hardened_too(self):
        conn = sybase._guard(self.raw)
        self.assertIs(conn.getMetaData().getConnection(), conn)
        rs = conn.createStatement().executeQuery('SELECT 1')
        with self.assertRaises(SoftechReadOnlyError):
            rs.getStatement().execute(WRITE)
        with self.assertRaises(SoftechReadOnlyError):
            rs.unwrap(object)


@override_settings(SOFTECH_READ_ONLY=False)
class LogModePassThroughTests(_Base):
    """Item 5 - log mode (observe-only) records would-be writes and lets everything through."""

    def test_unwrap_prepare_call_and_batches_pass_and_are_noted_once(self):
        conn = self.connect(gate.READ, 'log')
        self.assertIs(conn.unwrap(object), self.raw.unwrap.return_value)
        stmt = conn.createStatement()
        stmt.addBatch('UPDATE items SET x = 1')
        stmt.executeQuery('SELECT 1').getStatement().execute(WRITE)
        self.assertIs(stmt.unwrap(object), self.raw.createStatement.return_value.unwrap.return_value)
        conn.prepareCall('sp_updatestock ?').execute()
        conn.setReadOnly(False)
        self.raw.prepareCall.assert_called_once_with('sp_updatestock ?')
        self.raw.createStatement.return_value.addBatch.assert_called_once_with(
            'UPDATE items SET x = 1')
        self.raw.setReadOnly.assert_called_once_with(False)
        rows = AuditLog.objects.filter(action=gate.AUDIT_ACTION)
        self.assertEqual(rows.count(), 1)                    # deduplicated
        self.assertFalse(rows.get().extra['enforced'])
        self.assertEqual(rows.get().extra['mode'], 'log')

    def test_log_mode_full_is_the_raw_connection(self):
        self.assertIs(self.connect(gate.FULL, 'log', 'zone_no_read'), self.raw)


@override_settings(SOFTECH_READ_ONLY=False)
class FailingNoteTests(_Base):
    """Item 5 - a note() that raises never changes the outcome."""

    def test_enforce_write_is_still_refused(self):
        conn = self.connect(gate.READ, 'enforce')
        with mock.patch(NOTE, side_effect=RuntimeError('audit down')):
            with self.assertRaises(SoftechZoneWriteDenied):
                conn.prepareStatement('UPDATE items SET x = 1')
        self.raw.prepareStatement.assert_not_called()

    def test_log_mode_write_still_passes(self):
        conn = self.connect(gate.READ, 'log')
        with mock.patch(NOTE, side_effect=RuntimeError('audit down')):
            conn.prepareStatement('UPDATE items SET x = 1')
        self.raw.prepareStatement.assert_called_once()

    @override_settings(SOFTECH_GATE_ENFORCEMENT='enforce')
    def test_check_keeps_an_enforced_refusal_inside_the_network(self):
        # before: note() raising sent check() to gate_error, which is FULL inside the network
        ctx = SimpleNamespace(zone='Z3', failed=False, user_id=None,
                              network=SimpleNamespace(zone=INTERNAL, ip='10.0.0.1'), device=None)
        with mock.patch('apps.access.policy_middleware.enforce_problem', return_value=None), \
                mock.patch('apps.sync.softech_load.current_scope', return_value='web:x'), \
                mock.patch('apps.access.context.current', return_value=ctx), \
                mock.patch(NOTE, side_effect=RuntimeError('audit down')):
            d = gate.check('t')
        self.assertEqual(d.grant, gate.NONE)
        self.assertEqual(d.reason, 'anonymous')
        self.assertEqual(d.mode, 'enforce')


@override_settings(SOFTECH_READ_ONLY=False, SOFTECH_GATE_ENFORCEMENT='enforce')
class ModeCarriedTests(_Base):
    """Item 2 - one mode() per connect: the unsafe-setup ERROR is not repeated."""

    def test_unsafe_enforce_logs_once_per_read_connect(self):
        ctx = SimpleNamespace(zone='Z3', failed=False, user_id=None,
                              network=SimpleNamespace(zone='external', ip='1.2.3.4'), device=None)
        with mock.patch('apps.access.policy_middleware.enforce_problem',
                        return_value='no proxy'), \
                mock.patch('apps.access.policy_middleware._log_unsafe') as unsafe, \
                mock.patch('apps.sync.softech_load.current_scope', return_value='web:x'), \
                mock.patch('apps.access.context.current', return_value=ctx), \
                mock.patch('apps.access.softech_gate.decide',
                           return_value=GateDecision(gate.READ, 'zone_no_write', 'web:x', 'Z3')):
            conn = sybase._connect_with_retry(self.driver, 'jdbc:x', mock.Mock(), label='HQ')
            conn.prepareStatement('UPDATE items SET x = 1')     # unsafe enforce runs as log
        self.assertEqual(unsafe.call_count, 1)

    def test_check_carries_its_mode(self):
        with mock.patch('apps.access.policy_middleware.enforce_problem', return_value=None), \
                mock.patch('apps.sync.softech_load.current_scope', return_value='job:x'):
            self.assertEqual(gate.check('t').mode, 'enforce')
        with override_settings(SOFTECH_GATE_ENFORCEMENT='off'), \
                mock.patch('apps.sync.softech_load.current_scope', return_value='web:x'):
            self.assertEqual(gate.check('t').mode, 'off')

    def test_hand_built_decision_falls_back_to_a_guarded_lookup(self):
        d = GateDecision(gate.READ, 'zone_no_write', 'web', 'Z3')
        with mock.patch(MODE, side_effect=RuntimeError('boom')):
            self.assertEqual(gate.mode_of(d), 'log')


@override_settings(SOFTECH_READ_ONLY=False)
class SingleRefusalLogTests(_Base):
    """Item 3 - an enforced write refusal is one log line (note()), not two."""

    def test_one_line_per_refusal(self):
        conn = self.connect(gate.READ, 'enforce')
        with self.assertLogs('elrezeiky', level=logging.WARNING) as logs:
            with self.assertRaises(SoftechZoneWriteDenied):
                conn.prepareStatement('UPDATE items SET x = 1')
        self.assertEqual(len(logs.records), 1, logs.output)
        self.assertIn('softech gate denied', logs.output[0])


@override_settings(SOFTECH_READ_ONLY=False)
class HealthCountTests(TestCase):
    """Item 4 - "reachable x/y" leaves out the nodes the gate refused."""

    def test_refused_nodes_are_not_in_the_count(self):
        from apps.sync import network_health
        nodes = [('100', 'hq.local', 5000, 'SOFTECHDB9', True),
                 ('130', '10.0.0.30', 5000, 'SOFTECHDB9', False),
                 ('160', '10.0.0.60', 5000, 'SOFTECHDB9', False)]
        answers = {
            'hq.local': {'ok': True, 'elapsed_ms': 3.0, 'error': None},
            '10.0.0.30': {'ok': False, 'elapsed_ms': 0.0, 'error': gate.DENY_MESSAGE,
                          'denied': True},
            '10.0.0.60': {'ok': False, 'elapsed_ms': 8000.0, 'error': 'timeout'},
        }
        with mock.patch.object(network_health, '_node_list', return_value=nodes), \
                mock.patch('config.sybase._ensure_jvm'), \
                mock.patch('jpype.isThreadAttachedToJVM', return_value=True), \
                mock.patch('config.sybase.probe_connection',
                           side_effect=lambda h, *a, **k: dict(answers[h])), \
                mock.patch('apps.delivery.branch_watchdog.record_run') as record_run, \
                self.assertLogs('elrezeiky', level=logging.INFO) as logs:
            network_health.probe_all_nodes(record=True)
        self.assertIn('reachable 1/2', '\n'.join(logs.output))
        self.assertEqual(set(record_run.call_args.args[0]), {'hq.local', '10.0.0.60'})


def _java_modules(driver):
    jdbc = mock.MagicMock()
    jdbc.SybDriver.return_value = driver
    return {'com': mock.MagicMock(), 'com.sybase': mock.MagicMock(),
            'com.sybase.jdbc3': mock.MagicMock(), 'com.sybase.jdbc3.jdbc': jdbc,
            'java': mock.MagicMock(), 'java.util': mock.MagicMock(), 'java.sql': mock.MagicMock()}


@override_settings(SOFTECH_READ_ONLY=False, SYBASE_HOST='hq.local', SYBASE_USER='u',
                   SYBASE_PASSWORD='p', SOFTECH_BRANCH_HOST_OVERRIDE='')
class EndToEndTests(_Base):
    """Item 5 - the public entry points carry the gate all the way to the statement."""

    def _open(self, d, opener):
        with mock.patch('config.sybase._ensure_jvm'), \
                mock.patch.object(sybase.jpype.imports, 'registerDomain'), \
                mock.patch.dict('sys.modules', _java_modules(self.driver)), \
                mock.patch(CHECK, return_value=d), \
                mock.patch(MODE, side_effect=AssertionError('mode() called twice')):
            return opener()

    def _read_then_write(self, cursor):
        self.raw.createStatement.return_value.execute.return_value = False    # no result set
        cursor.execute('SET ROWCOUNT 1')
        with self.assertRaises(SoftechZoneWriteDenied):
            cursor.execute('UPDATE items SET x = 1')
        with self.assertRaises(SoftechZoneWriteDenied):
            cursor.execute('UPDATE items SET x = ?', [1])
        self.raw.createStatement.return_value.execute.assert_called_once_with('SET ROWCOUNT 1')
        self.raw.prepareStatement.assert_not_called()

    def test_branch_connection_read_grant_refuses_writes(self):
        wrapper = self._open(decision(gate.READ, 'enforce'),
                             lambda: sybase.get_branch_connection('10.0.0.30'))
        self._read_then_write(wrapper.cursor())

    def test_branch_connection_refused_never_connects(self):
        with self.assertRaises(SoftechAccessDenied):
            self._open(decision(gate.NONE, 'enforce', 'zone_no_read'),
                       lambda: sybase.get_branch_connection('10.0.0.30'))
        self.driver.connect.assert_not_called()

    def test_softech_connector_read_grant_refuses_writes(self):
        sc = self._open(decision(gate.READ, 'enforce'),
                        lambda: sybase.SoftechConnector(profile='prod').connect())
        self._read_then_write(sc._cursor())
        with self.assertRaises(SoftechZoneWriteDenied):
            sc.execute_stored_procedure('sp_updatestock', ['1'])

    def test_softech_connector_log_mode_lets_the_write_through(self):
        sc = self._open(decision(gate.READ, 'log'),
                        lambda: sybase.SoftechConnector(profile='prod').connect())
        self.raw.createStatement.return_value.execute.return_value = False
        sc._cursor().execute('UPDATE items SET x = 1')
        self.raw.createStatement.return_value.execute.assert_called_once_with(
            'UPDATE items SET x = 1')
        self.assertEqual(AuditLog.objects.filter(action=gate.AUDIT_ACTION).count(), 1)
