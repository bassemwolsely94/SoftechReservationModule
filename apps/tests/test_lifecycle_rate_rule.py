"""
Data lifecycle Stage 3: the rate_runs rule (design §5.2, §8). Keeps the last 3 completed runs, the run each
reader calls latest, the last run of each month for 24 months, running runs and runs an open ISR or rate
push still needs. Run headers stay and reviewed transfer recommendations are never touched.

Until the rule is `on` the P-56 step behaves as it always has. Once `on`, the P-56 step does nothing and the
rule deletes, so the circuit breaker stands in front of the delete. No test here reaches SOFTECH.
"""
import datetime
from dataclasses import replace
from types import SimpleNamespace
from unittest import mock

from dateutil.relativedelta import relativedelta
from django.test import TestCase
from django.utils import timezone

from apps.data_lifecycle.models import LifecycleRulePolicy, LifecycleRunLine
from apps.data_lifecycle.register import RULES
from apps.data_lifecycle.rules_rows import tight_runs_to_keep
from apps.data_lifecycle.runner import preview_rule
from apps.purchasing.models import (
    DemandCalculationRun, IsrPush, ItemDemandAggregated, ItemDemandMetrics, SalesRatePush,
    TransferRecommendation, TransferRecommendationRun,
)
from apps.sync import maintenance
from apps.sync.maintenance import prune_engine_runs, run_daily_retention
from apps.sync.models import SyncLog

from .factories import make_admin, make_branch, make_branch2, make_item


def _aware(y, m, d, h=12):
    return timezone.make_aware(datetime.datetime(y, m, d, h, 0))


NOW = _aware(2026, 11, 10)
DAYS_OF_A_MONTH = (3, 9, 15, 21, 27)


class RateRuleTestBase(TestCase):
    def setUp(self):
        self.item = make_item()
        self.branch = make_branch()

    def _run(self, when, status='success', finished_at=None, **metric):
        run = DemandCalculationRun.objects.create(status=status, calc_date=when.date())
        DemandCalculationRun.objects.filter(pk=run.pk).update(
            started_at=when, finished_at=finished_at or when + datetime.timedelta(hours=1))
        ItemDemandMetrics.objects.create(run=run, item=self.item, branch=self.branch, calc_date=when.date(), **metric)
        ItemDemandAggregated.objects.create(run=run, item=self.item, calc_date=when.date())
        return run

    def _fifteen(self, now=NOW):
        """5 runs a month in each of the 3 months before `now`, oldest first."""
        first = timezone.localtime(now).replace(day=1, hour=12, minute=0, second=0, microsecond=0)
        return [self._run((first - relativedelta(months=back)).replace(day=day))
                for back in (3, 2, 1) for day in DAYS_OF_A_MONTH]

    def _newest_three(self, now=NOW):
        return [self._run(now - datetime.timedelta(days=d)) for d in (3, 2, 1)]

    def _push(self, model, run, status, age_days, now=NOW):
        # one live ISR draft per route is a database constraint, so each gets its own branch code
        extra = {'branchcode': str(200 + IsrPush.objects.count())} if model is IsrPush else {}
        push = model.objects.create(run=run, status=status, **extra)
        model.objects.filter(pk=push.pk).update(created_at=now - datetime.timedelta(days=age_days))
        return push

    def _with_rows(self):
        return set(ItemDemandMetrics.objects.values_list('run_id', flat=True))


