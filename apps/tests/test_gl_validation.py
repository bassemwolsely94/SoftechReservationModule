"""Jan–Aug 2026 validation against finance's workbook (finance-gl Plan 3, Task 9).

Synthetic workbooks in the layout of finance's pivots: trailing-space sheet names, header on row 3,
the group only on its first row, `Total` / `Grand Total` rows, integer month headers. No finance data.
"""
import contextlib
import datetime
import io
import os
import shutil
import tempfile
from decimal import Decimal

import openpyxl
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import TestCase

from apps.branches.models import Branch
from apps.finance.gl import validation as val
from apps.finance.gl.ledger import approve, save_draft
from apps.finance.models import GLAccount, GLAccountGroup, GLParty
from apps.users.models import StaffProfile

D = datetime.date
NAMES = {'130': 'صيدلية د علياء النزهة2', '140': 'صيدلية د بليغ الجيزة'}   # finance's names (default aliases)
GROUP = 'Sub account name'


def _pivot(ws, header, rows):
    """Title rows 1-2, header on row 3; `rows` are (group, code, name, *values)."""
    ws.append(['تقرير'])
    ws.append([])
    ws.append(header)
    last = None
    for group, code, name, *values in rows:
        if group != last and last is not None:
            ws.append([f'{last} Total'])
        ws.append([group if group != last else None, code, name, *values])
        last = group
    if last is not None:
        ws.append([f'{last} Total'])
    ws.append(['Grand Total'])


class ValidationBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username='gl_val_u', password='x')
        cls.staff, _ = StaffProfile.objects.get_or_create(user=cls.user)
        cls.user2 = User.objects.create_user(username='gl_val_u2', password='x')
        cls.staff2, _ = StaffProfile.objects.get_or_create(user=cls.user2)
        g = GLAccountGroup.objects.create(name='مجموعة', section='balance_sheet', order=1)
        mk = GLAccount.objects.create
        cls.cash = mk(code='1101', name='الخزينة', group=g, nature='debit', account_type='asset')
        cls.sales = mk(code='6002', name='المبيعات', group=g, nature='credit', account_type='revenue')
        cls.supplier = mk(code='2341', name='الموردون', group=g, nature='credit', account_type='liability',
                          party_type='supplier', requires_party=True)
        cls.b130 = Branch.objects.create(softech_branch_id='130', name='فرع النزهة')
        cls.b140 = Branch.objects.create(softech_branch_id='140', name='فرع الجيزة')
        GLParty.objects.create(party_type='supplier', code='501', name='مورد أول', status='confirmed')

    def entry(self, day, amount, branch=None, credit='6002', debit='1101', party='', approved=True):
        bid = branch.pk if branch else None
        e = save_draft(user=self.staff, entry_date=day, description='اختبار', lines=[
            {'account_code': debit, 'debit': Decimal(amount), 'credit': Decimal('0'), 'branch_id': bid},
            {'account_code': credit, 'debit': Decimal('0'), 'credit': Decimal(amount), 'branch_id': bid,
             'party_code': party}])
        if approved:
            approve(e.id, user=self.staff2)
        return e

    def workbook(self, ytd=(), monthly=(), parties=None, branch_names=None, sheet_suffix=' '):
        """Sheet names get finance's trailing space."""
        wb = openpyxl.Workbook()
        names = branch_names or [NAMES['130'], NAMES['140']]
        ws = wb.active
        ws.title = 'ميزان الفروع' + sheet_suffix
        _pivot(ws, [GROUP, 'رقم العملية', 'Trans. Name', *names, 'Grand Total'],
               [(g, c, n, *v, sum(x or 0 for x in v)) for g, c, n, *v in ytd])
        ws = wb.create_sheet('ميزان المراجعة' + sheet_suffix)
        _pivot(ws, [GROUP, 'رقم العملية', 'Trans. Name', 'Debt', 'Credit', 'Grand Total'], [])
        ws = wb.create_sheet('المشتريات والمبيعات' + sheet_suffix)
        months = list(range(1, 9))
        _pivot(ws, [GROUP, 'رقم العملية', 'Trans. Name', *months, 'Grand Total', 'المتوسط الشهرى'],
               [(g, c, n, *[v.get(m) for m in months], sum(v.values()), 0) for g, c, n, v in monthly])
        for sheet, (_kind, _acc, _pt, label) in val.PARTY_SHEETS.items():
            rows = (parties or {}).get(sheet, [])
            if not rows and sheet not in (parties or {}):
                continue
            ws = wb.create_sheet(sheet + sheet_suffix)
            ws.append(['تقرير'])
            ws.append([])
            ws.append([label, 'name', 'Credit', 'Debt', 'Grand Total'])
            for code, name, bal in rows:
                ws.append([code, name, min(bal, 0) or None, max(bal, 0) or None, bal])
            ws.append(['Grand Total', None, None, None, sum(r[2] for r in rows)])
        d = tempfile.mkdtemp(prefix='gl_val_')
        self.addCleanup(shutil.rmtree, d, True)
        path = os.path.join(d, 'workbook.xlsx')
        wb.save(path)
        return path

    def standard(self):
        self.entry(D(2026, 3, 10), '100.00', self.b130)
        self.entry(D(2026, 4, 5), '50.00', self.b140)
        return dict(ytd=[('الأصول', 1101, 'الخزينة', 100, 50), ('الإيرادات', 6002, 'المبيعات', -100, -50)],
                    monthly=[('الإيرادات', 6002, 'المبيعات', {3: -100, 4: -50})])


