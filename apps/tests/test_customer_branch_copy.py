"""B7 step 3 — copy HQ customer flags onto a branch copy (audited, read back, gated). Fake SOFTECH."""
import datetime as dt
import io
import re

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.customers import branch_copy as BC
from apps.customers.models import BranchCopyWrite as W, CustomerStatusDrift

COLS = BC.FLAGS + BC.EDITOR
T = dt.datetime(2026, 10, 8, 6, 5, 31, 250000)


class DB:
    """One localcustomers table: {pic: {col: value}}. Executes the two statements branch_copy uses."""

    def __init__(self, rows, revert=False, race=None):
        self.rows, self.revert, self.race, self.sql = rows, revert, race, []

    def cursor(self):
        db = self

        class C:
            def execute(self, sql, p=None):
                db.sql.append((sql, p))
                if sql.startswith('SELECT'):
                    row = db.rows.get(p[0])
                    self.r = [tuple(row[c] for c in COLS)] if row else []
                    return
                if db.race:                       # someone changes the copy between our read and write
                    db.rows[db.race[0]].update(db.race[1])
                    db.race = None
                sets = re.split(r', (?=\w+ = )', sql.split(' SET ')[1].split(' WHERE ')[0])
                cols = [s.split(' = ')[0] for s in sets]
                pic = p[len(cols)]
                old = p[len(cols) + 1:]
                row = db.rows[pic]
                if all((row[c] if row[c] is not None else (0 if c not in BC._TEXT else '')) == o
                       for c, o in zip(BC.FLAGS, old)) and not db.revert:
                    for c, v in zip(cols, p[:len(cols)]):
                        row[c] = dt.datetime.strptime(v, '%Y-%m-%d %H:%M:%S.%f') if c == 'trans_time' else v

            def fetchall(self):
                return self.r
        return C()

    def close(self):
        pass


def hq():
    return DB({'05HD999': dict(phcodestatus='1', piclock=0, picdied=0, picpoints=0, picdiscounts=1,
                               usercode='1509', trans_time=T)})


def node(**kw):
    row = dict(phcodestatus='1', piclock=0, picdied=0, picpoints=1, picdiscounts=0, usercode='11',
               trans_time=dt.datetime(2018, 3, 10, 14, 20, 47))
    row.update(kw)
    return DB({'05HD999': row})


class CopyTests(TestCase):
    def setUp(self):
        from apps.tests.factories import make_user
        _, self.admin, _ = make_user('adm', role='admin')
        CustomerStatusDrift.objects.create(pic='05HD999', node_branch='140', field='points', hq_value='0',
                                           node_value='1', direction='hq_stricter', last_seen=T)

    def go(self, n, commit=True):
        return BC.copy_one('05HD999', '140', user=self.admin, commit=commit, hq_conn=hq(), node_conn=n)

    def test_gate_off_is_a_dry_run(self):
        n = node()
        r = self.go(n)
        self.assertEqual(r.status, W.STATUS_DRY_RUN)
        self.assertIn('WRITE_ENABLED is off', r.error)
        self.assertFalse(any(s.startswith('UPDATE') for s, _ in n.sql))
        self.assertEqual(n.rows['05HD999']['picpoints'], 1)

    @override_settings(CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True)
    def test_writes_changed_flags_and_hq_editor_then_verifies(self):
        n = node()
        r = self.go(n)
        self.assertEqual(r.status, W.STATUS_VERIFIED, r.error)
        row = n.rows['05HD999']
        self.assertEqual((row['picpoints'], row['picdiscounts'], row['usercode'], row['trans_time']), (0, 1, '1509', T))
        upd = [s for s, _ in n.sql if s.startswith('UPDATE')][0]
        self.assertIn('SET picpoints = ?, picdiscounts = ?, usercode = ?, trans_time = convert(datetime, ?)', upd)
        self.assertNotIn('table_dumped', upd)
        self.assertEqual(r.before['picpoints'], 1)
        self.assertEqual(r.after['picpoints'], 0)
        self.assertTrue(AuditLog.objects.filter(action='customer_branch_copy_written', object_id=str(r.pk)).exists())
        self.assertIsNotNone(CustomerStatusDrift.objects.get(pic='05HD999').resolved_at)
        # idempotent: second run writes nothing
        r2 = self.go(n)
        self.assertEqual(r2.status, W.STATUS_NO_CHANGE)
        self.assertEqual(sum(1 for s, _ in n.sql if s.startswith('UPDATE')), 1)

    @override_settings(CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True)
    def test_concurrent_change_is_not_overwritten(self):
        n = node()
        n.race = ('05HD999', {'picdiscounts': 1})
        r = self.go(n)
        self.assertEqual(r.status, W.STATUS_FAILED)              # copy moved on: neither HQ nor what we read
        self.assertEqual(n.rows['05HD999']['picpoints'], 1)       # our write did not land

    @override_settings(CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True)
    def test_reverted_write_is_reported(self):
        r = self.go(DB(node().rows, revert=True))     # e.g. a branch trigger undoes the write
        self.assertEqual(r.status, W.STATUS_CONFLICT)
        self.assertTrue(AuditLog.objects.filter(action='customer_branch_copy_written').exists())

    def test_missing_on_branch_fails_cleanly(self):
        r = self.go(DB({}))
        self.assertEqual(r.status, W.STATUS_FAILED)
        self.assertIn('no copy on branch 140', r.error)

    @override_settings(CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True)
    def test_pilot_cap_and_command_roles(self):
        with self.assertRaises(ValueError):
            BC.run(['A', 'B'], '140', user=self.admin, commit=True)
        from apps.tests.factories import make_user
        make_user('ph', role='pharmacist')
        with self.assertRaises(CommandError):
            call_command('push_customer_branch_copy', pic=['05HD999'], branch='140', user='ph', stdout=io.StringIO())


