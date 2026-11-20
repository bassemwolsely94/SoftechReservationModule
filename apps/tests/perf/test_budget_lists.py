"""
Query budgets for lists and search (performance stage 1, design §4 "list" ≤ 800 ms p95): the routes
the load test (deploy/loadtest/locustfile.py) hits. Each call runs the same number of queries with few
or many rows and stays under its ceiling in apps/tests/perf/budgets.py.
"""
import datetime
import uuid
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.branches.models import Branch
from apps.callcenter.models import CallItem, CallLog
from apps.customers.models import Customer
from apps.insurance import models as ins
from apps.pos_orders.models import MissedSaleSuggestion, SoftechSalesOrder, SoftechSalesOrderLine
from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
from apps.reservations.models import Reservation, ReservationLine
from apps.supply.models import SupplyCase

from ..factories import make_admin, make_branch, make_item, make_pharmacist, make_user
from .budget import assert_budget


class _Counter:
    n = 0

    def next(self):
        _Counter.n += 1
        return _Counter.n


def _count_list(resp):
    """Rows for both paginated (results) and plain list payloads, or a dict with a known list key."""
    data = resp.data
    if isinstance(data, dict):
        for key in ('results', 'items', 'rows', 'customers'):
            if isinstance(data.get(key), list):
                return len(data[key])
        return 0
    return len(data)


class ListBudgets(TestCase):
    def setUp(self):
        self.c = _Counter()
        self.branch = make_branch()
        _, self.admin, self.admin_client = make_admin('perf_l_admin')
        _, self.pharma, self.pharma_client = make_pharmacist('perf_l_pharma', branch=self.branch)
        self.item = make_item()

    # ── grow helpers ──────────────────────────────────────────────────────────
    def _reservations(self, n=25):
        for _ in range(n):
            i = self.c.next()
            # customer + assigned_to set: the list select_related()s them, so a dropped join shows up
            cust = Customer.objects.create(name=f'عميل حجز {i}', phone=f'012{i:08d}', softech_pic=f'RS{i:06d}',
                                           preferred_branch=self.branch)
            r = Reservation.objects.create(item=self.item, branch=self.branch, quantity_requested=1,
                                           contact_name=f'عميل {i}', contact_phone=f'010{i:08d}',
                                           created_by=self.admin, customer=cust, assigned_to=self.admin)
            for _ in range(2):
                ReservationLine.objects.create(reservation=r, item=self.item, quantity_requested=1)

    def _customers(self, n=25, name='أحمد'):
        for _ in range(n):
            i = self.c.next()
            Customer.objects.create(name=f'{name} عميل {i}', phone=f'011{i:08d}',
                                    softech_pic=f'PERF{i:06d}', preferred_branch=self.branch)

    def _items(self, n=25, name='باراسيتامول'):
        for _ in range(n):
            i = self.c.next()
            make_item(f'{name} {i}', f'F{i:05d}')

    def _supply_cases(self, n=20):
        for _ in range(n):
            i = self.c.next()
            SupplyCase.objects.create(item=make_item(f'صنف توريد {i}', f'S{i:05d}'), branch=self.branch,
                                      status=SupplyCase.STATUS_DETECTED)

    def _pos_orders(self, n=20):
        for _ in range(n):
            o = SoftechSalesOrder.objects.create(branch=self.branch,
                                                 softech_branchcode=self.branch.softech_branch_id,
                                                 store_code=self.branch.softech_branch_id, channel='cash')
            for _ in range(2):
                SoftechSalesOrderLine.objects.create(order=o, softech_itemcode='100', qty=Decimal('1'))

    def _missed_sales(self, n=24):
        """Both sources (C28): POS rows whose cart reached SOFTECH (bought_in_cart prefetch) and
        call-centre rows linked to a call item (select_related call_item)."""
        for k in range(n):
            i = self.c.next()
            cust = Customer.objects.create(name=f'عميل فائت {i}', phone=f'013{i:08d}',
                                           softech_pic=f'MS{i:06d}', preferred_branch=self.branch)
            row = dict(branch=self.branch, customer=cust, item=self.item, item_code='IT001',
                       item_name='باراسيتامول', qty=1, value=Decimal('10'), seen_at=timezone.now(),
                       selected_by=self.admin)
            if k % 2:
                log = CallLog.objects.create(phone_number=cust.phone, customer=cust, branch=self.branch,
                                             handled_by=self.admin)
                ci = CallItem.objects.create(call_log=log, item=self.item)
                MissedSaleSuggestion.objects.create(source='call_center', call_item=ci, **row)
            else:
                token = uuid.uuid4()
                o = SoftechSalesOrder.objects.create(branch=self.branch,
                                                     softech_branchcode=self.branch.softech_branch_id,
                                                     store_code=self.branch.softech_branch_id, channel='cash',
                                                     client_token=token,
                                                     status=SoftechSalesOrder.STATUS_PUSHED)
                SoftechSalesOrderLine.objects.create(order=o, softech_itemcode='100', qty=Decimal('1'))
                MissedSaleSuggestion.objects.create(source='pos', cart_token=token, **row)

    def _claims(self, n=15):
        client = ins.InsuranceClient.objects.create(name=f'جهة {self.c.next()}')
        sub = ins.InsuranceSubClient.objects.create(client=client, name='فئة')
        for _ in range(n):
            i = self.c.next()
            ins.InsuranceClaim.objects.create(claim_number=f'MT-P-{i:05d}', subclient=sub,
                                              period_from=datetime.date(2026, 8, 1),
                                              period_to=datetime.date(2026, 8, 31))

    # ── tests ─────────────────────────────────────────────────────────────────
    @override_settings(MISSED_SALES_ENABLED=True)
    def test_missed_sales_branch_scoped(self):
        self._missed_sales(2)
        assert_budget(self, 'pos-orders/missed-sales', self.pharma_client, '/api/pos-orders/missed-sales/',
                      grow=self._missed_sales, min_rows=25, rows_of=_count_list)

    @override_settings(MISSED_SALES_ENABLED=True)
    def test_missed_sales_source_filter(self):
        self._missed_sales(2)
        assert_budget(self, 'pos-orders/missed-sales', self.pharma_client,
                      '/api/pos-orders/missed-sales/?source=call_center',
                      grow=lambda: self._missed_sales(30), min_rows=15, rows_of=_count_list)

    def test_reservations(self):
        self._reservations(2)
        assert_budget(self, 'reservations', self.admin_client, '/api/reservations/',
                      grow=self._reservations, min_rows=25, rows_of=_count_list)

    def test_customers_branch_scoped(self):
        self._customers(2)
        assert_budget(self, 'customers', self.pharma_client, '/api/customers/',
                      grow=self._customers, min_rows=25, rows_of=_count_list)

    def test_customers_search(self):
        self._customers(2)
        assert_budget(self, 'customers?search', self.pharma_client, '/api/customers/?search=أحمد',
                      grow=self._customers, min_rows=25, rows_of=_count_list)

    def test_items_search(self):
        self._items(2)
        assert_budget(self, 'items?search', self.admin_client, '/api/items/?search=باراسيتامول',
                      grow=self._items, min_rows=25, rows_of=_count_list)

    def test_universal_search(self):
        term = 'باراسيتامول'

        def seed(n):
            self._items(n)
            self._customers(n, name=term)
            for _ in range(n):   # matching reservations (contact_name) and POS orders (customer_name)
                i = self.c.next()
                Reservation.objects.create(item=self.item, branch=self.branch, quantity_requested=1,
                                           contact_name=f'{term} {i}', contact_phone=f'013{i:08d}',
                                           created_by=self.admin)
                SoftechSalesOrder.objects.create(branch=self.branch, softech_branchcode=self.branch.softech_branch_id,
                                                 store_code=self.branch.softech_branch_id, channel='cash',
                                                 customer_name=f'{term} {i}')
        seed(2)
        # limit=25 (the max) so every group can carry the grown rows; `count` = all groups together
        assert_budget(self, 'search/universal', self.admin_client, f'/api/search/universal?q={term}&limit=25',
                      grow=lambda: seed(12), min_rows=40, rows_of=lambda r: r.data['count'])

    def test_supply_cases(self):
        self._supply_cases(2)
        assert_budget(self, 'supply/cases', self.admin_client, '/api/supply/cases/',
                      grow=self._supply_cases, min_rows=20, rows_of=_count_list)

    def test_pos_orders(self):
        self._pos_orders(2)
        assert_budget(self, 'pos-orders', self.admin_client, '/api/pos-orders/',
                      grow=self._pos_orders, min_rows=20, rows_of=_count_list)

    def test_insurance_claims(self):
        self._claims(2)
        assert_budget(self, 'insurance/claims', self.admin_client, '/api/insurance/claims/',
                      grow=self._claims, min_rows=15, rows_of=_count_list)


