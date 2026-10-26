"""
Tests for apps/invoices/reconcile.py — deterministic arithmetic self-repair of
OCR'd line numbers (net cost + quantity) from the line's own redundancy.
"""
from django.test import SimpleTestCase

from apps.invoices import reconcile as rc


class ReconcileTests(SimpleTestCase):

    def test_fills_missing_net_from_public_and_discount(self):
        out, notes = rc.reconcile_numbers({
            'public_price': 100, 'disc_pct': 20, 'extra_disc_pct': 0,
            'special_disc_pct': 0, 'net': 0, 'quantity': 5, 'line_total': 400})
        self.assertAlmostEqual(out['net'], 80.0, places=2)
        self.assertTrue(notes)

    def test_repairs_garbled_net_when_two_sources_agree(self):
        # OCR net misread as 8.0; public×disc = 80 and total÷qty = 80 agree → repair
        out, notes = rc.reconcile_numbers({
            'public_price': 100, 'disc_pct': 20, 'extra_disc_pct': 0,
            'special_disc_pct': 0, 'net': 8.0, 'quantity': 5, 'line_total': 400})
        self.assertAlmostEqual(out['net'], 80.0, places=2)
        self.assertTrue(any('مُصحّحة' in x for x in notes))

    def test_keeps_net_when_it_agrees_with_derivations(self):
        out, notes = rc.reconcile_numbers({
            'public_price': 100, 'disc_pct': 20, 'extra_disc_pct': 0,
            'special_disc_pct': 0, 'net': 80.0, 'quantity': 5, 'line_total': 400})
        self.assertAlmostEqual(out['net'], 80.0, places=2)
        self.assertEqual(notes, [])

    def test_does_not_override_net_on_a_single_source(self):
        # only public×disc available (no total÷qty); must NOT override a present net
        out, notes = rc.reconcile_numbers({
            'public_price': 100, 'disc_pct': 20, 'extra_disc_pct': 0,
            'special_disc_pct': 0, 'net': 50.0, 'quantity': 0, 'line_total': 0})
        self.assertAlmostEqual(out['net'], 50.0, places=2)   # kept — one source can't override

    def test_three_compounding_discounts(self):
        out, _ = rc.reconcile_numbers({
            'public_price': 268.5, 'disc_pct': 25, 'extra_disc_pct': 0,
            'special_disc_pct': 0, 'net': 0, 'quantity': 2, 'line_total': 402.75})
        self.assertAlmostEqual(out['net'], 201.375, places=2)

    def test_repairs_quantity_from_total_and_net(self):
        # qty misread as 82; total 400 / net 80 = 5 → repair to 5
        out, notes = rc.reconcile_numbers({
            'public_price': 0, 'disc_pct': 0, 'extra_disc_pct': 0, 'special_disc_pct': 0,
            'net': 80.0, 'quantity': 82, 'line_total': 400})
        self.assertEqual(out['quantity'], 5.0)
        self.assertTrue(any('الكمية' in x for x in notes))

    def test_no_change_when_nothing_derivable(self):
        out, notes = rc.reconcile_numbers({
            'public_price': 0, 'disc_pct': 0, 'extra_disc_pct': 0, 'special_disc_pct': 0,
            'net': 55.0, 'quantity': 3, 'line_total': 0})
        self.assertAlmostEqual(out['net'], 55.0, places=2)
        self.assertEqual(out['quantity'], 3)
        self.assertEqual(notes, [])

    def test_parse_structured_applies_reconciliation(self):
        # end-to-end through parse_structured: a garbled net is repaired
        from apps.invoices import ocr
        data = {'lines': [{
            'item_name': 'دواء تجريبي', 'public_price': 100, 'discount_pct': 20,
            'pharmacist_price': 8.0, 'quantity': 5, 'line_total': 400}]}
        _, lines = ocr.parse_structured(data)
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(lines[0]['unit_price'], 80.0, places=2)
        self.assertTrue(lines[0].get('_reconciled'))
