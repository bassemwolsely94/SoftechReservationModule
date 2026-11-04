"""Opening entry from the 31-12-2025 trial balance (finance-gl Task 5)."""
import datetime
import os
import tempfile
from decimal import Decimal
from io import StringIO
from unittest import mock

import openpyxl
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.finance.gl.coa_import import import_coa, parse_trial_balance_sheet
from apps.finance.gl.ledger import LedgerError
from apps.finance.gl.opening import build_opening_lines, post_opening
from apps.finance.models import GLAccount, LedgerEntry
from apps.tests.test_gl_coa_import import HEADER_2026, _sheet
from apps.users.models import StaffProfile

CLOSING = Decimal('500.00')
# assets 100+300 | liabilities 50 | equity capital 200 | 2409 retained 20
# sales 1000 cr | purchases 600 dr | opening stock 5301 100 dr | expenses 250 dr
# P&L net S = 600 + 100 + 250 - 1000 = -50 ; BS net = 400-50-200-20 = 130 ... balanced below
BLOCKS = [
    ('النقديه بالصندوق', [(1301, 'خزينة', 100, 0)]),
    ('المقبوضات التجاريه', [(1341, 'عملاء', 300, 0)]),
    ('المدفوعات التجاريه', [(2341, 'الموردين', 0, 50)]),
    ('حقوق الملكيه', [(2400, 'رأس المال', 0, 200), (2409, 'ارباح محتجزة', 0, 20)]),
    ('المبيعات', [(6001, 'مبيعات', 0, 1000)]),
    ('تكلفة المبيعات', [(5001, 'مشتريات', 600, 0)]),
    ('محزون أول المده', [(5301, 'مخزون اول المدة', 100, 0)]),
    ('المصروفات العموميه', [(7001, 'مرتبات', 250, 0)]),
]
# BS net = 100+300-50-200-20 = 130 ; P&L net S = 600+100+250-1000 = -50 ; sum = 80 != 0
# add a balancing equity account so the TB sums to zero
BLOCKS[3] = ('حقوق الملكيه', [(2400, 'رأس المال', 0, 280), (2409, 'ارباح محتجزة', 0, 20)])
# BS net = 100+300-50-280-20 = 50 ; S = -50 -> total 0


