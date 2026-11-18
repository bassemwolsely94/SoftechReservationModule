"""Crews piece 2b Part B, Task 3: every call-center reader reads the call-center crew.

The KPI board block, SalesTarget.actual_value (owner ruling D: the board's rollup figure), the
forecast engine member, references, the target workbook, rollup refresh, backtest, PIC calls and
insights read call_center_crew() — its KpiActualRollup rows (crew set, branch NULL) and its
members' dated seller codes — never the fake «CC» branch. Review Focus 2 (chain call_count sums
crew rows once), 3 (a call-center / closed branch never shows in branch lists) and 5 (refresh
rebuilds the crew month when sales sync after its build).
"""
import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.crews.models import Crew, CrewManualMember
from apps.forecasting import call_center as CCM
from apps.forecasting.models import ForecastResult, ForecastScenario, KpiActualRollup as K
from apps.incentives.models import SalesTarget

SEED = date(2024, 8, 1)


def _aware(y, m, d, h=12):
    return timezone.make_aware(datetime(y, m, d, h, 0))


def _crew(name='الكول سنتر', codes=('62',), exts=(), frm=SEED, to=None, type_='call_center'):
    c = Crew.objects.create(name=name, type=type_)
    for code in codes:
        CrewManualMember.objects.create(crew=c, mode='include', softech_usercode=code,
                                        valid_from=frm, valid_to=to, reason='t')
    for ext in exts:
        CrewManualMember.objects.create(crew=c, mode='include', pbx_extension=ext,
                                        valid_from=frm, valid_to=to, reason='t')
    return c


def _roll(y, m, metric, value, *, crew=None, branch=None):
    return K.objects.create(crew=crew, branch=branch, year=y, month=m, metric=metric,
                            value=Decimal(str(value)))


def _legacy_cc(kind=Branch.KIND_CALL_CENTER):
    # the legacy fake branch, planted only to prove nothing reads it any more
    return Branch.objects.create(softech_branch_id='C' + 'C', code='C' + 'C', name='Call Center',
                                 is_operational=False, kind=kind)


class CallCenterCrewLookupTests(TestCase):
    def test_none_without_a_live_call_center_crew(self):
        _crew(name='وظيفي', type_='job')
        self.assertIsNone(CCM.call_center_crew())
        self.assertEqual(CCM.call_center_seller_codes(date(2026, 6, 1), date(2026, 6, 30)), [])

    def test_lowest_id_live_call_center_crew(self):
        archived = _crew(name='قديم')
        archived.is_archived = True
        archived.save()
        first = _crew(name='كول 1')
        _crew(name='كول 2')
        self.assertEqual(CCM.call_center_crew(), first)
        self.assertEqual(CCM.call_center_crew_ids(), [first.pk, first.pk + 1])

    def test_seller_codes_dated_to_the_period(self):
        c = _crew(codes=('62',), frm=date(2026, 6, 1), to=date(2026, 6, 30))
        CrewManualMember.objects.create(crew=c, mode='include', softech_usercode='63',
                                        valid_from=date(2026, 7, 1), reason='t')
        CrewManualMember.objects.create(crew=c, mode='include', pbx_extension='15',
                                        valid_from=date(2026, 6, 1), reason='t')
        self.assertEqual(CCM.call_center_seller_codes(date(2026, 6, 1), date(2026, 6, 30)), ['62'])
        self.assertEqual(CCM.call_center_seller_codes(date(2026, 6, 1), date(2026, 7, 31)),
                         ['62', '63'])


class CrewActualTests(TestCase):
    def test_sums_months_overlapping_the_period(self):
        from apps.crews.kpi import crew_actual
        c, other = _crew(), _crew(name='آخر')
        b = Branch.objects.create(softech_branch_id='971', code='971', name='B')
        for m, v in [(4, 1), (5, 10), (6, 100), (7, 1000)]:
            _roll(2026, m, 'call_count', v, crew=c)
        _roll(2026, 6, 'call_count', 5, crew=other)
        _roll(2026, 6, 'call_count', 7, branch=b)
        _roll(2026, 6, 'cash_delivery', 9, crew=c)
        self.assertEqual(crew_actual(c, 'call_count', date(2026, 5, 15), date(2026, 6, 10)), 110.0)
        self.assertEqual(crew_actual(c, 'call_count', date(2025, 12, 1), date(2026, 4, 30)), 1.0)
        self.assertEqual(crew_actual(c, 'beauty', date(2026, 6, 1), date(2026, 6, 30)), 0.0)


