"""B3 — near-expiry rebalancing worklist (apps/batches/rebalance.py). Pure rules + mirrors; no SOFTECH."""
import datetime as dt
from decimal import Decimal

from django.test import TestCase

from apps.batches import rebalance as RB

T = dt.date(2026, 10, 7)


def day(n):
    return T + dt.timedelta(days=n)


def b(item, br, exp_days, qty, batch='B1'):
    return {'item': item, 'branch': br, 'batch_no': batch, 'expiry': day(exp_days), 'qty': qty}


def run(batches, rates, stock=None, **kw):
    opts = dict(today=T, horizon=180, min_days=30, transit=7, hq_codes=frozenset({'100'}))
    opts.update(kw)
    return RB.plan(batches, rates, stock or {}, **opts)


class PlanRuleTests(TestCase):
    def test_surplus_moves_to_fast_branch_with_transit_buffer(self):
        # source sells 0.1/day → 60 days sells 6 of 50 → 44 at risk; target sells 1/day, 53 sell-days
        lines, buckets = run([b('X', '130', 60, 50)], {('X', '130'): 0.1, ('X', '140'): 1.0})
        self.assertEqual(len(lines), 1)
        l = lines[0]
        self.assertEqual((l['from'], l['to'], l['qty'], l['days_to_expiry']), ('130', '140', 44, 60))
        self.assertEqual(buckets['no_target'], {})

    def test_fefo_earlier_batch_consumes_source_capacity_first(self):
        rates = {('X', '130'): 1.0, ('X', '140'): 5.0}
        lines, _ = run([b('X', '130', 40, 30, 'A'), b('X', '130', 50, 30, 'B')], rates)
        # A: 40 sell-days → all 30 sell; B: 50 − 30 = 20 sell, 10 at risk
        self.assertEqual([(l['batch_no'], l['qty']) for l in lines], [('B', 10)])

    def test_target_competing_stock_and_capacity_limit(self):
        rates = {('X', '130'): 0.0, ('X', '140'): 1.0, ('X', '150'): 0.5}
        stock = {('X', '140'): [(day(30), 40), (day(300), 999)]}   # only the earlier batch competes
        lines, buckets = run([b('X', '130', 67, 100)], rates, stock)
        got = {l['to']: l['qty'] for l in lines}
        self.assertEqual(got, {'140': 20, '150': 30})                # 60−40, 0.5×60
        self.assertEqual(buckets['no_target'], {('X', '130'): 50.0})

    def test_too_late_expired_and_beyond_horizon(self):
        rates = {('X', '130'): 0.0, ('X', '140'): 9.0}
        lines, buckets = run([b('X', '130', 10, 5), b('X', '130', -1, 5, 'E'), b('X', '130', 400, 5, 'F')], rates)
        self.assertEqual(lines, [])
        self.assertEqual(buckets['too_late'], {('X', '130'): 5.0})

    def test_hq_is_never_a_target_and_whole_packs_only(self):
        rates = {('X', '130'): 0.0, ('X', '100'): 9.0, ('X', '140'): 0.02}   # 140 can take 1.06 → 1 pack
        lines, _ = run([b('X', '130', 60, 3)], rates)
        self.assertEqual([(l['to'], l['qty']) for l in lines], [('140', 1)])

    def test_two_sources_share_one_target_most_urgent_first(self):
        rates = {('X', '130'): 0.0, ('X', '150'): 0.0, ('X', '140'): 1.0}
        lines, _ = run([b('X', '150', 90, 100, 'late'), b('X', '130', 40, 100, 'soon')], rates)
        self.assertEqual([(l['from'], l['qty']) for l in lines], [('130', 33), ('150', 50)])   # 83−33 left


class WorklistTests(TestCase):
    def setUp(self):
        from apps.batches.models import StockExpiryBalance
        from apps.catalog.models import Item
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        from apps.tests.factories import make_branch
        self.src, self.dst = make_branch('A', '130'), make_branch('B', '140')
        self.item = Item.objects.create(softech_id='700001', name='DRUG', cost_price=Decimal('10'), is_active=True)
        self.today = dt.date.today()
        StockExpiryBalance.objects.create(branch_code='130', store_code='130', item_code='700001', batch_no='L1',
                                          expiry_date=self.today + dt.timedelta(days=60), qty=Decimal('50'))
        StockExpiryBalance.objects.create(branch_code='130', store_code='103', item_code='700001', batch_no='Q',
                                          expiry_date=self.today + dt.timedelta(days=60), qty=Decimal('500'),
                                          is_quarantine=True)                           # quarantine ignored
        run = DemandCalculationRun.objects.create()
        for br, q90 in ((self.src, 9), (self.dst, 90)):
            ItemDemandMetrics.objects.create(run=run, item=self.item, branch=br, calc_date=self.today, qty_90d=q90)

    def test_worklist_values_and_open_transfer_flag(self):
        data = RB.worklist()
        r = data['rows'][0]
        self.assertEqual((r['from_branch'], r['to_branch'], r['qty'], r['value']), ('130', '140', 44, 440.0))
        self.assertEqual(data['totals']['rescuable_value'], 440.0)
        self.assertEqual(r['open_transfer'], '')
        from apps.tests.factories import make_user
        from apps.transfers.models import TransferRequest, TransferRequestItem
        _, staff, _ = make_user('ph', role='pharmacist', branch=self.dst)
        tr = TransferRequest.objects.create(requesting_branch=self.dst, supplying_branch=self.src, created_by=staff)
        TransferRequestItem.objects.create(request=tr, item=self.item, quantity=44)
        self.assertEqual(RB.worklist()['rows'][0]['open_transfer'], tr.request_number)
        self.assertEqual(RB.worklist(branch='150')['rows'], [])

    def test_api_and_can_create(self):
        from apps.tests.factories import make_user
        _, _, ph = make_user('ph2', role='pharmacist', branch=self.src)
        _, _, pur = make_user('pur2', role='purchasing')
        r = ph.get('/api/batches/stock-expiry/rebalance/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['can_create'])
        self.assertEqual(len(r.data['rows']), 1)
        self.assertFalse(pur.get('/api/batches/stock-expiry/rebalance/').data['can_create'])
