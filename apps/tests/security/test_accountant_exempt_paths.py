"""
apps/tests/security/test_accountant_exempt_paths.py

/api/search/, /api/notifications/ and /ws/ are not behind ModuleAccessMiddleware, so the
RBAC_ENFORCED_ROLES rule (the accountant: ledger / finance / cheques / dashboard / tasks only)
is checked in the views themselves:

- universal search drops the customers / orders / reservations groups the role has no view grant
  for (items stay open); every other role sees exactly what it saw before;
- record chatter (REST list + post, live socket) needs the record module's view grant.
"""
import importlib

from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework_simplejwt.tokens import RefreshToken

from apps.notifications.chatter_access import CHATTER_MODULE, can_use_thread
from apps.notifications.models import ChatterMessage
from apps.notifications.views import _ALLOWED_CHATTER_MODELS
from apps.reservations.models import Reservation
from apps.tests.factories import make_branch, make_customer, make_item, make_pharmacist, make_user
from core.middleware import module_access
from core.permissions import enforced_role_allows

from .fixtures import bearer_client, seed_code_matrix

SEARCH = '/api/search/universal'


def _reservation(branch, by):
    return Reservation.objects.create(item=make_item(), branch=branch, quantity_requested=1,
                                      contact_name='عميل', contact_phone='01011111111', created_by=by)


class EnforcedRolesSettingTests(TestCase):

    @override_settings(RBAC_ENFORCED_ROLES='accountant')
    def test_a_plain_string_is_not_a_substring_test(self):
        self.assertEqual(module_access.enforced_roles(), frozenset({'accountant'}))
        self.assertEqual(module_access._mode_for('account'), module_access._mode())

    @override_settings(RBAC_ENFORCED_ROLES='accountant, viewer')
    def test_comma_separated_string(self):
        self.assertEqual(module_access.enforced_roles(), frozenset({'accountant', 'viewer'}))

    @override_settings(RBAC_ENFORCED_ROLES=['accountant'])
    def test_list_becomes_frozenset(self):
        self.assertIsInstance(module_access.enforced_roles(), frozenset)

    @override_settings(RBAC_ENFORCED_ROLES=())
    def test_empty_enforces_nobody(self):
        self.assertEqual(module_access.enforced_roles(), frozenset())


class UniversalSearchGateTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.branch = make_branch()
        cust = make_customer(name='محمد علي', phone='01099887766')
        cust.preferred_branch = self.branch       # the pharmacist's own branch (B-2)
        cust.save()
        self.acc_user, _, _ = make_user('acc_search', role='accountant', branch=self.branch)
        self.ph_user, _, _ = make_user('ph_search', role='pharmacist', branch=self.branch)

    def tearDown(self):
        module_access.clear_cache()

    def test_accountant_gets_no_customers_orders_or_reservations(self):
        r = bearer_client(self.acc_user).get(SEARCH, {'q': 'محمد'})
        self.assertEqual(r.status_code, 200)
        res = r.data['results']
        self.assertEqual(res['customers'], [])
        self.assertEqual(res['orders'], [])
        self.assertEqual(res['reservations'], [])
        self.assertIn('items', res)

    def test_accountant_asking_only_for_customers_gets_nothing(self):
        r = bearer_client(self.acc_user).get(SEARCH, {'q': '01099887766', 'types': 'customers'})
        self.assertEqual(r.data['results'], {'customers': []})

    def test_pharmacist_still_finds_the_customer(self):
        r = bearer_client(self.ph_user).get(SEARCH, {'q': 'محمد'})
        self.assertTrue(r.data['results']['customers'])

    def test_legacy_roles_are_not_narrowed(self):
        # delivery holds no reservations / pos grant, but is not an enforced role: unchanged
        delivery, _, _ = make_user('dl_search', role='delivery', branch=self.branch)
        self.assertTrue(enforced_role_allows(delivery, 'reservations', 'view'))
        self.assertFalse(enforced_role_allows(self.acc_user, 'reservations', 'view'))
        self.assertTrue(enforced_role_allows(self.acc_user, 'ledger', 'view'))


class ChatterGateTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.branch = make_branch()
        self.ph_user, self.ph_prof, _ = make_pharmacist('ch_ph', branch=self.branch)
        self.acc_user, _, _ = make_user('ch_acc', role='accountant', branch=self.branch)
        self.res = _reservation(self.branch, self.ph_prof)

    def tearDown(self):
        module_access.clear_cache()

    def test_every_chattable_model_has_a_module(self):
        self.assertEqual(set(CHATTER_MODULE), set(_ALLOWED_CHATTER_MODELS))

    def test_accountant_cannot_use_a_reservation_thread(self):
        self.assertFalse(can_use_thread(self.acc_user, 'reservation', self.res.pk))
        self.assertTrue(can_use_thread(self.ph_user, 'reservation', self.res.pk))

    def test_rest_list_and_post_refuse_the_accountant(self):
        c = bearer_client(self.acc_user)
        base = f'/api/notifications/chatter/reservation/{self.res.pk}/'
        self.assertEqual(c.get(base).status_code, 403)
        self.assertEqual(c.post(base + 'post/', {'message': 'x'}, format='json').status_code, 403)
        self.assertEqual(c.get(f'/api/notifications/chatter/customer/{self.res.pk}/').status_code, 403)
        self.assertFalse(ChatterMessage.objects.exists())

    def test_rest_unchanged_for_a_role_with_the_grant(self):
        c = bearer_client(self.ph_user)
        base = f'/api/notifications/chatter/reservation/{self.res.pk}/'
        self.assertEqual(c.get(base).status_code, 200)
        self.assertEqual(c.post(base + 'post/', {'message': 'مرحبا'}, format='json').status_code, 201)


class ChatterSocketGateTests(TransactionTestCase):

    def setUp(self):
        import config.asgi
        self.app = importlib.reload(config.asgi).application
        seed_code_matrix()
        self.branch = make_branch()
        self.ph_user, self.ph_prof, _ = make_pharmacist('chs_ph', branch=self.branch)
        self.acc_user, _, _ = make_user('chs_acc', role='accountant', branch=self.branch)
        self.res = _reservation(self.branch, self.ph_prof)

    def tearDown(self):
        module_access.clear_cache()

    def _connects(self, user):
        token = str(RefreshToken.for_user(user).access_token)

        async def go():
            c = WebsocketCommunicator(self.app, f'/ws/chatter/reservation/{self.res.pk}/?token={token}',
                                      headers=[(b'origin', b'http://localhost')])
            ok, _ = await c.connect()
            await c.disconnect()
            return ok
        return async_to_sync(go)()

    def test_accountant_refused_pharmacist_joins(self):
        self.assertFalse(self._connects(self.acc_user))
        self.assertTrue(self._connects(self.ph_user))
