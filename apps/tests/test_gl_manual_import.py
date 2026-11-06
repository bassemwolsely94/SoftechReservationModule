"""Importer for finance's manual-only journal entries (finance-gl Plan 3, Task 8).

Synthetic workbooks in the layout of finance's 2020 journals: header on row 2, filler text in ignored
columns, trailing spaces in labels, two «due date» columns. No finance data here.
"""
import contextlib
import datetime
import io
import json
import os
import shutil
import tempfile
from decimal import Decimal
from unittest import mock

import openpyxl
from django.core.management import CommandError, call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.finance.gl import drafting, manual_import as mi
from apps.finance.gl.ledger import approve, reverse, save_draft
from apps.finance.gl.plan2_adapter import open_exception_count
from apps.finance.models import (
    GLAccount, GLAccountGroup, GLDraftRun, GLSourceDoc, GLSourceMap, LedgerEntry, PostingRule,
    SourceException,
)
from apps.tests.factories import make_user

D = datetime.datetime(2026, 3, 10)
D2 = datetime.datetime(2026, 3, 11)
OLD = datetime.datetime(2025, 12, 31)
BRANCH = 'فرع الاختبار'
BASE = '/api/finance/gl/'

HEADER = ['رقم العملية ', 'Trans. Name', 'filler a', 'customer code', 'suppliar code ', 'كود الموظف',
          'discreption ', 'shift num.', 'مدين', 'credit ', 'balanc', 'condition', 'date ',
          'Payment cheque num.', 'due date', 'filler b', 'Received cheque num.', 'due date ',
          'رقم الفرع', 'اسم الفرع']
BOOK_COL = 'اليومية'


def row(account, debit=0, credit=0, desc='قيد', date=D, branch=BRANCH, **kw):
    r = {'رقم العملية': account, 'Trans. Name': f'اسم {account}', 'filler a': 'نص ثابت', 'filler b': 'نص ثابت',
         'discreption': desc, 'مدين': debit, 'credit': credit, 'date': date, 'اسم الفرع': branch}
    r.update(kw)
    return r


def _d(v):
    return Decimal(str(v))


class WorkbookMixin:
    def _tmp(self):
        d = tempfile.mkdtemp(prefix='gl_manual_')
        self.addCleanup(shutil.rmtree, d, True)
        return d

    def xlsx(self, rows, name='journal.xlsx', book='النقدى', drop=(), header=None, extra_sheets=True):
        """`book` None = no book column. `drop` = column labels the file doesn't have."""
        labels = [h for h in (header or HEADER) if h.strip() not in drop]
        if book is not None:
            labels = labels + [BOOK_COL]
        wb = openpyxl.Workbook()
        wb.active.title = 'مراجعة'
        wb.active.append(['ملخص', 'لا يوجد هنا عناوين اليومية'])
        ws = wb.create_sheet('اليومية الامريكية')
        ws.append(['دفتر اليومية'])
        ws.append(labels)
        for r in rows:
            values = {**r}
            values.setdefault(BOOK_COL, book)
            out, due = [], [values.get('due1'), values.get('due2')]
            for label in labels:
                key = label.strip()
                if key == 'due date':
                    out.append(due.pop(0))
                else:
                    out.append(values.get(key))
            ws.append(out)
        path = os.path.join(self._tmp(), name)
        wb.save(path)
        return path