class SalesTargetCrewScopeTests(TestCase):
    """Owner ruling D: incentives use the board's rollup figure, now from the crew."""

    @classmethod
    def setUpTestData(cls):
        cls.crew = _crew()
        cls.retail = Branch.objects.create(softech_branch_id='972', code='972', name='R',
                                           kind=Branch.KIND_RETAIL)
        cls.cc = _legacy_cc()
        for metric, v in [('call_count', 1639), ('cash_delivery', 75000)]:
            _roll(2026, 10, metric, v, crew=cls.crew)
            _roll(2026, 10, metric, v, branch=cls.cc)        # not yet re-pointed (before Task 5)
        _roll(2026, 10, 'cash_delivery', 500, branch=cls.retail)

    def _t(self, scope, metric, **kw):
        return SalesTarget(scope_type=scope, metric=metric, period_start=date(2026, 10, 1),
                           period_end=date(2026, 10, 31), target_value=Decimal('1'), **kw)

    def test_crew_scope_reads_the_crew_rollup(self):
        self.assertEqual(self._t(SalesTarget.SCOPE_CREW, 'call_count', crew=self.crew)
                         .actual_value(), 1639.0)
        # a resolver metric too: the board figure, not KpiResolver over invoices
        self.assertEqual(self._t(SalesTarget.SCOPE_CREW, 'cash_delivery', crew=self.crew)
                         .actual_value(), 75000.0)

    def test_chain_call_count_counts_the_call_center_once(self):
        # legacy CC branch row + crew row both exist: the chain must not add both (Review Focus 2)
        self.assertEqual(self._t(SalesTarget.SCOPE_CHAIN, 'call_count').actual_value(), 1639.0)
        archived = _crew(name='مؤرشف')
        _roll(2026, 10, 'call_count', 999, crew=archived)
        archived.is_archived = True
        archived.save()
        self.assertEqual(self._t(SalesTarget.SCOPE_CHAIN, 'call_count').actual_value(), 1639.0)

    def test_branch_scope_call_count_reads_that_branch_only(self):
        _roll(2026, 10, 'call_count', 3, branch=self.retail)
        self.assertEqual(self._t(SalesTarget.SCOPE_BRANCH, 'call_count', branch=self.retail)
                         .actual_value(), 3.0)


class KpiBoardCrewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.retail = Branch.objects.create(softech_branch_id='973', code='973', name='R',
                                           kind=Branch.KIND_RETAIL)
        cls.crew = _crew()

    def setUp(self):
        from apps.tests.factories import make_user
        _, _, self.client = make_user('kpi_crew_admin', role='admin', access_all=True)

    def _board(self):
        return self.client.get('/api/forecasting/kpi-board/?year=2026&month=10').json()

    def test_call_center_block_reads_crew_rows_and_crew_targets(self):
        _roll(2026, 10, 'cash_delivery', 75000, crew=self.crew)
        _roll(2026, 10, 'call_count', 900, crew=self.crew)
        t = SalesTarget.objects.create(scope_type=SalesTarget.SCOPE_CREW, crew=self.crew,
                                       metric='call_count', period_start=date(2026, 10, 1),
                                       period_end=date(2026, 10, 31), target_value=Decimal('1000'))
        cc = self._board()['call_center']
        self.assertEqual(cc['crew_id'], self.crew.pk)
        self.assertEqual(cc['scope_key'], f'crew:{self.crew.pk}')
        self.assertEqual(cc['cells']['cash_delivery']['actual'], 75000.0)
        self.assertEqual(cc['cells']['call_count']['actual'], 900.0)
        self.assertEqual((cc['cells']['call_count']['target'], cc['cells']['call_count']['target_id']),
                         (1000.0, t.pk))

    def test_crew_only_month_has_no_branch_rows(self):
        _roll(2026, 10, 'cash_delivery', 75000, crew=self.crew)
        board = self._board()
        self.assertFalse(board['has_data'])
        self.assertEqual(board['branches'], [])
        self.assertIsNotNone(board['call_center'])

    def test_closed_or_call_center_branch_never_listed(self):
        # Review Focus 3: the CC branch closed (Task 5) and still carrying rows, or not yet closed
        _roll(2026, 10, 'cash_delivery', 100, branch=self.retail)
        closed = _legacy_cc(kind=Branch.KIND_CLOSED)
        _roll(2026, 10, 'cash_delivery', 75000, branch=closed)
        board = self._board()
        self.assertEqual([r['branch_id'] for r in board['branches']], [self.retail.pk])
        self.assertEqual(board['totals']['cash_delivery']['actual'], 100.0)
        from apps.forecasting.kpi import analytics_branches
        self.assertNotIn(closed.pk, set(analytics_branches().values_list('id', flat=True)))
        self.assertIsNone(board['call_center'])           # no crew rows this month

    def test_no_crew_no_block(self):
        self.crew.is_archived = True
        self.crew.save()
        self.assertIsNone(self._board()['call_center'])


