"""N3 final fix wave - parked items: admin Z1 guard, admin-only external flags (+ logged audit failure),
whoami tells the banner the mode and row, route phones masked like the order rows."""
from types import SimpleNamespace

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework_simplejwt.tokens import AccessToken

from apps.access.models import ZonePolicy
from apps.tests.factories import make_user


class ParkedItemsTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_admin_z1_must_stay_full(self):
        from apps.tests.factories import make_admin
        _, _, api = make_admin('fw_zp_admin')
        row = ZonePolicy.objects.get(role='admin', zone='Z1')
        url = f'/api/access/zone-policies/{row.pk}/'
        for body in ({'access': 'read_only'}, {'access': 'none'}, {'view_only': True}):
            self.assertEqual(api.patch(url, body, format='json').status_code, 400, body)
        row.refresh_from_db()
        self.assertEqual((row.access, row.view_only), ('full', False))
        self.assertEqual(api.patch(url, {'export': True}, format='json').status_code, 200)
        other = ZonePolicy.objects.get(role='admin', zone='Z2')
        self.assertEqual(api.patch(f'/api/access/zone-policies/{other.pk}/', {'access': 'none'},
                                   format='json').status_code, 200)

    def test_external_flags_admin_role_only(self):
        from apps.tests.factories import make_admin
        _, _, api = make_admin('fw_uf_admin')
        _, ph, _ = make_user('fw_uf_ph', role='pharmacist')
        r = api.patch(f'/api/users/staff/{ph.pk}/', {'external_export': True}, format='json')
        self.assertEqual(r.status_code, 400)
        ph.refresh_from_db()
        self.assertFalse(ph.external_export)
        _, ad, _ = make_user('fw_uf_ad', role='admin')
        self.assertEqual(api.patch(f'/api/users/staff/{ad.pk}/', {'external_export': True},
                                   format='json').status_code, 200)
        self.assertEqual(api.patch(f'/api/users/staff/{ad.pk}/', {'role': 'supervisor'},
                                   format='json').status_code, 200)
        ad.refresh_from_db()
        self.assertFalse(ad.external_export)            # leaving admin clears the flags

    def test_flags_audit_failure_is_logged(self):
        from unittest import mock
        from apps.users.serializers import _log_external_flags
        _, ad, _ = make_user('fw_uf_log', role='admin')
        ad.external_export = True
        with mock.patch('apps.users.serializers.UserActivityLog.objects.create', side_effect=RuntimeError):
            with self.assertLogs('elrezeiky.users', 'ERROR'):
                _log_external_flags(ad, {'external_export': False, 'external_softech_write': False})

    @override_settings(NETWORK_HEADER_TRUSTED=True, NETWORK_PROXY_KEY='', NETWORK_POLICY_ENFORCEMENT='log',
                       ACCESS_POLICY_TTL=0)
    def test_whoami_tells_the_banner_mode_and_row(self):
        user, _, _ = make_user('fw_who', role='pharmacist')
        r = self.client.get('/api/access/whoami/', HTTP_X_ELR_NETWORK='internal',
                            HTTP_AUTHORIZATION=f'Bearer {AccessToken.for_user(user)}')
        data = r.json()
        self.assertEqual((data['access_zone'], data['policy_mode'], data['zone_access']), ('Z2', 'log', 'read_only'))

    def test_route_serializer_masks_phone_like_the_order_rows(self):
        from django.test import RequestFactory
        from apps.delivery.serializers import DeliveryRouteSerializer
        user, _, _ = make_user('fw_route_viewer', role='viewer')
        order = SimpleNamespace(id=1, order_number='D1', route_sequence=1, customer_name='x',
                                customer_phone='01012345678', delivery_address='', delivery_area='',
                                delivery_lat=None, delivery_lng=None, google_maps_url='',
                                total_with_fees=0, payment_method='cash', status='new',
                                get_status_display=lambda: 'new')
        route = SimpleNamespace(orders=SimpleNamespace(order_by=lambda *a: [order]))
        req = RequestFactory().get('/')
        req.user = user
        rows = DeliveryRouteSerializer(context={'request': req}).get_orders(route)
        self.assertNotEqual(rows[0]['customer_phone'], '01012345678')
        self.assertTrue(rows[0]['customer_phone'].endswith('678'))
        self.assertEqual(DeliveryRouteSerializer(context={}).get_orders(route)[0]['customer_phone'], '01012345678')
