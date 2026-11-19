"""
Market Shortage speed (performance Stage 3.1, docs/superpowers/plans/2026-11-19-perf-stage3-market-shortage.md).

item_signals used to build a model object for every stockable item (51,905 on the office data, ~8 s even with
the sales cache warm) and counted sale months with COUNT(DISTINCT ...). It now decides candidacy from the
sales/stock numbers first and loads only candidates + confirmed + dismissed items, and counts months with a
bitmask. These tests pin that:
  - the signals and the JSON of candidates / deltas / confirmed / med-types are identical to the
    pre-change implementation (kept below as REFERENCE) for the same data;
  - the number of queries does not grow with the number of items;
  - an item with no signal and no saved state is never loaded.
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.db.models import Sum
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.catalog.models import Item
from apps.purchasing import shortage as S
from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics, SalesTransactionLine
from apps.tests.factories import make_admin, make_branch

ENDPOINTS = ('candidates/', 'deltas/', 'confirmed/', 'med-types/', 'dismissed/')


# ── REFERENCE: item_signals exactly as it was before Stage 3.1 (no cache, every stockable item) ──
def reference_item_signals(run=None):
    run = S._latest_run(run)
    if run is None:
        return {}, None
    stock = {r['item_id']: float(r['s'] or 0)
             for r in ItemDemandMetrics.objects.filter(run=run)
             .values('item_id').annotate(s=Sum('current_stock'))}
    with connection.cursor() as cur:
        cur.execute("""
            SELECT item_id,
                   SUM(CASE WHEN doc_date >= CURRENT_DATE - 30  THEN net_qty ELSE 0 END),
                   SUM(CASE WHEN doc_date >= CURRENT_DATE - 365 THEN net_qty ELSE 0 END),
                   COUNT(DISTINCT date_trunc('month', doc_date))
                         FILTER (WHERE doc_date >= CURRENT_DATE - 365 AND net_qty > 0)
            FROM purchasing_salestransactionline
            WHERE item_id IS NOT NULL AND doccode = '115'
            GROUP BY item_id
        """)
        sales = {r[0]: (float(r[1] or 0), float(r[2] or 0), int(r[3] or 0)) for r in cur.fetchall()}
    items = {i.id: i for i in Item.objects.filter(is_stockable=True).only(
        'id', 'softech_id', 'name', 'unit_price', 'pack_price', 'medicine_type',
        'medicine_type_name_ar', 'medicine_type_name',
        'in_shortage', 'shortage_source', 'shortage_dismissed')}
    out = {}
    for item_id, item in items.items():
        q30, q365, months = sales.get(item_id, (0.0, 0.0, 0))
        hist = q365 / 12.0
        st = stock.get(item_id, 0.0)
        coverage = st / hist if hist > 0 else (0.0 if st == 0 else 999.0)
        suppression = max(0.0, 1.0 - (q30 / hist)) if hist > 0 else 0.0
        is_candidate = (q365 >= S.MIN_ANNUAL_QTY and months >= S.MIN_SALE_MONTHS
                        and hist > 0 and coverage < S.COVERAGE_MAX)
        if not (is_candidate or item.in_shortage or item.shortage_dismissed):
            continue
        price = float(item.pack_price or 0)
        lost_units = max(0.0, hist - q30)
        out[item_id] = {
            'item': item,
            'annual_qty': q365, 'monthly_hist': hist, 'stock': st,
            'coverage': round(coverage, 3), 'qty_30d': q30, 'sale_months': months,
            'suppression': round(suppression, 3), 'price': price,
            'lost_monthly': round(lost_units * price, 2),
            'is_candidate': is_candidate,
            'tier': S._tier(coverage, suppression) if is_candidate else '',
            'score': round(hist * (1 - min(coverage, 1)) * (0.4 + 0.6 * suppression), 2)
                     if is_candidate else 0.0,
            'healthy': S._healthy(coverage, suppression),
        }
    return out, run


def _plain(sig):
    """Signals without the model object, plus the item fields consumers read."""
    out = {}
    for iid, s in sig.items():
        it = s['item']
        row = {k: v for k, v in s.items() if k != 'item'}
        row['item'] = (it.id, it.softech_id, it.name, it.unit_price, it.pack_price, it.medicine_type,
                       it.medicine_type_name_ar, it.medicine_type_name, it.in_shortage,
                       it.shortage_source, it.shortage_dismissed)
        out[iid] = row
    return out


class _Data:
    """Items with sales over the last ~13 months, a stock figure, and saved flags."""

    def setup_data(self, n_extra=0):
        cache.clear()
        self.branch = make_branch('فرع 130', '130')
        self.today = timezone.localdate()
        self.old_run = DemandCalculationRun.objects.create(status='success', finished_at=timezone.now())
        self.old_run.started_at = timezone.now() - timedelta(days=1)
        self.old_run.save(update_fields=['started_at'])
        self.run = DemandCalculationRun.objects.create(status='success', finished_at=timezone.now())
        self._n = 0
        med = [('01', 'دواء', 'Medicine'), ('02', 'تجميل', 'Cosmetics'), ('', '', '')]
        # (monthly qty by months-ago, last-30-day qty, stock, flags)
        specs = [
            ([10] * 12, 0, 0, {}),                                  # tier 1: out, sales collapsed
            ([10] * 12, 8, 1, {}),                                  # tier 2: low cover
            ([10] * 12, 9, 4, {}),                                  # tier 3: watch
            ([6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6], 6, 0, {}),    # 13 calendar months of sales
            ([30, 0, 0, 30, 0, 0, 30, 0, 0, 0, 0, 0], 0, 0, {}),    # exactly 3 sale months
            ([30, 0, 0, 30, 0, 0, 0, 0, 0, 0, 0, 0], 0, 0, {}),     # 2 months: not a candidate
            ([1] * 11, 0, 0, {}),                                   # 11 / year: below MIN_ANNUAL_QTY
            ([10] * 12, 0, 0, {'in_shortage': True, 'shortage_source': 'manual'}),
            ([10] * 12, 10, 500, {'in_shortage': True, 'shortage_source': 'auto'}),   # recovering
            ([10] * 12, 0, 0, {'shortage_dismissed': True, 'shortage_dismiss_reason': 'variant'}),  # re-entered
            ([], 0, 0, {'shortage_dismissed': True}),               # dismissed, quiet
            ([], 0, 3, {'in_shortage': True}),                      # confirmed, no sales, some stock
            ([], 0, 0, {}),                                         # quiet: must never be loaded
            ([10] * 12, 0, 50, {}),                                 # healthy: not a candidate
        ] + [([10] * 12, 0, 0, {})] * n_extra           + [([10] * 12, 0, 0, {'in_shortage': True})] * n_extra           + [([], 0, 0, {'shortage_dismissed': True})] * n_extra
        self.quiet = None
        for k, (months, q30, stock, flags) in enumerate(specs):
            code, ar, en = med[k % 3]
            it = self._item(months, q30, stock, flags, code, ar, en)
            if not months and not flags:
                self.quiet = it
        # who confirmed / dismissed (their names read StaffProfile.user — must not cost a query per row)
        _, staff, _ = make_admin(f'ms_by{n_extra}')
        Item.objects.filter(in_shortage=True).update(shortage_confirmed_by=staff)
        Item.objects.filter(shortage_dismissed=True).update(shortage_dismissed_by=staff)
        # a return line (doccode 30) and a zero line must not count
        it = Item.objects.filter(softech_id='SP1').first()
        self._line(it, self.today - timedelta(days=3), -5, doccode='30')
        self._line(it, self.today - timedelta(days=4), 0)
        # baseline snapshot for the older run, then the current run's snapshot (both via REFERENCE)
        with mock.patch.object(S, 'item_signals', reference_item_signals):
            S.ensure_snapshot(self.old_run)
            S.ensure_snapshot(self.run)
        cache.clear()

    def _item(self, months, q30, stock, flags, code, ar, en):
        self._n += 1
        it = Item.objects.create(
            softech_id=f'SP{self._n}', name=f'صنف {self._n}', is_stockable=True,
            unit_price=Decimal('3.5') * self._n, pack_price=Decimal('40') + self._n,
            medicine_type=code, medicine_type_name_ar=ar, medicine_type_name=en, **flags)
        # one line in the middle of each month back (35 + 30*m days ago); q30 at 10 days ago
        for m, qty in enumerate(months):
            if qty:
                self._line(it, self.today - timedelta(days=35 + 30 * m), qty)
        if q30:
            self._line(it, self.today - timedelta(days=10), q30)
        for run in (self.old_run, self.run):
            ItemDemandMetrics.objects.create(run=run, item=it, branch=self.branch,
                                             calc_date=self.today, current_stock=stock)
        return it

    def _line(self, it, day, qty, doccode='115'):
        SalesTransactionLine.objects.create(
            softech_branchcode='130', softech_itemcode=it.softech_id, doccode=doccode,
            docnumber=f'D{SalesTransactionLine.objects.count()}', doc_date=day, item=it,
            branch=self.branch, transqty=abs(qty), net_qty=qty)


class ShortageIdenticalOutputTests(_Data, TestCase):

    def setUp(self):
        self.setup_data()
        _, _, self.client = make_admin('ms_perf')

    def tearDown(self):
        cache.clear()

    def test_signals_equal_the_reference(self):
        ref, _ = reference_item_signals()
        cache.clear()
        new, run = S.item_signals()
        self.assertEqual(run, self.run)
        self.assertEqual(_plain(new), _plain(ref))
        tiers = {s['tier'] for s in ref.values()}
        self.assertTrue({S.TIER_STOCKOUT, S.TIER_SEVERE, S.TIER_WATCH} <= tiers, tiers)

    def _bodies(self):
        out = {}
        for path in ENDPOINTS:
            r = self.client.get(f'/api/purchasing/shortage/{path}')
            self.assertEqual(r.status_code, 200, path)
            body = r.json()
            body.pop('signals_as_of', None)
            out[path] = body
        return out

    def test_endpoints_equal_the_reference(self):
        with mock.patch.object(S, 'item_signals', reference_item_signals):
            before = self._bodies()
        cache.clear()
        after = self._bodies()
        self.assertEqual(after, before)
        self.assertTrue(before['deltas/']['recovering'])
        self.assertTrue(before['deltas/']['re_entered'])
        self.assertTrue(before['candidates/']['candidates'])

    def test_responses_say_when_the_figures_were_computed(self):
        for path in ('candidates/', 'deltas/', 'confirmed/'):
            body = self.client.get(f'/api/purchasing/shortage/{path}').json()
            self.assertTrue(body.get('signals_as_of'), path)

    def test_only_items_with_a_signal_or_saved_state_are_loaded(self):
        real = Item.from_db.__func__
        loaded = []

        def spy(cls, db, field_names, values):
            loaded.append(values[list(field_names).index('id')])
            return real(cls, db, field_names, values)

        with mock.patch.object(Item, 'from_db', classmethod(spy)):
            sig, _ = S.item_signals()
        self.assertNotIn(self.quiet.id, loaded)
        self.assertEqual(sorted(loaded), sorted(sig))


class ShortageQueryCountTests(TestCase):
    """The query count per endpoint does not grow with the number of items."""

    def _counts(self, n_extra):
        data = _Data()
        data.setup_data(n_extra)
        _, _, client = make_admin(f'ms_q{n_extra}')
        counts = {}
        for path in ENDPOINTS:
            client.get(f'/api/purchasing/shortage/{path}')          # warm: snapshot + sales cache
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(client.get(f'/api/purchasing/shortage/{path}').status_code, 200)
            counts[path] = len(ctx.captured_queries)
        cache.clear()
        return counts

    def test_flat_in_items(self):
        small = self._counts(0)
        Item.objects.all().delete()
        SalesTransactionLine.objects.all().delete()
        DemandCalculationRun.objects.all().delete()
        big = self._counts(12)
        self.assertEqual(big, small)
