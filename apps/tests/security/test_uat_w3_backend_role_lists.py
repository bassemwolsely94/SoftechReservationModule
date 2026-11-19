"""
UAT W3 follow-up (owner 2026-11-19): four backend checks that used role lists now ask the matrix.

* CanPushPosOrders — PUSH_ROLES only while `pos` is unseeded; once seeded a denial of pos create
  is final (it used to let the role back in, and a failed lookup allowed).
* Procurement engine trigger / reclassify / segment override — `purchasing` create / edit (was
  Django is_staff, which ignored the app role).
* Insights «generate» — analytics create, edit or export (compute POSTs, Z-11a); was a role list.
* Gift-coupon screen view — vouchers view plus export or edit; was a settings role list.
Same audience with today's matrix except procurement, where the purchasing role gains the actions.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings

from apps.pos_orders.permissions import CanPushPosOrders
from apps.tests.factories import make_user
from apps.users.models import RoleModuleAccess
from apps.vouchers.coupon_views import can_view
from core.middleware import module_access

from .fixtures import seed_code_matrix


def _deny(role, module, action):
    RoleModuleAccess.objects.filter(role=role, module=module, action=action).update(is_allowed=False)
    module_access.clear_cache()


class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        module_access.clear_cache()

    def tearDown(self):
        module_access.clear_cache()


class PosPushTests(_Base):

    def _allowed(self, role):
        _, profile, _ = make_user(f'w3pos_{role}', role=role)
        req = SimpleNamespace(user=profile.user)
        return CanPushPosOrders().has_permission(req, None)

    def test_matrix_roles_push(self):
        for role in ('pharmacist', 'salesperson', 'call_center', 'supervisor'):
            with self.subTest(role=role):
                self.assertTrue(self._allowed(role))

    def test_a_matrix_denial_is_final(self):
        _deny('pharmacist', 'pos', 'create')
        self.assertFalse(self._allowed('pharmacist'))

    def test_roles_without_pos_create_refused(self):
        for role in ('viewer', 'purchasing', 'delivery', 'accountant'):
            with self.subTest(role=role):
                self.assertFalse(self._allowed(role))

    def test_unseeded_pos_falls_back_to_the_list(self):
        RoleModuleAccess.objects.filter(module='pos').delete()
        module_access.clear_cache()
        self.assertTrue(self._allowed('pharmacist'))
        self.assertFalse(self._allowed('viewer'))


@override_settings(RBAC_ENFORCEMENT='log')
class ProcurementRunTests(_Base):

    def _post(self, role, path, staff=False):
        user, _, client = make_user(f'w3pr_{role}_{int(staff)}', role=role)
        if staff:
            type(user).objects.filter(pk=user.pk).update(is_staff=True)
            user.refresh_from_db()
            client.force_authenticate(user=user)
        with mock.patch('apps.procurement.views.start_thread'):
            return client.post(path, {}, format='json')

    def test_purchasing_role_runs_the_engine(self):
        for path in ('/api/procurement/trigger/', '/api/procurement/reclassify/'):
            with self.subTest(path=path):
                self.assertNotEqual(self._post('purchasing', path).status_code, 403)

    def test_is_staff_alone_no_longer_runs_it(self):
        self.assertEqual(self._post('salesperson', '/api/procurement/trigger/', staff=True).status_code, 403)

    def test_roles_without_purchasing_create_refused(self):
        for role in ('viewer', 'supervisor', 'pharmacist'):
            with self.subTest(role=role):
                self.assertEqual(self._post(role, '/api/procurement/trigger/').status_code, 403)

    def test_segment_override_needs_purchasing_edit(self):
        _, _, client = make_user('w3pr_seg_viewer', role='viewer')
        self.assertEqual(client.patch('/api/procurement/segments/987654321/update/', {}, format='json').status_code, 403)
        _, _, client = make_user('w3pr_seg_purch', role='purchasing')
        self.assertEqual(client.patch('/api/procurement/segments/987654321/update/', {}, format='json').status_code, 404)


@override_settings(RBAC_ENFORCEMENT='log')
class InsightsGenerateTests(_Base):
    URL = '/api/insights/reports/generate/'

    def _post(self, role):
        _, _, client = make_user(f'w3in_{role}', role=role)
        with mock.patch('apps.insights.views.InsightEngine.run', side_effect=RuntimeError('not here')):
            return client.post(self.URL, {}, format='json')

    def test_same_four_roles_generate(self):
        for role in ('supervisor', 'purchasing', 'quality_manager'):
            with self.subTest(role=role):
                self.assertNotEqual(self._post(role).status_code, 403)   # 500 from the mocked engine

    def test_view_only_roles_refused(self):
        for role in ('viewer', 'pharmacist', 'call_center'):
            with self.subTest(role=role):
                self.assertEqual(self._post(role).status_code, 403)

    def test_the_matrix_decides(self):
        _deny('quality_manager', 'analytics', 'export')
        self.assertEqual(self._post('quality_manager').status_code, 403)


class CouponViewTests(_Base):

    def _can(self, role):
        return can_view(make_user(f'w3cp_{role}', role=role)[1])

    def test_same_audience_as_before(self):
        for role, expected in (('admin', True), ('supervisor', True), ('purchasing', True),
                               ('quality_manager', True), ('call_center', False), ('pharmacist', False),
                               ('salesperson', False), ('viewer', False), ('accountant', False)):
            with self.subTest(role=role):
                self.assertEqual(self._can(role), expected)

    def test_the_matrix_decides(self):
        _deny('quality_manager', 'vouchers', 'export')
        self.assertFalse(self._can('quality_manager'))
