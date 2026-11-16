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


@override_settings(INVOICE_WRITER_ENABLED=True, WRITER_INSTANCE=True)
class InvoiceOutcomeUnknownTests(TestCase):
    """Full audit 2026-11-15: S-4 any error after the batch was sent = outcome unknown; S-3 a number-less
    purchase is not blindly retried, and a same-digits SOFTECH document with another total is not adopted."""

    def setUp(self):
        self.br = make_branch()
        self.item = make_item(softech_id='90792')
        self.vendor = VendorProfile.objects.create(name='V', softech_personcode='5014', is_main=True)

    def _inv(self, number='777', **kw):
        inv = SupplierInvoice.objects.create(branch=self.br, vendor=self.vendor, supplier_name='S',
                                             invoice_number=number, status='confirmed', **kw)
        InvoiceLine.objects.create(invoice=inv, item=self.item, manual_name='X',
                                   quantity=5, public_price=28, unit_price=22)
        return inv

    def _patches(self, dup_row=None, batch=None):
        ok = {'ok': True, 'errors': [], 'warnings': [], 'notices': []}
        return [mock.patch.object(writer, 'build_plan', return_value={}),
                mock.patch('apps.invoices.validations.validate_invoice', return_value=ok),
                mock.patch.object(writer, 'branch_host', return_value='h'),
                mock.patch.object(writer, 'compute', return_value=([], {})),
                mock.patch('config.sybase.get_branch_connection', return_value=mock.MagicMock()),
                mock.patch.object(writer, '_q1', return_value=dup_row),
                mock.patch.object(writer, 'read_stkbal', return_value={}),
                mock.patch.object(writer, 'read_supplier', return_value={'ptclassifcode': '1'}),
                mock.patch.object(writer, '_run_write_batch', side_effect=batch)]

    def _push(self, inv, dup_row=None, batch=None):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in self._patches(dup_row, batch):
                stack.enter_context(p)
            return writer.push_final(inv, dry_run=False, usercode='1509')

    def test_connection_reset_after_send_is_outcome_unknown(self):
        inv = self._inv()
        with self.assertRaises(RuntimeError):
            self._push(inv, batch=RuntimeError('JZ006: Caught IOException: Connection reset'))
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'push_failed')
        self.assertTrue(inv.erp_error.startswith(writer.TIMEOUT_UNKNOWN), inv.erp_error)

    def test_numberless_purchase_waits_for_a_check_after_an_unknown_outcome(self):
        inv = self._inv(number='بدون رقم')
        inv.status, inv.erp_error = 'push_failed', writer.TIMEOUT_UNKNOWN + 'socket closed'
        inv.save(update_fields=['status', 'erp_error'])
        with mock.patch('config.sybase.get_branch_connection') as connect:
            res = writer.push_final(inv, dry_run=False, usercode='1509')
        self.assertEqual(res['mode'], 'timeout_unknown')
        connect.assert_not_called()

    def test_same_digits_other_total_is_not_adopted(self):
        inv = self._inv(number='A-123')
        with mock.patch.object(writer, '_our_invoice_signature', return_value=(1000.0, set(), 1, None)):
            res = self._push(inv, dup_row=(555, 5000))
        self.assertEqual(res['mode'], 'duplicate_mismatch')
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'push_failed')
        self.assertIsNone(inv.softech_docnumber)
        self.assertTrue(inv.erp_error.startswith(writer.DUPLICATE_MISMATCH))

    def test_same_document_is_still_adopted(self):
        inv = self._inv(number='123')
        with mock.patch.object(writer, '_our_invoice_signature', return_value=(1000.0, set(), 1, None)):
            res = self._push(inv, dup_row=(555, 1004))
        self.assertEqual(res['mode'], 'idempotent')
        inv.refresh_from_db()
        self.assertEqual((inv.status, int(inv.softech_docnumber)), ('finalized', 555))
