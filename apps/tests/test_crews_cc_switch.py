"""Crews piece 2b Part B, Task 5: the one-shot switch of the call center from the fake CC branch to
the crew (apps/crews/cc_switch.py + migrate_call_center_to_crew).

Per month x metric: the crew value when it can be computed (source 'crew'), otherwise the stored CC
value (source 'stored'); CC rows are re-pointed in place (ids survive); targets and forecasts move
to the crew; the CC branch is closed; every step audited; a re-run is a no-op.
SOFTECH and the CDR are always mocked.
"""
import io
import json
import os
import tempfile
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.catalog.models import Category, Item
from apps.crews import cc_seed
from apps.crews.cc_legacy import LEGACY_CC_KEY
from apps.crews import cc_switch as S
from apps.crews.models import Crew
from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.forecasting.models import (CallCenterConfig, ForecastResult, ForecastScenario,
                                     KpiActualRollup as K)
from apps.incentives.models import SalesTarget

JUNE = (2026, 6)
TODAY = date(2026, 6, 25)          # the current month = June: one planned month
NO_RET = {'amount': Decimal('0'), 'profit': Decimal('0'), 'docs': 0}
RET_PATH = 'apps.crews.softech_returns.returns_for_codes'


def _when(d):
    return timezone.make_aware(datetime(d.year, d.month, d.day, 12, 0))


def _cdr(day, src, mobile):
    return {'calldate': f'{day} 10:00:00', 'src': src, 'dst': '82' + mobile,
            'disposition': 'ANSWERED'}


CDR = [_cdr('2026-06-02', '10', '01000000001'), _cdr('2026-06-03', '12', '01000000002'),
       _cdr('2026-06-04', '15', '01000000003'), _cdr('2026-06-05', '11', '01000000004')]


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cfg = CallCenterConfig.get_solo()
        cfg.sales_agent_usercodes = ['62', '63']
        cfg.call_agent_extensions = ['10', '12', '15']
        cfg.save()
        cls.cc = Branch.objects.create(softech_branch_id=LEGACY_CC_KEY, code='CCX',
                                       name='Call Center', name_ar='الكول سنتر',
                                       is_operational=False, kind=Branch.KIND_CALL_CENTER)
        cls.b1 = Branch.objects.create(softech_branch_id='983', code='983', name='B1', name_ar='فرع ١')
        cust = Customer.objects.create(name='ع', softech_pic='PICSW', softech_id='C-SW')
        cat = Category.objects.create(softech_id='CAT-SW', name='c')
        med = Item.objects.create(softech_id='SWMED', name='دواء', medicine_type='10', category=cat)
        for i, (user, day, total, cost, phc) in enumerate([
                ('62', date(2026, 6, 3), 1000, 600, 'P1'), ('63', date(2026, 6, 10), 300, 100, 'P2'),
                ('99', date(2026, 6, 21), 700, 200, 'P9')]):
            ph = PurchaseHistory.objects.create(
                customer=cust, softech_invoice_id=f'SW-{i}', branch=cls.b1, doc_code='115',
                total_amount=Decimal(total), invoice_date=_when(day), softech_user=user,
                softech_phcode=phc, sales_channel='91', sales_person_type='10')
            PurchaseHistoryLine.objects.create(
                purchase=ph, item=med, quantity=Decimal(1), unit_price=Decimal(total),
                line_total=Decimal(total), cost_at_sale=Decimal(cost))

    def store(self, **values):
        """CC rollup rows for June (metric=value)."""
        return {m: K.objects.create(branch=self.cc, year=2026, month=6, metric=m, value=Decimal(v))
                for m, v in values.items()}

    def plan(self, cdr=None, ret=NO_RET, **kw):
        cdr = {JUNE: CDR} if cdr is None else cdr
        side = {'side_effect': ret} if isinstance(ret, Exception) else {'return_value': ret}
        with mock.patch(RET_PATH, **side):
            return S.plan_switch(cdr_rows_by_month=cdr, today=TODAY, **kw)

    def apply(self, months, cdr=None, ret=NO_RET):
        cdr = {JUNE: CDR} if cdr is None else cdr
        with mock.patch(RET_PATH, return_value=ret):
            return S.apply_switch(None, confirm_months=months, cdr_rows_by_month=cdr, today=TODAY)

    @staticmethod
    def cell(plan, metric, ym=JUNE):
        month = [m for m in plan['months'] if (m['year'], m['month']) == ym]
        assert len(month) == 1, plan['months']
        found = [r for r in month[0]['metrics'] if r['metric'] == metric]
        return found[0] if found else None


