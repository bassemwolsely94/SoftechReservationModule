"""
apps/tests/test_multi_select_purchasing.py

Multi-select list filters (core/multi_filter.py) on the purchasing screens: the demand engine's
«بالفرع» list and its Excel export, suggested transfers, procurement alerts, phantom sales,
supplier invoices and the purchase-price comparison export. Two values → the union, one value →
as before, nothing → everything. Read-only API calls; nothing here touches SOFTECH.
"""
from datetime import date
from decimal import Decimal

from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.catalog.models import Item
from apps.invoices.models import SupplierInvoice
from apps.procurement.models import ProcurementAlert
from apps.purchasing.models import (DemandCalculationRun, ItemDemandMetrics,
                                    TransferRecommendation, TransferRecommendationRun)
from .factories import make_admin, make_branch, make_branch2, make_item


def _rows(r, key='id'):
    assert r.status_code == 200, (r.status_code, getattr(r, 'data', None))
    data = r.data
    rows = data.get('results', data.get('items', data)) if isinstance(data, dict) else data
    return {row[key] for row in rows}


class _Base(TestCase):
    def setUp(self):
        from apps.branches.models import Branch
        self.b1 = make_branch('فرع ١', 'P01')
        self.b2 = make_branch2('فرع ٢', 'P02')
        self.b3 = Branch.objects.create(softech_branch_id='P03', name='فرع ٣', name_ar='فرع ٣', is_active=True)
        self.user, _, self.client = make_admin('ms_purch_admin')


# ── Demand engine «بالفرع» (/api/purchasing/metrics/) + its export queryset ───
class MetricsBranchFilterTests(_Base):
    URL = '/api/purchasing/metrics/'

    def setUp(self):
        super().setUp()
        self.run = DemandCalculationRun.objects.create(status='success', calc_date=date(2026, 11, 1))
        self.item = make_item('صنف أ', 'MSP01')
        for br, abc in ((self.b1, 'A'), (self.b2, 'B'), (self.b3, 'C')):
            ItemDemandMetrics.objects.create(run=self.run, item=self.item, branch=br,
                                             calc_date=date(2026, 11, 1), abc_class=abc)

    def g(self, params):
        return _rows(self.client.get(self.URL, {'page_size': 50, **params}), 'branch_id')

    def test_branch_two_one_none(self):
        self.assertEqual(self.g({'branch': f'{self.b1.id},{self.b3.id}'}), {self.b1.id, self.b3.id})
        self.assertEqual(self.g({'branch': str(self.b2.id)}), {self.b2.id})
        self.assertEqual(self.g({}), {self.b1.id, self.b2.id, self.b3.id})

    def test_branch_repeated_param_and_junk(self):
        r = self.client.get(f'{self.URL}?branch={self.b1.id}&branch={self.b2.id}')
        self.assertEqual(_rows(r, 'branch_id'), {self.b1.id, self.b2.id})
        self.assertEqual(self.g({'branch': 'abc'}), set())          # junk → nothing, never everything

    def test_abc_tab_still_single(self):
        self.assertEqual(self.g({'abc_class': 'B'}), {self.b2.id})

    def test_export_queryset_takes_lists(self):
        from apps.purchasing.views import _build_metrics_qs
        rf = RequestFactory()

        def branches(params):
            return set(_build_metrics_qs(rf.get('/x', params), self.run).values_list('branch_id', flat=True))
        self.assertEqual(branches({'branch': f'{self.b1.id},{self.b2.id}'}), {self.b1.id, self.b2.id})
        self.assertEqual(branches({'branch': str(self.b3.id)}), {self.b3.id})
        self.assertEqual(branches({'abc_class': 'A,C'}), {self.b1.id, self.b3.id})
        self.assertEqual(branches({}), {self.b1.id, self.b2.id, self.b3.id})


# ── Suggested transfers (/api/purchasing/transfer-recs/) ───────────────────────
class TransferRecFilterTests(_Base):
    URL = '/api/purchasing/transfer-recs/'

    def setUp(self):
        super().setUp()
        drun = DemandCalculationRun.objects.create(status='success', calc_date=date(2026, 11, 1))
        trun = TransferRecommendationRun.objects.create(demand_run=drun, status='success')
        item = make_item('صنف ت', 'MSP02')

        def mk(f, t, st, abc):
            return TransferRecommendation.objects.create(run=trun, item=item, from_branch=f, to_branch=t,
                                                         quantity=Decimal('1'), status=st, abc_class=abc)
        self.r1 = mk(self.b1, self.b2, 'pending', 'A')
        self.r2 = mk(self.b2, self.b3, 'approved', 'B')
        self.r3 = mk(self.b3, self.b1, 'rejected', 'C')

    def g(self, params):
        return _rows(self.client.get(self.URL, {'page_size': 50, **params}))

    def test_status_two_one_none(self):
        self.assertEqual(self.g({'status': 'pending,approved'}), {self.r1.id, self.r2.id})
        self.assertEqual(self.g({'status': 'rejected'}), {self.r3.id})
        self.assertEqual(self.g({}), {self.r1.id, self.r2.id, self.r3.id})

    def test_abc_two_one(self):
        self.assertEqual(self.g({'abc_class': 'A,C'}), {self.r1.id, self.r3.id})
        self.assertEqual(self.g({'abc_class': 'B'}), {self.r2.id})

    def test_from_and_to_branch(self):
        self.assertEqual(self.g({'from_branch': f'{self.b1.id},{self.b2.id}'}), {self.r1.id, self.r2.id})
        self.assertEqual(self.g({'to_branch': str(self.b1.id)}), {self.r3.id})
        self.assertEqual(self.g({'from_branch': f'{self.b1.id},{self.b2.id}', 'to_branch': str(self.b3.id)}),
                         {self.r2.id})
        self.assertEqual(self.g({'from_branch': 'x'}), set())


