"""Chart-of-accounts importer from finance's trial-balance pivot (finance-gl Task 4)."""
import os
import tempfile
from decimal import Decimal

import openpyxl
from django.contrib.auth.models import User
from django.test import TestCase

from apps.finance.gl.coa_import import import_coa, parse_trial_balance_sheet
from apps.finance.gl.names import normalize_ar
from apps.finance.models import GLAccount, GLAccountGroup
from apps.users.models import StaffProfile

HEADER_2025 = ['Sub account name', 'رقم العملية', 'Trans. Name', 'Credit', 'Debt', 'Grand Total']
HEADER_2026 = ['Sub account name', 'رقم العملية', 'Trans. Name', 'Debt', 'Credit', 'Grand Total']


def _sheet(ws, header, blocks):
    ws.append(['Sum of balanc', None, None, 'condition'])
    ws.append(header)
    credit_first = header[3] == 'Credit'
    grand = 0
    for group, accounts in blocks:
        first = True
        for code, name, debit, credit in accounts:
            pair = [-credit, debit] if credit_first else [debit, -credit]
            ws.append([group if first else None, code, name, *pair, debit - credit])
            first = False
            grand += debit - credit
        ws.append([f'{group} Total', None, None, None, None, sum(a[2] - a[3] for a in accounts)])
    ws.append(['Grand Total', None, None, None, None, grand])


class CoaImportTests(TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, 'tb.xlsx')
        wb = openpyxl.Workbook()
        ws25 = wb.active
        ws25.title = '2025'
        _sheet(ws25, HEADER_2025, [
            ('النقديه بالصندوق ', [(1301, 'خزينة رئيسية', 100, 0), (1304, 'عهدة', 5, 0)]),
            ('المقبوضات غير التجاريه', [(2367, 'سلف', 7, 0)]),
            ('المدفوعات التجاريه', [(2341, 'الموردين', 0, 50)]),
        ])
        ws26 = wb.create_sheet('2026')
        _sheet(ws26, HEADER_2026, [
            ('النقديه بالصندوق', [(1301, 'خزينة', 40, 0)]),
            ('المقبوضات التجاريه', [('1341', 'عملاء', 9, 0)]),
        ])
        wb.save(self.path)
        self.user = User.objects.create_user(username='coa_u', password='x')
        self.staff, _ = StaffProfile.objects.get_or_create(user=self.user)

    def _rows(self, sheet='2025'):
        return parse_trial_balance_sheet(self.path, sheet)

    def test_group_carried_down_and_totals_skipped(self):
        rows = self._rows()
        self.assertEqual([r.code for r in rows], ['1301', '1304', '2367', '2341'])
        self.assertEqual([r.group for r in rows],
                         ['النقديه بالصندوق', 'النقديه بالصندوق',
                          'المقبوضات غير التجاريه', 'المدفوعات التجاريه'])

    def test_column_order_detected_from_header(self):
        r25 = self._rows('2025')[-1]
        self.assertEqual((r25.debit, r25.credit, r25.balance),
                         (Decimal('0'), Decimal('50'), Decimal('-50')))
        r26 = self._rows('2026')[0]
        self.assertEqual((r26.debit, r26.credit, r26.balance),
                         (Decimal('40'), Decimal('0'), Decimal('40')))

    def test_spelling_variants_map_to_same_group(self):
        self.assertEqual(normalize_ar('  النقدية   بالصندوق '), normalize_ar('النقديه بالصندوق'))
        self.assertEqual(normalize_ar('مصروفات مدفوعـه مقدماً'), normalize_ar('مصروفات مدفوعه مقدما'))
        self.assertEqual(normalize_ar('أول إلى آخر ى'), 'اول الي اخر ي')
        res = import_coa(self._rows('2025'), user=self.staff)
        self.assertEqual(res.unknown_groups, [])
        self.assertEqual(GLAccountGroup.objects.filter(name__startswith='النقدي').count(), 1)

    def test_unknown_group_reported_not_created(self):
        from apps.finance.gl.coa_import import TBRow
        rows = [TBRow('مجموعة غريبة', '9999', 'x', Decimal(1), Decimal(0), Decimal(1))]
        res = import_coa(rows, user=self.staff)
        self.assertEqual(res.unknown_groups, ['مجموعة غريبة'])
        self.assertFalse(GLAccount.objects.filter(code='9999').exists())

    def test_reimport_updates_name_never_deletes(self):
        import_coa(self._rows('2025'), user=self.staff)
        acc = GLAccount.objects.get(code='1301')
        acc.requires_branch = True
        acc.is_active = False
        acc.save()
        res = import_coa(self._rows('2026'), user=self.staff)
        acc.refresh_from_db()
        self.assertEqual(acc.name, 'خزينة')
        self.assertTrue(acc.requires_branch)
        self.assertFalse(acc.is_active)
        self.assertTrue(GLAccount.objects.filter(code='2341').exists())
        self.assertEqual(res.created, 1)  # 1341 only
        self.assertEqual(res.updated, 1)

    def test_system_closing_stock_accounts_created(self):
        import_coa([], user=self.staff)
        a, b = GLAccount.objects.get(code='1390'), GLAccount.objects.get(code='5302')
        self.assertTrue(a.is_system and b.is_system)
        self.assertEqual((a.statement_line, a.group.name, a.group.section),
                         ('inventory', 'بضاعة آخر المدة', 'balance_sheet'))
        self.assertEqual((b.nature, b.account_type, b.group.name, b.group.section, b.statement_line),
                         ('credit', 'cogs', 'مخزون آخر المدة', 'trading', 'closing_stock'))

    def test_bs_line_overrides_applied(self):
        import_coa(self._rows('2025'), user=self.staff)
        line = lambda c: GLAccount.objects.get(code=c).statement_line
        self.assertEqual(line('1304'), 'other_debtors')
        self.assertEqual(line('2367'), 'other_debtors')
        self.assertEqual(line('2341'), 'suppliers')
        self.assertEqual(line('1301'), 'cash')
        self.assertEqual(GLAccount.objects.get(code='2341').party_type, 'supplier')
        self.assertFalse(GLAccount.objects.get(code='2341').requires_party)
        import_coa(self._rows('2026'), user=self.staff)
        self.assertEqual(GLAccount.objects.get(code='1341').party_type, 'customer')

    def test_dry_run_writes_nothing(self):
        res = import_coa(self._rows('2025'), user=self.staff, dry_run=True)
        self.assertEqual(res.created, 6)  # 4 rows + 2 system
        self.assertFalse(GLAccount.objects.exists())
        self.assertFalse(GLAccountGroup.objects.exists())
