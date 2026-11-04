"""General-ledger REST API (finance-gl Task 8)."""
from django.core.management import call_command
from django.test import TestCase

from apps.finance.models import GLAccount, GLAccountGroup, LedgerEntry
from apps.tests.factories import make_anon_client, make_user

BASE = '/api/finance/gl/'


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
