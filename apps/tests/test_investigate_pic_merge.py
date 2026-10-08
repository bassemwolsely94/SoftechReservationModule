"""B7 probe (investigate_pic_merge) — read-only; SOFTECH replaced by a fake connection."""
import datetime as dt
import io
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.customers.models import Customer, PurchaseHistory

SCHEMA = [('phcode', 'varchar', 13), ('mobileno', 'varchar', 20), ('branchcustphone', 'varchar', 20),
          ('phcodestatus', 'varchar', 1), ('piclock', 'tinyint', 1)]
# phcode, mobile, status, lock, pphcode
LC = [('P1', '01001234567', '1', 0, ''), ('P2', '+201001234567', '0', 0, 'P1'),      # P2 deactivated twin of P1
      ('P3', '01112223334', '1', 0, ''), ('P4', '01112223334', '1', 0, ''),          # family sharing a phone
      ] + [(f'J{i}', '01000000000', '1', 0, '') for i in range(12)]                  # placeholder number
NAMES = {'P1': ('أحمد محمد علي', 'شارع النزهة 5'), 'P2': ('احمد محمد على', 'شارع النزهه 5'),
         'P3': ('سارة محمود', ''), 'P4': ('محمود حسن', '')}


class Cur:
    def execute(self, sql, p=None):
        s, self.r, self.description = ' '.join(sql.split()), [], [('a',)]
        if 'SET ROWCOUNT' in s:
            return
        if 'syscolumns c, ' in s and 'systypes' in s:
            self.r = SCHEMA if p and p[0] == 'localcustomers' else []
        elif s.startswith('SELECT phcode, mobileno, branchcustphone'):
            self.r = [(r[0], r[1], '', *NAMES.get(r[0], ('', '')), r[2]) for r in LC]
        elif "<> '1' OR piclock = 1" in s:
            cols = s.split('SELECT ')[1].split(' FROM')[0].split(', ')
            self.description = [(c,) for c in cols]
            rows = [r for r in LC if r[2] != '1' or r[3] == 1]
            self.r = [tuple({'phcode': r[0], 'phcodestatus': r[2], 'piclock': r[3], 'pphcode': r[4]}.get(c)
                            for c in cols) for r in rows]
        elif s.startswith('SELECT phcode, phcodestatus, piclock') and 'IN (' in s:
            self.r = [(r[0], r[2], r[3]) for r in LC if r[0] in p]
        elif "pphcode, '') <> '' AND l.pphcode" in s:
            self.r = [(1,)]
        elif "pphcode, '') <> '' AND pphcode <> phcode" in s and s.startswith('SELECT count'):
            self.r = [(1,)]
        elif "pphcode, '') <> ''" in s and s.startswith('SELECT count'):
            self.r = [(1,)]
        elif s.startswith('SELECT phcode, pphcode, relativecode'):
            self.r = [('P2', 'P1', 2)]

    def fetchall(self):
        return self.r


class Conn:
    def cursor(self):
        return Cur()

    def close(self):
        pass


class SuggestTests(TestCase):
    def test_lists_deactivated_codes_and_suggests_the_twin(self):
        from apps.tests.factories import make_branch
        c = Customer.objects.create(name='x', phone='01001234567', softech_pic='P1')
        PurchaseHistory.objects.create(customer=c, branch=make_branch('A', '130'), total_amount=10, softech_invoice_id='130-115-1-20261001', doc_code='115',
                                       softech_phcode='P1', invoice_date=timezone.now() - dt.timedelta(days=3))
        out = io.StringIO()
        with mock.patch('config.sybase.get_sybase_connection', return_value=Conn()):
            call_command('investigate_pic_merge', suggest=True, out='', stdout=out)
        text = out.getvalue()
        self.assertIn('placeholder / junk numbers excluded: 1 numbers · 12 PICs', text)
        self.assertIn('REAL shared numbers: 2 numbers · 4 PICs', text)
        self.assertIn("P2: status='0'", text)
        self.assertIn('shares a phone with P1', text)
        self.assertIn('SUGGESTED PAIR to review in SOFTECH: P2 (not active) ↔ P1 (active, same phone)', text)
        self.assertIn('P2 → pphcode P1 (relativecode 2)', text)
        self.assertIn('same name + same address: 1 pairs   e.g. P1 ↔ P2', text)    # Arabic variants normalised
        self.assertIn('different names (family / shared phone?): 1 pairs', text)
        self.assertNotIn('أحمد', text)                                               # names never printed
        self.assertNotIn('01001234567', text)                   # phones masked
