"""
Tests for the Batch-2b coverage writeback (apps/purchasing/coverage_writer.py).

Pure logic + gate/guard only — build_coverage_plan / push_coverage live paths hit
Sybase and are exercised via the gated dry-run + rollback probe in ops.
"""
from django.test import TestCase, override_settings

from apps.purchasing import coverage_writer as cw


class GateTests(TestCase):
    # Gate tests pin the setting: the real .env turns these gates ON (live since
    # 2026-09-25), so relying on the environment made them flaky.
    @override_settings(COVERAGE_WRITER_ENABLED=False)
    def test_gate_off_by_default(self):
        self.assertFalse(cw.coverage_writer_enabled())

    @override_settings(COVERAGE_WRITER_ENABLED=True)
    def test_gate_reads_setting(self):
        self.assertTrue(cw.coverage_writer_enabled())

    @override_settings(COVERAGE_WRITE_MAXQTY=False)
    def test_write_maxqty_off_by_default(self):
        self.assertFalse(cw._write_maxqty_too())

    def test_probe_requires_confirm(self):
        with self.assertRaises(ValueError):
            cw.probe_coverage_write('130', '87602', confirm=False)

    @override_settings(COVERAGE_WRITER_ENABLED=False)
    def test_probe_refused_when_gate_off(self):
        # confirm=True but gate OFF → WriterDisabled before any SOFTECH contact
        with self.assertRaises(cw.WriterDisabled):
            cw.probe_coverage_write('130', '87602', confirm=True)


class RoundingTests(TestCase):
    def test_round_coverage_2dp(self):
        self.assertEqual(cw._round(1.5, cw.COVERAGE_DECIMALS), 1.5)
        self.assertEqual(cw._round(0.756, cw.COVERAGE_DECIMALS), 0.76)

    def test_round_maxqty_1dp(self):
        self.assertEqual(cw._round(4.0 * 1.5, cw.MAXQTY_DECIMALS), 6.0)
        self.assertEqual(cw._round(2.67, cw.MAXQTY_DECIMALS), 2.7)

    def test_build_plan_rejects_nonpositive_coverage(self):
        with self.assertRaises(ValueError):
            cw.build_coverage_plan(coverage_months=0)


class CoverageSkipCheckTests(TestCase):
    """Fix 2 — an item is written when coverage OR (if we write it) the max is out of date,
    on ANY targeted server. surfaces = [(months, rate, maxqty), …]."""

    def test_coverage_same_and_max_not_written_skips(self):
        self.assertFalse(cw._cov_needs_write(1.5, [(1.5, 26.8, 0.0)], write_maxqty=False))

    def test_coverage_same_but_max_stale_writes(self):
        # the exact branch-130 situation after the first push: coverage 1.5, max still 0
        self.assertTrue(cw._cov_needs_write(1.5, [(1.5, 26.8, 0.0)], write_maxqty=True))

    def test_coverage_and_max_already_correct_skips(self):
        self.assertFalse(cw._cov_needs_write(1.5, [(1.5, 26.8, 40.2)], write_maxqty=True))

    def test_coverage_changing_writes(self):
        self.assertTrue(cw._cov_needs_write(2.0, [(1.5, 26.8, 40.2)], write_maxqty=False))

    def test_server100_out_of_date_writes(self):
        # branch server done, server 100 still at coverage 0 → write
        self.assertTrue(cw._cov_needs_write(1.5, [(1.5, 26.8, 40.2), (0.0, 15.1, 0.0)],
                                            write_maxqty=True))

    def test_row_absent_on_a_server_writes(self):
        self.assertTrue(cw._cov_needs_write(1.5, [(1.5, 26.8, 40.2), None], write_maxqty=True))

    def test_function_defaults_are_both(self):
        import inspect
        for fn in (cw.build_coverage_plan, cw.push_coverage):
            self.assertEqual(inspect.signature(fn).parameters['target'].default, 'both', fn.__name__)


