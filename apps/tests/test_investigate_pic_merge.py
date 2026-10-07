"""B7 probe (investigate_pic_merge) — read-only; SOFTECH replaced by a fake connection."""
import datetime as dt
import io
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from apps.customers.models import Customer

SCHEMA = [('phcode', 'varchar', 13), ('mobileno', 'varchar', 20), ('branchcustphone', 'varchar', 20),
          ('custstop', 'char', 1), ('ischronic', 'char', 1), ('picpoints', 'int', 4)]
LC = [  # phcode, mobileno, branchcustphone, custstop, ischronic, picpoints
    ('P1', '01001234567', '', '0', '1', 1), ('P2', '+201001234567', '', '1', '1', 0),     # pair 1: P2 stopped
    ('P3', '01112223334', '', '0', '0', 1), ('P4', '01112223334', '', '1', '0', 1),       # pair 2: P4 stopped
    ('P5', '01223334445', '', '0', '0', 1),
]


class Cur:
    description = None

    def execute(self, sql, p=None):
        s, self.r, self.description = ' '.join(sql.split()), [], [('a',)]
        if 'SET ROWCOUNT' in s:
            return
        if 'syscolumns c, ' in s and 'systypes' in s:
            self.r = SCHEMA if p and p[0] == 'localcustomers' else []
        elif s.startswith('SELECT phcode, mobileno, branchcustphone'):
            self.r = [(r[0], r[1], r[2]) for r in LC]
        elif s.startswith('SELECT phcode, ') and 'WHERE phcode IN' in s:
            cols = s.split('SELECT phcode, ')[1].split(' FROM')[0].split(', ')
            idx = {c: i for i, (c, _, _) in enumerate(SCHEMA)}
            self.description = [('phcode',)] + [(c,) for c in cols]
            self.r = [tuple([r[0]] + [r[idx[c]] for c in cols]) for r in LC if r[0] in p]

    def fetchall(self):
        return self.r


class Conn:
    def cursor(self):
        return Cur()

    def close(self):
        pass


class SuggestTests(TestCase):
    def test_finds_the_flag_column_and_dormant_pairs(self):
        today = dt.date.today()
        for pic, days in (('P1', 10), ('P2', 800), ('P3', 20), ('P4', None)):
            Customer.objects.create(name='x', phone=f'0100000{pic[1]}', softech_pic=pic,
                                    last_visit_date=(today - dt.timedelta(days=days)) if days else None)
        out = io.StringIO()
        with mock.patch('config.sybase.get_sybase_connection', return_value=Conn()):
            call_command('investigate_pic_merge', suggest=True, out='', stdout=out)
        text = out.getvalue()
        self.assertIn("localcustomers.custstop: '1' vs '0' → 2", text)
        self.assertIn('ODD P2', text)
        self.assertIn('ODD P4', text)
        self.assertIn('dormant P2', text)                       # P2 > 1 year, P1 active
        self.assertNotIn('01001234567', text)                   # phones masked
