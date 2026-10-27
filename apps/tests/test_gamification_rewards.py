"""
apps/tests/test_gamification_rewards.py — reward catalog (التحفيز phase 2).

Wallet = lifetime net points − pending/approved/fulfilled redemptions; redeeming never
changes XP/level/ranking. Requests ride apps.approvals; the outcome hook approves,
refunds on reject, and refuses self-approval. Stock, monthly limit, min level, cancel,
fulfil, reconcile and the API permission spine.
"""
from django.test import TestCase
from django.utils import timezone

from apps.approvals.models import ApprovalDecision, ApprovalRequest
from apps.approvals.service import ApprovalService
from apps.gamification import engine
from apps.gamification import rewards as R
from apps.gamification.defaults import ensure_defaults, ensure_rewards
from apps.gamification.models import GamificationChange, PlayerProfile, Redemption, Reward
from apps.tests.factories import make_admin, make_branch, make_user


def _give(staff, points, key):
    engine.Scorer().award(staff, 'manual_award', key, timezone.now(), points=points)
    engine.refresh_players([staff.id])


class RewardFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        _, cls.sales, cls.sales_c = make_user('rw_sales', role='salesperson', branch=cls.branch)
        _, cls.sup, cls.sup_c = make_user('rw_sup', role='supervisor', branch=cls.branch)
        _, cls.admin, cls.admin_c = make_admin('rw_admin')
        ensure_defaults()
        cls.reward = Reward.objects.create(name_ar='شهادة', name_en='Certificate', cost=300,
                                           stock=2, limit_per_month=2)

    def setUp(self):
        _give(self.sales, 1000, f'seed-{self._testMethodName}')

    def _approve_all(self, x, by=None):
        ar = ApprovalRequest.objects.get(pk=x.approval_request_id)
        for who in (by or [self.sup, self.admin]):
            ar.refresh_from_db()
            if ar.is_terminal:
                break
            ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED,
                                   decided_by=who, notes='موافق')
        x.refresh_from_db()
        return x

    def test_request_holds_points_and_stock_then_approve(self):
        x = R.request_reward(self.sales, self.reward.id, 'شكراً')
        self.assertEqual(x.status, 'pending')
        self.assertIsNotNone(x.approval_request_id)
        w = R.wallet(self.sales)
        self.assertEqual((w['balance'], w['held']), (700, 300))
        self.reward.refresh_from_db()
        self.assertEqual(self.reward.stock, 1)
        x = self._approve_all(x)
        self.assertEqual(x.status, 'approved')
        w = R.wallet(self.sales)
        self.assertEqual((w['balance'], w['spent'], w['held']), (700, 300, 0))

    def test_redeeming_never_changes_level_or_xp(self):
        p = PlayerProfile.objects.get(staff=self.sales)
        xp, level = p.xp, p.level_id
        self._approve_all(R.request_reward(self.sales, self.reward.id))
        engine.refresh_players([self.sales.id])
        p.refresh_from_db()
        self.assertEqual((p.xp, p.level_id), (xp, level))

    def test_reject_refunds_points_and_stock(self):
        x = R.request_reward(self.sales, self.reward.id)
        ApprovalService.decide(request=x.approval_request,
                               decision=ApprovalDecision.DECISION_REJECTED,
                               decided_by=self.sup, notes='ليس الآن')
        x.refresh_from_db()
        self.assertEqual(x.status, 'rejected')
        self.assertEqual(x.decision_note, 'ليس الآن')
        self.assertEqual(R.wallet(self.sales)['balance'], 1000)
        self.reward.refresh_from_db()
        self.assertEqual(self.reward.stock, 2)

    def test_self_approval_refused(self):
        _give(self.admin, 1000, 'adm')
        x = R.request_reward(self.admin, self.reward.id)
        x = self._approve_all(x, by=[self.sup, self.admin])
        self.assertEqual(x.status, 'rejected')
        self.assertIn('self-approval', x.decision_note)
        self.assertEqual(R.wallet(self.admin)['balance'], 1000)

    def test_not_enough_points(self):
        big = Reward.objects.create(name_ar='كبيرة', name_en='Big', cost=5000)
        with self.assertRaises(R.RewardError):
            R.request_reward(self.sales, big.id)
        self.assertFalse(Redemption.objects.filter(reward=big).exists())

    def test_balance_cannot_be_spent_twice(self):
        mid = Reward.objects.create(name_ar='متوسطة', name_en='Mid', cost=600)
        R.request_reward(self.sales, mid.id)
        with self.assertRaises(R.RewardError):      # 400 left < 600
            R.request_reward(self.sales, mid.id)

    def test_stock_monthly_limit_and_min_level(self):
        R.request_reward(self.sales, self.reward.id)
        R.request_reward(self.sales, self.reward.id)
        with self.assertRaises(R.RewardError):      # stock 0 and monthly limit 2
            R.request_reward(self.sales, self.reward.id)
        lvl = Reward.objects.create(name_ar='مستوى', name_en='Lvl', cost=10, min_level=9)
        with self.assertRaises(R.RewardError):
            R.request_reward(self.sales, lvl.id)
        role = Reward.objects.create(name_ar='دور', name_en='Role', cost=10, roles=['delivery'])
        with self.assertRaises(R.RewardError):
            R.request_reward(self.sales, role.id)

    def test_no_approval_reward_is_approved_immediately(self):
        r = Reward.objects.create(name_ar='فورية', name_en='Instant', cost=100,
                                  requires_approval=False)
        x = R.request_reward(self.sales, r.id)
        self.assertEqual(x.status, 'approved')
        self.assertIsNone(x.approval_request_id)

    def test_owner_cancels_pending_and_gets_points_back(self):
        x = R.request_reward(self.sales, self.reward.id)
        R.cancel(x, self.sales)
        x.refresh_from_db()
        self.assertEqual(x.status, 'cancelled')
        self.assertEqual(x.approval_request.status, 'cancelled')
        self.assertEqual(R.wallet(self.sales)['balance'], 1000)
        approved = self._approve_all(R.request_reward(self.sales, self.reward.id))
        with self.assertRaises(R.RewardError):      # owner cannot cancel after approval
            R.cancel(approved, self.sales)

    def test_fulfil_only_approved_and_not_by_owner(self):
        x = R.request_reward(self.sales, self.reward.id)
        with self.assertRaises(R.RewardError):
            R.fulfil(x, self.admin)
        x = self._approve_all(x)
        with self.assertRaises(R.RewardError):
            R.fulfil(x, self.sales)
        x = R.fulfil(x, self.admin, 'سُلّمت في اجتماع الفرع')
        self.assertEqual(x.status, 'fulfilled')
        self.assertEqual(R.wallet(self.sales)['spent'], 300)

    def test_reconcile_refunds_expired_approval(self):
        x = R.request_reward(self.sales, self.reward.id)
        ApprovalRequest.objects.filter(pk=x.approval_request_id).update(status='expired')
        self.assertEqual(R.reconcile(), 1)
        x.refresh_from_db()
        self.assertEqual(x.status, 'cancelled')
        self.assertEqual(R.wallet(self.sales)['balance'], 1000)


class RewardApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = make_branch()
        _, cls.sales, cls.sales_c = make_user('rwa_sales', role='salesperson', branch=cls.branch)
        _, cls.admin, cls.admin_c = make_admin('rwa_admin')
        ensure_defaults()
        ensure_rewards()
        _give(cls.sales, 2000, 'api-seed')

    def test_catalog_seeded_with_money_rewards_off(self):
        r = self.sales_c.get('/api/gamification/rewards/')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['wallet']['balance'], 2000)
        self.assertTrue(d['rewards'])
        self.assertTrue(Reward.objects.filter(category='time_off', is_active=False).exists())
        self.assertFalse(any(x['category'] == 'time_off' for x in d['rewards']))

    def test_request_and_wallet_and_cancel(self):
        rid = Reward.objects.filter(is_active=True, min_level=1).order_by('cost').first().id
        r = self.sales_c.post('/api/gamification/redemptions/', {'reward_id': rid, 'note': 'x'})
        self.assertEqual(r.status_code, 201, r.content)
        xid = r.json()['id']
        w = self.sales_c.get('/api/gamification/wallet/').json()
        self.assertEqual(len(w['redemptions']), 1)
        self.assertLess(w['wallet']['balance'], 2000)
        self.assertEqual(self.sales_c.post(f'/api/gamification/redemptions/{xid}/cancel/').status_code, 200)
        self.assertEqual(self.sales_c.get('/api/gamification/me/').json()['wallet']['balance'], 2000)

    def test_bad_request_is_400(self):
        r = self.sales_c.post('/api/gamification/redemptions/', {'reward_id': 999999})
        self.assertEqual(r.status_code, 400)

    def test_manager_endpoints_gated(self):
        self.assertEqual(self.sales_c.get('/api/gamification/redemptions/').status_code, 403)
        self.assertEqual(self.sales_c.post('/api/gamification/rewards/',
                                           {'name_ar': 'أ', 'name_en': 'a', 'cost': 5}).status_code, 403)
        self.assertEqual(self.admin_c.get('/api/gamification/redemptions/').status_code, 200)

    def test_admin_creates_and_edits_reward_audited(self):
        r = self.admin_c.post('/api/gamification/rewards/',
                              {'name_ar': 'تذكرة سينما', 'name_en': 'Cinema ticket', 'cost': 700,
                               'category': 'voucher', 'stock': 10}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        pk = r.json()['id']
        r = self.admin_c.patch(f'/api/gamification/rewards/{pk}/', {'cost': 0}, format='json')
        self.assertEqual(r.status_code, 400)
        r = self.admin_c.patch(f'/api/gamification/rewards/{pk}/', {'cost': 650, 'stock': None},
                               format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(Reward.objects.get(pk=pk).stock)
        self.assertTrue(GamificationChange.objects.filter(action='reward_edit').exists())

    def test_fulfil_via_api_and_other_staff_cannot_cancel(self):
        r = Reward.objects.create(name_ar='فورية', name_en='Instant', cost=100,
                                  requires_approval=False)
        x = R.request_reward(self.sales, r.id)
        _, other, other_c = make_user('rwa_other', role='salesperson', branch=self.branch)
        self.assertEqual(other_c.post(f'/api/gamification/redemptions/{x.id}/cancel/').status_code, 403)
        self.assertEqual(self.sales_c.post(f'/api/gamification/redemptions/{x.id}/fulfil/').status_code, 403)
        res = self.admin_c.post(f'/api/gamification/redemptions/{x.id}/fulfil/', {'note': 'تم'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['status'], 'fulfilled')

    def test_report_includes_rewards(self):
        r = Reward.objects.create(name_ar='فورية', name_en='Instant', cost=100,
                                  requires_approval=False)
        R.request_reward(self.sales, r.id)
        d = self.admin_c.get('/api/gamification/reports/overview/').json()
        self.assertEqual(d['rewards']['points_redeemed'], 100)
        self.assertEqual(d['rewards']['awaiting_fulfilment'], 1)
        self.assertEqual(self.admin_c.get('/api/gamification/reports/export/').status_code, 200)