class GLManualBase(WorkbookMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        _, cls.staff, _ = make_user('t8m_acct', role='accountant')
        cls.branch, _ = Branch.objects.update_or_create(
            softech_branch_id='B81', defaults={'name': BRANCH, 'name_ar': BRANCH})
        g = GLAccountGroup.objects.create(name='مجموعة يدوية', section='balance_sheet')
        mk = GLAccount.objects.create

        def acc(code, party='none', **kw):
            mk(code=code, name=f'حساب {code}', group=g, nature='debit', account_type='asset',
               party_type=party, **kw)
        for c in ('3280', '1296', '5105', '5106', '5121', '5122', '5101', '5102', '2354', '6002', '1302', '1301', '1999'):
            acc(c)
        acc('2341', party='supplier')
        acc('1341', party='customer')
        acc('1351', party='employee')
        acc('1000', is_posting=False)
        PostingRule.objects.create(
            code='t8.sales', source_type='sales_tenders', effective_from=datetime.date(2026, 1, 1),
            lines=[{'side': 'credit', 'account': '6002', 'amount': 'net'}])
        GLSourceMap.objects.create(kind='bank', source_value='40',
                                   account=GLAccount.objects.get(code='1302'))
        PostingRule.objects.create(   # an inactive rule feeds nothing
            code='t8.off', source_type='sales_tenders', effective_from=datetime.date(2026, 1, 1),
            is_active=False, lines=[{'side': 'debit', 'account': '1999', 'amount': 'net'}])

    def manual_rows(self, amount=100, desc='اهلاك الفترة', **kw):
        return [row('3280', debit=amount, desc=desc, **kw), row('1296', credit=amount, desc=desc, **kw)]

    def groups(self, rows, **kw):
        parsed = mi.parse_journal(self.xlsx(rows, **kw))
        return mi.group_entries(parsed.rows, parsed.rejected)

    def run_import(self, rows, include=(), **kw):
        return mi.import_entries(self.xlsx(rows, **kw), user=self.staff, include_mixed=list(include))

    def mixed_rows(self):
        return [row('1302', debit=50, desc='مختلط'), row('3280', credit=50, desc='مختلط')]


class ParseTests(GLManualBase):
    def test_header_found_by_labels_not_position(self):
        shifted = ['عمود زائد'] + list(reversed(HEADER))
        path = self.xlsx([row('3280', debit=10, shift=3)], header=shifted)
        parsed = mi.parse_journal(path)
        self.assertEqual(len(parsed.rows), 1)
        r = parsed.rows[0]
        self.assertEqual((r.account_code, r.side, r.amount, r.date, r.book),
                         ('3280', 'debit', _d('10.00'), D.date(), 'cash'))
        self.assertEqual(r.branch_name, BRANCH)

    def test_sheet_not_found_and_no_header_are_errors(self):
        path = self.xlsx([row('3280', debit=10)])
        with self.assertRaises(mi.ParseError) as c:
            mi.parse_journal(path, sheet_name='غير موجود')
        self.assertEqual(c.exception.code, 'sheet_not_found')
        with self.assertRaises(mi.ParseError) as c:
            mi.parse_journal(path, sheet_name='مراجعة')
        self.assertEqual(c.exception.code, 'header_not_found')

    def test_book_from_column_then_argument_then_filename_else_error(self):
        cash_col = self.xlsx([row('3280', debit=10)], book='النقدى')
        self.assertEqual(mi.parse_journal(cash_col, book='credit').rows[0].book, 'cash')   # column wins
        credit_col = self.xlsx([row('3280', debit=10)], book='الاجل')
        self.assertEqual(mi.parse_journal(credit_col).rows[0].book, 'credit')
        no_col = self.xlsx([row('3280', debit=10)], book=None, name='journal.xlsx')
        self.assertEqual(mi.parse_journal(no_col, book='credit').rows[0].book, 'credit')
        named = self.xlsx([row('3280', debit=10)], book=None, name='يوميات الآجل 2026.xlsx')
        self.assertEqual(mi.parse_journal(named).rows[0].book, 'credit')
        named = self.xlsx([row('3280', debit=10)], book=None, name='يومية النقدى 2026.xlsx')
        self.assertEqual(mi.parse_journal(named).book, 'cash')
        with self.assertRaises(mi.ParseError) as c:
            mi.parse_journal(no_col)
        self.assertEqual(c.exception.code, 'book_required')

    def test_condition_nothing_and_zero_rows_skipped_and_counted(self):
        parsed = mi.parse_journal(self.xlsx([
            row('3280', debit=10), row('3280', condition='Nothing'), row('1296', debit=0, credit=0),
            {},   # a blank row is no row at all
        ]))
        self.assertEqual(len(parsed.rows), 1)
        self.assertEqual(parsed.skipped_zero, 2)
        self.assertEqual(parsed.skipped, [])

    def test_nothing_row_with_an_amount_is_reported_not_counted_as_zero(self):
        parsed = mi.parse_journal(self.xlsx([row('3280', condition='Nothing', debit=5)]))
        self.assertEqual((parsed.rows, parsed.skipped_zero), ([], 0))
        self.assertEqual(parsed.skipped, [{'row': 3, 'reason': 'nothing_with_amount'}])
        parsed = mi.parse_journal(self.xlsx([row('3280', condition='Nothing', balanc=5)], drop=('مدين', 'credit')))
        self.assertEqual(parsed.skipped, [{'row': 3, 'reason': 'nothing_with_amount'}])
        gs = self.groups(self.manual_rows() + [row('3280', condition='Nothing', debit=1, desc='اهلاك الفترة')])
        self.assertEqual(gs[0].status, 'unbalanced')   # its group is short of that row

    def test_amount_from_condition_and_balance_when_columns_missing(self):
        parsed = mi.parse_journal(self.xlsx([
            row('3280', condition='Debt', balanc=-10.5), row('1296', condition='Credit', balanc=10.5),
            row('3280', condition='مدين', balanc=7), row('1296', condition='دائن', balanc=-7),
            row('1296', condition='غير معروف', balanc=7),
        ], drop=('مدين', 'credit')))
        self.assertEqual([(r.side, r.amount) for r in parsed.rows], [
            ('debit', _d('10.50')), ('credit', _d('10.50')), ('debit', _d('7.00')), ('credit', _d('7.00'))])
        self.assertEqual([s['reason'] for s in parsed.skipped], ['bad_condition'])

    def test_rows_without_date_or_account_reported_with_row_number(self):
        parsed = mi.parse_journal(self.xlsx([
            row('3280', debit=10), row('3280', debit=10, date=None), row(None, debit=10),
        ]))
        self.assertEqual(parsed.skipped, [{'row': 4, 'reason': 'no_date'}, {'row': 5, 'reason': 'no_account'}])

    def test_more_than_two_decimals_reported_float_artefact_taken(self):
        parsed = mi.parse_journal(self.xlsx([
            row('3280', debit=1234.5600000001),      # float noise within 1e-6: plainly 1234.56
            row('3280', debit=10.125),               # a real third decimal: reported, never rounded
            row('3280', debit='10.5600001'),         # text is exact: no float excuse
            row('3280', debit=-5),                   # negative: Plan 1 refuses it
            row('3280', debit='غلط'),
            row('3280', debit=5, credit=5),          # both sides
        ]))
        self.assertEqual([r.amount for r in parsed.rows], [_d('1234.56')])
        self.assertEqual([s['reason'] for s in parsed.skipped],
                         ['bad_amount', 'bad_amount', 'bad_amount', 'bad_amount', 'both_sides'])

    def test_second_due_date_belongs_to_received_cheque(self):
        d1, d2 = datetime.datetime(2026, 5, 1), datetime.datetime(2026, 6, 1)
        parsed = mi.parse_journal(self.xlsx([
            row('2341', credit=10, **{'Payment cheque num.': 'P1', 'due1': d1}),
            row('1341', debit=10, **{'Received cheque num.': 'R1', 'due2': d2}),
            row('1341', debit=10, **{'Payment cheque num.': 'P2', 'due1': d1, 'Received cheque num.': 'R2', 'due2': d2}),
            row('1341', debit=10, **{'due1': d1, 'Received cheque num.': 'R3', 'due2': d2}),   # a stray first date
            row('1341', debit=10, **{'due2': d2}),
        ]))
        self.assertEqual([(r.cheque_no, r.due_date) for r in parsed.rows],
                         [('P1', d1.date()), ('R1', d2.date()), ('P2', d1.date()), ('R3', d2.date()), ('', d2.date())])

    def test_party_or_cheque_code_too_long_is_reported_not_cut(self):
        long_code = 'x' * 41
        parsed = mi.parse_journal(self.xlsx([
            row('2341', credit=5, **{'suppliar code': long_code}),
            row('2341', credit=5, **{'Payment cheque num.': long_code}),
            row('2341', credit=5, **{'suppliar code': 'x' * 40}),
        ]))
        self.assertEqual(parsed.skipped, [{'row': 3, 'reason': 'party_too_long'},
                                          {'row': 4, 'reason': 'cheque_too_long'}])
        self.assertEqual(parsed.rows[0].supplier_code, 'x' * 40)

    def test_excel_number_codes_are_text(self):
        parsed = mi.parse_journal(self.xlsx([
            row(3280.0, debit=10, **{'رقم الفرع': 7.0, 'suppliar code': 55.0, 'customer code': 0, 'shift num.': 2.0})]))
        r = parsed.rows[0]
        self.assertEqual((r.account_code, r.branch_code, r.supplier_code, r.customer_code, r.shift),
                         ('3280', '7', '55', '', '2'))

    def test_row_cap_is_optional(self):
        path = self.xlsx([row('3280', debit=10), row('1296', credit=10)])
        self.assertEqual(len(mi.parse_journal(path).rows), 2)
        with self.assertRaises(mi.ParseError) as c:
            mi.parse_journal(path, max_rows=1)
        self.assertEqual(c.exception.code, 'too_many_rows')


class GroupingTests(GLManualBase):
    def test_groups_by_date_book_branch_description(self):
        gs = self.groups([
            row('3280', debit=10, desc='قيد ا'), row('1296', credit=10, desc='قيد أ '),   # normalize_ar
            row('3280', debit=20, desc='قيد ب'), row('1296', credit=20, desc='قيد ب'),
            row('3280', debit=30, desc='قيد ب', date=D2), row('1296', credit=30, desc='قيد ب', date=D2),
        ])
        self.assertEqual(len(gs), 3)
        self.assertTrue(all(g.balanced and g.status == 'manual' and not g.merged_by for g in gs))
        self.assertEqual(sorted(len(g.rows) for g in gs), [2, 2, 2])

    def test_returns_merge_by_date_branch_when_union_balances(self):
        gs = self.groups([
            row('5105', credit=60, desc='م تالف'), row('5121', credit=40, desc='جبر كسور'),
            row('2341', debit=100, desc='رقم 991'),
            row('3280', debit=5, desc='غيره'), row('1296', credit=5, desc='غيره'),
        ], book='الاجل')
        merged = [g for g in gs if g.merged_by]
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0].merged_by, merged[0].balanced, merged[0].status, len(merged[0].rows)),
                         ('date_branch', True, 'manual', 3))
        self.assertEqual(len(gs), 2)

    def test_returns_stay_unbalanced_when_union_does_not_balance(self):
        gs = self.groups([row('5105', credit=60, desc='م تالف'), row('2341', debit=100, desc='رقم 991')])
        self.assertEqual(sorted(g.status for g in gs), ['unbalanced', 'unbalanced'])
        self.assertFalse(any(g.balanced or g.merged_by for g in gs))

    def test_merge_needs_a_non_supplier_line_and_only_return_accounts(self):
        gs = self.groups([row('2341', debit=10, desc='ا'), row('2341', credit=10, desc='ب')])
        self.assertFalse(any(g.merged_by for g in gs))     # 2341 alone
        gs = self.groups([row('5105', credit=10, desc='ا'), row('2341', debit=5, desc='ب'), row('3280', debit=5, desc='ج')])
        self.assertFalse(any(g.merged_by for g in gs))     # 3280 is not a return account

    def test_group_with_a_rejected_row_is_never_balanced(self):
        gs = self.groups(self.manual_rows() + [row('3280', debit=1.005, desc='اهلاك الفترة')])
        self.assertEqual([(g.status, g.balanced) for g in gs], [('unbalanced', False)])

    def test_same_lines_different_descriptions_are_two_entries(self):
        gs = self.groups(self.manual_rows(desc='ا') + self.manual_rows(desc='ب'))
        self.assertEqual(len({g.key for g in gs}), 2)

    def test_statuses(self):
        gs = {g.description: g for g in self.groups(
            self.manual_rows(desc='قبل', date=OLD)
            + [row('6002', debit=5, desc='سوفتيك'), row('1302', credit=5, desc='سوفتيك')]
            + [row('9999', debit=5, desc='غير معروف'), row('1296', credit=5, desc='غير معروف')]
            + [row('1000', debit=5, desc='اجمالي'), row('1296', credit=5, desc='اجمالي')]
            + self.manual_rows(desc='فرع', branch='فرع مش موجود')
            + [row('3280', debit=5, desc='ناقص')]
            + self.mixed_rows())}
        self.assertEqual({k: v.status for k, v in gs.items()}, {
            'قبل': 'before_opening', 'سوفتيك': 'softech', 'غير معروف': 'unknown_account',
            'اجمالي': 'unknown_account', 'فرع': 'unknown_branch', 'ناقص': 'unbalanced', 'مختلط': 'mixed'})
        self.assertTrue(gs['قبل'].balanced)        # measured whatever the status
        self.assertTrue(gs['غير معروف'].balanced)
        self.assertEqual(gs['مختلط'].feeds, {'manual', 'softech'})

    def test_unbalanced_group_on_softech_accounts_is_softech(self):
        gs = self.groups([row('6002', debit=5, desc='ناقص')])
        self.assertEqual((gs[0].status, gs[0].balanced), ('softech', False))

    def test_key_unchanged_under_shuffled_rows_and_a_float_artefact(self):
        rows = [row('3280', debit=70.1, desc='ق'), row('3280', debit=29.9, desc='ق'), row('1296', credit=100, desc='ق')]
        key = self.groups(rows)[0].key
        self.assertEqual(self.groups(list(reversed(rows)))[0].key, key)
        noisy = [row('3280', debit=70.1000000001, desc='ق')] + rows[1:]
        self.assertEqual(self.groups(noisy)[0].key, key)

    def test_key_uses_the_resolved_branch(self):
        rows = self.manual_rows(**{'رقم الفرع': 'B81'})
        key = self.groups(self.manual_rows())[0].key
        self.assertEqual(self.groups(rows)[0].key, key)      # a re-export gaining the code column
        half = [self.manual_rows()[0], rows[1]]
        self.assertEqual([g.balanced for g in self.groups(half)], [True])   # one group, not two


