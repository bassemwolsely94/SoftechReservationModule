"""
apps/tests/test_expiry_buckets.py

P-26 (docs/product-review/06_SPEC_P-26_one_expiry_number.md): one store-role map, and every
expiry number reads it. Owner decision 2026-10-31: the closed branch's store 110 is excluded
from every number, screen and export (no alert, no clean-up list).
"""
import datetime as dt
import json
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase

from apps.batches import store_roles
from apps.batches.models import StockExpiryBalance
from apps.batches.stock_expiry import (
    fefo_at_risk, stock_expiry_report, stock_expiry_stores, stock_expiry_summary,
)

TODAY = dt.date.today()


def days(n):
    return TODAY + dt.timedelta(days=n)


def row(item, branch='130', store='101', exp=-10, qty='1', batch=''):
    return StockExpiryBalance.objects.create(branch_code=branch, store_code=store, item_code=item,
                                             item_name=item, batch_no=batch, expiry_date=days(exp),
                                             qty=Decimal(qty))


def _setting(key, value):
    from apps.config.models import SystemSetting
    SystemSetting.objects.update_or_create(key=key, defaults={'label': key, 'value': json.dumps(value),
                                                             'value_type': 'json'})


class RoleMapTests(TestCase):

    def test_defaults(self):
        self.assertEqual(store_roles.store_role('100', '110'), 'closed')
        self.assertEqual(store_roles.store_role('100', '105'), 'return_candidate')
        self.assertEqual(store_roles.store_role('130', '102'), 'write_off')      # any node, as before
        self.assertEqual(store_roles.store_role('100', '103'), 'cosmetics_expired')
        self.assertEqual(store_roles.store_role('130', '101'), 'live')
        self.assertEqual(store_roles.store_role('130', '110'), 'live')           # 110 is closed on HQ only

    def test_setting_overrides_a_default(self):
        _setting('expiry_store_roles', {'130:101': 'write_off'})
        self.assertEqual(store_roles.store_role('130', '101'), 'write_off')
        self.assertEqual(store_roles.store_role('100', '110'), 'closed')          # other defaults kept

    def test_bad_setting_falls_back_to_defaults(self):
        _setting('expiry_store_roles', {'130:101': 'not_a_role', 'junk': 'live'})
        self.assertEqual(store_roles.store_role('130', '101'), 'live')
        _setting('expiry_store_roles', ['not', 'a', 'dict'])
        self.assertEqual(store_roles.store_role('100', '105'), 'return_candidate')

    def test_store_on_a_closed_branch_is_closed(self):
        from apps.tests.factories import make_branch
        b = make_branch('مغلق', '190')
        b.kind = 'closed'
        b.save(update_fields=['kind'])
        self.assertEqual(store_roles.store_role('190', '1'), 'closed')

    def test_saved_row_gets_its_role(self):
        self.assertEqual(row('A', '100', '110').store_role, 'closed')
        r = row('B', '100', '105')
        self.assertEqual(r.store_role, 'return_candidate')
        self.assertTrue(r.is_quarantine)


class SyncTagsRolesTests(TestCase):

    def test_sync_writes_store_role(self):
        from apps.batches import stock_expiry
        from apps.tests.factories import make_branch
        make_branch('HQ', '100')

        class Cur:
            def execute(self, *a, **k):
                pass

            def fetchall(self):
                return [('I1', days(10), 5, '110', 'L', 'x'), ('I2', days(10), 5, '105', 'L', 'y'),
                        ('I3', days(10), 5, '101', 'L', 'z')]

        class Conn:
            def cursor(self):
                return Cur()

            def close(self):
                pass

        with mock.patch.object(stock_expiry, '_node_conn', return_value=Conn()):
            stock_expiry.sync_stock_expiry_all(only_branch='100')
        got = dict(StockExpiryBalance.objects.values_list('item_code', 'store_role'))
        self.assertEqual(got, {'I1': 'closed', 'I2': 'return_candidate', 'I3': 'live'})


