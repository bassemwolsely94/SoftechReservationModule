"""
Phase-6 backend tests for the /supply workspace: company-level internal cover (the network
scope correction), the availability review-grid analysis, bulk match confirmation, and the
live transfer-draft status on a case.
"""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from apps.supply import cases as case_svc
from apps.supply import execution as exe
from apps.supply.availability import analyze_batch, confirm_matches
from apps.supply.engine import recommend
from apps.supply.models import AvailabilityBatch, AvailabilityLine
from .factories import make_user


def _run():
    from apps.purchasing.models import DemandCalculationRun
    return DemandCalculationRun.objects.create(status='success', calc_date=date.today())


def _metric(run, item, branch, *, stock=0, safety=0, gap=0):
    from apps.purchasing.models import ItemDemandMetrics
    return ItemDemandMetrics.objects.create(run=run, item=item, branch=branch,
                                            calc_date=date.today(), current_stock=stock,
                                            safety_stock=safety, gap=gap)


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        cls.item = Item.objects.create(softech_id='800001', name='CELLCEPT 500MG', is_active=True)
        cls.a = Branch.objects.create(softech_branch_id='130', name='A')
        cls.hq = Branch.objects.create(softech_branch_id='100', name='HQ')
        cls.user, cls.staff, _ = make_user('ws_buyer', role='purchasing')


class NetworkCoverTests(_Base):
    def _network(self, gap_a, gap_hq):
        from apps.purchasing.models import ItemDemandAggregated
        run = _run()
        _metric(run, self.item, self.a, stock=0, gap=gap_a)
        _metric(run, self.item, self.hq, stock=20, safety=2, gap=gap_hq)
        ItemDemandAggregated.objects.create(run=run, item=self.item, calc_date=date.today(),
                                            total_current_stock=20,
                                            total_gap=max(gap_a, 0) + max(gap_hq, 0))
        return recommend(self.item.id)['quantity_ledger']

    def test_overstock_at_hq_covers_the_branch_before_buying(self):
        # Branch short 5; HQ holds 3 above its own target → buy only 2 (§9 / §14).
        L = self._network(gap_a=5, gap_hq=-3)
        self.assertEqual(L['required'], 5.0)
        self.assertEqual(L['internally_allocated'], 3.0)
        self.assertEqual(L['residual_gap'], 2.0)

    def test_overstock_fully_covers_so_nothing_to_buy(self):
        L = self._network(gap_a=5, gap_hq=-8)
        self.assertEqual(L['internally_allocated'], 5.0)
        self.assertEqual(L['residual_gap'], 0.0)

    def test_branch_that_is_itself_short_is_not_a_donor(self):
        # HQ also short (gap +2) → no internal cover; the whole deficit must be bought.
        L = self._network(gap_a=5, gap_hq=2)
        self.assertEqual(L['internally_allocated'], 0.0)
        self.assertEqual(L['residual_gap'], 7.0)


class AnalysisTests(_Base):
    def _batch(self):
        b = AvailabilityBatch.objects.create(source='whatsapp', supplier_name='Ibn Sina')
        good = AvailabilityLine.objects.create(batch=b, raw_text='cellcept 500 10 @ 100',
                                               item=self.item, match_score=0.95,
                                               supplier_qty=10, price=100)
        weak = AvailabilityLine.objects.create(batch=b, raw_text='cellc?', item=self.item,
                                               match_score=0.4, supplier_qty=3)
        none = AvailabilityLine.objects.create(batch=b, raw_text='zzz unknown', is_unmatched=True)
        return b, good, weak, none

    def test_grid_suggests_need_not_the_whole_offer(self):
        from apps.purchasing.models import ItemDemandAggregated
        run = _run()
        _metric(run, self.item, self.a, stock=0, gap=4)
        ItemDemandAggregated.objects.create(run=run, item=self.item, calc_date=date.today(),
                                            total_gap=4)
        b, good, weak, none = self._batch()
        res = analyze_batch(b)
        rows = {r['line_id']: r for r in res['lines']}
        self.assertEqual(rows[good.id]['state'], 'buy')
        self.assertEqual(rows[good.id]['suggested_buy'], 4.0)       # need 4, not the 10 offered
        self.assertEqual(rows[good.id]['offer_effective_cost'], 100.0)
        self.assertEqual(rows[weak.id]['state'], 'needs_match')     # low confidence
        self.assertEqual(rows[none.id]['state'], 'needs_match')
        self.assertIn('unmatched', rows[none.id]['flags'])
        self.assertEqual(res['summary']['total'], 3)

    def test_not_needed_when_no_residual(self):
        _metric(_run(), self.item, self.a, stock=30, gap=0)
        b, good, _, _ = self._batch()
        row = next(r for r in analyze_batch(b)['lines'] if r['line_id'] == good.id)
        self.assertEqual(row['state'], 'not_needed')
        self.assertEqual(row['suggested_buy'], 0.0)

    def test_bulk_confirm_only_high_confidence(self):
        b, good, weak, _ = self._batch()
        done = confirm_matches(b, staff=self.staff)
        self.assertEqual([l.id for l in done], [good.id])
        weak.refresh_from_db()
        self.assertFalse(weak.is_confirmed)


