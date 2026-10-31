"""Owner-approved 2026-10-31: (1) the distributor's «سعر صيدلي» for margin items is
(public − pharmacist margin − distributor margin) × (1 − discount) — used as the net
fallback and as a check on an OCR'd net; (2) the OCR column slide seen on
PharmaOverseas invoice 224 is put back deterministically. Numbers are from that paper."""
from django.test import SimpleTestCase

from apps.invoices import reconcile as rc
from apps.invoices.ocr import parse_structured


class PaperFormulaTests(SimpleTestCase):
    def test_margin_lines_match_paper(self):
        cases = [  # public, disc, pm, dm, paper net
            (338, 18, 5, 5, 268.96), (70, 25, 1.5, 1.5, 50.25), (100, 20, 4, 4, 73.60),
            (192, 20, 2, 2, 150.40), (34, 20, 1.5, 1.5, 24.80), (45, 20, 1, 1, 34.40),
        ]
        for P, d, pm, dm, net in cases:
            self.assertAlmostEqual(rc.paper_net(P, (d,), pm, dm), net, places=2)

    def test_taxed_base_only_on_standard_rate(self):
        self.assertAlmostEqual(rc.paper_net(130, (20,), vat_pct=14), 91.228, places=2)
        # a VAT AMOUNT dropped into the rate field is not a rate
        self.assertAlmostEqual(rc.paper_net(130, (20,), vat_pct=12.77), 104.0, places=2)

    def test_margin_mismatch_flagged_not_overridden(self):
        out, notes = rc.reconcile_numbers({
            'public_price': 338, 'disc_pct': 18, 'net': 277.16, 'quantity': 2,
            'pharmacist_margin': 5, 'distributor_margin': 5})
        self.assertEqual(out['net'], 277.16)
        self.assertIn(rc.MARGIN_MISMATCH_NOTE, notes)

    def test_margin_net_ok_not_flagged(self):
        _, notes = rc.reconcile_numbers({
            'public_price': 338, 'disc_pct': 18, 'net': 268.96, 'quantity': 2,
            'pharmacist_margin': 5, 'distributor_margin': 5})
        self.assertNotIn(rc.MARGIN_MISMATCH_NOTE, notes)


class ColumnShiftTests(SimpleTestCase):
    def test_untaxed_slide(self):
        out, notes = rc.repair_column_shift({
            'public_price': 338, 'disc_pct': 537.92, 'extra_disc_pct': 268.96, 'net': 0,
            'quantity': 2, 'pharmacist_margin': 5, 'distributor_margin': 5})
        self.assertEqual(notes, [rc.COLUMN_SHIFT_NOTE])
        self.assertAlmostEqual(out['net'], 268.96)
        self.assertAlmostEqual(out['disc_pct'], 18.0, places=2)
        self.assertEqual(out['extra_disc_pct'], 0)

    def test_taxed_slide(self):
        out, notes = rc.repair_column_shift({
            'public_price': 130, 'disc_pct': 91.23, 'extra_disc_pct': 25.54, 'net': 12.77,
            'quantity': 2})
        self.assertTrue(notes)
        self.assertAlmostEqual(out['net'], 91.23)
        self.assertEqual(out['vat_pct'], 14.0)
        self.assertAlmostEqual(out['disc_pct'], 20.0, places=1)

    def test_real_percentages_untouched(self):
        # 20 % and 10 % on qty 2: 20 = 10 × 2 but 10 is no plausible net of 130
        out, notes = rc.repair_column_shift({
            'public_price': 130, 'disc_pct': 20, 'extra_disc_pct': 10, 'net': 0, 'quantity': 2})
        self.assertEqual(notes, [])
        self.assertEqual(out['disc_pct'], 20)

    def test_normal_taxed_line_untouched(self):
        _, notes = rc.repair_column_shift({
            'public_price': 130, 'disc_pct': 20, 'extra_disc_pct': 0, 'net': 91.23, 'quantity': 2})
        self.assertEqual(notes, [])


class Invoice224ReplayTests(SimpleTestCase):
    """The first and a margin line of Gemini's raw output for invoice 224."""
    RAW = {'lines': [
        {'item_name': 'سودال 100 كيس 1 جم', 'quantity': 2, 'public_price': 130.0,
         'discount_pct': 91.23, 'extra_discount_pct': 25.54, 'pharmacist_price': 12.77,
         'vat_pct': 0, 'distributor_margin_amt': 0, 'pharmacist_margin_amt': 0},
        {'item_name': 'اكترابيد بنفل 3 مل', 'quantity': 2, 'public_price': 338.0,
         'discount_pct': 537.92, 'extra_discount_pct': 268.96, 'pharmacist_price': 0.0,
         'vat_pct': 0, 'distributor_margin_amt': 5, 'pharmacist_margin_amt': 5},
    ]}

    def test_replay(self):
        _, lines = parse_structured(self.RAW)
        sweetal, actrapid = lines
        self.assertAlmostEqual(sweetal['unit_price'], 91.23)
        self.assertAlmostEqual(sweetal['discount_pct'], 20.0, places=1)
        self.assertEqual(sweetal['extra_discount_pct'], 0)
        self.assertEqual(sweetal['vat_pct'], 14.0)
        self.assertAlmostEqual(actrapid['unit_price'], 268.96)   # was 277.16
        self.assertAlmostEqual(actrapid['discount_pct'], 18.0, places=2)
        self.assertIn('مُزاحة', actrapid['notes'])
