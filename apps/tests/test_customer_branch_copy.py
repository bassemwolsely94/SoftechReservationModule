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
