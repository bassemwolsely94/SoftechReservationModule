"""
Data lifecycle Stage 3: preview, real run, the per-rule circuit breaker, the `lifecycle` command and the
two steps added to the daily retention job (design §6 Stage 3). No SOFTECH involved.

The fake rules select SlowRequest rows, a table with no rule of its own in these tests.
"""
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.data_lifecycle import runner
from apps.data_lifecycle.models import LifecycleRulePolicy, LifecycleRun, LifecycleRunLine
from apps.data_lifecycle.policy import AUDIT_ACTION, has_fresh_preview
from apps.data_lifecycle.references import FileCandidate
from apps.data_lifecycle.register import KIND_FILE, KIND_P56, KIND_ROW, RULES, Rule
from apps.data_lifecycle.runner import breaker_limit, preview_rule, run_lifecycle_rules
from apps.notifications.models import Notification
from apps.sync.maintenance import RETENTION_LOCK_KEY, run_daily_retention
from apps.sync.models import SlowRequest, SyncLog

from .factories import make_admin, make_pharmacist


def _add_rows(n, path='a'):
    SlowRequest.objects.bulk_create([
        SlowRequest(path=path, method='GET', status_code=200, duration_ms=1) for _ in range(n)])


def _rows(path='a'):
    return SlowRequest.objects.filter(path=path)


def _rule(key='fake_a', *, path='a', kind=KIND_ROW, margin=100, ceiling=100_000, candidates=None, apply=None):
    return Rule(key=key, label_ar=key, label_en=key, kind=kind, floor_days=None, default_days=30, reason='test',
                margin=margin, ceiling=ceiling, candidates=candidates or (lambda: [_rows(path)]),
                targets=(), apply=apply)


def _turn_on(*keys):
    for key in keys:
        LifecycleRulePolicy.objects.create(rule_key=key, mode='on', reason='test')


def _only(*rules):
    """Only these rules exist for the length of the `with`."""
    return mock.patch.dict(RULES, {rule.key: rule for rule in rules}, clear=True)


def _last_line(key='fake_a'):
    return LifecycleRunLine.objects.filter(rule_key=key).order_by('-pk').first()


def _breaker_alerts():
    return Notification.objects.filter(notification_type='sync_failure').count()


class PreviewTests(TestCase):
    def test_preview_changes_nothing(self):
        _add_rows(7)
        with _only(_rule()):
            line = preview_rule('fake_a')
        self.assertEqual(_rows().count(), 7)
        self.assertEqual(line.count, 7)
        self.assertTrue(line.is_preview)
        self.assertEqual(line.error, '')
        self.assertTrue(line.run.is_preview)

    def test_preview_counts_as_fresh(self):
        """has_fresh_preview needs a finished run; without it no rule could ever be switched on."""
        with _only(_rule()):
            self.assertFalse(has_fresh_preview('fake_a'))
            line = preview_rule('fake_a')
            self.assertTrue(has_fresh_preview('fake_a'))
        self.assertIsNotNone(line.run.finished_at)

    def test_real_matches_preview_on_unchanged_data(self):
        _add_rows(40)
        _turn_on('fake_a')
        with _only(_rule()):
            previewed = preview_rule('fake_a').count
            removed = run_lifecycle_rules()
        self.assertEqual(removed, previewed)
        self.assertEqual(_last_line().count, previewed)
        self.assertFalse(_last_line().is_preview)
        self.assertEqual(_rows().count(), 0)

    def test_preview_rule_error_is_on_the_line(self):
        with _only(_rule(candidates=mock.Mock(side_effect=RuntimeError('boom')))):
            line = preview_rule('fake_a')
            self.assertFalse(has_fresh_preview('fake_a'))
        self.assertIn('boom', line.error)

    def test_preview_of_p56_or_unknown_rule_is_refused(self):
        for key in ('p56_audit', 'no_such_rule'):
            with self.assertRaises(ValueError, msg=key):
                preview_rule(key)
        self.assertFalse(LifecycleRun.objects.exists())


