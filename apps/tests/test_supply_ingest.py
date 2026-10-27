"""
Phase-0 tests for apps.supply — the shared ingest pipeline + read-only PositionService
extracted from apps.shortage (doc 24).

Goal: prove the extracted logic behaves identically to the shortage inline logic it
replaced (parse → dedup → resolve, explicit-pick vs fuzzy), and that PositionService
assembles the authoritative position read-only without recomputing anything.
"""
from datetime import date

from django.test import TestCase, SimpleTestCase

from apps.supply.ingest import (
    parse_entry, resolve_line, ParsedLine,
    AUTO_MATCH_IMPORT, AUTO_MATCH_SINGLE,
)


# ── parse_entry (pure — no DB) ────────────────────────────────────────────────

class ParseEntryTests(SimpleTestCase):
    def test_plain_string_splits_quantity(self):
        p = parse_entry('paracetamol 500mg 10')
        self.assertIsInstance(p, ParsedLine)
        self.assertEqual(p.raw_name, 'paracetamol 500mg')
        self.assertEqual(p.qty, 10.0)
        self.assertIsNone(p.override_id)
        self.assertEqual(p.override_sid, '')
        self.assertTrue(p.dedup_key)

    def test_no_trailing_number_defaults_qty_to_one(self):
        # A trailing token that isn't a bare number (has a unit) is NOT a quantity.
        p = parse_entry('Cellcept 500mg')
        self.assertEqual(p.qty, 1.0)
        self.assertEqual(p.raw_name, 'Cellcept 500mg')

    def test_bare_trailing_number_is_read_as_quantity_faithful_quirk(self):
        # KNOWN quirk of the extracted parser (parse_quantity_from_text): a bare
        # trailing number is taken as the quantity even when it is really a strength.
        # "Recormon 4000" → qty 4000, name "Recormon". Preserved verbatim in Phase 0;
        # strength-vs-qty disambiguation is a Phase-2 improvement (doc 24 §4/§7).
        p = parse_entry('Recormon 4000')
        self.assertEqual(p.qty, 4000.0)
        self.assertEqual(p.raw_name, 'Recormon')

    def test_dict_carries_explicit_pk_pick(self):
        p = parse_entry({'raw': 'أموكسيسيلين 5', 'item_id': 42})
        self.assertEqual(p.override_id, 42)
        self.assertEqual(p.override_sid, '')

    def test_dict_carries_explicit_softech_pick(self):
        p = parse_entry({'raw': 'كريون 25000', 'item_softech_id': ' 123456 '})
        self.assertEqual(p.override_sid, '123456')  # trimmed

    def test_blank_raw_is_skipped(self):
        self.assertIsNone(parse_entry('   '))
        self.assertIsNone(parse_entry({'raw': ''}))

    def test_thresholds_are_the_historical_shortage_values(self):
        # These must not drift silently — they defined shortage behaviour.
        self.assertEqual(AUTO_MATCH_IMPORT, 0.55)
        self.assertEqual(AUTO_MATCH_SINGLE, 0.70)


# ── resolve_line (DB — catalog resolution) ────────────────────────────────────

class ResolveLineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        cls.para = Item.objects.create(
            softech_id='100001', name='PARACETAMOL 500MG', is_active=True)
        cls.amox = Item.objects.create(
            softech_id='100002', name='AMOXICILLIN 500MG', is_active=True)

    def test_explicit_pk_pick_wins_and_is_confirmed(self):
        r = resolve_line('anything at all', override_id=self.para.id)
        self.assertEqual(r.item_id, self.para.id)
        self.assertEqual(r.score, 1.0)
        self.assertTrue(r.picked)

    def test_explicit_softech_pick_wins(self):
        r = resolve_line('anything', override_sid='100002')
        self.assertEqual(r.item_id, self.amox.id)
        self.assertTrue(r.picked)

    def test_bad_override_falls_through_to_fuzzy(self):
        # Non-existent pk → not an error; falls back to fuzzy on the raw name.
        r = resolve_line('PARACETAMOL 500MG', override_id=99999999)
        self.assertEqual(r.item_id, self.para.id)
        self.assertFalse(r.picked)          # fuzzy match is NOT a confirmed pick
        self.assertIsNotNone(r.score)

    def test_fuzzy_auto_match_returns_item_unconfirmed(self):
        r = resolve_line('paracetamol 500')
        self.assertEqual(r.item_id, self.para.id)
        self.assertFalse(r.picked)
        self.assertGreaterEqual(r.score, AUTO_MATCH_IMPORT)

    def test_unresolvable_line_returns_none(self):
        r = resolve_line('zzzzz nonexistent xyzzy qwerty')
        self.assertIsNone(r.item)
        self.assertIsNone(r.item_id)
        self.assertFalse(r.picked)

    def test_threshold_gates_weak_matches(self):
        # An impossibly high threshold rejects even a decent match.
        r = resolve_line('paracetamol 500', threshold=1.01)
        self.assertIsNone(r.item)


