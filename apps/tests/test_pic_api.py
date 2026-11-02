"""PIC Analytics Task 12 — the /api/pic-analytics/ endpoints, server-side dial and the Excel export (doc 33 §5, §9)."""
import json
from datetime import date as D
from io import BytesIO
from unittest import mock

import openpyxl
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.pbx.actions import AMIActionError
from apps.pbx.models import AgentExtension
from apps.customers.models import Customer
from apps.tests.factories import make_user
from apps.tests.test_pic_queries_calls import CallBase

PERIOD = 'from=2026-10-01&to=2026-10-31'
READ = ['access/', 'options/', 'overview/', 'pics/', 'groups/branch/', 'groups/salesperson/', 'groups/channel/',
        'groups/category/', 'retention/', 'retention/overdue/']
CALLS = ['calls/center/', 'calls/missed/', 'calls/missed/rows/', 'calls/unanswered/', 'numbers/',
         'numbers/conversions/']
RAW = '01000000010'                 # CallBase.call stores customer_number = '0' + key


def url(path, extra=''):
    return f'/api/pic-analytics/{path}?{PERIOD}{extra}'


def sheet_headers(wb):
    return {ws.title: [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))] for ws in wb.worksheets}


class ApiBase(CallBase):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.admin_c = make_user('q_admin', role='admin', branch=cls.ba)[2]
        cls.mgr_c = make_user('q_mgr', role='pharmacist', branch=cls.ba)[2]
        cls.ph_c = make_user('q_plain', role='pharmacist', branch=cls.ba)[2]
        cls.miss = cls.call(D(2026, 10, 5), '', 'inbound', 'abandoned', key='1000000010', ext='')
        cls.lead = cls.call(D(2026, 10, 6), '', 'inbound', 'answered', key='1000000020')


