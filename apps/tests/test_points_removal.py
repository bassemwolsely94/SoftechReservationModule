"""B7 Option B — remove customers from points at HQ (flag off + balance cleared). Fake HQ with tr_picpoints."""
import io

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.customers import points_removal as PR
from apps.customers.models import PointsRemoval as R


class HQ:
    """localcustomers.picpoints + localcustomerspoints (tot, con) + lcpointstrans resets + a picpoints log.
    INSERT into picpoints behaves like tr_picpoints (negative → conpoints += −points)."""

    def __init__(self, flags, balances, resets, race=None):
        self.flags, self.bal, self.resets, self.race, self.log, self.sql = flags, balances, resets, race, [], []

    def cursor(self):
        hq = self

        class C:
            def execute(self, sql, p=None):
                s = ' '.join(sql.split())
                hq.sql.append(s)
                self.r = []
                if 'FROM SOFTECHDB9.dbo.lcpointstrans' in s:
                    self.r = [(pic,) for pic, u in hq.resets if u in p]
                elif s.startswith('SELECT picpoints FROM'):
                    self.r = [(hq.flags[p[0]],)] if p[0] in hq.flags else []
                elif s.startswith('SELECT totpoints, conpoints'):
                    self.r = [hq.bal[p[0]]] if p[0] in hq.bal else []
                elif s.startswith('UPDATE SOFTECHDB9.dbo.localcustomers SET picpoints = 0'):
                    if hq.flags.get(p[1]) == 1:
                        hq.flags[p[1]] = 0
                    if hq.race:                                   # a sale lands right after our read
                        t, c = hq.bal[hq.race]
                        hq.bal[hq.race] = (t + 7, c)
                        hq.race = None
                elif s.startswith('INSERT INTO SOFTECHDB9.dbo.picpoints'):
                    pic, pts = p[0], p[1]
                    hq.log.append((pic, pts, s, p))
                    t, c = hq.bal[pic]
                    hq.bal[pic] = (t, c - pts) if pts < 0 else (t + pts, c)

            def fetchall(self):
                return self.r
        return C()

    def close(self):
        pass


def hq():
    return HQ(flags={'A': 1, 'B': 0, 'C': 1, 'D': 0, 'E': 1},
              balances={'A': (1000, 400), 'B': (500, 300), 'C': (10, 10), 'D': (5, 5), 'E': (90, 0)},
              resets=[('A', '19'), ('B', '19'), ('C', '19'), ('D', '19'), ('E', '54')])


class RemovalTests(TestCase):
    def setUp(self):
        from apps.tests.factories import make_user
        _, self.admin, _ = make_user('adm', role='admin')
        self.admin.softech_user_id = '1509'
        self.admin.save()

    def test_candidates_are_user_19_resets_still_enrolled_or_holding_points(self):
        self.assertEqual(PR.candidates(hq()), ['A', 'B', 'C'])          # D done already, E reset by 54
        self.assertEqual(PR.candidates(hq(), users=('19', '54')), ['A', 'B', 'C', 'E'])

    def test_gate_off_is_dry_run(self):
        db = hq()
        recs = PR.run(user=self.admin, commit=True, conn=db)
        self.assertEqual({r.status for r in recs}, {R.STATUS_DRY_RUN})
        self.assertEqual(recs[0].points_cleared, 600)
        self.assertFalse(any(s.startswith(('UPDATE', 'INSERT')) for s in db.sql))

    @override_settings(POINTS_REMOVAL_WRITE_ENABLED=True)
    def test_flag_off_and_balance_cleared_with_the_reset_method(self):
        db = hq()
        recs = PR.run(user=self.admin, commit=True, conn=db)
        self.assertEqual([(r.pic, r.status, r.points_cleared) for r in recs],
                         [('A', 'verified', 600), ('B', 'verified', 200), ('C', 'verified', 0)])
        self.assertEqual(db.flags['A'], 0)
        self.assertEqual(db.bal['A'], (1000, 1000))
        pic, pts, sql, params = db.log[0]
        self.assertEqual((pic, pts), ('A', -600))
        self.assertIn("'100', '0', 0, getdate()", sql)                 # branch 100, doc '0', docnumber 0
        self.assertEqual(params[2:], [PR.REASON, '1509'])
        upd = [s for s in db.sql if s.startswith('UPDATE')][0]
        self.assertIn('usercode = ?, trans_time = getdate()', upd)
        self.assertEqual(AuditLog.objects.filter(action='customer_points_removed').count(), 3)
        # idempotent
        again = PR.run(pics=['A'], user=self.admin, commit=True, conn=db)
        self.assertEqual(again[0].status, R.STATUS_NO_CHANGE)
        self.assertEqual(len(db.log), 2)

    @override_settings(POINTS_REMOVAL_WRITE_ENABLED=True)
    def test_balance_reread_after_flag_update(self):
        db = hq()
        db.race = 'A'                                       # +7 points arrive between our first read and the clear
        r = PR.run(pics=['A'], user=self.admin, commit=True, conn=db)[0]
        self.assertEqual((r.status, r.points_cleared, r.balance_after), (R.STATUS_VERIFIED, 607, 0))

    @override_settings(POINTS_REMOVAL_WRITE_ENABLED=True)
    def test_operator_without_softech_id_fails_and_stops(self):
        self.admin.softech_user_id = ''
        self.admin.save()
        db = hq()
        recs = PR.run(user=self.admin, commit=True, conn=db)
        self.assertEqual([r.status for r in recs], [R.STATUS_FAILED])
        self.assertEqual(db.flags['A'], 1)

    @override_settings(POINTS_REMOVAL_BATCH_MAX=2)
    def test_batch_cap_and_command(self):
        from unittest import mock
        out = io.StringIO()
        with mock.patch('config.sybase.get_sybase_connection', return_value=hq()):
            call_command('remove_from_points', user='adm', limit=10, stdout=out)
        t = out.getvalue()
        self.assertIn('2 codes · dry_run=2 · points to clear: 800', t)
        self.assertIn('review list: scratch', t)