class ParserTests(ValidationBase):
    def test_branch_tb_parsed_per_branch(self):
        rows = val.parse_branch_trial_balance(self.workbook(ytd=[
            ('الأصول', 1101, 'الخزينة', 100, None), ('الإيرادات', 6002, 'المبيعات', -100, -50.5)]))
        got = {(r.code, r.branch_label): r.balance for r in rows}
        self.assertEqual(got, {('1101', NAMES['130']): Decimal('100.00'), ('6002', NAMES['130']): Decimal('-100.00'),
                               ('6002', NAMES['140']): Decimal('-50.50')})   # Total rows and group labels skipped

    def test_finance_branch_names_resolve_via_default_aliases(self):
        idx = val._branch_index()
        self.assertEqual(val.resolve_branch(NAMES['130'], _index=idx), self.b130)
        self.assertEqual(val.resolve_branch('صيدلية  د بليغ الجيزة', _index=idx), self.b140)
        self.assertIsNone(val.resolve_branch('فرع مجهول', _index=idx))

    def test_monthly_sheet_parsed(self):
        rows = val.parse_monthly_sheet(self.workbook(monthly=[('الإيرادات', 6002, 'المبيعات', {3: -100, 8: -5})]))
        self.assertEqual({(r.code, r.month): r.amount for r in rows},
                         {('6002', 3): Decimal('-100.00'), ('6002', 8): Decimal('-5.00')})

    def test_party_sheets_parsed(self):
        path = self.workbook(parties={'الموردين': [(501, 'مورد أول', -70)], 'العملاء': [(9, 'عميل', 20)]})
        sup = val.parse_party_sheet(path, 'الموردين')
        self.assertEqual([(r.party_code, r.name, r.balance) for r in sup], [('501', 'مورد أول', Decimal('-70.00'))])
        self.assertEqual(val.parse_party_sheet(path, 'العملاء')[0].balance, Decimal('20.00'))

    def test_xls_gets_a_clear_message(self):
        with self.assertRaises(val.WorkbookError) as cm:
            val.parse_branch_trial_balance('finance.xls')
        self.assertIn('xlsx', cm.exception.message)