class FeedTests(GLManualBase):
    def test_effective_feed_auto_from_rules_and_maps_and_override(self):
        def get(code):
            return GLAccount.objects.get(code=code)

        self.assertEqual(mi.effective_feed(get('6002')), 'softech')   # rule line
        self.assertEqual(mi.effective_feed(get('1302')), 'softech')   # source map
        self.assertEqual(mi.effective_feed(get('3280')), 'manual')
        self.assertEqual(mi.effective_feed(get('1999')), 'manual')    # inactive rule
        GLAccount.objects.filter(code='6002').update(feed='manual')
        GLAccount.objects.filter(code='3280').update(feed='softech')
        GLAccount.objects.filter(code='1296').update(feed='both')
        self.assertEqual(mi.effective_feed(get('6002')), 'manual')
        self.assertEqual(mi.effective_feed(get('3280')), 'softech')
        self.assertEqual(mi.effective_feed(get('1296')), 'both')

    def test_feed_is_memoised_per_import(self):
        path = self.xlsx(self.manual_rows() + self.manual_rows(desc='ب'))
        parsed = mi.parse_journal(path)
        with mock.patch('apps.finance.gl.plan2_adapter.softech_fed_account_codes', return_value=set()) as fed:
            mi.group_entries(parsed.rows)
        self.assertEqual(fed.call_count, 1)

    def test_both_counts_as_not_manual(self):
        GLAccount.objects.filter(code='1296').update(feed='both')
        self.assertEqual(self.groups(self.manual_rows())[0].status, 'mixed')
        GLAccount.objects.filter(code='3280').update(feed='both')
        self.assertEqual(self.groups(self.manual_rows())[0].status, 'softech')


class BranchTests(GLManualBase):
    def test_branch_alias_setting(self):
        hq, _ = Branch.objects.update_or_create(softech_branch_id='100', defaults={'name': 'المركز'})
        self.assertEqual(mi.resolve_branch(BRANCH).pk, self.branch.pk)
        self.assertEqual(mi.resolve_branch('فرع  الاختبار ').pk, self.branch.pk)    # normalize_ar
        self.assertEqual(mi.resolve_branch('شركة الرزيقى').pk, hq.pk)                # a default alias
        self.assertIsNone(mi.resolve_branch('اسم غريب'))
        self.assertIsNone(mi.resolve_branch('', '7'))
        SystemSetting.objects.create(key='gl_branch_aliases', label='x', value_type='json',
                                     value='{"اسم غريب": "B81", "7": "B81", "9": "ZZ"}')
        self.assertEqual(mi.resolve_branch('اسم غريب').pk, self.branch.pk)
        self.assertEqual(mi.resolve_branch('', '7').pk, self.branch.pk)
        self.assertIsNone(mi.resolve_branch('', '9'))                                 # alias to no branch
        self.assertEqual(mi.resolve_branch('شركة الرزيقى').pk, hq.pk)                # defaults stay

    def test_bad_alias_setting_is_ignored(self):
        SystemSetting.objects.create(key='gl_branch_aliases', label='x', value_type='json', value='[1]')
        with self.assertLogs('apps.finance.gl.manual_import', 'WARNING'):
            self.assertEqual(mi.resolve_branch(BRANCH).pk, self.branch.pk)