# ── PositionService (DB — read-only assembler) ────────────────────────────────

class PositionServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item, ItemStock
        from apps.branches.models import Branch

        cls.item = Item.objects.create(softech_id='200001', name='ITEM A', is_active=True)
        cls.b1 = Branch.objects.create(softech_branch_id='130', name='Br130', name_ar='فرع ١٣٠')
        cls.b2 = Branch.objects.create(softech_branch_id='140', name='Br140', name_ar='فرع ١٤٠')

        # Usable stock in two branches + quarantine stock that must be excluded.
        ItemStock.objects.create(item=cls.item, branch=cls.b1, softech_store_code='130',
                                 quantity_on_hand=3)
        ItemStock.objects.create(item=cls.item, branch=cls.b2, softech_store_code='140',
                                 quantity_on_hand=7)
        ItemStock.objects.create(item=cls.item, branch=cls.b1, softech_store_code='105',
                                 quantity_on_hand=99)   # quarantine → excluded

    def test_empty_input_returns_empty(self):
        from apps.supply.position import PositionService
        self.assertEqual(PositionService.for_items([]), {})

    def test_cross_branch_stock_excludes_quarantine_and_sorts_desc(self):
        from apps.supply.position import PositionService
        pos = PositionService.for_items([self.item.id])[self.item.id]
        self.assertEqual(pos['total_on_hand'], 10.0)          # 3 + 7, not the 99 in 105
        self.assertEqual([b['qty_on_hand'] for b in pos['branches']], [7.0, 3.0])
        self.assertFalse(pos['has_run'])                      # no demand run yet
        self.assertIsNone(pos['demand'])
        # network falls back to live stock sum when no aggregate exists
        self.assertEqual(pos['network']['total_stock'], 10.0)

    def test_open_reservations_counted_closed_ignored(self):
        from apps.reservations.models import Reservation
        from apps.supply.position import PositionService
        Reservation.objects.create(item=self.item, branch=self.b1, quantity_requested=2,
                                   status='pending', contact_phone='0100', contact_name='X')
        Reservation.objects.create(item=self.item, branch=self.b1, quantity_requested=5,
                                   status='fulfilled', contact_phone='0101', contact_name='Y')
        pos = PositionService.for_items([self.item.id])[self.item.id]
        self.assertEqual(pos['reservations']['count'], 1)     # only the open one
        self.assertEqual(pos['reservations']['qty'], 2.0)

    def test_demand_metrics_are_read_not_recomputed(self):
        from apps.purchasing.models import (
            DemandCalculationRun, ItemDemandMetrics, ItemDemandAggregated)
        from apps.supply.position import PositionService

        run = DemandCalculationRun.objects.create(status='success', calc_date=date.today())
        ItemDemandMetrics.objects.create(
            run=run, item=self.item, branch=self.b1, calc_date=date.today(),
            current_stock=3, in_transit_qty=1, monthly_avg=12, safety_stock=2,
            gap=8, priority=5.5, coverage_months='0.25', abc_class='A')
        ItemDemandAggregated.objects.create(
            run=run, item=self.item, calc_date=date.today(),
            total_current_stock=10, total_in_transit=1, total_monthly_avg=12,
            total_gap=8, abc_class='A')

        pos = PositionService.for_items([self.item.id], branch=self.b1)[self.item.id]
        self.assertTrue(pos['has_run'])
        self.assertEqual(pos['demand']['gap'], 8.0)           # authoritative, verbatim
        self.assertEqual(pos['demand']['priority'], 5.5)
        self.assertEqual(pos['demand']['abc_class'], 'A')
        self.assertEqual(pos['network']['total_gap'], 8.0)