class ResumeAfterDropTests(TestCase):
    """A branch server dropping the connection mid-push (br140, 2026-09-27) must be
    resumed, and the result must reflect what actually landed in SOFTECH."""

    def _run(self, fake_apply, fake_verify):
        from unittest import mock
        from apps.purchasing import rate_writer as rw   # the resume logic lives there now
        # assertLogs keeps the simulated drop warnings out of the real platform.log
        with mock.patch.object(rw, '_read_conn_for_target', return_value=mock.Mock()), \
             self.assertLogs('elrezeiky.purchasing', level='WARNING'):
            return cw._write_surface_with_resume(None, 'node', ['a', 'b', 'c'],
                                                 write_fn=fake_apply, verify_fn=fake_verify)

    def test_resumes_and_writes_only_the_rest(self):
        written, calls = set(), []

        def fake_apply(conn, codes):
            calls.append(list(codes))
            if len(calls) == 1:
                written.update(['a', 'b'])            # got partway, then the line dropped
                raise RuntimeError('JZ0C0: Connection is already closed')
            written.update(codes)
            return {c: True for c in codes}

        def fake_verify(conn, codes):
            return {c: c in written for c in codes}

        landed, errors = self._run(fake_apply, fake_verify)
        self.assertTrue(all(landed.values()))          # everything confirmed in the end
        self.assertEqual(calls[1], ['c'])              # second attempt wrote only the missing item
        self.assertEqual(len(errors), 1)

    def test_partial_result_reflects_softech_when_it_keeps_failing(self):
        def fake_apply(conn, codes):
            raise RuntimeError('JZ006: IOException')

        def fake_verify(conn, codes):
            return {c: c == 'a' for c in codes}      # only 'a' is really there

        landed, errors = self._run(fake_apply, fake_verify)
        self.assertEqual(landed, {'a': True, 'b': False, 'c': False})
        self.assertEqual(len(errors), cw.MAX_WRITE_ATTEMPTS)


class TopUpTests(TestCase):
    """Auto top-up: fill items with no coverage, refresh stale maxes, never change a
    coverage set on purpose, skip rows absent on a server."""

    def test_groups(self):
        current = {
            'new':   (0.0, 5.0, 0.0),     # no coverage yet            → fill
            'stale': (1.5, 30.0, 40.2),   # rate moved 26.8→30         → refresh (max 45.0)
            'ok':    (1.5, 26.8, 40.2),   # already right              → nothing
            'mine':  (2.0, 10.0, 20.0),   # coverage 2.0 set on purpose, max right → nothing
        }
        fill, refresh, missing = cw._topup_groups(current, ['new', 'stale', 'ok', 'mine', 'gone'], True)
        self.assertEqual(fill, ['new'])
        self.assertEqual(refresh, ['stale'])
        self.assertEqual(missing, ['gone'])

    def test_deliberate_coverage_is_only_max_refreshed_never_reset(self):
        # coverage 2.0 with a stale max → refreshed at ITS 2.0, not pushed back to 1.5
        fill, refresh, _ = cw._topup_groups({'mine': (2.0, 12.0, 20.0)}, ['mine'], True)
        self.assertEqual((fill, refresh), ([], ['mine']))

    def test_no_refresh_when_max_writing_is_off(self):
        fill, refresh, _ = cw._topup_groups({'stale': (1.5, 30.0, 40.2)}, ['stale'], False)
        self.assertEqual((fill, refresh), ([], []))

    @override_settings(COVERAGE_AUTO_TOPUP_ENABLED=False)
    def test_auto_topup_off_by_default(self):
        self.assertFalse(cw.topup_settings()['enabled'])

    def test_topup_due_logic(self):
        from apps.purchasing.models import CoverageTopUp, DemandCalculationRun
        run = DemandCalculationRun.objects.create(status='success')
        self.assertTrue(cw.topup_due(run))                       # never topped up
        CoverageTopUp.objects.create(run=run, status='partial', months=1.5, target='node')
        self.assertTrue(cw.topup_due(run))                       # partial → retry
        CoverageTopUp.objects.create(run=run, status='dry_run', months=1.5, target='node')
        self.assertTrue(cw.topup_due(run))                       # previews don't count
        CoverageTopUp.objects.create(run=run, status='success', months=1.5, target='node')
        self.assertFalse(cw.topup_due(run))                      # done

    def test_topup_gives_up_after_max_partial_tries(self):
        from apps.purchasing.models import CoverageTopUp, DemandCalculationRun
        run = DemandCalculationRun.objects.create(status='success')
        for _ in range(cw.MAX_TOPUP_TRIES_PER_RUN):
            CoverageTopUp.objects.create(run=run, status='partial', months=1.5, target='node')
        self.assertFalse(cw.topup_due(run))


