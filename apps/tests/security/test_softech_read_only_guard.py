"""
SOFTECH_READ_ONLY guard integrity (Batch 2, P-8) — config/sybase.py.

  1. is_read_only_sql stripped comments BEFORE string literals, so a '--' or '/*' inside a
     quoted string hid the rest of the statement:  SELECT 'x--' DELETE FROM t  passed.
  2. The guarded statement handed out the RAW connection (stmt.getConnection()), and the
     connection proxy passed setReadOnly(False) / unwrap() straight through.
  3. SoftechConnector preferred SOFTECH_<PROFILE>_HOST over everything, so a staging box
     (SOFTECH_BRANCH_HOST_OVERRIDE set) that copied real SOFTECH_*_HOST values still
     reached production.
"""
import os
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.tests.test_security_hardening import FakeJavaConn, FakeStatement
from config import sybase
from config.sybase import SoftechReadOnlyError, _ReadOnlyJavaConnection, is_read_only_sql




class _Conn(FakeJavaConn):
    """A fake java connection whose statements point back at it (like the real driver)."""

    def createStatement(self, *args):
        st = FakeStatement(self.log)
        st.getConnection = lambda: self
        return st

    def prepareStatement(self, sql, *args):
        st = super().prepareStatement(sql, *args)
        st.getConnection = lambda: self
        return st

    def unwrap(self, cls):
        return self


class ReadOnlySqlCheckTests(SimpleTestCase):

    def test_comment_markers_inside_literals_cannot_hide_a_write(self):
        for sql in ("SELECT 'x--' DELETE FROM stktrans5",
                    "SELECT '/*' DELETE FROM stktrans5 /* */",
                    "SELECT 'it''s--' UPDATE items SET a = 1"):
            self.assertFalse(is_read_only_sql(sql), sql)

    def test_unbalanced_quote_is_refused(self):
        self.assertFalse(is_read_only_sql("SELECT a FROM t WHERE b = 'x; DELETE FROM t"))

    def test_real_reads_still_pass(self):
        for sql in ("SELECT a FROM t WHERE b = '--not a comment'",
                    "SELECT a /* note with 'quote */ FROM t",
                    "SELECT a -- trailing comment with 'quote\n FROM t WHERE c = 'x'",
                    "SET ROWCOUNT 50"):
            self.assertTrue(is_read_only_sql(sql), sql)


class ConnectionEscapeTests(SimpleTestCase):

    def test_statement_cannot_hand_out_the_raw_connection(self):
        guarded = _ReadOnlyJavaConnection(_Conn())
        for st in (guarded.createStatement(), guarded.prepareStatement('SELECT 1')):
            again = st.getConnection()
            with self.assertRaises(SoftechReadOnlyError):
                again.createStatement().execute('DELETE FROM stktrans5')

    def test_read_only_cannot_be_switched_off_or_unwrapped(self):
        raw = _Conn()
        guarded = _ReadOnlyJavaConnection(raw)
        with self.assertRaises(SoftechReadOnlyError):
            guarded.setReadOnly(False)
        with self.assertRaises(SoftechReadOnlyError):
            guarded.unwrap(object)
        self.assertTrue(raw.read_only)


class ConnectorStagingHostTests(SimpleTestCase):

    def _url(self):
        seen = {}

        def fake_connect(driver, jdbc_url, props, label=''):
            seen['url'] = jdbc_url
            return FakeJavaConn()
        with mock.patch('config.sybase._ensure_jvm'), \
                mock.patch.object(sybase.jpype.imports, 'registerDomain'), \
                mock.patch.dict('sys.modules', {
                    'com': mock.MagicMock(), 'com.sybase': mock.MagicMock(),
                    'com.sybase.jdbc3': mock.MagicMock(), 'com.sybase.jdbc3.jdbc': mock.MagicMock(),
                    'java': mock.MagicMock(), 'java.util': mock.MagicMock(), 'java.sql': mock.MagicMock()}), \
                mock.patch('config.sybase._connect_with_retry', side_effect=fake_connect):
            sybase.SoftechConnector(profile='prod').connect()
        return seen['url']

    @override_settings(SYBASE_HOST='staging-softech.local', SOFTECH_BRANCH_HOST_OVERRIDE='staging-softech.local')
    def test_staging_override_wins_over_profile_hosts(self):
        with mock.patch.dict(os.environ, {'SOFTECH_PROD_HOST': '10.0.0.99'}):
            self.assertIn('staging-softech.local', self._url())

    @override_settings(SYBASE_HOST='hq.local', SOFTECH_BRANCH_HOST_OVERRIDE='')
    def test_production_profile_hosts_unchanged(self):
        with mock.patch.dict(os.environ, {'SOFTECH_PROD_HOST': '10.0.0.99'}):
            self.assertIn('10.0.0.99', self._url())


class ConnectorTransactionTests(SimpleTestCase):
    """Batch 2, P-12: SoftechConnector.begin_transaction / commit / rollback were no-ops, so the
    A/P «rollback rehearsal» (probe_ap_writeback --rehearse) committed real cheques rows."""

    def _connector(self):
        calls = []
        wrapper = mock.Mock()
        wrapper.begin.side_effect = lambda: calls.append('begin')
        wrapper.commit.side_effect = lambda: calls.append('commit')
        wrapper.rollback.side_effect = lambda: calls.append('rollback')
        sc = sybase.SoftechConnector(profile='prod')
        sc._conn = wrapper
        return sc, calls

    def test_rollback_really_rolls_back(self):
        sc, calls = self._connector()
        sc.begin_transaction()
        sc.rollback()
        self.assertEqual(calls, ['begin', 'rollback'])

    def test_commit_really_commits(self):
        sc, calls = self._connector()
        sc.begin_transaction()
        sc.commit()
        self.assertEqual(calls, ['begin', 'commit'])
