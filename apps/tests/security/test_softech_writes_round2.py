"""
Round-2 R1 (docs/security/round2/R1_write_sites.md): idempotency guards for the two SOFTECH write
sites the manifest recorded with none — owner approved 2026-11-05 (decision pack Q2).

- apply_classification_changes: advisory lock 7_301_011 (one run at a time) + an item already at
  its target class in SOFTECH is skipped — no UPDATE, so a repeat click no longer re-stamps
  itemlastupdate and re-triggers replication to every branch.
- force_replication: advisory lock 7_301_012 + a second repair of the same item within 10 minutes
  is refused; every repair (admin action, command or scheduled job) leaves an AuditLog row
  `softech_replication_forced` — which also closes decision D4 (it used to log only).
"""
from unittest import mock

from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.tests.factories import make_user


class _ItemsCursor:
    """A stand-in SOFTECH `items` table: SELECT returns the current class, UPDATE changes it."""

    def __init__(self, current):
        self.current, self.updates, self._last = dict(current), 0, None

    def execute(self, sql, params=None):
        s = sql.strip().upper()
        if s.startswith('UPDATE'):
            self.updates += 1
            cols = [c.split('=')[0].strip().lower() for c in sql.split(' SET ', 1)[1].split(', usercode')[0].split(',')]
            for col, val in zip(cols, params):
                self.current[col] = val
        elif s.startswith('SELECT'):
            wanted = [c.strip().lower() for c in sql.split('SELECT', 1)[1].split('FROM')[0].split(',')]
            self._last = tuple(self.current.get(c) for c in wanted)

    def fetchone(self):
        return self._last

    def close(self):
        pass


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self):
        return self.cur

    def close(self):
        pass


