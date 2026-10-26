"""
SOFTECH write safety — writers that trusted their CALLER to check the switch (Batch 2, P-9).

A writer function must refuse on its own: a new command, job or view that calls it directly
must not write to SOFTECH just because it forgot the check.

  * pos_orders.pos_cancel_writer.write_pos_cancel_batch(dry_run=False) → POS_CANCEL_WRITE_ENABLED
  * finance.recon_writer.fix_due_before(commit=True)                    → AP_RECONCILE_WRITER_ENABLED
  * invoices.supplier_items.inject_mapping(commit=True)                 → INVOICE_SUPPLIER_ITEM_WRITE_ENABLED
    inject_mapping(commit=False) runs the real batch and rolls back    → SOFTECH_PROBES_ENABLED (as P-7)
"""
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings

from .routes import Tripwire


class _NoCursor:
    """A SOFTECH connection that must never be used."""
    used = False

    def cursor(self):
        _NoCursor.used = True
        raise AssertionError('SOFTECH connection used')


INVOICE = SimpleNamespace(branchcode='130', doccode='10', docnumber='5', docdate='2026-10-01')


@override_settings(POS_CANCEL_WRITE_ENABLED=False)
class PosCancelWriterTests(TestCase):

    def test_live_write_refused_when_switched_off(self):
        from apps.pos_orders.pos_cancel_writer import write_pos_cancel_batch
        with Tripwire() as tw:
            with self.assertRaisesMessage(Exception, 'POS_CANCEL_WRITE_ENABLED'):
                write_pos_cancel_batch(dry_run=False)
        self.assertEqual(tw.softech_calls, [])

    def test_dry_run_still_allowed(self):
        from apps.pos_orders.pos_cancel_writer import write_pos_cancel_batch
        self.assertTrue(write_pos_cancel_batch()['dry_run'])


class ApDueBeforeTests(SimpleTestCase):

    @override_settings(AP_RECONCILE_WRITER_ENABLED=False)
    def test_commit_refused_before_softech_when_switched_off(self):
        from apps.finance.recon_writer import ReconWriteError, fix_due_before
        _NoCursor.used = False
        with self.assertRaisesMessage(ReconWriteError, 'AP_RECONCILE_WRITER_ENABLED'):
            fix_due_before(INVOICE, [], conn=_NoCursor(), commit=True)
        self.assertFalse(_NoCursor.used)


class SupplierItemInjectTests(SimpleTestCase):

    @override_settings(INVOICE_SUPPLIER_ITEM_WRITE_ENABLED=False)
    def test_commit_refused_when_switched_off(self):
        from apps.invoices.supplier_items import inject_mapping
        _NoCursor.used = False
        with self.assertRaisesMessage(Exception, 'INVOICE_SUPPLIER_ITEM_WRITE_ENABLED'):
            inject_mapping(_NoCursor(), '30', 'IT001', 'V-1', commit=True)
        self.assertFalse(_NoCursor.used)

    @override_settings(INVOICE_SUPPLIER_ITEM_WRITE_ENABLED=True, SOFTECH_PROBES_ENABLED=False)
    def test_rollback_rehearsal_needs_the_probes_switch(self):
        from apps.invoices.supplier_items import inject_mapping
        _NoCursor.used = False
        with self.assertRaisesMessage(ValueError, 'SOFTECH_PROBES_ENABLED'):
            inject_mapping(_NoCursor(), '30', 'IT001', 'V-1', commit=False)
        self.assertFalse(_NoCursor.used)

    @override_settings(INVOICE_SUPPLIER_ITEM_WRITE_ENABLED=True)
    def test_switched_on_commit_reaches_softech(self):
        from apps.invoices.supplier_items import inject_mapping
        _NoCursor.used = False
        with self.assertRaises(AssertionError):
            inject_mapping(_NoCursor(), '30', 'IT001', 'V-1', commit=True)
        self.assertTrue(_NoCursor.used)