class ReferencesCrewTests(TestCase):
    def test_call_count_series_comes_from_the_crew(self):
        from apps.forecasting import references as R
        c = _crew()
        cc = _legacy_cc()
        _roll(2026, 5, 'call_count', 1905, crew=c)
        _roll(2026, 5, 'call_count', 7, branch=cc)
        self.assertEqual(dict(R._series('call_count')), {(2026, 5): 1905.0})


class EngineCrewMemberTests(TestCase):
    """The call-center forecast member is the crew: key crew:<id>, ForecastResult.crew set,
    committed as a crew-scope SalesTarget; pic_count only for it."""

    @classmethod
    def setUpTestData(cls):
        cls.br = Branch.objects.create(softech_branch_id='974', code='974', name='PB',
                                       kind=Branch.KIND_RETAIL)
        cls.crew = _crew()
        for (y, m, v) in [(2025, 9, 400), (2026, 8, 450), (2026, 7, 420)]:
            _roll(y, m, 'pic_count', v, crew=cls.crew)
            _roll(y, m, 'pic_count', v, branch=cls.br)        # a branch pic_count must be ignored
            _roll(y, m, 'cash_delivery', v * 100, crew=cls.crew)
            _roll(y, m, 'cash_delivery', v * 1000, branch=cls.br)

    def test_generate_and_commit_crew_member(self):
        from apps.forecasting.engine import ForecastEngine
        sc = ForecastScenario.objects.create(name='p', year=2026, month=9, model='a',
                                             incentive_threshold=Decimal('0.90'))
        eng = ForecastEngine()
        eng.generate(sc)
        key = f'crew:{self.crew.pk}'
        pic = ForecastResult.objects.filter(scenario=sc, metric='pic_count')
        self.assertEqual([(r.scope_key, r.crew_id, r.branch_id, r.scope_label) for r in pic],
                         [(key, self.crew.pk, None, self.crew.name)])
        cash = ForecastResult.objects.get(scenario=sc, metric='cash_delivery', scope_key=key)
        self.assertEqual(cash.branch_share, Decimal('0'))       # an overlay: no chain share
        chain = ForecastResult.objects.get(scenario=sc, metric='cash_delivery', scope_key='chain')
        branch = ForecastResult.objects.get(scenario=sc, metric='cash_delivery', branch=self.br)
        self.assertEqual(chain.forecast_value, branch.forecast_value)   # crew not in the chain
        eng.commit(sc)
        t = SalesTarget.objects.get(scope_type=SalesTarget.SCOPE_CREW, crew=self.crew,
                                    metric='pic_count', period_start=date(2026, 9, 1))
        self.assertEqual(float(t.target_value), 500.0)     # 400×1.10÷0.90 = 488.9 → step 50 up
        self.assertIsNone(t.branch_id)
        self.assertFalse(SalesTarget.objects.filter(branch__isnull=True,
                                                    scope_type=SalesTarget.SCOPE_BRANCH).exists())
        res = eng.commit_cell(sc, 'cash_delivery', scope_key=key)
        self.assertEqual(SalesTarget.objects.get(pk=res['target_id']).crew_id, self.crew.pk)


