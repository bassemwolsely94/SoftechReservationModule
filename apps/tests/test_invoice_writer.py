"""
apps/tests/test_invoice_writer.py

Covers the supplier-invoice (purchase) writeback WITHOUT any SOFTECH contact:
  - pricing.compute_line / compute_header reproduce the captured golden values
  - build_plan shape: doccode 10/120, counter column, supplier personcode mapping
  - docnumber2 = numeric supplier invoice no; non-numeric → 0
  - returns (doccode 120) carry r_docnumber
  - GATE: push_final never writes when INVOICE_WRITER_ENABLED is off (dry-run plan)
  - guards: no matched lines / unlinked supplier raise
"""
from django.test import TestCase, override_settings

from apps.invoices import pricing, writer
from apps.invoices.models import SupplierInvoice, InvoiceLine, VendorProfile
from .factories import make_branch, make_item


# ── pure pricing (no DB) ────────────────────────────────────────────────────
class PricingTests(TestCase):
    def test_golden_haloperidol(self):
        c = pricing.compute_line(public_price=28.0, unit_price=22.10, qty=5)
        self.assertEqual(c['transprice'], 22.10)
        self.assertEqual(c['transprice_total'], 110.5)
        self.assertEqual(c['newcostprice'], 22.10)
        self.assertAlmostEqual(c['pharmacydiscp'], 21.0714, places=3)

    def test_net_derived_from_discount(self):
        c = pricing.compute_line(public_price=38.0, unit_price=0, qty=10, discount_pct=25)
        self.assertEqual(c['transprice'], 28.5)
        self.assertEqual(c['transprice_total'], 285.0)
        self.assertEqual(c['pharmacydiscp'], 25.0)

    def test_vat_splits_pretax_and_tax(self):
        c = pricing.compute_line(public_price=114.0, unit_price=100.0, qty=2, vat_pct=14)
        self.assertEqual(c['itemsaleprice_tax'], 100.0)        # 114 / 1.14
        self.assertAlmostEqual(c['itemsalestax'], 24.5614, places=3)

    def test_header_leaves_breakdown_zero(self):
        lines = [pricing.compute_line(public_price=28.0, unit_price=22.10, qty=5)]
        h = pricing.compute_header(lines)
        self.assertEqual(h['doc_value'], 110.5)
        self.assertEqual((h['doc_value1'], h['doc_value2'], h['doc_value3']), (0.0, 0.0, 0.0))


# ── build_plan / mapping (DB, but NO SOFTECH) ───────────────────────────────
def _invoice(doc_kind='purchase', personcode='5014', invoice_number='5623', **kw):
    br = make_branch()
    vendor = VendorProfile.objects.create(name=f'V-{personcode}', softech_personcode=personcode)
    inv = SupplierInvoice.objects.create(
        branch=br, vendor=vendor, doc_kind=doc_kind, supplier_name='PHARMA OVER SEAS',
        invoice_number=invoice_number, status='confirmed', **kw)
    item = make_item(softech_id='90792')
    InvoiceLine.objects.create(invoice=inv, item=item, manual_name='HALOPERIDOL',
                               quantity=5, public_price=28, unit_price=22.10)
    return inv


class BuildPlanTests(TestCase):
    def test_purchase_plan_shape(self):
        inv = _invoice()
        plan = writer.build_plan(inv)
        self.assertEqual(plan['doccode'], '10')
        self.assertEqual(plan['counter'], 'lastdocnumberin_supp')
        self.assertEqual(plan['doc_value'], 110.5)
        h = plan['header']
        self.assertEqual(h['ptcode'], '20')
        self.assertEqual(h['cust_branch_code'], '5014')   # supplier personcode
        self.assertEqual(h['docnumber2'], 5623)           # numeric supplier invoice no
        self.assertEqual(h['docvalue1'], 0)               # purchases don't populate 1/2/3
        self.assertEqual(len(plan['lines']), 1)
        self.assertEqual(plan['lines'][0]['suppliercode'], '5014')

    def test_branchcode_defaults_from_branch(self):
        inv = _invoice()
        self.assertEqual(inv.softech_branchcode, inv.branch.softech_branch_id)
        self.assertEqual(inv.store_code, inv.softech_branchcode)

    def test_return_uses_out_counter_and_rdoc(self):
        inv = _invoice(doc_kind='return', return_of_docnumber=452723)
        plan = writer.build_plan(inv)
        self.assertEqual(plan['doccode'], '120')
        self.assertEqual(plan['counter'], 'lastdocnumberout_supp')
        self.assertEqual(plan['lines'][0]['r_docnumber'], 452723)
        self.assertEqual(plan['lines'][0]['r_doccode'], '10')

    def test_non_numeric_invoice_number_becomes_zero(self):
        inv = _invoice(invoice_number='INV/ABC')          # no digits at all
        self.assertEqual(writer.build_plan(inv)['header']['docnumber2'], 0)

    def test_invoice_number_keeps_digits_only(self):
        inv = _invoice(invoice_number='INV-12-34')        # digits → 1234
        self.assertEqual(writer.build_plan(inv)['header']['docnumber2'], 1234)

    def test_unlinked_supplier_raises(self):
        br = make_branch()
        v = VendorProfile.objects.create(name='NoCode')   # no softech_personcode
        inv = SupplierInvoice.objects.create(branch=br, vendor=v, status='confirmed')
        item = make_item(softech_id='90792')
        InvoiceLine.objects.create(invoice=inv, item=item, quantity=1, public_price=10, unit_price=8)
        with self.assertRaises(ValueError):
            writer.build_plan(inv)

    def test_no_matched_lines_raises(self):
        br = make_branch()
        v = VendorProfile.objects.create(name='V', softech_personcode='1')
        inv = SupplierInvoice.objects.create(branch=br, vendor=v, status='confirmed')
        InvoiceLine.objects.create(invoice=inv, item=None, quantity=1, public_price=10)  # unmatched
        with self.assertRaises(ValueError):
            writer.build_plan(inv)


# ── gate (NO SOFTECH write) ─────────────────────────────────────────────────
class GateTests(TestCase):
    @override_settings(INVOICE_WRITER_ENABLED=False)
    def test_push_disabled_returns_dry_run(self):
        inv = _invoice()
        res = writer.push_final(inv, dry_run=False)   # even dry_run=False stays dry while gated
        self.assertEqual(res['mode'], 'dry_run')
        self.assertFalse(res['wrote_to_softech'])
        self.assertIn('plan', res)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'confirmed')     # unchanged — nothing written
