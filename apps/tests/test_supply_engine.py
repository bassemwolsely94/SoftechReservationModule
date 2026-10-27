"""
Phase-3 tests for the supply decision engine (doc 24 §7/§9/§11/§12/§13/§19/§20).

net_demand (max rule, no double-count), internal allocation (surplus = stock − safety),
supplier effective-cost ranking + historical deal, and the full recommend() quantity ledger.
"""
from datetime import date

from django.test import TestCase, SimpleTestCase

from apps.supply.models import DemandSignal
from apps.supply import demand_signals as ds
from apps.supply.engine import (
    net_demand, allocate_internal, supplier_options, effective_unit_cost, recommend,
)


def _run():
    from apps.purchasing.models import DemandCalculationRun
    return DemandCalculationRun.objects.create(status='success', calc_date=date.today())


def _metric(run, item, branch, *, stock=0, safety=0, gap=0, in_transit=0, monthly_avg=0):
    from apps.purchasing.models import ItemDemandMetrics
    return ItemDemandMetrics.objects.create(
        run=run, item=item, branch=branch, calc_date=date.today(),
        current_stock=stock, safety_stock=safety, gap=gap,
        in_transit_qty=in_transit, monthly_avg=monthly_avg)


# ── Effective cost (pure) ──────────────────────────────────────────────────────

class EffectiveCostTests(SimpleTestCase):
    def test_foc_lowers_effective_cost_below_cheaper_nominal(self):
        # §12: 10 × 100 + 2 FOC = 83.33 beats 10 × 90 + 0 = 90.
        self.assertAlmostEqual(effective_unit_cost(100, 10, 2), 83.3333, places=3)
        self.assertEqual(effective_unit_cost(90, 10, 0), 90.0)

    def test_zero_qty_returns_price(self):
        self.assertEqual(effective_unit_cost(50, 0, 0), 50.0)


# ── net_demand ─────────────────────────────────────────────────────────────────

class NetDemandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        cls.item = Item.objects.create(softech_id='500001', name='DRUG', is_active=True)
        cls.branch = Branch.objects.create(softech_branch_id='130', name='B130')

    def test_engine_gap_is_the_baseline(self):
        run = _run()
        _metric(run, self.item, self.branch, stock=0, safety=2, gap=8, in_transit=0)
        nd = net_demand(self.item.id, branch_id=self.branch.id)
        self.assertEqual(nd['calculated_demand'], 8.0)
        self.assertEqual(nd['required'], 8.0)

    def test_scarce_item_caught_by_ledger_when_gap_zero(self):
        run = _run()
        _metric(run, self.item, self.branch, stock=0, safety=0, gap=0)
        # A waiting customer (reservation-class signal) but no sales-history gap.
        ds.record_signal('reservation', 'r1', provenance_class=DemandSignal.CLASS_CUSTOMER,
                         qty=3, item_id=self.item.id, branch_id=self.branch.id)
        nd = net_demand(self.item.id, branch_id=self.branch.id)
        self.assertEqual(nd['calculated_demand'], 0.0)
        self.assertEqual(nd['ledger_demand'], 3.0)
        self.assertEqual(nd['required'], 3.0)              # ledger catches it

    def test_reservation_covered_by_stock_needs_no_purchase(self):
        # §7 cash preservation: 10 on the shelf, 1 waiting customer, engine gap 0 →
        # the reservation is served from stock; nothing to buy.
        run = _run()
        _metric(run, self.item, self.branch, stock=10, safety=2, gap=0)
        ds.record_signal('reservation', 'r1', provenance_class=DemandSignal.CLASS_CUSTOMER,
                         qty=1, item_id=self.item.id, branch_id=self.branch.id)
        nd = net_demand(self.item.id, branch_id=self.branch.id)
        self.assertEqual(nd['ledger_demand'], 1.0)
        self.assertEqual(nd['ledger_need'], 0.0)
        self.assertEqual(nd['required'], 0.0)

    def test_ledger_need_nets_in_transit(self):
        # 5 reserved, 0 on hand, 4 already in transit → only 1 uncovered.
        run = _run()
        _metric(run, self.item, self.branch, stock=0, safety=0, gap=0, in_transit=4)
        ds.record_signal('reservation', 'r1', provenance_class=DemandSignal.CLASS_CUSTOMER,
                         qty=5, item_id=self.item.id, branch_id=self.branch.id)
        nd = net_demand(self.item.id, branch_id=self.branch.id)
        self.assertEqual(nd['ledger_need'], 1.0)
        self.assertEqual(nd['required'], 1.0)

    def test_gap_and_branch_request_take_max_not_sum(self):
        run = _run()
        _metric(run, self.item, self.branch, stock=0, safety=0, gap=5)
        ds.record_signal('shortage_item', 's1', provenance_class=DemandSignal.CLASS_BRANCH,
                         qty=5, item_id=self.item.id, branch_id=self.branch.id)
        nd = net_demand(self.item.id, branch_id=self.branch.id)
        self.assertEqual(nd['required'], 5.0)              # max(5,5) — not 10


