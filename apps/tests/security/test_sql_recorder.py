"""Tests for the RecordingSybase test double used by the SQL-injection tests."""
from django.test import SimpleTestCase

from .sql_recorder import RecordingSybase, assert_payload_bound


class RecordingSybaseTests(SimpleTestCase):

    def test_records_sql_and_params(self):
        import config.sybase
        with RecordingSybase(rows=[('A', 1)]) as rec:
            conn = config.sybase.get_sybase_connection()
            cur = conn.cursor()
            cur.execute('SELECT a FROM t WHERE b = ?', ['x'])
            self.assertEqual(cur.fetchall(), [('A', 1)])
            conn.close()
        self.assertEqual(rec.calls, [('SELECT a FROM t WHERE b = ?', ['x'])])

    def test_branch_connection_recorded_too(self):
        import config.sybase
        with RecordingSybase() as rec:
            config.sybase.get_branch_connection('10.0.0.1').cursor().execute('SELECT 1')
        self.assertEqual(rec.calls, [('SELECT 1', [])])

    def test_softech_connector_recorded_too(self):
        from config.sybase import SoftechConnector
        with RecordingSybase() as rec:
            conn = SoftechConnector(profile='prod').connect()
            conn._cursor().execute('SELECT a FROM t WHERE b = ?', ['x'])
            conn.execute_query('SELECT 2')
            conn.close()
        self.assertEqual(rec.calls, [('SELECT a FROM t WHERE b = ?', ['x']), ('SELECT 2', [])])

    def test_placeholder_count_mismatch_raises(self):
        import config.sybase
        with RecordingSybase():
            cur = config.sybase.get_sybase_connection().cursor()
            with self.assertRaises(AssertionError):
                cur.execute('SELECT a FROM t WHERE b = ? AND c = ?', ['only-one'])

    def test_assert_payload_bound_fails_when_pasted(self):
        calls = [("SELECT a FROM t WHERE b = '1' OR '1'='1'", [])]
        with self.assertRaises(AssertionError):
            assert_payload_bound(self, calls, "1' OR '1'='1")

    def test_assert_payload_bound_fails_when_absent(self):
        with self.assertRaises(AssertionError):
            assert_payload_bound(self, [('SELECT 1', [])], "x' --")

    def test_assert_payload_bound_passes_when_bound(self):
        assert_payload_bound(self, [('SELECT a FROM t WHERE b = ?', ["1' OR '1'='1"])],
                             "1' OR '1'='1")