class SummaryAndReportTests(TestCase):

    def setUp(self):
        from apps.catalog.models import Item
        for code, cost in (('L1', 10), ('L2', 10), ('C1', 100), ('R1', 20), ('W1', 5)):
            Item.objects.create(softech_id=code, name=code, cost_price=Decimal(cost))
        row('L1', exp=-5, qty='2')                       # live, expired on the shelf → 20
        row('L2', exp=20, qty='3')                       # live, < 30 days → 30
        row('C1', '100', '110', exp=-900, qty='1000')    # closed branch → 100,000, never counted
        row('R1', '100', '105', exp=-20, qty='4')        # return candidate → 80
        row('W1', '100', '102', exp=-400, qty='6')       # write-off → 30

    def test_summary_top_level_is_live_only(self):
        s = stock_expiry_summary()
        self.assertEqual(s['expired']['value'], 20.0)
        self.assertEqual(s['lt_30']['value'], 30.0)

    def test_closed_never_counted_even_with_quarantine(self):
        s = stock_expiry_summary(include_quarantine=True)
        self.assertEqual(s['expired']['value'], 20.0 + 80.0 + 30.0)
        self.assertNotIn('closed', s['buckets'])

    def test_buckets(self):
        b = stock_expiry_summary()['buckets']
        self.assertEqual(set(b), {'live', 'return_candidate', 'write_off', 'cosmetics_expired'})
        self.assertEqual(b['return_candidate']['value'], 80.0)
        self.assertEqual(b['write_off']['value'], 30.0)
        self.assertEqual(b['cosmetics_expired']['value'], 0.0)
        self.assertEqual(b['live']['expired']['value'], 20.0)
        self.assertEqual(b['live']['value'], 50.0)

    def test_report_default_is_live(self):
        codes = {r['item_code'] for r in stock_expiry_report(mode='all')}
        self.assertEqual(codes, {'L1', 'L2'})

    def test_report_quarantine_never_closed(self):
        codes = {r['item_code'] for r in stock_expiry_report(mode='all', include_quarantine=True)}
        self.assertEqual(codes, {'L1', 'L2', 'R1', 'W1'})

    def test_report_roles_filter(self):
        codes = {r['item_code'] for r in stock_expiry_report(mode='all', roles=['return_candidate', 'closed'])}
        self.assertEqual(codes, {'R1'})

    def test_stores_list_has_roles_and_no_closed_store(self):
        stores = stock_expiry_stores()
        self.assertNotIn(('100', '110'), {(s['branch_code'], s['store_code']) for s in stores})
        by = {(s['branch_code'], s['store_code']): s for s in stores}
        self.assertEqual(by[('100', '105')]['role'], 'return_candidate')
        self.assertTrue(by[('100', '105')]['role_label'])
        self.assertTrue(by[('100', '105')]['is_quarantine'])

    def test_rebalance_ignores_closed_store(self):
        from apps.batches import rebalance
        batches, *_ = rebalance._load(TODAY, 180)
        self.assertNotIn('C1', {b['item'] for b in batches})


class FefoAtRiskTests(SimpleTestCase):

    def test_fefo_maths(self):
        # rate 0.5/day: batch A (10 days, 10) sells 5 → 5 at risk; batch B (40 days, 20) sells 20−5=15 → 5
        rows = [(days(40), 20.0), (days(10), 10.0)]
        self.assertEqual(fefo_at_risk(rows, 0.5, TODAY, within_days=180), 10.0)

    def test_window_and_expired_rows_ignored(self):
        rows = [(days(-1), 50.0), (days(200), 50.0), (days(30), 10.0)]
        self.assertEqual(fefo_at_risk(rows, 0.0, TODAY, within_days=180), 10.0)

    def test_fast_seller_has_no_risk(self):
        self.assertEqual(fefo_at_risk([(days(30), 10.0)], 5.0, TODAY), 0.0)


class AtRiskConsumersTests(TestCase):

    def setUp(self):
        from apps.catalog.models import Item
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        from apps.tests.factories import make_branch
        self.branch = make_branch('A', '130')
        self.item = Item.objects.create(softech_id='700001', name='DRUG', cost_price=Decimal('10'))
        row('700001', '130', '130', exp=60, qty='50')                    # sells 9/90×60 = 6 → 44 at risk
        row('700001', '100', '110', exp=60, qty='9999')                  # closed, ignored
        self.run = DemandCalculationRun.objects.create()
        self.metrics = ItemDemandMetrics.objects.create(run=self.run, item=self.item, branch=self.branch,
                                                        calc_date=TODAY, qty_90d=9)

    def test_at_risk_by_branch(self):
        from apps.batches.stock_expiry import at_risk_by_branch
        got = at_risk_by_branch()
        self.assertEqual(got['130']['value'], 440.0)
        self.assertEqual(got['130']['items'], [('700001', 440.0)])
        self.assertNotIn('100', got)

    def test_insights_rule_reads_the_mirror(self):
        from apps.batches.models import StockBatch
        from apps.insights.rules import rule_near_expiry
        self.assertFalse(StockBatch.objects.exists())

        class Ctx:
            branches = [self.branch]

            def bn(self, b, lang):
                return b.name

        out = rule_near_expiry(Ctx(), 100)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['value'], Decimal('440.00'))
        self.assertEqual(rule_near_expiry(Ctx(), 1000), [])

    def test_forecasting_expiry_risk_reads_the_mirror(self):
        from apps.forecasting.service import ForecastService
        self.assertEqual(ForecastService._expiry_risk(self.metrics), Decimal('440.00'))


class SchedulerTests(SimpleTestCase):

    def test_near_expiry_scan_not_scheduled(self):
        from apps.sync import tasks
        from .test_scheduler_jobs import _FakeScheduler
        with mock.patch.object(tasks, 'BackgroundScheduler', _FakeScheduler), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
            ids = {j[1] for j in tasks._scheduler.jobs}
        self.assertNotIn('near_expiry_scan', ids)