class AccessTests(ApiBase):

    def test_every_endpoint_requires_access(self):
        every = READ + CALLS + ['export/']
        for p in every:
            self.assertEqual(APIClient().get(url(p)).status_code, 401, p)
            self.assertEqual(self.ph_c.get(url(p)).status_code, 403, p)
        for p in (f'calls/missed/{self.miss.pk}/dial/', f'numbers/{self.lead.pk}/dial/', 'numbers/label/'):
            self.assertEqual(APIClient().post(f'/api/pic-analytics/{p}').status_code, 401, p)
            self.assertEqual(self.ph_c.post(f'/api/pic-analytics/{p}').status_code, 403, p)

    def test_management_reads_everything(self):
        for p in READ + CALLS:
            r = self.admin_c.get(url(p))
            self.assertEqual(r.status_code, 200, (p, r.content[:200]))

    def test_branch_manager_calls_tabs_forbidden(self):
        for p in READ:
            self.assertEqual(self.mgr_c.get(url(p)).status_code, 200, p)
        for p in CALLS:
            self.assertEqual(self.mgr_c.get(url(p)).status_code, 403, p)
        base = '/api/pic-analytics/'
        self.assertEqual(self.mgr_c.post(f'{base}numbers/label/', {'number_id': self.lead.pk, 'label': 'spam'}).status_code, 403)
        self.assertEqual(self.mgr_c.post(f'{base}calls/missed/{self.miss.pk}/dial/').status_code, 403)
        self.assertEqual(self.mgr_c.post(f'{base}numbers/{self.lead.pk}/dial/').status_code, 403)

    def test_branch_manager_never_gets_cost_keys(self):
        for p in ('overview/', 'groups/branch/', 'groups/channel/', 'pics/'):
            body = self.mgr_c.get(url(p)).content.decode()
            self.assertNotIn('"gp', body, p)
            self.assertNotIn('cost', body, p)
        self.assertIn('"gp"', self.admin_c.get(url('overview/')).content.decode())

    def test_access_endpoint(self):
        d = self.admin_c.get('/api/pic-analytics/access/').json()
        self.assertTrue(d['management'] and d['can_export'] and 'new_reliable_from' in d)
        self.assertFalse(self.mgr_c.get('/api/pic-analytics/access/').json()['management'])

    def test_bad_params(self):
        self.assertEqual(self.admin_c.get('/api/pic-analytics/overview/?from=nope&to=2026-10-31').status_code, 400)
        self.assertEqual(self.admin_c.get('/api/pic-analytics/overview/').status_code, 400)
        self.assertEqual(self.admin_c.get(url('groups/nope/')).status_code, 404)
        self.assertEqual(self.mgr_c.get(url('groups/nope/')).status_code, 404)
        self.assertEqual(self.admin_c.get(url('pics/', '&page=0')).status_code, 400)
        self.assertEqual(self.admin_c.get(url('pics/', '&page_size=9999')).status_code, 400)
        self.assertEqual(self.admin_c.get(url('calls/missed/rows/', '&only_not_returned=2')).status_code, 400)
        self.assertEqual(self.admin_c.get(url('calls/missed/rows/', '&only_not_returned=x')).status_code, 400)
        self.assertEqual(self.admin_c.get(url('calls/missed/rows/', '&only_not_returned=1')).status_code, 200)

    def test_shapes(self):
        r = self.admin_c.get(url('retention/')).json()
        self.assertEqual(set(r), {'frequency', 'retention', 'cohorts'})
        self.assertEqual(self.admin_c.get(url('pics/')).json()['count'], 3)
        self.assertEqual(self.admin_c.get(url('groups/branch/')).json()['total']['key'], 'all')
        rows = self.admin_c.get(url('calls/missed/rows/')).json()['rows']
        self.assertEqual(rows[0]['call_id'], self.miss.pk)
        self.assertEqual(self.admin_c.get(url('calls/unanswered/')).json(), {'rows': []})

    def test_no_phone_key_or_raw_number_in_numbers_bodies(self):
        for p in ('numbers/', 'numbers/conversions/'):
            body = self.admin_c.get(url(p)).content.decode()
            for raw in ('1000000020', '01000000020', '1000000010', 'phone_key'):
                self.assertNotIn(raw, body, p)
        rows = self.admin_c.get(url('numbers/')).json()['rows']
        self.assertTrue(rows and all(isinstance(r['number_id'], int) for r in rows))
        self.assertIn(self.lead.pk, [r['number_id'] for r in rows])

    def test_bad_number_id(self):
        base = '/api/pic-analytics/'
        self.assertEqual(self.admin_c.post(f'{base}numbers/99999999/dial/').status_code, 404)
        self.assertEqual(self.admin_c.post(f'{base}numbers/label/',
                                           {'number_id': 99999999, 'label': 'spam'}).status_code, 400)
        self.assertEqual(self.admin_c.post(f'{base}numbers/label/',
                                           {'phone_key': '1000000020', 'label': 'spam'}).status_code, 400)

    def test_linked_number_is_400(self):
        linked = self.call(D(2026, 10, 7), 'N1', 'inbound', 'answered', key='1000000030')
        base = '/api/pic-analytics/'
        self.assertEqual(self.admin_c.post(f'{base}numbers/{linked.pk}/dial/').status_code, 400)
        self.assertEqual(self.admin_c.post(f'{base}numbers/label/',
                                           {'number_id': linked.pk, 'label': 'spam'}).status_code, 400)

    def test_label_number(self):
        r = self.admin_c.post('/api/pic-analytics/numbers/label/',
                              {'number_id': self.lead.pk, 'label': 'spam', 'note': 'x'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.admin_c.post('/api/pic-analytics/numbers/label/',
                                           {'number_id': self.lead.pk, 'label': 'bogus'}).status_code, 400)
        self.assertTrue(AuditLog.objects.filter(action='pic_phone_labelled').exists())


class OptionsTests(ApiBase):

    def test_codes_and_labels(self):
        Customer.objects.filter(softech_pic='N1').update(softech_ptclassifcode='90', person_classif_label='توصيل')
        d = self.admin_c.get(url('options/')).json()
        self.assertEqual({r['code'] for r in d['salespeople']}, {'u1', 'u2'})
        self.assertTrue(all(r['label'] for r in d['salespeople']))
        self.assertEqual({r['code'] for r in d['categories']}, {'10', '50'})
        self.assertEqual(d['channels'], [{'code': 'cash', 'label': 'نقدي'}])
        self.assertEqual(d['customer_types'], [{'code': '90', 'label': 'توصيل'}])
        self.assertIn('vip', {r['code'] for r in d['segments']})
        self.assertEqual([r['code'] for r in d['frequency']], ['m1', 'm2', 'm3', 'm4_6', 'm7_12', 'y1plus'])
        self.assertIn('10', {a['ext'] for a in d['agents']})

    def test_other_filters_do_not_narrow_options(self):
        d = self.admin_c.get(url('options/', '&salesperson=u1')).json()
        self.assertEqual({r['code'] for r in d['salespeople']}, {'u1', 'u2'})

    def test_branch_manager_salespeople_only_from_own_branches(self):
        self.fact('R1', D(2026, 10, 11), self.bb, 1, 10, 5, 1, {'10': 10}, sp='u3')
        admin = {r['code'] for r in self.admin_c.get(url('options/')).json()['salespeople']}
        mgr = self.mgr_c.get(url('options/')).json()
        self.assertIn('u3', admin)
        self.assertEqual({r['code'] for r in mgr['salespeople']}, {'u1', 'u2'})

    def test_agents_absent_for_branch_manager(self):
        self.assertNotIn('agents', self.mgr_c.get(url('options/')).json())

    def test_requires_access_and_valid_period(self):
        self.assertEqual(self.ph_c.get(url('options/')).status_code, 403)
        self.assertEqual(self.admin_c.get('/api/pic-analytics/options/').status_code, 400)


class DialTests(ApiBase):
    P = '/api/pic-analytics/'

    def link_admin_ext(self):
        AgentExtension.objects.create(extension='201', staff=self.admin_p, pbx_name='Admin')

    def test_missed_dial_management(self):
        self.link_admin_ext()
        with mock.patch('apps.pbx.actions.originate_call') as orig:
            r = self.admin_c.post(f'{self.P}calls/missed/{self.miss.pk}/dial/')
        self.assertEqual(r.status_code, 200, r.content)
        orig.assert_called_once()
        self.assertEqual(orig.call_args[0][:2], ('201', RAW))
        self.assertNotIn(RAW, r.content.decode())                   # the browser never gets the number
        self.assertNotIn('1000000010', r.content.decode())
        e = AuditLog.objects.get(action='pic_analytics_dialled')
        self.assertEqual(e.extra['call_id'], self.miss.pk)

    def test_number_dial_management(self):
        self.link_admin_ext()
        with mock.patch('apps.pbx.actions.originate_call') as orig:
            r = self.admin_c.post(f'{self.P}numbers/{self.lead.pk}/dial/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(orig.call_args[0][:2], ('201', '01000000020'))
        self.assertNotIn('01000000020', r.content.decode())
        self.assertEqual(AuditLog.objects.filter(action='pic_analytics_dialled').count(), 1)

    def test_no_extension_is_400(self):
        with mock.patch('apps.pbx.actions.originate_call') as orig:
            r = self.admin_c.post(f'{self.P}calls/missed/{self.miss.pk}/dial/')
        self.assertEqual(r.status_code, 400)
        orig.assert_not_called()
        self.assertFalse(AuditLog.objects.filter(action='pic_analytics_dialled').exists())

    def test_ami_error_is_502_and_unknown_is_404(self):
        self.link_admin_ext()
        with mock.patch('apps.pbx.actions.originate_call', side_effect=AMIActionError('down')):
            r = self.admin_c.post(f'{self.P}calls/missed/{self.miss.pk}/dial/')
        self.assertEqual((r.status_code, r.json()['detail']), (502, 'down'))
        self.assertEqual(self.admin_c.post(f'{self.P}calls/missed/999999/dial/').status_code, 404)
        self.assertEqual(self.admin_c.post(f'{self.P}numbers/99999999/dial/').status_code, 404)
        # an answered call is not a missed call
        self.assertEqual(self.admin_c.post(f'{self.P}calls/missed/{self.lead.pk}/dial/').status_code, 404)

    def test_pbx_dial_view_unchanged(self):
        AgentExtension.objects.create(extension='202', staff=self.admin_p, pbx_name='Admin')
        with mock.patch('apps.pbx.actions.originate_call') as orig:
            r = self.admin_c.post('/api/pbx/dial/', {'destination': '0100 000-0099'}, format='json')
            bad = self.admin_c.post('/api/pbx/dial/', {'destination': ' '}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['caller_ext'], r.json()['destination']), ('202', '01000000099'))
        self.assertEqual(orig.call_args[0][:2], ('202', '01000000099'))
        self.assertEqual(bad.status_code, 400)


class CallbackTests(ApiBase):
    P = '/api/pic-analytics/'

    def due(self, days=1):
        from django.utils import timezone
        from datetime import timedelta
        return (timezone.now() + timedelta(days=days)).isoformat()

    def test_creates_pending_callback(self):
        from apps.callcenter.models import CallLog
        r = self.admin_c.post(f'{self.P}calls/missed/{self.miss.pk}/callback/',
                              {'due': self.due(), 'note': 'اتصل بعد الظهر'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        log = CallLog.objects.get(pk=r.json()['id'])
        self.assertEqual((log.status, log.direction, log.source, log.handled_by), ('callback', 'inbound', 'manual', self.admin_p))
        self.assertEqual(log.phone_number, RAW)
        self.assertNotIn(RAW, r.content.decode())
        self.assertNotIn('1000000010', r.content.decode())
        pend = self.admin_c.get('/api/callcenter/calls/pending-callbacks/?mode=all').json()
        self.assertIn(log.pk, [x['id'] for x in (pend.get('results') if isinstance(pend, dict) else pend)])
        e = AuditLog.objects.get(action='pic_analytics_callback_scheduled')
        self.assertEqual((e.extra['call_id'], e.extra['calllog_id'], e.extra['note']),
                         (self.miss.pk, log.pk, 'اتصل بعد الظهر'))
        self.assertEqual(e.extra['callback_due'], log.callback_due.isoformat())
        self.assertFalse(AuditLog.objects.filter(action='pic_analytics_dialled').exists())

    def test_past_due_and_missing_due_are_400(self):
        for body in ({'due': self.due(-1)}, {}, {'due': 'nope'}, {'due': self.due(), 'note': 'x' * 501}):
            r = self.admin_c.post(f'{self.P}calls/missed/{self.miss.pk}/callback/', body, format='json')
            self.assertEqual(r.status_code, 400, body)

    def test_branch_manager_forbidden_and_answered_404(self):
        self.assertEqual(self.mgr_c.post(f'{self.P}calls/missed/{self.miss.pk}/callback/',
                                         {'due': self.due()}, format='json').status_code, 403)
        self.assertEqual(self.admin_c.post(f'{self.P}calls/missed/{self.lead.pk}/callback/',
                                           {'due': self.due()}, format='json').status_code, 404)


class ExportTests(ApiBase):

    def get(self, client, extra='', path='export/'):
        return client.get(url(path, extra))

    def wb(self, resp):
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return openpyxl.load_workbook(BytesIO(resp.content))

    def test_management_workbook(self):
        r = self.get(self.admin_c)
        self.assertIn('pic-analytics_2026-10-01_2026-10-31.xlsx', r['Content-Disposition'])
        wb = self.wb(r)
        self.assertEqual(wb.sheetnames, ['الفلاتر والتعريفات', 'نظرة عامة', 'العملاء', 'الفروع', 'البائعون',
                                         'القنوات', 'الأصناف', 'الولاء والتكرار', 'مركز الاتصال',
                                         'المكالمات الفائتة', 'أرقام جديدة'])
        for ws in wb.worksheets:
            self.assertTrue(ws.sheet_view.rightToLeft, ws.title)
            self.assertEqual(ws.freeze_panes, 'A2', ws.title)
        head = wb['العملاء']['A1']
        self.assertEqual((head.fill.fgColor.rgb[-6:], head.font.b), ('022871', True))
        heads = sheet_headers(wb)
        self.assertIn('الربح الإجمالي', heads['العملاء'])
        self.assertEqual(wb['العملاء'].max_row, 1 + 3)
        labels = [c.value for c in wb['الفروع']['A'][1:]]
        self.assertIn('961 · أ', labels)                                  # "code · name"
        self.assertEqual(wb['المكالمات الفائتة'].max_row, 2)
        self.assertEqual(wb['أرقام جديدة'].max_row, 3)                   # two unlinked numbers

    def test_export_has_no_cost_columns_for_branch_manager(self):
        wb = self.wb(self.get(self.mgr_c))
        self.assertEqual(wb.sheetnames, ['الفلاتر والتعريفات', 'نظرة عامة', 'العملاء', 'الفروع', 'البائعون',
                                         'القنوات', 'الأصناف', 'الولاء والتكرار'])
        for title, headers in sheet_headers(wb).items():
            for h in headers:
                for bad in ('تكلفة', 'ربح', 'هامش'):
                    self.assertNotIn(bad, str(h), (title, h))
        for ws in wb.worksheets:                      # nothing cost-like anywhere in the labels column either
            for row in ws.iter_rows(min_col=1, max_col=1, values_only=True):
                self.assertFalse(any(b in str(row[0] or '') for b in ('تكلفة', 'الربح', 'هامش')), (ws.title, row))

    def test_branch_manager_pic_sheet_keeps_call_columns(self):
        heads = sheet_headers(self.wb(self.get(self.mgr_c)))['العملاء']
        for h in ('مكالمات واردة', 'مكالمات صادرة'):
            self.assertIn(h, heads)
        self.assertFalse([h for h in heads if any(b in str(h) for b in ('تكلفة', 'ربح', 'هامش'))])

    def test_export_audited(self):
        self.get(self.admin_c, '&salesperson=u1')
        e = AuditLog.objects.get(action='pic_analytics_exported')
        self.assertEqual(e.extra['filters']['salesperson'], 'u1')
        self.assertEqual(e.extra['filters']['from'], '2026-10-01')
        self.assertEqual(e.extra['rows']['العملاء'], 1)
        self.assertIn('الفلاتر والتعريفات', e.extra['rows'])
        self.assertEqual(json.loads(json.dumps(e.extra)), e.extra)

    def test_branch_manager_export_scoped_and_audited(self):
        wb = self.wb(self.get(self.mgr_c, '&branch=%d,%d' % (self.ba.pk, self.bb.pk)))   # asks for both branches
        self.assertEqual(wb['الفروع']['A'][1].value, '961 · أ')
        self.assertNotIn('962 · ب', [c.value for c in wb['الفروع']['A']])
        self.assertEqual(AuditLog.objects.filter(action='pic_analytics_exported').count(), 1)

    def test_empty_period_exports_filters_sheet(self):
        r = self.client_get_empty()
        wb = self.wb(r)
        self.assertEqual(wb.sheetnames[0], 'الفلاتر والتعريفات')
        self.assertGreater(wb['الفلاتر والتعريفات'].max_row, 10)
        self.assertEqual(wb['العملاء'].max_row, 1)

    def client_get_empty(self):
        return self.admin_c.get('/api/pic-analytics/export/?from=2025-01-01&to=2025-01-05')

    def test_export_bad_filters(self):
        self.assertEqual(self.admin_c.get('/api/pic-analytics/export/?from=x&to=y').status_code, 400)
        self.assertFalse(AuditLog.objects.filter(action='pic_analytics_exported').exists())