def node_db(rows):
    base = dict(phcodestatus='1', piclock=0, picdied=0, picpoints=1, picdiscounts=0, usercode='11',
                trans_time=dt.datetime(2018, 3, 10, 14, 20, 47))
    return DB({p: {**base, **kw} for p, kw in rows.items()})


def hq_db(rows):
    base = dict(phcodestatus='1', piclock=0, picdied=0, picpoints=1, picdiscounts=0, usercode='1509', trans_time=T)
    return DB({p: {**base, **kw} for p, kw in rows.items()})


class BatchTests(TestCase):
    def setUp(self):
        from unittest import mock
        from apps.tests.factories import make_branch, make_user
        b = make_branch('B', '140')
        b.db_host = '10.0.0.4'
        b.save()
        _, self.admin, _ = make_user('adm2', role='admin')
        D = CustomerStatusDrift
        for pic, field, direction in (('P1', 'points', D.HQ_STRICTER), ('P2', 'points', D.HQ_STRICTER),
                                      ('P3', 'points', D.HQ_STRICTER), ('P3', 'status', D.NODE_STRICTER),
                                      ('07HD11663', 'points', D.HQ_STRICTER), ('P4', 'lock', D.HQ_STRICTER),
                                      ('P5', 'points', D.HQ_STRICTER)):
            D.objects.create(pic=pic, node_branch='140', field=field, hq_value='0', node_value='1',
                             direction=direction, last_seen=T)
        self.hq = hq_db({'P1': {'picpoints': 0, 'picdiscounts': 1}, 'P2': {'picpoints': 0},
                         'P3': {'picpoints': 0}, 'P4': {'piclock': 1}, '07HD11663': {'picpoints': 0},
                         'P5': {'picpoints': 0}})
        self.node = node_db({'P1': {}, 'P2': {}, 'P3': {'phcodestatus': '0'}, 'P4': {}, '07HD11663': {},
                             'P5': {'phcodestatus': '0'}})       # P5: node blocked, HQ active → would relax
        self.patch = [mock.patch('config.sybase.get_sybase_connection', return_value=self.hq),
                      mock.patch('config.sybase.get_branch_connection', return_value=self.node)]
        for p in self.patch:
            p.start()
            self.addCleanup(p.stop)

    def test_candidates_exclude_branch_stricter_and_held(self):
        self.assertEqual(BC.batch_candidates('140', 50), ['P1', 'P2', 'P4', 'P5'])
        self.assertEqual(BC.batch_candidates('140', 2), ['P1', 'P2'])

    @override_settings(CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True)
    def test_batch_tightens_only_and_never_grants_discount(self):
        recs = BC.run_batch('140', user=self.admin, commit=True)
        got = {r.pic: r.status for r in recs}
        self.assertEqual(got, {'P1': 'verified', 'P2': 'verified', 'P4': 'verified', 'P5': 'skipped'})
        self.assertEqual(self.node.rows['P1']['picpoints'], 0)
        self.assertEqual(self.node.rows['P1']['picdiscounts'], 0)          # discount NOT copied
        self.assertEqual(self.node.rows['P4']['piclock'], 1)
        self.assertEqual(self.node.rows['P5']['phcodestatus'], '0')        # not relaxed
        self.assertEqual(self.node.rows['07HD11663']['picpoints'], 1)      # held
        self.assertIsNotNone(CustomerStatusDrift.objects.get(pic='P1', field='points').resolved_at)

    @override_settings(CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True)
    def test_include_discount_copies_it(self):
        BC.run_batch('140', user=self.admin, commit=True, include_discount=True, limit=1)
        self.assertEqual(self.node.rows['P1']['picdiscounts'], 1)

    def test_batch_dry_run_and_command(self):
        out = io.StringIO()
        call_command('push_customer_branch_copy', from_drift=True, branch='140', user='adm2', limit=2, stdout=out)
        t = out.getvalue()
        self.assertIn('P1 @ branch 140: dry_run', t)
        self.assertIn('2 codes - dry_run=2', t)
        self.assertIn('review list: scratch', t)
        self.assertEqual(self.node.rows['P1']['picpoints'], 1)

    @override_settings(CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True, CUSTOMER_BRANCH_COPY_BATCH_MAX=2)
    def test_batch_max_caps_limit_and_stops_on_conflict(self):
        self.assertEqual(len(BC.run_batch('140', user=self.admin, commit=False, limit=50)), 2)
        self.node.race = ('P1', {'picdiscounts': 1})
        recs = BC.run_batch('140', user=self.admin, commit=True)
        self.assertEqual([r.status for r in recs], ['failed'])            # stopped at the first problem


