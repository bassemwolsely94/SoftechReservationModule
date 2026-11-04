"""
apps/tests/test_usage_print.py — usage-instructions slip (Project 5).

Invoice lookup by (branch, 115, docnumber, docdate) from the sales mirror with a read-only live
fallback; deterministic suggestions; a human confirms every line before printing; audit.
"""
import datetime as _dt
import tempfile
from decimal import Decimal
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
from apps.usage_print import lookup
from apps.usage_print.models import UsageSheet, UsageSheetLine

from .factories import make_branch, make_branch2, make_customer, make_item, make_user

_PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
        b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00'
        b'\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82')


def _sale(branch, number, day, customer, lines, phcode='', doc_code='115'):
    ph = PurchaseHistory.objects.create(
        customer=customer, branch=branch, doc_code=doc_code, docnumber=str(number),
        softech_invoice_id=f'{branch.softech_branch_id}-{doc_code}-{number}-{day.strftime("%Y%m%d")}',
        invoice_date=timezone.make_aware(_dt.datetime.combine(day, _dt.time())), softech_phcode=phcode)
    for item, qty in lines:
        PurchaseHistoryLine.objects.create(purchase=ph, item=item, quantity=Decimal(qty),
                                           unit_price=Decimal('10'), line_total=Decimal('10'))
    return ph


