"""
apps/tests/test_kpi_rollup_refresh.py  (doc 16)

Catch-up rebuild of KpiActualRollup (apps/forecasting/rollup_refresh.py): a month is
stale when its sales were synced after its rollup was computed — so a just-closed month
picks up its late sales (Oct-2026 froze 5.9% short when only the current month was
rebuilt) — the current month is throttled, and a generated scenario whose closed signal
months were re-rolled-up is flagged for recalculation.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.customers.models import Customer, PurchaseHistory
from apps.forecasting import rollup_refresh as RR
from apps.forecasting.models import ForecastScenario, KpiActualRollup


def _aware(y, m, d, h=12):
    return timezone.make_aware(datetime(y, m, d, h, 0))


class RollupStalenessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='981', code='981', name='RR', is_operational=True)
        cls.cust = Customer.objects.create(name='ر', softech_pic='PICRR', softech_id='C-RR')

    def _sale(self, ref, when, synced):
        PurchaseHistory.objects.create(
            customer=self.cust, softech_invoice_id=ref, branch=self.b, doc_code='115',
            total_amount=Decimal('100'), invoice_date=when, sales_channel='91', sales_person_type='10')
        PurchaseHistory.objects.filter(softech_invoice_id=ref).update(last_synced=synced)

    def _rollup(self, y, m, computed):
        KpiActualRollup.objects.create(branch=self.b, year=y, month=m, metric='cash_delivery', value=Decimal('1'))
        KpiActualRollup.objects.filter(year=y, month=m).update(computed_at=computed)

    def test_closed_month_with_late_sales_is_stale(self):
        # rollup computed on the 31st, the 31st's sales synced on the 2nd → stale
        self._rollup(2025, 3, _aware(2025, 3, 31, 6))
        self._sale('L1', _aware(2025, 3, 31, 20), synced=_aware(2025, 4, 2, 3))
        st = RR.month_status(2025, 3, now=_aware(2025, 4, 3))
        self.assertTrue(st['stale'])
        self.assertFalse(st['current'])

    def test_closed_month_rebuilt_after_last_sync_is_fresh(self):
        self._sale('L2', _aware(2025, 3, 31, 20), synced=_aware(2025, 4, 2, 3))
        self._rollup(2025, 3, _aware(2025, 4, 2, 4))
        self.assertFalse(RR.month_status(2025, 3, now=_aware(2025, 4, 3))['stale'])

    def test_month_with_sales_but_no_rollup_is_stale(self):
        self._sale('L3', _aware(2025, 5, 10), synced=_aware(2025, 5, 10, 13))
        self.assertTrue(RR.month_status(2025, 5, now=_aware(2025, 6, 1))['stale'])

    def test_current_month_is_throttled(self):
        now = timezone.now()
        y, m = timezone.localdate(now).year, timezone.localdate(now).month
        self._rollup(y, m, now - timedelta(minutes=30))
        self._sale('L4', now - timedelta(minutes=10), synced=now - timedelta(minutes=5))
        self.assertFalse(RR.month_status(y, m, now=now)['stale'])        # rebuilt 30 min ago
        KpiActualRollup.objects.filter(year=y, month=m).update(computed_at=now - timedelta(hours=3))
        self.assertTrue(RR.month_status(y, m, now=now)['stale'])         # older than the throttle

    def test_candidate_months_roll_back_over_the_year(self):
        self.assertEqual(RR.candidate_months(date(2027, 1, 2)), [(2026, 11), (2026, 12), (2027, 1)])

    def test_refresh_rebuilds_stale_months_and_forced_current(self):
        today = date.today()
        with mock.patch.object(RR, 'stale_months', return_value=[(2025, 3)]), \
             mock.patch.object(RR, 'rebuild', side_effect=lambda ms: sorted(ms)) as rb, \
             mock.patch('apps.forecasting.references.refresh_history') as refs:
            done = RR.refresh(force_current=True)
        self.assertEqual(done, [(2025, 3), (today.year, today.month)])
        rb.assert_called_once()
        refs.assert_called_once()           # a closed month changed → references follow

    def test_refresh_current_only_keeps_references(self):
        today = date.today()
        with mock.patch.object(RR, 'stale_months', return_value=[]), \
             mock.patch.object(RR, 'rebuild', side_effect=lambda ms: sorted(ms)), \
             mock.patch('apps.forecasting.references.refresh_history') as refs:
            self.assertEqual(RR.refresh(force_current=True), [(today.year, today.month)])
        refs.assert_not_called()

    def test_refresh_skips_while_another_runs(self):
        RR._lock.acquire()
        try:
            self.assertIsNone(RR.refresh())
        finally:
            RR._lock.release()


class ScenarioSignalsChangedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b = Branch.objects.create(softech_branch_id='982', code='982', name='SC', is_operational=True)

    def _scenario(self, y, m, generated_at):
        sc = ForecastScenario.objects.create(name='t', year=y, month=m)
        ForecastScenario.objects.filter(pk=sc.pk).update(
            status=ForecastScenario.STATUS_GENERATED, generated_at=generated_at)
        sc.refresh_from_db()
        return sc

    def _flag(self, sc):
        from apps.forecasting.serializers import ForecastScenarioSerializer
        return ForecastScenarioSerializer(sc).data['signals_changed_at']

    def test_closed_lm_rebuilt_after_generate_flags_scenario(self):
        sc = self._scenario(2025, 5, _aware(2025, 4, 30))
        KpiActualRollup.objects.create(branch=self.b, year=2025, month=4, metric='cash_delivery', value=Decimal('1'))
        KpiActualRollup.objects.filter(year=2025, month=4).update(computed_at=_aware(2025, 5, 2))
        self.assertIsNotNone(self._flag(sc))

    def test_rollups_older_than_generate_do_not_flag(self):
        KpiActualRollup.objects.create(branch=self.b, year=2025, month=4, metric='cash_delivery', value=Decimal('1'))
        KpiActualRollup.objects.filter(year=2025, month=4).update(computed_at=_aware(2025, 5, 2))
        sc = self._scenario(2025, 5, _aware(2025, 5, 3))
        self.assertIsNone(self._flag(sc))

    def test_running_month_never_flags(self):
        today = date.today()
        ny, nm = RR._shift(today.year, today.month, 1)
        sc = self._scenario(ny, nm, timezone.now() - timedelta(days=1))
        KpiActualRollup.objects.create(branch=self.b, year=today.year, month=today.month,
                                       metric='cash_delivery', value=Decimal('1'))   # computed now
        self.assertIsNone(self._flag(sc))


class KpiRefreshViewTests(TestCase):
    def setUp(self):
        from apps.tests.factories import make_user
        _, _, self.client = make_user('rr_admin', role='admin', access_all=True)

    def test_status_lists_current_and_previous_months(self):
        r = self.client.get('/api/forecasting/kpi-board/refresh/')
        self.assertEqual(r.status_code, 200, r.content)
        months = [(m['year'], m['month']) for m in r.json()['months']]
        self.assertEqual(months, RR.candidate_months())

    def test_post_starts_background_refresh(self):
        with mock.patch('apps.forecasting.views.start_thread') as st:
            r = self.client.post('/api/forecasting/kpi-board/refresh/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['started'])
        st.assert_called_once()
