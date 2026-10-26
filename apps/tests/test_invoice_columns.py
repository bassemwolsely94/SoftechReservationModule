"""
Tests for the SOFTECH purchase-line column engine (apps/invoices/softech_columns.py).

Golden values are REAL stktrans doccode-10 lines read from prod (2026-10-14):
the engine must reproduce SofTech's cell arithmetic exactly, including the
pre-tax discount base that the legacy pricing.compute_line gets wrong.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.invoices import softech_columns as sc
from apps.invoices import grid


class ColumnEngineTests(SimpleTestCase):

    def test_exempt_item_two_discounts_compound(self):
        # real line: P=144 Pb=144 (rate 0) D1=18.667 D2=4.940 -> C=111.334
        r = sc.recompute({'public_price': 144, 'tax_rate': 0,
                          'disc_pct': 18.667, 'extra_disc_pct': 4.940, 'quantity': 1})
        self.assertAlmostEqual(r['base_price'], 144.0, places=2)
        self.assertAlmostEqual(r['unit_cost'], 111.334, places=2)
        self.assertAlmostEqual(r['vat_amount'], 0.0, places=2)

    def test_taxed_item_discounts_on_pretax_base(self):
        # real line: P=85 rate 14 -> Pb=74.561; D1=20 D2=1.65 -> C=58.665
        r = sc.recompute({'public_price': 85, 'tax_rate': 14,
                          'disc_pct': 20, 'extra_disc_pct': 1.65, 'quantity': 1})
        self.assertAlmostEqual(r['base_price'], 74.561, places=2)
        self.assertAlmostEqual(r['unit_cost'], 58.665, places=2)
        # VAT amount on the pre-tax cost = C * 14%
        self.assertAlmostEqual(r['vat_amount'], 58.665 * 0.14, places=2)

    def test_vat_amount_is_cost_times_rate(self):
        # real line: taxed, cost 419.737, rate 14 -> Tx 58.763
        r = sc.recompute({'base_price': 482.456, 'tax_rate': 14,
                          'unit_cost': 419.737, 'quantity': 1}, changed='unit_cost')
        self.assertAlmostEqual(r['vat_amount'], 58.763, places=2)

    def test_edit_cost_backsolves_main_discount(self):
        # type a net cost directly -> D1 recomputed, D2 kept; round-trips to same cost
        cells = {'public_price': 85, 'tax_rate': 14, 'extra_disc_pct': 1.65,
                 'unit_cost': 58.665, 'quantity': 1}
        r = sc.recompute(cells, changed='unit_cost')
        self.assertAlmostEqual(r['disc_pct'], 20.0, places=1)
        # feeding the back-solved discounts forward reproduces the same cost
        r2 = sc.recompute({'public_price': 85, 'tax_rate': 14,
                           'disc_pct': r['disc_pct'], 'extra_disc_pct': 1.65, 'quantity': 1})
        self.assertAlmostEqual(r2['unit_cost'], 58.665, places=2)

    def test_edit_base_price_updates_public(self):
        r = sc.recompute({'base_price': 100, 'tax_rate': 14, 'quantity': 1},
                         changed='base_price')
        self.assertAlmostEqual(r['public_price'], 114.0, places=2)

    def test_cost_total_tracks_qty(self):
        r = sc.recompute({'public_price': 100, 'tax_rate': 0, 'disc_pct': 20, 'quantity': 10})
        self.assertAlmostEqual(r['unit_cost'], 80.0, places=2)
        self.assertAlmostEqual(r['cost_total'], 800.0, places=2)

    def test_foc_expands_to_two_lines(self):
        lines = sc.expand_foc({'public_price': 100, 'tax_rate': 0, 'disc_pct': 20,
                               'quantity': 10, 'bonus_qty': 1})
        self.assertEqual(len(lines), 2)
        paid, free = lines
        self.assertEqual(paid['role'], 'paid')
        self.assertAlmostEqual(paid['quantity'], 10.0, places=2)
        self.assertAlmostEqual(paid['unit_cost'], 80.0, places=2)
        self.assertEqual(free['role'], 'free')
        self.assertAlmostEqual(free['quantity'], 1.0, places=2)
        self.assertAlmostEqual(free['unit_cost'], 0.0, places=2)   # FOC pack = zero cost

    def test_no_bonus_is_single_line(self):
        self.assertEqual(len(sc.expand_foc({'public_price': 50, 'quantity': 5})), 1)

    def test_price_comparison_detects_change(self):
        c = sc.price_comparison(85.0, 80.0)
        self.assertTrue(c['changed'])
        self.assertEqual(c['direction'], 'up')
        self.assertAlmostEqual(c['delta'], 5.0, places=2)
        same = sc.price_comparison(80.0, 80.0)
        self.assertFalse(same['changed'])

    def test_to_write_fields_maps_softech_columns(self):
        w = sc.to_write_fields({'public_price': 85, 'tax_rate': 14,
                                'disc_pct': 20, 'extra_disc_pct': 1.65, 'quantity': 3})
        self.assertAlmostEqual(w['itemsaleprice'], 85.0, places=2)
        self.assertAlmostEqual(w['itemsaleprice_tax'], 74.561, places=2)
        self.assertAlmostEqual(w['transprice'], 58.665, places=2)
        self.assertAlmostEqual(w['transprice_total'], 58.665 * 3, places=2)


class SoftechMatchTests(SimpleTestCase):
    """The grid must match the real «مشتريات من الموردين» screen: 3 discounts,
    the tax model, cost-incl-tax, and the bidirectional field logic."""

    def test_screenshot_case(self):
        # real screen: base 268.5, خصم أساسى 25%, qty 2, VAT-exempt → 201.375 / 402.75
        r = sc.recompute({'public_price': 268.5, 'base_price': 268.5, 'vat_pct': 0,
                          'disc_pct': 25, 'quantity': 2})
        self.assertAlmostEqual(r['unit_cost'], 201.375, places=3)
        self.assertAlmostEqual(r['cost_total'], 402.75, places=2)
        self.assertAlmostEqual(r['cost_total_incl_tax'], 402.75, places=2)

    def test_three_discounts_compound(self):
        r = sc.recompute({'base_price': 100, 'vat_pct': 0,
                          'disc_pct': 10, 'extra_disc_pct': 5, 'special_disc_pct': 2})
        self.assertAlmostEqual(r['unit_cost'], 100 * 0.9 * 0.95 * 0.98, places=4)

    def test_special_discount_applied_after_the_other_two(self):
        r = sc.recompute({'base_price': 200, 'vat_pct': 0, 'disc_pct': 20,
                          'extra_disc_pct': 10, 'special_disc_pct': 5})
        self.assertAlmostEqual(r['unit_cost'], 200 * 0.8 * 0.9 * 0.95, places=4)

    def test_tax_from_cost_vs_base(self):
        # tax on cost (default) vs on the base price
        on_cost = sc.recompute({'base_price': 100, 'vat_pct': 14, 'disc_pct': 20, 'tax_from_cost': True})
        self.assertAlmostEqual(on_cost['vat_amount'], 80 * 0.14, places=3)   # 80 = cost
        on_base = sc.recompute({'base_price': 100, 'vat_pct': 14, 'disc_pct': 20, 'tax_from_cost': False})
        self.assertAlmostEqual(on_base['vat_amount'], 100 * 0.14, places=3)  # 100 = base

    def test_vat_amount_and_pct_bidirectional(self):
        # edit the tax VALUE → the % is derived
        r = sc.recompute({'base_price': 100, 'disc_pct': 0, 'unit_cost': 100,
                          'vat_amount': 14, 'tax_from_cost': True}, changed='vat_amount')
        self.assertAlmostEqual(r['vat_pct'], 14.0, places=2)
        self.assertEqual(r['tax_type'], 'value')

    def test_edit_incl_tax_backsolves_cost_and_discount(self):
        r = sc.recompute({'base_price': 100, 'vat_pct': 14, 'unit_cost_incl_tax': 114,
                          'tax_from_cost': True}, changed='unit_cost_incl_tax')
        self.assertAlmostEqual(r['unit_cost'], 100.0, places=2)
        self.assertAlmostEqual(r['disc_pct'], 0.0, places=1)

    def test_cost_incl_tax_equals_cost_plus_tax(self):
        r = sc.recompute({'base_price': 100, 'vat_pct': 14, 'disc_pct': 20, 'tax_from_cost': True})
        self.assertAlmostEqual(r['unit_cost_incl_tax'], r['unit_cost'] + r['vat_amount'], places=4)

    def test_special_discount_writes_to_specialdiscp(self):
        # VERIFIED 2026-10-17 on real stktrans: d3 → specialdiscp, and
        # transprice = base·(1−d1)(1−d2)(1−d3)
        w = sc.to_write_fields({'base_price': 100, 'vat_pct': 0, 'disc_pct': 20,
                                'extra_disc_pct': 7, 'special_disc_pct': 2, 'quantity': 1})
        self.assertAlmostEqual(w['specialdiscp'], 2.0, places=3)
        self.assertAlmostEqual(w['pharmacydiscp'], 20.0, places=3)
        self.assertAlmostEqual(w['additionaldiscp'], 7.0, places=3)
        self.assertAlmostEqual(w['transprice'], 100 * 0.8 * 0.93 * 0.98, places=4)


class GridBridgeTests(SimpleTestCase):
    """The model↔engine bridge (grid.py) — DB-free, duck-typed stand-ins."""

    def _item(self, pack_price, pack_price_tax, sale_tax_pct=0, sid='999', name='X'):
        return SimpleNamespace(pack_price=pack_price, pack_price_tax=pack_price_tax,
                               sale_tax_pct=sale_tax_pct, softech_id=sid, name=name)

    def _line(self, item, **kw):
        base = dict(id=1, item_id=1, item=item, manual_name='raw', raw_text='raw',
                    vendor_item_code='', batch_number='', expiry_date='',
                    public_price=0, quantity=1, discount_pct=0, extra_discount_pct=0,
                    unit_price=0, bonus_qty=0, vat_pct=0, match_score=0.9,
                    match_review=False, needs_pick=False, is_confirmed=False,
                    price_action='keep_old')
        base.update(kw)
        return SimpleNamespace(**base)

    def test_item_rate_derived_from_price_ratio(self):
        # 14%-VAT item whose sale_tax_pct flag is 0 → rate still derived from P/Pb
        P, Pb, rate = grid.item_price_base(self._item(85, 74.561, sale_tax_pct=0))
        self.assertAlmostEqual(rate, 14.0, places=1)

    def test_grid_row_honours_ocr_net_cost(self):
        # OCR supplied net=58.665 on a taxed item → shown as-is; with the 1.65% extra
        # discount present the back-solved main discount is 20% (the real line).
        line = self._line(self._item(85, 74.561), public_price=85, unit_price=58.665,
                          extra_discount_pct=1.65, quantity=3)
        row = grid.grid_row(line)
        self.assertAlmostEqual(row['cells']['unit_cost'], 58.665, places=2)
        self.assertAlmostEqual(row['cells']['disc_pct'], 20.0, places=0)
        self.assertAlmostEqual(row['cells']['cost_total'], 58.665 * 3, places=1)

    def test_grid_row_price_change_flagged(self):
        line = self._line(self._item(90, 90), public_price=85)   # invoice 85 vs catalog 90
        row = grid.grid_row(line)
        self.assertTrue(row['price']['changed'])
        self.assertEqual(row['price']['direction'], 'down')

    def test_grid_row_foc_two_lines(self):
        line = self._line(self._item(100, 100), public_price=100, discount_pct=20,
                          quantity=10, bonus_qty=1)
        row = grid.grid_row(line)
        self.assertEqual(len(row['foc']), 2)
        self.assertAlmostEqual(row['foc'][1]['unit_cost'], 0.0, places=2)

    def test_recompute_cells_endpoint_shape(self):
        out = grid.recompute_cells({'cells': {'public_price': 100, 'tax_rate': 14,
                                              'disc_pct': 20, 'quantity': 5}, 'changed': 'disc_pct'})
        self.assertIn('cells', out)
        self.assertIn('softech', out)
        self.assertAlmostEqual(out['cells']['base_price'], 100 / 1.14, places=2)
        self.assertAlmostEqual(out['softech']['transprice'], (100 / 1.14) * 0.8, places=2)

    def test_computed_entries_foc_two_entries(self):
        # bonus line → paid (qty 10, cost 80) + free (qty 1, cost 0) for the writer
        line = self._line(self._item(100, 100), public_price=100, discount_pct=20,
                          quantity=10, bonus_qty=1, unit_price=0)
        es = grid.computed_entries(line)
        self.assertEqual(len(es), 2)
        self.assertAlmostEqual(es[0]['qty'], 10, places=2)
        self.assertAlmostEqual(es[0]['transprice'], 80.0, places=2)
        self.assertAlmostEqual(es[1]['qty'], 1, places=2)
        self.assertAlmostEqual(es[1]['transprice'], 0.0, places=2)
        self.assertTrue(es[1].get('is_bonus'))

    def test_computed_entries_taxed_uses_pretax_base(self):
        # the corrected write path: cost on the pre-tax base, not the public price
        line = self._line(self._item(85, 74.561), public_price=85, discount_pct=20,
                          extra_discount_pct=1.65, quantity=1, unit_price=0)
        es = grid.computed_entries(line)
        self.assertAlmostEqual(es[0]['transprice'], 58.665, places=2)
        self.assertAlmostEqual(es[0]['itemsaleprice_tax'], 74.561, places=2)

    def test_grid_row_exposes_margins_without_touching_cost(self):
        # margins are display-only: present in the row, but cost/line-total stay net
        line = self._line(self._item(100, 100), public_price=100, discount_pct=20,
                          quantity=5, unit_price=0,
                          distributor_margin_amt=2.5, pharmacist_margin_amt=2.5)
        row = grid.grid_row(line)
        self.assertEqual(row['distributor_margin_amt'], 2.5)
        self.assertEqual(row['pharmacist_margin_amt'], 2.5)
        # cost is still the net discounted base (margin NOT folded in)
        self.assertAlmostEqual(row['cells']['unit_cost'], 80.0, places=2)
        self.assertAlmostEqual(row['cells']['cost_total'], 400.0, places=2)

    def test_margin_summary_rolls_up_to_invoice_total(self):
        it = self._item(100, 100)
        lines = [
            self._line(it, public_price=100, discount_pct=20, quantity=5, unit_price=0,
                       distributor_margin_amt=2.0, pharmacist_margin_amt=2.0),
            self._line(it, public_price=100, discount_pct=20, quantity=3, unit_price=0,
                       distributor_margin_amt=1.0, pharmacist_margin_amt=1.0),
        ]
        s = grid.margin_summary(lines)
        # net line totals: 80×5 + 80×3 = 640 ; distributor margin: 2×5 + 1×3 = 13
        self.assertAlmostEqual(s['lines_net_total'], 640.0, places=1)
        self.assertAlmostEqual(s['distributor_margin_total'], 13.0, places=2)
        self.assertAlmostEqual(s['invoice_total_with_margin'], 653.0, places=1)


class VendorOcrProfileTests(SimpleTestCase):
    def test_hints_alphanumeric_foc_and_tax(self):
        from apps.invoices.ocr import vendor_prompt_hints
        h = vendor_prompt_hints({'code_format': 'alphanumeric', 'foc_style': 'same_line',
                                 'tax_note': 'prices include 14% VAT'})
        self.assertIn('ALPHANUMERIC', h)
        self.assertIn('10+1', h)
        self.assertIn('14% VAT', h)

    def test_empty_profile_gives_no_hints(self):
        from apps.invoices.ocr import vendor_prompt_hints
        self.assertEqual(vendor_prompt_hints({}), '')
        self.assertEqual(vendor_prompt_hints(None), '')

    def test_parse_structured_reads_bonus(self):
        from apps.invoices.ocr import parse_structured
        _, lines = parse_structured({'supplier_name': 'X', 'lines': [
            {'item_name': 'PANADOL', 'quantity': 10, 'bonus_qty': 1, 'public_price': 50}]})
        self.assertEqual(lines[0]['bonus_qty'], 1.0)