class ValidateTests(ValidationBase):
    def test_matching_ledger_has_no_differences(self):
        res = val.validate(self.workbook(**self.standard()))
        self.assertEqual((res['ytd'], res['monthly'], res['parties']), ([], [], []))
        self.assertEqual(res['totals']['differences'], 0)
        self.assertEqual((res['unmapped_branches'], res['unknown_accounts']), ([], []))

    def test_only_differences_listed_with_account_totals(self):
        std = self.standard()
        std['ytd'][1] = ('الإيرادات', 6002, 'المبيعات', -100, -60)          # branch 140 differs by 10
        std['monthly'] = [('الإيرادات', 6002, 'المبيعات', {3: -100, 4: -60})]
        res = val.validate(self.workbook(**std))
        self.assertEqual([(r['code'], r['branch'], r['difference']) for r in res['ytd']],
                         [('6002', '140 · فرع الجيزة', Decimal('10.00'))])
        self.assertEqual([(r['code'], r['month'], r['difference']) for r in res['monthly']],
                         [('6002', 4, Decimal('10.00'))])
        total = res['totals']['ytd'][0]
        self.assertEqual((total['code'], total['ledger'], total['workbook'], total['difference']),
                         ('6002', Decimal('-150.00'), Decimal('-160.00'), Decimal('10.00')))
        self.assertEqual(res['totals']['differences'], 2)

    def test_unmapped_branch_reported(self):
        std = self.standard()
        std['ytd'] = [('الأصول', 1101, 'الخزينة', 100, 50, 7)]
        res = val.validate(self.workbook(**std, branch_names=[NAMES['130'], NAMES['140'], 'فرع غير معروف']))
        self.assertEqual(res['unmapped_branches'], ['فرع غير معروف'])
        total = next(t for t in res['totals']['ytd'] if t['code'] == '1101')   # no branch row differs, the total does
        self.assertEqual((total['workbook'], total['difference']), (Decimal('157.00'), Decimal('-7.00')))

    def test_unknown_account_reported(self):
        std = self.standard()
        std['ytd'].append(('أخرى', 9999, 'غير موجود', 5, None))
        res = val.validate(self.workbook(**std))
        self.assertEqual(res['unknown_accounts'], ['9999'])
        self.assertEqual([r['code'] for r in res['ytd']], ['9999'])

    def test_drafts_ignored(self):
        std = self.standard()
        self.entry(D(2026, 3, 11), '20.00', self.b130, approved=False)
        self.assertEqual(val.validate(self.workbook(**std))['totals']['differences'], 0)

    def test_entries_after_through_date_ignored(self):
        std = self.standard()
        self.entry(D(2026, 9, 1), '20.00', self.b130)
        self.assertEqual(val.validate(self.workbook(**std))['totals']['differences'], 0)
        self.assertEqual(len(val.validate(self.workbook(**std), through=D(2026, 9, 30))['ytd']), 2)

    def test_parties_compared_per_kind(self):
        std = self.standard()
        self.entry(D(2026, 5, 2), '70.00', self.b130, debit='1101', credit='2341', party='501')
        std['ytd'] += [('الخصوم', 2341, 'الموردون', -70, None)]
        std['ytd'][0] = ('الأصول', 1101, 'الخزينة', 170, 50)
        std['parties'] = {'الموردين': [(501, 'مورد أول', -70), (502, 'مورد ثان', -30)]}
        res = val.validate(self.workbook(**std))
        self.assertEqual([(r['kind'], r['party_code'], r['difference']) for r in res['parties']],
                         [('suppliers', '502', Decimal('30.00'))])
        self.assertEqual([p['party_code'] for p in res['unmapped_parties']], ['502'])
        self.assertEqual(res['missing_sheets'], ['الدائنون', 'العملاء', 'مدينون'])
        sup = next(t for t in res['totals']['parties'] if t['kind'] == 'suppliers')
        self.assertEqual((sup['ledger'], sup['workbook']), (Decimal('-70.00'), Decimal('-100.00')))

    def test_export_has_explanation_column(self):
        std = self.standard()
        std['ytd'][1] = ('الإيرادات', 6002, 'المبيعات', -100, -60)
        res = val.validate(self.workbook(**std))
        wb = openpyxl.load_workbook(io.BytesIO(val.export_validation(res)))
        self.assertEqual(wb.sheetnames[:2], ['حسب الفرع', 'شهري'])
        ws = wb['حسب الفرع']
        self.assertTrue(ws.sheet_view.rightToLeft)
        self.assertEqual(ws.cell(1, 7).value, 'التفسير')
        self.assertEqual([ws.cell(2, 7).value, ws.cell(3, 7).value], [None, None])   # empty for finance to fill
        self.assertEqual(ws.cell(3, 3).value, 'الإجمالى')
        self.assertEqual(ws.cell(2, 6).number_format, '#,##0.00')


class CommandTests(ValidationBase):
    def run_cmd(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            call_command('gl_validate_workbook', *args, stdout=out)
        return out.getvalue()

    def test_clean_run_and_report_file(self):
        path = self.workbook(**self.standard())
        out_path = os.path.join(os.path.dirname(path), 'report.xlsx')
        self.assertIn('differences=0', self.run_cmd(path, '--out', out_path))
        self.assertTrue(os.path.exists(out_path))

    def test_differences_exit_with_error(self):
        std = self.standard()
        std['ytd'][0] = ('الأصول', 1101, 'الخزينة', 100, 40)
        with self.assertRaises(CommandError):
            self.run_cmd(self.workbook(**std))

    def test_xls_refused_with_arabic_message(self):
        with self.assertRaises(CommandError) as cm:
            self.run_cmd('finance.xls')
        self.assertIn('xlsx', str(cm.exception))
