"""
Queue-scope rule for company-wide (market-shortage) cases — owner decision 2026-09-28:
open only if the item is human-CONFIRMED as a market shortage OR its estimated lost sales
≥ the admin threshold (default 2,000 EGP/month); urgency rule unchanged; out-of-scope cases
in a system status are closed with an audited reason.
"""
from datetime import date
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from apps.supply import cases as svc
from apps.supply import demand_signals as ds
from apps.supply.kpis import supply_kpis
from apps.supply.models import DemandSignal, SupplyCase

S = SupplyCase
DETECTOR = 'apps.purchasing.shortage.compute_shortage_candidates'


class ScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        from apps.purchasing.models import DemandCalculationRun, ItemDemandAggregated
        cls.confirmed = Item.objects.create(softech_id='950001', name='CONFIRMED', is_active=True,
                                            in_shortage=True)
        cls.costly = Item.objects.create(softech_id='950002', name='COSTLY', is_active=True)
        cls.minor = Item.objects.create(softech_id='950003', name='MINOR', is_active=True)
        cls.branch = Branch.objects.create(softech_branch_id='130', name='B')
        run = DemandCalculationRun.objects.create(status='success', calc_date=date.today())
        for it in (cls.confirmed, cls.costly, cls.minor):
            ItemDemandAggregated.objects.create(run=run, item=it, calc_date=date.today(),
                                                total_gap=5, total_current_stock=0)
            ds.record_signal('market_shortage', str(it.id),
                             provenance_class=DemandSignal.CLASS_STATISTICAL, qty=5, item_id=it.id)

    def detector(self):
        return [SimpleNamespace(item_id=self.confirmed.id, lost_monthly=300.0),
                SimpleNamespace(item_id=self.costly.id, lost_monthly=3000.0),
                SimpleNamespace(item_id=self.minor.id, lost_monthly=500.0)]

    def test_only_confirmed_or_high_loss_items_open_company_cases(self):
        with mock.patch(DETECTOR, return_value=self.detector()):
            counts = svc.sweep_cases(notify=False)
        opened = set(SupplyCase.objects.filter(branch__isnull=True).values_list('item_id', flat=True))
        self.assertEqual(opened, {self.confirmed.id, self.costly.id})     # minor stays on watchlist
        self.assertEqual(counts['opened'], 2)
        c = SupplyCase.objects.get(item=self.confirmed)
        self.assertIn('مؤكَّد كنقص سوق', c.last_reasons[0])                # why it is followed up
        self.assertIn('3,000', SupplyCase.objects.get(item=self.costly).last_reasons[0])

    def test_threshold_is_admin_editable(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.create(key=svc.NETWORK_CASE_MIN_LOST_SETTING, value='5000',
                                     value_type='integer')
        with mock.patch(DETECTOR, return_value=self.detector()):
            svc.sweep_cases(notify=False)
        opened = set(SupplyCase.objects.filter(branch__isnull=True).values_list('item_id', flat=True))
        self.assertEqual(opened, {self.confirmed.id})                    # 3,000 < 5,000

    def test_out_of_scope_case_in_system_status_is_closed_with_audited_reason(self):
        from apps.audit.models import AuditLog
        stale = SupplyCase.objects.create(item=self.minor, branch=None, status=S.STATUS_DETECTED)
        with mock.patch(DETECTOR, return_value=self.detector()):
            counts = svc.sweep_cases(notify=False)
        stale.refresh_from_db()
        self.assertEqual(stale.status, S.STATUS_CANCELLED)
        self.assertTrue(stale.close_reason.startswith(svc.SCOPE_CLOSE_REASON))
        self.assertEqual(counts['out_of_scope'], 1)
        self.assertTrue(AuditLog.objects.filter(action='supply_case_closed',
                                                object_id=str(stale.pk)).exists())

    def test_case_a_person_already_acted_on_is_never_auto_closed(self):
        acted = SupplyCase.objects.create(item=self.minor, branch=None, status=S.STATUS_ORDERED)
        with mock.patch(DETECTOR, return_value=self.detector()):
            svc.sweep_cases(notify=False)
        acted.refresh_from_db()
        self.assertEqual(acted.status, S.STATUS_ORDERED)

    def test_branch_request_still_opens_a_case_for_an_out_of_scope_item(self):
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        run = DemandCalculationRun.objects.order_by('-started_at').first()
        ItemDemandMetrics.objects.create(run=run, item=self.minor, branch=self.branch,
                                         calc_date=date.today(), current_stock=0, gap=3)
        ds.record_signal('shortage_item', 'b1', provenance_class=DemandSignal.CLASS_BRANCH,
                         qty=3, item_id=self.minor.id, branch_id=self.branch.id)
        with mock.patch(DETECTOR, return_value=self.detector()):
            svc.sweep_cases(notify=False)
        self.assertTrue(SupplyCase.objects.filter(item=self.minor, branch=self.branch).exists())

    def test_urgency_rule_unchanged_zero_stock_market_shortage_is_urgent(self):
        with mock.patch(DETECTOR, return_value=self.detector()):
            svc.sweep_cases(notify=False)
        self.assertTrue(SupplyCase.objects.get(item=self.confirmed).is_urgent)

    def test_scope_closures_do_not_inflate_the_cancelled_kpi(self):
        SupplyCase.objects.create(item=self.minor, branch=None, status=S.STATUS_DETECTED)
        with mock.patch(DETECTOR, return_value=self.detector()):
            svc.sweep_cases(notify=False)
        r = supply_kpis(days=30)['resolution']
        self.assertEqual(r['cancelled_count'], 0)
        self.assertEqual(r['scoped_out_count'], 1)
