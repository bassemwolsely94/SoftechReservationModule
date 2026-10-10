"""B7 merge part 2 — approved pair merged at HQ (fake SOFTECH): points moved once, old code closed, read back."""
import io
import re

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.customers import account_state as AS
from apps.customers import merge_write as MW
from apps.customers.models import Customer, CustomerMergeWrite as W, MergeCandidate as MC


class HQ:
    """localcustomers {pic: [status, lock, died, points]}, balances {pic: n}, picpoints log (trigger applied)."""
    def __init__(self, codes, fail_insert_no=None):
        self.codes = {k: list(v[:4]) for k, v in codes.items()}
        self.bal = {k: v[4] for k, v in codes.items()}
        self.log, self.inserts, self.fail_insert_no = [], 0, fail_insert_no

    def cursor(self):
        return Cur(self)

    def close(self):
        pass


class Cur:
    def __init__(self, hq):
        self.hq, self.r = hq, []

    def execute(self, sql, p=None):
        s, hq = ' '.join(sql.split()), self.hq
        if s.startswith('SELECT phcodestatus, piclock, picdied, picpoints'):
            self.r = [tuple(hq.codes[p[0]])] if p[0] in hq.codes else []
        elif s.startswith('SELECT sum(totpoints - conpoints)'):
            self.r = [(hq.bal.get(p[0]),)]
        elif s.startswith('SELECT count(*), sum(points) FROM SOFTECHDB9.dbo.picpoints'):
            rows = [x for x in hq.log if x[0] == p[0] and x[2] == p[1]]
            self.r = [(len(rows), sum(x[1] for x in rows) if rows else None)]
        elif s.startswith('INSERT INTO SOFTECHDB9.dbo.picpoints'):
            hq.inserts += 1
            if hq.inserts == hq.fail_insert_no:
                raise RuntimeError('link dropped')
            pic, pts, tag, op = p
            hq.log.append((pic, pts, tag, op))
            hq.bal[pic] = hq.bal.get(pic, 0) + pts
        elif s.startswith('UPDATE SOFTECHDB9.dbo.localcustomers SET phcodestatus'):
            assert re.search(r"phcodestatus = '0', phcodestatususercode = \?, phcodestatustime = getdate\(\)", s)
            op, _, pic, was = p
            if (hq.codes[pic][0] or '') == was:
                hq.codes[pic][0] = '0'
        else:
            raise AssertionError(s)

    def fetchall(self):
        return self.r


ON = override_settings(CUSTOMER_MERGE_WRITE_ENABLED=True)


class MergeWriteTests(TestCase):
    def setUp(self):
        from apps.tests.factories import make_branch, make_user
        _, self.op, _ = make_user('mw', role='admin', branch=make_branch('A', '130'))
        self.op.softech_user_id = '1509'
        self.op.save()
        self.cand = MC.objects.create(old_pic='03HD3059', main_pic='06HD8958', main_auto_pic='06HD8958',
                                      cluster='03HD3059', strength='strong', status=MC.APPROVED)
        Customer.objects.create(name='x', phone='01001112223', softech_pic='03HD3059', softech_status='1')

    def hq(self, old=('1', 0, 0, 1, 9), main=('1', 0, 0, 1, 100), **kw):
        return HQ({'03HD3059': old, '06HD8958': main}, **kw)

    def test_dry_run_writes_nothing(self):
        hq = self.hq()
        r = MW.merge_one(self.cand, user=self.op, commit=True, conn=hq)
        self.assertEqual((r.status, r.points_moved), (W.STATUS_DRY_RUN, 9))
        self.assertIn('CUSTOMER_MERGE_WRITE_ENABLED is off', r.error)
        self.assertEqual((hq.log, hq.codes['03HD3059'][0]), ([], '1'))
        self.cand.refresh_from_db()
        self.assertEqual(self.cand.status, MC.APPROVED)

    @ON
    def test_merge_moves_points_once_and_closes_old(self):
        hq = self.hq()
        r = MW.merge_one(self.cand, user=self.op, commit=True, conn=hq)
        self.assertEqual(r.status, W.STATUS_VERIFIED, r.error)
        self.assertEqual(hq.log, [('03HD3059', -9, f'B7 merge {self.cand.pk}', '1509'),
                                  ('06HD8958', 9, f'B7 merge {self.cand.pk}', '1509')])
        self.assertEqual((hq.bal['03HD3059'], hq.bal['06HD8958'], hq.codes['03HD3059'][0]), (0, 109, '0'))
        self.cand.refresh_from_db()
        self.assertEqual(self.cand.status, MC.MERGED)
        c = Customer.objects.get(softech_pic='03HD3059')
        self.assertEqual((c.merged_into_pic, c.softech_status), ('06HD8958', '0'))
        st = AS.state(c)
        self.assertTrue(st['blocked'])
        self.assertIn('06HD8958', st['message'])
        r2 = MW.merge_one(self.cand, user=self.op, commit=True, conn=hq)      # rerun: nothing moves again
        self.assertEqual(r2.status, W.STATUS_NO_CHANGE)
        self.assertEqual(len(hq.log), 2)

    @ON
    def test_stop_after_debit_resumes_with_credit_only(self):
        hq = self.hq(fail_insert_no=2)
        r = MW.merge_one(self.cand, user=self.op, commit=True, conn=hq)
        self.assertEqual(r.status, W.STATUS_FAILED)
        self.cand.refresh_from_db()
        self.assertEqual(self.cand.status, MC.FAILED)
        recs = MW.run(pics=['03HD3059'], user=self.op, commit=True, conn=hq)
        self.assertEqual(recs[0].status, W.STATUS_VERIFIED, recs[0].error)
        self.assertEqual([x[1] for x in hq.log], [-9, 9])
        self.assertEqual(hq.bal['06HD8958'], 109)

    @ON
    def test_refusals_write_nothing(self):
        cases = [({'main': ('0', 0, 0, 1, 5)}, 'not active'),
                 ({'old': ('1', 0, 0, 0, 40)}, 'outside the points system'),
                 ({'old': ('1', 1, 0, 1, 0)}, 'entity')]
        for kw, msg in cases:
            MC.objects.filter(pk=self.cand.pk).update(status=MC.APPROVED)
            self.cand.refresh_from_db()
            hq = self.hq(**kw)
            r = MW.merge_one(self.cand, user=self.op, commit=True, conn=hq)
            self.assertEqual(r.status, W.STATUS_FAILED)
            self.assertIn(msg, r.error)
            self.assertEqual(hq.log, [])
        MC.objects.filter(pk=self.cand.pk).update(status=MC.MARKED)
        self.cand.refresh_from_db()
        self.assertIn('not approved', MW.merge_one(self.cand, user=self.op, commit=True, conn=self.hq()).error)

    @ON
    def test_old_already_closed_without_points_is_recorded(self):
        hq = self.hq(old=('0', 0, 0, 1, 0))
        r = MW.merge_one(self.cand, user=self.op, commit=True, conn=hq)
        self.assertEqual(r.status, W.STATUS_NO_CHANGE)
        self.cand.refresh_from_db()
        self.assertEqual(self.cand.status, MC.MERGED)

    def test_command_dry_run(self):
        from unittest import mock
        out = io.StringIO()
        with mock.patch('config.sybase.get_sybase_connection', return_value=self.hq()):
            call_command('merge_customer_codes', approved=True, user='mw', stdout=out)
        t = out.getvalue()
        self.assertIn('03HD3059 -> 06HD8958: dry_run', t)
        self.assertIn('points to move 9', t)
        self.assertIn('dry run', t)