class PreviewTests(GLManualBase):
    def test_preview_lists_manual_accounts(self):
        res = mi.preview(self.xlsx(
            self.manual_rows() + [row('6002', debit=5, desc='س'), row('1302', credit=5, desc='س')]
            + [row('5105', credit=7, desc='م'), row('2341', debit=7, desc='9')]
            + [row('3280', condition='Nothing')] + [row('3280', debit=1, date=None)]))
        self.assertEqual(res['book'], 'cash')
        self.assertEqual([a['code'] for a in res['manual_accounts']], ['1296', '2341', '3280', '5105'])
        self.assertEqual(res['manual_accounts'][0]['name'], 'حساب 1296')
        self.assertEqual(res['counts'], {'manual': 2, 'softech': 1, 'mixed': 0, 'unbalanced': 0,
                                         'unknown_account': 0, 'unknown_branch': 0, 'before_opening': 0,
                                         'changed_since_import': 0, 'possible_duplicate': 0})
        self.assertEqual((res['merged_count'], res['balanced_count'], res['skipped_zero']), (1, 3, 1))
        self.assertEqual(res['skipped'], [{'row': 10, 'reason': 'no_date'}])
        self.assertEqual(res['totals']['debit'], _d('112.00'))
        self.assertEqual(res['totals']['credit'], _d('112.00'))
        self.assertEqual(len(res['groups']), 3)
        self.assertFalse(LedgerEntry.objects.exists() or GLSourceDoc.objects.exists())

    def test_preview_saves_nothing_on_mixed(self):
        res = mi.preview(self.xlsx(self.mixed_rows()))
        self.assertEqual(res['counts']['mixed'], 1)
        self.assertEqual(res['groups'][0]['key'][:14], 'manual_import:')
        self.assertFalse(GLSourceDoc.objects.exists() or SourceException.objects.exists())


class ManualSetTests(GLManualBase):
    def setUp(self):
        GLAccount.objects.filter(code='1301').update(feed='softech')

    def test_listed_account_set_is_manual_whatever_the_feed(self):
        rows = [row('1301', debit=30, desc='تحويل داخلي'), row('1302', credit=30, desc='تحويل داخلي')]
        g = self.groups(rows)[0]
        self.assertEqual((g.status, g.manual_set, g.feeds), ('manual', True, {'softech'}))
        self.assertEqual(self.run_import(rows)['imported'], 1)

    def test_link_account_is_ignored_in_the_comparison(self):
        gs = self.groups([row('1301', debit=30), row('2354', credit=15), row('1302', credit=15)])
        self.assertEqual(gs[0].status, 'manual')

    def test_a_group_beyond_the_listed_set_is_not_covered(self):
        g = self.groups([row('1301', debit=30), row('1302', credit=15), row('6002', credit=15)])[0]
        self.assertEqual((g.status, g.manual_set), ('softech', False))

    def test_still_needs_to_balance_and_a_branch(self):
        self.assertEqual(self.groups([row('1301', debit=30), row('1302', credit=20)])[0].status, 'unbalanced')
        gs = self.groups([row('1301', debit=30, branch='غريب'), row('1302', credit=30, branch='غريب')])
        self.assertEqual(gs[0].status, 'unknown_branch')

    def test_setting_replaces_the_default_and_a_bad_one_is_ignored(self):
        setting = SystemSetting.objects.create(key='gl_import_manual_account_sets', label='x', value_type='json',
                                               value='[["6002", "1302"]]')
        self.assertEqual(self.groups([row('6002', debit=5), row('1302', credit=5)])[0].status, 'manual')
        setting.value = '["6002"]'
        setting.save()
        with self.assertLogs('apps.finance.gl.manual_import', 'WARNING'):
            self.assertEqual(self.groups([row('6002', debit=5), row('1302', credit=5)])[0].status, 'softech')

    def test_softech_groups_summarised_by_account_set(self):
        rows = ([row('6002', debit=5, desc='ا'), row('1302', credit=5, desc='ا')]
                + [row('1302', debit=7, desc='ب'), row('6002', credit=7, desc='ب')]
                + self.manual_rows())
        expected = [{'accounts': ['1302', '6002'], 'groups': 2, 'debit': _d('12.00'), 'credit': _d('12.00')}]
        self.assertEqual(mi.preview(self.xlsx(rows))['softech_summary'], expected)
        self.assertEqual(self.run_import(rows)['softech_summary'], expected)

    def test_party_missing_counted_for_importable_groups(self):
        GLAccount.objects.filter(code='2341').update(requires_party=True)
        res = mi.preview(self.xlsx(
            [row('3280', debit=5, desc='ا'), row('2341', credit=5, desc='ا')]
            + [row('3280', debit=6, desc='ب'), row('2341', credit=6, desc='ب', **{'suppliar code': 'S1'})]
            + [row('3280', debit=7, desc='ج', date=OLD), row('2341', credit=7, desc='ج', date=OLD)]))
        self.assertEqual(res['party_missing'], 1)
        self.assertEqual(len(res['warnings']), 1)