# ── Internal allocation ────────────────────────────────────────────────────────

class AllocationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        cls.item = Item.objects.create(softech_id='510001', name='DRUG', is_active=True)
        cls.b1 = Branch.objects.create(softech_branch_id='130', name='B130')
        cls.b2 = Branch.objects.create(softech_branch_id='140', name='B140')
        cls.dest = Branch.objects.create(softech_branch_id='150', name='B150')

    def test_greedy_allocation_from_surplus_never_below_safety(self):
        run = _run()
        _metric(run, self.item, self.b1, stock=10, safety=2)   # surplus 8
        _metric(run, self.item, self.b2, stock=5, safety=1)    # surplus 4
        _metric(run, self.item, self.dest, stock=0, safety=3)  # requester (excluded)
        alloc = allocate_internal(self.item.id, 10, to_branch_id=self.dest.id)
        self.assertEqual(alloc['internally_allocated'], 10.0)  # 8 from b1 + 2 from b2
        self.assertEqual(alloc['total_surplus_available'], 12.0)
        self.assertEqual(alloc['transfers'][0]['from_branch_id'], self.b1.id)  # richest first

    def test_no_surplus_means_no_transfer(self):
        run = _run()
        _metric(run, self.item, self.b1, stock=2, safety=3)    # below safety → no surplus
        alloc = allocate_internal(self.item.id, 5, to_branch_id=self.dest.id)
        self.assertEqual(alloc['internally_allocated'], 0.0)


# ── Supplier sourcing ──────────────────────────────────────────────────────────

class SourcingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        cls.item = Item.objects.create(softech_id='520001', name='DRUG', is_active=True)

    def _offer(self, price, qty, foc):
        from apps.supply.models import AvailabilityBatch, AvailabilityLine
        b = AvailabilityBatch.objects.create(source='whatsapp', supplier_name='Supp')
        return AvailabilityLine.objects.create(batch=b, raw_text='drug', item=self.item,
                                               price=price, supplier_qty=qty, foc_qty=foc)
    def test_foc_offer_beats_cheaper_nominal(self):
        a = self._offer(100, 10, 2)   # effective 83.33
        b = self._offer(90, 10, 0)    # effective 90
        src = supplier_options(self.item.id, 10, availability_lines=[a, b])
        self.assertEqual(src['best']['availability_line_id'], a.id)
        self.assertAlmostEqual(src['best']['effective_cost'], 83.3333, places=2)

    def test_better_historical_deal_flagged(self):
        from apps.procurement.models import PurchaseLine
        PurchaseLine.objects.create(item=self.item, item_code=self.item.softech_id,
                                    branch_code='100', supplier_code='565', doc_number='1',
                                    doc_date=date.today(), doccode='10',
                                    effective_cost=80, unit_price=100, bonus_qty=2)
        offer = self._offer(90, 10, 0)   # effective 90 > historical 80
        src = supplier_options(self.item.id, 10, availability_lines=[offer])
        self.assertIsNotNone(src['better_historical_deal'])
        self.assertEqual(src['better_historical_deal']['effective_cost'], 80.0)