class _Base(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.b1, self.b2 = make_branch(), make_branch2()
        self.u, self.ph_profile, self.api = make_user('up_pharm', role='pharmacist', branch=self.b1)
        self.cust = make_customer()
        self.cust.softech_pic = '01HD14'
        self.cust.save()
        self.brilique = make_item('BRILIQUE 90MG', 'BR090')
        self.aspirin = make_item('ASPIRIN PROTECT', 'AS100')

    def get(self, number, branch=None, day=None):
        q = {'number': number, 'branch': (branch or self.b1).softech_branch_id}
        if day:
            q['date'] = day.isoformat()
        return self.api.get('/api/usage-print/sheet/', q)

    def act(self, line_id, action, text=''):
        return self.api.post(f'/api/usage-print/lines/{line_id}/', {'action': action, 'text': text}, format='json')


@override_settings(USAGE_PRINT_ENABLED=False)
class FlagOffTests(_Base):
    def test_everything_404_and_menu_hidden(self):
        _sale(self.b1, 500, self.today, self.cust, [(self.brilique, 1)])
        self.assertEqual(self.get(500).status_code, 404)
        self.assertEqual(self.api.get('/api/usage-print/settings/').status_code, 404)
        self.assertFalse(self.api.get('/api/auth/me/').json()['can_usage_print'])


@override_settings(USAGE_PRINT_ENABLED=True, MEDIA_ROOT=tempfile.mkdtemp())
class SheetTests(_Base):
    def test_menu_flag_on(self):
        self.assertTrue(self.api.get('/api/auth/me/').json()['can_usage_print'])

    def test_same_number_other_branch_or_day_never_mixed(self):
        _sale(self.b1, 500, self.today, self.cust, [(self.brilique, 1)])
        _sale(self.b2, 500, self.today, self.cust, [(self.aspirin, 1)])
        _sale(self.b1, 500, self.today - _dt.timedelta(days=1), self.cust, [(self.aspirin, 2)])
        r = self.get(500)
        self.assertEqual(r.status_code, 200)
        self.assertEqual([ln['itemcode'] for ln in r.json()['lines']], ['BR090'])
        r = self.get(500, day=self.today - _dt.timedelta(days=1))
        self.assertEqual([ln['quantity'] for ln in r.json()['lines']], ['2.000'])

    def test_other_branch_forbidden_without_reading_softech(self):
        with patch('apps.usage_print.views.find_invoice') as fi:
            r = self.get(500, branch=self.b2)
        self.assertEqual(r.status_code, 403)
        fi.assert_not_called()

    def test_return_doc_and_old_date_and_bad_number(self):
        _sale(self.b1, 501, self.today, self.cust, [(self.brilique, 1)], doc_code='30')
        with patch('apps.usage_print.lookup._read_live', return_value=[]):
            self.assertEqual(self.get(501).status_code, 404)
        self.assertFalse(UsageSheet.objects.exists())
        self.assertEqual(self.get(501, day=self.today - _dt.timedelta(days=30)).status_code, 400)
        self.assertEqual(self.get('abc').status_code, 400)

    def test_multi_batch_rows_are_summed(self):
        _sale(self.b1, 502, self.today, self.cust, [(self.brilique, 1), (self.brilique, 2)])
        lines = self.get(502).json()['lines']
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]['quantity'], '3.000')

    def test_patient_name_only_for_real_pic(self):
        _sale(self.b1, 503, self.today, self.cust, [(self.brilique, 1)], phcode='01HD14')
        _sale(self.b1, 504, self.today, self.cust, [(self.brilique, 1)], phcode='')
        self.assertEqual(self.get(503).json()['patient_name'], self.cust.name)
        self.assertEqual(self.get(504).json()['patient_name'], '')

    def test_print_locked_until_every_line_decided_then_audited(self):
        _sale(self.b1, 505, self.today, self.cust, [(self.brilique, 1), (self.aspirin, 1)])
        s = self.get(505).json()
        self.assertFalse(s['ready'])
        url = f'/api/usage-print/sheets/{s["id"]}/print/'
        self.assertEqual(self.api.post(url, {'layout': 'single'}, format='json').status_code, 409)
        a, b = s['lines']
        self.assertEqual(self.act(a['id'], 'confirm', '').status_code, 400)   # empty text refused
        self.assertEqual(self.act(a['id'], 'confirm', 'قرص واحد مرتين يوميا بعد الأكل').status_code, 200)
        self.assertEqual(self.api.post(url, {'layout': 'single'}, format='json').status_code, 409)
        r = self.act(b['id'], 'exclude')
        self.assertTrue(r.json()['ready'])
        r = self.api.post(url, {'layout': 'per_item'}, format='json')
        self.assertEqual(r.status_code, 200)
        slip = r.json()['slip']
        self.assertEqual(slip['layout'], 'per_item')
        self.assertEqual([i['text'] for i in slip['items']], ['قرص واحد مرتين يوميا بعد الأكل'])
        self.api.post(url, {'layout': 'single'}, format='json')
        sheet = UsageSheet.objects.get(pk=s['id'])
        self.assertEqual(sheet.print_count, 2)
        self.assertEqual(sheet.last_printed_by, self.ph_profile)
        self.assertEqual(AuditLog.objects.filter(action='usage_sheet_printed').count(), 2)
        self.assertEqual(AuditLog.objects.filter(action='usage_line_confirmed').count(), 1)
        self.assertEqual(AuditLog.objects.filter(action='usage_line_excluded').count(), 1)

    def test_reset_with_new_text_unconfirms(self):
        _sale(self.b1, 506, self.today, self.cust, [(self.brilique, 1)])
        ln = self.get(506).json()['lines'][0]
        self.act(ln['id'], 'confirm', 'قرص واحد')
        r = self.act(ln['id'], 'reset', 'نصف قرص')
        line = r.json()['lines'][0]
        self.assertEqual((line['status'], line['text']), ('pending', 'نصف قرص'))
        self.assertFalse(r.json()['ready'])

    def test_suggestion_order(self):
        other = make_customer('مريض آخر', '01099999999')
        # two other patients confirmed "A" for Brilique; our patient once confirmed "B"
        for n, cust, text in [(600, other, 'A'), (601, other, 'A'), (602, self.cust, 'B')]:
            _sale(self.b1, n, self.today, cust, [(self.brilique, 1)],
                  phcode='01HD14' if cust == self.cust else '')
            ln = self.get(n).json()['lines'][0]
            self.act(ln['id'], 'confirm', text)
        _sale(self.b1, 603, self.today, self.cust, [(self.brilique, 1), (self.aspirin, 1)], phcode='01HD14')
        lines = {ln['itemcode']: ln for ln in self.get(603).json()['lines']}
        self.assertEqual((lines['BR090']['text'], lines['BR090']['suggestion_source']), ('B', 'patient_last'))
        self.assertEqual(lines['AS100']['suggestion_source'], 'none')
        _sale(self.b1, 604, self.today, other, [(self.brilique, 1)])   # unnamed → most common
        ln = self.get(604).json()['lines'][0]
        self.assertEqual((ln['text'], ln['suggestion_source']), ('A', 'item_common'))
        self.assertEqual(ln['status'], 'pending')   # a suggestion is never pre-confirmed

    def test_curated_suggestion_from_approved_counselling_only(self):
        from apps.counselling.services import approve
        from apps.counselling.models import CounsellingContent, CounsellingContentItem
        c = CounsellingContent.objects.create(title='Aspirin', dose_ar='قرص', frequency_ar='مرة يوميا',
                                              with_food='after', created_by=self.ph_profile)
        CounsellingContentItem.objects.create(content=c, item=self.aspirin, linked_by=self.ph_profile)
        _sale(self.b1, 610, self.today, self.cust, [(self.aspirin, 1)])
        with override_settings(COUNSELLING_CONTENT_ENABLED=True):   # draft is never offered
            self.assertEqual(self.get(610).json()['lines'][0]['suggestion_source'], 'none')
            approve(self.ph_profile, c)
            _sale(self.b1, 611, self.today, self.cust, [(self.aspirin, 1)])
            ln = self.get(611).json()['lines'][0]
            self.assertEqual((ln['text'], ln['suggestion_source']), ('قرص — مرة يوميا — بعد الأكل', 'curated'))
            self.assertEqual(ln['status'], 'pending')
        _sale(self.b1, 612, self.today, self.cust, [(self.aspirin, 1)])   # content switch off → nothing
        self.assertEqual(self.get(612).json()['lines'][0]['suggestion_source'], 'none')

    def test_reopen_after_invoice_changed(self):
        ph = _sale(self.b1, 507, self.today, self.cust, [(self.brilique, 1), (self.aspirin, 1)])
        s = self.get(507).json()
        for ln in s['lines']:
            self.act(ln['id'], 'confirm', 'x')
        PurchaseHistoryLine.objects.filter(purchase=ph, item=self.aspirin).update(quantity=Decimal('2'))
        s = self.get(507).json()
        self.assertTrue(s['invoice_changed'])
        st = {ln['itemcode']: ln['status'] for ln in s['lines']}
        self.assertEqual(st, {'BR090': 'confirmed', 'AS100': 'pending'})
        self.assertFalse(self.get(507).json()['invoice_changed'])   # quiet again once seen

    def test_live_fallback_and_unreachable(self):
        rows = [('BR090', Decimal('1'), '01HD14', '1500'), ('BR090', Decimal('1'), '01HD14', '1500')]
        with patch('apps.usage_print.lookup._read_live', return_value=rows):
            s = self.get(700).json()
        self.assertEqual(s['source'], 'live')
        self.assertEqual(s['lines'][0]['quantity'], '2.000')
        self.assertEqual(s['patient_name'], self.cust.name)
        with patch('apps.usage_print.lookup._read_live', side_effect=lookup.LiveUnavailable('down')):
            r = self.get(701)
        self.assertEqual(r.status_code, 503)
        self.assertIn('حاول', r.json()['detail'])

    def test_live_read_tries_branch_then_hq_and_never_bare_docnumber(self):
        executed = []

        class Cur:
            def execute(self, sql, params=None, timeout=None):
                executed.append((sql, params))

            def fetchall(self):
                return []

        class Conn:
            def cursor(self):
                return Cur()

            def close(self):
                pass

        self.b1.db_host = '10.0.0.5'
        self.b1.save()
        with patch('config.sybase.get_branch_connection', side_effect=RuntimeError('node down')), \
                patch('config.sybase.get_sybase_connection', return_value=Conn()):
            self.assertIsNone(lookup.from_live(self.b1, 900, self.today))
        sql, params = executed[0]
        self.assertIn('st.branchcode = ?', sql)
        self.assertIn("st.doccode = '115'", sql)
        self.assertIn('st.docdate = ?', sql)
        self.assertEqual(params, [self.b1.softech_branch_id, 900, self.today.strftime('%Y%m%d')])

    def test_prescription_attach_and_rules(self):
        _sale(self.b1, 508, self.today, self.cust, [(self.brilique, 1)])
        sid = self.get(508).json()['id']
        url = f'/api/usage-print/sheets/{sid}/prescription/'
        bad = SimpleUploadedFile('x.pdf', b'%PDF-1.4', content_type='application/pdf')
        self.assertEqual(self.api.post(url, {'prescription_image': bad}, format='multipart').status_code, 400)
        ok = SimpleUploadedFile('rx.png', _PNG, content_type='image/png')
        r = self.api.post(url, {'prescription_image': ok}, format='multipart')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['prescription_origin'], 'sheet')
        self.assertTrue(AuditLog.objects.filter(action='usage_rx_attached').exists())

    def test_settings_edit_needs_edit_permission(self):
        body = {'presets': {'timing': ['بعد الأكل']}, 'slip': {'usage_print.hotline': '19000'}}
        self.assertEqual(self.api.put('/api/usage-print/settings/', body, format='json').status_code, 403)
        _, _, sup = make_user('up_sup', role='supervisor', branch=self.b1)
        r = sup.put('/api/usage-print/settings/', body, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['presets']['timing'], ['بعد الأكل'])
        self.assertEqual(r.json()['slip']['usage_print.hotline'], '19000')
        self.assertTrue(AuditLog.objects.filter(action='usage_settings_changed').exists())

    def test_role_without_module_gets_404(self):
        _, _, cc = make_user('up_cc', role='call_center', branch=self.b1)
        self.assertEqual(cc.get('/api/usage-print/settings/').status_code, 404)

    def test_line_of_other_branch_hidden(self):
        _, _, admin = make_user('up_admin', role='admin', access_all=True)
        _sale(self.b2, 509, self.today, self.cust, [(self.brilique, 1)])
        r = admin.get('/api/usage-print/sheet/', {'number': 509, 'branch': self.b2.softech_branch_id})
        lid = r.json()['lines'][0]['id']
        self.assertEqual(self.act(lid, 'confirm', 'x').status_code, 404)
        self.assertEqual(UsageSheetLine.objects.get(pk=lid).status, 'pending')
