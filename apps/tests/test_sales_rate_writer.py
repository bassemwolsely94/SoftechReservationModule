"""
Tests for the Feature-1 sales-rate writeback (apps/purchasing/rate_writer.py).

Covers the pure logic (rounding, store resolution) and the audit-spine
persistence (SalesRatePush + lines) WITHOUT any SOFTECH connection — build_plan /
push live-write paths hit Sybase and are exercised via the gated dry-run in ops.
"""
from types import SimpleNamespace

from django.test import TestCase, override_settings

from apps.purchasing import rate_writer
from apps.purchasing.models import SalesRatePush, SalesRatePushLine


def _make_push(status, eligible=True):
    p = SalesRatePush.objects.create(status=status, eligible_count=1 if eligible else 0)
    SalesRatePushLine.objects.create(
        push=p, itemcode='87602', item_name='ABILIFY', branchcode='130',
        storecode='130', old_rate=0.0, new_rate=0.9, eligible=eligible)
    return p


class RoundingAndStoreTests(TestCase):
    def test_round_to_rate_decimals(self):
        self.assertEqual(rate_writer._round(0.8667), 0.9)   # RATE_DECIMALS = 1 (native precision)
        self.assertEqual(rate_writer._round(2.14), 2.1)
        self.assertEqual(rate_writer._round(0), 0.0)
        self.assertEqual(rate_writer._round(None), 0.0)

    def test_resolve_store_defaults_to_branchcode(self):
        b = SimpleNamespace(softech_branch_id='130')
        self.assertEqual(rate_writer.resolve_store(b), '130')

    @override_settings(SALES_RATE_STORE_MAP={'130': '131'})
    def test_resolve_store_honours_override_map(self):
        b = SimpleNamespace(softech_branch_id='130')
        self.assertEqual(rate_writer.resolve_store(b), '131')


def _plan(mode=None):
    """A minimal plan dict shaped exactly like build_plan()'s output."""
    changes = [
        {'itemcode': '87602', 'item_name': 'ABILIFY 10MG', 'old': 0.0, 'new': 0.867,
         'delta': 0.867, 'eligible': True, 'reason': ''},
        {'itemcode': '999', 'item_name': 'BLOCKED', 'old': 1.0, 'new': 1.0,
         'delta': None, 'eligible': False, 'reason': 'itemupdt_monthlyqty!=1'},
    ]
    if mode == 'commit':
        changes[0]['verified'] = True
    branch = {'branchcode': '130', 'name': 'ElNozha', 'store': '130', 'host': 'h',
              'reachable': True, 'changes': changes, 'eligible_count': 1, 'skipped_count': 1}
    if mode == 'commit':
        branch.update(written=1, verified=1, reverted=0)
    plan = {'run_id': None, 'calc_date': '2026-09-09', 'branches': [branch],
            'totals': {'branches': 1, 'eligible': 1, 'skipped': 1, 'unreachable': 0}}
    if mode:
        plan['mode'] = mode
    return plan


class RateMethodTests(TestCase):
    def test_make_adv_config_whitelists_params(self):
        cfg = rate_writer._make_adv_config(
            {'trend_months': 4, 'bulk_cap_factor': 2.0,
             'cash_budget': 99999, 'nonsense': 'x'})   # last two must be ignored
        self.assertEqual(cfg.trend_months, 4)
        self.assertEqual(cfg.bulk_cap_factor, 2.0)
        self.assertEqual(cfg.cash_budget, 0.0)          # default preserved (not whitelisted)
        self.assertFalse(hasattr(cfg, 'nonsense'))

    def test_make_adv_config_empty_uses_defaults(self):
        from apps.purchasing.advanced_engine import AdvancedConfig
        cfg = rate_writer._make_adv_config(None)
        self.assertEqual(cfg.trend_months, AdvancedConfig().trend_months)

    def test_build_plan_rejects_unknown_method(self):
        with self.assertRaises(ValueError):
            rate_writer.build_plan(method='telepathy')

    def test_persist_plan_stamps_method_and_params(self):
        plan = _plan()
        plan['method'] = 'advanced'
        plan['method_params'] = {'trend_months': 6}
        push = rate_writer.persist_plan(plan)
        self.assertEqual(push.method, SalesRatePush.METHOD_ADVANCED)
        self.assertEqual(push.method_params, {'trend_months': 6})

    def test_persist_plan_defaults_method_to_pivot(self):
        push = rate_writer.persist_plan(_plan())   # no 'method' key
        self.assertEqual(push.method, SalesRatePush.METHOD_PIVOT)
        self.assertEqual(push.method_params, {})


