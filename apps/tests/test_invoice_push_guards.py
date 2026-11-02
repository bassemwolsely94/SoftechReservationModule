"""
W1 supplier-invoice push guards: quantity / value plausibility sized on a year of
purchases (owner 2026-11-01), and the atomic «pushing» flip that stops a double post.
No SOFTECH connection is used (live=False / writer gate off / mocked).
"""
from datetime import date
from unittest import mock

from django.test import TestCase, override_settings

from apps.invoices import validations, writer
from apps.invoices.models import SupplierInvoice, InvoiceLine, VendorProfile
from apps.stock_audit.models import StockLedgerLine
from .factories import make_branch, make_item

_n = iter(range(1, 100000))


class InvoiceQtyGuardTests(TestCase):
    def setUp(self):
        self.br = make_branch()
        self.item = make_item(softech_id='90792')
        self.vendor = VendorProfile.objects.create(name='V', softech_personcode='5014', is_main=True)
        for q in (10, 12, 8):                         # three earlier purchases, largest = 12
            StockLedgerLine.objects.create(branchcode='100', doccode='10', docnumber=next(_n),
                                           docdate=date(2026, 9, 1), itemcode='90792', transqty=q)

    def _codes(self, qty, price=20, item=None):
        inv = SupplierInvoice.objects.create(branch=self.br, vendor=self.vendor, supplier_name='S',
                                             invoice_number=str(next(_n)), status='confirmed')
        InvoiceLine.objects.create(invoice=inv, item=item or self.item, manual_name='X',
                                   quantity=qty, public_price=28, unit_price=price)
        v = validations.validate_invoice(inv, live=False)
        return {e['code'] for e in v['errors']}, {w['code'] for w in v['warnings']}

    def test_normal_quantity_is_clean(self):
        errs, warns = self._codes(20)              # < 3 × 12
        self.assertFalse({'qty_spike', 'qty_absurd'} & (errs | warns))

    def test_over_three_times_needs_a_reason(self):
        errs, warns = self._codes(40)              # > 36
        self.assertIn('qty_spike', warns)
        self.assertNotIn('qty_absurd', errs)

    def test_over_twenty_times_and_500_units_is_refused(self):
        errs, _ = self._codes(600)                 # > 240 and > 500
        self.assertIn('qty_absurd', errs)
        errs, warns = self._codes(300, price=1)    # > 20× but under 500 units → reason only
        self.assertNotIn('qty_absurd', errs)
        self.assertIn('qty_spike', warns)

    def test_new_item_and_line_value(self):
        new = make_item(softech_id='11111')
        _, warns = self._codes(250, item=new)
        self.assertIn('qty_high_new_item', warns)
        _, warns = self._codes(30, price=2000)     # 60,000 EGP line
        self.assertIn('line_value_high', warns)


@override_settings(INVOICE_WRITER_ENABLED=True, WRITER_INSTANCE=True)
class InvoiceAtomicPushTests(TestCase):
    def setUp(self):
        self.br = make_branch()
        item = make_item(softech_id='90792')
        vendor = VendorProfile.objects.create(name='V', softech_personcode='5014', is_main=True)
        self.inv = SupplierInvoice.objects.create(branch=self.br, vendor=vendor, supplier_name='S',
                                                  invoice_number='777', status='confirmed')
        InvoiceLine.objects.create(invoice=self.inv, item=item, manual_name='X',
                                   quantity=5, public_price=28, unit_price=22)

    def test_second_request_with_a_stale_copy_never_writes(self):
        stale = SupplierInvoice.objects.get(pk=self.inv.pk)       # read before the other push
        SupplierInvoice.objects.filter(pk=self.inv.pk).update(status='pushing')   # the first push won
        with mock.patch.object(writer, 'build_plan', return_value={}), \
             mock.patch('apps.invoices.validations.validate_invoice',
                        return_value={'ok': True, 'errors': [], 'warnings': [], 'notices': []}), \
             mock.patch.object(writer, 'branch_host', return_value='h'), \
             mock.patch.object(writer, 'compute', return_value=([], {})), \
             mock.patch('config.sybase.get_branch_connection') as conn:
            with self.assertRaises(ValueError):
                writer.push_final(stale, dry_run=False, usercode='1509')
        conn.assert_not_called()
        self.assertEqual(SupplierInvoice.objects.get(pk=self.inv.pk).status, 'pushing')
