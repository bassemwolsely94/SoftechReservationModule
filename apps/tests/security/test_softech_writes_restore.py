"""
SOFTECH write safety — restore-based rehearsals (Batch 2, P-13).

probe_write (stkbal.monthlyqty), probe_coverage_write (stkbal.maxnowqtymonths) and
probe_approve_isr (stockisrm.israpp) write a REAL marker to SOFTECH, read it back, then
write the original back. The restore was plain sequential code: if the readback failed
(dropped link, timeout, bad row) the marker stayed in SOFTECH — for the ISR probe that is a
real approval of a pending ISR. The restore must run whatever happens after the marker.
"""
from unittest import mock

from django.test import TestCase, override_settings

from apps.purchasing import coverage_writer, isr_writer, rate_writer
from apps.tests.factories import make_branch


class _Cursor:
    """Every SELECT after the marker UPDATE (and before the restore) fails."""

    def __init__(self, row):
        self.row = row
        self.updates = []

    def execute(self, sql, params=None):
        if sql.lstrip().upper().startswith('UPDATE'):
            self.updates.append((sql, list(params or [])))
        elif len(self.updates) == 1:
            raise RuntimeError('link dropped mid-rehearsal')

    def fetchone(self):
        return self.row

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def close(self):
        pass


@override_settings(SOFTECH_PROBES_ENABLED=True, COVERAGE_WRITER_ENABLED=True)
class RestoreAlwaysRunsTests(TestCase):

    def setUp(self):
        make_branch(softech_id='130')

    def _run(self, fn, cur, patches):
        for p in patches:
            p.start()
        try:
            with self.assertRaises(RuntimeError):
                fn()
        finally:
            for p in patches:
                p.stop()
        self.assertEqual(len(cur.updates), 2, 'marker written but never restored')
        return cur.updates[-1]

    def test_rate_probe_restores_after_failed_readback(self):
        cur = _Cursor((5.0, 'U1', None))
        sql, params = self._run(
            lambda: rate_writer.probe_write('130', '87602', confirm=True), cur,
            [mock.patch.object(rate_writer, 'resolve_store', return_value='130'),
             mock.patch('config.sybase.get_branch_connection', return_value=_Conn(cur))])
        self.assertEqual(params[0], 5.0)

    def test_coverage_probe_restores_after_failed_readback(self):
        cur = _Cursor((2.0,))
        sql, _ = self._run(
            lambda: coverage_writer.probe_coverage_write('130', '87602', confirm=True), cur,
            [mock.patch.object(coverage_writer, 'resolve_store', return_value='130'),
             mock.patch.object(coverage_writer, '_read_conn_for_target', return_value=_Conn(cur))])
        self.assertIn('maxnowqtymonths=' + coverage_writer._lit(2.0) + ',', sql)

    def test_isr_approve_probe_restores_after_failed_readback(self):
        cur = _Cursor((0,))
        sql, params = self._run(
            lambda: isr_writer.probe_approve_isr('130', 261305, confirm=True), cur,
            [mock.patch('config.sybase.get_branch_connection', return_value=_Conn(cur))])
        self.assertEqual(params[0], 0, 'pending ISR left approved')