class WriteTopologyTests(TestCase):
    """Batch 3 — target = node | hq | both; default BOTH (owner, 2026-09-27)."""

    def test_default_target_is_both(self):
        push = rate_writer.persist_plan(_plan())
        self.assertEqual(push.target, SalesRatePush.TARGET_BOTH)

    def test_function_defaults_are_both(self):
        import inspect
        for fn in (rate_writer.build_plan, rate_writer.push):
            self.assertEqual(inspect.signature(fn).parameters['target'].default,
                             rate_writer.TARGET_BOTH, fn.__name__)

    def test_needs_write_when_either_server_differs(self):
        # branch server already correct (26.8) but server 100 stale (15.1) → write
        self.assertTrue(rate_writer._needs_write(26.8, [26.8, 15.1], 0.0005))
        self.assertTrue(rate_writer._needs_write(26.8, [15.1, 26.8], 0.0005))
        # both already correct → skip
        self.assertFalse(rate_writer._needs_write(26.8, [26.8, 26.8], 0.0005))
        # single-server target behaves as before
        self.assertFalse(rate_writer._needs_write(26.8, [26.8], 0.0005))
        # a row absent on a server (None → 0) needs a write
        self.assertTrue(rate_writer._needs_write(26.8, [26.8, None], 0.0005))

    def test_persist_plan_records_server100_before_value(self):
        plan = _plan()
        plan['target'] = 'both'
        plan['branches'][0]['changes'][0]['old_hq'] = 15.1
        push = rate_writer.persist_plan(plan)
        line = push.lines.get(itemcode='87602')
        self.assertEqual(float(line.old_rate_hq), 15.1)

    def test_build_plan_rejects_unknown_target(self):
        with self.assertRaises(ValueError):
            rate_writer.build_plan(target='mars')

    def test_persist_plan_stamps_target(self):
        plan = _plan()
        plan['target'] = 'both'
        push = rate_writer.persist_plan(plan)
        self.assertEqual(push.target, SalesRatePush.TARGET_BOTH)

    def test_write_surfaces_count_per_target(self):
        # patch the two connection factories so no real SOFTECH is touched
        import apps.purchasing.rate_writer as rw
        from types import SimpleNamespace
        import config.sybase as sb
        calls = {'branch': 0, 'hq': 0}
        orig_b, orig_h = sb.get_branch_connection, sb.get_sybase_connection
        sb.get_branch_connection = lambda *a, **k: (calls.__setitem__('branch', calls['branch'] + 1) or SimpleNamespace(close=lambda: None))
        sb.get_sybase_connection = lambda *a, **k: (calls.__setitem__('hq', calls['hq'] + 1) or SimpleNamespace(close=lambda: None))
        try:
            branch = SimpleNamespace(effective_db_host='h', effective_db_port=5000, db_name='D')
            self.assertEqual(len(rw._write_conns_for_target(branch, rw.TARGET_NODE)), 1)
            self.assertEqual(len(rw._write_conns_for_target(branch, rw.TARGET_HQ)), 1)
            self.assertEqual(len(rw._write_conns_for_target(branch, rw.TARGET_BOTH)), 2)
        finally:
            sb.get_branch_connection, sb.get_sybase_connection = orig_b, orig_h