class PlanTests(_Base):
    def test_plan_writes_nothing_and_seeds_only_in_rollback(self):
        self.store(cash_delivery=1234, cash=50, call_count=99)
        n_audit = AuditLog.objects.count()
        p = self.plan()
        self.assertEqual(Crew.objects.count(), 0)                     # seed rolled back
        self.assertEqual(AuditLog.objects.count(), n_audit)
        self.assertEqual(K.objects.filter(branch=self.cc).count(), 3)
        self.assertTrue(p['seeds_crew'])
        self.assertEqual(p['month_count'], 1)
        self.assertFalse(p['nothing_to_move'])

    def test_sources_per_metric(self):
        self.store(cash_delivery=1234, cash=50, call_count=99)
        p = self.plan()
        cd = self.cell(p, 'cash_delivery')
        self.assertEqual((cd['stored'], cd['new'], cd['source']), ('1234.00', '1300.00', 'crew'))
        cash = self.cell(p, 'cash')                                    # not a crew metric
        self.assertEqual((cash['stored'], cash['new'], cash['source']), ('50.00', '50.00', 'stored'))
        calls = self.cell(p, 'call_count')
        self.assertEqual((calls['new'], calls['source']), ('3.00', 'crew'))
        pics = self.cell(p, 'pic_count')                               # no CC row → created
        self.assertEqual((pics['stored'], pics['new'], pics['source'], pics['action']),
                         (None, '2.00', 'crew', 'create'))

    def test_cdr_unavailable_keeps_stored_call_count(self):
        self.store(call_count=99)
        p = self.plan(cdr={})
        calls = self.cell(p, 'call_count')
        self.assertEqual((calls['new'], calls['source']), ('99.00', 'stored'))

    def test_returns_unreachable_keeps_stored_money(self):
        self.store(cash_delivery=1234, gross_profit=10, beauty=7)
        p = self.plan(ret=RuntimeError('down'))
        self.assertEqual(self.cell(p, 'cash_delivery')['source'], 'stored')
        self.assertEqual(self.cell(p, 'gross_profit')['new'], '10.00')
        self.assertEqual(self.cell(p, 'beauty')['source'], 'crew')

    def test_targets_and_forecasts_listed(self):
        self.store(cash_delivery=1000)
        t = SalesTarget.objects.create(scope_type=SalesTarget.SCOPE_BRANCH, branch=self.cc,
                                       metric='cash_delivery', period_start=date(2026, 6, 1),
                                       period_end=date(2026, 6, 30), target_value=2000)
        sc = ForecastScenario.objects.create(name='s', year=2026, month=7)
        ForecastResult.objects.create(scenario=sc, branch=self.cc, scope_key='x', metric='beauty')
        p = self.plan(focus_month=JUNE)
        row = p['targets'][0]
        self.assertEqual((row['id'], row['achieved_before'], row['achieved_after']),
                         (t.pk, '1000.00', '1300.00'))
        self.assertEqual((row['pct_before'], row['pct_after']), (50.0, 65.0))
        self.assertEqual(p['focus_targets'], [t.pk])
        self.assertEqual(p['forecast_count'], 1)
        self.assertEqual(p['branch'], {'id': self.cc.pk, 'kind_before': 'call_center',
                                       'kind_after': 'closed'})


