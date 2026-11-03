"""Sortable grid headers (S4): customers, call-center calls/cases, referral leads and vouchers order on the
server — every whitelisted field asc + desc answers 200, NULLs sort last, ties end on a unique pk, and the
priority column sorts by urgency rather than by the raw choice text."""
import datetime

from django.test import TestCase

from apps.callcenter.models import CallLog, CustomerCase
from apps.customers.models import Customer
from apps.referral.models import ReferralCode, ReferralLead
from apps.vouchers.models import Voucher

from .factories import make_admin, make_branch, make_customer, make_pharmacist, make_user


def rows(resp):
    assert resp.status_code == 200, resp.content
    d = resp.json()
    return d['results'] if isinstance(d, dict) and 'results' in d else d


class CustomerOrderingTests(TestCase):
    URL = '/api/customers/'
    FIELDS = ['name', 'created_at', 'updated_at', 'churn_score', 'ltv', 'days_since_last_visit',
              'last_visit_date', 'segment', 'preferred_branch__name_ar']

    def setUp(self):
        _u, _p, self.api = make_admin('s4_cust_admin')
        self.b1 = make_branch('ب فرع', 'S4A')
        self.b2 = make_branch('ا فرع', 'S4B')
        self.b1.name_ar, self.b2.name_ar = 'ب فرع', 'ا فرع'
        self.b1.save()
        self.b2.save()
        self.c1 = make_customer('زياد', '01000000041')
        self.c2 = make_customer('أحمد', '01000000042')
        self.c3 = make_customer('منى', '01000000043')
        Customer.objects.filter(pk=self.c1.pk).update(preferred_branch=self.b1, days_since_last_visit=10)
        Customer.objects.filter(pk=self.c2.pk).update(preferred_branch=self.b2, days_since_last_visit=50)
        # c3 keeps days_since_last_visit NULL and no branch

    def ids(self, ordering):
        return [r['id'] for r in rows(self.api.get(self.URL, {'ordering': ordering}))]

    def test_every_field_asc_and_desc_is_200(self):
        for f in self.FIELDS:
            for o in (f, '-' + f):
                self.assertEqual(self.api.get(self.URL, {'ordering': o}).status_code, 200, o)

    def test_null_values_last_both_directions(self):
        self.assertEqual(self.ids('days_since_last_visit')[-1], self.c3.id)
        self.assertEqual(self.ids('-days_since_last_visit')[-1], self.c3.id)
        self.assertEqual(self.ids('days_since_last_visit')[:2], [self.c1.id, self.c2.id])
        self.assertEqual(self.ids('preferred_branch__name_ar')[:2], [self.c2.id, self.c1.id])

    def test_blank_segment_last_both_directions(self):
        Customer.objects.filter(pk=self.c1.pk).update(segment='vip')
        Customer.objects.filter(pk=self.c2.pk).update(segment='regular')
        Customer.objects.filter(pk=self.c3.pk).update(segment='')
        for o in ('segment', '-segment'):
            self.assertEqual(self.ids(o)[-1], self.c3.id, o)
        self.assertEqual(self.ids('segment')[:2], [self.c2.id, self.c1.id])

    def test_phone_is_not_an_ordering_field(self):
        # an unknown / masked field is ignored: the default (name) order stays
        self.assertEqual(self.ids('phone'), self.ids('name'))

    def test_unique_tiebreak_pages_do_not_repeat(self):
        for i in range(60):
            Customer.objects.create(name=f'عميل {i:02d}', phone=f'0100000{i + 100:04d}', segment='regular')
        seen = []
        for page in (1, 2):
            seen += [r['id'] for r in rows(self.api.get(self.URL, {'ordering': 'segment', 'page': page}))]
        self.assertEqual(len(seen), len(set(seen)))


