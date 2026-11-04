"""Plan 2 / Task 7: seed rules and maps, freshness domain, scheduler window, draft-now endpoints."""
import datetime
from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.finance.gl import drafting, rules as R, seed
from apps.finance.models import (
    FinancialPeriod, GLAccount, GLAccountGroup, GLDraftRun, GLSourceMap, PostingRule,
)
from apps.sync import tasks
from apps.sync.freshness import get_freshness
from apps.tests.factories import make_user

BASE = '/api/finance/gl/'
D = datetime.date


def _all_codes():
    codes = set()
    for r in seed.RULES:
        codes.update(seed._rule_accounts(r))
    codes.update(a for _, a, _, _ in seed.BANK_MAPS)
    codes.update(a for _, a in seed.EXPENSE_MAPS)
    return sorted(codes)


def _make_accounts(codes):
    g, _ = GLAccountGroup.objects.get_or_create(name='seed-g', section='balance_sheet')
    for c in codes:
        party = {'1341': 'customer', '2341': 'supplier'}.get(c, 'none')
        GLAccount.objects.get_or_create(
            code=c, defaults=dict(name=c, group=g, nature='debit', account_type='asset',
                                  party_type=party))


def _make_branches():
    for code in ('100', '130', '140', '150', '160', '170'):
        Branch.objects.get_or_create(softech_branch_id=code, defaults={'name': f'b{code}'})


class SeedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _make_accounts(_all_codes())
        _make_branches()
        cls.user = drafting.system_user()

    def test_seed_rules_all_validate(self):
        res = seed.seed_gl_drafting(user=self.user)
        self.assertEqual(res['skipped'], [])
        self.assertEqual(len(res['rules_created']), len(seed.RULES))
        self.assertEqual(len(res['maps_created']), len(seed.BANK_MAPS) + len(seed.EXPENSE_MAPS))
        for rule in PostingRule.objects.all():
            self.assertEqual(R.validate_rule(rule.source_type, rule.conditions, rule.lines,
                                             rule.action), [], rule.code)
        m = GLSourceMap.objects.get(kind='bank', source_value='40')
        self.assertEqual((m.account.code, m.branch.softech_branch_id), ('1302', '130'))
        self.assertEqual(GLSourceMap.objects.get(kind='bank', source_value='10').branch.softech_branch_id,
                         '100')

    def test_seed_is_idempotent_and_keeps_finance_edits(self):
        seed.seed_gl_drafting(user=self.user)
        v1 = PostingRule.objects.get(code='sales.cash', version=1)
        R.save_rule(user=self.user, code='sales.cash', source_type=v1.source_type,
                    effective_from=D(2026, 6, 1), conditions=v1.conditions, lines=v1.lines,
                    granularity=v1.granularity, book=v1.book, description='edited')
        bank = GLSourceMap.objects.get(kind='bank', source_value='40')
        R.save_map(user=self.user, kind='bank', source_value='40', account_code='1301',
                   branch_id=bank.branch_id)
        res = seed.seed_gl_drafting(user=self.user)
        self.assertEqual(res['rules_created'], [])
        self.assertEqual(res['maps_created'], [])
        self.assertEqual(PostingRule.objects.filter(code='sales.cash').count(), 2)
        self.assertEqual(PostingRule.objects.filter(code='sales.cash').order_by('-version').first().version, 2)
        self.assertEqual(GLSourceMap.objects.get(kind='bank', source_value='40').account.code, '1301')

    def test_missing_accounts_and_branches_are_reported_not_raised(self):
        GLAccount.objects.filter(code='6006').delete()      # sales.card
        GLAccount.objects.filter(code='1316').delete()      # bank map 01
        Branch.objects.filter(softech_branch_id='150').delete()   # bank map 60
        res = seed.seed_gl_drafting(user=self.user)
        skipped = {(s['what'], s['code']): s for s in res['skipped']}
        self.assertEqual(skipped[('rule', 'sales.card')]['accounts'], ['6006'])
        self.assertEqual(skipped[('map', 'bank:01')]['reason'], 'missing_account')
        self.assertEqual(skipped[('map', 'bank:60')]['reason'], 'missing_branch')
        self.assertFalse(PostingRule.objects.filter(code='sales.card').exists())
        # a later run (account now present) fills the gap
        _make_accounts(['6006'])
        res2 = seed.seed_gl_drafting(user=self.user)
        self.assertIn('sales.card', res2['rules_created'])

    def test_empty_chart_skips_everything_without_error(self):
        GLAccount.objects.all().delete()
        res = seed.seed_gl_drafting(user=self.user)
        # only rules with no static account (skip / all-mapped) can be created
        self.assertEqual(sorted(res['rules_created']), ['expenses.box', 'purchases.branch'])
        self.assertEqual(res['maps_created'], [])
        self.assertTrue(res['skipped'])

    def test_supplier_cash_debit_lands_on_the_box_branch(self):
        from decimal import Decimal
        from apps.finance.gl.sources import SourceDoc
        seed.seed_gl_drafting(user=self.user)
        rule = PostingRule.objects.get(code='supplier.cash')
        d = SourceDoc('supplier_payments', 'chq:100:1', D(2026, 3, 10), '100', '', '',
                      {'amount': Decimal('50')},
                      {'bankcode': '40', 'financialdoc': '10', 'direction': 'payment'})
        hq = Branch.objects.get(softech_branch_id='100').pk
        lines = R.build_lines(rule, [d], hq_branch_id=hq)
        by = {l['account_code']: l for l in lines}
        b130 = Branch.objects.get(softech_branch_id='130').pk
        self.assertEqual(by['5100']['branch_id'], b130)
        self.assertEqual(by['1302']['branch_id'], b130)

    def test_management_command(self):
        call_command('seed_gl_drafting', verbosity=0)
        self.assertTrue(PostingRule.objects.filter(code='sales.credit').exists())