class CaseTransferStatusTests(_Base):
    def test_case_shows_live_status_of_its_transfer_drafts(self):
        from apps.catalog.models import ItemStock
        from apps.transfers.models import TransferRequest
        run = _run()
        _metric(run, self.item, self.a, stock=0, gap=4)
        _metric(run, self.item, self.hq, stock=20, safety=2)
        ItemStock.objects.create(item=self.item, branch=self.hq, softech_store_code='100',
                                 quantity_on_hand=20)
        case = case_svc.evaluate_case(self.item.id, self.a.id)['case']
        exe.approve_internal_transfer(case, idempotency_key='ws-1', staff=self.staff)
        TransferRequest.objects.update(status='rejected')          # transfers team said no
        c = APIClient()
        c.force_authenticate(self.user)
        data = c.get(f'/api/supply/cases/{case.id}/').json()
        self.assertEqual(data['transfer_requests'][0]['status'], 'rejected')

    def test_analysis_and_bulk_confirm_endpoints(self):
        b = AvailabilityBatch.objects.create(source='whatsapp')
        AvailabilityLine.objects.create(batch=b, raw_text='cellcept', item=self.item, match_score=0.9)
        c = APIClient()
        c.force_authenticate(self.user)
        self.assertEqual(c.get(f'/api/supply/availability/{b.id}/analysis/').status_code, 200)
        r = c.post(f'/api/supply/availability/{b.id}/confirm-matches/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['confirmed'], 1)


class RealDataFindingsTests(_Base):
    """Regressions for the issues found verifying /supply against real dev data."""

    def _hist(self, eff):
        from apps.procurement.models import PurchaseLine
        from apps.procurement.models import SupplierItemMapping
        PurchaseLine.objects.create(item=self.item, item_code=self.item.softech_id,
                                    branch_code='100', supplier_code='260', doc_number='9',
                                    doc_date=date.today(), doccode='10', effective_cost=eff,
                                    unit_price=eff)
        SupplierItemMapping.objects.create(supplier_code='260', item_code=self.item.softech_id,
                                           last_price=eff * 1.2)       # recent price rose

    def test_price_flag_only_for_lines_that_quote_a_price(self):
        _metric(_run(), self.item, self.a, stock=0, gap=5)
        self._hist(80)
        b = AvailabilityBatch.objects.create(source='whatsapp')
        unpriced = AvailabilityLine.objects.create(batch=b, raw_text='cellcept 5', item=self.item,
                                                   match_score=0.95, supplier_qty=5)
        priced = AvailabilityLine.objects.create(batch=b, raw_text='cellcept 5 @ 100', item=self.item,
                                                 match_score=0.95, supplier_qty=5, price=100)
        rows = {r['line_id']: r for r in analyze_batch(b)['lines']}
        self.assertNotIn('price_above_history', rows[unpriced.id]['flags'])   # no quote → no claim
        self.assertIn('price_above_history', rows[priced.id]['flags'])        # 100 vs best 80
        self.assertEqual(rows[priced.id]['better_historical_deal']['gap_pct'], 25.0)

    def test_suggested_buy_is_whole_units_capped_by_offer(self):
        from apps.supply.availability import whole_units
        self.assertEqual(whole_units(3.67), 4.0)
        self.assertEqual(whole_units(3.67, cap=3), 3.0)
        self.assertEqual(whole_units(0), 0.0)
        self.assertEqual(whole_units(5.0), 5.0)

    def test_rounding_up_to_a_whole_unit_is_not_over_buying(self):
        from apps.supply.execution import _exceeds_need, _is_override
        self.assertFalse(_exceeds_need(4, 3.67))     # next whole box — fine, no reason needed
        self.assertTrue(_exceeds_need(5, 3.67))      # beyond that — needs a reason
        self.assertTrue(_exceeds_need(1, 0))         # nothing needed at all
        self.assertFalse(_is_override(4, 3.67))
        self.assertTrue(_is_override(2, 3.67))       # buying less is a recorded deviation

    def test_order_text_collapses_softech_name_spacing(self):
        from apps.catalog.models import Item
        from apps.supply.execution import preview_order
        spaced = Item.objects.create(softech_id='800099', name='CELLCEPT  500MG   50TAB', is_active=True)
        text = preview_order([{'item_id': spaced.id, 'qty': 5}])['text']
        self.assertEqual(text, 'مطلوب:\nCELLCEPT 500MG 50TAB — 5')
