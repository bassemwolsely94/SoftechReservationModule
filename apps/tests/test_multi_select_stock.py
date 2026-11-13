"""
Multi-select list filters on the stock / expiry screens (core/multi_filter.py).

/stock-audit (branch · status · severity · channel), /stock-count sessions (status · branch_code ·
mode), /batches disposal ledger (status · branch · decision), the rescue worklist (branch), the
return calendar (supplier · location, its Excel too) and the item operational filters of the
inventory / sales dashboards (item_level · branch_trans · supplier_trans · customer_trans) take one
value as before or several as a comma list (?status=draft,closed). Two values = the union, one value =
as before, nothing = every row the user may see. The filters run after branch scoping, so a branch
user who asks for another branch still sees only their own rows. Nothing here touches SOFTECH.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.tests.factories import make_branch, make_branch2, make_item, make_user
from apps.tests.security.fixtures import seed_code_matrix
from core.middleware import module_access

TODAY = timezone.localdate()


def _rows(resp):
    data = resp.data
    return data.get('results', data) if hasattr(data, 'get') else data


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):
    def setUp(self):
        seed_code_matrix()
        self.b1 = make_branch('فرع م1', 'MS1')
        self.b2 = make_branch2('فرع م2', 'MS2')
        self.b3 = make_branch('فرع م3', 'MS3')
        _, self.admin, self.admin_c = make_user('ms_stock_admin', role='admin', access_all=True)
        _, self.pharm, self.pharm_c = make_user('ms_stock_pharm', role='pharmacist', branch=self.b1)

    def tearDown(self):
        module_access.clear_cache()


# ── /stock-audit ──────────────────────────────────────────────────────────────

class StockAuditMultiFilterTests(_Base):
    URL = '/api/stock-audit/findings/'

    def setUp(self):
        super().setUp()
        _, _, self.sup_c = make_user('ms_sa_sup', role='supervisor', branch=self.b1)
        self.f1 = self.finding('MS1', 'open', 'critical', 1)
        self.f2 = self.finding('MS2', 'escalated', 'warning', 2)
        self.f3 = self.finding('MS3', 'reviewed', 'info', 3)

    def finding(self, branch, status, severity, n):
        from apps.stock_audit.models import StockAuditFinding
        return StockAuditFinding.objects.create(
            rule_code='sale_below_cost', dedup_key=f'{branch}|ms|{n}', severity=severity, status=status,
            branchcode=branch, itemcode='100001', doccode='115', docnumber=n, docdate=TODAY,
            occurred_at=timezone.now(), softech_user='166', value_egp=Decimal('100'),
            message_ar='رسالة', message_en='message', last_seen=timezone.now())

    def ids(self, client=None, **params):
        r = (client or self.sup_c).get(self.URL, params)
        self.assertEqual(r.status_code, 200)
        return {x['id'] for x in r.json()['results']}

    def test_two_branches_are_the_union(self):
        self.assertEqual(self.ids(branch='MS1,MS2'), {self.f1.id, self.f2.id})

    def test_repeated_param_form(self):
        r = self.sup_c.get(self.URL + '?branch=MS1&branch=MS3')
        self.assertEqual({x['id'] for x in r.json()['results']}, {self.f1.id, self.f3.id})

    def test_one_value_and_none(self):
        self.assertEqual(self.ids(branch='MS2'), {self.f2.id})
        self.assertEqual(self.ids(), {self.f1.id, self.f2.id, self.f3.id})

    def test_status_and_severity_lists(self):
        self.assertEqual(self.ids(status='open,reviewed'), {self.f1.id, self.f3.id})
        self.assertEqual(self.ids(severity='critical,info'), {self.f1.id, self.f3.id})
        self.assertEqual(self.ids(status='open,escalated', severity='warning'), {self.f2.id})

    def test_summary_branch_list(self):
        r = self.sup_c.get('/api/stock-audit/summary/', {'branch': 'MS1,MS2'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(sum(x['total'] for x in r.json()['rules']), 2)

    def test_branch_manager_never_widened(self):
        from apps.stock_audit.models import StockAuditAccess
        StockAuditAccess.objects.create(staff=self.pharm, granted_by=self.admin)
        self.assertEqual(self.ids(self.pharm_c, branch='MS1,MS2,MS3'), {self.f1.id})
        self.assertEqual(self.ids(self.pharm_c, branch='MS2'), set())


# ── /stock-count sessions ─────────────────────────────────────────────────────

class StockCountSessionMultiFilterTests(_Base):
    URL = '/api/stockcount/sessions/'

    def setUp(self):
        super().setUp()
        from apps.stockcount.models import StockCountSession
        mk = StockCountSession.objects.create
        self.s1 = mk(name='جرد 1', branch_code='MS1', status='draft')
        self.s2 = mk(name='جرد 2', branch_code='MS2', status='snapshot_taken')
        self.s3 = mk(name='جرد 3', branch_code='MS1', status='closed')

    def ids(self, client=None, **params):
        r = (client or self.admin_c).get(self.URL, params)
        self.assertEqual(r.status_code, 200)
        return {x['id'] for x in _rows(r)}

    def test_two_statuses_are_the_union(self):
        self.assertEqual(self.ids(status='draft,closed'), {self.s1.id, self.s3.id})

    def test_one_status_and_none(self):
        self.assertEqual(self.ids(status='snapshot_taken'), {self.s2.id})
        self.assertEqual(self.ids(), {self.s1.id, self.s2.id, self.s3.id})

    def test_branch_code_list(self):
        self.assertEqual(self.ids(branch_code='MS1,MS2'), {self.s1.id, self.s2.id, self.s3.id})
        self.assertEqual(self.ids(branch_code='MS2'), {self.s2.id})

    def test_branch_user_never_widened(self):
        self.assertEqual(self.ids(self.pharm_c, branch_code='MS1,MS2'), {self.s1.id, self.s3.id})
        self.assertEqual(self.ids(self.pharm_c, status='draft,snapshot_taken'), {self.s1.id})


# ── /batches: disposal ledger ─────────────────────────────────────────────────

class DisposalLedgerMultiFilterTests(_Base):
    URL = '/api/batches/stock-expiry/disposal/'

    def setUp(self):
        super().setUp()
        from apps.batches.models import ExpiryDisposalRecord
        mk = ExpiryDisposalRecord.objects.create
        self.r1 = mk(item_code='D1', branch_code='MS1', qty=Decimal('1'), decision='destroy', status='draft')
        self.r2 = mk(item_code='D2', branch_code='MS2', qty=Decimal('1'), decision='return_supplier', status='approved')
        self.r3 = mk(item_code='D3', branch_code='MS1', qty=Decimal('1'), decision='quarantine', status='done')

    def ids(self, client=None, **params):
        r = (client or self.admin_c).get(self.URL, params)
        self.assertEqual(r.status_code, 200)
        return {x['id'] for x in r.data['items']}

    def test_two_statuses_are_the_union(self):
        self.assertEqual(self.ids(status='draft,done'), {self.r1.id, self.r3.id})

    def test_one_value_and_none(self):
        self.assertEqual(self.ids(status='approved'), {self.r2.id})
        self.assertEqual(self.ids(), {self.r1.id, self.r2.id, self.r3.id})

    def test_branch_and_decision_lists(self):
        self.assertEqual(self.ids(branch='MS1,MS2', decision='destroy,return_supplier'), {self.r1.id, self.r2.id})

    def test_branch_user_never_widened(self):
        self.assertEqual(self.ids(self.pharm_c, branch='MS1,MS2'), {self.r1.id, self.r3.id})
        self.assertEqual(self.ids(self.pharm_c, branch='MS2'), set())


# ── /batches: rescue-before-expiry worklist ───────────────────────────────────

class RebalanceWorklistMultiBranchTests(TestCase):
    """worklist(branch=[…]): a line shows when it leaves OR reaches one of the branches."""

    def lines(self):
        def line(item, src, dst):
            return {'item': item, 'from': src, 'to': dst, 'batch_no': 'L', 'expiry': TODAY + dt.timedelta(days=60),
                    'days_to_expiry': 60, 'qty': 1, 'source_rate': 0.0, 'target_rate': 1.0}
        return [line('X1', '130', '140'), line('X2', '150', '160'), line('X3', '170', '130')]

    def run_worklist(self, branch):
        from apps.batches import rebalance as RB
        buckets = {'too_late': {}, 'no_target': {}}
        with mock.patch.object(RB, '_load', return_value=([], {}, {}, {}, set(), True)), \
                mock.patch.object(RB, 'plan', return_value=(self.lines(), buckets)):
            return {r['item_code'] for r in RB.worklist(branch=branch)['rows']}

    def test_two_branches_are_the_union(self):
        self.assertEqual(self.run_worklist(['140', '160']), {'X1', 'X2'})

    def test_one_value_as_before_and_none(self):
        self.assertEqual(self.run_worklist('130'), {'X1', 'X3'})
        self.assertEqual(self.run_worklist(['130']), {'X1', 'X3'})
        self.assertEqual(self.run_worklist(None), {'X1', 'X2', 'X3'})

    def test_api_reads_comma_list(self):
        seed_code_matrix()
        self.addCleanup(module_access.clear_cache)
        _, _, c = make_user('ms_rb_admin', role='admin', access_all=True)
        from apps.batches import rebalance as RB
        with mock.patch.object(RB, 'worklist', return_value={'rows': []}) as wl:
            r = c.get('/api/batches/stock-expiry/rebalance/', {'branch': '130,140'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(wl.call_args.kwargs['branch'], ['130', '140'])


# ── /batches: supplier return calendar ────────────────────────────────────────

D = dt.date
RW_TODAY = D(2026, 10, 31)


@override_settings(RBAC_ENFORCEMENT='log')
class ReturnCalendarMultiFilterTests(TestCase):
    URL = '/api/batches/return-window/'

    def setUp(self):
        from apps.batches.models import PurchaseExpiryEntry, StockExpiryBalance
        from apps.catalog.models import Item
        seed_code_matrix()
        self.addCleanup(module_access.clear_cache)
        make_branch('الرئيسي', '100')
        self.b130 = make_branch('فرع 130', '130')
        make_branch('فرع 140', '140')
        # a calendar line carries a supplier only when that supplier has a return policy (565 and 260 are
        # seeded by migration); give 999 one too, otherwise item C is never a supplier match
        from apps.procurement.models import SupplierReturnPolicy
        SupplierReturnPolicy.objects.get_or_create(supplier_code='999', defaults={'supplier_name': 'S999'})
        for code, sup in (('A', '565'), ('B', '260'), ('C', '999')):
            Item.objects.create(softech_id=code, name=f'Item {code}', cost_price=Decimal('10'))
            PurchaseExpiryEntry.objects.create(branch_code='100', supplier_code=sup, supplier_name=f'S{sup}',
                                               doc_number=code, doc_date=D(2026, 1, 1), item_code=code,
                                               entered_expiry=D(2026, 12, 15), qty=Decimal('100'))
            StockExpiryBalance.objects.create(branch_code='130', store_code='101', item_code=code, item_name=code,
                                              batch_no='L1', expiry_date=D(2026, 12, 15), qty=Decimal('2'))
        StockExpiryBalance.objects.create(branch_code='100', store_code='105', item_code='A', item_name='A',
                                          batch_no='L2', expiry_date=D(2026, 12, 15), qty=Decimal('3'))
        StockExpiryBalance.objects.create(branch_code='140', store_code='101', item_code='B', item_name='B',
                                          batch_no='L3', expiry_date=D(2026, 12, 15), qty=Decimal('3'))
        _, _, self.buyer = make_user('ms_rw_buyer', role='purchasing')
        _, _, self.ph130 = make_user('ms_rw_ph', role='pharmacist', branch=self.b130)

    def cal(self, **kw):
        from apps.batches.return_calendar import calendar
        return {(l['item_code'], l['branch_code'], l['store_code']) for l in calendar(today=RW_TODAY, **kw)['lines']}

    def api(self, client=None, **params):
        with mock.patch('apps.batches.return_calendar._today', return_value=RW_TODAY):
            r = (client or self.buyer).get(self.URL, params)
        self.assertEqual(r.status_code, 200)
        return {(l['item_code'], l['branch_code'], l['store_code']) for l in r.data['lines']}

    def test_calendar_takes_lists(self):
        self.assertEqual({k[0] for k in self.cal(supplier=['565', '260'])}, {'A', 'B'})
        self.assertEqual(self.cal(location=['105']), {('A', '100', '105')})
        self.assertEqual(self.cal(supplier='999'), {('C', '130', '101')})          # one value, as before

    def test_api_two_suppliers_union_one_and_none(self):
        self.assertEqual({k[0] for k in self.api(supplier='565,999')}, {'A', 'C'})
        self.assertEqual({k[0] for k in self.api(supplier='260')}, {'B'})
        self.assertEqual(len(self.api()), 5)

    def test_api_location_list(self):
        got = self.api(location='105,shelf')
        self.assertIn(('A', '100', '105'), got)
        self.assertIn(('B', '140', '101'), got)
        self.assertEqual(self.api(location='nonsense'), self.api())             # junk = no filter, as before

    def test_branch_user_never_widened(self):
        got = self.api(self.ph130, supplier='565,260', branch='130,140')
        self.assertEqual({k[1] for k in got}, {'130'})
        self.assertEqual({k[0] for k in got}, {'A', 'B'})

    def test_export_grid_takes_lists_supplier_sheet_needs_one(self):
        with mock.patch('apps.batches.return_calendar._today', return_value=RW_TODAY):
            grid = self.buyer.post(self.URL + 'export/', {'kind': 'grid', 'supplier_code': '565,260',
                                                         'location': 'shelf'}, format='json')
            two = self.buyer.post(self.URL + 'export/', {'kind': 'supplier', 'supplier_code': '565,260'},
                                  format='json')
            one = self.buyer.post(self.URL + 'export/', {'kind': 'supplier', 'supplier_code': '565'},
                                  format='json')
        self.assertEqual(grid.status_code, 200)
        self.assertEqual(two.status_code, 400)
        self.assertEqual(one.status_code, 200)


# ── /inventory + /analytics/sales: item operational filters ──────────────────

class InventoryItemFiltersMultiTests(_Base):
    URL = '/api/analytics/inventory/'

    def setUp(self):
        super().setUp()
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        run = DemandCalculationRun.objects.create(status='success')
        for i, (level, trans, branch) in enumerate(((1, 'A', self.b1), (2, 'B', self.b1), (3, 'C', self.b2)), 1):
            it = make_item(f'صنف {i}', f'MSI{i}')
            it.item_level, it.branch_trans, it.supplier_trans, it.customer_trans = level, trans, trans, trans
            it.save()
            ItemDemandMetrics.objects.create(run=run, item=it, branch=branch, calc_date=TODAY)

    def total(self, client=None, **params):
        r = (client or self.admin_c).get(self.URL, params)
        self.assertEqual(r.status_code, 200, r.data)
        return r.data['total_items']

    def test_two_levels_are_the_union(self):
        self.assertEqual(self.total(item_level='1,3'), 2)

    def test_one_value_and_none(self):
        self.assertEqual(self.total(item_level='2'), 1)
        self.assertEqual(self.total(), 3)
        self.assertEqual(self.total(item_level='x'), 3)            # junk is ignored, as before

    def test_movement_lists(self):
        self.assertEqual(self.total(branch_trans='A,C'), 2)
        self.assertEqual(self.total(supplier_trans='B'), 1)
        self.assertEqual(self.total(customer_trans='A,B', item_level='2,3'), 1)

    def test_branch_user_never_widened(self):
        self.assertEqual(self.total(self.pharm_c, item_level='1,2,3'), 2)


class SalesLineItemFiltersMultiTests(TestCase):
    """_line_qs_for — the sales dashboard's item filters — reads the same comma lists."""

    def test_line_filters_take_lists(self):
        from apps.analytics.views import _line_qs_for
        from apps.customers.models import PurchaseHistory
        qs = PurchaseHistory.objects.all()
        sql_two = str(_line_qs_for(qs, {'item_level': '1,2', 'branch_trans': 'A,B'}).query)
        sql_one = str(_line_qs_for(qs, {'item_level': '1'}).query)
        self.assertIn('"item_level" IN (1, 2)', sql_two)
        self.assertIn('"branch_trans" IN (A, B)', sql_two)
        self.assertIn('"item_level" = 1', sql_one)
        self.assertEqual(str(_line_qs_for(qs, {}).query), str(_line_qs_for(qs, {'item_level': ''}).query))
