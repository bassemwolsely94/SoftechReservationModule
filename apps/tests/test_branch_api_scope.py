"""GET /api/branches/ scopes, audited kind/order edits."""
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.branches.models import Branch, _reset_hq_code_cache
from apps.tests.factories import make_user


def _mk(code, kind, order=100):
    return Branch.objects.create(softech_branch_id=code, name=f'B{code}', name_ar=f'ف{code}',
                                 code=code, kind=kind, display_order=order)


@override_settings(RBAC_ENFORCEMENT='log')
class BranchApiScopeTests(TestCase):

    def setUp(self):
        _reset_hq_code_cache()
        self.addCleanup(_reset_hq_code_cache)
        self.hq = _mk('100', Branch.KIND_HQ, 0)
        self.r1 = _mk('201', Branch.KIND_RETAIL, 20)
        self.r2 = _mk('202', Branch.KIND_RETAIL, 10)
        self.closed = _mk('203', Branch.KIND_CLOSED)
        self.pending = _mk('204', Branch.KIND_PENDING)
        self.cc = _mk('205', Branch.KIND_CALL_CENTER)
        _, _, self.admin = make_user('bs_admin', role='admin', access_all=True)
        _, _, self.staff = make_user('bs_staff', role='pharmacist')

    def _ids(self, resp):
        data = resp.data.get('results', resp.data) if hasattr(resp.data, 'get') else resp.data
        return [b['softech_branch_id'] for b in data if b['softech_branch_id'] != 'B01']  # B01 = factory user branch

    def test_default_scope_is_live(self):
        ids = self._ids(self.staff.get('/api/branches/'))
        self.assertIn('100', ids)
        for gone in ('203', '204', '205'):
            self.assertNotIn(gone, ids)

    def test_scope_retail_excludes_hq(self):
        ids = self._ids(self.staff.get('/api/branches/?scope=retail'))
        self.assertNotIn('100', ids)
        self.assertEqual(set(ids), {'201', '202'})

    def test_scope_all_admin_only(self):
        self.assertEqual(self.staff.get('/api/branches/?scope=all').status_code, 403)
        self.assertEqual(self.staff.get('/api/branches/?scope=pending').status_code, 403)
        self.assertEqual(len(self._ids(self.admin.get('/api/branches/?scope=all'))), 6)
        self.assertEqual(self._ids(self.admin.get('/api/branches/?scope=pending')), ['204'])
        self.assertEqual(len(self._ids(self.admin.get('/api/branches/?all=1'))), 6)

    def test_unknown_scope_400(self):
        r = self.staff.get('/api/branches/?scope=zzz')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['detail'], 'نطاق الفروع غير معروف')

    def test_results_follow_display_order(self):
        ids = self._ids(self.staff.get('/api/branches/?scope=live'))
        self.assertEqual(ids, ['100', '202', '201'])

    def test_kind_change_audited(self):
        r = self.admin.patch(f'/api/branches/{self.pending.id}/', {'kind': 'retail'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['kind_label'], 'فرع بيع')
        self.assertTrue(r.data['is_live'])
        row = AuditLog.objects.get(action='branch_classified')
        self.assertEqual(row.changes, {'kind': ['pending', 'retail']})
        self.assertEqual(row.object_id, str(self.pending.pk))

    def test_display_order_change_audited(self):
        r = self.admin.patch(f'/api/branches/{self.r1.id}/', {'display_order': 5}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        row = AuditLog.objects.get(action='branch_order_changed')
        self.assertEqual(row.changes, {'display_order': [20, 5]})

    def test_unrelated_patch_not_audited(self):
        self.admin.patch(f'/api/branches/{self.r1.id}/', {'phone': '1'}, format='json')
        self.assertFalse(AuditLog.objects.filter(
            action__in=['branch_classified', 'branch_order_changed']).exists())

    def test_non_admin_cannot_patch_kind(self):
        r = self.staff.patch(f'/api/branches/{self.r1.id}/', {'kind': 'closed'}, format='json')
        self.assertEqual(r.status_code, 403)