class RealStockOnlyTests(TestCase):
    """Coverage (max-stock ceilings) is written for real stock only — coupons, gifts and
    non-stockable items are skipped, using the same rule as the ISR writer."""

    def test_coupons_gifts_and_non_stockable_are_skipped(self):
        import datetime
        from apps.branches.models import Branch
        from apps.catalog.models import Item
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        from apps.purchasing.rate_writer import _pivot_want
        run = DemandCalculationRun.objects.create(status='success')
        br = Branch.objects.create(softech_branch_id='130', name='ElNozha')
        items = {
            'normal':  Item.objects.create(softech_id='1', name='NORMAL', pack_price=50),
            'coupon':  Item.objects.create(softech_id='118639', name='COUPON', pack_price=-50),
            'zero':    Item.objects.create(softech_id='3', name='FREE', pack_price=0),
            'gift':    Item.objects.create(softech_id='4', name='GIFT', pack_price=10,
                                           medicine_type='60'),
            'service': Item.objects.create(softech_id='5', name='SERVICE', pack_price=10,
                                           is_stockable=False),
        }
        for it in items.values():
            ItemDemandMetrics.objects.create(run=run, item=it, branch=br,
                                             calc_date=datetime.date.today(), monthly_avg=2)
        all_items = _pivot_want(run, [br], None)['130']
        stock = _pivot_want(run, [br], None, stock_only=True)['130']
        self.assertEqual(len(all_items), 5)          # the rate writer still sees everything
        self.assertEqual(set(stock), {'1'})          # coverage: real stock only


class ResetNonStockTests(TestCase):
    """The reset only ever touches rows WE stamped, and confirms both fields are 0."""

    def _conn(self, rows):
        from unittest import mock
        cur = mock.Mock()
        cur.fetchall.return_value = rows
        conn = mock.Mock()
        conn.cursor.return_value = cur
        return conn

    def test_only_rows_stamped_by_us_are_candidates(self):
        conn = self._conn([
            ('118639', 1.5, 109.8, '1509'),   # ours → reset
            ('102230', 1.5, 3.0, ' 1509 '),   # ours (padded char column) → reset
            ('20977', 2.0, 5.0, '77'),        # set natively by someone else → leave alone
            ('92680', 0.0, 0.0, '1509'),      # nothing to undo
        ])
        got = cw._ours_with_ceiling(conn, '130', '130', ['118639', '102230', '20977', '92680'], '1509')
        self.assertEqual(got, ['118639', '102230'])

    def test_verify_requires_both_fields_zero(self):
        conn = self._conn([('a', 0.0, 0.0), ('b', 0.0, 2.0), ('c', 1.5, 0.0)])
        self.assertEqual(cw._verify_reset(conn, '130', '130', ['a', 'b', 'c', 'd']),
                         {'a': True, 'b': False, 'c': False, 'd': False})


class CoverageTopologyTests(TestCase):
    def test_build_plan_rejects_unknown_target(self):
        with self.assertRaises(ValueError):
            cw.build_coverage_plan(coverage_months=1.5, target='mars')

    def test_probe_rejects_both_target(self):
        # 'both' is not a single probe surface; must be node|hq
        with override_settings(COVERAGE_WRITER_ENABLED=True):
            with self.assertRaises(ValueError):
                cw.probe_coverage_write('130', '87602', confirm=True, target='both')
