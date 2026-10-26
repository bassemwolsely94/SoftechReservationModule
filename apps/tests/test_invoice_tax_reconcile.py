"""
Tests for SofTech tax reconciliation (apps/invoices/grid.py).

Golden values are REAL HQ purchase lines (br100, 2026-10): doc 65966 (native
«مشتريات من الموردين», Method 1 — VAT outside cost) and the CENTRAVITA case from
our doc 65912 that exposed the dirty-catalog bug. The engine must:
  • take the invoice's OCR'd VAT rate over a dirty catalog-derived rate, and flag it;
  • reproduce SofTech's per-line cost/VAT and the three bottom totals exactly.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.invoices import grid


def _item(pack_price, pack_price_tax, sale_tax_pct=0.0, softech_id='X', name='ITEM'):
    return SimpleNamespace(pack_price=pack_price, pack_price_tax=pack_price_tax,
                           sale_tax_pct=sale_tax_pct, softech_id=softech_id, name=name,
                           barcode='', nowqty=0)


def _line(item, *, public_price=0, unit_price=0, vat_pct=0, qty=1,
          d1=0, d2=0, d3=0, bonus=0):
    return SimpleNamespace(
        id=1, item_id=(1 if item else None), item=item,
        public_price=public_price, unit_price=unit_price, vat_pct=vat_pct,
        quantity=qty, discount_pct=d1, extra_discount_pct=d2, special_discount_pct=d3,
        tax_from_cost=True, bonus_qty=bonus, manual_name=name_of(item), raw_text='',
        match_score=1.0, match_review=False, needs_pick=False, is_confirmed=False,
        price_action='keep_old', order=0, notes='', ocr_confidence=1.0,
        batch_number='', expiry_date='', vendor_item_code='',
        pharmacist_margin_amt=0, distributor_margin_amt=0,
    )


def name_of(item):
    return getattr(item, 'name', '') if item else ''


class EffectiveTaxTests(SimpleTestCase):
    def test_ocr_rate_overrides_dirty_catalog(self):
        # CENTRAVITA: item IS taxed on the invoice (vat 14) but the master is dirty
        # (pack_price_tax == pack_price → derived 0%). The invoice rate must win.
        it = _item(160.0, 160.0)                      # dirty: both equal → catalog rate 0
        ln = _line(it, public_price=0, unit_price=112.281, vat_pct=14, qty=2)
        public, base, rate, conflict = grid.effective_tax(ln)
        self.assertEqual(rate, 14)
        self.assertTrue(conflict)
        self.assertAlmostEqual(base, 160.0 / 1.14, places=2)     # Pb recomputed from rate

    def test_agreement_uses_catalog_no_conflict(self):
        # COPAD: catalog already taxed (155 / 135.965 = 14%), invoice agrees → no flag.
        it = _item(155.0, 135.965)
        ln = _line(it, public_price=155, unit_price=108.772, vat_pct=14, qty=2)
        _, base, rate, conflict = grid.effective_tax(ln)
        self.assertAlmostEqual(rate, 14.0, places=1)
        self.assertFalse(conflict)
        self.assertAlmostEqual(base, 135.965, places=2)

    def test_exempt_stays_exempt_when_no_ocr_rate(self):
        it = _item(237.0, 237.0)                      # exempt
        ln = _line(it, public_price=237, unit_price=176.25, vat_pct=0, qty=1)
        _, base, rate, conflict = grid.effective_tax(ln)
        self.assertEqual(rate, 0)
        self.assertFalse(conflict)
        self.assertEqual(base, 237.0)


class LineCostTests(SimpleTestCase):
    def test_natry_taxed_line_matches_softech(self):
        # doc 65966 NATRY: P=70 Pb=61.404 d1=20 → cost 49.123, tax 6.877 (Method 1)
        it = _item(70.0, 61.404)
        ln = _line(it, public_price=70, unit_price=49.123, vat_pct=14, qty=2)
        e = grid.computed_entries(ln)[0]
        self.assertAlmostEqual(e['transprice'], 49.123, places=2)      # cost excl VAT
        self.assertAlmostEqual(e['itemsalestax'], 6.877, places=2)     # VAT = net×14%
        self.assertAlmostEqual(e['transprice_total'], 98.25, places=1)


class TaxSummaryTests(SimpleTestCase):
    def test_reproduces_65966_subset_totals(self):
        # NATRY (taxed) + NESTOGEN (exempt) from doc 65966.
        natry = _line(_item(70.0, 61.404), public_price=70, unit_price=49.123, vat_pct=14, qty=2)
        nesto = _line(_item(280.0, 280.0), public_price=280, unit_price=254.58, vat_pct=0, qty=3)
        ts = grid.tax_summary([natry, nesto])
        self.assertAlmostEqual(ts['total_net'], 98.25 + 763.74, places=1)      # 861.99
        self.assertAlmostEqual(ts['tax_outside_cost'], 6.877 * 2, places=1)    # 13.75
        self.assertAlmostEqual(ts['total_final'], ts['total_net'] + ts['tax_outside_cost'], places=2)

    def test_centravita_tax_included_in_final(self):
        # The CENTRAVITA fix: a dirty-catalog taxed item contributes its VAT to the final.
        it = _item(160.0, 160.0)
        ln = _line(it, public_price=0, unit_price=112.281, vat_pct=14, qty=2)
        ts = grid.tax_summary([ln])
        self.assertAlmostEqual(ts['tax_outside_cost'], 112.281 * 0.14 * 2, places=1)  # 31.44
        self.assertGreater(ts['total_final'], ts['total_net'])


class MarginFoldTests(SimpleTestCase):
    """PharmaOverseas-style: the distributor margin folds into the posted cost; the
    grand total = Σnet + Σmargin + Σtax. Verified against human doc 65688 (inv164)."""

    def _mucophylline(self):   # net 35.25 + margin 1.5 → cost 36.75, qty 50, exempt
        # exempt item: catalog base == public (no VAT); invoice سعر الجمهور = 50.
        return _line(_item(50.0, 50.0), public_price=50, unit_price=35.25, vat_pct=0, qty=50)

    def test_fold_adds_margin_to_posted_cost(self):
        ln = self._mucophylline()
        ln.distributor_margin_amt = 1.5
        r = grid.grid_row(ln, fold_margin=True)
        self.assertAlmostEqual(r['net_cost'], 35.25, places=2)
        self.assertAlmostEqual(r['cost_to_post'], 36.75, places=2)   # net + margin → SofTech
        e = grid.computed_entries(ln, fold_margin=True)[0]
        self.assertAlmostEqual(e['transprice'], 36.75, places=2)
        self.assertAlmostEqual(e['transprice_total'], 36.75 * 50, places=1)   # 1837.50

    def test_no_fold_keeps_net(self):
        ln = self._mucophylline()
        ln.distributor_margin_amt = 1.5
        r = grid.grid_row(ln, fold_margin=False)
        self.assertAlmostEqual(r['cost_to_post'], 35.25, places=2)   # RAMCO-style: net only

    def test_tax_summary_folds_margin_into_final(self):
        a = self._mucophylline(); a.distributor_margin_amt = 1.5           # 35.25/1.5/q50
        b = _line(_item(157.0, 157.0), public_price=157, unit_price=126.28, vat_pct=0, qty=12)
        b.distributor_margin_amt = 1.5
        c = _line(_item(122.0, 122.0), public_price=122, unit_price=94.40, vat_pct=0, qty=4)
        c.distributor_margin_amt = 2.0
        ts = grid.tax_summary([a, b, c], fold_margin=True)
        self.assertAlmostEqual(ts['total_net'], 3655.46, places=1)
        self.assertAlmostEqual(ts['margin_total'], 101.0, places=1)       # 1.5*50+1.5*12+2*4
        self.assertAlmostEqual(ts['total_final'], 3756.46, places=1)      # = paper total