class ChangedSinceImportTests(GLManualBase):
    def test_row_added(self):
        self.run_import(self.manual_rows())
        entry = LedgerEntry.objects.get()
        rows = [row('3280', debit=100, desc='اهلاك الفترة'), row('3280', debit=5, desc='اهلاك الفترة'),
                row('1296', credit=105, desc='اهلاك الفترة')]
        res = self.run_import(rows)
        self.assertEqual((res['imported'], res['changed_since_import']), (0, 1))
        self.assertEqual(res['not_imported']['changed_since_import'][0]['existing_entry_id'], entry.pk)
        self.assertEqual(LedgerEntry.objects.count(), 1)

    def test_figure_corrected_shows_the_number_of_an_approved_entry(self):
        self.run_import(self.manual_rows(amount=100))
        entry = approve(LedgerEntry.objects.get().pk, user=self.staff)
        res = mi.preview(self.xlsx(self.manual_rows(amount=101)))
        self.assertEqual(res['counts']['changed_since_import'], 1)
        g = res['groups'][0]
        self.assertEqual((g['existing_entry_id'], g['existing_entry_number']), (entry.pk, entry.number))

    def test_merged(self):
        self.run_import([row('5105', credit=60, desc='م تالف'), row('2341', debit=60, desc='رقم 1')], book='الاجل')
        self.assertEqual(LedgerEntry.objects.count(), 1)
        # another description, another figure: still that day's merged entry
        res = self.run_import([row('5106', credit=70, desc='جبر كسور'), row('2341', debit=70, desc='رقم 2')],
                              book='الاجل')
        self.assertEqual(res['changed_since_import'], 1)
        self.assertEqual(LedgerEntry.objects.count(), 1)

    def test_same_lines_are_still_already_imported(self):
        self.run_import(self.manual_rows())
        res = self.run_import(self.manual_rows())
        self.assertEqual((res['already_imported'], res['changed_since_import']), (1, 0))

    def test_another_description_or_date_is_a_new_group(self):
        self.run_import(self.manual_rows())
        self.assertEqual(self.run_import(self.manual_rows(amount=9, desc='غيره'))['imported'], 1)
        self.assertEqual(self.run_import(self.manual_rows(amount=9, date=D2))['imported'], 1)

    def test_reimports_once_the_old_entry_is_deleted_or_reversed(self):
        self.run_import(self.manual_rows(amount=100))
        LedgerEntry.objects.get().delete()
        self.assertEqual(self.run_import(self.manual_rows(amount=101))['imported'], 1)
        approved = approve(LedgerEntry.objects.get().pk, user=self.staff)
        reverse(approved.pk, user=self.staff, reason='تصحيح')
        self.assertEqual(self.run_import(self.manual_rows(amount=102))['imported'], 1)

    def test_a_changed_mixed_group_is_not_parked_or_includable(self):
        key = mi.group_entries(mi.parse_journal(self.xlsx(self.mixed_rows())).rows)[0].key
        self.run_import(self.mixed_rows(), include=[key])
        rows = [row('1302', debit=51, desc='مختلط'), row('3280', credit=51, desc='مختلط')]
        new_key = mi.group_entries(mi.parse_journal(self.xlsx(rows)).rows)[0].key
        res = self.run_import(rows, include=[new_key])
        self.assertEqual((res['included'], res['parked'], res['changed_since_import']), (0, 0, 1))
        self.assertEqual(res['include_unmatched'], [new_key])
        self.assertFalse(SourceException.objects.exists())

    def test_edited_description_does_not_hide_the_group(self):
        self.run_import(self.manual_rows())
        LedgerEntry.objects.update(description='عدّله محاسب')
        self.assertEqual(self.run_import(self.manual_rows(amount=101))['changed_since_import'], 1)


class PossibleDuplicateTests(GLManualBase):
    def setUp(self):
        GLAccount.objects.filter(code='1301').update(feed='softech')

    def drafted(self, amount=30, day=D, branch=None, source_type='treasury_other', key='t8:voucher:1', **kw):
        return save_draft(
            user=self.staff, entry_date=day.date(), description='سند تحويل', branch=branch or self.branch,
            source_type=source_type, source_key=key, lines=[
                {'account_code': '1301', 'debit': _d(amount), 'credit': _d(0)},
                {'account_code': '1302', 'debit': _d(0), 'credit': _d(amount)}], **kw)

    def keyed(self, amount=30, **kw):
        return [row('1301', debit=amount, desc='تحويل داخلي', **kw), row('1302', credit=amount, desc='تحويل داخلي', **kw)]

    def test_drafted_transfer_and_the_same_keyed_group_is_possible_duplicate(self):
        entry = approve(self.drafted().pk, user=self.staff)
        res = mi.preview(self.xlsx(self.keyed()))
        self.assertEqual(res['counts']['possible_duplicate'], 1)
        g = res['groups'][0]
        self.assertEqual((g['status'], g['existing_entry_id'], g['existing_entry_number']),
                         ('possible_duplicate', entry.pk, entry.number))
        res = self.run_import(self.keyed())
        self.assertEqual((res['imported'], res['possible_duplicate']), (0, 1))
        self.assertEqual(res['not_imported']['possible_duplicate'][0]['existing_entry_id'], entry.pk)
        self.assertFalse(LedgerEntry.objects.filter(source_type='manual_import').exists())
        self.assertFalse(SourceException.objects.exists())

    def test_different_total_is_manual(self):
        self.drafted(amount=31)
        self.assertEqual(self.groups(self.keyed())[0].status, 'manual')

    def test_included_is_imported_and_stays_imported(self):
        self.drafted()
        path = self.xlsx(self.keyed())
        key = mi.group_entries(mi.parse_journal(path).rows)[0].key
        res = mi.import_entries(path, user=self.staff, include_mixed=[key])
        self.assertEqual((res['included'], res['possible_duplicate'], res['include_unmatched']), (1, 0, []))
        self.assertEqual(LedgerEntry.objects.get(source_key=key).status, 'draft')
        res = mi.import_entries(path, user=self.staff)
        self.assertEqual((res['already_imported'], res['possible_duplicate']), (1, 0))

    def test_another_date_branch_or_direction_is_manual(self):
        self.drafted(day=D2)
        other, _ = Branch.objects.update_or_create(softech_branch_id='B82', defaults={'name': 'فرع تاني'})
        self.drafted(branch=other, key='t8:voucher:2')
        save_draft(user=self.staff, entry_date=D.date(), description='عكس الاتجاه', branch=self.branch,
                   source_type='treasury_other', source_key='t8:voucher:3', lines=[
                       {'account_code': '1302', 'debit': _d(30), 'credit': _d(0)},
                       {'account_code': '1301', 'debit': _d(0), 'credit': _d(30)}])
        self.assertEqual(self.groups(self.keyed())[0].status, 'manual')

    def test_a_line_on_the_branch_counts_when_the_entry_has_none(self):
        save_draft(user=self.staff, entry_date=D.date(), description='س', source_type='treasury_other',
                   source_key='t8:voucher:4', lines=[
                       {'account_code': '1301', 'debit': _d(30), 'credit': _d(0), 'branch_id': self.branch.pk},
                       {'account_code': '1302', 'debit': _d(0), 'credit': _d(30)}])
        self.assertEqual(self.groups(self.keyed())[0].status, 'possible_duplicate')

    def test_reversed_entries_and_their_mirrors_do_not_count(self):
        reverse(approve(self.drafted().pk, user=self.staff).pk, user=self.staff, reason='خطأ')
        self.assertEqual(self.groups(self.keyed())[0].status, 'manual')

    def test_a_manual_import_entry_does_not_count(self):
        self.run_import(self.keyed())
        rows = [row('1301', debit=30, desc='تحويل تاني'), row('1302', credit=30, desc='تحويل تاني')]
        self.assertEqual(self.groups(rows)[0].status, 'manual')

    def test_only_groups_manual_through_the_list(self):
        GLAccount.objects.filter(code__in=('1301', '1302')).update(feed='manual')
        self.drafted()
        self.assertEqual(self.groups(self.keyed())[0].status, 'manual')

    def test_link_lines_are_left_out_of_the_comparison(self):
        self.drafted()
        rows = [row('1301', debit=30, desc='ر'), row('1302', credit=30, desc='ر'),
                row('2354', debit=5, desc='ر'), row('2354', credit=5, desc='ر')]
        self.assertEqual(self.groups(rows)[0].status, 'possible_duplicate')

    def _line_queries(self, rows):
        parsed = mi.parse_journal(self.xlsx(rows))
        lookups = mi._Lookups(parsed.rows)
        with CaptureQueriesContext(connection) as ctx:
            mi.group_entries(parsed.rows, lookups=lookups)
        return [q for q in ctx.captured_queries if 'finance_ledgerline' in q['sql']]

    def test_one_query_over_the_date_range(self):
        self.drafted()
        rows = self.keyed() + self.keyed(date=D2) + [
            row('1301', debit=9, desc='ب', date=D2), row('1302', credit=9, desc='ب', date=D2)]
        found = self._line_queries(rows)
        self.assertEqual(len(found), 1)
        self.assertIn('2026-03-10', found[0]['sql'])
        self.assertIn('2026-03-11', found[0]['sql'])
        self.assertEqual(self._line_queries(self.manual_rows()), [])   # nothing on the list: no query


