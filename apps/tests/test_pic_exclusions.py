"""PIC Analytics Task E1 — the changeable PIC exclusion list (doc 33 §15), on synthetic facts."""
from datetime import date as D
from decimal import Decimal
from io import BytesIO

import openpyxl
from django.db.models import Sum

from apps.audit.models import AuditLog
from apps.customers.models import Customer
from apps.users.models import RoleModuleAccess
from apps.pic_analytics import exclusions
from apps.pic_analytics.models import PicDayFact, PicExclusion
from apps.pic_analytics.queries import groups, missed, numbers, options, retention
from apps.pic_analytics.queries.calls import call_center, calls_by_pic
from apps.pic_analytics.queries.overview import overview
from apps.pic_analytics.queries.pics import pic_rows
from apps.tests.factories import make_user
from apps.tests.test_pic_api import ApiBase, url
from apps.tests.test_pic_queries_calls import at

D_ = Decimal
BASE = '/api/pic-analytics/exclusions/'


class ExcludeBase(ApiBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for action in ('view', 'export'):
            RoleModuleAccess.objects.update_or_create(
                role='supervisor', module='pic_analytics', action=action, defaults={'is_allowed': True})
        cls.sup_c = make_user('q_sup', role='supervisor', branch=cls.ba)[2]
        Customer.objects.filter(softech_pic__in=['R1', 'RE']).update(phone='01234567891')
        cls.n1_phone_call = cls.call(D(2026, 10, 7), 'N1', 'inbound', 'answered', ext='10', key='1000000001')

    def exclude(self, pic='N1', reason='حساب جاري'):
        return PicExclusion.objects.create(pic=pic, reason=reason, added_by=self.admin_p)


class QueryTests(ExcludeBase):

    def test_overview_reconciles_and_drops_the_pic(self):
        before = overview(self.flt(), self.mgmt)
        self.assertEqual((before['distinct_pics'], before['excluded_net'], before['excluded_pics']), (3, D_('0'), 0))
        self.exclude()
        o = overview(self.flt(), self.mgmt)
        self.assertEqual((o['distinct_pics'], o['new'], o['returning']), (2, 0, 2))
        self.assertEqual(o['excluded_net'], D_('350'))
        self.assertEqual(o['excluded_pics'], 1)
        total = PicDayFact.objects.filter(day__gte=D(2026, 10, 1), day__lte=D(2026, 10, 31)).aggregate(s=Sum('net'))['s']
        self.assertEqual(o['net'] + o['no_pic_net'] + o['excluded_net'], total)
        self.assertEqual(o['visits'], 2)
        self.assertEqual([m['new'] for m in o['by_month']], [0])

    def test_removing_restores_without_rebuild(self):
        x = self.exclude()
        self.assertEqual(overview(self.flt(), self.mgmt)['distinct_pics'], 2)
        exclusions.remove_exclusion(x.pk, self.admin_p)
        o = overview(self.flt(), self.mgmt)
        self.assertEqual((o['distinct_pics'], o['excluded_net'], o['excluded_pics']), (3, D_('0'), 0))

    def test_pic_filters_leave_excluded_line_out(self):
        self.exclude()
        o = overview(self.flt(segment='vip'), self.mgmt)
        self.assertIsNone(o['excluded_net'])

    def test_pic_list_groups_and_options(self):
        Customer.objects.filter(softech_pic='N1').update(softech_ptclassifcode='ZZ', person_classif_label='نوع')
        self.exclude()
        self.assertNotIn('N1', [r['pic'] for r in pic_rows(self.flt(), self.mgmt)['rows']])
        g = groups.by_branch(self.flt(), self.mgmt)
        self.assertEqual(sum(r['net'] for r in g['rows']), D_('120'))
        self.assertEqual(g['total']['distinct_pics'], 2)
        self.assertEqual(groups.by_category(self.flt(), self.mgmt)['total']['distinct_pics'], 2)
        self.assertEqual(groups.by_salesperson(self.flt(), self.mgmt)['total']['net'], D_('120'))
        self.assertNotIn('ZZ', [t['code'] for t in options.filter_options(self.flt(), self.mgmt)['customer_types']])

    def test_retention_frequency_and_cohorts(self):
        PicDayFact.objects.filter(pic='N1', day=D(2026, 10, 5)).update(is_first_purchase=True)
        PicDayFact.objects.filter(pic='N1', day=D(2026, 10, 20)).update(is_first_purchase=True)
        before = retention.cohorts(self.flt(), self.mgmt)
        self.assertEqual(before[-1]['size'], 1)
        self.exclude()
        self.assertEqual(retention.cohorts(self.flt(), self.mgmt)[-1]['size'], 0)
        fr = retention.frequency(self.flt(), self.mgmt)
        self.assertEqual(sum(fr['c'].values()), 2)

    def test_per_pic_calls_not_counted_but_call_remains(self):
        self.exclude()
        f = self.flt()
        self.assertNotIn('N1', calls_by_pic(f, None))
        self.assertEqual(calls_by_pic(f, {'N1'}), {})
        self.assertEqual(overview(f, self.mgmt)['calls_in'], 3)           # 2 from the base + N1's: still a call
        rows = {r['agent_ext']: r for r in call_center(f, self.mgmt)['rows']}
        self.assertEqual(rows['10']['calls_in'], 2)
        self.assertEqual(rows['10']['pics_reached'], 0)
        row = next(r for r in pic_rows(self.flt(), self.mgmt)['rows'] if r['pic'] == 'R1')
        self.assertEqual(row['calls_in'], 0)

    def test_missed_call_of_excluded_pic_is_flagged(self):
        c = self.call(D(2026, 10, 8), 'N1', 'inbound', 'abandoned', key='1000000001')
        self.exclude()
        rows = missed.missed_rows(self.flt(), self.mgmt, False, 1)['rows']
        r = next(r for r in rows if r['call_id'] == c.pk)
        self.assertTrue(r['pic_excluded'])
        self.assertIsNone(r['lifetime_net'])
        self.assertFalse(r['bought_within_7d'])

    def test_conversions_skip_excluded(self):
        Customer.objects.filter(softech_pic='N1').update(softech_created_at=D(2026, 10, 10))
        self.call(D(2026, 10, 7), 'N1', 'inbound', 'answered', key='1000000001')
        self.assertEqual(numbers.conversions(self.flt(), self.mgmt)['became_pic'], 1)
        self.exclude()
        self.assertEqual(numbers.conversions(self.flt(), self.mgmt)['became_pic'], 0)

    def test_branch_manager_figures_also_drop_it(self):
        self.exclude()
        o = overview(self.flt(), self.mgr)
        self.assertEqual(o['excluded_net'], D_('150'))          # only N1's branch-A sales are in scope
        self.assertNotIn('N1', [r['pic'] for r in pic_rows(self.flt(), self.mgr)['rows']])


class ApiTests(ExcludeBase):

    def test_branch_manager_and_plain_user_403(self):
        for c in (self.mgr_c, self.ph_c):
            self.assertEqual(c.get(BASE).status_code, 403)
            self.assertEqual(c.post(BASE, {'pic': 'N1', 'reason': 'x'}, format='json').status_code, 403)
            self.assertEqual(c.get(url('exclusions/suggestions/')).status_code, 403)
            self.assertEqual(c.post(f'{BASE}1/remove/').status_code, 403)
        self.assertEqual(PicExclusion.objects.count(), 0)

    def test_supervisor_and_admin_manage(self):
        for c in (self.sup_c, self.admin_c):
            self.assertEqual(c.get(BASE).status_code, 200)
            self.assertEqual(c.get(url('exclusions/suggestions/')).status_code, 200)
        self.assertTrue(self.sup_c.get('/api/pic-analytics/access/').json()['can_manage_exclusions'])
        self.assertFalse(self.mgr_c.get('/api/pic-analytics/access/').json()['can_manage_exclusions'])

    def test_add_list_remove_and_audit(self):
        r = self.sup_c.post(BASE, {'pic': 'N1', 'reason': 'حساب عقد'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        x = PicExclusion.objects.get()
        self.assertEqual((x.pic, x.reason), ('N1', 'حساب عقد'))
        row = self.admin_c.get(BASE).json()['rows'][0]
        self.assertEqual((row['pic'], row['customer_name'], row['reason']), ('N1', 'جديد', 'حساب عقد'))
        self.assertIn('net_12m', row)
        self.assertIn('visits_12m', row)
        self.assertNotIn('01000000001', str(row))
        a = AuditLog.objects.get(action='pic_analytics_pic_excluded')
        self.assertEqual((a.extra['pic'], a.extra['reason'], a.extra['after']), ('N1', 'حساب عقد', 'excluded'))
        self.assertEqual(self.admin_c.get(url('overview/')).json()['excluded_net'], 350.0)

        r = self.admin_c.post(f'{BASE}{x.pk}/remove/')
        self.assertEqual(r.status_code, 200)
        x.refresh_from_db()
        self.assertIsNotNone(x.removed_at)
        self.assertEqual(x.removed_by, self.admin_p)
        a = AuditLog.objects.get(action='pic_analytics_pic_included')
        self.assertEqual((a.extra['before'], a.extra['after'], a.extra['pic']), ('excluded', 'included', 'N1'))
        self.assertEqual(self.admin_c.get(BASE).json()['rows'], [])
        self.assertEqual(self.admin_c.post(f'{BASE}{x.pk}/remove/').status_code, 404)
        # re-adding creates a NEW row and keeps the history
        self.assertEqual(self.admin_c.post(BASE, {'pic': 'N1', 'reason': 'مرة أخرى'}, format='json').status_code, 201)
        self.assertEqual(PicExclusion.objects.filter(pic='N1').count(), 2)

    def test_validation(self):
        post = lambda d: self.admin_c.post(BASE, d, format='json')      # noqa: E731
        self.assertEqual(post({'pic': 'NOPE', 'reason': 'x'}).status_code, 400)
        self.assertEqual(post({'pic': '', 'reason': 'x'}).status_code, 400)
        self.assertEqual(post({'pic': 'N1', 'reason': ''}).status_code, 400)
        self.assertEqual(post({'pic': 'N1', 'reason': '  '}).status_code, 400)
        self.assertEqual(post({'pic': 'N1', 'reason': 'x' * 256}).status_code, 400)
        self.assertEqual(post({'pic': 'ACCT-5', 'reason': 'x'}).status_code, 400)
        self.assertEqual(post({'pic': 'N1', 'reason': 'ok'}).status_code, 201)
        dup = post({'pic': 'N1', 'reason': 'ok'})
        self.assertEqual(dup.status_code, 400)
        self.assertEqual(PicExclusion.objects.count(), 1)

    def test_suggestions_flag_junk_phone_and_busy_pic_without_phones(self):
        Customer.objects.create(name='حساب وهمي', softech_pic='JUNK', softech_id='Q-JUNK', phone='0100000000000')
        Customer.objects.create(name='مدخل', softech_pic='TXT', softech_id='Q-TXT', phone='dasdasdasd')
        Customer.objects.create(name='عقد', softech_pic='BUSY', softech_id='Q-BUSY', phone='01234567891')
        for pic in ('JUNK', 'TXT'):
            self.fact(pic, D(2026, 10, 3), self.ba, 1, 20, 10, 1, {'10': 20})
        for d in range(1, 31):
            self.fact('BUSY', D(2026, 10, d), self.ba, 1, 10, 5, 1, {'10': 10})
        r = self.admin_c.get(url('exclusions/suggestions/'))
        self.assertEqual(r.status_code, 200)
        rows = {x['pic']: x for x in r.json()['rows']}
        self.assertIn('junk_phone', rows['JUNK']['rules'])
        self.assertIn('junk_phone', rows['TXT']['rules'])
        self.assertIn('visits', rows['BUSY']['rules'])
        self.assertNotIn('R1', rows)           # a real-looking phone, one visit: not flagged
        body = r.content.decode()
        for raw in ('0100000000000', 'dasdasdasd', '01234567891'):
            self.assertNotIn(raw, body)
        self.exclude('BUSY')
        again = {x['pic'] for x in self.admin_c.get(url('exclusions/suggestions/')).json()['rows']}
        self.assertNotIn('BUSY', again)            # already excluded: not suggested again

    def test_suggestion_rules(self):
        self.assertTrue(exclusions.junk_phone('101010101'))
        self.assertTrue(exclusions.junk_phone('0100000000000'))
        self.assertTrue(exclusions.junk_phone('abc'))
        self.assertFalse(exclusions.junk_phone('01234567891'))
        self.assertFalse(exclusions.junk_phone(''))
        Customer.objects.create(name='فواتير', softech_pic='MANY', softech_id='Q-MANY', phone='01234567891')
        self.fact('MANY', D(2026, 10, 9), self.ba, 6, 20, 10, 1, {'10': 20})
        Customer.objects.create(name='ضخم', softech_pic='HUGE', softech_id='Q-HUGE', phone='01234567891')
        self.fact('HUGE', D(2026, 10, 9), self.ba, 1, 100000, 10, 1, {'10': 100000})
        rows = {x['pic']: x for x in exclusions.suggestions(self.flt(), self.mgmt)}
        self.assertEqual(rows['MANY']['rules'], ['invoices_per_visit'])
        self.assertEqual(rows['HUGE']['rules'], ['net'])


class ExportTests(ExcludeBase):

    def test_workbook_lists_exclusions_and_the_line(self):
        self.exclude(reason='حساب كهرباء')
        r = self.admin_c.get(url('export/'))
        self.assertEqual(r.status_code, 200)
        wb = openpyxl.load_workbook(BytesIO(r.content))
        cells = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row if c.value is not None]
        self.assertTrue(any('N1' in c and 'حساب كهرباء' in c for c in cells))
        self.assertTrue(any(c == 'مبيعات عملاء مستبعدون' for c in cells))
        names = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows() for c in row]
        self.assertNotIn('01000000001', ' '.join(names))
        # a branch manager sees only how many, never the PIC or reason
        r = self.mgr_c.get(url('export/'))
        self.assertEqual(r.status_code, 200)
        cells = ' '.join(str(c.value) for ws in openpyxl.load_workbook(BytesIO(r.content)).worksheets
                         for row in ws.iter_rows() for c in row if c.value is not None)
        self.assertNotIn('حساب كهرباء', cells)