# ── Full recommendation ledger ─────────────────────────────────────────────────

class RecommendTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        cls.item = Item.objects.create(softech_id='530001', name='DRUG', is_active=True)
        cls.b1 = Branch.objects.create(softech_branch_id='130', name='B130')
        cls.dest = Branch.objects.create(softech_branch_id='150', name='B150')

    def test_demand15_internal6_external9(self):
        # §11 worked example: demand 15, internal surplus 6, residual procurement 9.
        run = _run()
        _metric(run, self.item, self.dest, stock=0, safety=0, gap=15)   # requester needs 15
        _metric(run, self.item, self.b1, stock=8, safety=2)             # surplus 6
        rec = recommend(self.item.id, branch_id=self.dest.id)
        L = rec['quantity_ledger']
        self.assertEqual(L['required'], 15.0)
        self.assertEqual(L['internally_allocated'], 6.0)
        self.assertEqual(L['residual_gap'], 9.0)
        self.assertEqual(L['proposed_purchase'], 9.0)
        self.assertTrue(rec['reasons'])                     # explainable

    def test_in_transit_is_not_subtracted_twice(self):
        # The engine gap is ALREADY net of in-transit (gap = calc_gap(stock + in_transit)),
        # so a gap of 10 with 4 in transit still means 10 more are needed — subtracting
        # the 4 again would under-order.
        run = _run()
        _metric(run, self.item, self.dest, stock=0, safety=0, gap=10, in_transit=4)
        rec = recommend(self.item.id, branch_id=self.dest.id)
        L = rec['quantity_ledger']
        self.assertEqual(L['confirmed_incoming'], 4.0)      # shown, informational
        self.assertEqual(L['residual_gap'], 10.0)           # NOT 6


class BranchOwnFiguresTests(TestCase):
    """Owner decision 2026-10-05: a branch's need uses ONLY that branch's figures — a branch
    with no engine metric for the item never inherits the NETWORK gap / stock."""

    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item, ItemStock
        from apps.branches.models import Branch
        from apps.purchasing.models import ItemDemandAggregated
        cls.item = Item.objects.create(softech_id='500901', name='EPREXLIKE 4000', is_active=True)
        cls.a = Branch.objects.create(softech_branch_id='170', name='A')
        cls.b = Branch.objects.create(softech_branch_id='160', name='B')
        run = _run()
        _metric(run, cls.item, cls.a, stock=0, safety=2, gap=16)          # only A has a target
        ItemDemandAggregated.objects.create(run=run, item=cls.item, calc_date=date.today(),
                                            total_current_stock=0, total_gap=16)
        ItemStock.objects.create(item=cls.item, branch=cls.b, quantity_on_hand=2)

    def test_branch_without_metric_has_no_engine_need(self):
        nd = net_demand(self.item.id, branch_id=self.b.id)
        self.assertEqual(nd['calculated_demand'], 0.0)                   # was 16 (network gap)
        self.assertEqual(nd['current_stock'], 2.0)                       # its own live on-hand
        self.assertEqual(nd['required'], 0.0)

    def test_waiting_customer_netted_against_own_shelf(self):
        ds.record_signal('reservation', 'rsv-901', item=self.item, branch=self.b, qty=3,
                         provenance_class=DemandSignal.CLASS_CUSTOMER)
        nd = net_demand(self.item.id, branch_id=self.b.id)
        self.assertEqual(nd['required'], 1.0)                            # 3 waiting − 2 on the shelf
