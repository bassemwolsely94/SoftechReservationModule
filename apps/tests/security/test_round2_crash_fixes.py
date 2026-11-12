"""
Round 2 close-out: the 93 `role_crashes` lines R3 found once the role sweep used real records.

Each test plants the same neutral record the sweep plants (canary Planter) and asserts a clear
answer instead of a 500. SOFTECH and the network are offline (Tripwire).
"""
import logging

from django.apps import apps
from django.test import TestCase

from apps.tests.factories import make_branch
from apps.users.models import StaffProfile

from .canary import Planter
from .fixtures import role_clients, seed_code_matrix
from .routes import Tripwire


class CrashFixTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.branch = make_branch()
        cls.clients = role_clients(cls.branch)
        admin = StaffProfile.objects.select_related('user').get(user__username='sec_admin')
        cls.planter = Planter(cls.branch, admin.user, admin)

    def setUp(self):
        self.admin = self.clients['admin']
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)

    def plant(self, label):
        obj = self.planter.instance(apps.get_model(label))
        self.assertIsNotNone(obj, f'planter could not build {label}')
        return obj

    def test_demand_action_not_allowed_from_status_is_400(self):
        demand = self.plant('demand.DemandRecord')
        self.assertEqual(demand.status, 'new')
        for action in ('follow-up', 'stock-eta', 'suggest-transfer', 'flag-purchasing', 'fulfill'):
            with self.subTest(action=action), Tripwire():
                r = self.admin.post(f'/api/demand/{demand.pk}/{action}/', {}, format='json')
                self.assertEqual(r.status_code, 400, r.content[:200])
                self.assertIn('لا يمكن الانتقال', r.json()['detail'])
        demand.refresh_from_db()
        self.assertEqual(demand.status, 'new')

    def test_insurance_client_and_subclient_in_use_refuse_delete_with_409(self):
        claim = self.plant('insurance.InsuranceClaim')
        sub = claim.subclient
        for path, model, pk in ((f'/api/insurance/subclients/{sub.pk}/', type(sub), sub.pk),
                                (f'/api/insurance/clients/{sub.client_id}/', type(sub.client), sub.client_id)):
            with self.subTest(path=path), Tripwire():
                r = self.admin.delete(path)
                self.assertEqual(r.status_code, 409, r.content[:200])
                self.assertTrue(r.json()['detail'])
                self.assertTrue(model.objects.filter(pk=pk).exists())

    def test_request_replication_with_softech_offline_is_503(self):
        req = self.plant('discount_approvals.ItemPriceChangeRequest')
        with Tripwire():
            r = self.admin.get(f'/api/pricing-approvals/{req.pk}/replication/')
        self.assertEqual(r.status_code, 503, r.content[:200])

    def test_reservation_with_an_image_row_without_file_still_opens(self):
        img = self.plant('reservations.ReservationImage')
        self.assertFalse(img.image)
        for path in (f'/api/reservations/{img.reservation_id}/',
                     f'/api/reservations/{img.reservation_id}/images/'):
            with self.subTest(path=path), Tripwire():
                r = self.admin.get(path)
                self.assertEqual(r.status_code, 200, r.content[:200])

    def test_forecast_scenario_refuses_an_impossible_target_month(self):
        """A scenario for year 1 or month 13 made «generate» fail (year 0 / month 13 bounds)."""
        for bad in ({'year': 1, 'month': 5}, {'year': 2026, 'month': 13}, {'year': 2026, 'month': 0}):
            with self.subTest(**bad), Tripwire():
                r = self.admin.post('/api/forecasting/scenarios/', {'name': 'x', **bad}, format='json')
                self.assertEqual(r.status_code, 400, r.content[:200])
                self.assertTrue(set(r.json()) & {'year', 'month'})

    def test_transits_with_a_non_numeric_doc_number_still_list(self):
        t = self.plant('transits.InTransitTransfer')
        self.assertFalse(t.erp_doc_number.isdigit())
        for path in ('/api/transits/', f'/api/transits/{t.pk}/'):
            with self.subTest(path=path), Tripwire():
                r = self.admin.get(path)
                self.assertEqual(r.status_code, 200, r.content[:200])
