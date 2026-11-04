"""Chart-of-accounts importer from finance's trial-balance pivot (finance-gl Task 4)."""
import os
import tempfile
from decimal import Decimal

import openpyxl
from django.contrib.auth.models import User
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.finance.gl.coa_import import (
    TBRow, import_coa, parse_trial_balance_sheet, parse_trial_balance_sheet_with_warnings,
)
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


def _row(group, code, name='n'):
    return TBRow(group, code, name, Decimal(1), Decimal(0), Decimal(1))


class CoaImportMappingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='coa_m', password='x')
        self.staff, _ = StaffProfile.objects.get_or_create(user=self.user)

    def test_group_default_lines(self):
        import_coa([
            _row('شركات شقيقة', '2501'), _row('الضرائب', '2601'),
            _row('المقبوضات غير التجاريه', '1399'), _row('التحويلات', '1310'),
            _row('جارى الشركاء', '2411'), _row('محزون أول المده', '5301'),
        ], user=self.staff)
        line = lambda c: GLAccount.objects.get(code=c).statement_line
        self.assertEqual(line('2501'), 'creditors')
        self.assertEqual(line('2601'), 'creditors')
        self.assertEqual(line('1399'), 'other_debtors')
        self.assertEqual(line('1310'), 'cash')
        self.assertEqual(line('2411'), 'partners')
        self.assertEqual(line('5301'), 'opening_stock')
        self.assertEqual(GLAccount.objects.get(code='2411').party_type, 'partner')

    def test_closing_stock_not_in_cogs_group(self):
        import_coa([_row('تكلفة المبيعات', '5101')], user=self.staff)
        self.assertEqual(GLAccount.objects.get(code='5101').group.name, 'تكلفة المبيعات')
        self.assertNotEqual(GLAccount.objects.get(code='5302').group.name, 'تكلفة المبيعات')

    def test_contra_revenue_by_code_any_group(self):
        import_coa([_row('المبيعات', '6018'), _row('ايرادات', '6019')], user=self.staff)
        for c in ('6018', '6019'):
            a = GLAccount.objects.get(code=c)
            self.assertEqual((a.account_type, a.nature), ('contra_revenue', 'debit'))

    def test_audit_on_real_import_not_dry_run(self):
        import_coa([_row('المبيعات', '6001')], user=self.staff, dry_run=True)
        self.assertFalse(AuditLog.objects.filter(action='gl_coa_imported').exists())
        import_coa([_row('المبيعات', '6001')], user=self.staff)
        log = AuditLog.objects.get(action='gl_coa_imported')
        self.assertEqual(log.extra['created'], 3)
        self.assertIsNone(log.old_data['6001'])
        self.assertEqual(log.new_data['6001']['statement_line'], 'net_sales')

    def test_reimport_audits_per_account_diff_and_counts_real_changes(self):
        import_coa([_row('المبيعات', '6001', 'مبيعات'), _row('المبيعات', '6002', 'مرتجع')],
                   user=self.staff)
        AuditLog.objects.filter(action='gl_coa_imported').delete()
        res = import_coa([_row('المبيعات', '6001', 'مبيعات نقدية'), _row('المبيعات', '6002', 'مرتجع')],
                         user=self.staff)
        self.assertEqual((res.created, res.updated), (0, 1))     # 6002 unchanged → not counted
        log = AuditLog.objects.get(action='gl_coa_imported')
        self.assertEqual(log.old_data, {'6001': {'name': 'مبيعات'}})
        self.assertEqual(log.new_data, {'6001': {'name': 'مبيعات نقدية'}})
        self.assertEqual(log.extra['updated'], 1)

    def test_import_rolls_back_when_audit_fails(self):
        from unittest import mock
        with mock.patch('apps.audit.models.AuditLog.save', side_effect=RuntimeError('audit down')):
            with self.assertRaises(RuntimeError):
                import_coa([_row('المبيعات', '6001')], user=self.staff)
        self.assertFalse(GLAccount.objects.filter(code='6001').exists())

    def test_reimport_keeps_existing_system_account(self):
        import_coa([], user=self.staff)
        acc = GLAccount.objects.get(code='1390')
        acc.name = 'بضاعة (معدل)'
        acc.save()
        import_coa([_row('اصول ثابته', '1390', 'x')], user=self.staff)
        acc.refresh_from_db()
        self.assertEqual((acc.name, acc.group.name), ('بضاعة (معدل)', 'بضاعة آخر المدة'))

    def test_unparseable_amount_warns(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = os.path.join(d.name, 'w.xlsx')
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(HEADER_2026)
        ws.append(['اصول ثابته', 1101, 'x', 'abc', 0, 0])
        wb.save(path)
        rows, warnings = parse_trial_balance_sheet_with_warnings(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(len(parse_trial_balance_sheet(path)), 1)
