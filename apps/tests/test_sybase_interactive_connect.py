"""
SOFTECH connects made for a person waiting on a screen fail fast and skip a node that just failed
(design docs/superpowers/specs/2026-11-19-softech-interactive-connect-design.md). Background connects
(syncs, writers) keep today's retries and never read or write the dead-node memory.

No real Sybase: the driver and the java connection are Mock()s, as in the N4 connect tests.
"""
import datetime
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from apps.access import softech_gate as gate
from apps.access.softech_gate import GateDecision
from config import sybase

CHECK = 'apps.access.softech_gate.check'
MODE = 'apps.access.softech_gate.mode'


@override_settings(SOFTECH_READ_ONLY=False)
class _Base(TestCase):
    def setUp(self):
        cache.clear()
        self.driver = mock.Mock(name='driver')
        self.driver.connect.return_value = mock.Mock(name='java_conn')
        for p in (mock.patch('config.sybase._load', return_value=mock.Mock()),
                  mock.patch(CHECK, return_value=GateDecision(gate.FULL, None, 'web:x', 'Z1')),
                  mock.patch(MODE, return_value='enforce')):
            p.start()
            self.addCleanup(p.stop)
        self.sleep = mock.patch('config.sybase.time.sleep').start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        cache.clear()

    def interactive(self, node='branch 10.0.0.5:5000'):
        return sybase._connect_with_retry(self.driver, 'jdbc:x', mock.Mock(), label='branch 10.0.0.5',
                                          interactive=True, node_key=node)

    def background(self):
        return sybase._connect_with_retry(self.driver, 'jdbc:x', mock.Mock(), label='branch 10.0.0.5')


class InteractiveConnectTests(_Base):

    def test_one_attempt_and_no_pause(self):
        self.driver.connect.side_effect = RuntimeError('JZ006 connect timed out')
        with self.assertRaises(RuntimeError):
            self.interactive()
        self.assertEqual(self.driver.connect.call_count, 1)
        self.sleep.assert_not_called()

    def test_background_keeps_three_attempts_with_pause(self):
        self.driver.connect.side_effect = RuntimeError('down')
        with self.assertRaises(RuntimeError):
            self.background()
        self.assertEqual(self.driver.connect.call_count, sybase.SYBASE_CONNECT_ATTEMPTS)
        self.assertEqual(self.sleep.call_count, sybase.SYBASE_CONNECT_ATTEMPTS - 1)

    def test_failed_node_is_skipped_without_calling_the_driver(self):
        self.driver.connect.side_effect = RuntimeError('down')
        with self.assertRaises(RuntimeError):
            self.interactive()
        self.driver.connect.reset_mock()
        with self.assertRaises(sybase.SoftechNodeUnavailable):
            self.interactive()
        self.driver.connect.assert_not_called()

    def test_other_nodes_are_not_skipped(self):
        self.driver.connect.side_effect = RuntimeError('down')
        with self.assertRaises(RuntimeError):
            self.interactive('branch 10.0.0.5:5000')
        self.driver.connect.side_effect = None
        self.assertIsNotNone(self.interactive('HQ'))

    def test_memory_expires(self):
        self.driver.connect.side_effect = RuntimeError('down')
        with self.assertRaises(RuntimeError):
            self.interactive()
        later = sybase.time.time() + sybase.SYBASE_DEAD_NODE_SECONDS + 1
        self.driver.connect.side_effect = None
        with mock.patch('config.sybase.time.time', return_value=later):
            self.assertIsNotNone(self.interactive())

    def test_success_clears_the_memory(self):
        self.driver.connect.side_effect = RuntimeError('down')
        with self.assertRaises(RuntimeError):
            self.interactive()
        later = sybase.time.time() + sybase.SYBASE_DEAD_NODE_SECONDS + 1
        self.driver.connect.side_effect = None
        with mock.patch('config.sybase.time.time', return_value=later):
            self.interactive()
        self.assertIsNotNone(self.interactive())          # not skipped any more, even inside the window

    def test_background_ignores_and_never_writes_the_memory(self):
        self.driver.connect.side_effect = RuntimeError('down')
        with self.assertRaises(RuntimeError):
            self.background()
        self.driver.connect.reset_mock()
        with self.assertRaises(RuntimeError):            # interactive still tries: background wrote nothing
            self.interactive()
        self.assertEqual(self.driver.connect.call_count, 1)
        with self.assertRaises(sybase.SoftechNodeUnavailable):
            self.interactive()
        self.driver.connect.reset_mock()
        with self.assertRaises(RuntimeError):            # background never reads the memory
            self.background()
        self.assertEqual(self.driver.connect.call_count, sybase.SYBASE_CONNECT_ATTEMPTS)

    def test_gate_refusal_is_not_remembered_as_a_dead_node(self):
        with mock.patch(CHECK, return_value=GateDecision(gate.NONE, 'zone_no_read', 'web:x', 'Z3')):
            with self.assertRaises(sybase.SoftechAccessDenied):
                self.interactive()
        self.assertIsNotNone(self.interactive())


class LoginTimeoutTests(SimpleTestCase):

    def test_interactive_login_timeout_is_set_on_the_connection(self):
        props = mock.Mock()
        sybase._apply_login_timeout(props, sybase.SYBASE_INTERACTIVE_LOGIN_TIMEOUT_SECONDS)
        props.setProperty.assert_called_once_with('LOGIN_TIMEOUT', '5')

    def test_default_login_timeout_unchanged(self):
        props = mock.Mock()
        sybase._apply_login_timeout(props)
        props.setProperty.assert_called_once_with('LOGIN_TIMEOUT', str(sybase.SYBASE_LOGIN_TIMEOUT_SECONDS))


class UsagePrintUsesInteractiveTests(SimpleTestCase):

    def test_live_lookup_connects_interactively_branch_then_hq(self):
        from apps.usage_print import lookup
        branch = mock.Mock(db_host='10.0.0.5', effective_db_host='10.0.0.5', effective_db_port=5000,
                           softech_branch_id='130')
        hq_conn = mock.Mock()
        hq_conn.cursor.return_value.fetchall.return_value = [('100', 1, 'P1')]
        with mock.patch('config.sybase.get_branch_connection',
                        side_effect=sybase.SoftechNodeUnavailable('branch 10.0.0.5')) as br, \
                mock.patch('config.sybase.get_sybase_connection', return_value=hq_conn) as hq:
            rows = lookup._read_live(branch, 123, datetime.date(2026, 11, 19))
        self.assertEqual(rows, [('100', 1, 'P1')])
        self.assertTrue(br.call_args.kwargs.get('interactive'))
        self.assertTrue(hq.call_args.kwargs.get('interactive'))

    def test_both_down_raises_live_unavailable(self):
        from apps.usage_print import lookup
        branch = mock.Mock(db_host='10.0.0.5', effective_db_host='10.0.0.5', effective_db_port=5000,
                           softech_branch_id='130')
        with mock.patch('config.sybase.get_branch_connection', side_effect=RuntimeError('down')), \
                mock.patch('config.sybase.get_sybase_connection', side_effect=RuntimeError('down')):
            with self.assertRaises(lookup.LiveUnavailable):
                lookup._read_live(branch, 123, datetime.date(2026, 11, 19))
