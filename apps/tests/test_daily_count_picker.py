"""
Daily counts — which items get picked (apps/stockcount/daily/picker.py). Pure reads of our own
mirrors (ItemStock, StockLedgerLine, StockAuditFinding, StockExpiryBalance, past counts);
deterministic for a given seed. Nothing here touches SOFTECH.
"""
import datetime as dt
from decimal import Decimal

from django.test import TestCase

from apps.catalog.models import ItemStock
from apps.stockcount.daily import picker
from apps.stockcount.daily.picker import Candidate
from apps.stockcount.models import (DailyCountAttempt, DailyCountPick, DailyCountSettings,
                                    StockCountSession)
from .factories import make_branch, make_item

TODAY = dt.date(2026, 11, 3)


def stock(item, branch, qty, rate=0, store='101'):
    return ItemStock.objects.create(item=item, branch=branch, softech_store_code=store,
                                    quantity_on_hand=Decimal(qty), monthly_qty=Decimal(rate))


class CandidatesTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.items = []
        for i in range(10):
            it = make_item(f'صنف {i}', f'I{i:03d}')
            it.cost_price = Decimal(10 + i)
            it.save()
            stock(it, self.branch, 2, rate=1)
            self.items.append(it)

    def by_code(self):
        return {c.item_code: c for c in picker.candidates(self.branch, TODAY)}

    def test_weights_reasons_high_value(self):
        big = make_item('غالي', 'BIG01')
        big.cost_price = Decimal('900')
        big.save()
        stock(big, self.branch, 5, rate=1)
        c = self.by_code()
        self.assertIn('قيمة عالية', c['BIG01'].reasons)
        self.assertGreater(c['BIG01'].weight, c['I000'].weight)

    def test_negative_stock_eligible_and_flagged(self):
        neg = make_item('سالب', 'NEG01')
        stock(neg, self.branch, -3)
        c = self.by_code()
        self.assertIn('NEG01', c)
        self.assertIn('رصيد سالب', c['NEG01'].reasons)

    def test_quarantine_zero_and_inactive_excluded(self):
        q = make_item('عزل', 'QRN01')
        stock(q, self.branch, 4, store='102')
        z = make_item('صفر', 'ZER01')
        stock(z, self.branch, 0)
        off = make_item('موقوف', 'OFF01')
        off.is_active = False
        off.save()
        stock(off, self.branch, 4)
        c = self.by_code()
        for code in ('QRN01', 'ZER01', 'OFF01'):
            self.assertNotIn(code, c)

    def _count(self, code, days_ago, diff=Decimal('0')):
        s = StockCountSession.objects.create(name='d', mode='daily', branch_code=self.branch.softech_branch_id,
                                             count_date=TODAY - dt.timedelta(days=days_ago))
        p = DailyCountPick.objects.create(session=s, item_code=code, item_name=code, status='counted')
        a = DailyCountAttempt.objects.create(pick=p, counted_qty=Decimal('2') + diff, expected_qty=Decimal('2'),
                                             expected_source='live', expected_read_at=s.created_at,
                                             difference=diff)
        DailyCountAttempt.objects.filter(pk=a.pk).update(
            created_at=dt.datetime.combine(TODAY - dt.timedelta(days=days_ago), dt.time(10), tzinfo=dt.timezone.utc))

    def test_recently_counted_skipped_unless_flagged(self):
        self._count('I001', 3)                       # clean count 3 days ago → rotated out
        self._count('I002', 3, diff=Decimal('-1'))   # had a difference → stays in
        c = self.by_code()
        self.assertNotIn('I001', c)
        self.assertIn('I002', c)
        self.assertIn('فروق سابقة', c['I002'].reasons)

    def test_never_counted_has_reason(self):
        self.assertIn('لم يُجرد من قبل', self.by_code()['I005'].reasons)

    def test_near_expiry_asks_expiry(self):
        from apps.batches.models import StockExpiryBalance
        StockExpiryBalance.objects.create(branch_code=self.branch.softech_branch_id, store_code='101',
                                          item_code='I004', expiry_date=TODAY + dt.timedelta(days=40),
                                          qty=Decimal('2'))
        c = self.by_code()['I004']
        self.assertTrue(c.ask_expiry)
        self.assertIn('قرب انتهاء', c.reasons)


def cands(n):
    return [Candidate(item_code=f'C{i:03d}', item_name=f'C{i}', weight=1.0 + i / 10, reasons=[], ask_expiry=False)
            for i in range(n)]


class DrawTests(TestCase):
    def test_draw_deterministic_same_seed(self):
        a = picker.draw(cands(80), [1, 2, 3], 20, seed='B01|2026-11-03')
        b = picker.draw(cands(80), [1, 2, 3], 20, seed='B01|2026-11-03')
        self.assertEqual({k: [c.item_code for c in v] for k, v in a.items()},
                         {k: [c.item_code for c in v] for k, v in b.items()})
        self.assertEqual([len(a[p]) for p in (1, 2, 3)], [20, 20, 20])

    def test_draw_no_overlap_between_people(self):
        out = picker.draw(cands(80), [1, 2, 3], 20, seed='x')
        codes = [c.item_code for v in out.values() for c in v]
        self.assertEqual(len(codes), len(set(codes)))

    def test_fewer_items_than_needed(self):
        out = picker.draw(cands(25), [1, 2], 20, seed='x')
        codes = [c.item_code for v in out.values() for c in v]
        self.assertEqual(len(codes), 25)
        self.assertEqual(len(set(codes)), 25)

    def test_settings_singleton(self):
        self.assertEqual(DailyCountSettings.get().items_per_person, 20)
