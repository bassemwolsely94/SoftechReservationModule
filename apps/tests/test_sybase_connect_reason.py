"""
apps/tests/test_sybase_connect_reason.py

A failed SOFTECH login logs the server's own reason. jConnect's JZ00L ("Login failed. Examine
the SQLWarnings chained to this exception") hides it in getNextException(); without it the
branch-130 outage of 2026-11-04 could not be told apart from a changed password.
No real Sybase: the exceptions are fakes with the jConnect method names.
"""
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.access import softech_gate as gate
from apps.access.softech_gate import GateDecision
from config import sybase


class FakeSQLException(Exception):
    def __init__(self, message, nxt=None):
        super().__init__(message)
        self._message, self._next = message, nxt

    def getMessage(self):
        return self._message

    def getNextException(self):
        return self._next


def jz00l(*reasons):
    nxt = None
    for r in reversed(reasons):
        nxt = FakeSQLException(r, nxt)
    return FakeSQLException('JZ00L: Login failed.  Examine the SQLWarnings chained to this '
                            'exception for the reason(s).', nxt)


class ReasonChainTests(SimpleTestCase):

    def test_chain_is_read_in_order_without_duplicates(self):
        exc = jz00l('There are not enough user connections available.', 'Login failed.',
                    'Login failed.')
        self.assertEqual(sybase.sql_reason_chain(exc),
                         'There are not enough user connections available. | Login failed.')

    def test_plain_python_error_has_no_chain(self):
        self.assertEqual(sybase.sql_reason_chain(RuntimeError('boom')), '')
        self.assertEqual(sybase._connect_error_text(RuntimeError('boom')), 'boom')

    def test_chain_is_capped(self):
        exc = jz00l(*[f'r{i}' for i in range(10)])
        self.assertEqual(sybase.sql_reason_chain(exc, limit=3), 'r0 | r1 | r2')

    def test_error_text_fits_the_watchdog_cap_and_keeps_the_reason(self):
        reason = 'There are not enough user connections available to start a new process.'
        text = sybase._connect_error_text(jz00l(reason))
        self.assertLessEqual(len(text), 200)
        self.assertIn(reason, text)
        self.assertTrue(text.startswith('JZ00L'))


@override_settings(SOFTECH_READ_ONLY=False)
class RetryLogTests(SimpleTestCase):

    def test_each_failed_attempt_logs_the_server_reason(self):
        driver = mock.Mock()
        driver.connect.side_effect = jz00l('Login failed: max user connections reached.')
        with mock.patch('apps.access.softech_gate.check',
                        return_value=GateDecision(gate.FULL, None, 'x', 'Z1')), \
                mock.patch('config.sybase._load'), mock.patch('config.sybase.time.sleep'), \
                self.assertLogs('elrezeiky.sync', level='WARNING') as logs:
            with self.assertRaises(FakeSQLException):
                sybase._connect_with_retry(driver, 'jdbc:x', mock.Mock(), label='branch 10.0.0.9')
        self.assertEqual(len(logs.output), sybase.SYBASE_CONNECT_ATTEMPTS)
        for line in logs.output:
            self.assertIn('server: Login failed: max user connections reached.', line)