class ApplyTests(_Base):
    def test_confirm_months_must_match(self):
        self.store(cash_delivery=1234)
        with self.assertRaises(S.SwitchRefused):
            self.apply(months=2)
        with self.assertRaises(S.SwitchRefused):
            self.apply(months=None)
        self.assertEqual(Crew.objects.count(), 0)
        self.assertEqual(K.objects.filter(branch=self.cc).count(), 1)

    def test_apply_moves_everything_and_audits(self):
        rows = self.store(cash_delivery=1234, cash=50, call_count=99)
        t = SalesTarget.objects.create(scope_type=SalesTarget.SCOPE_BRANCH, branch=self.cc,
                                       metric='call_count', period_start=date(2026, 6, 1),
                                       period_end=date(2026, 6, 30), target_value=10)
        sc = ForecastScenario.objects.create(name='s', year=2026, month=7)
        f = ForecastResult.objects.create(scenario=sc, branch=self.cc, scope_key='x', metric='beauty')
        self.apply(months=1)
        crew = Crew.objects.get(name=cc_seed.CC_CREW_NAME)
        self.assertEqual(K.objects.filter(branch=self.cc).count(), 0)
        moved = K.objects.get(pk=rows['cash_delivery'].pk)              # id survives
        self.assertEqual((moved.branch_id, moved.crew_id, moved.value), (None, crew.pk, Decimal('1300')))
        self.assertEqual(K.objects.get(pk=rows['cash'].pk).value, Decimal('50'))
        self.assertEqual(K.objects.get(crew=crew, year=2026, month=6, metric='pic_count').value, 2)
        t.refresh_from_db()
        self.assertEqual((t.scope_type, t.crew_id, t.branch_id), ('crew', crew.pk, None))
        self.assertEqual(t.actual_value(), 3.0)
        f.refresh_from_db()
        self.assertEqual((f.crew_id, f.branch_id, f.scope_key), (crew.pk, None, f'crew:{crew.pk}'))
        self.cc.refresh_from_db()
        self.assertEqual(self.cc.kind, Branch.KIND_CLOSED)
        a = AuditLog.objects.get(action='cc_crew_history_rebuilt')
        self.assertEqual(a.old_data['cash_delivery'], '1234.00')
        self.assertEqual(a.new_data['cash_delivery'], '1300.00')
        self.assertEqual((a.extra['year'], a.extra['month']), (2026, 6))
        self.assertEqual(a.extra['source']['cash'], 'stored')
        self.assertEqual(a.extra['source']['call_count'], 'crew')
        for action in ('cc_targets_moved_to_crew', 'cc_forecasts_moved_to_crew', 'crew_cc_seeded'):
            self.assertTrue(AuditLog.objects.filter(action=action).exists(), action)
        closed = AuditLog.objects.get(action='cc_branch_closed')
        self.assertEqual((closed.old_data['kind'], closed.new_data['kind']), ('call_center', 'closed'))

    def test_existing_crew_row_replaces_cc_row(self):
        self.store(cash_delivery=1234)
        crew = Crew.objects.get(pk=cc_seed.seed()['crew_id'])
        kept = K.objects.create(crew=crew, year=2026, month=6, metric='cash_delivery', value=5)
        self.apply(months=1)
        kept.refresh_from_db()
        self.assertEqual(kept.value, Decimal('1300'))
        self.assertEqual(K.objects.filter(crew=crew, year=2026, month=6,
                                          metric='cash_delivery').count(), 1)
        a = AuditLog.objects.get(action='cc_crew_history_rebuilt')
        self.assertEqual(a.extra['replaced_crew_rows'], {'cash_delivery': kept.pk})

    def test_rerun_is_noop(self):
        self.store(cash_delivery=1234, call_count=99)
        self.apply(months=1)
        n_audit, n_rows = AuditLog.objects.count(), K.objects.count()
        p = self.plan()
        self.assertEqual((p['month_count'], p['nothing_to_move']), (0, True))
        self.apply(months=0)
        self.assertEqual((AuditLog.objects.count(), K.objects.count()), (n_audit, n_rows))

    def test_chain_call_count_counts_crew_once(self):
        self.store(call_count=99)
        self.apply(months=1)
        t = SalesTarget.objects.create(scope_type=SalesTarget.SCOPE_CHAIN, metric='call_count',
                                       period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                                       target_value=10)
        self.assertEqual(t.actual_value(), 3.0)


class CommandTests(_Base):
    def run_cmd(self, *args):
        out = io.StringIO()
        # never the live PBX: the command's CDR is "not configured" here
        with mock.patch(RET_PATH, return_value=NO_RET),                 mock.patch('apps.crews.cc_comparison.cdr_configured', return_value=False),                 mock.patch('apps.crews.kpi.cdr_configured', return_value=False):
            call_command('migrate_call_center_to_crew', *args, stdout=out)
        return out.getvalue()

    def test_dry_run_apply_and_second_dry_run(self):
        self.store(cash_delivery=1234, call_count=99)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'plan.json')
            out = self.run_cmd('--out', path)
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
        self.assertIn('1234.00 → ', out)
        self.assertIn('(stored)', out)                                 # CDR not configured here
        n = data['month_count']
        self.assertGreaterEqual(n, 1)
        with self.assertRaises(CommandError):
            self.run_cmd('--apply')
        with self.assertRaises(CommandError):
            self.run_cmd('--apply', '--confirm-months', str(n + 1))
        self.assertEqual(K.objects.filter(branch=self.cc).count(), 2)
        self.run_cmd('--apply', '--confirm-months', str(n))
        self.assertEqual(K.objects.filter(branch=self.cc).count(), 0)
        again = self.run_cmd()
        self.assertIn('nothing to move', again)
        self.assertIn('0 month', again)