# ── Procurement alerts (/api/procurement/alerts/) ──────────────────────────────
class AlertSeverityFilterTests(_Base):
    URL = '/api/procurement/alerts/'

    def setUp(self):
        super().setUp()

        def mk(sev):
            return ProcurementAlert.objects.create(alert_type='price_spike', severity=sev, title=sev, message='-')
        self.a1, self.a2, self.a3 = mk('critical'), mk('warning'), mk('info')

    def g(self, params):
        return _rows(self.client.get(self.URL, params))

    def test_severity_two_one_none(self):
        self.assertEqual(self.g({'severity': 'critical,info'}), {self.a1.id, self.a3.id})
        self.assertEqual(self.g({'severity': 'warning'}), {self.a2.id})
        self.assertEqual(self.g({'severity': ''}), {self.a1.id, self.a2.id, self.a3.id})

    def test_severity_with_open_only(self):
        ProcurementAlert.objects.filter(pk=self.a1.pk).update(is_resolved=True)
        self.assertEqual(self.g({'severity': 'critical,warning', 'is_resolved': 'false'}), {self.a2.id})


# ── Phantom sales (/api/purchasing/phantom/candidates/) ────────────────────────
class PhantomMedFilterTests(_Base):
    URL = '/api/purchasing/phantom/candidates/'

    def setUp(self):
        super().setUp()
        self.i1, self.i2, self.i3 = make_item('دواء', 'MSP03'), make_item('تجميل', 'MSP04'), make_item('أخرى', 'MSP05')
        for it, med in ((self.i1, '10'), (self.i2, '50'), (self.i3, '20')):
            Item.objects.filter(pk=it.pk).update(medicine_type=med, is_phantom_substitution=True)

    def g(self, params):
        return _rows(self.client.get(self.URL, params), 'item_id')

    def test_med_two_one_none(self):
        self.assertEqual(self.g({'med': '10,50'}), {self.i1.id, self.i2.id})
        self.assertEqual(self.g({'med': '20'}), {self.i3.id})
        self.assertEqual(self.g({}), {self.i1.id, self.i2.id, self.i3.id})


# ── Supplier invoices (/api/invoices/invoices/) ────────────────────────────────
class InvoiceListFilterTests(_Base):
    URL = '/api/invoices/invoices/'

    def setUp(self):
        super().setUp()

        def mk(br, st):
            return SupplierInvoice.objects.create(branch=br, status=st, created_by=self.user.staff_profile,
                                                  supplier_name='مورد')
        self.v1 = mk(self.b1, 'review')
        self.v2 = mk(self.b2, 'confirmed')
        self.v3 = mk(self.b3, 'finalized')

    def g(self, params):
        return _rows(self.client.get(self.URL, params))

    def test_branch_two_one_none(self):
        self.assertEqual(self.g({'branch': f'{self.b1.id},{self.b2.id}'}), {self.v1.id, self.v2.id})
        self.assertEqual(self.g({'branch': str(self.b3.id)}), {self.v3.id})
        self.assertEqual(self.g({}), {self.v1.id, self.v2.id, self.v3.id})
        self.assertEqual(self.g({'branch': 'junk'}), set())

    def test_status_two_one_and_combined(self):
        self.assertEqual(self.g({'status': 'review,finalized'}), {self.v1.id, self.v3.id})
        self.assertEqual(self.g({'status': 'confirmed'}), {self.v2.id})
        self.assertEqual(self.g({'status': 'review,confirmed', 'branch': str(self.b2.id)}), {self.v2.id})


# ── Purchase-price comparison export filter (apps/supply/price_history.filter_board) ──
class PurchasePriceSupplierFilterTests(SimpleTestCase):
    BOARD = {
        'items': [{'code': '1', 'name': 'MILGA', 'state': 'cheaper', 'producer': 'EVA', 'suppliers': [{'key': 'D1'}]},
                  {'code': '2', 'name': 'OTHER', 'state': 'best', 'producer': 'EVA', 'suppliers': [{'key': 'D2'}]},
                  {'code': '3', 'name': 'THIRD', 'state': 'best', 'producer': 'PHARCO', 'suppliers': [{'key': 'g:A-B'}]}],
        'suppliers': [{'key': 'D1', 'name': 'RAMCO'}, {'key': 'D2', 'name': 'IBN SINA'}, {'key': 'g:A-B', 'name': 'EGY'}],
        'state_labels': {'cheaper': 'يوجد أرخص', 'best': 'نشتري من الأفضل'},
    }

    def _codes(self, **kw):
        from apps.supply.price_history import filter_board
        f = filter_board(self.BOARD, **kw)
        return [r['code'] for r in f['items']], f

    def test_two_suppliers_union(self):
        codes, f = self._codes(supplier=['D1', 'g:A-B'])
        self.assertEqual(codes, ['1', '3'])
        self.assertEqual([s['name'] for s in f['suppliers']], ['RAMCO', 'EGY'])
        self.assertEqual(f['filters']['supplier'], 'RAMCO، EGY')

    def test_one_supplier_as_before(self):
        self.assertEqual(self._codes(supplier='D2')[0], ['2'])
        self.assertEqual(self._codes(supplier=['D2'])[0], ['2'])

    def test_no_supplier_all(self):
        codes, f = self._codes(supplier=[])
        self.assertEqual(codes, ['1', '2', '3'])
        self.assertNotIn('supplier', f['filters'])
