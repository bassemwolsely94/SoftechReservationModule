"""
apps/tests/test_gamification_champions.py — بطل الشهر (monthly champions).

Network top 3 per role + branch #1 per role (group ≥ MIN players) + branch of the month;
escalated audit flag and non-positive score are not eligible; a month is crowned once;
champion bonuses count for XP + wallet but never for rankings; revoke reverses the bonus
and drops badges that depended on the title; announcement + notifications; API gating.
"""
from datetime import datetime, time, timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.gamification import champions as C
from apps.gamification import engine, services
from apps.gamification import rewards as R
from apps.gamification.defaults import ensure_defaults
from apps.gamification.models import Champion, ChampionMonth, PlayerProfile, StaffBadge
from apps.notifications.models import Announcement, Notification
from apps.tests.factories import make_admin, make_branch, make_branch2, make_user

LAST = C.previous_month()


def _in_last_month(day=10):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(LAST.replace(day=day), time(12, 0)), tz)


def _give(staff, points, key, rule='manual_award'):
    engine.Scorer().award(staff, rule, key, _in_last_month(), points=points)


@override_settings(GAMIFICATION_CHAMPION_MIN_PLAYERS=2, GAMIFICATION_BRANCH_OF_MONTH_MIN_PLAYERS=2)
class CrownTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.b1, cls.b2 = make_branch(), make_branch2()
        mk = lambda n, role, b: make_user(n, role=role, branch=b)[1]
        cls.s1 = mk('ch_s1', 'salesperson', cls.b1)   # 900 — network #1, b1 champion
        cls.s2 = mk('ch_s2', 'salesperson', cls.b1)   # 400
        cls.s3 = mk('ch_s3', 'salesperson', cls.b2)   # 700 — network #2; alone in b2 → no b2 title
        cls.s4 = mk('ch_s4', 'salesperson', cls.b2)   # 1000 but escalated audit flag → excluded
        cls.p1 = mk('ch_p1', 'pharmacist', cls.b1)    # 300 — pharmacist network #1
        cls.p2 = mk('ch_p2', 'pharmacist', cls.b1)    # -5 → not eligible
        for s, pts in ((cls.s1, 900), (cls.s2, 400), (cls.s3, 700), (cls.s4, 1010), (cls.p1, 300)):
            _give(s, pts, f'seed-{s.id}')
        _give(cls.s4, -10, 'flag', rule='abuse_flag')
        _give(cls.p2, -5, 'neg')
        engine.refresh_players()

    def _crown(self):
        return C.crown(LAST)

    def test_network_podium_branch_champions_and_bonuses(self):
        cm, created = self._crown()
        self.assertTrue(created)
        net = {(c.role, c.rank): c.staff_id for c in Champion.objects.filter(kind='network')}
        self.assertEqual(net[('salesperson', 1)], self.s1.id)
        self.assertEqual(net[('salesperson', 2)], self.s3.id)
        self.assertEqual(net[('salesperson', 3)], self.s2.id)
        self.assertEqual(net[('pharmacist', 1)], self.p1.id)
        self.assertNotIn(self.s4.id, net.values())                  # audit flag
        self.assertNotIn(self.p2.id, net.values())                  # non-positive
        branch = {(c.branch_id, c.role): c.staff_id for c in Champion.objects.filter(kind='branch')}
        self.assertEqual(branch[(self.b1.id, 'salesperson')], self.s1.id)
        self.assertEqual(branch[(self.b1.id, 'pharmacist')], self.p1.id)
        # b2 salespeople: s3 + s4 are 2 players, s4 excluded → s3 is champion of b2
        self.assertEqual(branch[(self.b2.id, 'salesperson')], self.s3.id)
        s1 = {c.kind: c.bonus for c in Champion.objects.filter(staff=self.s1)}
        self.assertEqual(s1, {'network': 500, 'branch': 200})
        self.assertEqual(Champion.objects.get(staff=self.s3, kind='network').bonus, 200)
        self.assertTrue(Champion.objects.filter(kind='branch_of_month').exists())

    def test_crowned_once(self):
        self._crown()
        n = Champion.objects.count()
        cm, created = self._crown()
        self.assertFalse(created)
        self.assertEqual(Champion.objects.count(), n)
        self.assertEqual(ChampionMonth.objects.count(), 1)

    def test_bonus_counts_for_xp_and_wallet_not_ranking(self):
        before = PlayerProfile.objects.get(staff=self.s1).xp
        self._crown()
        p = PlayerProfile.objects.get(staff=self.s1)
        self.assertEqual(p.xp, before + 700)
        self.assertEqual(R.wallet(self.s1)['balance'], 900 + 700)
        today = timezone.localdate()
        this_month = services.ranking(today.replace(day=1), today)
        self.assertFalse(any(r['staff_id'] == self.s1.id for r in this_month))   # bonus ≠ ranking point
        self.assertTrue(StaffBadge.objects.filter(staff=self.s1, badge__key='champ_branch_1').exists())

    def test_announcement_and_notifications(self):
        cm, _ = self._crown()
        self.assertIsNotNone(cm.announcement_id)
        ann = Announcement.objects.get(pk=cm.announcement_id)
        self.assertTrue(ann.is_pinned)
        self.assertIn('🥇', ann.body)
        self.assertTrue(Notification.objects.filter(recipient=self.s1,
                                                    notification_type='gamification_champion').exists())

    def test_revoke_reverses_bonus_and_badge(self):
        self._crown()
        _, admin, _ = make_admin('ch_admin')
        before = PlayerProfile.objects.get(staff=self.s1).xp
        for c in Champion.objects.filter(staff=self.s1):
            C.revoke(c, admin, 'تلاعب مؤكد بعد المراجعة')
        p = PlayerProfile.objects.get(staff=self.s1)
        self.assertEqual(p.xp, before - 700)
        self.assertEqual(R.wallet(self.s1)['balance'], 900)
        self.assertFalse(StaffBadge.objects.filter(staff=self.s1, badge__key='champ_branch_1').exists())
        with self.assertRaises(ValueError):
            C.revoke(Champion.objects.filter(staff=self.s1).first(), admin, 'مرة أخرى')

    def test_admin_never_competes(self):
        _, admin, _ = make_admin('ch_admin_player')
        _give(admin, 5000, 'adm-big')
        self._crown()
        self.assertFalse(Champion.objects.filter(staff=admin).exists())
        self.assertNotIn('admin', C.race(self.s1)['network'])

    def test_cannot_crown_running_month(self):
        with self.assertRaises(ValueError):
            C.crown(timezone.localdate())

    def test_race_and_board(self):
        self._crown()
        b = C.board()
        self.assertEqual(b['month'], LAST)
        self.assertTrue(b['champions'])
        r = C.race(self.s1)
        self.assertIn('network', r)
        self.assertGreaterEqual(r['days_left'], 0)


class ChampionApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.b1 = make_branch()
        _, cls.s1, cls.s1_c = make_user('cha_s1', role='salesperson', branch=cls.b1)
        _, cls.s2, _ = make_user('cha_s2', role='salesperson', branch=cls.b1)
        _, cls.admin, cls.admin_c = make_admin('cha_admin')
        _give(cls.s1, 500, 'a')
        _give(cls.s2, 100, 'b')

    def test_board_open_crown_and_revoke_gated(self):
        r = self.s1_c.get('/api/gamification/champions/')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()['can_edit'])
        self.assertEqual(self.s1_c.post('/api/gamification/champions/crown/').status_code, 403)
        r = self.admin_c.post('/api/gamification/champions/crown/', {'month': f'{LAST:%Y-%m}'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.admin_c.post('/api/gamification/champions/crown/',
                                           {'month': f'{LAST:%Y-%m}'}).status_code, 200)
        cid = Champion.objects.filter(staff=self.s1).first().id
        self.assertEqual(self.s1_c.post(f'/api/gamification/champions/{cid}/revoke/',
                                        {'reason': 'سبب كافٍ'}).status_code, 403)
        self.assertEqual(self.admin_c.post(f'/api/gamification/champions/{cid}/revoke/',
                                           {'reason': ''}).status_code, 400)
        self.assertEqual(self.admin_c.post(f'/api/gamification/champions/{cid}/revoke/',
                                           {'reason': 'سبب مكتوب'}).status_code, 200)

    def test_titles_in_me_and_running_month_refused(self):
        C.crown(LAST)
        me = self.s1_c.get('/api/gamification/me/').json()
        self.assertTrue(any(t['kind'] == 'branch' for t in me['titles']))
        today = timezone.localdate()
        r = self.admin_c.post('/api/gamification/champions/crown/', {'month': f'{today:%Y-%m}'})
        self.assertEqual(r.status_code, 400)

    def test_report_lists_champions(self):
        C.crown(LAST)
        r = self.admin_c.get('/api/gamification/reports/overview/',
                             {'from': f'{LAST:%Y-%m-%d}', 'to': f'{timezone.localdate():%Y-%m-%d}'})
        self.assertTrue(r.json()['champions'])
