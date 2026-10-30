"""probe_softech_change_columns (doc 30 Phase 2): read-only, every section runs, and
the stock verdict reflects whether modif_lastupdate followed today's movements."""
import datetime
import io
import os
import tempfile
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from config.sybase import is_read_only_sql

NOW = datetime.datetime.now().replace(microsecond=0)


class _Cur:
    def __init__(self, conn):
        self.conn, self.rows = conn, []

    def execute(self, sql, params=None, timeout=None):
        self.conn.sql.append(sql)
        s = ' '.join(sql.split()).lower()
        if s.startswith('set rowcount'):
            self.rows = []
        elif 'from softechdb9.dbo.syscolumns' in s:
            self.rows = {'stkbal': [('modif_lastupdate', 'datetime')],
                         'localcustomers': [('custdate', 'datetime')]}.get(params[0], [('x', 'int')])
        elif 'from softechdb9.dbo.stkbal where branchcode' in s:
            self.rows = [('I1', 'S1', NOW if self.conn.bumped else NOW - datetime.timedelta(days=2))]
        elif 'from softechdb9.dbo.stkbal' in s:
            self.rows = [(1000, 0, NOW - datetime.timedelta(days=900), NOW, 40, 300, 900, 600, NOW)]
        elif 'group by st.itemcode' in s:
            self.rows = [('I1', '130', 'S1', '115', NOW - datetime.timedelta(minutes=30))]
        elif 'group by st.doccode' in s:
            self.rows = [('115', 500, 3, 0)]
        elif "st.doccode in ('115', '30')" in s:
            self.rows = [(120, 0, NOW)]
        elif 'from softechdb9.dbo.items' in s and 'count(*)' in s:
            self.rows = [(37000, 10, NOW, 5, 40)]
        elif 'from softechdb9.dbo.items' in s:
            self.rows = []
        elif 'count(*) from softechdb9.dbo.localcustomers' in s:
            self.rows = [(200000,)]
        elif 'from softechdb9.dbo.localcustomers' in s:
            self.rows = [(10, NOW, 30, 200)]
        else:
            self.rows = []

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class _Conn:
    def __init__(self, bumped=True):
        self.bumped, self.sql = bumped, []

    def cursor(self):
        return _Cur(self)

    def close(self):
        pass


class ProbeChangeColumnsTests(TestCase):

    def _run(self, conn):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d, \
             mock.patch('config.sybase.get_sybase_connection', return_value=conn):
            path = os.path.join(d, 'probe.txt')
            call_command('probe_softech_change_columns', out=path, stdout=out)
            self.assertTrue(os.path.exists(path))
        return out.getvalue()

    def test_all_sections_run_read_only(self):
        conn = _Conn()
        text = self._run(conn)
        self.assertNotIn('! failed', text)
        for n in range(1, 7):
            self.assertIn(f'[{n}]', text)
        self.assertTrue(conn.sql)
        self.assertEqual([q for q in conn.sql if not is_read_only_sql(q)], [])

    def test_stock_verdict(self):
        self.assertIn('safe to pull stock by modif_lastupdate', self._run(_Conn(bumped=True)))
        self.assertIn('NOT every movement bumps it', self._run(_Conn(bumped=False)))
