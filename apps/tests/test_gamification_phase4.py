"""
apps/tests/test_gamification_phase4.py — daily-count points, per-role points, branch
team challenges (التحفيز phase 4).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.gamification import challenges as T
from apps.gamification import engine, services
from apps.gamification import rewards as R
from apps.gamification.defaults import ensure_defaults
from apps.gamification.models import (DailyScore, GamificationChange, PlayerProfile, PointEvent,
                                      PointRule, TeamChallenge, TeamChallengeResult)
from apps.notifications.models import Notification
from apps.stockcount.models import DailyCountAttempt, DailyCountPick, StockCountSession
from apps.tests.factories import make_admin, make_branch, make_branch2, make_user


def _pts(staff, rule):
    return sum(PointEvent.objects.filter(staff=staff, rule_key=rule).values_list('points', flat=True))


def _daily_session(staff, branch, day, items, counted, status='closed'):
    s = StockCountSession.objects.create(name=f'daily {staff.id} {day}', mode='daily', status=status,
                                         branch_code=branch.softech_branch_id, count_date=day,
                                         assigned_to=staff, variance_at=timezone.now())
    for i in range(items):
        p = DailyCountPick.objects.create(session=s, item_code=f'I{i}', item_name=f'item {i}',
                                          status='counted' if i < counted else 'missed')
        if i < counted:
            a = DailyCountAttempt.objects.create(
                pick=p, counted_by=staff, counted_qty=Decimal('1'), expected_qty=Decimal('1'),
                expected_source='mirror', expected_read_at=timezone.now(), difference=Decimal('0'))
            p.latest_attempt = a
            p.save(update_fields=['latest_attempt'])
    return s


class DailyCountPointsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.b = make_branch()
        _, cls.s1, _ = make_user('p4_dc1', role='salesperson', branch=cls.b)

    def test_full_list_scores_items_and_completion(self):
        today = timezone.localdate()
        _daily_session(self.s1, self.b, today, items=5, counted=5)
        engine.score_day(today)
        self.assertEqual(_pts(self.s1, 'daily_count_item'), 5)
        self.assertEqual(_pts(self.s1, 'daily_count_complete'), 5)
        self.assertEqual(_pts(self.s1, 'daily_count_missed'), 0)

    def test_missed_items_penalised_capped_and_break_clean_day(self):
        today = timezone.localdate()
        _daily_session(self.s1, self.b, today, items=10, counted=2)   # 8 missed
        sc = engine.score_day(today)
        self.assertEqual(_pts(self.s1, 'daily_count_complete'), 0)
        self.assertEqual(_pts(self.s1, 'daily_count_missed'), -5)          # capped
        engine.finalize_day(today, sc, penalties=False)
        ds = DailyScore.objects.get(staff=self.s1, day=today)
        self.assertFalse(ds.clean_day)
        self.assertEqual(ds.left_behind, 5)                               # 5 penalty events kept

    def test_recount_does_not_score_twice(self):
        today = timezone.localdate()
        s = _daily_session(self.s1, self.b, today, items=1, counted=1)
        DailyCountAttempt.objects.create(
            pick=s.daily_picks.first(), counted_by=self.s1, counted_qty=Decimal('2'),
            expected_qty=Decimal('1'), expected_source='mirror', expected_read_at=timezone.now(),
            difference=Decimal('1'))
        engine.score_day(today)
        self.assertEqual(_pts(self.s1, 'daily_count_item'), 1)

    def test_open_item_listed(self):
        today = timezone.localdate()
        _daily_session(self.s1, self.b, today, items=3, counted=0, status='snapshot_taken')
        DailyCountPick.objects.filter(session__assigned_to=self.s1).update(status='pending')
        keys = {i['key']: i for i in services.open_items(self.s1)}
        self.assertEqual(keys['daily_count_open']['count'], 3)
        self.assertEqual(keys['daily_count_open']['route'], '/m/daily-count')


class RolePointsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.b = make_branch()
        _, cls.sales, _ = make_user('p4_rp_s', role='salesperson', branch=cls.b)
        _, cls.pharma, _ = make_user('p4_rp_p', role='pharmacist', branch=cls.b)
        _, cls.admin, cls.admin_c = make_admin('p4_rp_admin')

    def test_role_override_applies_only_to_that_role(self):
        PointRule.objects.filter(key='shortage_submitted').update(role_points={'pharmacist': 7})
        sc = engine.Scorer()
        sc.award(self.pharma, 'shortage_submitted', 'x1', timezone.now())
        sc.award(self.sales, 'shortage_submitted', 'x2', timezone.now())
        self.assertEqual(_pts(self.pharma, 'shortage_submitted'), 7)
        self.assertEqual(_pts(self.sales, 'shortage_submitted'), 3)

    def test_edit_role_points_via_api_validated_and_audited(self):
        url = '/api/gamification/rules/stockcount_completed/'
        self.assertEqual(self.admin_c.patch(url, {'role_points': {'nope': 3}}, format='json').status_code, 400)
        self.assertEqual(self.admin_c.patch(url, {'role_points': {'pharmacist': 5000}}, format='json').status_code, 400)
        r = self.admin_c.patch(url, {'role_points': {'pharmacist': 25}}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['role_points'], {'pharmacist': 25})
        self.assertTrue(GamificationChange.objects.filter(action='rule_edit', target='rule:stockcount_completed').exists())


class TeamChallengeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.b1, cls.b2 = make_branch(), make_branch2()
        mk = lambda n, b: make_user(n, role='salesperson', branch=b)[1]
        cls.a1, cls.a2 = mk('p4_tc_a1', cls.b1), mk('p4_tc_a2', cls.b1)
        cls.c1, cls.c2 = mk('p4_tc_c1', cls.b2), mk('p4_tc_c2', cls.b2)
        _, cls.admin, cls.admin_c = make_admin('p4_tc_admin')
        _, _, cls.staff_c = make_user('p4_tc_viewer', role='salesperson', branch=cls.b1)
        cls.end = timezone.localdate() - timedelta(days=1)
        cls.start = cls.end - timedelta(days=6)
        # b1: clean every day; b2: one day with left-behind items
        for s in (cls.a1, cls.a2, cls.c1, cls.c2):
            for i in range(7):
                d = cls.start + timedelta(days=i)
                bad = s.branch_id == cls.b2.id and i == 3
                DailyScore.objects.create(staff=s, day=d, branch_id=s.branch_id, finalized=True,
                                          clean_day=not bad, left_behind=3 if bad else 0)

    def _ch(self, metric='left_behind_max', target='0', **kw):
        return TeamChallenge.objects.create(name_ar='صفر تأخير', name_en='Zero overdue', metric=metric,
                                            target=Decimal(target), start=self.start, end=self.end,
                                            bonus_per_member=150, **kw)

    def test_left_behind_winner_gets_bonus_per_member(self):
        ch = self._ch()
        self.assertEqual(T.evaluate(ch), 1)
        r = {x.branch_id: x for x in TeamChallengeResult.objects.filter(challenge=ch)}
        self.assertTrue(r[self.b1.id].achieved)
        self.assertFalse(r[self.b2.id].achieved)
        self.assertEqual(r[self.b2.id].value, Decimal('6.00'))
        self.assertEqual(_pts(self.a1, 'team_challenge'), 150)
        self.assertEqual(_pts(self.c1, 'team_challenge'), 0)
        self.assertTrue(Notification.objects.filter(recipient=self.a1,
                                                    notification_type='gamification_team').exists())

    def test_evaluated_once(self):
        ch = self._ch()
        T.evaluate(ch)
        T.evaluate(ch)
        self.assertEqual(_pts(self.a1, 'team_challenge'), 150)
        self.assertEqual(TeamChallengeResult.objects.filter(challenge=ch).count(), 2)

    def test_clean_day_rate_and_scope(self):
        ch = self._ch(metric='clean_day_rate', target='95', branch_ids=[self.b2.id])
        T.evaluate(ch)
        self.assertEqual(TeamChallengeResult.objects.filter(challenge=ch).count(), 1)
        res = TeamChallengeResult.objects.get(challenge=ch)
        self.assertEqual(res.value, Decimal('85.71'))                       # 12/14
        self.assertFalse(res.achieved)

    def test_no_data_is_not_applicable_and_min_members(self):
        ch = self._ch(metric='fast_reply_rate', target='80')
        T.evaluate(ch)
        self.assertTrue(all(r.value is None and not r.achieved for r in ch.results.all()))
        ch2 = self._ch(min_members=5)
        T.evaluate(ch2)
        self.assertFalse(ch2.results.filter(achieved=True).exists())

    def test_bonus_counts_for_xp_wallet_not_ranking(self):
        ch = self._ch()
        T.evaluate(ch)
        p = PlayerProfile.objects.get(staff=self.a1)
        self.assertEqual(p.xp, 150)
        self.assertEqual(R.wallet(self.a1)['balance'], 150)
        today = timezone.localdate()
        self.assertFalse(services.ranking(today - timedelta(days=30), today))

    def test_running_challenge_cannot_be_evaluated_but_shows_progress(self):
        ch = TeamChallenge.objects.create(name_ar='جاري', name_en='Running', metric='left_behind_max',
                                          target=Decimal('0'), start=self.start,
                                          end=timezone.localdate() + timedelta(days=3))
        with self.assertRaises(ValueError):
            T.evaluate(ch)
        rows = T.standings(ch)
        self.assertEqual(rows[0]['branch_id'], self.b1.id)                  # lower is better
        self.assertFalse(rows[0]['final'])

    def test_evaluate_due_from_day_close(self):
        self._ch()
        self.assertEqual(T.evaluate_due(), 1)
        self.assertEqual(T.evaluate_due(), 0)

    def test_api_board_open_editing_gated(self):
        r = self.staff_c.get('/api/gamification/challenges/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['can_edit'])
        body = {'name_ar': 'تحدٍ', 'name_en': 'Challenge', 'metric': 'clean_day_rate', 'target': 90,
                'start': str(self.start), 'end': str(self.end), 'bonus_per_member': 100}
        self.assertEqual(self.staff_c.post('/api/gamification/challenges/', body, format='json').status_code, 403)
        self.assertEqual(self.admin_c.post('/api/gamification/challenges/', {**body, 'target': 150},
                                           format='json').status_code, 400)
        self.assertEqual(self.admin_c.post('/api/gamification/challenges/', {**body, 'end': '2000-01-01'},
                                           format='json').status_code, 400)
        r = self.admin_c.post('/api/gamification/challenges/', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        cid = r.json()['id']
        self.assertEqual(self.staff_c.post(f'/api/gamification/challenges/{cid}/evaluate/').status_code, 403)
        r = self.admin_c.post(f'/api/gamification/challenges/{cid}/evaluate/')
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.json()['evaluated_at'])
        self.assertEqual(self.admin_c.patch(f'/api/gamification/challenges/{cid}/', {'target': 50},
                                            format='json').status_code, 400)      # locked
        self.assertTrue(GamificationChange.objects.filter(action='challenge_create').exists())