class LinkAccountTests(GLManualBase):
    def test_link_account_does_not_make_group_mixed_and_is_reported(self):
        rows = [row('3280', debit=70, desc='فاتورة'), row('2354', credit=70, desc='فاتورة'),
                row('2354', debit=70, desc='سداد'), row('1296', credit=70, desc='سداد')]
        res = mi.preview(self.xlsx(rows))
        self.assertEqual(res['counts']['manual'], 2)
        self.assertEqual(res['link_accounts'], [{'code': '2354', 'debit': _d('70.00'), 'credit': _d('70.00'),
                                                 'net': _d('0.00')}])
        self.assertEqual(res['warnings'], [])
        self.assertNotIn('2354', [a['code'] for a in res['manual_accounts']])
        res = mi.import_entries(self.xlsx(rows), user=self.staff)
        self.assertEqual(res['imported'], 2)
        e = LedgerEntry.objects.filter(source_type='manual_import', lines__account__code='2354')
        self.assertEqual(e.distinct().count(), 2)              # kept as they stand

    def test_link_line_next_to_softech_line_is_softech(self):
        gs = self.groups([row('6002', debit=70), row('2354', credit=70)])
        self.assertEqual(gs[0].status, 'softech')

    def test_net_warning_only_for_a_file_holding_both_books(self):
        rows = [row('3280', debit=70, desc='ا'), row('2354', credit=70, desc='ا')]
        self.assertEqual(mi.preview(self.xlsx(rows))['warnings'], [])            # one book: its other half is elsewhere
        both = rows + [row('2354', debit=60, desc='ب', **{BOOK_COL: 'الاجل'}),
                       row('1296', credit=60, desc='ب', **{BOOK_COL: 'الاجل'})]
        res = mi.preview(self.xlsx(both))
        self.assertEqual(res['book'], 'mixed')
        self.assertEqual(res['link_accounts'][0]['net'], _d('-10.00'))
        self.assertEqual(len(res['warnings']), 1)
        self.assertIn('2354', res['warnings'][0])

    def test_link_setting_replaces_default(self):
        SystemSetting.objects.create(key='gl_import_link_accounts', label='x', value_type='json', value='["6002"]')
        gs = self.groups([row('3280', debit=70), row('6002', credit=70)])
        self.assertEqual(gs[0].status, 'manual')


class ImportTests(GLManualBase):
    def test_manual_group_imported_as_draft(self):
        res = self.run_import([
            row('3280', debit=100, desc='اهلاك', **{'shift num.': 2}),
            row('2341', credit=100, desc='اهلاك', **{'suppliar code': 'S9', 'customer code': 'C9',
                                                       'Payment cheque num.': 'P1',
                                                       'due1': datetime.datetime(2026, 5, 1)}),
            row('1341', debit=30, desc='ع', **{'customer code': 'C1', 'suppliar code': 'S1'}),
            row('1351', credit=30, desc='ع', **{'كود الموظف': 'E1', 'customer code': 'C1'}),
        ], book='الاجل')
        self.assertEqual(res['imported'], 2)
        e = LedgerEntry.objects.get(description='اهلاك')
        self.assertEqual((e.status, e.book, e.branch_id, e.source_type, e.entry_date, e.created_by_id),
                         ('draft', 'credit', self.branch.pk, 'manual_import', D.date(), self.staff.pk))
        self.assertTrue(e.source_key.startswith('manual_import:'))
        self.assertRegex(e.source_key, r'^manual_import:[0-9a-f]{20}:[0-9a-f]{12}$')
        lines = list(e.lines.order_by('line_no').select_related('account'))
        self.assertEqual([(ln.account.code, ln.debit, ln.credit, ln.branch_id) for ln in lines], [
            ('3280', _d('100.00'), _d('0'), self.branch.pk), ('2341', _d('0'), _d('100.00'), self.branch.pk)])
        self.assertEqual((lines[0].party_code, lines[1].party_code), ('', 'S9'))    # by the account's party type
        self.assertEqual((lines[1].cheque_no, lines[1].due_date), ('P1', datetime.date(2026, 5, 1)))
        self.assertEqual(lines[0].description, 'اهلاك')
        other = LedgerEntry.objects.get(description='ع').lines.order_by('line_no')
        self.assertEqual([ln.party_code for ln in other], ['C1', 'E1'])
        log = AuditLog.objects.filter(action='gl_manual_import').latest('id')
        self.assertEqual(log.new_data['imported'], 2)
        self.assertFalse(LedgerEntry.objects.exclude(status='draft').filter(source_type='manual_import').exists())

    def test_softech_group_skipped(self):
        res = self.run_import([row('6002', debit=5), row('1302', credit=5)])
        self.assertEqual((res['imported'], res['softech']), (0, 1))
        self.assertFalse(LedgerEntry.objects.exists())
        self.assertFalse(GLSourceDoc.objects.exists())

    def test_unbalanced_and_unknown_account_reported_not_imported(self):
        res = self.run_import(
            [row('3280', debit=5, desc='ناقص')]
            + [row('9999', debit=5, desc='غريب'), row('1296', credit=5, desc='غريب')]
            + self.manual_rows(desc='فرع', branch='فرع مش موجود')
            + self.manual_rows(desc='قديم', date=OLD)
            + self.manual_rows(desc='سليم'))
        self.assertEqual((res['imported'], res['unbalanced'], res['unknown_account'], res['unknown_branch'],
                          res['before_opening']), (1, 1, 1, 1, 1))
        self.assertEqual(list(LedgerEntry.objects.values_list('description', flat=True)), ['سليم'])
        self.assertFalse(SourceException.objects.exists())
        self.assertEqual(sorted(res['not_imported'].keys()),
                         ['before_opening', 'unbalanced', 'unknown_account', 'unknown_branch'])
        self.assertEqual(len(res['not_imported']['unbalanced']), 1)

    def test_reimport_creates_no_duplicates(self):
        rows = self.manual_rows() + self.mixed_rows()
        first = self.run_import(rows)
        self.assertEqual((first['imported'], first['parked']), (1, 1))
        drafts = LedgerEntry.objects.count()
        second = self.run_import(rows)
        self.assertEqual((second['imported'], second['already_imported'], second['parked'], second['parked_existing']),
                         (0, 1, 0, 1))
        self.assertEqual(LedgerEntry.objects.count(), drafts)
        self.assertEqual(GLSourceDoc.objects.count(), 1)
        self.assertEqual(SourceException.objects.count(), 1)

    def test_reimport_after_reversal_or_delete_is_a_new_draft(self):
        self.run_import(self.manual_rows())
        LedgerEntry.objects.filter(source_type='manual_import').update(status='reversed')
        self.assertEqual(self.run_import(self.manual_rows())['imported'], 1)

    def test_source_conflict_race_counts_as_already_imported(self):
        path = self.xlsx(self.manual_rows())
        parsed = mi.parse_journal(path)
        key = mi.group_entries(parsed.rows)[0].key
        save_draft(user=self.staff, entry_date=D.date(), description='سبق', source_type='manual_import',
                   source_key=key, lines=[{'account_code': '3280', 'debit': _d(1), 'credit': _d(0)}])
        with mock.patch.object(mi, '_live_keys', return_value=set()):   # as if it landed after the check
            res = mi.import_entries(path, user=self.staff)
        self.assertEqual((res['imported'], res['already_imported'], res['failed']), (0, 1, []))

    def test_a_refused_group_does_not_stop_the_others(self):
        rows = self.manual_rows(desc='ا') + self.manual_rows(desc='ب')
        real = mi.save_draft
        calls = []

        def flaky(**kw):
            calls.append(kw)
            if len(calls) == 1:
                raise mi.LedgerError('bad_amount')
            return real(**kw)
        with mock.patch.object(mi, 'save_draft', side_effect=flaky):
            res = self.run_import(rows)
        self.assertEqual(res['imported'], 1)
        self.assertEqual([f['code'] for f in res['failed']], ['bad_amount'])

    def test_audit_holds_no_figures_from_the_file(self):
        self.run_import(self.manual_rows(amount=98765.43, desc='بيان سري') + [row('3280', debit=11.111, desc='ب')])
        log = AuditLog.objects.filter(action='gl_manual_import').latest('id')
        self.assertEqual(log.new_data['imported'], 1)
        self.assertEqual(log.user_name, self.staff.full_name)
        written = json.dumps([log.new_data, log.extra, log.note], ensure_ascii=False)
        for secret in ('98765', '11.111', 'بيان سري'):
            self.assertNotIn(secret, written)

    def test_an_imported_draft_can_be_approved(self):
        self.run_import(self.manual_rows())
        entry = approve(LedgerEntry.objects.get().pk, user=self.staff)
        self.assertEqual(entry.status, 'approved')
        self.assertTrue(entry.number.startswith('JV-2026-'))
        self.assertEqual(self.run_import(self.manual_rows())['already_imported'], 1)