class ModeTests(TestCase):
    def test_off_rule_does_nothing(self):
        _add_rows(5)
        candidates = mock.Mock(return_value=[_rows()])
        LifecycleRulePolicy.objects.create(rule_key='fake_a', mode='off', reason='test')
        with _only(_rule(candidates=candidates)):
            self.assertEqual(run_lifecycle_rules(), 0)
        candidates.assert_not_called()
        self.assertEqual(_rows().count(), 5)
        self.assertFalse(LifecycleRunLine.objects.exists())

    def test_preview_mode_rule_only_previews(self):
        _add_rows(5)
        with _only(_rule()):      # no policy row: a new rule starts in preview
            self.assertEqual(run_lifecycle_rules(), 0)
            self.assertTrue(has_fresh_preview('fake_a'))   # previews stay fresh day after day
        self.assertEqual(_rows().count(), 5)
        line = _last_line()
        self.assertTrue(line.is_preview)
        self.assertEqual(line.count, 5)
        self.assertFalse(line.run.is_preview)
        self.assertIsNotNone(line.run.finished_at)

    def test_p56_rules_are_listed_but_never_run(self):
        p56 = Rule(key='p56_fake', label_ar='x', label_en='x', kind=KIND_P56, floor_days=None, default_days=1,
                   reason='x', margin=None, ceiling=None, candidates=None, targets=())
        with _only(p56):
            self.assertEqual(run_lifecycle_rules(), 0)
        self.assertFalse(LifecycleRunLine.objects.exists())

    def test_real_run_has_a_finished_run_row(self):
        _turn_on('fake_a')
        with _only(_rule()):
            run_lifecycle_rules()
        run = LifecycleRun.objects.get()
        self.assertFalse(run.is_preview)
        self.assertIsNotNone(run.finished_at)


class BreakerTests(TestCase):
    def setUp(self):
        make_admin('breaker_admin')

    def test_breaker_stops_only_that_rule(self):
        _add_rows(101, 'a')
        _add_rows(100, 'b')
        _turn_on('fake_a', 'fake_b')
        with _only(_rule('fake_a', path='a'), _rule('fake_b', path='b')):
            self.assertEqual(run_lifecycle_rules(), 100)
        line_a, line_b = _last_line('fake_a'), _last_line('fake_b')
        self.assertTrue(line_a.stopped_by_breaker)
        self.assertEqual(line_a.count, 0)
        self.assertEqual(_rows('a').count(), 101)
        self.assertFalse(line_b.stopped_by_breaker)
        self.assertEqual(line_b.count, 100)
        self.assertEqual(_rows('b').count(), 0)
        self.assertEqual(_breaker_alerts(), 1)

    def test_breaker_alert_is_once_a_day_per_rule(self):
        _add_rows(101)
        _turn_on('fake_a')
        with _only(_rule()):
            run_lifecycle_rules()
            run_lifecycle_rules()
        self.assertEqual(_breaker_alerts(), 1)

    def test_preview_is_consumed(self):
        _add_rows(1000)
        _turn_on('fake_a')
        with _only(_rule()):
            preview_rule('fake_a')
            self.assertEqual(run_lifecycle_rules(), 1000)
            self.assertFalse(_last_line().stopped_by_breaker)
            _add_rows(600)
            self.assertEqual(run_lifecycle_rules(), 0)
        self.assertTrue(_last_line().stopped_by_breaker)
        self.assertEqual(_rows().count(), 600)

    def test_first_large_run_allowed_by_preview(self):
        _add_rows(1000)
        _turn_on('fake_a')
        with _only(_rule()):
            preview_rule('fake_a')
            _add_rows(400)
            self.assertEqual(run_lifecycle_rules(), 1400)
        self.assertFalse(_last_line().stopped_by_breaker)

    def test_limit_is_exact(self):
        rule = _rule(margin=100, ceiling=100_000)
        self.assertEqual(breaker_limit(rule), 100)
        run = LifecycleRun.objects.create(is_preview=True)
        LifecycleRunLine.objects.create(run=run, rule_key=rule.key, count=1000, is_preview=True)
        self.assertEqual(breaker_limit(rule), 100, 'an unfinished preview does not count')
        LifecycleRun.objects.update(finished_at=run.started_at)
        self.assertEqual(breaker_limit(rule), 1600)

    def test_ceiling_beats_the_preview(self):
        _add_rows(300)
        _turn_on('fake_a')
        with _only(_rule(margin=100, ceiling=200)):
            preview_rule('fake_a')
            self.assertEqual(run_lifecycle_rules(), 0)
        self.assertTrue(_last_line().stopped_by_breaker)
        self.assertEqual(_rows().count(), 300)

    def test_failed_preview_does_not_raise_the_limit(self):
        run = LifecycleRun.objects.create(is_preview=True)
        LifecycleRun.objects.update(finished_at=run.started_at)
        LifecycleRunLine.objects.create(run=run, rule_key='fake_a', count=1000, is_preview=True, error='boom')
        self.assertEqual(breaker_limit(_rule()), 100)

    def test_stopped_run_consumes_the_preview(self):
        """Once the breaker fired, a person has to look: the next run gets the margin until a new preview."""
        _add_rows(1000)
        _turn_on('fake_a')
        with _only(_rule()):
            preview_rule('fake_a')
            _add_rows(1000)
            run_lifecycle_rules()
            self.assertTrue(_last_line().stopped_by_breaker)
            self.assertEqual(breaker_limit(RULES['fake_a']), 100)
            preview_rule('fake_a')
            self.assertEqual(run_lifecycle_rules(), 2000)

    def test_routine_cleanup_sends_no_notification(self):
        _add_rows(50)
        _turn_on('fake_a')
        with _only(_rule()):
            self.assertEqual(run_lifecycle_rules(), 50)
        self.assertEqual(Notification.objects.count(), 0)