class PurchasingListBudgets(TestCase):
    TODAY = datetime.date(2026, 11, 3)

    def setUp(self):
        self.run = DemandCalculationRun.objects.create(status='success')
        self.b1 = Branch.objects.create(softech_branch_id='101', name='B1', name_ar='ب', is_active=True)
        _, _, self.client_ = make_user('perf_purch', role='purchasing', branch=self.b1, access_all=True)
        self.n = 0

    def _metrics(self, n=30):
        for _ in range(n):
            self.n += 1
            it = make_item(f'دواء {self.n}', f'M{self.n:05d}')
            it.effect_code = f'E{self.n % 5}'
            it.effect_name = f'Effect {self.n % 5}'
            it.save()
            ItemDemandMetrics.objects.create(run=self.run, item=it, branch=self.b1, calc_date=self.TODAY,
                                             monthly_avg=1)

    def test_metrics(self):
        self._metrics(2)
        assert_budget(self, 'purchasing/metrics', self.client_, '/api/purchasing/metrics/',
                      grow=self._metrics, min_rows=30, rows_of=_count_list)

    def _aggregated(self, n=30):
        from apps.purchasing.models import ItemDemandAggregated
        for _ in range(n):
            self.n += 1
            it = make_item(f'دواء {self.n}', f'M{self.n:05d}')
            ItemDemandAggregated.objects.create(run=self.run, item=it, calc_date=self.TODAY, total_monthly_avg=1,
                                                total_current_stock=self.n % 9)

    def test_aggregated(self):
        self._aggregated(2)
        assert_budget(self, 'purchasing/aggregated', self.client_, '/api/purchasing/aggregated/',
                      grow=self._aggregated, min_rows=30, rows_of=_count_list)

    def test_filter_options(self):
        self._metrics(2)
        # the grown items carry 5 effect codes (E0–E4): they must reach the effects list
        assert_budget(self, 'purchasing/filter-options', self.client_, '/api/purchasing/filter-options/',
                      grow=self._metrics, min_rows=5, rows_of=lambda r: len(r.data.get('effects') or []))