class KeepSetTests(RateRuleTestBase):
    def test_fifteen_runs_over_three_months(self):
        runs = self._fifteen()
        failed = self._run(NOW - datetime.timedelta(days=1), status='failed')
        running = self._run(NOW - datetime.timedelta(days=40), status='running')
        self._push(IsrPush, runs[1], 'proposed', 10)
        self._push(SalesRatePush, runs[6], 'approved', 10)
        expected = {r.pk for r in runs[-3:]} | {runs[4].pk, runs[9].pk, runs[1].pk, runs[6].pk, running.pk}

        self.assertEqual(tight_runs_to_keep(now=NOW), expected)
        removed = prune_engine_runs(keep=tight_runs_to_keep(now=NOW))

        self.assertEqual(self._with_rows(), expected)
        self.assertEqual(set(ItemDemandAggregated.objects.values_list('run_id', flat=True)), expected)
        self.assertNotIn(failed.pk, self._with_rows())
        self.assertEqual(DemandCalculationRun.objects.count(), 17)      # run headers are kept
        self.assertEqual(removed['metrics'], 17 - len(expected))

    def _old_run_and_later_of_its_month(self):
        old = self._run(_aware(2026, 3, 5))
        self._run(_aware(2026, 3, 20))      # March's last run, the one kept as monthly
        self._newest_three()
        return old

    def _assert_push_limits(self, model, open_statuses, closed_statuses):
        for status in open_statuses:
            with self.subTest(status=status, age=89):
                old = self._old_run_and_later_of_its_month()
                self._push(model, old, status, 89)
                self.assertIn(old.pk, tight_runs_to_keep(now=NOW))
            with self.subTest(status=status, age=91):
                old = self._old_run_and_later_of_its_month()
                self._push(model, old, status, 91)
                self.assertNotIn(old.pk, tight_runs_to_keep(now=NOW))
        for status in closed_statuses:
            with self.subTest(status=status, age=1):
                old = self._old_run_and_later_of_its_month()
                self._push(model, old, status, 1)
                self.assertNotIn(old.pk, tight_runs_to_keep(now=NOW))

    def test_open_isr_holds_its_run(self):
        self._assert_push_limits(IsrPush, ('proposed', 'approved'), ('pushed', 'cancelled', 'failed'))

    def test_proposed_rate_push_holds_its_run(self):
        self._assert_push_limits(SalesRatePush, ('proposed', 'approved'), ('executed', 'cancelled', 'failed'))

    def test_push_with_no_run_holds_nothing(self):
        self._newest_three()
        self._push(IsrPush, None, 'proposed', 1)
        self.assertNotIn(None, tight_runs_to_keep(now=NOW))

    def test_monthly_older_than_24_months_goes(self):
        too_old = self._run(_aware(2024, 10, 28))    # 25 calendar months back: gone
        edge = self._run(_aware(2024, 11, 2))        # 24 calendar months back: the whole month still counts
        kept = self._run(_aware(2025, 1, 20))
        newest = self._newest_three()

        prune_engine_runs(keep=tight_runs_to_keep(now=NOW))

        self.assertNotIn(too_old.pk, self._with_rows())
        self.assertEqual(self._with_rows(), {edge.pk, kept.pk, *(r.pk for r in newest)})
        self.assertTrue(DemandCalculationRun.objects.filter(pk=too_old.pk).exists())


class LatestDefinitionTests(RateRuleTestBase):
    def _assert_readers_have_rows(self):
        from apps.purchasing import rate_writer, shortage, views
        for reader in (lambda: shortage._latest_run(None), rate_writer._latest_run, views._latest_run):
            run = reader()
            self.assertTrue(ItemDemandMetrics.objects.filter(run=run).exists(), run)
            self.assertTrue(ItemDemandAggregated.objects.filter(run=run).exists(), run)

    def test_every_latest_definition_is_kept(self):
        """A long run that started early and finished last is what rate_writer._latest_run reads."""
        long_run = self._run(_aware(2026, 10, 1), finished_at=_aware(2026, 11, 9, 23))
        self._run(_aware(2026, 10, 3))      # October's last run by started_at, so the long run is not kept as monthly
        self._newest_three()

        prune_engine_runs(keep=tight_runs_to_keep(now=NOW))

        self.assertIn(long_run.pk, self._with_rows())
        self._assert_readers_have_rows()

    def test_newest_id_is_kept(self):
        """spike_views reads the newest id, whatever its dates say."""
        self._newest_three()
        self._run(_aware(2026, 10, 25))
        newest_id = self._run(_aware(2026, 10, 2))

        prune_engine_runs(keep=tight_runs_to_keep(now=NOW))

        self.assertIn(newest_id.pk, self._with_rows())

    def test_readers_only_read_success_so_partial_runs_cannot_crowd_it_out(self):
        success = self._run(_aware(2026, 10, 5))
        self._run(_aware(2026, 10, 25), status='partial')
        for day in (1, 2, 3):
            self._run(_aware(2026, 11, day), status='partial')

        prune_engine_runs(keep=tight_runs_to_keep(now=NOW))

        self.assertIn(success.pk, self._with_rows())
        self._assert_readers_have_rows()

    def test_tie_of_four_on_one_calc_date(self):
        self._newest_three()
        same_day = NOW - datetime.timedelta(hours=6)
        for hour in range(4):
            self._run(same_day + datetime.timedelta(hours=hour))

        prune_engine_runs(keep=tight_runs_to_keep(now=NOW))

        self._assert_readers_have_rows()

    def test_dead_stock_growth_finds_older_run(self):
        from apps.insights.rules import rule_dead_stock_growth
        ctx = SimpleNamespace(branches=[self.branch], bn=lambda branch, lang: branch.name)
        runs = self._fifteen()
        self.assertTrue(ItemDemandMetrics.objects.filter(run=runs[9]).update(
            monthly_avg=0, current_stock=10, pack_price=10))       # September's last run
        ItemDemandMetrics.objects.filter(run=runs[14]).update(monthly_avg=0, current_stock=20, pack_price=10)

        prune_engine_runs(keep=tight_runs_to_keep(now=NOW))

        found = rule_dead_stock_growth(ctx, 10)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['baseline'], 100)
        self.assertEqual(found[0]['value'], 200)
        kept_dates = dict(DemandCalculationRun.objects.values_list('pk', 'calc_date'))
        self.assertGreaterEqual((kept_dates[runs[14].pk] - kept_dates[runs[9].pk]).days, 20)
        self.assertIn(str(kept_dates[runs[9].pk]), found[0]['message_en'])