class RemovalCopyTests(TestCase):
    def setUp(self):
        from unittest import mock
        from apps.customers.models import PointsRemoval as R
        from apps.tests.factories import make_branch, make_user
        b = make_branch('B', '140')
        b.db_host = '10.0.0.4'
        b.save()
        _, self.admin, _ = make_user('adm3', role='admin')
        for pic in ('R1', 'R2', 'R3', 'R4'):
            R.objects.create(pic=pic, status='verified', flag_after=0, balance_after=0, discount_after=1)
        R.objects.create(pic='R5', status='failed')
        self.hq = hq_db({p: {'picpoints': 0, 'picdiscounts': 1} for p in ('R1', 'R2', 'R3', 'R4')})
        self.node = node_db({'R1': {}, 'R2': {'picpoints': 0, 'picdiscounts': 1}, 'R3': {'picpoints': 0}})
        for p in (mock.patch('config.sybase.get_sybase_connection', return_value=self.hq),
                  mock.patch('config.sybase.get_branch_connection', return_value=self.node)):
            p.start()
            self.addCleanup(p.stop)

    @override_settings(CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True)
    def test_points_off_and_discount_on_branch_copies(self):
        recs = BC.run_removals_batch('140', user=self.admin, commit=True)
        got = {r.pic: r.status for r in recs}
        self.assertEqual(got, {'R1': 'verified', 'R2': 'no_change', 'R3': 'verified', 'R4': 'skipped'})
        self.assertEqual((self.node.rows['R1']['picpoints'], self.node.rows['R1']['picdiscounts']), (0, 1))
        self.assertEqual(self.node.rows['R3']['picdiscounts'], 1)
        self.assertEqual(BC.removal_candidates('140', 50), [])          # all settled → next run is empty

    @override_settings(CUSTOMER_BRANCH_COPY_WRITE_ENABLED=True, CUSTOMER_BRANCH_COPY_BATCH_MAX=2)
    def test_command_batches(self):
        out = io.StringIO()
        call_command('push_customer_branch_copy', from_removals=True, branch='140', user='adm3', batches=5,
                     quiet=True, commit=True, stdout=out)
        t = out.getvalue()
        self.assertIn('batch 1: 2 codes - verified=1, no_change=1', t.replace('no_change=1, verified=1', 'verified=1, no_change=1'))
        self.assertIn('batch 3: 0 codes', t)