class KpiExportCrewTests(TestCase):
    def test_cc_targets_from_crew_rows(self):
        from apps.forecasting.kpi_export import cc_targets
        self.assertIsNone(cc_targets(2026, 10))
        c = _crew()
        for (y, m) in [(2025, 10), (2026, 9), (2026, 8)]:
            _roll(y, m, 'cash_delivery', 200_000, crew=c)
        out = cc_targets(2026, 10)
        self.assertEqual(out['_crew_id'], c.pk)
        self.assertGreater(out['sales']['a'], 0)

    def test_legacy_workbook_call_center_key(self):
        import tempfile
        import openpyxl
        from apps.forecasting.kpi_export import _read_legacy_achieved
        wb = openpyxl.Workbook()
        ws = wb.active
        ws['E23'], ws['H23'], ws['K23'], ws['N23'] = 10, 20, 30, 40
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'legacy.xlsx'
            wb.save(p)
            out = _read_legacy_achieved(p)
        self.assertEqual(out['call_center'], {'cash_delivery': 10, 'gross_profit': 20,
                                              'beauty': 30, 'customer_count': 40})


class RollupRefreshCrewTests(TestCase):
    """Review Focus 5: a crew month whose sales synced after its build is stale and the
    refresh rebuilds it with build_crew_rollups."""

    @classmethod
    def setUpTestData(cls):
        from apps.customers.models import Customer
        cls.b = Branch.objects.create(softech_branch_id='975', code='975', name='RR',
                                      kind=Branch.KIND_RETAIL)
        cls.cust = Customer.objects.create(name='ر', softech_pic='PICRC', softech_id='C-RC')
        cls.crew = _crew()

    def _sale(self, ref, when, synced):
        from apps.customers.models import PurchaseHistory
        PurchaseHistory.objects.create(
            customer=self.cust, softech_invoice_id=ref, branch=self.b, doc_code='115',
            total_amount=Decimal('100'), invoice_date=when, sales_channel='91',
            sales_person_type='10', softech_user='62')
        PurchaseHistory.objects.filter(softech_invoice_id=ref).update(last_synced=synced)

    def test_crew_rows_older_than_the_sync_make_the_month_stale(self):
        from apps.forecasting import rollup_refresh as RR
        _roll(2025, 3, 'cash_delivery', 1, branch=self.b)
        _roll(2025, 3, 'cash_delivery', 1, crew=self.crew)
        K.objects.filter(branch=self.b).update(computed_at=_aware(2025, 4, 2, 6))
        K.objects.filter(crew=self.crew).update(computed_at=_aware(2025, 3, 31, 6))
        self._sale('RC1', _aware(2025, 3, 31, 20), synced=_aware(2025, 4, 2, 3))
        self.assertTrue(RR.month_status(2025, 3, now=_aware(2025, 4, 3))['stale'])
        K.objects.filter(crew=self.crew).update(computed_at=_aware(2025, 4, 2, 6))
        self.assertFalse(RR.month_status(2025, 3, now=_aware(2025, 4, 3))['stale'])

    def test_rows_nobody_rebuilds_do_not_pin_the_month_stale(self):
        from apps.forecasting import rollup_refresh as RR
        _roll(2025, 3, 'cash_delivery', 1, branch=self.b)
        K.objects.filter(branch=self.b).update(computed_at=_aware(2025, 4, 2, 6))
        old = _aware(2025, 3, 1, 6)
        archived = _crew(name='مؤرشف')
        _roll(2025, 3, 'cash_delivery', 1, crew=archived)
        archived.is_archived = True
        archived.save()
        _roll(2025, 3, 'cash_delivery', 1, branch=_legacy_cc())
        K.objects.exclude(branch=self.b).update(computed_at=old)
        self._sale('RC2', _aware(2025, 3, 31, 20), synced=_aware(2025, 4, 2, 3))
        self.assertFalse(RR.month_status(2025, 3, now=_aware(2025, 4, 3))['stale'])

    def test_rebuild_refreshes_the_crew_month(self):
        from apps.crews.kpi import CrewMonth
        from apps.forecasting import rollup_refresh as RR
        _roll(2025, 3, 'cash_delivery', 1, crew=self.crew)
        K.objects.filter(crew=self.crew).update(computed_at=_aware(2025, 3, 31, 6))
        fake = CrewMonth(kpis={'cash_delivery': Decimal('100')})
        with mock.patch('apps.crews.management.commands.build_crew_rollups.compute_crew_month',
                        return_value=fake) as cm:
            self.assertEqual(RR.rebuild([(2025, 3)]), [(2025, 3)])
        cm.assert_called_once()
        row = K.objects.get(crew=self.crew, year=2025, month=3, metric='cash_delivery')
        self.assertEqual(row.value, Decimal('100.00'))
        self.assertGreater(row.computed_at, _aware(2025, 4, 1))

    def test_retired_call_center_rollup_command(self):
        with self.assertRaises(CommandError):
            call_command('build_call_center_rollups', year=2026, month=6)


