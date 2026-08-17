"""
apps/tests/test_pos_models.py

Model mappings/lifecycle + the read-only reconciler (with a fake SOFTECH reader).
"""
from decimal import Decimal
from django.test import TestCase

from apps.pos_orders.models import (
    SoftechSalesOrder, SoftechSalesOrderLine, SoftechSalesOrderPayment,
)
from apps.pos_orders import reconcile
from .factories import make_branch


def _order(**kw):
    br = make_branch()
    return SoftechSalesOrder.objects.create(
        branch=br, softech_branchcode=br.softech_branch_id, store_code='130',
        softech_pic='130HD9668', **kw)


class ClaimSerializerTests(TestCase):
    def test_claim_maps_into_source_companies_raw(self):
        from apps.pos_orders.serializers import OrderSerializer
        br = make_branch()
        s = OrderSerializer(data={
            'branch': br.id, 'channel': 'contract', 'doc_kind': 'sale',
            'softech_pic': '130HD9668',
            'claim': {'patientname': 'X', 'patientno': '500145123261',
                      'membershipno': 'dms', 'examdate': '2026-06-21'},
            'lines': [{'softech_itemcode': '404', 'qty': 1, 'item_sale_price': 10}],
        })
        s.is_valid(raise_exception=True)
        order = s.save()
        raw = order.source_companies_raw
        self.assertEqual(raw['patientno'], '500145123261')
        self.assertEqual(raw['membershipno'], 'dms')
        self.assertEqual(raw['examdate'], {'__dt__': '2026-06-21 00:00:00'})


class MappingTests(TestCase):
    def test_doccode_mapping(self):
        self.assertEqual(_order(doc_kind='sale').softech_doccode, '115')
        self.assertEqual(_order(doc_kind='return').softech_doccode, '30')

    def test_ptclassif_mapping(self):
        self.assertEqual(_order(channel='cash').softech_ptclassifcode, '91')
        self.assertEqual(_order(channel='delivery').softech_ptclassifcode, '90')
        self.assertEqual(_order(channel='contract').softech_ptclassifcode, '10')
        self.assertEqual(_order(channel='insurance').softech_ptclassifcode, '15')

    def test_counter_column_mapping(self):
        self.assertEqual(_order(doc_kind='sale').softech_counter_column, 'lastdocnumberout_cust')
        self.assertEqual(_order(doc_kind='return').softech_counter_column, 'lastdocnumberin_cust')

    def test_payment_type_mapping(self):
        o = _order()
        self.assertEqual(SoftechSalesOrderPayment(order=o, pay_type='cash').softech_paymenttype, '30')
        self.assertEqual(SoftechSalesOrderPayment(order=o, pay_type='credit').softech_paymenttype, '10')
        self.assertEqual(SoftechSalesOrderPayment(order=o, pay_type='card').softech_paymenttype, '40')

    def test_is_locked_transitions(self):
        o = _order()
        self.assertFalse(o.is_locked)                                  # draft
        o.status = SoftechSalesOrder.STATUS_READY
        self.assertFalse(o.is_locked)                                  # ready
        for st in ('pushing', 'pushed', 'settled', 'cancelled'):
            o.status = st
            self.assertTrue(o.is_locked, st)


class ReconcileTests(TestCase):
    class FakeReader:
        def __init__(self, exists, final):
            self._exists, self._final = exists, final
        def pending_exists(self, order):
            return self._exists
        def final_doc(self, order):
            return self._final

    def _pushed(self, **kw):
        o = _order(doc_kind=kw.pop('doc_kind', 'sale'), **kw)
        o.status = SoftechSalesOrder.STATUS_PUSHED
        o.softech_docnumber = 468769
        o.save()
        return o

    def test_still_pending_unchanged(self):
        o = self._pushed()
        reconcile.reconcile_order(o, self.FakeReader(exists=True, final=None))
        o.refresh_from_db()
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_PUSHED)

    def test_settled_when_final_doc_found(self):
        o = self._pushed()
        reconcile.reconcile_order(o, self.FakeReader(exists=False, final=Decimal('452724')))
        o.refresh_from_db()
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_SETTLED)
        self.assertEqual(o.softech_final_docnumber, Decimal('452724'))

    def test_gone_but_no_final_left_unchanged(self):
        # never auto-cancel on an uncertain read — surfaced for manual review
        o = self._pushed()
        reconcile.reconcile_order(o, self.FakeReader(exists=False, final=None))
        o.refresh_from_db()
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_PUSHED)

    def test_non_pushed_ignored(self):
        o = _order()  # draft, no docnumber
        reconcile.reconcile_order(o, self.FakeReader(exists=False, final=Decimal('1')))
        o.refresh_from_db()
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_DRAFT)