class ApplyTests(TestCase):
    def setUp(self):
        make_admin('apply_admin')

    def test_apply_replaces_the_delete(self):
        _add_rows(5)
        _turn_on('fake_a')
        apply = mock.Mock(return_value=3)
        with _only(_rule(apply=apply)):
            self.assertEqual(run_lifecycle_rules(), 3)
        apply.assert_called_once_with()
        self.assertEqual(_rows().count(), 5)
        self.assertEqual(_last_line().count, 3)

    def test_breaker_counts_candidates_and_never_calls_apply(self):
        _add_rows(101)
        _turn_on('fake_a')
        apply = mock.Mock(return_value=0)
        with _only(_rule(apply=apply)):
            run_lifecycle_rules()
        apply.assert_not_called()
        self.assertTrue(_last_line().stopped_by_breaker)

    def test_preview_never_calls_apply(self):
        apply = mock.Mock(return_value=0)
        with _only(_rule(apply=apply)):
            preview_rule('fake_a')
            run_lifecycle_rules()
        apply.assert_not_called()


class ErrorTests(TestCase):
    def test_rule_error_does_not_stop_others(self):
        _add_rows(5, 'b')
        _turn_on('fake_a', 'fake_b')
        bad = _rule('fake_a', candidates=mock.Mock(side_effect=RuntimeError('boom')))
        with _only(bad, _rule('fake_b', path='b')):
            self.assertEqual(run_lifecycle_rules(), 5)
        self.assertIn('boom', _last_line('fake_a').error)
        self.assertEqual(_last_line('fake_a').count, 0)
        self.assertEqual(_last_line('fake_b').error, '')
        self.assertEqual(_rows('b').count(), 0)

    def test_apply_error_is_on_the_line(self):
        _turn_on('fake_a')
        with _only(_rule(apply=mock.Mock(side_effect=RuntimeError('boom')))):
            self.assertEqual(run_lifecycle_rules(), 0)
        self.assertIn('boom', _last_line().error)

    def test_apply_returning_a_non_integer_is_on_the_line_and_others_run(self):
        """prune_engine_runs returns a dict; a None or dict must not lose the record of what just ran."""
        for value in (None, {'metrics': 3}, True):
            with self.subTest(value=value):
                LifecycleRunLine.objects.all().delete()
                LifecycleRun.objects.all().delete()
                LifecycleRulePolicy.objects.all().delete()
                _add_rows(5, 'b')
                _turn_on('fake_a', 'fake_b')
                with _only(_rule('fake_a', apply=mock.Mock(return_value=value)), _rule('fake_b', path='b')):
                    self.assertEqual(run_lifecycle_rules(), 5)
                line = _last_line('fake_a')
                self.assertIn('integer', line.error)
                self.assertEqual(line.count, 0)
                self.assertEqual(_last_line('fake_b').count, 5)
                self.assertEqual(_rows('b').count(), 0)
                self.assertIsNotNone(LifecycleRun.objects.get().finished_at)

    def test_mode_read_failure_does_not_stop_others(self):
        _add_rows(5, 'b')
        _turn_on('fake_b')
        real_get_mode = runner.get_mode

        def get_mode(key):
            if key == 'fake_a':
                raise RuntimeError('boom')
            return real_get_mode(key)

        with _only(_rule('fake_a'), _rule('fake_b', path='b')), mock.patch.object(runner, 'get_mode', get_mode):
            self.assertEqual(run_lifecycle_rules(), 5)
        self.assertIsNotNone(LifecycleRun.objects.get().finished_at)

    def test_line_save_failure_does_not_stop_others(self):
        _add_rows(5, 'b')
        _turn_on('fake_a', 'fake_b')
        real_save = LifecycleRunLine.save

        def save(line, *args, **kwargs):
            if line.rule_key == 'fake_a':
                raise RuntimeError('boom')
            return real_save(line, *args, **kwargs)

        with _only(_rule('fake_a', apply=mock.Mock(return_value=0)), _rule('fake_b', path='b')), \
                mock.patch.object(LifecycleRunLine, 'save', save):
            self.assertEqual(run_lifecycle_rules(), 5)
        self.assertEqual(_rows('b').count(), 0)
        self.assertIsNotNone(LifecycleRun.objects.get().finished_at)

    def test_error_text_hides_secrets(self):
        _turn_on('fake_a')
        with _only(_rule(candidates=mock.Mock(side_effect=RuntimeError('password=hunter22')))):
            run_lifecycle_rules()
        self.assertNotIn('hunter22', _last_line().error)


