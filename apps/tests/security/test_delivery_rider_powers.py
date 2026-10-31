"""
N0 H2 + H3 — a rider's GPS pings must not move the drop-off target, and the rider role
cannot cancel or close orders (the dispatcher does). Collect-cash and the rider steps
stay open to the order's own rider (guard(..., rider_ok=True)).
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.delivery.models import DeliveryDriver, DeliveryOrder
from apps.tests.factories import make_branch, make_user
from core.middleware import module_access

DROP = (Decimal('30.0000000'), Decimal('31.0000000'))


class RiderPowersTests(TestCase):
    def setUp(self):
        call_command('seed_permissions', verbosity=0)
        module_access.clear_cache()
        self.branch = make_branch()
        _, prof, self.rider = make_user('h23_rider', role='delivery', branch=self.branch)
        self.driver = DeliveryDriver.objects.create(full_name='سائق', mobile='0100000011',
                                                    staff_profile=prof)
        self.order = DeliveryOrder.objects.create(
            branch=self.branch, customer_name='عميل', assigned_driver=self.driver,
            status=DeliveryOrder.STATUS_OUT, delivery_lat=DROP[0], delivery_lng=DROP[1])

    def tearDown(self):
        module_access.clear_cache()

    def _loc(self, **body):
        return self.rider.post(f'/api/delivery/app/orders/{self.order.pk}/location/', body, format='json')

    def test_location_update_keeps_dropoff_target(self):
        r = self._loc(lat=31.5, lng=32.5)
        self.assertEqual(r.status_code, 200, r.content)
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_lat, DROP[0])
        self.assertEqual(self.order.delivery_lng, DROP[1])
        self.assertEqual(float(self.order.rider_lat), 31.5)
        self.assertEqual(float(self.order.rider_lng), 32.5)
        self.assertIsNotNone(self.order.rider_location_at)

    def test_location_rejects_junk(self):
        for body in ({'lat': 'abc', 'lng': 31}, {'lat': 91, 'lng': 31}, {'lat': 30, 'lng': 181},
                     {'lat': 30}, {}):
            r = self._loc(**body)
            self.assertEqual(r.status_code, 400, body)
        self.order.refresh_from_db()
        self.assertIsNone(self.order.rider_lat)
        self.assertIsNone(self.order.rider_location_at)
        self.assertEqual(self.order.delivery_lat, DROP[0])

    def test_dropoff_geofence_uses_original_target(self):
        self._loc(lat=35.0, lng=35.0)            # rider pings far from the address
        far = self.rider.post(f'/api/delivery/{self.order.pk}/complete/',
                              {'pod_lat': 35.0, 'pod_lng': 35.0}, format='json')
        self.assertEqual(far.status_code, 400, far.content)
        self.assertEqual(far.json().get('geofence'), 'dropoff_too_far')
        ok = self.rider.post(f'/api/delivery/{self.order.pk}/complete/',
                             {'pod_lat': 30.0, 'pod_lng': 31.0}, format='json')
        self.assertEqual(ok.status_code, 200, ok.content)

    def test_rider_cannot_cancel_or_close_own_order(self):
        r = self.rider.post(f'/api/delivery/{self.order.pk}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 403)
        self.order.status = DeliveryOrder.STATUS_DELIVERED
        self.order.save()
        r = self.rider.post(f'/api/delivery/{self.order.pk}/close/')
        self.assertEqual(r.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, DeliveryOrder.STATUS_DELIVERED)

    def test_rider_can_still_collect_cash_and_complete(self):
        r = self.rider.post(f'/api/delivery/{self.order.pk}/complete/',
                            {'pod_lat': 30.0, 'pod_lng': 31.0}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.rider.post(f'/api/delivery/{self.order.pk}/collect-cash/',
                            {'collected_amount': 10}, format='json')
        self.assertEqual(r.status_code, 200, r.content)

    def test_dispatcher_can_cancel_and_close(self):
        for role in ('supervisor', 'admin'):
            c = make_user(f'h23_{role}', role=role, branch=self.branch)[2]
            o = DeliveryOrder.objects.create(branch=self.branch, customer_name='ع',
                                             status=DeliveryOrder.STATUS_READY)
            self.assertEqual(c.post(f'/api/delivery/{o.pk}/cancel/', {'reason': 'x'},
                                    format='json').status_code, 200, role)
            o2 = DeliveryOrder.objects.create(branch=self.branch, customer_name='ع',
                                              status=DeliveryOrder.STATUS_DELIVERED)
            self.assertEqual(c.post(f'/api/delivery/{o2.pk}/close/').status_code, 200, role)

    def test_tracking_shows_recent_rider_location_only(self):
        from django.core import signing
        token = signing.dumps({'oid': self.order.pk}, salt='delivery-track')
        anon = self.client
        # no ping yet: no pin (and certainly not the drop-off address)
        self.assertIsNone(anon.get(f'/api/delivery/track/{token}/').json()['location'])
        self._loc(lat=31.5, lng=32.5)
        loc = anon.get(f'/api/delivery/track/{token}/').json()['location']
        self.assertEqual(loc, {'lat': 31.5, 'lng': 32.5})
        DeliveryOrder.objects.filter(pk=self.order.pk).update(
            rider_location_at=timezone.now() - timedelta(minutes=31))
        self.assertIsNone(anon.get(f'/api/delivery/track/{token}/').json()['location'])

    def test_rider_cannot_patch_order_but_supervisor_can(self):
        for body in ({'delivery_lat': '35.0'}, {'delivery_address': 'x'}, {'notes': 'x'}):
            r = self.rider.patch(f'/api/delivery/{self.order.pk}/', body, format='json')
            self.assertEqual(r.status_code, 403, body)
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_lat, DROP[0])
        sup = make_user('h23_sup_patch', role='supervisor', branch=self.branch)[2]
        r = sup.patch(f'/api/delivery/{self.order.pk}/', {'notes': 'ok'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