@override_settings(PRICING_SOFTECH_WRITE_ENABLED=True)
class ClassificationIdempotencyTests(TestCase):
    def setUp(self):
        from apps.catalog.models import Item
        self.user = make_user('r1_admin', role='admin')[0]
        self.item = Item.objects.create(softech_id='91011', name='X', origin_code='3', store_classif='1')

    def _apply(self, cur):
        from apps.discount_approvals import alignment
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn(cur)):
            return alignment.apply_classification_changes(
                [{'item_id': self.item.id, 'origin_code': '9'}], '19', actor=self.user)

    def test_second_apply_writes_nothing(self):
        cur = _ItemsCursor({'itemorigincode': '3'})
        err, res = self._apply(cur)
        self.assertIsNone(err)
        self.assertEqual(cur.updates, 1)
        self.assertTrue(res[0]['ok'])
        audits = AuditLog.objects.filter(action='softech_item_class_written').count()

        err, res = self._apply(cur)                 # same plan again (double click / retry)
        self.assertIsNone(err)
        self.assertEqual(cur.updates, 1, 'second apply re-wrote an item already at its target')
        self.assertTrue(res[0]['ok'])
        self.assertTrue(res[0].get('unchanged'))
        self.assertEqual(AuditLog.objects.filter(action='softech_item_class_written').count(), audits)

    def test_item_already_right_in_softech_still_fixes_our_copy(self):
        # SOFTECH already holds '9' but our copy still says '3': no SOFTECH write, copy corrected
        cur = _ItemsCursor({'itemorigincode': '9'})
        err, res = self._apply(cur)
        self.assertIsNone(err)
        self.assertEqual(cur.updates, 0)
        self.assertTrue(res[0].get('unchanged'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.origin_code, '9')

    def test_refuses_while_another_run_holds_the_lock(self):
        from apps.vouchers.coupon_dashboard import pg_lock
        from apps.discount_approvals.alignment import LOCK_CLASSIFICATION
        self.assertEqual(LOCK_CLASSIFICATION, 7_301_011)
        conn = mock.Mock()
        with mock.patch.object(pg_lock, '__enter__', return_value=False), \
                mock.patch('config.sybase.get_sybase_connection', return_value=conn) as connect:
            from apps.discount_approvals import alignment
            err, res = alignment.apply_classification_changes(
                [{'item_id': self.item.id, 'origin_code': '9'}], '19', actor=self.user)
        self.assertTrue(err)
        self.assertEqual(res, [])
        connect.assert_not_called()


class _MotalbaCursor:
    """motalba rows for one receipt: the SELECT returns their dates, the UPDATE is recorded."""

    def __init__(self, rows):
        self.rows, self.sql, self.rowcount = rows, [], len(rows)

    def execute(self, sql, params=None):
        self.sql.append(sql.strip().split()[0].upper())

    def fetchall(self):
        return self.rows


class MotalbaOldDateTests(TestCase):
    """Q1 (owner 2026-11-05): a receipt-date change keeps the motalba rows' old dates, read
    before the UPDATE, so the change is fully audited and could be restored."""

    def test_old_motalba_dates_are_read_before_the_update(self):
        import datetime
        from apps.insurance import date_service as ds
        cur = _MotalbaCursor([(9001, datetime.datetime(2026, 10, 20)), (9002, datetime.datetime(2026, 10, 21))])
        rows, old = ds._set_motalba_docdate(cur, '55', '130', '115', '20261014')
        self.assertEqual(cur.sql, ['SELECT', 'UPDATE'], 'old dates must be read before they are overwritten')
        self.assertEqual(rows, 2)
        self.assertEqual(old, [{'motalbano': '9001', 'docdate': '2026-10-20'},
                               {'motalbano': '9002', 'docdate': '2026-10-21'}])

    def test_apply_stores_the_old_motalba_dates_on_the_run(self):
        import datetime
        from apps.insurance import date_service as ds
        from apps.insurance.models import SoftechDateEditRun as D
        conn = mock.MagicMock()
        old = [{'motalbano': '9001', 'docdate': '2026-10-20'}]
        with mock.patch.object(ds, '_hq_conn', return_value=conn), \
                mock.patch.object(ds, '_open_branch', return_value=conn), \
                mock.patch.object(ds, '_read_docdate', return_value=datetime.date(2026, 10, 20)), \
                mock.patch.object(ds, '_date_issues', return_value=[]), \
                mock.patch.object(ds, '_set_docdate'), \
                mock.patch.object(ds, '_set_motalba_docdate', return_value=(1, old)):
            out = ds._apply_locked(None, '55', '130', datetime.date(2026, 10, 14), None, '115')
        run = D.objects.get(pk=out['run_id'])
        self.assertEqual(run.motalba_old_dates, old)


class _RecCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((' '.join(sql.split()), list(params or [])))

    def close(self):
        pass


@override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True)
class MotalbaRevertTests(TestCase):
    """Q1 follow-up (owner 2026-11-05): reverting a receipt-date change also puts each motalba row
    back to its recorded old date — one UPDATE per motalbano, in the same transaction as the
    receipt. A run from before the old dates were kept leaves the motalba as it is."""

    def _run(self, old_dates):
        import datetime
        from apps.insurance.models import SoftechDateEditRun as D
        return D.objects.create(docnumber='55', branchcode='130', doccode='115',
                                old_date=datetime.date(2026, 10, 20), new_date=datetime.date(2026, 10, 14),
                                nodes=['HQ', '130'], status=D.STATUS_APPLIED, motalba_old_dates=old_dates)

    def _revert(self, run):
        from apps.insurance import date_service as ds
        hcur, bcur = _RecCursor(), _RecCursor()
        hq, br = mock.MagicMock(), mock.MagicMock()
        hq.cursor.return_value, br.cursor.return_value = hcur, bcur
        with mock.patch.object(ds, '_hq_conn', return_value=hq), \
                mock.patch.object(ds, '_open_branch', return_value=br):
            out = ds._revert_locked(run)
        return out, hcur

    def test_revert_restores_each_motalba_row(self):
        run = self._run([{'motalbano': '9001', 'docdate': '2026-10-20'},
                         {'motalbano': '9002', 'docdate': '2026-10-19'}])
        out, hcur = self._revert(run)
        motalba = [(s, p) for s, p in hcur.calls if 'motalba' in s]
        self.assertEqual(len(motalba), 2)
        self.assertTrue(all('motalbano=' in s.replace(' ', '') for s, _ in motalba))
        self.assertEqual([p[0] for _, p in motalba], ['20261020', '20261019'])
        self.assertEqual(out['motalba_restored'], 2)
        run.refresh_from_db()
        self.assertEqual(run.status, run.STATUS_REVERTED)

    def test_old_run_without_recorded_dates_leaves_motalba(self):
        out, hcur = self._revert(self._run(None))
        self.assertFalse([s for s, _ in hcur.calls if 'motalba' in s])
        self.assertEqual(out['motalba_restored'], 0)


class CommandActorTests(TestCase):
    """D2 (owner 2026-11-05): the A/P writer commands record who wrote — a live run needs
    --actor naming an active staff user; a dry run writes nothing and needs none."""

    def test_dry_run_needs_no_actor(self):
        from apps.finance.recon_writer import command_actor
        self.assertIsNone(command_actor('', commit=False))

    def test_live_run_without_actor_is_refused(self):
        from django.core.management.base import CommandError
        from apps.finance.recon_writer import command_actor
        with self.assertRaises(CommandError):
            command_actor('', commit=True)
        with self.assertRaises(CommandError):
            command_actor('nobody_here', commit=True)

    def test_live_run_resolves_the_staff_profile(self):
        from apps.finance.recon_writer import command_actor
        user, profile, _ = make_user('ap_writer', role='admin')
        self.assertEqual(command_actor('ap_writer', commit=True), profile)
        profile.is_active = False
        profile.save(update_fields=['is_active'])
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            command_actor('ap_writer', commit=True)

    def test_every_ap_writer_command_takes_actor(self):
        from django.core.management import load_command_class
        for name in ('push_ap_allocation', 'push_ap_allocations_bulk', 'fix_ap_due_before'):
            parser = load_command_class('apps.finance', name).create_parser('manage.py', name)
            self.assertIn('--actor', parser.format_help(), name)


