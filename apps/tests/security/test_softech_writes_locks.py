"""
SOFTECH write safety — missing locks / idempotency on real writes (Batch 2, P-15).

  * ISR push (push_isr_record): APPROVED was checked on the caller's in-memory copy — two
    clicks (or a click + auto_generate) both wrote an ISR. `push_isr --commit` wrote ISRs with
    no IsrPush record, no duplicate guard and no audit.
  * Insurance re-price rebalance: run.rebalanced checked in memory, no lock → two requests both
    shift every later personnewbal; SOFTECH committed BEFORE the PG record, so a failed save
    left the shift unrecorded and a retry shifted again.
  * Insurance date edit: a second apply on the same receipt recorded the already-changed date
    as old_date — its revert restores the wrong date.
  * Points removal: two concurrent runs both read the balance and both debit it.
  * Offers channel B: every click INSERTed a new SOFTECH offer (cashier applies both); the
    INSERTs ran in autocommit, so a failure half-way left half an offer.

A lock "held elsewhere" is held from a SECOND real PostgreSQL session (advisory locks are
re-entrant inside one session — exactly what another worker process looks like).
"""
import io
from contextlib import contextmanager
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings



@contextmanager
def _held_elsewhere(key):
    from django.db import connections
    other = connections.create_connection('default')
    try:
        with other.cursor() as c:
            c.execute('SELECT pg_advisory_lock(%s)', [key])
        yield
    finally:
        with other.cursor() as c:
            c.execute('SELECT pg_advisory_unlock_all()')
        other.close()


def _branch(code):
    from apps.branches.models import Branch
    return Branch.objects.get_or_create(softech_branch_id=code, defaults={
        'name': code, 'name_ar': code, 'is_active': True, 'db_host': f'10.0.0.{code}'})[0]


# ── ISR ───────────────────────────────────────────────────────────────────────

@override_settings(ISR_WRITER_ENABLED=True)
class IsrPushTests(TestCase):

    def setUp(self):
        from apps.purchasing import isr_writer as W
        from apps.purchasing.models import IsrPush as P
        from apps.tests.test_isr_guards import _lines
        self.W, self.P = W, P
        _branch('100'), _branch('160')
        p = W._persist_proposal(source='100', dest='160', kind=P.KIND_HQ_TO_BRANCH, lines=_lines(('A', 2)))
        P.objects.filter(pk=p.pk).update(status=P.STATUS_APPROVED)
        self.p = P.objects.get(pk=p.pk)

    def test_stale_approved_copy_is_not_pushed_again(self):
        stale = self.P.objects.get(pk=self.p.pk)               # loaded before the other push finished
        self.P.objects.filter(pk=self.p.pk).update(status=self.P.STATUS_PUSHED)
        with mock.patch('config.sybase.get_branch_connection') as conn:
            with self.assertRaises(ValueError):
                self.W.push_isr_record(stale)
        conn.assert_not_called()

    def test_refused_while_another_push_of_it_runs(self):
        with _held_elsewhere(self.W.LOCK_ISR_PUSH * 1_000_000 + self.p.pk), \
                mock.patch('config.sybase.get_branch_connection') as conn:
            with self.assertRaises(ValueError):
                self.W.push_isr_record(self.p)
        conn.assert_not_called()

    def test_push_isr_command_commit_writes_nothing_unrecorded(self):
        from apps.tests.test_isr_guards import _lines
        plan = {'lines': _lines(('A', 2)), 'line_count': 1, 'run_id': 1, 'prefix': '2616'}
        raised = None
        with mock.patch('config.sybase.get_branch_connection') as conn, \
                mock.patch.object(self.W, 'build_plan', return_value=plan):
            try:
                call_command('push_isr', branch='160', commit=True, stdout=io.StringIO())
            except Exception as exc:          # the old path dies inside the (fake) write
                raised = exc
        conn.assert_not_called()
        self.assertIsInstance(raised, CommandError)


# ── insurance ─────────────────────────────────────────────────────────────────

class _Hq:
    """Fake HQ connection; on commit, notes what PostgreSQL already holds."""

    def __init__(self, on_commit=None, rows=()):
        self.on_commit, self.rows, self.log = on_commit, list(rows), []

    def cursor(self):
        hq = self

        class C:
            def execute(self, sql, params=None, timeout=None):
                hq.log.append(sql.split()[0].upper())

            def fetchall(self):
                return hq.rows

            def fetchone(self):
                return None

            def close(self):
                pass
        return C()

    def begin(self):
        self.log.append('begin')

    def commit(self):
        self.log.append('commit')
        if self.on_commit:
            self.on_commit()

    def rollback(self):
        self.log.append('rollback')

    def close(self):
        pass


