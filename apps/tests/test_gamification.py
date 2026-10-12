"""
apps/tests/test_gamification.py — التحفيز (points, levels, badges, rankings).

Covers: sales scoring (count + capped value + profit with the cash multiplier), the
ledger never double-counts on re-run, daily caps, penalties at day close, clean day +
streak, levels never drop, badges, promotions → notification, and the API permission
spine (own data open, reports/config gated by RBAC module `gamification`).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
from apps.gamification import engine
from apps.gamification.defaults import ensure_defaults
from apps.gamification.models import (GamificationChange, Level, LevelHistory, PlayerProfile,
                                      PointEvent, PointRule, StaffBadge)
from apps.notifications.models import Notification
from apps.reservations.models import Reservation
from apps.tasks.models import OperationalTask
from apps.tests.factories import (make_admin, make_branch, make_branch2, make_customer,
                                  make_user)
from apps.transfers.models import TransferRequest


def _sale(staff_code, branch, n, amount='100', doc='115', channel='', gp=None, when=None):
    when = when or timezone.now()
    ph = PurchaseHistory.objects.create(
        customer=make_customer(), softech_invoice_id=f'INV-{doc}-{staff_code}-{n}',
        branch=branch, doc_code=doc, total_amount=Decimal(amount), invoice_date=when,
        softech_user=staff_code, sales_channel=channel)
    if gp is not None:
        PurchaseHistoryLine.objects.create(
            purchase=ph, quantity=Decimal('1'), unit_price=Decimal(amount),
            line_total=Decimal(amount), cost_at_sale=Decimal(amount) - Decimal(gp))
    return ph


def _points(staff, rule=None):
    qs = PointEvent.objects.filter(staff=staff)
    if rule:
        qs = qs.filter(rule_key=rule)
    return sum(qs.values_list('points', flat=True))


class EngineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.branch2 = make_branch2()
        _, cls.sales, _ = make_user('gam_sales', role='salesperson', branch=cls.branch)
        cls.sales.softech_user_id = '501'
        cls.sales.save()
        _, cls.pharma, _ = make_user('gam_pharma', role='pharmacist', branch=cls.branch2)
        ensure_defaults()

    def setUp(self):
        self.today = timezone.localdate()

    def test_sales_count_value_profit_and_idempotent(self):
        # 3 invoices of 600 EGP (1 cash), GP 150 each → invoices 3×2, value floor(1800/500)=3,
        # profit (150 + 150 + 150×1.5)/100 = 5.25 → 5
        _sale('501', self.branch, 1, '600', gp='150')
        _sale('501', self.branch, 2, '600', gp='150')
        _sale('501', self.branch, 3, '600', channel='91', gp='150')
        engine.run(days=0, finalize=False)
        self.assertEqual(_points(self.sales, 'sale_invoice'), 6)
        self.assertEqual(_points(self.sales, 'sale_value'), 3)
        self.assertEqual(_points(self.sales, 'sale_profit'), 5)
        before = PointEvent.objects.count()
        engine.run(days=0, finalize=False)                      # re-run: nothing new
        self.assertEqual(PointEvent.objects.count(), before)

    def test_daily_aggregate_tops_up_as_the_day_goes_on(self):
        _sale('501', self.branch, 1, '1000')
        engine.run(days=0, finalize=False)
        self.assertEqual(_points(self.sales, 'sale_value'), 2)
        _sale('501', self.branch, 2, '1000')
        engine.run(days=0, finalize=False)
        self.assertEqual(_points(self.sales, 'sale_value'), 4)  # only the difference added

    def test_daily_cap(self):
        PointRule.objects.filter(key='sale_invoice').update(daily_cap=5)
        for i in range(6):
            _sale('501', self.branch, i)
        engine.run(days=0, finalize=False)
        self.assertEqual(_points(self.sales, 'sale_invoice'), 5)

    def test_returns_reduce_value_but_score_the_work(self):
        _sale('501', self.branch, 1, '1000')
        _sale('501', self.branch, 2, '600', doc='30')
        engine.run(days=0, finalize=False)
        self.assertEqual(_points(self.sales, 'return_processed'), 1)
        self.assertEqual(_points(self.sales, 'sale_value'), 0)  # net 400 < 500

    def test_inactive_rule_and_role_filter(self):
        PointRule.objects.filter(key='sale_invoice').update(roles=['pharmacist'])
        _sale('501', self.branch, 1)
        engine.run(days=0, finalize=False)
        self.assertEqual(_points(self.sales, 'sale_invoice'), 0)

    def test_reservation_overdue_penalty_breaks_clean_day(self):
        Reservation.objects.create(branch=self.branch, assigned_to=self.sales,
                                   created_by=self.sales, status='pending',
                                   follow_up_date=self.today - timedelta(days=2))
        engine.score_day(self.today)
        sc = engine.finalize_day(self.today)
        self.assertEqual(_points(self.sales, 'reservation_created'), 2)
        self.assertEqual(_points(self.sales, 'reservation_overdue'), -2)
        self.assertEqual(_points(self.sales, 'clean_day'), 0)
        engine.finalize_day(self.today, sc)                    # re-run: no second penalty
        self.assertEqual(_points(self.sales, 'reservation_overdue'), -2)
        self.assertEqual(PlayerProfile.objects.get(staff=self.sales).current_streak, 0)

    def test_clean_days_build_a_streak_and_weekly_bonus(self):
        start = self.today - timedelta(days=7)
        for i in range(7):
            day = start + timedelta(days=i)
            at = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time())) \
                + timedelta(hours=10)
            _sale('501', self.branch, 100 + i, when=at)
            sc = engine.score_day(day)
            engine.finalize_day(day, sc, penalties=False)
        p = PlayerProfile.objects.get(staff=self.sales)
        self.assertEqual(p.current_streak, 7)
        self.assertEqual(p.best_streak, 7)
        self.assertEqual(_points(self.sales, 'clean_day'), 70)
        self.assertEqual(_points(self.sales, 'streak_week'), 25)

    def test_branch_request_answered_fast(self):
        now = timezone.now()
        TransferRequest.objects.create(requesting_branch=self.branch,
                                       supplying_branch=self.branch2, status='approved',
                                       created_by=self.sales, reviewed_by=self.pharma,
                                       submitted_at=now - timedelta(minutes=30), reviewed_at=now)
        engine.run(days=0, finalize=False)
        self.assertEqual(_points(self.pharma, 'transfer_request_answered'), 4)
        self.assertEqual(_points(self.pharma, 'transfer_request_fast'), 4)
        self.assertEqual(_points(self.sales, 'transfer_request_created'), 2)

    def test_task_on_time_vs_late(self):
        now = timezone.now()
        OperationalTask.objects.create(title='a', status='completed', assigned_to=self.pharma,
                                       completed_by=self.pharma, completed_at=now,
                                       due_date=now + timedelta(hours=1), created_by=self.pharma)
        OperationalTask.objects.create(title='b', status='completed', assigned_to=self.pharma,
                                       completed_by=self.pharma, completed_at=now,
                                       due_date=now - timedelta(hours=1), created_by=self.pharma)
        engine.run(days=0, finalize=False)
        self.assertEqual(_points(self.pharma, 'task_on_time'), 5)
        self.assertEqual(_points(self.pharma, 'task_late'), 2)

    def test_levels_never_drop_promotion_notifies_and_badges(self):
        lv2 = Level.objects.get(number=2)
        sc = engine.Scorer()
        sc.award(self.sales, 'manual_award', 'test:1', timezone.now(), points=lv2.min_xp)
        _sale('501', self.branch, 1)
        engine.run(days=0, finalize=False)
        p = PlayerProfile.objects.get(staff=self.sales)
        self.assertEqual(p.level.number, 2)
        self.assertTrue(LevelHistory.objects.filter(staff=self.sales, level=lv2).exists())
        self.assertTrue(Notification.objects.filter(
            recipient=self.sales, notification_type='gamification_level_up').exists())
        self.assertTrue(StaffBadge.objects.filter(staff=self.sales,
                                                  badge__key='first_sale').exists())
        # a big penalty lowers net points but never the level
        sc.award(self.sales, 'manual_award', 'test:2', timezone.now(), points=-500)
        engine.refresh_players([self.sales.id])
        p.refresh_from_db()
        self.assertEqual(p.level.number, 2)
        self.assertLess(p.net_points, p.xp)

    def test_defaults_do_not_overwrite_admin_edits(self):
        PointRule.objects.filter(key='sale_invoice').update(points=7)
        ensure_defaults()
        self.assertEqual(PointRule.objects.get(key='sale_invoice').points, 7)
        ensure_defaults(reset=True)
        self.assertEqual(PointRule.objects.get(key='sale_invoice').points, 2)


class ApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        cls.branch2 = make_branch2()
        _, cls.sales, cls.sales_c = make_user('gapi_sales', role='salesperson', branch=cls.branch)
        _, cls.mate, _ = make_user('gapi_mate', role='salesperson', branch=cls.branch)
        _, cls.admin, cls.admin_c = make_admin('gapi_admin')
        ensure_defaults()
        sc = engine.Scorer()
        now = timezone.now()
        sc.award(cls.sales, 'manual_award', 's', now, points=50)
        sc.award(cls.mate, 'manual_award', 'm', now, points=80)
        others = []
        for i in range(12):
            _, p, _ = make_user(f'gapi_net{i}', role='salesperson', branch=cls.branch2)
            sc.award(p, 'manual_award', f'n{i}', now, points=100 + i)
            others.append(p)
        engine.refresh_players()

    def test_me(self):
        r = self.sales_c.get('/api/gamification/me/')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['points']['day'], 50)
        self.assertEqual(d['rank']['branch']['rank'], 2)
        self.assertFalse(d['can_manage'])
        self.assertIn('open_items', d)
        self.assertTrue(d['level']['current']['title_ar'])

    def test_branch_leaderboard_is_own_branch_only(self):
        r = self.sales_c.get('/api/gamification/leaderboard/?scope=branch&branch=%d' % self.branch2.id)
        names = {row['staff_id'] for row in r.json()['rows']}
        self.assertEqual(names, {self.sales.id, self.mate.id})   # ignored foreign branch param

    def test_network_top_10_for_staff_full_for_managers(self):
        r = self.sales_c.get('/api/gamification/leaderboard/?scope=network')
        self.assertEqual(len(r.json()['rows']), 10)
        self.assertTrue(r.json()['limited'])
        self.assertEqual(r.json()['me']['rank'], 14)
        r = self.admin_c.get('/api/gamification/leaderboard/?scope=network')
        self.assertEqual(len(r.json()['rows']), 14)

    def test_reports_gated(self):
        self.assertEqual(self.sales_c.get('/api/gamification/reports/overview/').status_code, 403)
        self.assertEqual(self.sales_c.get('/api/gamification/reports/export/').status_code, 403)
        r = self.admin_c.get('/api/gamification/reports/overview/?period=month')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['kpis']['players'], 14)
        r = self.admin_c.get('/api/gamification/reports/export/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])

    def test_supervisor_grant_via_rbac(self):
        from apps.users.models import RoleModuleAccess
        _, _, sup_c = make_user('gapi_sup', role='supervisor', branch=self.branch)
        self.assertEqual(sup_c.get('/api/gamification/reports/overview/').status_code, 403)
        RoleModuleAccess.objects.create(role='supervisor', module='gamification', action='view',
                                        is_allowed=True)
        self.assertEqual(sup_c.get('/api/gamification/reports/overview/').status_code, 200)

    def test_rule_edit_audited_and_gated(self):
        r = self.sales_c.patch('/api/gamification/rules/sale_invoice/', {'points': 9}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.admin_c.patch('/api/gamification/rules/sale_invoice/',
                               {'points': 3, 'reason': 'test'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(PointRule.objects.get(key='sale_invoice').points, 3)
        c = GamificationChange.objects.get(action='rule_edit')
        self.assertEqual(c.before['points'], 2)
        self.assertEqual(c.after['points'], 3)
        r = self.admin_c.patch('/api/gamification/rules/sale_invoice/', {'roles': ['nope']},
                               format='json')
        self.assertEqual(r.status_code, 400)

    def test_level_threshold_must_stay_ordered(self):
        r = self.admin_c.patch('/api/gamification/levels/3/', {'min_xp': 10}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.admin_c.patch('/api/gamification/levels/3/', {'title_ar': 'ماهر'}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_manual_adjust_rules(self):
        url = '/api/gamification/adjust/'
        self.assertEqual(self.sales_c.post(url, {'staff_id': self.mate.id, 'points': 5,
                                                 'reason': 'شكراً'}).status_code, 403)
        self.assertEqual(self.admin_c.post(url, {'staff_id': self.mate.id, 'points': 5,
                                                 'reason': ''}).status_code, 400)
        self.assertEqual(self.admin_c.post(url, {'staff_id': self.admin.id, 'points': 5,
                                                 'reason': 'نفسي نفسي'}).status_code, 400)
        self.assertEqual(self.admin_c.post(url, {'staff_id': self.mate.id, 'points': 9999,
                                                 'reason': 'كثير جداً'}).status_code, 400)
        r = self.admin_c.post(url, {'staff_id': self.mate.id, 'points': 20,
                                    'reason': 'مساعدة فرع آخر'})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(GamificationChange.objects.filter(action='manual_award').exists())

    def test_rules_and_badges_open_to_everyone(self):
        self.assertEqual(self.sales_c.get('/api/gamification/rules/').status_code, 200)
        self.assertEqual(self.sales_c.get('/api/gamification/levels/').status_code, 200)
        r = self.sales_c.get('/api/gamification/badges/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(len(r.json()) > 0)

    def test_anonymous_rejected(self):
        from rest_framework.test import APIClient
        self.assertIn(APIClient().get('/api/gamification/me/').status_code, (401, 403))
