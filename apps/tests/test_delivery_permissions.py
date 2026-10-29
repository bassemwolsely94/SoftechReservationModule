"""
Delivery API permissions (apps/delivery/permissions.py): every endpoint checks the
RoleModuleAccess matrix for module 'delivery', and a rider may only act on orders
assigned to them. Before this, any logged-in user could cancel, close or record cash.
"""
from django.test import TestCase

from apps.delivery.models import DeliveryDriver, DeliveryOrder
from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

GRANTS = {
    'viewer':      {'view'},
    'call_center': {'view', 'create', 'assign'},
    'pharmacist':  {'view', 'create', 'edit', 'approve', 'finalize'},
    'supervisor':  {'view', 'create', 'edit', 'approve', 'assign'},
    'delivery':    {'view', 'edit', 'approve', 'finalize'},
}


class DeliveryPermissionTests(TestCase):
    def setUp(self):
        module_access.clear_cache()
        for role, actions in GRANTS.items():
            for a in actions:
                RoleModuleAccess.objects.create(role=role, module='delivery', action=a)
        self.branch = make_branch()
        _, self.rider_profile, self.rider = make_user('rider_a', role='delivery', branch=self.branch)
        _, other_profile, self.other_rider = make_user('rider_b', role='delivery', branch=self.branch)
        self.driver = DeliveryDriver.objects.create(full_name='سائق أ', mobile='0100000001',
                                                    staff_profile=self.rider_profile)
        self.other_driver = DeliveryDriver.objects.create(full_name='سائق ب', mobile='0100000002',
                                                          staff_profile=other_profile)

    def tearDown(self):
        module_access.clear_cache()

    def _order(self, status=DeliveryOrder.STATUS_READY, driver=None):
        return DeliveryOrder.objects.create(branch=self.branch, customer_name='عميل', status=status,
                                            assigned_driver=driver)

    def _client(self, role):
        return make_user(f'del_{role}', role=role, branch=self.branch)[2]

    def test_read_needs_view(self):
        self.assertEqual(self._client('viewer').get('/api/delivery/').status_code, 200)
        self.assertEqual(self._client('salesperson').get('/api/delivery/').status_code, 403)

    def test_viewer_cannot_create_or_edit(self):
        c = self._client('viewer')
        self.assertEqual(c.post('/api/delivery/', {}, format='json').status_code, 403)
        o = self._order()
        self.assertEqual(c.patch(f'/api/delivery/{o.pk}/', {'notes': 'x'}, format='json').status_code, 403)

    def test_cancel_needs_approve(self):
        o = self._order()
        r = self._client('call_center').post(f'/api/delivery/{o.pk}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 403)
        o.refresh_from_db()
        self.assertEqual(o.status, DeliveryOrder.STATUS_READY)
        r = self._client('pharmacist').post(f'/api/delivery/{o.pk}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_close_and_cash_need_finalize_or_approve(self):
        o = self._order(status=DeliveryOrder.STATUS_DELIVERED)
        self.assertEqual(self._client('call_center').post(f'/api/delivery/{o.pk}/collect-cash/',
                                                          {'collected_amount': 10}, format='json').status_code, 403)
        self.assertEqual(self._client('call_center').post(f'/api/delivery/{o.pk}/close/').status_code, 403)
        # supervisor has approve but not finalize — still allowed to close
        self.assertEqual(self._client('supervisor').post(f'/api/delivery/{o.pk}/close/').status_code, 200)

    def test_assign_needs_assign(self):
        o = self._order()
        r = self._client('pharmacist').post(f'/api/delivery/{o.pk}/assign/', {'driver_id': self.driver.pk}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self._client('call_center').post(f'/api/delivery/{o.pk}/assign/', {'driver_id': self.driver.pk}, format='json')
        self.assertNotEqual(r.status_code, 403)

    def test_rider_acts_only_on_own_orders(self):
        mine = self._order(status=DeliveryOrder.STATUS_ASSIGNED, driver=self.driver)
        theirs = self._order(status=DeliveryOrder.STATUS_ASSIGNED, driver=self.other_driver)
        self.assertEqual(self.rider.post(f'/api/delivery/{mine.pk}/accept/').status_code, 200)
        r = self.rider.post(f'/api/delivery/{theirs.pk}/accept/')
        self.assertEqual(r.status_code, 403)
        theirs.refresh_from_db()
        self.assertEqual(theirs.status, DeliveryOrder.STATUS_ASSIGNED)
        # matrix grants the rider role approve, but not on another rider's order
        r = self.rider.post(f'/api/delivery/{theirs.pk}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 403)
        r = self.rider.post(f'/api/delivery/{theirs.pk}/collect-cash/', {'collected_amount': 5}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_rider_records_cash_on_own_order_without_finalize(self):
        RoleModuleAccess.objects.filter(role='delivery', action__in=('finalize', 'approve')).delete()
        module_access.clear_cache()
        mine = self._order(status=DeliveryOrder.STATUS_DELIVERED, driver=self.driver)
        r = self.rider.post(f'/api/delivery/{mine.pk}/collect-cash/', {'collected_amount': 5}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_admin_bypasses_matrix(self):
        o = self._order()
        r = self._client('admin').post(f'/api/delivery/{o.pk}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_unseeded_matrix_does_not_lock_out(self):
        RoleModuleAccess.objects.all().delete()
        module_access.clear_cache()
        o = self._order()
        r = self._client('viewer').post(f'/api/delivery/{o.pk}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_analytics_need_view(self):
        for url in ('/api/delivery/summary/', '/api/delivery/dashboard/', '/api/delivery/routes/'):
            self.assertEqual(self._client('salesperson').get(url).status_code, 403, url)
            self.assertNotEqual(self._client('viewer').get(url).status_code, 403, url)