class MixedTests(GLManualBase):
    def park(self):
        res = self.run_import(self.mixed_rows())
        self.assertEqual(res['parked'], 1)
        return res, SourceException.objects.get(kind='mixed_manual_entry')

    def test_mixed_group_parked_as_exception_unless_included(self):
        res, exc = self.park()
        self.assertEqual(res['imported'], 0)
        self.assertFalse(LedgerEntry.objects.exists())
        doc = exc.source_doc
        self.assertEqual((doc.source_type, doc.doc_date, doc.branch_code, doc.status, doc.amounts, doc.attrs),
                         ('manual_import', D.date(), 'B81', 'exception', {}, {'book': 'cash', 'description': 'مختلط'}))
        self.assertTrue(doc.source_key.startswith('manual_import:'))
        self.assertEqual((exc.status, exc.source_date, exc.detail), ('open', D.date(), {'group_key': doc.source_key}))
        self.assertEqual(res['parked_keys'], [doc.source_key])
        self.assertEqual([ln['account_code'] for ln in exc.proposed_lines], ['1302', '3280'])
        self.assertEqual(exc.proposed_lines[0]['debit'], '50.00')
        self.assertEqual(exc.proposed_lines[0]['branch_id'], self.branch.pk)
        self.assertEqual(open_exception_count(D.date(), D.date()), 1)     # blocks that month's close

        path = self.xlsx(self.mixed_rows())
        direct = mi.import_entries(path, user=self.staff, include_mixed=[doc.source_key])
        self.assertEqual(direct['included'], 1)
        entry = LedgerEntry.objects.get(source_key=doc.source_key)
        self.assertEqual(entry.status, 'draft')
        self.assertEqual(sorted(entry.lines.values_list('account__code', flat=True)), ['1302', '3280'])  # all its lines

    def test_including_a_parked_group_resolves_its_exception(self):
        res, exc = self.park()
        key = exc.source_doc.source_key
        res = self.run_import(self.mixed_rows(), include=[key])
        self.assertEqual((res['included'], res['parked']), (1, 0))
        exc.refresh_from_db()
        entry = LedgerEntry.objects.get(source_key=key)
        self.assertEqual((exc.status, exc.resolved_by_id), ('resolved', self.staff.pk))
        self.assertIsNotNone(exc.resolved_at)
        doc = exc.source_doc
        doc.refresh_from_db()
        self.assertEqual((doc.status, doc.entry_id), ('drafted', entry.pk))
        self.assertEqual(open_exception_count(D.date(), D.date()), 0)
        log = AuditLog.objects.filter(action='gl_manual_exception_resolved').latest('id')
        self.assertEqual((log.old_data['status'], log.new_data['status']), ('open', 'resolved'))
        # a third run finds it imported; the resolved row stays resolved
        res = self.run_import(self.mixed_rows())
        self.assertEqual((res['already_imported'], res['parked'], res['parked_existing']), (1, 0, 0))
        self.assertEqual(SourceException.objects.count(), 1)

    def test_include_of_a_group_that_is_not_mixed_does_nothing(self):
        path = self.xlsx([row('6002', debit=5), row('1302', credit=5)])
        key = mi.group_entries(mi.parse_journal(path).rows)[0].key
        res = mi.import_entries(path, user=self.staff, include_mixed=[key, 'manual_import:nope'])
        self.assertEqual(res['included'], 0)
        self.assertFalse(LedgerEntry.objects.exists())
        self.assertEqual(sorted(res['include_unmatched']), sorted([key, 'manual_import:nope']))

    def test_ignored_parked_group_stays_ignored_on_reimport(self):
        _, exc = self.park()
        exc.status = 'ignored'
        exc.save(update_fields=['status'])
        res = self.run_import(self.mixed_rows())
        self.assertEqual((res['parked'], res['parked_existing'], res['parked_keys']), (0, 1, []))
        self.assertEqual(SourceException.objects.filter(status='open').count(), 0)

    def test_still_open_parked_group_is_listed_again(self):
        _, exc = self.park()
        res = self.run_import(self.mixed_rows())
        self.assertEqual((res['parked_existing'], res['parked_keys']), (1, [exc.source_doc.source_key]))

    def test_parked_group_that_became_manual_resolves_on_import(self):
        _, exc = self.park()
        GLAccount.objects.filter(code='1302').update(feed='manual')
        res = self.run_import(self.mixed_rows())
        self.assertEqual(res['imported'], 1)
        exc.refresh_from_db()
        self.assertEqual(exc.status, 'resolved')

    def test_include_rolls_back_when_the_draft_is_refused(self):
        _, exc = self.park()
        key = exc.source_doc.source_key
        with mock.patch.object(mi, 'save_draft', side_effect=mi.LedgerError('bad_amount')):
            res = self.run_import(self.mixed_rows(), include=[key])
        self.assertEqual([f['code'] for f in res['failed']], ['bad_amount'])
        exc.refresh_from_db()
        self.assertEqual(exc.status, 'open')


