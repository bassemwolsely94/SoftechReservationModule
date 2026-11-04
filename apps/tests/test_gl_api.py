"""General-ledger REST API (finance-gl Task 8)."""
import io

import openpyxl
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.audit.models import AuditLog
from apps.finance.gl.ledger import MESSAGES
from apps.finance.models import GLAccount, GLAccountGroup, LedgerEntry
from apps.tests.factories import make_anon_client, make_user
from core.middleware import module_access

BASE = '/api/finance/gl/'


def _bearer(user):
    """A client authenticated like the browser (Bearer JWT), so ModuleAccessMiddleware sees it."""
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
    return c


def _body(debit='100.00', credit='100.00', date='2026-03-01'):
    return {'entry_date': date, 'book': 'general', 'description': 'قيد تجربة', 'lines': [
        {'account_code': '1101', 'debit': debit, 'credit': '0'},
        {'account_code': '4101', 'debit': '0', 'credit': credit},
    ]}


class GLApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_permissions', verbosity=0)
        cash = GLAccountGroup.objects.create(name='نقدية', section='balance_sheet', order=1)
        sales = GLAccountGroup.objects.create(name='المبيعات', section='trading', order=2)
        GLAccount.objects.create(code='1101', name='الخزينة', group=cash, nature='debit',
                                 account_type='asset', statement_line='cash')
        GLAccount.objects.create(code='4101', name='المبيعات', group=sales, nature='credit',
                                 account_type='revenue', statement_line='net_sales')

    def setUp(self):
        _, self.acct, self.c = make_user('gl_acct', role='accountant')
        _, _, self.viewer = make_user('gl_viewer', role='viewer', access_all=True)
        _, _, self.pharm = make_user('gl_pharm', role='pharmacist')
        _, _, self.admin = make_user('gl_admin', role='admin', access_all=True)

    def _draft(self, **kw):
        r = self.c.post(BASE + 'entries/', _body(**kw), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        return r.data

    def test_requires_auth(self):
        self.assertIn(make_anon_client().get(BASE + 'accounts/').status_code, (401, 403))

    def test_non_all_branch_user_403(self):
        self.assertEqual(self.pharm.get(BASE + 'accounts/').status_code, 403)

    def test_accountant_can_create_and_approve(self):
        d = self._draft()
        self.assertEqual(d['status'], 'draft')
        self.assertEqual(d['total_debit'], '100.00')
        r = self.c.post(f'{BASE}entries/{d["id"]}/approve/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['number'], 'JV-2026-000001')
        self.assertEqual(r.data['created_by_name'], r.data['approved_by_name'])
        lst = self.c.get(BASE + 'entries/', {'status': 'approved'})
        self.assertEqual([e['number'] for e in lst.data['results']], ['JV-2026-000001'])
        self.assertEqual(lst.data['results'][0]['total_debit'], '100.00')

    def test_viewer_cannot_approve(self):
        d = self._draft()
        self.assertEqual(self.viewer.post(f'{BASE}entries/{d["id"]}/approve/').status_code, 403)
        self.assertEqual(self.viewer.post(BASE + 'entries/', _body(), format='json').status_code, 403)

    def test_put_on_approved_entry_409(self):
        d = self._draft()
        self.c.post(f'{BASE}entries/{d["id"]}/approve/')
        r = self.c.put(f'{BASE}entries/{d["id"]}/', _body(debit='5.00', credit='5.00'), format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.data['code'], 'not_draft')

    def test_delete_approved_entry_refused(self):
        d = self._draft()
        self.c.post(f'{BASE}entries/{d["id"]}/approve/')
        self.assertEqual(self.c.delete(f'{BASE}entries/{d["id"]}/').status_code, 409)
        d2 = self._draft()
        self.assertEqual(self.c.delete(f'{BASE}entries/{d2["id"]}/').status_code, 204)
        self.assertFalse(LedgerEntry.objects.filter(pk=d2['id']).exists())

    def test_bulk_approve_reports_each(self):
        ok = self._draft()
        bad = self._draft(credit='90.00')
        r = self.c.post(BASE + 'entries/approve/', {'ids': [ok['id'], bad['id']]}, format='json')
        self.assertEqual(r.status_code, 200)
        by_id = {x['id']: x for x in r.data['results']}
        self.assertTrue(by_id[ok['id']]['ok'])
        self.assertFalse(by_id[bad['id']]['ok'])
        self.assertEqual(by_id[bad['id']]['code'], 'unbalanced')

    def test_ledger_error_shape(self):
        d = self._draft(credit='90.00')
        r = self.c.post(f'{BASE}entries/{d["id"]}/approve/')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'unbalanced')
        self.assertIn('متزن', r.data['detail'])

    def test_three_decimals_rejected_with_line(self):
        r = self.c.post(BASE + 'entries/', _body(debit='10.005', credit='10.005'), format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['code'], 'bad_amount')
        self.assertIn('السطر 1', r.data['detail'])

    def test_reverse(self):
        d = self._draft()
        self.c.post(f'{BASE}entries/{d["id"]}/approve/')
        self.assertEqual(self.c.post(f'{BASE}entries/{d["id"]}/reverse/', {}).status_code, 400)
        r = self.c.post(f'{BASE}entries/{d["id"]}/reverse/', {'reason': 'خطأ'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['reverses'], d['id'])
        again = self.c.post(f'{BASE}entries/{d["id"]}/reverse/', {'reason': 'x'}, format='json')
        self.assertEqual(again.status_code, 409)

    def test_trial_balance_and_statement(self):
        d = self._draft()
        self.c.post(f'{BASE}entries/{d["id"]}/approve/')
        tb = self.c.get(BASE + 'reports/trial-balance/', {'from': '2026-01-01', 'to': '2026-12-31'})
        self.assertEqual(tb.status_code, 200)
        total = tb.data[-1]
        self.assertTrue(total['is_total'])
        self.assertEqual(total['closing_debit'], total['closing_credit'])
        st = self.c.get(BASE + 'reports/account-statement/',
                        {'code': '1101', 'from': '2026-01-01', 'to': '2026-12-31'})
        self.assertEqual(st.data['closing_balance'], '100.00')
        self.assertEqual(self.c.get(BASE + 'reports/trial-balance/').status_code, 400)

    def test_statements_endpoints(self):
        for path, params in (('statements', {'from': '2026-01-01', 'to': '2026-12-31'}),
                             ('position', {'as_of': '2026-12-31'}),
                             ('branch-pl', {'from': '2026-01-01', 'to': '2026-12-31'}),
                             ('comparison', {'years': '2025,2026'})):
            r = self.c.get(f'{BASE}reports/{path}/', params)
            self.assertEqual(r.status_code, 200, (path, r.content[:200]))

    def test_trial_balance_xlsx_requires_export(self):
        params = {'from': '2026-01-01', 'to': '2026-12-31', 'format': 'xlsx'}
        r = self.c.get(BASE + 'reports/trial-balance/', params)
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])
        self.assertEqual(self.viewer.get(BASE + 'reports/trial-balance/', params).status_code, 403)

    def test_account_patch_needs_edit(self):
        r = self.c.patch(BASE + 'accounts/1101/', {'name': 'خزينة'}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.admin.patch(BASE + 'accounts/1101/', {'name': 'خزينة الرئيسي'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(GLAccount.objects.get(code='1101').name, 'خزينة الرئيسي')

    def test_accounts_search_and_filters(self):
        r = self.c.get(BASE + 'accounts/', {'q': 'خزين'})
        self.assertEqual([a['code'] for a in r.data], ['1101'])
        self.assertEqual(r.data[0]['group']['name'], 'نقدية')

    # ── safeguards ported from the reviewed parallel API (75ed7de5) ─────────────
    @override_settings(RBAC_ENFORCEMENT='enforce')
    def test_module_middleware_maps_gl_to_ledger(self):
        """/api/finance/gl/ is the `ledger` module: the accountant (finance view only, ledger
        create/approve) can write under enforce; a branch user is still refused.
        Bearer clients: the middleware runs before DRF, so force_authenticate would bypass it."""
        module_access.clear_cache()
        c = _bearer(self.acct.user)
        r = c.post(BASE + 'entries/', _body(), format='json')
        self.assertEqual(r.status_code, 201, r.content)
        eid = r.data['id']
        r = c.put(f'{BASE}entries/{eid}/', _body(debit='5.00', credit='5.00'), format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(c.post(f'{BASE}entries/{eid}/approve/').status_code, 200)
        r = c.post(f'{BASE}entries/{eid}/reverse/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        d2 = c.post(BASE + 'entries/', _body(), format='json').data
        self.assertEqual(c.delete(f'{BASE}entries/{d2["id"]}/').status_code, 204)
        # the middleware itself still refuses a role without any ledger write grant
        viewer = _bearer(get_user_model().objects.get(username='gl_viewer'))
        r = viewer.post(BASE + 'entries/', _body(), format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json().get('module'), 'ledger')

    def test_module_middleware_only_exact_gl_segment(self):
        from core.middleware.module_access import required
        self.assertEqual(required('/api/finance/gl/entries/', 'POST')[0], 'ledger')
        self.assertEqual(required('/api/finance/gl/accounts/', 'GET'), ('ledger', ('view',)))
        self.assertNotEqual((required('/api/finance/glx/', 'POST') or ('',))[0], 'ledger')
        self.assertNotEqual((required('/api/finance/accounts/', 'GET') or ('',))[0], 'ledger')

    def test_conflict_codes_409_others_400(self):
        d = self._draft()
        r = self.c.post(f'{BASE}entries/{d["id"]}/reverse/', {'reason': 'x'}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (409, 'not_approved'))
        self.assertEqual(r.data['detail'], MESSAGES['not_approved'])
        self.c.post(f'{BASE}entries/{d["id"]}/approve/')
        mirror = self.c.post(f'{BASE}entries/{d["id"]}/reverse/', {'reason': 'x'}, format='json').data
        r = self.c.post(f'{BASE}entries/{mirror["id"]}/reverse/', {'reason': 'y'}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (409, 'is_reversal'))
        r = self.c.post(f'{BASE}entries/{mirror["id"]}/approve/')
        self.assertEqual((r.status_code, r.data['code']), (409, 'not_draft'))
        bad = self._draft(credit='90.00')
        r = self.c.post(f'{BASE}entries/{bad["id"]}/approve/')
        self.assertEqual((r.status_code, r.data['code']), (400, 'unbalanced'))

    def test_notes_saved_in_audited_draft(self):
        body = {**_body(), 'notes': 'ملاحظة أولى'}
        d = self.c.post(BASE + 'entries/', body, format='json').data
        self.assertEqual(d['notes'], 'ملاحظة أولى')
        log = AuditLog.objects.filter(action='gl_entry_draft_saved', object_id=str(d['id'])).latest('id')
        self.assertEqual(log.new_data['notes'], 'ملاحظة أولى')
        r = self.c.put(f'{BASE}entries/{d["id"]}/', {**_body(), 'notes': 'ثانية'}, format='json')
        self.assertEqual(r.data['notes'], 'ثانية')
        log = AuditLog.objects.filter(action='gl_entry_draft_saved', object_id=str(d['id'])).latest('id')
        self.assertEqual((log.old_data['notes'], log.new_data['notes']), ('ملاحظة أولى', 'ثانية'))
        # no notes key → unchanged
        r = self.c.put(f'{BASE}entries/{d["id"]}/', _body(), format='json')
        self.assertEqual(r.data['notes'], 'ثانية')
        r = self.c.put(f'{BASE}entries/{d["id"]}/', {**_body(), 'notes': 'x' * 4001}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (400, 'bad_input'))
        self.assertEqual(LedgerEntry.objects.get(pk=d['id']).notes, 'ثانية')

    def test_closing_stock_param_and_warnings(self):
        d = self._draft()
        self.c.post(f'{BASE}entries/{d["id"]}/approve/')
        params = {'from': '2026-01-01', 'to': '2026-12-31'}
        r = self.c.get(BASE + 'reports/statements/', params)
        self.assertEqual(r.data['stock_basis'], 'missing')
        self.assertTrue(r.data['warnings'])
        r = self.c.get(BASE + 'reports/statements/', {**params, 'closing_stock': '40.00'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['stock_basis'], 'supplied')
        self.assertEqual(r.data['closing_stock'], '40.00')
        r = self.c.get(BASE + 'reports/position/', {'as_of': '2026-12-31', 'closing_stock': '40'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['stock_basis'], 'supplied')
        self.assertIn('unclosed_pl', r.data)
        self.assertIn('warnings', r.data)
        for bad in ('1.005', '-1', 'abc', 'NaN', 'Infinity', '1e16'):
            for path, p in (('statements', params), ('position', {'as_of': '2026-12-31'})):
                r = self.c.get(f'{BASE}reports/{path}/', {**p, 'closing_stock': bad})
                self.assertEqual(r.status_code, 400, (path, bad))
                self.assertEqual(r.data['code'], 'bad_amount')
        for path, p in (('statements', params), ('position', {'as_of': '2026-12-31'})):
            r = self.c.get(f'{BASE}reports/{path}/', {**p, 'format': 'xlsx'})
            self.assertEqual(r.status_code, 200)
            ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
            self.assertTrue(str(ws.cell(row=3, column=1).value).startswith('⚠'), path)

    def test_xlsx_permission_checked_before_report(self):
        # the viewer is refused before the (invalid) range is even parsed
        r = self.viewer.get(BASE + 'reports/statements/', {'from': 'bad', 'format': 'xlsx'})
        self.assertEqual(r.status_code, 403)

    def test_bulk_approve_dedupes(self):
        d = self._draft()
        r = self.c.post(BASE + 'entries/approve/', {'ids': [d['id'], d['id'], str(d['id'])]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['results']), 1)
        self.assertEqual(r.data['approved'], 1)
        r = self.c.post(BASE + 'entries/approve/', {'ids': list(range(1, 502))}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_account_statement_unknown_code_404_and_bad_range(self):
        r = self.c.get(BASE + 'reports/account-statement/',
                       {'code': '9999', 'from': '2026-01-01', 'to': '2026-12-31'})
        self.assertEqual(r.status_code, 404)
        r = self.c.get(BASE + 'reports/trial-balance/', {'from': '2026-12-31', 'to': '2026-01-01'})
        self.assertEqual((r.status_code, r.data['code']), (400, 'bad_input'))

    def test_import_upload_validation(self):
        r = self.admin.post(BASE + 'accounts/import/',
                            {'file': SimpleUploadedFile('tb.csv', b'a,b'), 'dry_run': 'true'})
        self.assertEqual((r.status_code, r.data['code']), (400, 'bad_file'))
        r = self.admin.post(BASE + 'accounts/import/',
                            {'file': SimpleUploadedFile('tb.xlsx', b'not a zip'), 'dry_run': 'true'})
        self.assertEqual((r.status_code, r.data['code']), (400, 'bad_file'))
        with override_settings(MAX_UPLOAD_FILE_SIZE=10):
            r = self.admin.post(BASE + 'accounts/import/',
                                {'file': SimpleUploadedFile('tb.xlsx', b'x' * 9), 'dry_run': 'true'})
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.data['code'], 'bad_file')

    def test_account_patch_audited_only_on_change(self):
        self.admin.patch(BASE + 'accounts/1101/', {'name': 'خزينة 2'}, format='json')
        self.admin.patch(BASE + 'accounts/1101/', {'name': 'خزينة 2'}, format='json')
        pk = str(GLAccount.objects.get(code='1101').pk)
        logs = AuditLog.objects.filter(action='gl_account_updated', object_id=pk)
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.get().new_data['name'], 'خزينة 2')

    def test_write_without_staff_profile_refused(self):
        # refused by the matrix permission today; the views' no_profile guard backs it up
        su = get_user_model().objects.create_superuser('gl_su_noprofile', 'su@example.com', 'x-Pass-123!')
        c = APIClient()
        c.force_authenticate(su)
        r = c.post(BASE + 'entries/', _body(), format='json')
        self.assertEqual(r.status_code, 403, r.content)
        self.assertFalse(LedgerEntry.objects.exists())
