"""Owner rule 2026-10-31 (Option B): خصم أساسي (d1) and the net unit cost are always
linked; editing خصم إضافي/خاص keeps the net and d1 absorbs the change; d2/d3 are
never changed automatically. Example from invoice 224 (SWEETAL)."""
from django.test import SimpleTestCase

from apps.invoices import softech_columns as sc

SWEETAL = {'public_price': 130, 'base_price': 114.035, 'vat_pct': 14, 'quantity': 2,
           'disc_pct': 20, 'extra_disc_pct': 0, 'special_disc_pct': 0, 'unit_cost': 91.228}


class DiscountRuleTests(SimpleTestCase):
    def test_extra_discount_keeps_net_and_d1_absorbs(self):
        r = sc.recompute({**SWEETAL, 'extra_disc_pct': 5}, changed='extra_disc_pct')
        self.assertAlmostEqual(r['unit_cost'], 91.228, places=3)
        self.assertAlmostEqual(r['extra_disc_pct'], 5)
        self.assertAlmostEqual(r['disc_pct'], 15.789, places=2)

    def test_special_discount_same_rule(self):
        r = sc.recompute({**SWEETAL, 'special_disc_pct': 5}, changed='special_disc_pct')
        self.assertAlmostEqual(r['unit_cost'], 91.228, places=3)
        self.assertAlmostEqual(r['disc_pct'], 15.789, places=2)

    def test_basic_discount_moves_net(self):
        r = sc.recompute({**SWEETAL, 'disc_pct': 25}, changed='disc_pct')
        self.assertAlmostEqual(r['unit_cost'], 85.526, places=2)
        self.assertAlmostEqual(r['net_cost'], 85.526, places=2)

    def test_net_edit_back_solves_d1_keeps_d2(self):
        r = sc.recompute({**SWEETAL, 'extra_disc_pct': 5, 'net_cost': 86.667}, changed='net_cost')
        self.assertAlmostEqual(r['extra_disc_pct'], 5)
        self.assertAlmostEqual(r['disc_pct'], 20.0, places=2)

    def test_d1_never_negative_on_extra_edit(self):
        # no discount in the cost yet → d1 stays 0 and the cost follows d2
        r = sc.recompute({**SWEETAL, 'disc_pct': 0, 'unit_cost': 114.035, 'extra_disc_pct': 10},
                         changed='extra_disc_pct')
        self.assertEqual(r['disc_pct'], 0)
        self.assertAlmostEqual(r['unit_cost'], 102.632, places=2)

    def test_net_cost_excludes_folded_margin(self):
        # Actrapid (PharmaOverseas): net 268.96 + distributor margin 5 posted
        cells = {'public_price': 338, 'base_price': 338, 'vat_pct': 0, 'quantity': 2,
                 'disc_pct': 0, 'margin_in_cost': 5}
        r = sc.recompute({**cells, 'net_cost': 268.96}, changed='net_cost')
        self.assertAlmostEqual(r['unit_cost'], 273.96, places=3)
        self.assertAlmostEqual(r['net_cost'], 268.96, places=3)
        self.assertAlmostEqual(r['disc_pct'], 18.9467, places=3)