class CallCenterOrderingTests(TestCase):
    CALLS = '/api/callcenter/calls/'
    CASES = '/api/callcenter/cases/'

    def setUp(self):
        _u, self.p, self.api = make_admin('s4_cc_admin')
        self.cust = make_customer('عميل', '01000000051')
        self.l1 = CallLog.objects.create(phone_number='01000000052', caller_name='ب',
                                         duration_seconds=30, quality_score=70)
        self.l2 = CallLog.objects.create(phone_number='01000000053', caller_name='ا',
                                         duration_seconds=90, quality_score=None)
        self.l3 = CallLog.objects.create(phone_number='01000000054', caller_name='ت',
                                         duration_seconds=60, quality_score=95, handled_by=self.p)
        for pr, num in (('low', 1), ('urgent', 2), ('normal', 3), ('high', 4)):
            CustomerCase.objects.create(customer=self.cust, category='complaint', priority=pr,
                                        title=f'حالة {pr}', case_number=f'S4-{num}')

    def test_calls_every_field_asc_and_desc_is_200(self):
        for f in ['called_at', 'duration_seconds', 'quality_score', 'caller_name', 'purpose', 'status',
                  'ai_sentiment', 'handled_by_name_key']:
            for o in (f, '-' + f):
                self.assertEqual(self.api.get(self.CALLS, {'ordering': o}).status_code, 200, o)

    def test_calls_quality_score_null_last_both_ways(self):
        for o in ('quality_score', '-quality_score'):
            self.assertEqual(rows(self.api.get(self.CALLS, {'ordering': o}))[-1]['id'], self.l2.id)
        self.assertEqual([r['id'] for r in rows(self.api.get(self.CALLS, {'ordering': 'caller_name'}))],
                         [self.l2.id, self.l1.id, self.l3.id])

    def test_calls_handled_by_sorts_by_displayed_name(self):
        _u2, p2, _c = make_user('s4_agent_b', role='call_center', access_all=True)
        CallLog.objects.filter(pk=self.l1.pk).update(handled_by=p2)
        names = {self.l3.id: self.p.full_name, self.l1.id: p2.full_name}
        expect = sorted(names, key=lambda i: names[i].casefold())
        asc = [r['id'] for r in rows(self.api.get(self.CALLS, {'ordering': 'handled_by_name_key'}))]
        desc = [r['id'] for r in rows(self.api.get(self.CALLS, {'ordering': '-handled_by_name_key'}))]
        self.assertEqual(asc, expect + [self.l2.id])             # unassigned call last
        self.assertEqual(desc, expect[::-1] + [self.l2.id])

    def test_cases_every_field_asc_and_desc_is_200(self):
        for f in ['created_at', 'updated_at', 'sla_due', 'priority_rank', 'case_number', 'title', 'category',
                  'status', 'customer__name', 'assigned_to_name_key']:
            for o in (f, '-' + f):
                self.assertEqual(self.api.get(self.CASES, {'ordering': o}).status_code, 200, o)

    def test_cases_assigned_and_customer_name_order(self):
        _u2, p2, _c = make_user('s4_agent_c', role='call_center', access_all=True)
        c2 = make_customer('أحمد', '01000000055')
        a, b, c, d = CustomerCase.objects.order_by('id')
        CustomerCase.objects.filter(pk=a.pk).update(assigned_to=self.p)
        CustomerCase.objects.filter(pk=b.pk).update(assigned_to=p2)
        CustomerCase.objects.filter(pk=c.pk).update(customer=c2)
        names = {a.id: self.p.full_name, b.id: p2.full_name}
        expect = sorted(names, key=lambda i: names[i].casefold())
        got = [r['id'] for r in rows(self.api.get(self.CASES, {'ordering': 'assigned_to_name_key'}))]
        self.assertEqual(got[:2], expect)
        got = [r['id'] for r in rows(self.api.get(self.CASES, {'ordering': '-assigned_to_name_key'}))]
        self.assertEqual(got[:2], expect[::-1])
        self.assertEqual(set(got[2:]), {c.id, d.id})             # unassigned last
        got = [r['id'] for r in rows(self.api.get(self.CASES, {'ordering': 'customer__name'}))]
        self.assertEqual(got[0], c.id)                           # 'أحمد' before 'عميل'
        got = [r['id'] for r in rows(self.api.get(self.CASES, {'ordering': '-customer__name'}))]
        self.assertEqual(got[-1], c.id)

    def test_branch_scope_holds_under_ordering(self):
        ba, bb = make_branch('فرع أ', 'S4SA'), make_branch('فرع ب', 'S4SB')
        _u, _p, api_a = make_pharmacist('s4_scoped_a', branch=ba)
        la = CallLog.objects.create(phone_number='01000000071', branch=ba, duration_seconds=5)
        lb = CallLog.objects.create(phone_number='01000000072', branch=bb, duration_seconds=6)
        ca = CustomerCase.objects.create(customer=self.cust, category='other', title='أ', branch=ba, case_number='S4-A')
        cb = CustomerCase.objects.create(customer=self.cust, category='other', title='ب', branch=bb, case_number='S4-B')
        for o in ('duration_seconds', '-duration_seconds', 'quality_score', 'handled_by_name_key'):
            ids = {r['id'] for r in rows(api_a.get(self.CALLS, {'ordering': o}))}
            self.assertIn(la.id, ids, o)
            self.assertNotIn(lb.id, ids, o)
        for o in ('case_number', '-priority_rank', 'assigned_to_name_key'):
            ids = {r['id'] for r in rows(api_a.get(self.CASES, {'ordering': o}))}
            self.assertIn(ca.id, ids, o)
            self.assertNotIn(cb.id, ids, o)

    def test_cases_priority_sorts_by_urgency(self):
        pr = [r['priority'] for r in rows(self.api.get(self.CASES, {'ordering': '-priority_rank'}))]
        self.assertEqual(pr, ['urgent', 'high', 'normal', 'low'])
        pr = [r['priority'] for r in rows(self.api.get(self.CASES, {'ordering': 'priority_rank'}))]
        self.assertEqual(pr, ['low', 'normal', 'high', 'urgent'])


