"""B7 replication probe (investigate_pic_replication) — read-only; HQ and a node replaced by fake connections."""
import datetime as dt
import io
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

D = dt.datetime
# phcode, status, lock, branch, trans_time, table_dumped, status_time, pphcode, picpoints flag, died
HQ = [('03HD1', '0', 0, '130', D(2025, 1, 2), D(2024, 6, 1), D(2025, 1, 2), '03HD1', 1, 0),   # deactivated after last ship
      ('06HD2', '1', 0, '150', D(2024, 1, 1), D(2024, 1, 1, 0, 5), None, '06HD2', 1, 0),
      ('06HD3', '1', 0, '150', D(2024, 1, 1), None, None, '06HD3', 1, 0),                       # never shipped
      ('150HD4', '1', 0, '150', D(2024, 1, 1), D(2024, 1, 2), None, '150HD4', 1, 0)]          # node lost it
NODE = [('03HD1', '1', 0, '130', D(2024, 6, 1), D(2024, 6, 1), None, '03HD1', 1, 0),           # still active here
        ('06HD2', '1', 0, '150', D(2024, 1, 1), D(2024, 1, 1, 0, 5), None, '06HD2', 1, 0),
        ('06HD3', '1', 0, '150', D(2024, 1, 1), None, None, '06HD3', 1, 0)]
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
        elif s.startswith('SELECT count(*), sum(case when table_dumped'):
            self.r = [(3, 3)]
        elif s.startswith('SELECT count(*), sum(case when points'):
            self.r = [(4, 30, 10, D(2026, 1, 1))] if self.node else [(2, 10, 0, D(2025, 1, 1))]
        elif 'GROUP BY doccode' in s:
            self.r = [('115', 3, 20)]
        elif s.startswith('SELECT phcode, usercode, trans_time, totpoints - conpointsold'):
            self.r = [('06HD3', '19', D(2024, 5, 14), 500)]
        elif "doccode = '30' AND transdate >" in s:
            self.r = [(2, -15, D(2026, 3, 1))]
        elif s.startswith('SELECT totpointsold'):
            self.r = [(0, 0, 400, 0, '150', '62', D(2026, 2, 2))] if self.node else []
        elif s.startswith('SELECT totpoints, conpoints FROM'):
            self.r = [(20, 0)] if self.node else [(10, 0)]
        elif 'localcustomers2' in s and s.startswith('SELECT count'):
            self.r = [(1 if self.node else 0, None)]
        elif s.startswith('SELECT phcode, sourcepic'):
            self.description = [('phcode',), ('sourcepic',), ('sourcepicpoints',)]
            self.r = [('06HD2', '06HD3', 10)] if self.node else []
        elif 'FROM SOFTECHDB9.dbo.picstrans' in s and s.startswith('SELECT count'):
            self.r = [(5, None)]
        elif s.startswith('SELECT phcode, phcode2'):
            self.description = [('phcode',), ('phcode2',)]
            self.r = [('06HD3', '06HD9')]
        elif 'lcpointstrans' in s and s.startswith('SELECT count'):
            self.r = [(7, None)]
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
        self.assertIn('most common (node − HQ): +10×1', t)
        self.assertIn('node higher than HQ: 1 codes (+10 points) · HQ higher than node: 0 codes (−0 points)', t)
        self.assertIn('HQ codes created at 150 missing on the node 1', t)
        self.assertIn('balance: different=1', t)
        self.assertIn('06HD3 HQ 10 / node 20', t)
        self.assertIn('changed AFTER their last ship (a change that cannot have replicated): 1', t)
        self.assertIn('never shipped (NULL)=1', t)
        self.assertIn('lcpointstrans: 7 rows', t)
        self.assertIn('none readable', t)

    def test_explain_reads_native_merge_and_points_on_both_sides(self):
        out = io.StringIO()
        with mock.patch('config.sybase.get_sybase_connection', return_value=Conn()), \
                mock.patch('config.sybase.get_branch_connection', return_value=Conn(node=True)):
            call_command('investigate_pic_replication', host=['10.0.0.1'], explain=True, out='', stdout=out)
        t = out.getvalue()
        self.assertIn('HQ: localcustomers2 (merge) 0', t)
        self.assertIn('10.0.0.1: localcustomers2 (merge) 1', t)
        self.assertIn("merge: {'phcode': '06HD2', 'sourcepic': '06HD3', 'sourcepicpoints': 10}", t)
        self.assertIn("code change: {'phcode': '06HD3', 'phcode2': '06HD9'}", t)
        self.assertIn('06HD3 (HQ 10 / node 20, created at 150)', t)
        self.assertIn('node: balance 20−0 · log 4 rows earned 30 used 10', t)
        self.assertIn('manual edits 0/0→400/0 at 150 by 62', t)
        self.assertIn('HQ  : balance 10−0 · log 2 rows earned 10 used 0', t)
        self.assertIn('1 customers reset at HQ (consumed set = earned) · by user: 19=1', t)
        self.assertIn('10.0.0.1: holds 1 reset customers · 1 still show a balance here (20 points; 1 of them still enrolled', t)
        self.assertIn('06HD3 on 10.0.0.1: balance 20 · reset 2024-05-14 00:00:00 by 19 (500 points)', t)
        self.assertIn('used at the till after the reset: 2 times, 15 points', t)
