"""PIC Analytics Task 16 — the left-out follow-ups (doc 33 §15) and the parked minors."""
import json
from datetime import date as D, timedelta
from io import BytesIO
from unittest import mock

import openpyxl
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.callcenter.models import CallLog
from apps.customers.models import Customer
from apps.pbx.cdr import relink_all
from apps.pbx.models import AgentExtension
from apps.pic_analytics.models import PhoneLabel, PicDayFact
from apps.pic_analytics.queries import groups, options
from apps.pic_analytics.queries.calls import call_center, calls_by_pic
from apps.pic_analytics.queries.missed import missed_rows, missed_summary
from apps.pic_analytics.queries.numbers import conversions, label_number
from apps.pic_analytics.queries.options import filter_options
from apps.pic_analytics.queries.overview import overview
from apps.pic_analytics.queries.pics import pic_rows
from apps.tests.test_pic_api import ApiBase, url
from apps.tests.test_pic_queries_calls import CallBase


class SearchTests(CallBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        Customer.objects.filter(softech_pic='R1').update(phone_alt='+201000000777')
        Customer.objects.create(name='خارج النطاق', softech_pic='OUT', softech_id='Q-OUT', phone='01000000009',
                                softech_created_at=D(2025, 1, 1))
        cls.fact('OUT', D(2026, 10, 8), cls.bb, 1, 10, 5, 1, {'10': 10})

    def pics(self, q, access=None):
        f = self.flt(q=q)
        return [r['pic'] for r in pic_rows(f, access or self.mgmt, '-net', 1, None)['rows']]

    def test_name_contains_case_insensitive(self):
        self.assertEqual(self.pics('عائ'), ['R1'])
        self.assertEqual(set(self.pics('')), {'N1', 'R1', 'RE', 'OUT'})

    def test_exact_pic_code(self):
        self.assertEqual(self.pics('re'), [])          # exact code, case-sensitive: not a name either
        self.assertEqual(self.pics('RE'), ['RE'])
        self.assertEqual(self.pics('R'), [])

    def test_phone_any_format_and_alt_phone(self):
        self.assertEqual(self.pics('0100 000-0002'), ['R1'])
        self.assertEqual(self.pics('+201000000002'), ['R1'])
        self.assertEqual(self.pics('01000000777'), ['R1'])          # phone_alt
        self.assertEqual(self.pics('0100000'), [])                   # a prefix is not a phone

    def test_short_digits_are_not_a_phone(self):
        self.assertEqual(self.pics('123456'), [])

    def test_branch_manager_search_stays_in_scope(self):
        self.assertEqual(self.pics('خارج', self.mgmt), ['OUT'])
        self.assertEqual(self.pics('خارج', self.mgr), [])
        self.assertEqual(self.pics('01000000009', self.mgr), [])
        self.assertEqual(self.pics('OUT', self.mgr), [])

    def test_search_adds_nothing_to_the_row_shape(self):
        plain = pic_rows(self.flt(), self.mgmt, '-net', 1, 50)['rows']
        found = pic_rows(self.flt(q='01000000002'), self.mgmt, '-net', 1, 50)['rows']
        self.assertEqual([r['pic'] for r in found], ['R1'])
        self.assertEqual(set(found[0]), set(next(r for r in plain if r['pic'] == 'R1')))
        self.assertEqual(found[0]['phone'], next(r for r in plain if r['pic'] == 'R1')['phone'])

    def test_branch_manager_never_sees_the_searched_phone(self):
        rows = pic_rows(self.flt(q='01000000002'), self.mgr, '-net', 1, 50)['rows']
        self.assertEqual([r['pic'] for r in rows], ['R1'])
        self.assertNotIn('01000000002', json.dumps(rows, default=str))

    def test_count_follows_search(self):
        self.assertEqual(pic_rows(self.flt(q='جديد'), self.mgmt, '-net', 1, 50)['count'], 1)


class BasketLinesTests(CallBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        PicDayFact.objects.filter(pic='N1', day=D(2026, 10, 5), salesperson='u1').update(lines=3)
        PicDayFact.objects.filter(pic='N1', day=D(2026, 10, 5), salesperson='u2').update(lines=2)

    def test_overview_basket_lines(self):
        o = overview(self.flt(), self.mgmt)
        self.assertEqual(o['basket_lines'], 2.0)                    # (5 + 1 + 1 + 1) lines / 4 visits
        self.assertIsNone(overview(self.flt(category='10'), self.mgmt)['basket_lines'])

    def test_groups_lines_per_visit(self):
        rows = {r['key']: r for r in groups.by_branch(self.flt(), self.mgmt)['rows']}
        self.assertEqual(rows[self.ba.pk]['lines_per_visit'], 2.33)    # 7 lines / 3 visits
        self.assertEqual(rows[self.bb.pk]['lines_per_visit'], 1.0)
        self.assertEqual(groups.by_branch(self.flt(), self.mgmt)['total']['lines_per_visit'], 2.0)
        for fn in (groups.by_branch, groups.by_salesperson, groups.by_channel):
            for r in fn(self.flt(category='10'), self.mgmt)['rows']:
                self.assertIsNone(r['lines_per_visit'])
        for r in groups.by_category(self.flt(), self.mgmt)['rows']:
            self.assertIsNone(r['lines_per_visit'])


class SameDayCallTests(CallBase):

    def test_calls_by_pic_same_day(self):
        # R1 bought 2026-10-10
        self.call(D(2026, 10, 10), 'R1', hh=8)
        self.call(D(2026, 10, 9), 'R1')
        self.call(D(2026, 10, 10), 'R1', status='abandoned')       # not answered: never counts
        c = calls_by_pic(self.flt(), {'R1'})['R1']
        self.assertEqual((c['call_to_purchase'], c['call_to_purchase_same_day']), (2, 1))

    def test_call_center_same_day_pct(self):
        self.call(D(2026, 10, 10), 'R1', ext='10')
        self.call(D(2026, 10, 9), 'R1', ext='10')
        self.call(D(2026, 10, 1), 'R1', ext='10')                  # no sale that day or within 7 days
        row = call_center(self.flt(), self.mgmt)['rows'][0]
        self.assertEqual(row['call_to_purchase_pct'], 66.7)
        self.assertEqual(row['call_to_purchase_same_day_pct'], 33.3)

    def test_same_day_none_without_answered_pic_calls(self):
        self.call(D(2026, 10, 10), '', ext='10')
        self.assertIsNone(call_center(self.flt(), self.mgmt)['rows'][0]['call_to_purchase_same_day_pct'])


class NewPicsPerAgentTests(CallBase):

    def test_new_pics_sold_per_agent(self):
        # N1 is the only NEW pic; its first-day fact rows carry salespeople u1 and u2
        self.admin_p.softech_user_id = 'u1'
        self.admin_p.save()
        AgentExtension.objects.create(extension='10', staff=self.admin_p, pbx_name='A')
        AgentExtension.objects.create(extension='11', staff=self.mgr_p, pbx_name='B')      # no softech_user_id
        self.call(D(2026, 10, 5), 'N1', ext='10')
        self.call(D(2026, 10, 5), 'N1', ext='11')
        self.call(D(2026, 10, 5), 'N1', ext='12')                  # extension unknown to us
        res = call_center(self.flt(), self.mgmt)
        by = {r['agent_ext']: r['new_pics_sold'] for r in res['rows']}
        self.assertEqual(by, {'10': 1, '11': None, '12': None})
        self.assertIn('team_new_pics_sold', res)

    def test_agent_whose_code_sold_nobody_new_gets_zero(self):
        self.admin_p.softech_user_id = 'u9'
        self.admin_p.save()
        AgentExtension.objects.create(extension='10', staff=self.admin_p, pbx_name='A')
        self.call(D(2026, 10, 5), 'N1', ext='10')
        self.assertEqual(call_center(self.flt(), self.mgmt)['rows'][0]['new_pics_sold'], 0)


class ConversionSplitTests(CallBase):

    def setUp(self):
        AgentExtension.objects.create(extension='10', staff=self.admin_p, pbx_name='Ten')
        # number 1 -> pic X1 (created 10-10): answered by ext 10 then ext 11, bought at branch bb
        self.call(D(2026, 9, 20), '', key='1000000060', ext='10')
        self.call(D(2026, 9, 25), '', key='1000000060', ext='11')
        self.call(D(2026, 9, 26), '', key='1000000060', ext='12', status='abandoned')
        # number 2 -> pic X2 (created 10-10): answered by ext 10, never bought
        self.call(D(2026, 9, 21), '', key='1000000061', ext='10')
        Customer.objects.create(name='ج١', softech_pic='X1', softech_id='Q-X1', phone='01000000060',
                                softech_created_at=D(2026, 10, 10))
        Customer.objects.create(name='ج٢', softech_pic='X2', softech_id='Q-X2', phone='01000000061',
                                softech_created_at=D(2026, 10, 10))
        relink_all()
        self.fact('X1', D(2026, 10, 9), self.ba, 1, 5, 3, 1, {'10': 5})        # before creation: ignored
        self.fact('X1', D(2026, 10, 12), self.bb, 1, 50, 30, 1, {'10': 50})
        self.fact('X1', D(2026, 10, 14), self.ba, 1, 50, 30, 1, {'10': 50})

    def test_by_agent_is_the_last_answered_call_before_creation(self):
        c = conversions(self.flt(), self.mgmt)
        by = {r['agent_ext']: r for r in c['by_agent']}
        self.assertEqual((by['11']['became_pic'], by['11']['became_pic_and_bought']), (1, 1))
        self.assertEqual((by['10']['became_pic'], by['10']['became_pic_and_bought']), (1, 0))
        self.assertIn('(10)', by['10']['label'])
        self.assertEqual(sum(r['became_pic'] for r in c['by_agent']), c['became_pic'])

    def test_by_branch_is_the_first_sale_on_or_after_creation(self):
        c = conversions(self.flt(), self.mgmt)
        by = {r['branch_id']: r for r in c['by_branch']}
        self.assertEqual((by[self.bb.pk]['became_pic'], by[self.bb.pk]['became_pic_and_bought']), (1, 1))
        self.assertEqual((by[None]['became_pic'], by[None]['became_pic_and_bought']), (1, 0))
        self.assertIn('962', by[self.bb.pk]['label'])
        self.assertEqual(sum(r['became_pic'] for r in c['by_branch']), c['became_pic'])


class LabelListTests(ApiBase):
    P = '/api/pic-analytics/numbers/labels/'

    def test_list_and_delete(self):
        pl = label_number('1000000020', 'spam', 'ملاحظة', self.admin_p)
        r = self.admin_c.get(self.P)
        self.assertEqual(r.status_code, 200, r.content)
        row = r.json()['rows'][0]
        self.assertEqual((row['label'], row['label_display'], row['note'], row['label_id']),
                         ('spam', 'مزعج', 'ملاحظة', pl.pk))
        self.assertEqual(row['number_id'], self.lead.pk)
        self.assertEqual(row['created_by'], self.admin_p.full_name)
        self.assertIn('•', row['number'])
        body = r.content.decode()
        for raw in ('1000000020', '01000000020', 'phone_key'):
            self.assertNotIn(raw, body)
        d = self.admin_c.post(f'{self.P}{pl.pk}/delete/')
        self.assertEqual(d.status_code, 200, d.content)
        self.assertFalse(PhoneLabel.objects.exists())
        e = AuditLog.objects.get(action='pic_phone_unlabelled')
        self.assertEqual((e.old_data['label'], e.old_data['note']), ('spam', 'ملاحظة'))
        self.assertEqual(self.admin_c.post(f'{self.P}{pl.pk}/delete/').status_code, 404)

    def test_newest_first_and_paging(self):
        a = label_number('1000000020', 'spam', '', self.admin_p)
        b = label_number('1000000010', 'staff', '', self.admin_p)
        ids = [x['label_id'] for x in self.admin_c.get(self.P).json()['rows']]
        self.assertEqual(ids, [b.pk, a.pk])
        r = self.admin_c.get(self.P + '?page=2&page_size=1').json()
        self.assertEqual((r['count'], [x['label_id'] for x in r['rows']]), (2, [a.pk]))
        self.assertEqual(self.admin_c.get(self.P + '?page=0').status_code, 400)

    def test_label_without_a_call_has_no_number_id(self):
        label_number('1999999999', 'other', '', self.admin_p)
        row = self.admin_c.get(self.P).json()['rows'][0]
        self.assertIsNone(row['number_id'])

    def test_management_only(self):
        pl = label_number('1000000020', 'spam', '', self.admin_p)
        self.assertEqual(self.mgr_c.get(self.P).status_code, 403)
        self.assertEqual(self.mgr_c.post(f'{self.P}{pl.pk}/delete/').status_code, 403)
        self.assertEqual(self.ph_c.get(self.P).status_code, 403)
        self.assertEqual(self.ph_c.post(f'{self.P}{pl.pk}/delete/').status_code, 403)
        self.assertTrue(PhoneLabel.objects.exists())


class ActionListLabelTests(CallBase):

    def test_labelled_numbers_leave_the_action_list_but_not_the_kpi(self):
        self.call(D(2026, 10, 5), '', 'inbound', 'abandoned', key='1000000010', hh=9)
        self.call(D(2026, 10, 5), '', 'inbound', 'abandoned', key='1000000011', hh=9)
        label_number('1000000010', 'supplier', '', self.admin_p)
        rows = missed_rows(self.flt(), self.mgmt, True, 1)
        self.assertEqual([r['customer_number'][-2:] for r in rows['rows']], ['11'])
        self.assertEqual(rows['count'], 1)
        self.assertEqual(missed_rows(self.flt(), self.mgmt, False, 1)['count'], 2)
        self.assertEqual(missed_summary(self.flt(), self.mgmt)['not_returned'], 2)
        self.assertEqual(overview(self.flt(), self.mgmt)['missed_not_returned'], 2)


class CallbackMatchTests(ApiBase):

    def cb_url(self, call):
        return f'/api/pic-analytics/calls/missed/{call.pk}/callback/'

    def due(self, hours=24):
        return (timezone.now() + timedelta(hours=hours)).isoformat()

    def test_callback_in_another_number_format_blocks_a_second_one(self):
        CallLog.objects.create(phone_number='+201000000010', direction='inbound', status='callback',
                               callback_due=timezone.now() + timedelta(days=1), source='manual')
        r = self.admin_c.post(self.cb_url(self.miss), {'due': self.due()}, format='json')
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual(CallLog.objects.count(), 1)
        row = next(x for x in self.admin_c.get(url('calls/missed/rows/', '&only_not_returned=1')).json()['rows']
                   if x['call_id'] == self.miss.pk)
        self.assertIsNotNone(row['callback_pending'])

    def test_second_callback_after_first_is_409_and_other_number_is_free(self):
        self.assertEqual(self.admin_c.post(self.cb_url(self.miss), {'due': self.due()}, format='json').status_code, 200)
        self.assertEqual(self.admin_c.post(self.cb_url(self.miss), {'due': self.due()}, format='json').status_code, 409)
        other = self.call(D(2026, 10, 7), '', 'inbound', 'abandoned', key='1000000033', ext='')
        self.assertEqual(self.admin_c.post(self.cb_url(other), {'due': self.due()}, format='json').status_code, 200)

    def test_similar_number_with_different_digits_does_not_match(self):
        CallLog.objects.create(phone_number='01000000910', direction='inbound', status='callback',
                               callback_due=timezone.now() + timedelta(days=1), source='manual')
        r = self.admin_c.post(self.cb_url(self.miss), {'due': self.due()}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_check_and_create_run_in_a_locking_transaction(self):
        with mock.patch('django.db.models.query.QuerySet.select_for_update', autospec=True,
                        side_effect=lambda qs, *a, **k: qs) as sfu:
            r = self.admin_c.post(self.cb_url(self.miss), {'due': self.due()}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(sfu.called)


class SegmentLabelTests(CallBase):

    def test_missed_rows_carry_the_label_and_the_code(self):
        self.call(D(2026, 10, 5), 'N1', 'inbound', 'abandoned', key='1000000001')
        row = missed_rows(self.flt(), self.mgmt, False, 1)['rows'][0]
        self.assertEqual(row['segment'], dict(Customer.SEGMENT_CHOICES)['vip'])
        self.assertEqual(row['segment_code'], 'vip')

    def test_excel_shows_labels_not_codes(self):
        from apps.pic_analytics.export import build_workbook
        self.call(D(2026, 10, 5), 'N1', 'inbound', 'abandoned', key='1000000001')
        data, _ = build_workbook(self.flt(), self.mgmt)
        wb = openpyxl.load_workbook(BytesIO(data))
        for name in ('المكالمات الفائتة', 'العملاء'):
            ws = wb[name]
            head = [c.value for c in ws[1]]
            col = head.index('الشريحة')
            values = [r[col].value for r in ws.iter_rows(min_row=2)]
            self.assertIn(dict(Customer.SEGMENT_CHOICES)['vip'], values, name)
            self.assertNotIn('vip', values, name)


class OptionsMemoTests(CallBase):

    def test_option_copy_gets_a_fresh_memo(self):
        f = self.flt()
        f.memo['x'] = 1
        seen, real = [], options.calls_qs

        def spy(ff, *a, **k):
            seen.append(ff)
            return real(ff, *a, **k)
        with mock.patch.object(options, 'calls_qs', spy):
            filter_options(f, self.mgmt)
        self.assertTrue(seen)
        self.assertTrue(all(s.memo is not f.memo for s in seen))
        self.assertEqual(f.memo, {'x': 1})


class ApiFollowupTests(ApiBase):

    def test_pics_q_param(self):
        self.assertEqual(self.admin_c.get(url('pics/', '&q=%D8%B9%D8%A7%D8%A6')).json()['count'], 1)
        self.assertEqual(self.admin_c.get(url('pics/', '&q=01000000002')).json()['rows'][0]['pic'], 'R1')
        self.assertEqual(self.mgr_c.get(url('pics/', '&q=nobody')).json()['count'], 0)
        self.assertEqual(self.admin_c.get(url('pics/', '&q=' + 'x' * 200)).status_code, 400)

    def test_new_keys_in_the_api(self):
        self.assertIn('basket_lines', self.admin_c.get(url('overview/')).json())
        self.assertIn('lines_per_visit', self.admin_c.get(url('groups/branch/')).json()['rows'][0])
        c = self.admin_c.get(url('numbers/conversions/')).json()
        self.assertIn('by_agent', c)
        self.assertIn('by_branch', c)
        row = self.admin_c.get(url('calls/center/')).json()['rows'][0]
        self.assertIn('new_pics_sold', row)
        self.assertIn('call_to_purchase_same_day_pct', row)

    def test_export_filename_uses_the_effective_period(self):
        r = self.admin_c.get('/api/pic-analytics/export/?from=2020-01-01&to=2099-01-01')
        self.assertEqual(r.status_code, 200)
        self.assertIn('pic-analytics_2024-08-01_2026-10-20.xlsx', r['Content-Disposition'])

    def test_export_pic_sheet_honours_the_search(self):
        r = self.admin_c.get(url('export/', '&q=01000000002'))
        wb = openpyxl.load_workbook(BytesIO(r.content))
        ws = wb['العملاء']
        pics = [row[0].value for row in ws.iter_rows(min_row=2)]
        self.assertEqual(pics, ['R1'])

    def test_export_never_writes_the_searched_phone(self):
        r = self.admin_c.get(url('export/', '&q=01000000002'))
        e = AuditLog.objects.filter(action='pic_analytics_exported').latest('pk')
        self.assertNotIn('01000000002', json.dumps(e.extra, default=str))
        wb = openpyxl.load_workbook(BytesIO(r.content))
        cells = [str(c.value) for row in wb['الفلاتر والتعريفات'].iter_rows() for c in row]
        self.assertFalse(any('01000000002' in c for c in cells))