class ReferralOrderingTests(TestCase):
    URL = '/api/referral/leads/'

    def setUp(self):
        _u, _p, self.api = make_admin('s4_ref_admin')
        a = make_customer('ي مُحيل', '01000000061')
        b = make_customer('ا مُحيل', '01000000062')
        ca = ReferralCode.objects.create(customer=a)
        cb = ReferralCode.objects.create(customer=b)
        self.x = ReferralLead.objects.create(referral_code=ca, referrer=a, lead_name='ب',
                                             lead_phone='01000000063', fraud_score=10)
        self.y = ReferralLead.objects.create(referral_code=cb, referrer=b, lead_name='ا',
                                             lead_phone='01000000064', fraud_score=50)

    def ids(self, o):
        return [r['id'] for r in rows(self.api.get(self.URL, {'ordering': o}))]

    def test_every_field_asc_and_desc_is_200(self):
        for f in ['lead_name', 'referrer__name', 'status', 'fraud_score', 'created_at']:
            for o in (f, '-' + f):
                self.assertEqual(self.api.get(self.URL, {'ordering': o}).status_code, 200, o)

    def test_order(self):
        self.assertEqual(self.ids('lead_name'), [self.y.id, self.x.id])
        self.assertEqual(self.ids('-fraud_score'), [self.y.id, self.x.id])
        self.assertEqual(self.ids('referrer__name'), [self.y.id, self.x.id])
        self.assertEqual(self.ids('lead_phone'), self.ids(''))      # masked phone: not orderable, default kept


class VoucherOrderingTests(TestCase):
    URL = '/api/vouchers/vouchers/'

    def setUp(self):
        _u, self.p, self.api = make_admin('s4_vou_admin')
        today = datetime.date.today()

        def mk(title, used, until):
            return Voucher.objects.create(
                code=Voucher.generate_code(), title=title, voucher_type='discount_pct', discount_pct=10,
                created_by=self.p, status='active', max_uses=10, times_used=used, valid_from=today,
                valid_until=until)

        self.a = mk('ب', 5, today + datetime.timedelta(days=5))
        self.b = mk('ا', 1, None)
        self.c = mk('ت', 9, today + datetime.timedelta(days=1))

    def ids(self, o):
        return [r['id'] for r in rows(self.api.get(self.URL, {'ordering': o}))]

    def test_every_field_asc_and_desc_is_200(self):
        from apps.vouchers.views import VoucherViewSet
        for f in VoucherViewSet.LIST_ORDERINGS:
            for o in (f, '-' + f):
                self.assertEqual(self.api.get(self.URL, {'ordering': o}).status_code, 200, o)

    def test_order_and_nulls_last(self):
        self.assertEqual(self.ids('title'), [self.b.id, self.a.id, self.c.id])
        self.assertEqual(self.ids('-times_used'), [self.c.id, self.a.id, self.b.id])
        self.assertEqual(self.ids('valid_until')[-1], self.b.id)
        self.assertEqual(self.ids('-valid_until')[-1], self.b.id)

    def test_unknown_field_is_400_and_default_is_newest_first(self):
        self.assertEqual(self.api.get(self.URL, {'ordering': 'discount_pct;drop'}).status_code, 400)
        self.assertEqual(self.ids(''), [self.c.id, self.b.id, self.a.id])
