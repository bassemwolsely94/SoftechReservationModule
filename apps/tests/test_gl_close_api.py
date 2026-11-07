"""Close, comparison, sub-ledger, correction and cutover API (finance-gl Plan 3, Task 10).

SOFTECH is mocked; the workbooks are synthetic. TestCase throughout (ruling): the background threads never really
start. `start_thread` is patched, and where a test needs the run's outcome it runs the target inline.
"""
import datetime
import io
import json
import zipfile
from decimal import Decimal
from unittest import mock

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.finance import recon_labels
from apps.finance.gl import close as close_service
from apps.finance.gl import close_views, compare, plan2_adapter, softech_checks, softech_stock
from apps.finance.gl.close import CloseError
from apps.finance.gl.ledger import approve, save_draft
from apps.finance.gl.periods import month_period
from apps.finance.gl.softech_stock import Valuation
from apps.finance.models import (ClosingStockSnapshot, FinancialPeriod, GLAccount, GLAccountGroup, GLComparisonLine, GLSoftechCheck,
                                 GLSourceDoc, LedgerEntry, SourceException)
from apps.tests.factories import make_user
from apps.tests.security.fixtures import seed_code_matrix
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

BASE = '/api/finance/gl/'
VIEWS = 'apps.finance.gl.close_views'
LOGGER = 'elrezeiky.finance'
D = datetime.date
JAN, MAR = D(2026, 1, 31), D(2026, 3, 10)
BRANCH_NAME = 'فرع الاختبار'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _bearer(user):
    """Authenticated like the browser (Bearer JWT), so ModuleAccessMiddleware sees it."""
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
    return c


def _inline(target, *, args=(), kwargs=None, name=None, daemon=True):
    target(*args, **(kwargs or {}))


def _store(code, value, as_of):
    return {'store_code': code, 'store_name': f'مخزن {code}', 'branch_code': code, 'included': True, 'rows': 3,
            'value': Decimal(str(value)), 'snapshot_date': as_of, 'carried': False}


def _journal(rows, book='النقدى', name='journal.xlsx'):
    """rows: (account, debit, credit, description). `book` None = no book column."""
    wb = openpyxl.Workbook()
    ws = wb.active
    labels = ['رقم العملية', 'discreption', 'مدين', 'credit', 'date', 'اسم الفرع']
    ws.append(labels + (['اليومية'] if book else []))
    for account, debit, credit, desc in rows:
        ws.append([account, desc, debit, credit, datetime.datetime(2026, 3, 10), BRANCH_NAME] + ([book] if book else []))
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=XLSX)


def _workbook(name='finance.xlsx'):
    """Finance's pivots, the two required sheets: 9901 at the Giza branch holds 70 against the ledger's 100."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'ميزان الفروع '
    ws.append(['Sub account name', 'رقم العملية', 'Trans. Name', 'صيدلية د بليغ الجيزة', 'Grand Total'])
    ws.append(['مجموعة', 9901, 'حساب', 70, 70])
    ws = wb.create_sheet('المشتريات والمبيعات ')
    ws.append(['Sub account name', 'رقم العملية', 'Trans. Name', 1, 2, 3])
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=XLSX)


class ApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.acct_user, cls.acct_staff, _ = make_user('gl_api_acct', role='accountant')
        cls.admin_user, cls.admin_staff, _ = make_user('gl_api_admin', role='admin', access_all=True)
        g = GLAccountGroup.objects.create(name='مجموعة API', section='balance_sheet', order=1)
        t = GLAccountGroup.objects.create(name='متاجرة API', section='trading', order=2)
        mk = GLAccount.objects.create
        mk(code='9901', name='يدوي أول', group=g, nature='debit', account_type='asset', feed='manual')
        mk(code='9902', name='يدوي تاني', group=t, nature='credit', account_type='revenue', feed='manual')
        mk(code='9903', name='من سوفتيك', group=g, nature='debit', account_type='asset', feed='softech')
        mk(code='2341', name='الموردون', group=g, nature='credit', account_type='liability', party_type='supplier')
        mk(code='1390', name='بضاعة آخر المدة', group=g, nature='debit', account_type='asset',
           statement_line='inventory', requires_branch=True)
        mk(code='5302', name='مخزون آخر المدة', group=t, nature='credit', account_type='revenue',
           statement_line='closing_stock', requires_branch=True)
        cls.branch = Branch.objects.create(softech_branch_id='961', name=BRANCH_NAME)
        cls.giza = Branch.objects.create(softech_branch_id='140', name='فرع الجيزة')
        cls.check_row, _ = GLSoftechCheck.objects.update_or_create(key='t_api', defaults=dict(
            label='فحص API', kind='movement', account_codes=['9902'], group_names=[], source='sales',
            sign='credit', per_party=False, blocks_close=False, tolerance=Decimal('1.00')))

    def setUp(self):
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        recon_labels._cache['at'] = 0
        self.addCleanup(recon_labels._cache.__setitem__, 'at', 0)
        self.acct = _bearer(self.acct_user)
        self.admin = _bearer(self.admin_user)
        self.figures = {}
        p = mock.patch.object(softech_checks, 'figures', side_effect=lambda source, period: self.figures)
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.object(softech_stock, 'valuation', side_effect=self._valuation)
        self.valuation = p.start()
        self.addCleanup(p.stop)
        self.jan = month_period(D(2026, 1, 1))

    def _valuation(self, as_of):
        stores = [_store('961', '1000.50', as_of)]
        return Valuation(as_of=as_of, stores=stores, total=Decimal('1000.50'))

    def draft(self, amount='100.00', day=MAR, branch=None):
        return save_draft(user=self.admin_staff, entry_date=day, description='اختبار', lines=[
            {'account_code': '9901', 'debit': Decimal(amount), 'credit': Decimal('0'),
             'branch_id': (branch or self.branch).pk},
            {'account_code': '9902', 'debit': Decimal('0'), 'credit': Decimal(amount),
             'branch_id': (branch or self.branch).pk}])

    def posted(self, amount='100.00', day=MAR, branch=None):
        return approve(self.draft(amount, day, branch).pk, user=self.admin_staff)

    def set_status(self, day, status_):
        period = month_period(day)
        FinancialPeriod.objects.filter(pk=period.pk).update(status=status_, is_closed=status_ == 'closed')
        return period

    def inline_threads(self):
        """Run the background targets in the test's thread; they must not close its connection."""
        for p in (mock.patch(f'{VIEWS}.start_thread', side_effect=_inline), mock.patch(f'{VIEWS}.connections')):
            p.start()
            self.addCleanup(p.stop)