class TransferRecommendationTests(RateRuleTestBase):
    def test_reviewed_recommendation_survives(self):
        old = self._run(_aware(2026, 3, 5))
        self._run(_aware(2026, 3, 20))
        newest = self._newest_three()
        other = make_branch2()
        old_run = TransferRecommendationRun.objects.create(demand_run=old, status='success')
        new_run = TransferRecommendationRun.objects.create(demand_run=newest[-1], status='success')

        def rec(run, status, code):
            return TransferRecommendation.objects.create(
                run=run, status=status, item=make_item(code, code), from_branch=self.branch, to_branch=other,
                quantity=1)
        reviewed = [rec(old_run, status, f'R{i}') for i, status in enumerate(('approved', 'rejected', 'executed'))]
        old_pending = rec(old_run, 'pending', 'P1')
        new_pending = rec(new_run, 'pending', 'P2')

        prune_engine_runs(keep=tight_runs_to_keep(now=NOW))

        left = set(TransferRecommendation.objects.values_list('pk', flat=True))
        self.assertEqual(left, {r.pk for r in reviewed} | {new_pending.pk})
        self.assertNotIn(old_pending.pk, left)


class SwitchTests(RateRuleTestBase):
    """Which code deletes: the P-56 step until the rule is on, then only the rule behind its breaker."""

    def _turn_on(self):
        LifecycleRulePolicy.objects.create(rule_key='rate_runs', mode='on', reason='test')

    def _step_count(self, run, name='retention:engine_runs'):
        return SyncLog.objects.get(sync_run=run, table_name=name).records_processed

    def test_engine_runs_to_keep_is_not_tightened_by_the_mode(self):
        self._fifteen(timezone.now())
        before = maintenance.engine_runs_to_keep()
        self._turn_on()
        self.assertEqual(maintenance.engine_runs_to_keep(), before)
        self.assertEqual(len(before), 11)

    def test_preview_mode_keeps_ten(self):
        """Until switched on, today's behaviour is unchanged and the rule only counts."""
        runs = self._fifteen(timezone.now())
        expected = {r.pk for r in runs[-10:]} | {runs[4].pk}

        run = run_daily_retention()

        self.assertEqual(self._with_rows(), expected)
        self.assertEqual(self._step_count(run), 8)      # 4 runs × (metrics + aggregated)
        line = LifecycleRunLine.objects.get(rule_key='rate_runs')
        self.assertTrue(line.is_preview)
        tight = tight_runs_to_keep()
        self.assertEqual(line.count, 2 * len(expected - tight))

    def test_off_mode_leaves_the_p56_step_running(self):
        runs = self._fifteen(timezone.now())
        LifecycleRulePolicy.objects.create(rule_key='rate_runs', mode='off', reason='test')

        run = run_daily_retention()

        self.assertEqual(self._with_rows(), {r.pk for r in runs[-10:]} | {runs[4].pk})
        self.assertEqual(self._step_count(run), 8)
        self.assertFalse(LifecycleRunLine.objects.filter(rule_key='rate_runs').exists())

    def test_on_mode_only_the_rule_deletes(self):
        runs = self._fifteen(timezone.now())
        self._turn_on()
        tight = tight_runs_to_keep()
        removable = 2 * (len(runs) - len(tight))

        run = run_daily_retention()

        self.assertEqual(self._with_rows(), tight)
        self.assertEqual(self._step_count(run), 0)
        self.assertEqual(self._step_count(run, 'retention:lifecycle'), removable)
        line = LifecycleRunLine.objects.get(rule_key='rate_runs')
        self.assertFalse(line.is_preview)
        self.assertEqual((line.count, line.error), (removable, ''))

    def test_on_mode_oversized_run_is_stopped_by_the_breaker(self):
        """The P-56 step must not delete in the breaker's place: everything stays."""
        runs = self._fifteen(timezone.now())
        self._turn_on()

        with mock.patch.dict(RULES, {'rate_runs': replace(RULES['rate_runs'], margin=1)}):
            run = run_daily_retention()

        self.assertEqual(self._with_rows(), {r.pk for r in runs})
        self.assertEqual(self._step_count(run), 0)
        self.assertEqual(self._step_count(run, 'retention:lifecycle'), 0)
        line = LifecycleRunLine.objects.get(rule_key='rate_runs')
        self.assertTrue(line.stopped_by_breaker)
        self.assertEqual(line.count, 0)

    def test_prune_with_no_keep_set_uses_todays_set(self):
        runs = self._fifteen(timezone.now())
        prune_engine_runs()
        self.assertEqual(self._with_rows(), {r.pk for r in runs[-10:]} | {runs[4].pk})

    def test_rule_is_wired_and_preview_matches_the_real_removal(self):
        rule = RULES['rate_runs']
        self.assertIsNotNone(rule.apply)
        self._fifteen(timezone.now())
        counted = {'purchasing.ItemDemandMetrics', 'purchasing.ItemDemandAggregated',
                   'purchasing.TransferRecommendation'}
        self.assertEqual({qs.model._meta.label for qs in rule.candidates()}, counted)
        self.assertEqual(set(rule.targets), counted)

        previewed = preview_rule('rate_runs').count
        self.assertGreater(previewed, 0)
        self.assertEqual(ItemDemandMetrics.objects.count(), 15)     # a preview removes nothing

        removed = rule.apply()
        self.assertIs(type(removed), int)
        self.assertEqual(removed, previewed)


