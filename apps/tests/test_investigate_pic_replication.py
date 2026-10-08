"""B7 replication probe (investigate_pic_replication) — read-only; HQ and a node replaced by fake connections."""
import datetime as dt
import io
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

D = dt.datetime
# phcode, status, lock, branch, trans_time, table_dumped, status_time, pphcode
HQ = [('03HD1', '0', 0, '130', D(2025, 1, 2), D(2024, 6, 1), D(2025, 1, 2), '03HD1'),   # deactivated after last ship
      ('06HD2', '1', 0, '150', D(2024, 1, 1), D(2024, 1, 1, 0, 5), None, '06HD2'),
      ('06HD3', '1', 0, '150', D(2024, 1, 1), None, None, '06HD3'),                       # never shipped
      ('150HD4', '1', 0, '150', D(2024, 1, 1), D(2024, 1, 2), None, '150HD4')]          # node lost it
NODE = [('03HD1', '1', 0, '130', D(2024, 6, 1), D(2024, 6, 1), None, '03HD1'),           # still active here
        ('06HD2', '1', 0, '150', D(2024, 1, 1), D(2024, 1, 1, 0, 5), None, '06HD2'),
        ('06HD3', '1', 0, '150', D(2024, 1, 1), None, None, '06HD3')]
PTS_HQ = [('03HD1', 9, 0, None), ('06HD2', 4450, 3960, None), ('06HD3', 10, 0, None)]
PTS_NODE = [('03HD1', 9, 0, None), ('06HD2', 4450, 3960, None), ('06HD3', 20, 0, None)]


class Cur:
    def __init__(self, node):
        self.node = node

    def execute(self, sql, p=None):
        s, self.r, self.description = ' '.join(sql.split()), [], [('a',)]
        if s.startswith('SELECT phcode, phcodestatus'):
            self.r = NODE if self.node else HQ
        elif s.startswith('SELECT phcode, totpoints'):
            self.r = PTS_NODE if self.node else PTS_HQ
        elif 'lastdocnumbers' in s:
            self.r = [('150',)]
        elif s.startswith('SELECT count(*), sum(case'):
            self.r = [(3, 3)]
        elif 'syscolumns' in s:
            self.r = [('branchcode',), ('phcode',), ('totpoints',), ('trans_time',)] if p == ['lcpointstrans'] else []
        elif s.startswith('SELECT count(*) FROM'):
            self.r = [(1,)]
        elif s.startswith('SELECT branchcode, phcode, totpoints, trans_time'):
            self.description = [('branchcode',), ('phcode',), ('totpoints',), ('trans_time',)]
            self.r = [('150', '06HD2', 4450, D(2026, 1, 1))]

    def fetchall(self):
        return self.r


class Conn:
    def __init__(self, node=False):
        self.node = node

    def cursor(self):
        return Cur(self.node)

    def close(self):
        pass


class ReplicationProbeTests(TestCase):
    def test_reports_unreplicated_deactivation_and_mismatches(self):
        out = io.StringIO()
        with mock.patch('config.sybase.get_sybase_connection', return_value=Conn()), \
                mock.patch('config.sybase.get_branch_connection', return_value=Conn(node=True)):
            call_command('investigate_pic_replication', host=['10.0.0.1'], out='', stdout=out)
        t = out.getvalue()
        self.assertIn('10.0.0.1: own branch 150 · 3 customers', t)
        self.assertIn("03HD1: HQ status='0'", t)
        self.assertIn("10.0.0.1: status='1' lock=0", t)
        self.assertIn('◀ DIFFERENT', t)
        self.assertIn("HQ '0' / node '1'=1", t)
        self.assertIn('03HD1 (changed last: HQ)', t)
        self.assertIn('HQ codes created at 150 missing on the node 1', t)
        self.assertIn('balance: different=1', t)
        self.assertIn('06HD3 HQ 10 / node 20', t)
        self.assertIn('changed AFTER their last ship (a change that cannot have replicated): 1', t)
        self.assertIn('never shipped (NULL)=1', t)
        self.assertIn('lcpointstrans: 1 rows', t)
        self.assertIn('none readable', t)