class ProbeWriterGateTests(TestCase):
    """D1 (owner 2026-11-05): SOFTECH probes (rehearsals / diagnostics that run real DML) need
    SOFTECH_PROBES_ENABLED and either the writer copy, or a read-only copy (where SOFTECH refuses
    the DML anyway). A reader with read-only switched off can no longer reach them."""

    def _calls(self):
        from django.core.management.base import CommandError
        from core.softech_switches import SoftechProbesDisabled, command_require_probes, require_probes
        out = []
        for fn, exc in ((require_probes, SoftechProbesDisabled), (command_require_probes, CommandError)):
            try:
                fn('probe_x')
                out.append('allowed')
            except exc:
                out.append('refused')
        return out

    @override_settings(SOFTECH_PROBES_ENABLED=True, WRITER_INSTANCE=False, SOFTECH_READ_ONLY=False)
    def test_reader_with_read_only_off_is_refused(self):
        self.assertEqual(self._calls(), ['refused', 'refused'])

    @override_settings(SOFTECH_PROBES_ENABLED=True, WRITER_INSTANCE=True, SOFTECH_READ_ONLY=False)
    def test_writer_is_allowed(self):
        self.assertEqual(self._calls(), ['allowed', 'allowed'])

    @override_settings(SOFTECH_PROBES_ENABLED=True, WRITER_INSTANCE=False, SOFTECH_READ_ONLY=True)
    def test_read_only_reader_is_allowed(self):
        self.assertEqual(self._calls(), ['allowed', 'allowed'])

    @override_settings(SOFTECH_PROBES_ENABLED=False, WRITER_INSTANCE=True, SOFTECH_READ_ONLY=False)
    def test_switch_off_still_refuses_on_the_writer(self):
        self.assertEqual(self._calls(), ['refused', 'refused'])


class _HQCursor:
    """HQ items row for force_replication: SELECT returns one row, UPDATEs are counted."""

    def __init__(self):
        from apps.discount_approvals.replication import PRICE_COLS
        self.row = (None, '15') + tuple(10.0 for _ in PRICE_COLS)
        self.updates = 0

    def execute(self, sql, params=None):
        if sql.strip().upper().startswith('UPDATE'):
            self.updates += 1

    def fetchone(self):
        return self.row


@override_settings(REPLICATION_REPAIR_ENABLED=True)
class ForceReplicationIdempotencyTests(TestCase):
    def setUp(self):
        self.user = make_user('r1_repl_admin', role='admin')[0]

    def _repair(self, cur, **kw):
        from apps.discount_approvals.replication import force_replication
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn(cur)):
            return force_replication('91012', mode='restamp', **kw)

    def test_repeat_within_10_minutes_is_refused_and_each_repair_is_audited(self):
        cur = _HQCursor()
        out = self._repair(cur, actor=self.user)
        self.assertTrue(out['restamped'])
        self.assertEqual(cur.updates, 1)
        row = AuditLog.objects.filter(action='softech_replication_forced').order_by('-id').first()
        self.assertIsNotNone(row, 'a SOFTECH re-stamp left no audit row')
        self.assertEqual((row.extra or {}).get('softech_id'), '91012')

        out = self._repair(cur, actor=self.user)              # double click / job + admin
        self.assertEqual(out.get('error'), 'repaired_recently')
        self.assertEqual(cur.updates, 1, 'second repair within 10 minutes re-stamped SOFTECH')

    def test_repair_allowed_again_after_10_minutes(self):
        import datetime
        from django.utils import timezone
        cur = _HQCursor()
        self._repair(cur)
        AuditLog.objects.filter(action='softech_replication_forced').update(
            created_at=timezone.now() - datetime.timedelta(minutes=11))
        out = self._repair(cur)
        self.assertTrue(out['restamped'])
        self.assertEqual(cur.updates, 2)

    def test_refuses_while_another_repair_holds_the_lock(self):
        from apps.vouchers.coupon_dashboard import pg_lock
        from apps.discount_approvals.replication import LOCK_REPLICATION
        self.assertEqual(LOCK_REPLICATION, 7_301_012)
        with mock.patch.object(pg_lock, '__enter__', return_value=False), \
                mock.patch('config.sybase.get_sybase_connection') as connect:
            from apps.discount_approvals.replication import force_replication
            out = force_replication('91012', mode='restamp')
        self.assertEqual(out.get('error'), 'busy')
        connect.assert_not_called()