class IsrReaderTests(RateRuleTestBase):
    ISR = {'isr': '261609', 'branch': '160', 'for_branch': '100', 'date': '2026-10-01', 'approved': 1,
           'value': 60.0, 'user': '11', 'lines': [{'code': 'A', 'qty': 6.0, 'cost': 10.0}]}

    def test_isr_reader_after_prune(self):
        from apps.purchasing import isr_fulfillment as F
        old = self._run(_aware(2026, 3, 5))
        self._run(_aware(2026, 3, 20))
        self._newest_three()
        pushed = self._push(IsrPush, old, 'pushed', 200)
        prune_engine_runs(keep=tight_runs_to_keep(now=NOW))
        self.assertFalse(ItemDemandMetrics.objects.filter(run=old).exists())
        no_rows_yet = DemandCalculationRun.objects.create(status='success', calc_date=NOW.date())
        DemandCalculationRun.objects.filter(pk=no_rows_yet.pk).update(started_at=NOW, finished_at=NOW)
        proposal = IsrPush.objects.create(run=no_rows_yet, status='proposed', branchcode='160')

        with mock.patch('config.sybase.get_sybase_connection', side_effect=AssertionError('reached SOFTECH')), \
                mock.patch.object(F, '_live_stock', return_value=({}, [], {})), \
                mock.patch('apps.purchasing.in_transit.by_branch_code', return_value=({}, 14)):
            snap = F.collect_requests([dict(self.ISR)])
        self.assertEqual(snap['run_id'], no_rows_yet.pk)
        self.assertEqual(snap['eng'], {})
        self.assertEqual(F.compute(snap, 1)['isrs'][0]['isr'], '261609')

        client = make_admin('rate_rule_admin')[2]
        results = {row['id']: row for row in client.get('/api/purchasing/isr/pushes/').data['results']}
        self.assertEqual(results[pushed.pk]['run_id'], old.pk)
        self.assertEqual(results[proposal.pk]['run_id'], no_rows_yet.pk)
        self.assertEqual(client.get(f'/api/purchasing/isr/pushes/{pushed.pk}/').data['run_id'], old.pk)