class RateResumeBothServersTests(TestCase):
    """Option (a): rates go to the branch server AND server 100. A dropped connection is
    resumed; a line is confirmed only when it landed on BOTH servers."""

    def _run(self, fail_hq_times):
        from unittest import mock
        written = {'node': set(), 'hq': set()}
        calls = {'hq': 0}

        def conn_for(branch, label):
            return mock.Mock(label=label)

        def fake_apply(conn, bc, st, items, uc):
            codes = [c for c, _ in items]
            if conn.label == 'hq':
                calls['hq'] += 1
                if calls['hq'] <= fail_hq_times:
                    if calls['hq'] == 1:
                        written['hq'].update(codes[:1])  # first try: one row in, then dropped
                    raise RuntimeError('JZ0C0: Connection is already closed')
            written[conn.label].update(codes)
            return {c: True for c in codes}

        def fake_verify(conn, bc, st, intended):
            return {c: c in written[conn.label] for c in intended}

        # assertLogs keeps the simulated drop warnings out of the real platform.log
        with mock.patch.object(rate_writer, '_read_conn_for_target', side_effect=conn_for), \
             mock.patch.object(rate_writer, '_apply_rate_updates', side_effect=fake_apply), \
             mock.patch.object(rate_writer, '_verify_rates', side_effect=fake_verify), \
             self.assertLogs('elrezeiky.purchasing', level='WARNING'):
            return rate_writer._write_all_surfaces(None, 'both', '130', '130',
                                                   {'a': 1.0, 'b': 2.0, 'c': 3.0}, '1509')

    def test_server100_drop_is_resumed(self):
        ok, errors = self._run(fail_hq_times=1)
        self.assertEqual(ok, {'a': True, 'b': True, 'c': True})
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith('[hq]'))

    def test_line_not_confirmed_unless_on_both_servers(self):
        ok, errors = self._run(fail_hq_times=99)          # server 100 never recovers
        self.assertEqual(ok, {'a': True, 'b': False, 'c': False})   # only 'a' reached server 100
        self.assertEqual(len(errors), rate_writer.MAX_WRITE_ATTEMPTS)


class MaxQtyRefreshTests(TestCase):
    """Fix 3 — maxnowqty kept in step with rate × coverage (SOFTECH doesn't recompute it)."""

    def test_expected_maxqty(self):
        self.assertEqual(rate_writer._expected_maxqty(26.8, 1.5), 40.2)
        self.assertEqual(rate_writer._expected_maxqty(390.7, 1.5), 586.1)   # half-up
        self.assertEqual(rate_writer._expected_maxqty(0, 1.5), 0.0)         # no rate → no limit
        self.assertEqual(rate_writer._expected_maxqty(-3, 1.5), 0.0)        # net returns → no limit
        self.assertEqual(rate_writer._expected_maxqty(26.8, 0), 0.0)        # no coverage → 0

    def test_expected_maxqty_never_below_one_pack_for_selling_items(self):
        # owner rule 2026-09-28: 1 pen/month × 1.5 = 0.2 → 1 pack, not 0.2
        self.assertEqual(rate_writer._expected_maxqty(0.1, 1.5), 1.0)
        self.assertEqual(rate_writer._expected_maxqty(0.3, 1.5), 1.0)   # 0.45 → 0.5 → floor 1
        self.assertEqual(rate_writer._expected_maxqty(0.67, 1.5), 1.0)  # 1.005 → 1.0
        self.assertEqual(rate_writer._expected_maxqty(0.7, 1.5), 1.1)   # above the floor, unchanged
        self.assertEqual(rate_writer._expected_maxqty(0, 1.5), 0.0)     # no sales → still 0 (no limit)

    def test_expected_maxqty_exact_halves_match_softech(self):
        # real br130 rows SOFTECH stored correctly but a float product misjudged
        self.assertEqual(rate_writer._expected_maxqty(0.7, 1.5), 1.1)   # 1.05 → 1.1
        self.assertEqual(rate_writer._expected_maxqty(6.1, 1.5), 9.2)   # 9.15 → 9.2
        self.assertEqual(rate_writer._expected_maxqty(4.3, 1.5), 6.5)   # 6.45 → 6.5

    @override_settings(COVERAGE_WRITE_MAXQTY=False)
    def test_refresh_off_when_setting_off(self):
        self.assertFalse(rate_writer._refresh_maxqty())

    @override_settings(COVERAGE_WRITE_MAXQTY=True)
    def test_refresh_follows_setting(self):
        self.assertTrue(rate_writer._refresh_maxqty())

    def test_refresh_sql_only_touches_rows_with_coverage(self):
        sql = rate_writer._refresh_maxqty_sql("'130'", "'130'", "'1509'", ['6741', '80611'])
        self.assertIn('maxnowqtymonths > 0', sql)                     # rows without coverage untouched
        self.assertIn('CASE WHEN monthlyqty > 0', sql)                # rate ≤ 0 → 0 (no limit)
        self.assertIn('round(monthlyqty * maxnowqtymonths, 1)', sql)  # each row's OWN rate × coverage
        self.assertIn('< 1.0 THEN 1.0', sql)                          # never below one pack
        self.assertIn("itemcode IN ('6741','80611')", sql)
        self.assertIn("branchcode='130'", sql)
        self.assertIn('usercode_xq', sql)


