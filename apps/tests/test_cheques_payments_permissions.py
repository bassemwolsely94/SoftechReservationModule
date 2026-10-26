"""
Cheques + payment audit permissions (core.permissions MatrixPermission / deny_unless).
Before 2026-10-26 these endpoints only required a login: any staff member could create,
activate or cancel cheque plans, mark a cheque cleared, close payment exceptions or
delete bank statements. The screens were limited in the frontend only.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.cheques.models import ChequeInstalment, ChequePlan
from apps.payments.models import PaymentException
from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

GRANTS = {
    ('purchasing', 'cheques'):  {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
    ('purchasing', 'finance'):  {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
    ('pharmacist', 'cheques'):  {'view'},
    ('pharmacist', 'finance'):  {'view'},
}


class _Base(TestCase):
    def setUp(self):
        module_access.clear_cache()
        for (role, module), actions in GRANTS.items():
            for a in actions:
                RoleModuleAccess.objects.create(role=role, module=module, action=a)
        self.branch = make_branch()

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role):
        return make_user(f'cp_{role}', role=role, branch=self.branch)[2]


class ChequePermissionTests(_Base):
    def setUp(self):
        super().setUp()
        self.plan = ChequePlan.objects.create(title='خطة', payee_name='مورد', total_amount=Decimal('1000'),
                                              first_due_date=date(2026, 11, 1))
        self.inst = ChequeInstalment.objects.create(plan=self.plan, instalment_no=1, amount=Decimal('1000'),
                                                    nominal_date=date(2026, 11, 1), due_date=date(2026, 11, 1))

    def test_reads_need_view(self):
        for url in ('/api/cheques/plans/', '/api/cheques/treasury/'):
            self.assertEqual(self._client('salesperson').get(url).status_code, 403, url)
            self.assertEqual(self._client('pharmacist').get(url).status_code, 200, url)

    def test_view_only_role_cannot_change_plans(self):
        c = self._client('pharmacist')
        self.assertEqual(c.post(f'/api/cheques/plans/{self.plan.pk}/activate/').status_code, 403)
        self.assertEqual(c.post(f'/api/cheques/plans/{self.plan.pk}/cancel/').status_code, 403)
        self.assertEqual(c.delete(f'/api/cheques/plans/{self.plan.pk}/').status_code, 403)
        self.assertEqual(c.post('/api/cheques/plans/', {}, format='json').status_code, 403)
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status, 'draft')

    def test_activate_and_cancel_need_approve(self):
        c = self._client('purchasing')
        self.assertEqual(c.post(f'/api/cheques/plans/{self.plan.pk}/activate/').status_code, 200)
        self.assertEqual(c.post(f'/api/cheques/plans/{self.plan.pk}/cancel/').status_code, 200)

    def test_marking_cleared_needs_finalize(self):
        url = f'/api/cheques/plans/{self.plan.pk}/instalments/{self.inst.pk}/'
        RoleModuleAccess.objects.create(role='supervisor', module='cheques', action='edit')
        module_access.clear_cache()
        sup = self._client('supervisor')
        self.assertEqual(sup.patch(url, {'status': 'cleared'}, format='json').status_code, 403)
        self.assertNotEqual(sup.patch(url, {'cheque_number': '123'}, format='json').status_code, 403)
        self.inst.refresh_from_db()
        self.assertNotEqual(self.inst.status, 'cleared')
        self.assertEqual(self._client('purchasing').patch(url, {'status': 'cleared'}, format='json').status_code, 200)

    def test_holidays_stay_open(self):
        self.assertEqual(self._client('salesperson').get('/api/cheques/holidays/').status_code, 200)


class PaymentAuditPermissionTests(_Base):
    def setUp(self):
        super().setUp()
        etype = PaymentException._meta.get_field('exception_type').choices[0][0]
        self.exc = PaymentException.objects.create(exception_type=etype)

    def test_reads_need_view(self):
        for url in ('/api/payments/audit/exceptions/', '/api/payments/audit/statements/',
                    '/api/payments/audit/stmt-lines/'):
            self.assertEqual(self._client('salesperson').get(url).status_code, 403, url)
            self.assertEqual(self._client('pharmacist').get(url).status_code, 200, url)

    def test_resolve_and_dismiss_need_approve(self):
        url = f'/api/payments/audit/exceptions/{self.exc.pk}/'
        self.assertEqual(self._client('pharmacist').post(url + 'resolve/', {}, format='json').status_code, 403)
        self.assertEqual(self._client('pharmacist').post(url + 'dismiss/', {}, format='json').status_code, 403)
        self.exc.refresh_from_db()
        self.assertEqual(self.exc.status, PaymentException.STATUS_OPEN)
        self.assertEqual(self._client('purchasing').post(url + 'resolve/', {}, format='json').status_code, 200)

    def test_assign_needs_assign_or_approve(self):
        _, staff, _ = make_user('cp_target', role='purchasing', branch=self.branch)
        url = f'/api/payments/audit/exceptions/{self.exc.pk}/assign/'
        self.assertEqual(self._client('pharmacist').post(url, {'staff_id': staff.pk}, format='json').status_code, 403)
        self.assertEqual(self._client('purchasing').post(url, {'staff_id': staff.pk}, format='json').status_code, 200)

    def test_statement_upload_needs_create(self):
        r = self._client('pharmacist').post('/api/payments/audit/statements/', {})
        self.assertEqual(r.status_code, 403)

    def test_unseeded_matrix_does_not_lock_out(self):
        RoleModuleAccess.objects.all().delete()
        module_access.clear_cache()
        self.assertEqual(self._client('pharmacist').get('/api/payments/audit/exceptions/').status_code, 200)
