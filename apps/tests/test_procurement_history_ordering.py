"""Sortable headers on the purchase-history grid: whitelisted ?ordering= on /api/procurement/history/."""
import datetime
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.procurement.models import PurchaseLine
from apps.procurement.views import history_order_by

from .factories import make_admin


class HistoryOrderByTests(SimpleTestCase):
    def test_whitelist_and_default(self):
        self.assertEqual(history_order_by('-net_value'), ('-net_value', 'id'))
        self.assertEqual(history_order_by('item_name'), ('item__name', 'id'))
        self.assertEqual(history_order_by('-supplier_code'), ('-supplier_code', 'id'))
        self.assertEqual(history_order_by(''), ('-doc_date', 'id'))
        self.assertEqual(history_order_by('password; drop'), ('-doc_date', 'id'))


class HistoryOrderingApiTests(TestCase):
    def setUp(self):
        _, _, self.client_ = make_admin('hist_admin')
        for i, (sup, val) in enumerate((('B1', 30), ('A1', 10), ('C1', 20))):
            PurchaseLine.objects.create(
                branch_code='100', supplier_code=sup, doc_number=f'H{i}', doccode='10',
                doc_date=datetime.date(2026, 10, 1 + i), item_code='X1',
                net_qty=Decimal(1), raw_qty=Decimal(1), net_value=Decimal(val), raw_value=Decimal(val))

    def codes(self, ordering):
        r = self.client_.get('/api/procurement/history/', {'ordering': ordering} if ordering else {})
        self.assertEqual(r.status_code, 200)
        return [x['supplier_code'] for x in (r.data if isinstance(r.data, list) else r.data['results'])]

    def test_orders_by_value_both_ways(self):
        self.assertEqual(self.codes('net_value'), ['A1', 'C1', 'B1'])
        self.assertEqual(self.codes('-net_value'), ['B1', 'C1', 'A1'])

    def test_orders_by_supplier(self):
        self.assertEqual(self.codes('supplier_code'), ['A1', 'B1', 'C1'])

    def test_unknown_ordering_falls_back_to_newest(self):
        self.assertEqual(self.codes('nonsense'), ['C1', 'A1', 'B1'])
        self.assertEqual(self.codes(''), ['C1', 'A1', 'B1'])


class SegmentationOrderingApiTests(TestCase):
    def setUp(self):
        from apps.procurement.models import SupplierSegmentation
        _, _, self.client_ = make_admin('seg_admin')
        for code, name, inv in (('S2', 'Beta', 5), ('S1', 'Alpha', 9), ('S3', 'Gamma', 1)):
            SupplierSegmentation.objects.create(supplier_code=code, supplier_name=name, invoice_count_365d=inv)

    def codes(self, ordering):
        r = self.client_.get('/api/procurement/segments/', {'ordering': ordering})
        self.assertEqual(r.status_code, 200)
        return [x['supplier_code'] for x in r.data['results']]

    def test_header_orderings(self):
        self.assertEqual(self.codes('supplier_name'), ['S1', 'S2', 'S3'])
        self.assertEqual(self.codes('-invoice_count_365d'), ['S1', 'S2', 'S3'])
        self.assertEqual(self.codes('invoice_count_365d'), ['S3', 'S2', 'S1'])
        self.assertEqual(self.codes('-supplier_code'), ['S3', 'S2', 'S1'])


class EveryOrderingFieldTests(TestCase):
    """Rule 9: each whitelisted field exists, asc and desc, on both grids."""
    def test_history_and_segments(self):
        from apps.procurement.views import _HIST_ORDER_FIELDS
        _, _, c = make_admin('ord_all')
        for f in _HIST_ORDER_FIELDS:
            for o in (f, '-' + f):
                self.assertEqual(c.get('/api/procurement/history/', {'ordering': o}).status_code, 200, o)
        for f in ('purchase_value_365d', 'supplier_category', 'foc_rate_pct', 'return_pct', 'supplier_code',
                  'supplier_name', 'ptcode', 'ptclassifcode', 'invoice_count_365d', 'manual_override'):
            for o in (f, '-' + f):
                self.assertEqual(c.get('/api/procurement/segments/', {'ordering': o}).status_code, 200, o)