class Plan2LeavesManualDocsAloneTests(GLManualBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with contextlib.redirect_stdout(io.StringIO()):
            call_command('seed_permissions', verbosity=0)

    def setUp(self):
        _, _, self.client_acct = make_user('t8m_api', role='accountant')
        self.run_import(self.mixed_rows())
        self.exc = SourceException.objects.get(kind='mixed_manual_entry')

    def test_redraft_leaves_manual_import_docs_alone(self):
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            r = self.client_acct.post(BASE + 'exceptions/redraft/', {'ids': [self.exc.pk]}, format='json')
        self.assertEqual(r.status_code, 400, r.content)
        st.assert_not_called()
        self.assertFalse(GLDraftRun.objects.exists())

    def test_redraft_of_a_selection_runs_the_others_only(self):
        doc = GLSourceDoc.objects.create(source_type='sales_tenders', source_key='k1', doc_date=D2.date(),
                                         branch_code='B81', amounts={}, content_hash='k1', status='exception')
        other = SourceException.objects.create(source_doc=doc, kind='no_rule', source_date=D2.date(), message='m')
        with mock.patch('apps.finance.gl.drafting_views.start_thread'):
            r = self.client_acct.post(BASE + 'exceptions/redraft/', {'ids': [self.exc.pk, other.pk]}, format='json')
        self.assertEqual(r.status_code, 202, r.content)
        run = GLDraftRun.objects.get(pk=r.data['run_id'])
        self.assertEqual(run.source_types, ['sales_tenders'])
        self.assertEqual((run.date_from, run.date_to), (D2.date(), D2.date()))

    def test_engine_run_never_touches_a_parked_doc(self):
        doc = self.exc.source_doc
        run = drafting.start_run(triggered_by='test', date_from=D.date(), date_to=D.date(), source_types=[])
        drafting.draft_range(D.date(), D.date(), run=run, fetch=lambda sql: [], readers={'sales_tenders': lambda a, b, f: []})
        doc.refresh_from_db()
        self.exc.refresh_from_db()
        self.assertEqual((doc.status, self.exc.status), ('exception', 'open'))

    def test_p23_decisions_refuse_a_parked_exception(self):
        for url in ('accept-softech', 'keep-edit'):
            r = self.client_acct.post(f'{BASE}exceptions/{self.exc.pk}/{url}/', {'version': 'x'}, format='json')
            self.assertEqual(r.status_code, 409, r.content)
            self.assertEqual(r.data['code'], 'not_edited_by_user')

    def test_ignore_with_a_reason_works(self):
        r = self.client_acct.post(f'{BASE}exceptions/{self.exc.pk}/ignore/', {'note': 'مش محتاجينه'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.exc.refresh_from_db()
        self.assertEqual(self.exc.status, 'ignored')
        self.assertEqual(open_exception_count(D.date(), D.date()), 0)


class CommandTests(GLManualBase):
    def call(self, *args):
        out = io.StringIO()
        call_command('import_gl_manual_entries', *args, stdout=out)
        return out.getvalue()

    def test_preview_saves_nothing(self):
        out = self.call(self.xlsx(self.manual_rows() + self.mixed_rows()), '--preview')
        self.assertIn('manual=1', out)
        self.assertIn('mixed=1', out)
        self.assertFalse(LedgerEntry.objects.exists() or GLSourceDoc.objects.exists())

    def test_import_and_include_mixed(self):
        path = self.xlsx(self.manual_rows() + self.mixed_rows())
        out = self.call(path, '--user', self.staff.user.username)
        self.assertIn('imported=1', out)
        self.assertIn('parked=1', out)
        key = GLSourceDoc.objects.get().source_key
        self.assertIn(key, out)
        self.assertEqual(LedgerEntry.objects.get().created_by_id, self.staff.pk)
        with self.assertRaises(CommandError):
            self.call(path, '--include-mixed', key)
        out = self.call(path, '--include-mixed', key, '--user', self.staff.user.username)
        self.assertIn('included=1', out)
        self.assertNotIn(f'parked {key}', out)

    def test_output_lists_skipped_rows_groups_not_imported_and_softech_dropped(self):
        path = self.xlsx([row('3280', debit=5, desc='ناقص'), row('3280', debit=1, date=None),
                          row('6002', debit=5, desc='س'), row('1302', credit=5, desc='س')])
        for args in (['--preview'], []):
            out = self.call(path, *args)
            self.assertIn('skipped no_date (1): rows 4', out)
            self.assertIn('unbalanced manual_import:', out)
            self.assertIn('softech dropped accounts=1302,6002 groups=1', out)

    def test_ignored_group_prints_no_parked_key(self):
        path = self.xlsx(self.mixed_rows())
        self.call(path)
        SourceException.objects.update(status='ignored')
        self.assertNotIn('parked manual_import:', self.call(path))

    def test_book_and_sheet_arguments(self):
        path = self.xlsx(self.manual_rows(), book=None)
        with self.assertRaises(CommandError):
            self.call(path, '--preview')
        self.assertIn('book=credit', self.call(path, '--preview', '--book', 'credit', '--sheet', 'اليومية الامريكية'))

    def test_unknown_user_refused(self):
        with self.assertRaises(CommandError):
            self.call(self.xlsx(self.manual_rows()), '--user', 'nobody-here')


class MoneyTests(SimpleTestCase):
    def test_money(self):
        self.assertEqual(mi._money(None), Decimal('0.00'))
        self.assertEqual(mi._money(''), Decimal('0.00'))
        self.assertEqual(mi._money(12), Decimal('12.00'))
        self.assertEqual(mi._money(12.34), Decimal('12.34'))
        self.assertEqual(mi._money('12.34'), Decimal('12.34'))
        self.assertEqual(mi._money(0.1 + 0.2), Decimal('0.30'))
        for bad in (12.3451, '12.341', 'x', float('nan'), float('inf'), True, 1e17):
            with self.assertRaises(ValueError, msg=repr(bad)):
                mi._money(bad)