class PeriodTests(ApiBase):
    def test_periods_list_is_months_from_january_and_creates_no_future_month(self):
        today = timezone.localdate()
        r = self.acct.get(BASE + f'periods/?year={today.year}')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([p['month'] for p in r.data], list(range(1, today.month + 1)))
        self.assertEqual(r.data[0]['status'], 'open')
        self.assertFalse(FinancialPeriod.objects.filter(year=today.year + 1, period_type='month').exists())
        self.assertEqual(self.acct.get(BASE + f'periods/?year={today.year + 1}').data, [])
        self.assertEqual(self.acct.get(BASE + 'periods/?year=2025').data, [])
        self.assertEqual(self.acct.get(BASE + 'periods/?year=abc').status_code, 400)

    def test_close_needs_finalize(self):
        with mock.patch(f'{VIEWS}.start_thread') as start:
            r = self.acct.post(BASE + f'periods/{self.jan.pk}/close/')
        self.assertEqual(r.status_code, 403)
        start.assert_not_called()
        self.jan.refresh_from_db()
        self.assertEqual(self.jan.status, 'open')

    def test_close_returns_202_and_period_shows_closing(self):
        compare.compute(self.jan)
        with mock.patch(f'{VIEWS}.start_thread') as start:
            r = self.admin.post(BASE + f'periods/{self.jan.pk}/close/')
        self.assertEqual(r.status_code, 202, r.content)
        start.assert_called_once()
        got = self.acct.get(BASE + f'periods/{self.jan.pk}/')
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.data['status'], 'closing')
        self.assertIsNotNone(got.data['closing_started_at'])
        self.assertFalse(got.data['close_stuck'])
        self.assertIsNone(got.data['last_close_failure'])

    def test_background_run_closes_the_month_and_payload_shows_the_stock(self):
        compare.compute(self.jan)
        self.inline_threads()
        self.assertEqual(self.admin.post(BASE + f'periods/{self.jan.pk}/close/').status_code, 202)
        got = self.acct.get(BASE + f'periods/{self.jan.pk}/').data
        self.assertEqual(got['status'], 'closed')
        self.assertEqual(got['closing_stock_total'], '1000.50')
        self.assertEqual(got['closed_by_name'], self.admin_staff.full_name)
        self.assertTrue(got['can_reopen'])

    def test_checklist_refusal_comes_back_on_the_post(self):
        self.draft(day=D(2026, 1, 10))
        compare.compute(self.jan)
        with mock.patch(f'{VIEWS}.start_thread') as start:
            r = self.admin.post(BASE + f'periods/{self.jan.pk}/close/')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'checklist')
        self.assertFalse({i['key']: i for i in r.data['items']}['no_drafts']['ok'])
        start.assert_not_called()

    def test_state_refusals_are_conflicts(self):
        self.set_status(JAN, 'closed')
        r = self.admin.post(BASE + f'periods/{self.jan.pk}/close/')
        self.assertEqual((r.status_code, r.data['code']), (409, 'not_open'))
        FinancialPeriod.objects.filter(pk=self.jan.pk).update(status='closing', is_closed=False,
                                                              closing_started_at=timezone.now())
        r = self.admin.post(BASE + f'periods/{self.jan.pk}/close/')
        self.assertEqual((r.status_code, r.data['code']), (409, 'close_running'))

    def test_stuck_month_is_flagged_and_the_post_takes_it_over(self):
        compare.compute(self.jan)
        FinancialPeriod.objects.filter(pk=self.jan.pk).update(
            status='closing', closing_started_at=timezone.now() - datetime.timedelta(minutes=31))
        self.assertTrue(self.acct.get(BASE + f'periods/{self.jan.pk}/').data['close_stuck'])
        with mock.patch(f'{VIEWS}.start_thread'):
            r = self.admin.post(BASE + f'periods/{self.jan.pk}/close/')
        self.assertEqual(r.status_code, 202, r.content)

    def test_failed_close_shows_a_code_and_never_the_raw_error(self):
        compare.compute(self.jan)
        self.inline_threads()
        self.valuation.side_effect = TimeoutError('sybase host 10.9.9.9 timed out')
        with self.assertLogs(LOGGER, level='ERROR'):
            self.assertEqual(self.admin.post(BASE + f'periods/{self.jan.pk}/close/').status_code, 202)
        got = self.acct.get(BASE + f'periods/{self.jan.pk}/')
        self.assertEqual(got.data['status'], 'open')
        self.assertEqual(got.data['last_close_failure']['code'], 'close_failed')
        self.assertNotIn('10.9.9.9', got.content.decode())
        self.assertNotIn('TimeoutError', got.content.decode())
        # the next attempt hides it while it runs
        with mock.patch(f'{VIEWS}.start_thread'):
            self.admin.post(BASE + f'periods/{self.jan.pk}/close/')
        self.assertIsNone(self.acct.get(BASE + f'periods/{self.jan.pk}/').data['last_close_failure'])

    def test_year_end_failure_names_the_account(self):
        now = timezone.now()
        FinancialPeriod.objects.filter(pk=self.jan.pk).update(status='closing', closing_started_at=now)
        close_service._close_failed(self.jan.pk, CloseError('year_end_account', detail={
            'account_code': '9902', 'code': 'inactive_account'}), self.admin_staff, now)
        failure = self.acct.get(BASE + f'periods/{self.jan.pk}/').data['last_close_failure']
        self.assertEqual(failure['code'], 'year_end_account')
        self.assertEqual(failure['account_code'], '9902')
        self.assertIn('9902', failure['detail'])

    def test_a_thread_that_cannot_start_returns_the_month_to_open(self):
        compare.compute(self.jan)
        self.admin.raise_request_exception = False
        with mock.patch(f'{VIEWS}.start_thread', side_effect=RuntimeError('no thread')), \
                self.assertLogs('django.request', level='ERROR'):
            r = self.admin.post(BASE + f'periods/{self.jan.pk}/close/')
        self.assertEqual(r.status_code, 500)
        self.jan.refresh_from_db()
        self.assertEqual(self.jan.status, 'open')

    def test_checklist_shape(self):
        r = self.acct.get(BASE + f'periods/{self.jan.pk}/checklist/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(set(r.data), {'period', 'items', 'can_close'})
        keys = [i['key'] for i in r.data['items']]
        self.assertIn('no_drafts', keys)
        self.assertEqual(keys[-1], 'stock_snapshot')
        self.assertEqual(set(r.data['items'][0]), {'key', 'label_ar', 'ok', 'blocking', 'detail', 'link'})
        self.assertIs(r.data['can_close'], False)   # the comparison was never computed
        compare.compute(self.jan)
        self.assertIs(self.acct.get(BASE + f'periods/{self.jan.pk}/checklist/').data['can_close'], True)

    def test_reopen_requires_reason(self):
        compare.compute(self.jan)
        self.inline_threads()
        self.admin.post(BASE + f'periods/{self.jan.pk}/close/')
        r = self.admin.post(BASE + f'periods/{self.jan.pk}/reopen/', {'reason': '  '}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (400, 'reason_required'))
        r = self.acct.post(BASE + f'periods/{self.jan.pk}/reopen/', {'reason': 'سبب'}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.admin.post(BASE + f'periods/{self.jan.pk}/reopen/', {'reason': 'مراجعة'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([m['status'] for m in r.data['months']], ['open'])
        r = self.admin.post(BASE + f'periods/{self.jan.pk}/reopen/', {'reason': 'مراجعة'}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (400, 'not_closed'))

    def test_reopen_info_lists_the_later_months_that_go_with_it(self):
        self.set_status(JAN, 'closed')
        self.set_status(D(2026, 2, 1), 'closed')
        rows = {p['month']: p for p in self.acct.get(BASE + 'periods/?year=2026').data}
        self.assertEqual(rows[1]['reopens_with'], ['2026-02'])
        self.assertEqual(rows[2]['reopens_with'], [])
        self.assertTrue(rows[1]['can_reopen'])
        self.assertFalse(rows[3]['can_reopen'])

    def test_unknown_or_non_month_period_404(self):
        self.assertEqual(self.acct.get(BASE + 'periods/987654/').status_code, 404)
        year = FinancialPeriod.objects.create(year=2026, month=0, period_type='year', period_start=D(2026, 1, 1),
                                              period_end=D(2026, 12, 31))
        self.assertEqual(self.acct.get(BASE + f'periods/{year.pk}/').status_code, 404)
        self.assertEqual(self.admin.post(BASE + f'periods/{year.pk}/close/').status_code, 404)

    def test_closing_stock_snapshot_and_preview(self):
        r = self.acct.get(BASE + f'periods/{self.jan.pk}/closing-stock/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data['snapshot'])
        r = self.acct.get(BASE + f'periods/{self.jan.pk}/closing-stock/?preview=1')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['total'], '1000.50')
        self.assertEqual(r.data['stores'][0]['branch_label'], f'961 · {BRANCH_NAME}')
        self.assertFalse(LedgerEntry.objects.filter(source_type='closing_stock').exists())
        compare.compute(self.jan)
        self.inline_threads()
        self.admin.post(BASE + f'periods/{self.jan.pk}/close/')
        r = self.acct.get(BASE + f'periods/{self.jan.pk}/closing-stock/')
        self.assertEqual(r.data['snapshot']['total'], '1000.50')
        self.assertEqual(r.data['stores'][0]['store_code'], '961')
        self.assertEqual(r.data['stores'][0]['value'], '1000.50')
        self.assertEqual(r.data['stores'][0]['branch_label'], f'961 · {BRANCH_NAME}')

    def test_preview_softech_failure_hides_the_error(self):
        self.valuation.side_effect = TimeoutError('sybase host 10.9.9.9')
        with self.assertLogs('elrezeiky.errors', level='ERROR'):
            r = self.acct.get(BASE + f'periods/{self.jan.pk}/closing-stock/?preview=1')
        self.assertEqual((r.status_code, r.data['code']), (503, 'softech_unavailable'))
        self.assertNotIn('10.9.9.9', r.content.decode())

    def test_approve_into_closing_period_409(self):
        e = self.draft()
        self.set_status(MAR, 'closing')
        r = self.acct.post(BASE + f'entries/{e.pk}/approve/')
        self.assertEqual((r.status_code, r.data['code']), (409, 'period_closing'))

    def test_non_all_branch_user_403(self):
        pharm = _bearer(make_user('gl_api_pharm', role='pharmacist')[0])
        for path in (f'periods/?year=2026', f'periods/{self.jan.pk}/', f'compare/?period={self.jan.pk}',
                     'closing-stock-stores/', 'subledgers/suppliers/?from=2026-01-01&to=2026-01-31'):
            with self.subTest(path=path):
                self.assertEqual(pharm.get(BASE + path).status_code, 403)
        self.assertEqual(pharm.post(BASE + 'corrections/', {}, format='json').status_code, 403)


class CompareTests(ApiBase):
    def test_placeholder_rows_hidden_unless_explained(self):
        compare.compute(self.jan)
        r = self.acct.get(BASE + f'compare/?period={self.jan.pk}&check=t_api')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['lines'], [])
        self.assertFalse(r.data['stale'])
        line = GLComparisonLine.objects.get(period=self.jan, softech_check=self.check_row)
        compare.explain(line.pk, user=self.acct_staff, text='لا شيء')
        self.assertEqual(len(self.acct.get(BASE + f'compare/?period={self.jan.pk}&check=t_api').data['lines']), 1)

    def test_lines_carry_server_decisions_and_labels(self):
        self.posted(day=D(2026, 1, 10))
        self.figures = {('961', ''): Decimal('60.00')}
        compare.compute(self.jan)
        row = self.acct.get(BASE + f'compare/?period={self.jan.pk}&check=t_api').data['lines'][0]
        self.assertEqual((row['ledger_amount'], row['softech_amount'], row['difference']), ('100.00', '60.00', '40.00'))
        self.assertTrue(row['needs_explanation'])
        self.assertEqual(row['branch_name'], f'961 · {BRANCH_NAME}')
        self.assertEqual(row['check_key'], 't_api')

    def test_compare_list_query_count_does_not_grow_with_lines(self):
        self.posted(day=D(2026, 1, 10))
        self.figures = {('961', ''): Decimal('60.00')}
        compare.compute(self.jan)
        url = BASE + f'compare/?period={self.jan.pk}&check=t_api'
        with self.assertNumQueries(FuzzyInt(1, 40)) as one:
            self.acct.get(url)
        self.posted(day=D(2026, 1, 11), branch=self.giza)
        self.figures = {('961', ''): Decimal('60.00'), ('140', ''): Decimal('60.00')}
        compare.compute(self.jan)
        with self.assertNumQueries(len(one.captured_queries)):
            self.acct.get(url)

    def test_refresh_is_open_to_view_and_runs_in_background(self):
        with mock.patch(f'{VIEWS}.start_thread') as start:
            r = self.acct.post(BASE + 'compare/refresh/', {'period': self.jan.pk}, format='json')
        self.assertEqual(r.status_code, 202, r.content)
        start.assert_called_once()
        self.assertFalse(GLComparisonLine.objects.filter(period=self.jan).exists())

    def test_refresh_computes_is_audited_and_reports_last_run(self):
        self.inline_threads()
        r = self.acct.post(BASE + 'compare/refresh/', {'period': self.jan.pk, 'checks': ['t_api']}, format='json')
        self.assertEqual(r.status_code, 202, r.content)
        self.assertTrue(GLComparisonLine.objects.filter(period=self.jan, softech_check=self.check_row).exists())
        row = AuditLog.objects.filter(action='gl_comparison_computed', object_id=str(self.jan.pk)).first()
        self.assertEqual(row.user_id, self.acct_staff.pk)
        refresh = self.acct.get(BASE + f'compare/?period={self.jan.pk}').data['refresh']
        self.assertFalse(refresh['running'])
        self.assertTrue(refresh['last_run']['ok'])

    def test_refresh_refused_while_another_runs(self):
        with compare.refresh_lock() as got:
            self.assertTrue(got)
            self.assertTrue(self.acct.get(BASE + f'compare/?period={self.jan.pk}').data['refresh']['running'])
            with mock.patch(f'{VIEWS}.start_thread') as start:
                r = self.acct.post(BASE + 'compare/refresh/', {'period': self.jan.pk}, format='json')
            self.assertEqual((r.status_code, r.data['code']), (409, 'compare_running'))
            start.assert_not_called()
        self.assertFalse(compare.refresh_running())

    def test_refresh_refused_on_a_closing_month(self):
        self.set_status(JAN, 'closing')
        r = self.acct.post(BASE + 'compare/refresh/', {'period': self.jan.pk}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (409, 'period_closing'))

    def test_refresh_bad_input(self):
        self.assertEqual(self.acct.post(BASE + 'compare/refresh/', {}, format='json').status_code, 400)
        self.assertEqual(self.acct.post(BASE + 'compare/refresh/', {'period': 987654}, format='json').status_code, 404)
        for checks in ('t_api', ['no_such_check'], [1]):
            r = self.acct.post(BASE + 'compare/refresh/', {'period': self.jan.pk, 'checks': checks}, format='json')
            self.assertEqual(r.status_code, 400, checks)

    def test_failed_refresh_reports_without_the_raw_error(self):
        self.inline_threads()
        with mock.patch.object(softech_checks, 'figures', side_effect=TimeoutError('host 10.9.9.9')), \
                self.assertLogs(LOGGER, level='ERROR'):
            self.acct.post(BASE + 'compare/refresh/', {'period': self.jan.pk}, format='json')
        got = self.acct.get(BASE + f'compare/?period={self.jan.pk}')
        self.assertFalse(got.data['refresh']['last_run']['ok'])
        self.assertEqual(got.data['refresh']['last_run']['code'], 'softech_unavailable')
        self.assertNotIn('10.9.9.9', got.content.decode())

    def test_line_detail(self):
        self.posted(day=D(2026, 1, 10))
        self.figures = {('961', ''): Decimal('60.00')}
        compare.compute(self.jan)
        line = GLComparisonLine.objects.get(period=self.jan, softech_check=self.check_row, branch=self.branch)
        with mock.patch.object(softech_checks, 'detail', return_value=[{'date': D(2026, 1, 10), 'amount': Decimal('60.00')}]):
            r = self.acct.get(BASE + f'compare/lines/{line.pk}/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['by_day'][0]['difference'], '40.00')
        self.assertEqual(r.data['line']['id'], line.pk)
        self.assertEqual(self.acct.get(BASE + 'compare/lines/987654/').status_code, 404)

    def test_explain_needs_approve(self):
        compare.compute(self.jan)
        line = GLComparisonLine.objects.get(period=self.jan, softech_check=self.check_row)
        r = self.acct.post(BASE + f'compare/lines/{line.pk}/explain/', {'text': ' '}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (400, 'explanation_required'))
        self.assertNotEqual(r.data['detail'], 'explanation_required')
        r = self.acct.post(BASE + f'compare/lines/{line.pk}/explain/', {'text': 'مفسّر'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['explanation'], 'مفسّر')
        RoleModuleAccess.objects.filter(role='accountant', module='ledger', action='approve').update(is_allowed=False)
        module_access.clear_cache()
        r = self.acct.post(BASE + f'compare/lines/{line.pk}/explain/', {'text': 'تاني'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_check_patch_needs_edit(self):
        r = self.acct.patch(BASE + 'compare/checks/', {'key': 't_api', 'tolerance': '5.00'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.check_row.refresh_from_db()
        self.assertEqual(self.check_row.tolerance, Decimal('1.00'))
        r = self.admin.patch(BASE + 'compare/checks/', {'key': 't_api', 'tolerance': '5.00', 'blocks_close': True},
                             format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['tolerance'], '5.00')
        self.check_row.refresh_from_db()
        self.assertTrue(self.check_row.blocks_close)
        row = AuditLog.objects.get(action='gl_softech_check_updated', object_id=str(self.check_row.pk))
        self.assertEqual(row.old_data['tolerance'], '1.00')
        self.assertEqual(row.new_data['tolerance'], '5.00')
        keys = [c['key'] for c in self.acct.get(BASE + 'compare/checks/').data]
        self.assertIn('t_api', keys)

    def test_check_patch_refuses_bad_values(self):
        for body in ({'tolerance': '-1'}, {'tolerance': '1.234'}, {'tolerance': 'x'}, {'tolerance': 'NaN'},
                     {'account_codes': ['0000']}, {'account_codes': '9901'}, {'group_names': ['لا توجد']},
                     {'account_codes': [], 'group_names': []}, {'blocks_close': 'yes'}, {'is_active': 1}):
            r = self.admin.patch(BASE + 'compare/checks/', {'key': 't_api', **body}, format='json')
            self.assertEqual(r.status_code, 400, body)
        r = self.admin.patch(BASE + 'compare/checks/', {'key': 'no_such', 'tolerance': '1'}, format='json')
        self.assertEqual(r.status_code, 404)

    def test_editing_a_checks_accounts_makes_the_comparison_stale(self):
        compare.compute(self.jan)
        self.assertFalse(compare.is_stale(self.jan))
        self.admin.patch(BASE + 'compare/checks/', {'key': 't_api', 'tolerance': '2.00'}, format='json')
        self.assertFalse(compare.is_stale(self.jan))   # a tolerance is read live: no figure moved
        self.admin.patch(BASE + 'compare/checks/', {'key': 't_api', 'account_codes': ['9901']}, format='json')
        self.assertTrue(compare.is_stale(self.jan))
        compare.compute(self.jan)
        self.assertFalse(compare.is_stale(self.jan))


class SubledgerTests(ApiBase):
    URL = BASE + 'subledgers/suppliers/?from=2026-03-01&to=2026-03-31'

    def setUp(self):
        super().setUp()
        e = save_draft(user=self.admin_staff, entry_date=MAR, description='مورد', lines=[
            {'account_code': '9901', 'debit': Decimal('50.00'), 'credit': Decimal('0'), 'branch_id': self.branch.pk},
            {'account_code': '2341', 'debit': Decimal('0'), 'credit': Decimal('50.00'), 'branch_id': self.branch.pk,
             'party_code': '501'}])
        approve(e.pk, user=self.admin_staff)

    def test_json_keeps_decimals_as_strings(self):
        r = self.acct.get(self.URL)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['rows'][0]['closing'], '50.00')
        self.assertEqual(r.data['totals']['closing'], '50.00')

    def test_unknown_kind_404_and_bad_dates_400(self):
        self.assertEqual(self.acct.get(BASE + 'subledgers/nope/?from=2026-03-01&to=2026-03-31').status_code, 404)
        self.assertEqual(self.acct.get(BASE + 'subledgers/suppliers/?from=x&to=2026-03-31').status_code, 400)

    def test_xlsx_needs_export(self):
        r = self.acct.get(self.URL + '&format=xlsx')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], XLSX)
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        self.assertTrue(wb.active.sheet_view.rightToLeft)
        RoleModuleAccess.objects.filter(role='accountant', module='ledger', action='export').update(is_allowed=False)
        module_access.clear_cache()
        self.assertEqual(self.acct.get(self.URL + '&format=xlsx').status_code, 403)
        self.assertEqual(self.acct.get(self.URL).status_code, 200)

    def test_notes_payable_export_lists_the_cheques(self):
        GLAccount.objects.create(code='2343', name='أوراق الدفع', group=GLAccount.objects.get(code='2341').group,
                                 nature='credit', account_type='liability')
        e = save_draft(user=self.admin_staff, entry_date=MAR, description='شيك', lines=[
            {'account_code': '9901', 'debit': Decimal('30.00'), 'credit': Decimal('0'), 'branch_id': self.branch.pk},
            {'account_code': '2343', 'debit': Decimal('0'), 'credit': Decimal('30.00'), 'branch_id': self.branch.pk,
             'cheque_no': 'CH-7', 'due_date': D(2026, 5, 1)}])
        approve(e.pk, user=self.admin_staff)
        r = self.acct.get(BASE + 'subledgers/notes_payable/?from=2026-03-01&to=2026-03-31&format=xlsx')
        self.assertEqual(r.status_code, 200, r.content[:200])
        cells = [c for row in openpyxl.load_workbook(io.BytesIO(r.content)).active.values for c in row]
        self.assertIn('CH-7', cells)

    def test_suppliers_vs_ap(self):
        r = self.acct.get(BASE + 'subledgers/suppliers-vs-ap/?as_of=2026-03-31')
        self.assertEqual(r.status_code, 200, r.content)
        row = next(x for x in r.data['rows'] if x['party_code'] == '501')
        self.assertEqual(row['gl_balance'], '50.00')
        self.assertIsNone(row['ap_balance'])
        r = self.acct.get(BASE + 'subledgers/suppliers-vs-ap/?as_of=2026-03-31&format=xlsx')
        self.assertEqual(r['Content-Type'], XLSX)
        self.assertEqual(self.acct.get(BASE + 'subledgers/suppliers-vs-ap/').status_code, 400)


class CorrectionBase(ApiBase):
    def lines(self, amount):
        return [{'account_code': '9901', 'debit': amount, 'credit': '0', 'branch_id': self.branch.pk},
                {'account_code': '9902', 'debit': '0', 'credit': amount, 'branch_id': self.branch.pk}]

    def closed_original(self):
        e = self.posted()
        self.set_status(MAR, 'closed')
        return e

    def exception(self, original=None, entry_id=None, lines=None, day=MAR):
        doc = GLSourceDoc.objects.create(source_type='expenses', source_key=f'k{GLSourceDoc.objects.count()}',
                                         doc_date=day, content_hash='h', status='exception', group_key='grp')
        return SourceException.objects.create(
            source_doc=doc, kind='closed_period_change', source_date=day, original_entry=original,
            proposed_lines=lines if lines is not None else self.lines('110.00'),
            detail={'group_key': 'grp', 'entry_id': entry_id, 'member_source_keys': [doc.source_key]})


class CorrectionTests(CorrectionBase):
    def test_correction_drafts_the_difference_in_the_next_open_month(self):
        e = self.closed_original()
        r = self.acct.post(BASE + 'corrections/', {'original_id': e.pk, 'lines': self.lines('110.00'),
                                                   'reason': 'سبب'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['status'], 'draft')
        self.assertEqual(r.data['entry_date'], '2026-04-01')
        self.assertEqual(r.data['total_debit'], '10.00')

    def test_correction_input_and_state_refusals(self):
        e = self.closed_original()
        ok = {'original_id': e.pk, 'lines': self.lines('110.00'), 'reason': 'سبب'}
        for body, want in (({**ok, 'reason': ' '}, 400), ({**ok, 'lines': 'x'}, 400), ({**ok, 'lines': ['x']}, 400),
                           ({**ok, 'original_id': 'x'}, 400), ({**ok, 'original_id': 987654}, 404),
                           ({**ok, 'exception_id': 'x'}, 400), ({**ok, 'reason': 'x' * 501}, 400),
                           ({**ok, 'lines': self.lines('100.00')}, 400)):
            self.assertEqual(self.acct.post(BASE + 'corrections/', body, format='json').status_code, want, body)
        self.assertEqual(self.acct.post(BASE + 'corrections/', ok, format='json').status_code, 201)
        r = self.acct.post(BASE + 'corrections/', ok, format='json')
        self.assertEqual((r.status_code, r.data['code']), (409, 'correction_pending'))

    def test_open_period_original_is_a_conflict(self):
        r = self.acct.post(BASE + 'corrections/', {'original_id': self.posted().pk, 'lines': self.lines('110.00'),
                                                   'reason': 'سبب'}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (409, 'period_open'))

    def test_from_exception_with_an_original_posts_the_correction(self):
        e = self.closed_original()
        exc = self.exception(original=e, entry_id=e.pk)
        r = self.acct.post(BASE + 'corrections/from-exception/', {'exception_id': exc.pk, 'reason': 'سبب'},
                           format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['total_debit'], '10.00')
        exc.refresh_from_db()
        self.assertEqual(exc.status, 'resolved')
        r = self.acct.post(BASE + 'corrections/from-exception/', {'exception_id': exc.pk, 'reason': 'سبب'},
                           format='json')
        self.assertEqual((r.status_code, r.data['code']), (409, 'exception_not_open'))

    def test_from_exception_without_an_original_posts_the_late_document(self):
        self.set_status(MAR, 'closed')
        exc = self.exception()
        r = self.acct.post(BASE + 'corrections/from-exception/', {'exception_id': exc.pk, 'reason': 'مستند متأخر'},
                           format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['total_debit'], '110.00')
        row = AuditLog.objects.get(action='gl_late_document_drafted', extra__exception_id=exc.pk)
        self.assertEqual(row.extra['reason'], 'مستند متأخر')

    def test_from_exception_with_a_live_draft_is_a_conflict(self):
        self.set_status(MAR, 'closed')
        draft = self.draft(day=D(2026, 4, 5))
        exc = self.exception(entry_id=draft.pk)
        r = self.acct.post(BASE + 'corrections/from-exception/', {'exception_id': exc.pk, 'reason': 'س'}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (409, 'exception_has_draft'))

    def test_from_exception_needs_a_reason_and_a_real_exception(self):
        exc = self.exception()
        r = self.acct.post(BASE + 'corrections/from-exception/', {'exception_id': exc.pk}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.acct.post(BASE + 'corrections/from-exception/', {'exception_id': 987654, 'reason': 'س'}, format='json')
        self.assertEqual(r.status_code, 404)


class ManualImportTests(ApiBase):
    ROWS = [(9901, 100, 0, 'قيد يدوي'), (9902, 0, 100, 'قيد يدوي')]
    MIXED = [(9903, 40, 0, 'قيد مختلط'), (9902, 0, 40, 'قيد مختلط')]

    def post(self, path, **data):
        return self.acct.post(BASE + path, data, format='multipart')

    def test_manual_import_rejects_non_xlsx(self):
        for path in ('manual-import/preview/', 'manual-import/'):
            r = self.post(path, file=SimpleUploadedFile('journal.xls', b'x'))
            self.assertEqual((r.status_code, r.data['code']), (400, 'bad_file'))
        self.assertEqual(self.post('manual-import/preview/').data['code'], 'no_file')
        r = self.post('manual-import/preview/', file=SimpleUploadedFile('journal.xlsx', b'not a zip'))
        self.assertEqual((r.status_code, r.data['code']), (400, 'unreadable'))

    @override_settings(MAX_UPLOAD_FILE_SIZE=10)
    def test_manual_import_rejects_an_oversized_file(self):
        r = self.post('manual-import/preview/', file=_journal(self.ROWS))
        self.assertEqual(r.status_code, 400)

    def test_preview_saves_nothing(self):
        r = self.post('manual-import/preview/', file=_journal(self.ROWS))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['counts']['manual'], 1)
        self.assertEqual(r.data['totals']['debit'], '100.00')
        self.assertFalse(LedgerEntry.objects.filter(source_type='manual_import').exists())

    def test_book_is_asked_for_or_read_from_the_file_name(self):
        r = self.post('manual-import/preview/', file=_journal(self.ROWS, book=None))
        self.assertEqual((r.status_code, r.data['code']), (400, 'book_required'))
        self.assertIn('الدفتر', r.data['detail'])
        r = self.post('manual-import/preview/', file=_journal(self.ROWS, book=None), book='cash')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.post('manual-import/preview/', file=_journal(self.ROWS, book=None, name='يومية النقدية.xlsx'))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['book'], 'cash')

    def test_import_drafts_and_audits_the_uploaded_name(self):
        r = self.post('manual-import/', file=_journal(self.ROWS, name='finance_march.xlsx'))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['imported'], 1)
        self.assertEqual(LedgerEntry.objects.filter(source_type='manual_import', status='draft').count(), 1)
        row = AuditLog.objects.filter(action='gl_manual_import').first()
        self.assertEqual(row.extra['file'], 'finance_march.xlsx')
        self.assertEqual(row.user_id, self.acct_staff.pk)

    def test_include_mixed_takes_json_or_repeated_fields(self):
        key = self.post('manual-import/preview/', file=_journal(self.MIXED)).data['groups'][0]['key']
        r = self.post('manual-import/', file=_journal(self.MIXED), include_mixed=json.dumps([key]))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['included'], 1)
        r = self.post('manual-import/', file=_journal(self.MIXED), include_mixed='{"a": 1}')
        self.assertEqual(r.status_code, 400)

    @override_settings(MAX_IMPORT_ROWS=1)
    def test_over_the_row_cap_points_at_the_command(self):
        for path in ('manual-import/preview/', 'manual-import/'):
            r = self.post(path, file=_journal(self.ROWS))
            self.assertEqual((r.status_code, r.data['code']), (400, 'too_many_rows'))
            self.assertIn('import_gl_manual_entries', r.data['detail'])


class ValidationApiTests(ApiBase):
    def post(self, client=None, **data):
        return (client or self.acct).post(BASE + 'validation/', data, format='multipart')

    def test_validation_returns_xlsx(self):
        self.posted(branch=self.giza)
        r = self.post(file=_workbook(), through='2026-08-31')
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r['Content-Type'], XLSX)
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertEqual(r['X-GL-Validation-Differences'], '2')   # 9901 against the file, 9902 against nothing
        self.assertIn('حسب الفرع', openpyxl.load_workbook(io.BytesIO(r.content)).sheetnames)

    def test_validation_needs_export(self):
        RoleModuleAccess.objects.filter(role='accountant', module='ledger', action='export').update(is_allowed=False)
        module_access.clear_cache()
        self.assertEqual(self.post(file=_workbook()).status_code, 403)

    def test_validation_bad_input(self):
        self.assertEqual(self.post().data['code'], 'no_file')
        self.assertEqual(self.post(file=SimpleUploadedFile('f.xls', b'x')).data['code'], 'bad_file')
        self.assertEqual(self.post(file=_workbook(), through='x').status_code, 400)
        self.assertEqual(self.post(file=_workbook(), through='2025-12-31').status_code, 400)
        wb = openpyxl.Workbook()
        buf = io.BytesIO()
        wb.save(buf)
        r = self.post(file=SimpleUploadedFile('f.xlsx', buf.getvalue()))
        self.assertEqual((r.status_code, r.data['code']), (400, 'sheet_not_found'))


class ClosingStockStoresTests(ApiBase):
    URL = BASE + 'closing-stock-stores/'

    def rows(self):
        return {r['store_code']: r for r in self.acct.get(self.URL).data}

    def test_get_fills_in_the_defaults(self):
        rows = self.rows()
        self.assertEqual(rows['102']['branch_code'], '100')
        self.assertTrue(rows['102']['included'])
        self.assertFalse(rows['102']['overridden'])
        self.assertEqual(rows['961']['branch_label'], f'961 · {BRANCH_NAME}')

    def test_patch_needs_edit(self):
        r = self.acct.patch(self.URL, {'stores': {'961': {'included': False}}}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(SystemSetting.objects.filter(key='gl_closing_stock_stores').exists())

    def test_patch_merges_removes_and_audits(self):
        r = self.admin.patch(self.URL, {'stores': {'961': {'included': False}, '777': {'branch': '140'}}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        rows = {x['store_code']: x for x in r.data}
        self.assertFalse(rows['961']['included'])
        self.assertTrue(rows['961']['overridden'])
        self.assertEqual(rows['777']['branch_code'], '140')
        self.assertFalse(softech_stock.store_map()['961'].included)
        row = AuditLog.objects.get(action='gl_closing_stock_stores_updated')
        self.assertEqual(row.old_data, {'stores': {}})
        self.assertEqual(row.new_data['stores']['777'], {'branch': '140'})
        r = self.admin.patch(self.URL, {'stores': {'961': None}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(SystemSetting.get('gl_closing_stock_stores'), {'777': {'branch': '140'}})

    def test_patch_refuses_what_the_reader_would_drop(self):
        for stores in ('x', {}, {'961': 'x'}, {'961': {}}, {'961': {'other': 1}}, {'961': {'included': 'no'}},
                       {'961': {'included': None}}, {'961': {'branch': ' '}}, {'961': {'branch': '999'}},
                       {' ': {'included': True}}, {'12345678901': {'included': True}}):
            r = self.admin.patch(self.URL, {'stores': stores}, format='json')
            self.assertEqual(r.status_code, 400, stores)
        self.assertFalse(SystemSetting.objects.filter(key='gl_closing_stock_stores').exists())


def _broken(upload):
    """The same workbook with its sheets' XML cut short: it opens, and fails when a sheet is read."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(upload.read())) as src, zipfile.ZipFile(out, 'w') as dst:
        for name in src.namelist():
            data = src.read(name)
            dst.writestr(name, data[:len(data) // 2] if name.startswith('xl/worksheets/') else data)
    return SimpleUploadedFile(upload.name, out.getvalue(), content_type=XLSX)


class FixRoundTests(ApiBase):
    """Read errors only become `unreadable`; everything else is a logged 500. Row cap on validation."""
    ROWS = ManualImportTests.ROWS

    def multipart(self, path, **data):
        return self.acct.post(BASE + path, data, format='multipart')

    @override_settings(MAX_IMPORT_ROWS=1)
    def test_validation_over_the_row_cap_points_at_the_command(self):
        r = self.multipart('validation/', file=_workbook())
        self.assertEqual((r.status_code, r.data['code']), (400, 'too_many_rows'))
        self.assertIn('gl_validate_workbook', r.data['detail'])

    def test_a_sheet_that_fails_to_read_is_unreadable(self):
        r = self.multipart('manual-import/preview/', file=_broken(_journal(self.ROWS)))
        self.assertEqual((r.status_code, r.data['code']), (400, 'unreadable'))
        r = self.multipart('manual-import/', file=_broken(_journal(self.ROWS)))
        self.assertEqual((r.status_code, r.data['code']), (400, 'unreadable'))
        r = self.multipart('validation/', file=_broken(_workbook()))
        self.assertEqual((r.status_code, r.data['code']), (400, 'unreadable'))
        r = self.multipart('validation/', file=SimpleUploadedFile('f.xlsx', b'not a zip'))
        self.assertEqual((r.status_code, r.data['code']), (400, 'unreadable'))

    def _is_logged_500(self, patcher, path, upload):
        self.acct.raise_request_exception = False
        with patcher, self.assertLogs('django.request', level='ERROR'):
            r = self.multipart(path, file=upload)
        self.assertEqual(r.status_code, 500)
        self.assertNotIn(b'unreadable', r.content)

    def test_a_bug_mid_import_is_a_logged_500_not_an_unreadable_file(self):
        for bug in (KeyError('bug'), ValueError('bug')):
            with self.subTest(bug=bug):
                self._is_logged_500(mock.patch('apps.finance.gl.manual_import.save_draft', side_effect=bug),
                                    'manual-import/', _journal(self.ROWS))

    def test_a_bug_in_validation_is_a_logged_500_not_an_unreadable_file(self):
        for bug in (KeyError('bug'), ValueError('bug')):
            with self.subTest(bug=bug):
                self._is_logged_500(mock.patch('apps.finance.gl.validation._ytd', side_effect=bug),
                                    'validation/', _workbook())

    def test_validation_reports_the_differences_total(self):
        self.posted(branch=self.giza)
        r = self.multipart('validation/', file=_workbook())
        self.assertEqual(r.status_code, 200, r.content[:200])
        self.assertEqual(r['X-GL-Validation-Difference-Total'], '130.00')   # 100 - 70 on 9901, 100 on 9902
        self.assertIn('X-GL-Validation-Difference-Total', r['Access-Control-Expose-Headers'])

    def test_include_mixed_sent_as_a_file_is_refused(self):
        r = self.multipart('manual-import/', file=_journal(self.ROWS),
                           include_mixed=SimpleUploadedFile('keys.txt', b'x'))
        self.assertEqual(r.status_code, 400)

    def test_snapshot_labels_its_missing_stores_by_branch(self):
        hq = Branch.objects.filter(softech_branch_id='100').first() or Branch.objects.create(
            softech_branch_id='100', name='الرئيسي')
        compare.compute(self.jan)
        self.inline_threads()
        self.admin.post(BASE + f'periods/{self.jan.pk}/close/')
        snapshot = FinancialPeriod.objects.get(pk=self.jan.pk).closing_stock
        ClosingStockSnapshot.objects.filter(pk=snapshot.pk).update(missing_stores=['102'])
        recon_labels._cache['at'] = 0
        got = self.acct.get(BASE + f'periods/{self.jan.pk}/closing-stock/').data['snapshot']['missing_stores']
        self.assertEqual(got[0]['store_code'], '102')
        self.assertEqual(got[0]['branch_label'], f'100 · {hq.name_ar or hq.name}')

    def test_refresh_period_must_be_a_real_id(self):
        r = self.acct.post(BASE + 'compare/refresh/', {'period': True}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_refresh_of_a_closed_month_is_accepted(self):
        self.set_status(JAN, 'closed')
        with mock.patch(f'{VIEWS}.start_thread') as start:
            r = self.acct.post(BASE + 'compare/refresh/', {'period': self.jan.pk}, format='json')
        self.assertEqual(r.status_code, 202, r.content)
        start.assert_called_once()

    def test_refresh_that_loses_the_race_records_it(self):
        with mock.patch.object(compare, 'refresh', side_effect=compare.RefreshBusy()):
            close_views._run_refresh(self.jan, None, self.acct_staff)
        last = self.acct.get(BASE + f'compare/?period={self.jan.pk}').data['refresh']['last_run']
        self.assertEqual((last['ok'], last['code']), (False, 'compare_running'))
        self.assertTrue(last['detail'])


class FromExceptionFixTests(CorrectionBase):
    def _deleted_draft_id(self):
        draft = self.draft(day=D(2026, 4, 5))
        pk = draft.pk
        draft.delete()
        return pk

    def _post(self, exc):
        return self.acct.post(BASE + 'corrections/from-exception/', {'exception_id': exc.pk, 'reason': 'س'},
                              format='json')

    def test_a_deleted_draft_lets_the_correction_through(self):
        e = self.closed_original()
        r = self._post(self.exception(original=e, entry_id=self._deleted_draft_id()))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['total_debit'], '10.00')

    def test_a_deleted_draft_lets_the_late_document_through(self):
        self.set_status(MAR, 'closed')
        r = self._post(self.exception(entry_id=self._deleted_draft_id()))
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['total_debit'], '110.00')

    def test_the_correction_uses_the_lines_read_under_the_lock(self):
        e = self.closed_original()
        exc = self.exception(original=e, entry_id=e.pk)
        real = plan2_adapter.closed_period_change

        def rewritten_after_the_views_read(pk, **kw):
            change = real(pk, **kw)
            if not kw.get('for_update'):   # the engine rewrites the group right after the view has read it
                SourceException.objects.filter(pk=pk).update(proposed_lines=self.lines('120.00'))
            return change
        with mock.patch.object(plan2_adapter, 'closed_period_change', side_effect=rewritten_after_the_views_read):
            r = self._post(exc)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['total_debit'], '20.00')


class FuzzyInt(int):
    """assertNumQueries bound: equal to anything in [low, high]."""

    def __new__(cls, low, high):
        obj = super().__new__(cls, high)
        obj.low, obj.high = low, high
        return obj

    def __eq__(self, other):
        return self.low <= other <= self.high

    __hash__ = int.__hash__
