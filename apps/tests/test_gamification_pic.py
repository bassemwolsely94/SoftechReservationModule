"""
apps/tests/test_gamification_pic.py — customer-code (PIC) gamification.

New PIC (doc 33 rule: first purchase ever + created by SOFTECH within 30 days; credited to
the day's first invoice), won-back PIC (365+ days away), customers served on their code
(distinct per day), the customer-code day (judged at day close), excluded PICs, and the
anti-gaming guards (phone, person, positive first sale). Plus the «عملائي» panel, the team
challenge metrics and the report block.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.customers.models import Customer, PurchaseHistory
from apps.gamification import challenges as T
from apps.gamification import engine, services
from apps.gamification.defaults import ensure_defaults
from apps.gamification.models import PointEvent, StaffBadge, TeamChallenge
from apps.pic_analytics.models import PicExclusion
from apps.tests.factories import make_admin, make_branch, make_user

N = [0]


def _at(day, hour=10, minute=0):
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(day, time(hour, minute)), tz)


def _cust(pic, created=None, phone='01000000001', **kw):
    return Customer.objects.create(name=f'عميل {pic}', phone=phone, softech_pic=pic,
                                   softech_created_at=created, **kw)


def _sale(user, branch, pic, when, amount='100', doc='115'):
    N[0] += 1
    cust = Customer.objects.filter(softech_pic=pic).first() if pic else None
    cust = cust or Customer.objects.get_or_create(phone='walkin', defaults={'name': 'walk-in'})[0]
    return PurchaseHistory.objects.create(
        customer=cust, softech_invoice_id=f'PICT-{N[0]}', branch=branch, doc_code=doc,
        total_amount=Decimal(amount), invoice_date=when.replace(hour=0, minute=0),
        trans_time=when, softech_user=user, softech_phcode=pic or '')


def _pts(staff, rule):
    return sum(PointEvent.objects.filter(staff=staff, rule_key=rule).values_list('points', flat=True))


def _n(staff, rule):
    return PointEvent.objects.filter(staff=staff, rule_key=rule).count()


class PicScoringTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.b = make_branch()
        _, cls.a, _ = make_user('pic_a', role='salesperson', branch=cls.b)
        _, cls.c, _ = make_user('pic_c', role='salesperson', branch=cls.b)
        cls.a.softech_user_id, cls.c.softech_user_id = '701', '702'
        cls.a.save()
        cls.c.save()

    def setUp(self):
        self.today = timezone.localdate()

    def test_new_pic_credited_to_first_invoice_of_the_day(self):
        _cust('01HD1', created=self.today)
        _sale('702', self.b, '01HD1', _at(self.today, 9))          # first
        _sale('701', self.b, '01HD1', _at(self.today, 11))
        engine.score_day(self.today)
        self.assertEqual(_pts(self.c, 'pic_new'), 10)
        self.assertEqual(_pts(self.a, 'pic_new'), 0)
        # both served the customer on their code
        self.assertEqual(_n(self.a, 'pic_visit'), 1)
        self.assertEqual(_n(self.c, 'pic_visit'), 1)

    def test_old_customer_without_history_is_not_new(self):
        _cust('01HD2', created=self.today - timedelta(days=400))   # custdate long ago
        _sale('701', self.b, '01HD2', _at(self.today))
        engine.score_day(self.today)
        self.assertEqual(_pts(self.a, 'pic_new'), 0)

    def test_guards_phone_person_positive_sale(self):
        _cust('01HD3', created=self.today, phone='')                 # no phone
        _cust('01HD4', created=self.today, is_account_placeholder=True, phone='0100000004')
        _cust('01HD5', created=self.today, merged_into_pic='01HD9', phone='0100000005')
        _cust('01HD6', created=self.today, phone='0100000006')
        for pic in ('01HD3', '01HD4', '01HD5'):
            _sale('701', self.b, pic, _at(self.today))
        _sale('701', self.b, '01HD6', _at(self.today), amount='0')   # zero first sale
        engine.score_day(self.today)
        self.assertEqual(_pts(self.a, 'pic_new'), 0)

    def test_previous_purchase_means_not_new_and_year_away_is_won_back(self):
        _cust('01HD7', created=self.today - timedelta(days=500))
        _sale('701', self.b, '01HD7', _at(self.today - timedelta(days=400)))
        _cust('01HD8', created=self.today - timedelta(days=500), phone='0100000008')
        _sale('701', self.b, '01HD8', _at(self.today - timedelta(days=20)))
        _sale('701', self.b, '01HD7', _at(self.today))
        _sale('701', self.b, '01HD8', _at(self.today))
        engine.score_day(self.today)
        self.assertEqual(_pts(self.a, 'pic_new'), 0)
        self.assertEqual(_pts(self.a, 'pic_reactivated'), 8)          # only 01HD7

    def test_same_customer_many_invoices_is_one_visit_and_rerun_safe(self):
        _cust('01HD10', created=self.today - timedelta(days=200))
        _sale('701', self.b, '01HD10', _at(self.today - timedelta(days=30)))
        for h in (9, 10, 11):
            _sale('701', self.b, '01HD10', _at(self.today, h))
        engine.score_day(self.today)
        engine.score_day(self.today)
        self.assertEqual(_pts(self.a, 'pic_visit'), 1)

    def test_excluded_pic_never_counts(self):
        _cust('01HD11', created=self.today)
        PicExclusion.objects.create(pic='01HD11', reason='كود مشترك للفرع')
        _sale('701', self.b, '01HD11', _at(self.today))
        engine.score_day(self.today)
        self.assertEqual(_pts(self.a, 'pic_new') + _pts(self.a, 'pic_visit'), 0)

    @override_settings(GAMIFICATION_PIC_CAPTURE_PCT=70, GAMIFICATION_PIC_CAPTURE_MIN_INVOICES=10)
    def test_capture_day_judged_at_close_only(self):
        _cust('01HD12', created=self.today - timedelta(days=100))
        for i in range(8):
            _sale('701', self.b, '01HD12', _at(self.today, 9, i))
        for i in range(2):
            _sale('701', self.b, '', _at(self.today, 12, i))          # walk-ins
        sc = engine.score_day(self.today)
        self.assertEqual(_pts(self.a, 'pic_capture_day'), 0)          # not during the day
        engine.finalize_day(self.today, sc, penalties=False)
        self.assertEqual(_pts(self.a, 'pic_capture_day'), 5)          # 8/10 = 80%
        # c: 9 invoices only → below the minimum
        for i in range(9):
            _sale('702', self.b, '01HD12', _at(self.today, 14, i))
        engine.finalize_day(self.today, engine.Scorer(), penalties=False)
        self.assertEqual(_pts(self.c, 'pic_capture_day'), 0)

    def test_milestone_badge(self):
        for i in range(10):
            pic = f'02HD{i}'
            _cust(pic, created=self.today, phone=f'01100000{i:02d}')
            _sale('701', self.b, pic, _at(self.today, 9, i))
        engine.run(days=0, finalize=False)
        self.assertEqual(_n(self.a, 'pic_new'), 10)
        self.assertTrue(StaffBadge.objects.filter(staff=self.a, badge__key='pic_new_10').exists())


class PicPanelAndReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_defaults()
        cls.b = make_branch()
        _, cls.a, cls.a_c = make_user('picp_a', role='salesperson', branch=cls.b)
        cls.a.softech_user_id = '711'
        cls.a.save()
        _, _, cls.admin_c = make_admin('picp_admin')
        _, cls.nolink, cls.nolink_c = make_user('picp_x', role='salesperson', branch=cls.b)

    def test_panel(self):
        today = timezone.localdate()
        _cust('03HD1', created=today)
        _sale('711', self.b, '03HD1', _at(today, 9))
        _sale('711', self.b, '', _at(today, 10))
        engine.run(days=0, finalize=False)
        pic = self.a_c.get('/api/gamification/me/').json()['pic']
        self.assertTrue(pic['linked'])
        self.assertEqual(pic['today']['new_pics'], 1)
        self.assertEqual(pic['today']['customers_served'], 1)
        self.assertEqual(pic['today']['invoices'], 2)
        self.assertEqual(pic['today']['capture_pct'], 50.0)
        self.assertTrue(any(m['rule_key'] == 'pic_new' and m['threshold'] == 10 for m in pic['milestones']))
        self.assertFalse(self.nolink_c.get('/api/gamification/me/').json()['pic']['linked'])

    def test_report_and_challenge_metrics(self):
        today = timezone.localdate()
        yday = today - timedelta(days=1)
        _cust('03HD2', created=yday)
        _sale('711', self.b, '03HD2', _at(yday, 9))
        _sale('711', self.b, '', _at(yday, 10))
        engine.score_day(yday)
        r = self.admin_c.get('/api/gamification/reports/overview/',
                             {'from': str(yday), 'to': str(today)}).json()
        self.assertEqual(r['pic']['new_pics'], 1)
        self.assertEqual(r['pic']['capture_pct'], 50.0)
        self.assertEqual(r['pic']['top_new'][0]['new_pics'], 1)
        ch = TeamChallenge.objects.create(name_ar='تسجيل', name_en='Capture', metric='pic_capture_rate',
                                          target=Decimal('40'), start=yday, end=yday)
        ch2 = TeamChallenge.objects.create(name_ar='جدد', name_en='New', metric='new_pics_per_member',
                                           target=Decimal('0.5'), start=yday, end=yday)
        T.evaluate(ch)
        T.evaluate(ch2)
        res = ch.results.get(branch=self.b)
        self.assertEqual(res.value, Decimal('50.00'))
        self.assertTrue(res.achieved)
        self.assertEqual(ch2.results.get(branch=self.b).value, Decimal('0.50'))   # 1 new / 2 members