class OpeningTests(TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, 'tb.xlsx')
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '2026'
        _sheet(ws, HEADER_2026, BLOCKS)
        wb.save(self.path)
        user = User.objects.create_user(username='open_u', password='x')
        self.staff, _ = StaffProfile.objects.get_or_create(user=user)
        self.rows = parse_trial_balance_sheet(self.path)
        import_coa(self.rows, user=self.staff)

    def _by_code(self, lines):
        return {ln['account_code']: ln for ln in lines}

    def test_bs_accounts_carried_pl_accounts_closed_to_2409(self):
        lines = self._by_code(build_opening_lines(self.rows, CLOSING))
        self.assertEqual(lines['1301']['debit'], Decimal('100.00'))
        self.assertEqual(lines['2341']['credit'], Decimal('50.00'))
        self.assertEqual(lines['2400']['credit'], Decimal('280.00'))
        for code in ('6001', '5001', '7001'):
            self.assertNotIn(code, lines)

    def test_profit_equals_closing_stock_minus_pl_net(self):
        # S = -50 (trading+P&L net); merged 2409 = carried -20 + (S - closing) = -570 (credit 570)
        amounts = [ln for ln in build_opening_lines(self.rows, CLOSING)
                   if ln['account_code'] == '2409']
        self.assertEqual(len(amounts), 1)
        self.assertEqual(amounts[0]['credit'], Decimal('570.00'))
        self.assertEqual(amounts[0]['debit'], Decimal('0.00'))
        self.assertIn('مرحل -20.00', amounts[0]['description'])
        self.assertIn('نتيجة السنة -550.00', amounts[0]['description'])

    def test_opening_stock_on_5301(self):
        lines = build_opening_lines(self.rows, CLOSING)
        stock = [ln for ln in lines if ln['account_code'] == '5301']
        self.assertEqual(len(stock), 1)
        self.assertEqual(stock[0]['debit'], CLOSING)
        self.assertEqual(stock[0]['credit'], Decimal('0'))

    def test_entry_balances_and_is_approved_dated_2026_01_01(self):
        entry = post_opening(self.path, closing_stock=CLOSING, user=self.staff)
        entry.refresh_from_db()
        self.assertEqual(entry.status, 'approved')
        self.assertEqual(entry.entry_date, datetime.date(2026, 1, 1))
        self.assertEqual((entry.book, entry.source_type, entry.source_key),
                         ('opening', 'opening', 'opening:2026'))
        d = sum(ln.debit for ln in entry.lines.all())
        c = sum(ln.credit for ln in entry.lines.all())
        self.assertEqual(d, c)

    def test_second_import_refused(self):
        post_opening(self.path, closing_stock=CLOSING, user=self.staff)
        with self.assertRaises(LedgerError) as cm:
            post_opening(self.path, closing_stock=CLOSING, user=self.staff)
        self.assertEqual(cm.exception.code, 'source_conflict')
        self.assertEqual(LedgerEntry.objects.filter(source_key='opening:2026').count(), 1)

    def test_missing_coa_accounts_listed(self):
        GLAccount.objects.filter(code__in=['1301', '7001']).delete()
        with self.assertRaises(LedgerError) as cm:
            post_opening(self.path, closing_stock=CLOSING, user=self.staff)
        self.assertEqual(cm.exception.code, 'missing_accounts')
        self.assertEqual(cm.exception.detail['codes'], ['1301', '7001'])

    def test_failed_approve_leaves_no_draft_and_retry_works(self):
        with mock.patch('apps.finance.gl.opening.approve', side_effect=LedgerError('empty')):
            with self.assertRaises(LedgerError):
                post_opening(self.path, closing_stock=CLOSING, user=self.staff)
        self.assertFalse(LedgerEntry.objects.filter(source_key='opening:2026').exists())
        entry = post_opening(self.path, closing_stock=CLOSING, user=self.staff)
        self.assertEqual(entry.status, 'approved')

    def test_closing_stock_validated(self):
        for bad in ('0', '-5', '1.234', 'NaN', 'Infinity', 'abc'):
            with self.assertRaises(LedgerError, msg=bad) as cm:
                build_opening_lines(self.rows, bad)
            self.assertEqual(cm.exception.code, 'bad_amount')
        with self.assertRaises(CommandError):
            call_command('import_gl_opening', self.path, '--closing-stock', '1.234',
                         '--user', 'open_u', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('import_gl_opening', self.path, '--closing-stock', 'NaN',
                         '--user', 'open_u', stdout=StringIO())

    def test_unbalanced_tb_refused(self):
        rows = list(self.rows)
        rows[0] = rows[0].__class__(rows[0].group, rows[0].code, rows[0].name,
                                    Decimal('101'), Decimal('0'), Decimal('101'))
        with self.assertRaises(LedgerError) as cm:
            build_opening_lines(rows, CLOSING)
        self.assertEqual(cm.exception.code, 'unbalanced')

    def test_command_dry_run_and_user_required(self):
        out = StringIO()
        call_command('import_gl_opening', self.path, '--closing-stock', '500',
                     '--user', 'open_u', '--dry-run', stdout=out)
        self.assertFalse(LedgerEntry.objects.filter(source_key='opening:2026').exists())
        self.assertIn('debit', out.getvalue().lower())
        with self.assertRaises(CommandError):
            call_command('import_gl_opening', self.path, '--closing-stock', '500',
                         '--user', 'nobody', stdout=StringIO())
        call_command('import_gl_opening', self.path, '--closing-stock', '500',
                     '--user', 'open_u', stdout=StringIO())
        self.assertTrue(LedgerEntry.objects.filter(source_key='opening:2026').exists())
