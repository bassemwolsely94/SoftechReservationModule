"""
apps/tests/test_purchase_expiry_audit.py

Tests for the Purchase-Expiry Physical Audit engine (apps/batches/expiry_audit.py).

The engine reads SOFTECH only inside run_backfill() and the default stock
resolver; audit_candidates() and the pure helpers are exercised here WITHOUT any
Sybase connection — DB tests populate the PurchaseExpiryEntry mirror directly and
inject a fake stock fetcher, so the core selection logic ("purchase-entry trigger
∩ currently-in-stock") is verified deterministically.
"""
import datetime as _dt
from decimal import Decimal

from django.test import SimpleTestCase, TestCase

from apps.batches.expiry_audit import (
    _month_chunks, _valid_expiry, _clean_docnumber,
    resolve_main_suppliers, audit_candidates,
)
from apps.batches.models import PurchaseExpiryEntry
from apps.procurement.models import SupplierSegmentation
from apps.catalog.models import Item


# ── Pure helpers (no DB) ──────────────────────────────────────────────────────

class PureHelperTests(SimpleTestCase):

    def test_month_chunks_span_and_bounds(self):
        chunks = list(_month_chunks(_dt.date(2024, 1, 15), _dt.date(2024, 3, 10)))
        # Jan (from the 15th), full Feb, Mar (to the 11th exclusive)
        self.assertEqual(chunks[0], ('2024-01-15', '2024-02-01'))
        self.assertEqual(chunks[1], ('2024-02-01', '2024-03-01'))
        self.assertEqual(chunks[2], ('2024-03-01', '2024-03-11'))

    def test_month_chunks_single_month(self):
        chunks = list(_month_chunks(_dt.date(2023, 6, 1), _dt.date(2023, 6, 30)))
        self.assertEqual(chunks, [('2023-06-01', '2023-07-01')])

    def test_month_chunks_year_boundary(self):
        chunks = list(_month_chunks(_dt.date(2023, 12, 1), _dt.date(2024, 1, 31)))
        self.assertEqual(chunks[0], ('2023-12-01', '2024-01-01'))
        self.assertEqual(chunks[1], ('2024-01-01', '2024-02-01'))

    def test_valid_expiry_guards_sentinels(self):
        self.assertTrue(_valid_expiry(_dt.date(2025, 6, 30)))
        self.assertFalse(_valid_expiry(_dt.date(1900, 1, 1)))   # SOFTECH sentinel
        self.assertFalse(_valid_expiry(None))

    def test_clean_docnumber_strips_float_suffix(self):
        self.assertEqual(_clean_docnumber('64550.0'), '64550')
        self.assertEqual(_clean_docnumber('64550'), '64550')
        self.assertEqual(_clean_docnumber(None), '')

    def test_fifo_oldest_date(self):
        from apps.batches.expiry_audit import _fifo_oldest_date
        # newest-first: small recent top-up on top of a big old batch
        arr = [(_dt.date(2026, 8, 1), Decimal('10')),
               (_dt.date(2025, 9, 1), Decimal('100'))]
        # 50 on hand → old batch still contributes → oldest unit = Sep-2025
        self.assertEqual(_fifo_oldest_date(arr, Decimal('50')), _dt.date(2025, 9, 1))
        # 8 on hand → covered by the recent top-up alone → fresh
        self.assertEqual(_fifo_oldest_date(arr, Decimal('8')), _dt.date(2026, 8, 1))
        # no arrivals → None; arrivals < qty → earliest (oldest)
        self.assertIsNone(_fifo_oldest_date([], Decimal('5')))
        self.assertEqual(_fifo_oldest_date(arr, Decimal('999')), _dt.date(2025, 9, 1))


# ── Supplier resolution (DB) ──────────────────────────────────────────────────

class ResolveMainSuppliersTests(TestCase):

    def setUp(self):
        SupplierSegmentation.objects.create(
            supplier_code='S1', supplier_name='Distributor One',
            supplier_category='OFFICIAL_DISTRIBUTOR')
        SupplierSegmentation.objects.create(
            supplier_code='S2', supplier_name='Pharma Maker',
            supplier_category='MANUFACTURER')
        SupplierSegmentation.objects.create(
            supplier_code='S3', supplier_name='Corner Warehouse',
            supplier_category='SMALL_WAREHOUSE')
        SupplierSegmentation.objects.create(
            supplier_code='S4', supplier_name='Mr Patient',
            supplier_category='PATIENT_REPURCHASE')

    def test_default_returns_only_main_categories(self):
        result = resolve_main_suppliers()
        self.assertEqual(set(result.keys()), {'S1', 'S2'})
        self.assertEqual(result['S1']['category'], 'OFFICIAL_DISTRIBUTOR')
        self.assertEqual(result['S2']['name'], 'Pharma Maker')

    def test_custom_categories(self):
        result = resolve_main_suppliers(categories=['SMALL_WAREHOUSE'])
        self.assertEqual(set(result.keys()), {'S3'})

    def test_empty_when_no_main_suppliers(self):
        SupplierSegmentation.objects.all().delete()
        self.assertEqual(resolve_main_suppliers(), {})