@override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True)
class RebalanceTests(TestCase):

    def setUp(self):
        from apps.insurance import reprice_service as rs
        from apps.insurance.models import SoftechRepriceRun as R
        self.rs, self.R = rs, R
        self.run = R.objects.create(docnumber='12', branchcode='130', status=R.STATUS_APPLIED,
                                    net_delta=Decimal('5'), cust_branch_code='130X1')

    def test_stale_copy_does_not_shift_twice(self):
        stale = self.R.objects.get(pk=self.run.pk)
        self.R.objects.filter(pk=self.run.pk).update(rebalanced=True)
        with mock.patch.object(self.rs, '_hq_conn') as hq:
            with self.assertRaises(self.rs.RepriceError):
                self.rs.rebalance_run(stale, confirm=True)
        hq.assert_not_called()

    def test_refused_while_another_rebalance_of_it_runs(self):
        with _held_elsewhere(self.rs.LOCK_REBALANCE * 1_000_000 + self.run.pk), \
                mock.patch.object(self.rs, '_hq_conn') as hq:
            with self.assertRaises(self.rs.RepriceError):
                self.rs.rebalance_run(self.run, confirm=True)
        hq.assert_not_called()

    def test_softech_commits_only_after_postgres_holds_the_record(self):
        seen = {}

        def at_commit():
            seen['rebalanced'] = self.R.objects.get(pk=self.run.pk).rebalanced
            seen['edits'] = self.run.edits.count()
        hq = _Hq(on_commit=at_commit, rows=[('130', 7, '115', 20)])
        with mock.patch.object(self.rs, '_hq_conn', return_value=hq), \
                mock.patch.object(self.rs, '_edit_balance', return_value=Decimal('10')), \
                mock.patch.object(self.rs, 'verify_running_balance', return_value=(True, 3)):
            self.rs.rebalance_run(self.run, confirm=True)
        self.assertEqual(seen, {'rebalanced': True, 'edits': 1},
                         'SOFTECH committed before the shift was recorded — a retry shifts again')


@override_settings(INSURANCE_SOFTECH_WRITE_ENABLED=True)
class DateEditTests(TestCase):

    def setUp(self):
        import datetime
        from apps.insurance import date_service as ds
        from apps.insurance.models import SoftechDateEditRun as D
        self.ds, self.D = ds, D
        D.objects.create(docnumber='55', branchcode='130', doccode='115', old_date=datetime.date(2026, 10, 20),
                         new_date=datetime.date(2026, 10, 14), nodes=['HQ', '130'], status=D.STATUS_APPLIED)

    def test_second_apply_on_a_changed_receipt_is_refused(self):
        with mock.patch.object(self.ds, '_hq_conn') as hq:
            with self.assertRaises(self.ds.RepriceError):
                self.ds.apply_date_edit(None, '55', '130', '2026-10-12', confirm=True)
        hq.assert_not_called()

    def test_refused_while_another_date_edit_runs(self):
        with _held_elsewhere(self.ds.LOCK_DATE_EDIT), mock.patch.object(self.ds, '_hq_conn') as hq:
            with self.assertRaises(self.ds.RepriceError):
                self.ds.apply_date_edit(None, '77', '130', '2026-10-12', confirm=True)
        hq.assert_not_called()


# ── points removal ────────────────────────────────────────────────────────────

@override_settings(POINTS_REMOVAL_WRITE_ENABLED=True)
class PointsRemovalLockTests(TestCase):

    def test_second_live_run_is_refused(self):
        from apps.customers import points_removal as pr
        conn = mock.MagicMock()
        with _held_elsewhere(pr.LOCK_KEY):
            with self.assertRaises(ValueError):
                pr.run(pics=['130HD1'], commit=True, conn=conn)
        conn.cursor.assert_not_called()


# ── offers channel B ──────────────────────────────────────────────────────────

class _Offers:
    def __init__(self, existing=None, fail_on_insert=None):
        self.existing, self.fail_on_insert = existing, fail_on_insert
        self.log, self.inserts, self.last = [], 0, ''

    def cursor(self):
        return self

    def execute(self, sql, params=None):
        self.last = sql
        if sql.lstrip().upper().startswith('INSERT'):
            self.inserts += 1
            self.log.append('INSERT')
            if self.fail_on_insert and self.inserts == self.fail_on_insert:
                raise RuntimeError('link dropped')

    def fetchone(self):
        if 'MAX(offersno)' in self.last:
            return (100,)
        if 'SELECT offersno' in self.last:
            return (self.existing,) if self.existing else None
        return (1,)

    def begin(self):
        self.log.append('begin')

    def commit(self):
        self.log.append('commit')

    def rollback(self):
        self.log.append('rollback')

    def close(self):
        pass


_PLAN = {'eligible': True, 'extra_items': ['B2'], 'rows': [{
    'specialoffertype': 1, 'branchcode': '-1', 'specialoffer_startdate': '2026-10-26',
    'specialoffer_finishdate': '2099-12-31', 'itemqty_from': 2, 'itemqty_to': 0,
    'specialoffer_itemcode': 'A1', 'bonus_itemcode': 'G1', 'bonus_itemqty': 1, 'offer_by_percent': '0',
    'classifcode': '', 'storecode': '', 'producercode': ''}]}


class ChannelBTests(TestCase):

    def _write(self, fake):
        from apps.offers import channel_b as cb
        with mock.patch('config.sybase.get_sybase_connection', return_value=fake):
            return cb._write_specialoffer(_PLAN, '19')

    def test_identical_live_offer_is_not_inserted_again(self):
        fake = _Offers(existing=6457)
        res = self._write(fake)
        self.assertEqual(fake.inserts, 0, 'a second identical offer reached the cashier')
        self.assertEqual(res['written'][0]['offersno'], 6457)

    def test_failure_half_way_leaves_no_half_offer(self):
        fake = _Offers(fail_on_insert=2)
        with self.assertRaises(RuntimeError):
            self._write(fake)
        self.assertEqual(fake.log[0], 'begin', 'INSERTs ran in autocommit')
        self.assertEqual(fake.log[-1], 'rollback')

    def test_refused_while_another_promo_write_runs(self):
        from apps.offers import channel_b as cb
        fake = _Offers()
        with _held_elsewhere(cb.LOCK_KEY):
            res = self._write(fake)
        self.assertFalse(res['applied'])
        self.assertEqual(fake.inserts, 0)