class FileRuleTests(TestCase):
    def _file_rule(self, **kwargs):
        files = [FileCandidate('a.bin', [], 10), FileCandidate('b.bin', [], 32)]
        return _rule(kind=KIND_FILE, candidates=lambda: files, **kwargs)

    def test_preview_reports_count_and_bytes(self):
        with _only(self._file_rule()):
            line = preview_rule('fake_a')
        self.assertEqual((line.count, line.bytes), (2, 42))

    @override_settings(LIFECYCLE_FILE_RULES_ENABLED=False)
    def test_stored_on_only_previews_while_locked(self):
        _turn_on('fake_a')
        with _only(self._file_rule()), mock.patch.object(runner, 'move_file_candidates') as move:
            self.assertEqual(run_lifecycle_rules(), 0)
        move.assert_not_called()
        line = _last_line()
        self.assertTrue(line.is_preview)
        self.assertEqual((line.count, line.bytes), (2, 42))

    @override_settings(LIFECYCLE_FILE_RULES_ENABLED=True)
    def test_on_holds_each_candidate(self):
        _turn_on('fake_a')
        with _only(self._file_rule()), mock.patch.object(runner.holding, 'hold_file') as hold:
            self.assertEqual(run_lifecycle_rules(), 2)
        self.assertEqual([call.args for call in hold.call_args_list],
                         [('a.bin', [], 'fake_a'), ('b.bin', [], 'fake_a')])
        line = _last_line()
        self.assertFalse(line.is_preview)
        self.assertEqual((line.count, line.bytes, line.error), (2, 42, ''))

    @override_settings(LIFECYCLE_FILE_RULES_ENABLED=True)
    def test_breaker_counts_files(self):
        make_admin('file_admin')
        _turn_on('fake_a')
        with _only(self._file_rule(margin=1)), mock.patch.object(runner, 'move_file_candidates') as move:
            run_lifecycle_rules()
        move.assert_not_called()
        self.assertTrue(_last_line().stopped_by_breaker)


class RetentionWiringTests(TestCase):
    def test_retention_includes_lifecycle_step(self):
        run = run_daily_retention()
        names = list(SyncLog.objects.filter(sync_run=run).order_by('pk').values_list('table_name', flat=True))
        self.assertEqual(names[-3:], ['retention:lifecycle', 'retention:purge_held', 'retention:data_health'])
        self.assertIn('retention:screen_views', names)
        self.assertEqual(run.status, 'success')

    def test_real_register_is_previewed_and_p56_is_not(self):
        run_daily_retention()
        keys = set(LifecycleRunLine.objects.values_list('rule_key', flat=True))
        self.assertEqual(keys, {key for key, rule in RULES.items() if rule.kind != KIND_P56})
        self.assertFalse(LifecycleRunLine.objects.filter(is_preview=False).exists())

    def test_lifecycle_runs_under_the_retention_lock(self):
        # PG advisory locks are re-entrant within a session, so hold it on a separate raw connection.
        from apps.sync.scheduler_lock import _raw_connection
        conn = _raw_connection()
        self.addCleanup(conn.close)
        with conn.cursor() as cur:
            cur.execute('SELECT pg_advisory_lock(%s)', [RETENTION_LOCK_KEY])
        with mock.patch('apps.data_lifecycle.runner.run_lifecycle_rules') as lifecycle:
            self.assertIsNone(run_daily_retention())
        lifecycle.assert_not_called()

    def test_removed_count_reaches_the_sync_log(self):
        with mock.patch('apps.data_lifecycle.runner.run_lifecycle_rules', return_value=12):
            run = run_daily_retention()
        self.assertEqual(SyncLog.objects.get(sync_run=run, table_name='retention:lifecycle').records_processed, 12)

    def test_failing_lifecycle_step_does_not_stop_the_next_step(self):
        with mock.patch('apps.data_lifecycle.runner.run_lifecycle_rules', side_effect=RuntimeError('x')):
            run = run_daily_retention()
        self.assertEqual(run.status, 'failed')
        self.assertTrue(SyncLog.objects.filter(sync_run=run, table_name='retention:purge_held').exists())

    def test_purge_held_counts_nothing_when_nothing_is_held(self):
        self.assertEqual(runner.purge_held_files(), 0)


