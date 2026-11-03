"""
Daily counts — generation, blind counting, review (apps/stockcount/daily/service.py + views.py).
Counts stay in our database: the only SOFTECH contact is a READ of one item's balance at submit
time (patched here). Switches: DAILY_COUNT_ENABLED + BranchSettings.daily_count_enabled.
"""
import datetime as dt
import json
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.branches.models import BranchSettings
from apps.catalog.models import ItemStock
from apps.stockcount.daily import service
from apps.stockcount.models import (DailyCountAttempt, DailyCountPick, DailyCountSettings,
                                    StockCountSession, StockCountSnapshot)
from .factories import make_admin, make_branch, make_branch2, make_item, make_salesperson, make_user

TODAY = dt.date(2026, 11, 3)
LIVE = 'apps.stockcount.daily.service.fetch_stock_balance'


def _grant_manager(profile):
    from apps.stock_audit.models import StockAuditAccess
    StockAuditAccess.objects.create(staff=profile)


@override_settings(DAILY_COUNT_ENABLED=True)
class DailyCountTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        bs = BranchSettings.for_branch(self.branch)
        bs.daily_count_enabled = True
        bs.save()
        for i in range(30):
            it = make_item(f'صنف {i}', f'D{i:03d}')
            it.cost_price = Decimal('100')
            it.save()
            ItemStock.objects.create(item=it, branch=self.branch, softech_store_code='101',
                                     quantity_on_hand=Decimal('5'), monthly_qty=Decimal('1'))
        _, self.s1, self.c1 = make_salesperson('dc_s1', branch=self.branch)
        _, self.s2, self.c2 = make_salesperson('dc_s2', branch=self.branch)
        _, self.mgr, self.cm = make_user('dc_mgr', role='pharmacist', branch=self.branch)
        _grant_manager(self.mgr)
        _, self.admin, self.ca = make_admin('dc_admin')

    def _gen(self):
        return service.generate(self.branch, TODAY)

    def _my(self, client):
        with mock.patch('apps.stockcount.daily.views.cairo_today', return_value=TODAY):
            return client.get('/api/stockcount/daily/my/')

    def _count(self, client, pick, qty, live=Decimal('5'), token=None):
        body = {'pick_id': pick.pk, 'counted_qty': str(qty)}
        if token:
            body['client_token'] = token
        with mock.patch(LIVE, return_value={pick.item_code: live}):
            return client.post('/api/stockcount/daily/my/count/', body, format='json')

    def _first_pick(self, profile):
        return DailyCountPick.objects.filter(session__assigned_to=profile).order_by('pk').first()

    # ── switches ──────────────────────────────────────────────────────────────
    def test_switch_off_404(self):
        with override_settings(DAILY_COUNT_ENABLED=False):
            self.assertEqual(self.c1.get('/api/stockcount/daily/my/').status_code, 404)
            self.assertEqual(self.cm.get('/api/stockcount/daily/board/').status_code, 404)

    def test_branch_switch_off_generates_nothing(self):
        bs = BranchSettings.for_branch(self.branch)
        bs.daily_count_enabled = False
        bs.save()
        self.assertEqual(self._gen(), 0)

    # ── generation ────────────────────────────────────────────────────────────
    def test_generate_idempotent_and_skips_leave(self):
        from apps.hr.models import LeaveRequest, LeaveType
        lt = LeaveType.objects.create(code='annual', name='Annual', name_ar='اعتيادي')
        LeaveRequest.objects.create(staff=self.s2, leave_type=lt, start_date=TODAY, end_date=TODAY,
                                    days_requested=1, status=LeaveRequest.STATUS_APPROVED)
        self._gen()
        self._gen()
        sessions = StockCountSession.objects.filter(mode='daily', count_date=TODAY)
        self.assertEqual(list(sessions.values_list('assigned_to', flat=True)), [self.s1.pk])
        self.assertEqual(DailyCountPick.objects.filter(session__in=sessions).count(), 20)
        self.assertTrue(AuditLog.objects.filter(action='daily_count_generated').exists())

    def test_pharmacists_excluded_by_default_and_no_shared_items(self):
        self._gen()
        self.assertFalse(StockCountSession.objects.filter(mode='daily', assigned_to=self.mgr).exists())
        codes = list(DailyCountPick.objects.values_list('item_code', flat=True))
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(codes), 30)            # 2 people × 20 wanted, only 30 eligible

    def test_profile_without_branch_or_inactive_ignored(self):
        _, nob, _ = make_salesperson('dc_nob', branch=self.branch)
        nob.is_active = False
        nob.save()
        self._gen()
        self.assertFalse(StockCountSession.objects.filter(assigned_to=nob).exists())

    # ── counting (blind) ──────────────────────────────────────────────────────
    def test_my_list_is_blind(self):
        self._gen()
        r = self._my(self.c1)
        self.assertEqual(r.status_code, 200, r.content)
        text = json.dumps(r.json())
        for key in ('expected', 'difference', 'value_egp', 'reasons', 'weight'):
            self.assertNotIn(key, text)
        self.assertEqual(len(r.json()['picks']), 15)
        p = self._first_pick(self.s1)
        r = self._count(self.c1, p, 4)
        self.assertEqual(r.status_code, 200, r.content)
        for key in ('expected', 'difference', 'value_egp'):
            self.assertNotIn(key, json.dumps(r.json()))

    def test_count_uses_live_then_mirror(self):
        self._gen()
        p = self._first_pick(self.s1)
        self._count(self.c1, p, 3, live=Decimal('4'))
        a = DailyCountAttempt.objects.get(pick=p)
        self.assertEqual((a.expected_qty, a.expected_source, a.difference), (Decimal('4'), 'live', Decimal('-1')))
        self.assertEqual(a.value_egp, Decimal('100'))
        with mock.patch(LIVE, side_effect=RuntimeError('down')):
            r = self.c1.post('/api/stockcount/daily/my/count/', {'pick_id': p.pk, 'counted_qty': '5'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        a2 = DailyCountAttempt.objects.filter(pick=p).order_by('-pk').first()
        self.assertEqual((a2.expected_qty, a2.expected_source), (Decimal('5'), 'mirror'))
        snap = StockCountSnapshot.objects.get(session=p.session, item_code=p.item_code)
        self.assertEqual(snap.counted_qty, Decimal('5'))       # snapshot mirrors the latest attempt

    def test_double_submit_same_token_one_attempt(self):
        self._gen()
        p = self._first_pick(self.s1)
        self._count(self.c1, p, 4, token='tok-1')
        r = self._count(self.c1, p, 4, token='tok-1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(DailyCountAttempt.objects.filter(pick=p).count(), 1)

    def test_cannot_count_someone_elses_pick(self):
        self._gen()
        p = self._first_pick(self.s2)
        self.assertEqual(self._count(self.c1, p, 1).status_code, 404)

    def test_negative_or_bad_qty_rejected(self):
        self._gen()
        p = self._first_pick(self.s1)
        self.assertEqual(self._count(self.c1, p, -1).status_code, 400)
        self.assertEqual(self._count(self.c1, p, 'x').status_code, 400)

    # ── review ────────────────────────────────────────────────────────────────
    def test_salesperson_cannot_review(self):
        self._gen()
        p = self._first_pick(self.s1)
        self._count(self.c1, p, 4)
        self.assertEqual(self.c1.get('/api/stockcount/daily/board/').status_code, 403)
        self.assertEqual(self.c1.post(f'/api/stockcount/daily/picks/{p.pk}/accept/',
                                      {'reason': 'loss'}, format='json').status_code, 403)

    def test_manager_board_and_accept_writes_audit(self):
        self._gen()
        p = self._first_pick(self.s1)
        self._count(self.c1, p, 4)
        with mock.patch('apps.stockcount.daily.views.cairo_today', return_value=TODAY):
            r = self.cm.get('/api/stockcount/daily/board/')
        self.assertEqual(r.status_code, 200, r.content)
        diffs = r.json()['differences']
        self.assertEqual([d['pick_id'] for d in diffs], [p.pk])
        self.assertEqual(diffs[0]['difference'], -1.0)
        r = self.cm.post(f'/api/stockcount/daily/picks/{p.pk}/accept/',
                         {'reason': 'loss', 'note': 'كسر', 'needs_softech_adjustment': True}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        p.refresh_from_db()
        self.assertEqual((p.status, p.review_reason, p.needs_softech_adjustment), ('accepted', 'loss', True))
        self.assertTrue(AuditLog.objects.filter(action='daily_count_accepted', object_id=str(p.pk)).exists())

    def test_recount_goes_to_other_person_blind(self):
        self._gen()
        p = self._first_pick(self.s1)
        self._count(self.c1, p, 4)
        r = self.cm.post(f'/api/stockcount/daily/picks/{p.pk}/recount/', {'assignee_id': self.s2.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        mine = [x['pick_id'] for x in self._my(self.c2).json()['picks']]
        self.assertIn(p.pk, mine)
        self.assertEqual(self._count(self.c2, p, 5).status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.status, 'counted')
        self.assertEqual(p.attempts.count(), 2)

    def test_manager_other_branch_403(self):
        b2 = make_branch2()
        _, other, co = make_user('dc_mgr2', role='pharmacist', branch=b2)
        _grant_manager(other)
        self._gen()
        p = self._first_pick(self.s1)
        self._count(self.c1, p, 4)
        self.assertEqual(co.post(f'/api/stockcount/daily/picks/{p.pk}/accept/',
                                 {'reason': 'loss'}, format='json').status_code, 404)

    def test_escalate_on_value_and_repeat(self):
        self._gen()
        p = self._first_pick(self.s1)
        self._count(self.c1, p, 2)                  # -3 × 100 EGP = 300 ≥ 200
        p.refresh_from_db()
        self.assertEqual(p.status, 'escalated')
        self.assertIn('200', p.escalation_reason)
        # an escalated pick is the auditor's, not the branch manager's
        self.assertEqual(self.cm.post(f'/api/stockcount/daily/picks/{p.pk}/accept/',
                                      {'reason': 'loss'}, format='json').status_code, 403)
        self.assertEqual(self.ca.post(f'/api/stockcount/daily/picks/{p.pk}/accept/',
                                      {'reason': 'loss'}, format='json').status_code, 200)
        s = DailyCountSettings.get()
        s.escalate_value_egp = Decimal('100000')
        s.escalate_repeat_count = 1
        s.save()
        q = DailyCountPick.objects.filter(session__assigned_to=self.s1).order_by('pk')[1]
        self._count(self.c1, q, 4)
        q.refresh_from_db()
        self.assertEqual(q.status, 'escalated')

    def test_manager_own_count_goes_to_auditor(self):
        s = DailyCountSettings.get()
        s.include_pharmacists = True
        s.save()
        self._gen()
        p = self._first_pick(self.mgr)
        self._count(self.cm, p, 4)                   # small diff, but it's the manager's own count
        p.refresh_from_db()
        self.assertEqual(p.status, 'escalated')

    def test_match_needs_no_review(self):
        self._gen()
        p = self._first_pick(self.s1)
        self._count(self.c1, p, 5)
        p.refresh_from_db()
        self.assertEqual(p.status, 'counted')
        with mock.patch('apps.stockcount.daily.views.cairo_today', return_value=TODAY):
            self.assertEqual(self.cm.get('/api/stockcount/daily/board/').json()['differences'], [])

    def test_close_day_marks_missed(self):
        self._gen()
        p = self._first_pick(self.s1)
        self._count(self.c1, p, 5)
        service.close_day(self.branch, TODAY)
        self.assertEqual(DailyCountPick.objects.filter(session__assigned_to=self.s1, status='missed').count(), 14)
        self.assertEqual(StockCountSession.objects.get(assigned_to=self.s1, count_date=TODAY).status, 'closed')

    def test_existing_session_list_hides_daily(self):
        self._gen()
        r = self.ca.get('/api/stockcount/sessions/')
        rows = r.json() if isinstance(r.json(), list) else r.json().get('results', [])
        self.assertFalse([x for x in rows if x.get('mode') == 'daily'])


class DailyCountJobTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        bs = BranchSettings.for_branch(self.branch)
        bs.daily_count_enabled = True
        bs.working_hours = [{'from': '08:00', 'to': '01:00'}]
        bs.save()
        it = make_item('صنف', 'J0001')
        ItemStock.objects.create(item=it, branch=self.branch, softech_store_code='101',
                                 quantity_on_hand=Decimal('5'), monthly_qty=Decimal('1'))
        _, self.s1, _ = make_salesperson('job_s1', branch=self.branch)

    def _at(self, day, hour):
        from django.utils import timezone
        return timezone.make_aware(dt.datetime.combine(day, dt.time(hour)))

    def test_job_off_does_nothing(self):
        service.run_job(self._at(TODAY, 10))
        self.assertFalse(StockCountSession.objects.filter(mode='daily').exists())

    @override_settings(DAILY_COUNT_ENABLED=True)
    def test_job_generates_after_hour_and_closes_after_branch_close(self):
        service.run_job(self._at(TODAY, 6))              # before job_hour 7
        self.assertFalse(StockCountSession.objects.filter(mode='daily').exists())
        service.run_job(self._at(TODAY, 10))
        sess = StockCountSession.objects.get(mode='daily', count_date=TODAY)
        service.run_job(self._at(TODAY + dt.timedelta(days=1), 0))   # still open until 01:00
        sess.refresh_from_db()
        self.assertNotEqual(sess.status, 'closed')
        service.run_job(self._at(TODAY + dt.timedelta(days=1), 2))
        sess.refresh_from_db()
        self.assertEqual(sess.status, 'closed')
        self.assertEqual(DailyCountPick.objects.get(session=sess).status, 'missed')

    def test_close_at_24h_is_midnight(self):
        bs = BranchSettings.for_branch(self.branch)
        bs.is_24h = True
        bs.save()
        self.assertEqual(service.close_at(self.branch, TODAY), self._at(TODAY + dt.timedelta(days=1), 0))