class FreshnessTests(TestCase):
    def test_freshness_domain_reads_last_run(self):
        out = get_freshness(['gl_drafting'])['domains']['gl_drafting']
        self.assertIsNone(out['last_success_at'])
        now = timezone.now()
        GLDraftRun.objects.create(status='partial', date_from=D(2026, 3, 1), date_to=D(2026, 3, 2),
                                  finished_at=now)
        out = get_freshness(['gl_drafting'])['domains']['gl_drafting']
        self.assertIsNotNone(out['last_success_at'])
        self.assertFalse(out['last_run_failed'])
        GLDraftRun.objects.create(status='failed', date_from=D(2026, 3, 1), date_to=D(2026, 3, 2),
                                  finished_at=now)
        out = get_freshness(['gl_drafting'])['domains']['gl_drafting']
        self.assertTrue(out['last_run_failed'])
        self.assertIsNotNone(out['last_success_at'])


class SchedulerTests(TestCase):
    def test_registered_at_0830(self):
        from .test_scheduler_jobs import _FakeScheduler
        captured = {}

        class _Capture(_FakeScheduler):
            def add_job(self, func, trigger, *args, **kwargs):
                captured[kwargs.get('id')] = kwargs
                super().add_job(func, trigger, *args, **kwargs)

        with mock.patch.object(tasks, 'BackgroundScheduler', _Capture), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
        job = captured['gl_drafting']
        self.assertEqual((job['hour'], job['minute']), (8, 30))
        self.assertEqual(job['max_instances'], 1)

    def test_scheduler_window_starts_at_earliest_open_month(self):
        today = D(2026, 11, 4)
        self.assertEqual(tasks._gl_drafting_window(today), (D(2026, 10, 1), D(2026, 11, 3)))
        FinancialPeriod.objects.create(year=2026, month=10, period_type='month', status='closed',
                                       is_closed=True, period_start=D(2026, 10, 1),
                                       period_end=D(2026, 10, 31))
        self.assertEqual(tasks._gl_drafting_window(today), (D(2026, 11, 1), D(2026, 11, 3)))

    def test_job_uses_scheduler_trigger_and_survives_busy(self):
        with mock.patch.object(tasks, '_gl_drafting_window', return_value=(D(2026, 10, 1), D(2026, 11, 3))), \
             mock.patch.object(drafting, 'draft_range') as dr:
            tasks._run_gl_drafting()
        self.assertEqual(GLDraftRun.objects.get().triggered_by, 'scheduler')
        dr.assert_called_once()
        # the first run is still 'running' -> the second call hits DraftBusy and returns quietly
        with mock.patch.object(tasks, '_gl_drafting_window', return_value=(D(2026, 10, 1), D(2026, 11, 3))), \
             mock.patch.object(drafting, 'draft_range') as dr2:
            self.assertIsNone(tasks._run_gl_drafting())
        dr2.assert_not_called()


class RunEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)

    def setUp(self):
        _, _, self.acct = make_user('gs_acct', role='accountant')
        _, _, self.viewer = make_user('gs_viewer', role='viewer', access_all=True)
        _, _, self.pharm = make_user('gs_pharm', role='pharmacist')
        self.body = {'date_from': '2026-03-01', 'date_to': '2026-03-31'}

    def test_run_endpoint_202_then_409_while_running(self):
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            r = self.acct.post(BASE + 'drafting/run/', self.body, format='json')
            self.assertEqual(r.status_code, 202, r.content)
            run = GLDraftRun.objects.get(pk=r.data['run_id'])
            self.assertEqual((run.status, run.date_from, run.date_to), ('running', D(2026, 3, 1), D(2026, 3, 31)))
            self.assertTrue(run.triggered_by.startswith('user:'))
            st.assert_called_once()
            r2 = self.acct.post(BASE + 'drafting/run/', self.body, format='json')
            self.assertEqual(r2.status_code, 409)
            self.assertEqual(st.call_count, 1)

    def test_run_endpoint_background_target_runs_the_engine(self):
        with mock.patch('apps.finance.gl.drafting_views.start_thread') as st:
            r = self.acct.post(BASE + 'drafting/run/', {**self.body, 'source_types': ['expenses']},
                               format='json')
        target, kw = st.call_args.args[0], st.call_args.kwargs
        with mock.patch.object(drafting, 'draft_range') as dr:
            target(*kw['args'])
        self.assertEqual(dr.call_args.kwargs['source_types'], ['expenses'])
        self.assertEqual(dr.call_args.kwargs['run'].pk, r.data['run_id'])

    def test_run_endpoint_validates_input(self):
        for body in ({}, {'date_from': 'x', 'date_to': '2026-01-01'},
                     {'date_from': '2026-03-05', 'date_to': '2026-03-01'},
                     {**self.body, 'source_types': ['nope']}):
            self.assertEqual(self.acct.post(BASE + 'drafting/run/', body, format='json').status_code, 400, body)
        self.assertFalse(GLDraftRun.objects.exists())

    def test_run_endpoint_needs_ledger_create(self):
        with mock.patch('apps.finance.gl.drafting_views.start_thread'):
            self.assertEqual(self.viewer.post(BASE + 'drafting/run/', self.body, format='json').status_code, 403)
            self.assertEqual(self.pharm.post(BASE + 'drafting/run/', self.body, format='json').status_code, 403)
        self.assertFalse(GLDraftRun.objects.exists())

    def test_runs_list_and_detail(self):
        run = GLDraftRun.objects.create(status='success', date_from=D(2026, 3, 1), date_to=D(2026, 3, 2),
                                        counts={'drafted': 3})
        r = self.acct.get(BASE + 'drafting/runs/?limit=5')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['results'][0]['counts'], {'drafted': 3})
        self.assertEqual(self.acct.get(f'{BASE}drafting/runs/{run.pk}/').data['status'], 'success')
        self.assertEqual(self.acct.get(f'{BASE}drafting/runs/999999/').status_code, 404)
        self.assertEqual(self.pharm.get(BASE + 'drafting/runs/').status_code, 403)