class CommandTests(TestCase):
    def setUp(self):
        _, self.admin, _ = make_admin('cmd_admin')

    def _call(self, *args):
        out = StringIO()
        call_command('lifecycle', *args, stdout=out)
        return out.getvalue()

    def test_list_shows_every_rule(self):
        output = self._call('list')
        for key in RULES:
            self.assertIn(key, output)

    def test_preview_writes_a_line(self):
        _add_rows(3)
        with _only(_rule()):
            output = self._call('preview', 'fake_a')
        self.assertIn('3', output)
        self.assertEqual(_rows().count(), 3)
        self.assertTrue(_last_line().is_preview)

    def test_preview_of_unknown_rule_is_a_command_error(self):
        with self.assertRaises(CommandError):
            self._call('preview', 'no_such_rule')

    def test_failed_preview_is_a_command_error(self):
        with _only(_rule(candidates=mock.Mock(side_effect=RuntimeError('boom')))):
            with self.assertRaises(CommandError):
                self._call('preview', 'fake_a')

    def test_set_goes_through_the_service(self):
        self._call('set', 'prescriptions', '--mode', 'off', '--keep-days', '1200',
                   '--user', 'cmd_admin', '--reason', 'طلب المحاسب')
        row = LifecycleRulePolicy.objects.get(rule_key='prescriptions')
        self.assertEqual((row.mode, row.keep_days_override, row.changed_by), ('off', 1200, self.admin))
        log = AuditLog.objects.get(action=AUDIT_ACTION)
        self.assertEqual(log.user, self.admin)
        self.assertEqual(log.new_data, {'mode': 'off', 'keep_days': 1200})

    def test_set_refusal_is_a_command_error(self):
        with self.assertRaises(CommandError):
            self._call('set', 'prescriptions', '--mode', 'off', '--keep-days', '10',
                       '--user', 'cmd_admin', '--reason', 'x')
        self.assertFalse(LifecycleRulePolicy.objects.exists())

    def test_set_needs_an_active_admin(self):
        make_pharmacist('cmd_pharmacist')
        for username in ('cmd_pharmacist', 'nobody'):
            with self.assertRaises(CommandError, msg=username):
                self._call('set', 'prescriptions', '--mode', 'off', '--user', username, '--reason', 'x')
        self.admin.is_active = False
        self.admin.save(update_fields=['is_active'])
        with self.assertRaises(CommandError):
            self._call('set', 'prescriptions', '--mode', 'off', '--user', 'cmd_admin', '--reason', 'x')
        self.assertFalse(LifecycleRulePolicy.objects.exists())


class TableSizeSnapshotTests(TestCase):
    def test_one_row_per_table_over_the_threshold(self):
        from apps.data_lifecycle.models import TableSizeSnapshot
        from apps.data_lifecycle.runner import snapshot_table_sizes
        written = snapshot_table_sizes(min_bytes=0)
        self.assertGreater(written, 0)
        tables = list(TableSizeSnapshot.objects.values_list('table', flat=True))
        self.assertEqual(len(tables), len(set(tables)))
        self.assertEqual(len(tables), written)
        self.assertIn('data_lifecycle_lifecyclerun', tables)
        row = TableSizeSnapshot.objects.get(table='data_lifecycle_lifecyclerun')
        self.assertGreaterEqual(row.total_bytes, row.heap_bytes)
        self.assertGreater(row.total_bytes, 0)

    def test_default_threshold_is_20_mb_so_a_test_database_writes_nothing(self):
        from apps.data_lifecycle.models import TableSizeSnapshot
        from apps.data_lifecycle.runner import TABLE_SIZE_MIN_BYTES, snapshot_table_sizes
        self.assertEqual(TABLE_SIZE_MIN_BYTES, 20 * 1024 * 1024)
        self.assertEqual(snapshot_table_sizes(), 0)
        self.assertFalse(TableSizeSnapshot.objects.exists())

    def test_the_step_never_raises(self):
        from apps.data_lifecycle.runner import snapshot_table_sizes
        with mock.patch('apps.data_lifecycle.runner.connection') as conn:
            conn.cursor.side_effect = RuntimeError('db gone')
            self.assertEqual(snapshot_table_sizes(), 0)

    def test_retention_runs_the_snapshot_step(self):
        run = run_daily_retention()
        self.assertTrue(SyncLog.objects.filter(sync_run=run, table_name='retention:table_sizes').exists())