class PersistPlanTests(TestCase):
    def test_dry_run_persists_as_proposed(self):
        push = rate_writer.persist_plan(_plan(), scope={'branch_filter': ['130']})
        self.assertEqual(push.status, SalesRatePush.STATUS_PROPOSED)
        self.assertIsNone(push.executed_at)
        self.assertEqual(push.eligible_count, 1)
        self.assertEqual(push.skipped_count, 1)
        self.assertEqual(push.lines.count(), 2)
        # eligible line carries the before→after; blocked line records the reason
        elig = push.lines.get(itemcode='87602')
        self.assertTrue(elig.eligible)
        self.assertEqual(float(elig.old_rate), 0.0)
        self.assertEqual(float(elig.new_rate), 0.867)
        self.assertFalse(elig.written)          # nothing written on a proposal
        blocked = push.lines.get(itemcode='999')
        self.assertFalse(blocked.eligible)
        self.assertIn('itemupdt', blocked.reason)

    def test_commit_persists_as_executed_with_verified(self):
        push = rate_writer.persist_plan(_plan('commit'))
        self.assertEqual(push.status, SalesRatePush.STATUS_EXECUTED)
        self.assertIsNotNone(push.executed_at)
        self.assertEqual(push.written_count, 1)
        self.assertEqual(push.verified_count, 1)
        elig = push.lines.get(itemcode='87602')
        self.assertTrue(elig.written)
        self.assertTrue(elig.verified)


class WriterGateTests(TestCase):
    @override_settings(SALES_RATE_WRITER_ENABLED=False)
    def test_gate_off_by_default(self):
        self.assertFalse(rate_writer.writer_enabled())

    def test_probe_write_requires_confirm(self):
        with self.assertRaises(ValueError):
            rate_writer.probe_write('130', '87602', confirm=False)


class ExecutePushGuardTests(TestCase):
    """Gate + status are checked BEFORE any SOFTECH connection, so these run offline."""

    @override_settings(SALES_RATE_WRITER_ENABLED=False)
    def test_execute_refused_when_gate_off(self):
        p = _make_push(SalesRatePush.STATUS_APPROVED)
        with self.assertRaises(rate_writer.WriterDisabled):
            rate_writer.execute_push(p)
        p.refresh_from_db()
        self.assertEqual(p.status, SalesRatePush.STATUS_APPROVED)   # unchanged

    @override_settings(SALES_RATE_WRITER_ENABLED=True)
    def test_execute_refused_when_not_approved(self):
        p = _make_push(SalesRatePush.STATUS_PROPOSED)
        with self.assertRaises(ValueError):
            rate_writer.execute_push(p)
        p.refresh_from_db()
        self.assertEqual(p.status, SalesRatePush.STATUS_PROPOSED)   # unchanged