# ── audit_candidates (DB + injected stock fetcher) ────────────────────────────

class AuditCandidatesTests(TestCase):
    """
    The period is an ENTERED-EXPIRY window (batches a MAIN supplier logged as
    expiring in the window); the purchase itself may have happened at any time.
      A100 — main supplier, batch expiring in window, IN STOCK now  → candidate
      A200 — main supplier, expiring in window, NOT in stock          → excluded
      A300 — expiring in window + in stock, but NON-main supplier      → excluded
      A400 — main + in stock, but entered expiry OUTSIDE the window    → excluded
    """
    WINDOW_FROM = _dt.date(2026, 9, 1)     # ENTERED-EXPIRY window
    WINDOW_TO   = _dt.date(2026, 9, 30)

    def _entry(self, **kw):
        base = dict(
            branch_code='130', supplier_code='S1', supplier_name='Distributor One',
            supplier_category='OFFICIAL_DISTRIBUTOR', doc_number='1000',
            doc_date=_dt.date(2023, 6, 1),          # purchased long ago — must not matter
            item_code='A100', item_name='Item A100',
            dblitemflag=1, entered_expiry=_dt.date(2026, 9, 15), qty=Decimal('10'),
            store_code='100',
        )
        base.update(kw)
        return PurchaseExpiryEntry.objects.create(**base)

    def setUp(self):
        # A100 — candidate: TWO batches expiring in the window + one OUTSIDE it.
        self._entry(item_code='A100', dblitemflag=1, entered_expiry=_dt.date(2026, 9, 5))
        self._entry(item_code='A100', dblitemflag=2, doc_number='1001',
                    entered_expiry=_dt.date(2026, 9, 25))
        self._entry(item_code='A100', dblitemflag=3, doc_number='1010',
                    entered_expiry=_dt.date(2027, 3, 31))   # expiry OUTSIDE window
        # A200 — main + expiring in window but not in stock
        self._entry(item_code='A200', item_name='Item A200', doc_number='1002',
                    entered_expiry=_dt.date(2026, 9, 20))
        # A300 — expiring in window + in stock but NON-main supplier
        self._entry(item_code='A300', item_name='Item A300', doc_number='1003',
                    supplier_code='S9', supplier_name='Corner Warehouse',
                    supplier_category='SMALL_WAREHOUSE',
                    entered_expiry=_dt.date(2026, 9, 10))
        # A400 — main + in stock but entered expiry OUTSIDE the window
        self._entry(item_code='A400', item_name='Item A400', doc_number='1004',
                    doc_date=_dt.date(2022, 5, 1), entered_expiry=_dt.date(2025, 5, 31))

    def _stock(self, in_stock_codes):
        """Return a fake stock_fetcher that reports the given codes on-hand."""
        def fetcher(branch_codes, item_codes):
            out = {}
            for code in item_codes:
                if code in in_stock_codes:
                    out[('130', code)] = Decimal('7')
            return out
        return fetcher

    def test_only_in_stock_main_supplier_in_window(self):
        # Everything on-hand → discriminators left are "main supplier" +
        # "entered expiry inside the window".
        rows = audit_candidates(
            self.WINDOW_FROM, self.WINDOW_TO,
            stock_fetcher=self._stock({'A100', 'A200', 'A300', 'A400'}),
        )
        codes = {r['item_code'] for r in rows}
        self.assertIn('A100', codes)      # main + expiring in window + in stock
        self.assertIn('A200', codes)
        self.assertNotIn('A300', codes)   # non-main supplier
        self.assertNotIn('A400', codes)   # expiry outside window

    def test_out_of_stock_excluded(self):
        rows = audit_candidates(
            self.WINDOW_FROM, self.WINDOW_TO,
            stock_fetcher=self._stock({'A100'}),   # only A100 on-hand
        )
        codes = {r['item_code'] for r in rows}
        self.assertEqual(codes, {'A100'})
        self.assertNotIn('A200', codes)   # expiring in window but NOT in stock

    def test_candidate_aggregates_in_window_batches(self):
        rows = audit_candidates(
            self.WINDOW_FROM, self.WINDOW_TO,
            stock_fetcher=self._stock({'A100'}),
        )
        a100 = next(r for r in rows if r['item_code'] == 'A100')
        # Only the two IN-WINDOW batches count; the 2027 one is excluded.
        self.assertEqual(a100['entry_count'], 2)
        self.assertEqual(a100['earliest_entered_expiry'], '2026-09-05')
        self.assertEqual(a100['latest_entered_expiry'], '2026-09-25')
        self.assertEqual(a100['current_qty'], 7.0)
        self.assertEqual(a100['branches_in_stock'], ['130'])
        self.assertEqual(a100['suppliers'], ['Distributor One'])

    def test_non_main_supplier_excluded_even_if_in_stock(self):
        rows = audit_candidates(
            self.WINDOW_FROM, self.WINDOW_TO,
            stock_fetcher=self._stock({'A100', 'A300'}),
        )
        self.assertNotIn('A300', {r['item_code'] for r in rows})

    def test_window_excludes_out_of_period_expiry(self):
        rows = audit_candidates(
            self.WINDOW_FROM, self.WINDOW_TO,
            stock_fetcher=self._stock({'A100', 'A400'}),
        )
        self.assertNotIn('A400', {r['item_code'] for r in rows})

    def test_purchase_date_does_not_matter(self):
        # A very old purchase (2021) with an IN-WINDOW expiry still qualifies —
        # the report keys on entered expiry, not purchase date.
        self._entry(item_code='A400', doc_number='1099', doc_date=_dt.date(2021, 1, 1),
                    item_name='Item A400', entered_expiry=_dt.date(2026, 9, 12))
        rows = audit_candidates(
            self.WINDOW_FROM, self.WINDOW_TO,
            stock_fetcher=self._stock({'A400'}),
        )
        self.assertIn('A400', {r['item_code'] for r in rows})

    def test_only_in_stock_false_returns_all_triggers(self):
        rows = audit_candidates(
            self.WINDOW_FROM, self.WINDOW_TO, only_in_stock=False,
        )
        codes = {r['item_code'] for r in rows}
        # All MAIN-supplier items expiring in window regardless of stock: A100, A200.
        self.assertEqual(codes, {'A100', 'A200'})
        for r in rows:
            self.assertIsNone(r['current_qty'])

    def test_has_entered_expiry_passed_flag(self):
        # A batch whose expiry is well in the past → flag True (deterministic:
        # 2020 < any run date). Use a matching past expiry window.
        self._entry(item_code='A500', item_name='Item A500', doc_number='1005',
                    entered_expiry=_dt.date(2020, 6, 30))
        rows = audit_candidates(
            _dt.date(2020, 1, 1), _dt.date(2020, 12, 31),
            stock_fetcher=self._stock({'A500'}),
        )
        a500 = next(r for r in rows if r['item_code'] == 'A500')
        self.assertTrue(a500['has_entered_expiry_passed'])

    def test_enrichment_and_sort_and_filters(self):
        # Two items with different economics (expiry within the window).
        Item.objects.create(softech_id='E1', name='Cheap Local',
                            cost_price=10, pack_price=15, is_imported=False)
        Item.objects.create(softech_id='E2', name='Expensive Imported',
                            cost_price=200, pack_price=260, is_imported=True)
        for code in ('E1', 'E2'):
            self._entry(item_code=code, item_name='', doc_number=f'D{code}',
                        entered_expiry=_dt.date(2026, 9, 15))

        def stock(branch_codes, item_codes):
            qty = {'E1': Decimal('100'), 'E2': Decimal('10')}
            return {('130', c): qty[c] for c in item_codes if c in qty}

        rows = audit_candidates(self.WINDOW_FROM, self.WINDOW_TO,
                                stock_fetcher=stock, sort='value_at_risk')
        by = {r['item_code']: r for r in rows if r['item_code'] in ('E1', 'E2')}
        # Enrichment: value_at_risk = qty × unit_cost
        self.assertEqual(by['E1']['value_at_risk'], 1000.0)   # 100 × 10
        self.assertEqual(by['E2']['value_at_risk'], 2000.0)   # 10 × 200
        self.assertEqual(by['E2']['unit_cost'], 200.0)
        self.assertTrue(by['E2']['is_imported'])
        self.assertFalse(by['E1']['is_imported'])
        self.assertEqual(by['E2']['item_name'], 'Expensive Imported')  # name from catalog

        # Sort by value_at_risk → E2 (2000) before E1 (1000).
        order = [r['item_code'] for r in rows if r['item_code'] in ('E1', 'E2')]
        self.assertEqual(order, ['E2', 'E1'])

        # Sort by qty → E1 (100) before E2 (10).
        rows_q = audit_candidates(self.WINDOW_FROM, self.WINDOW_TO,
                                  stock_fetcher=stock, sort='qty')
        order_q = [r['item_code'] for r in rows_q if r['item_code'] in ('E1', 'E2')]
        self.assertEqual(order_q, ['E1', 'E2'])

        # imported_only keeps just E2.
        rows_imp = audit_candidates(self.WINDOW_FROM, self.WINDOW_TO,
                                    stock_fetcher=stock, imported_only=True)
        self.assertNotIn('E1', {r['item_code'] for r in rows_imp})
        self.assertIn('E2', {r['item_code'] for r in rows_imp})

        # min_value_at_risk drops E1 (1000 < 1500).
        rows_var = audit_candidates(self.WINDOW_FROM, self.WINDOW_TO,
                                    stock_fetcher=stock, min_value_at_risk=1500)
        codes_var = {r['item_code'] for r in rows_var}
        self.assertIn('E2', codes_var)
        self.assertNotIn('E1', codes_var)

    def test_stock_age_fifo_and_sort(self):
        # AGE1: 50 on hand = big old batch (Sep-2025) + small recent top-up
        #       (Aug-2026) → oldest on-hand unit is STILL from Sep-2025.
        # AGE2: 8 on hand, only a recent Aug-2026 arrival → fresh.
        for code in ('AGE1', 'AGE2'):
            self._entry(item_code=code, item_name=f'Item {code}', doc_number=f'AG{code}',
                        entered_expiry=_dt.date(2026, 9, 15))

        def stock(bcs, codes):
            q = {'AGE1': Decimal('50'), 'AGE2': Decimal('8')}
            return {('130', c): q[c] for c in codes if c in q}

        def arrivals(bcs, codes):
            data = {
                ('130', 'AGE1'): [(_dt.date(2026, 8, 1), Decimal('10')),
                                  (_dt.date(2025, 9, 1), Decimal('100'))],
                ('130', 'AGE2'): [(_dt.date(2026, 8, 1), Decimal('10'))],
            }
            return {k: v for k, v in data.items() if k[1] in codes}

        rows = audit_candidates(self.WINDOW_FROM, self.WINDOW_TO,
                                stock_fetcher=stock, arrivals_fetcher=arrivals,
                                sort='stock_age')
        by = {r['item_code']: r for r in rows if r['item_code'] in ('AGE1', 'AGE2')}
        self.assertEqual(by['AGE1']['oldest_arrival_date'], '2025-09-01')
        self.assertEqual(by['AGE2']['oldest_arrival_date'], '2026-08-01')
        self.assertEqual(by['AGE1']['stock_age_days'],
                         (_dt.date.today() - _dt.date(2025, 9, 1)).days)
        self.assertEqual(by['AGE1']['oldest_arrival_branch'], '130')
        # Longest-sitting first
        order = [r['item_code'] for r in rows if r['item_code'] in ('AGE1', 'AGE2')]
        self.assertEqual(order, ['AGE1', 'AGE2'])

    def test_stock_age_absent_when_not_in_stock(self):
        rows = audit_candidates(self.WINDOW_FROM, self.WINDOW_TO, only_in_stock=False)
        for r in rows:
            self.assertIsNone(r['stock_age_days'])

    def test_branch_scope_filter(self):
        # Same item, one batch expiring in-window at a different branch.
        self._entry(item_code='A100', branch_code='160', doc_number='2000',
                    dblitemflag=1, entered_expiry=_dt.date(2026, 9, 18))
        rows = audit_candidates(
            self.WINDOW_FROM, self.WINDOW_TO, branch_codes=['160'],
            stock_fetcher=self._stock({'A100'}),
        )
        a100 = [r for r in rows if r['item_code'] == 'A100']
        self.assertEqual(len(a100), 1)
        # Only the branch-160 entry counted (branch-130 rows filtered out).
        self.assertEqual(a100[0]['entry_count'], 1)