class BacktestCrewTests(TestCase):
    def test_crew_only_months_are_not_testable(self):
        from apps.forecasting.backtest import BacktestService
        c = _crew()
        for k in range(14):
            y, m = divmod((2025 * 12 + 0) + k, 12)
            _roll(y, m + 1, 'cash_delivery', 1, crew=c)
        self.assertEqual(BacktestService()._testable_months('cash_delivery'), [])


class SellerCodeReadersTests(TestCase):
    def test_insights_cc_agents_are_the_crews_codes_for_the_period(self):
        from apps.insights.rules import Ctx
        c = _crew(codes=('62',), frm=date(2026, 6, 1), to=date(2026, 6, 30))
        CrewManualMember.objects.create(crew=c, mode='include', softech_usercode='77',
                                        valid_from=date(2026, 8, 1), reason='t')
        ctx = Ctx('month', date(2026, 6, 1), date(2026, 6, 30))
        self.assertEqual(sorted(ctx.cc_agents), ['62'])


class CrewHistoryAndAdminTests(TestCase):
    def test_has_history_with_targets_or_forecasts(self):
        c = _crew(codes=(), frm=date.today())
        self.assertFalse(c.has_history())
        t = SalesTarget.objects.create(scope_type=SalesTarget.SCOPE_CREW, crew=c, metric='call_count',
                                       period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
                                       target_value=Decimal('1'))
        self.assertTrue(c.has_history())
        t.delete()
        sc = ForecastScenario.objects.create(name='h', year=2026, month=10)
        ForecastResult.objects.create(scenario=sc, crew=c, scope_key=f'crew:{c.pk}', metric='beauty')
        self.assertTrue(c.has_history())

    def test_rollup_str_names_the_crew(self):
        c = _crew()
        self.assertIn(c.name, str(_roll(2026, 10, 'call_count', 5, crew=c)))

    def test_call_center_config_agent_fields_read_only(self):
        from django.contrib import admin
        from apps.forecasting.models import CallCenterConfig
        ma = admin.site._registry[CallCenterConfig]
        ro = ma.get_readonly_fields(None)
        self.assertIn('sales_agent_usercodes', ro)
        self.assertIn('call_agent_extensions', ro)
        text = ' '.join(str(fs[0] or '') + str(fs[1].get('description', ''))
                        for fs in ma.get_fieldsets(None))
        self.assertIn('انتقلت إلى طاقم الكول سنتر', text)
        rollup_admin = admin.site._registry[K]
        self.assertIn('crew', rollup_admin.list_display)
        self.assertIn('crew', rollup_admin.list_filter)


class NoLegacyCcKeyTests(TestCase):
    """No reader finds the fake branch by its 'CC' key any more. The one-shot switch tools
    look it up in apps/crews/cc_legacy.py only."""
    ALLOWED = {Path('apps/crews/cc_legacy.py')}
    PATTERNS = [re.compile(r"""softech_branch_id\s*=\s*['"]CC['"]"""),
                re.compile(r"""(['"])CC\1""")]

    def test_no_cc_key_outside_migrations_and_tests(self):
        root = Path(settings.BASE_DIR)
        hits = []
        for p in (root / 'apps').rglob('*.py'):
            rel = p.relative_to(root)
            parts = rel.parts
            if 'migrations' in parts or 'tests' in parts or rel in self.ALLOWED:
                continue
            src = p.read_text(encoding='utf-8', errors='replace')
            for rx in self.PATTERNS:
                for mt in rx.finditer(src):
                    line = src.count('\n', 0, mt.start()) + 1
                    hits.append(f'{rel.as_posix()}:{line}')
        self.assertEqual(hits, [])
