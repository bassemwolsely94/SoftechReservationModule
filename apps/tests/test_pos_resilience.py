"""
apps/tests/test_pos_resilience.py — offline / SOFTECH-down behaviour.

Guarantees verified here:
  • push is IDEMPOTENT — an order already in SOFTECH is never re-written (no duplicate doc).
  • connectivity errors are classified as "unreachable" (→ queue) vs real errors (→ fail).
"""
from decimal import Decimal
from django.test import TestCase

from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
from apps.pos_orders import writer
from .factories import make_branch


def _order(**kw):
    br = make_branch()
    return SoftechSalesOrder.objects.create(
        branch=br, softech_branchcode=br.softech_branch_id, store_code='130', **kw)


class ResilienceTests(TestCase):
    def test_push_is_idempotent_when_already_pushed(self):
        o = _order(channel='cash', status=SoftechSalesOrder.STATUS_PUSHED,
                   softech_docnumber=468900)
        SoftechSalesOrderLine.objects.create(order=o, softech_itemcode='1', qty=1, item_sale_price=10)
        res = writer.push_order(o, dry_run=False)         # must NOT contact SOFTECH or re-write
        self.assertTrue(res['already_pushed'])
        self.assertFalse(res['wrote_to_softech'])
        self.assertEqual(res['docnumber'], 468900)

    def test_settled_order_not_repushed(self):
        o = _order(channel='cash', status=SoftechSalesOrder.STATUS_SETTLED, softech_docnumber=452800)
        res = writer.push_order(o, dry_run=False)
        self.assertTrue(res['already_pushed'])

    def test_unreachable_classifier(self):
        self.assertTrue(writer._is_unreachable(Exception('JZ006: Caught IOException: ConnectException: Connection timed out')))
        self.assertTrue(writer._is_unreachable(Exception('java.net.ConnectException: Connection refused')))
        self.assertFalse(writer._is_unreachable(Exception('Implicit conversion from VARCHAR to DECIMAL')))
        self.assertFalse(writer._is_unreachable(Exception('verify-readback mismatch')))

    def test_queued_status_is_retryable_not_locked(self):
        o = _order(channel='cash', status=SoftechSalesOrder.STATUS_QUEUED)
        self.assertFalse(o.is_locked)                     # queued orders can still be retried/edited
