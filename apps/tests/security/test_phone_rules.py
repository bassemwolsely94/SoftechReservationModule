"""
Batch 5b — the owner's phone decisions (docs/security/PHONE_MASKING_PLAN.md) that the phone canary
sweep can't see on its own: numbers that MUST still show (no over-masking), the live-call channel,
and the full-number rule on lookups.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

from .canary import Planter
from .fixtures import bearer_client, seed_code_matrix
from .test_phone_canary_sweep import NUMBER, NUMBER_TOKEN


@override_settings(RBAC_ENFORCEMENT='enforce')
class PhoneDecisionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        RoleModuleAccess.objects.filter(role__in=['pharmacist', 'viewer']).update(is_allowed=True)
        module_access.clear_cache()
        cls.a = make_branch('PhR A', softech_id='PRA')
        cls.b = make_branch('PhR B', softech_id='PRB')
        cls.ua, cls.pa, _ = make_user('phr_a', role='pharmacist', branch=cls.a)
        cls.ub, cls.pb, _ = make_user('phr_b', role='pharmacist', branch=cls.b)
        cls.uv, _, _ = make_user('phr_view', role='viewer', branch=cls.a)
        cls.cc, _, _ = make_user('phr_cc', role='call_center', branch=cls.b)

    def setUp(self):
        module_access.clear_cache()
        self.planter = Planter(self.a, self.ua, self.pa, phone=NUMBER)
        from apps.customers.models import Customer
        self.cust = self.planter.build(Customer, marked=True)
        self.planter.neutral[Customer] = self.cust

    def _plant(self, label, **over):
        from django.apps import apps
        model = apps.get_model(label)
        obj = self.planter.build(model, marked=True)
        self.assertIsNotNone(obj, label)
        if over:
            model.objects.filter(pk=obj.pk).update(**over)
            obj.refresh_from_db()
        return obj

    # D2: the number needed to serve your own branch's record is shown — even for a customer of
    # another home branch
    def test_d2_own_branch_reservation_shows_the_number(self):
        type(self.cust).objects.filter(pk=self.cust.pk).update(preferred_branch=self.b)
        res = self._plant('reservations.Reservation')
        r = bearer_client(self.ua).get(f'/api/reservations/{res.pk}/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertIn(NUMBER_TOKEN, r.content.decode())

    # D4 / D7: the read-only viewer sees the record, not the number
    def test_d4_viewer_gets_it_masked(self):
        res = self._plant('reservations.Reservation')
        r = bearer_client(self.uv).get(f'/api/reservations/{res.pk}/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertNotIn(NUMBER_TOKEN, r.content.decode())

    # D5: a rider of another branch keeps the recipient's number on an order assigned to them
    def test_d5_assigned_rider_sees_the_number(self):
        rider, rp, _ = make_user('phr_rider', role='delivery', branch=self.b)
        from apps.delivery.models import DeliveryDriver
        driver = Planter(self.b, rider, rp).build(DeliveryDriver, marked=False)
        self.assertIsNotNone(driver)
        rel = next(f.name for f in DeliveryDriver._meta.fields
                   if f.is_relation and f.related_model is type(rp) and f.remote_field.related_name == 'driver_profile')
        DeliveryDriver.objects.filter(pk=driver.pk).update(**{rel: rp})
        order = self._plant('delivery.DeliveryOrder', assigned_driver=driver)
        r = bearer_client(rider).get(f'/api/delivery/{order.pk}/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertIn(NUMBER_TOKEN, r.content.decode())

    # D1: the live-call channel
    def test_d1_only_agents_receive_calls(self):
        from apps.pbx.consumers import may_receive_calls
        self.assertTrue(may_receive_calls(self.cc, None))
        self.assertFalse(may_receive_calls(self.uv, None), 'viewer: call-center view but no numbers')
        RoleModuleAccess.objects.filter(role='pharmacist', module='callcenter').update(is_allowed=False)
        module_access.clear_cache()
        self.assertFalse(may_receive_calls(self.ua, None))
        self.assertTrue(may_receive_calls(self.ua, object()), 'a configured extension = an agent')

    # D6: campaign recipients' numbers for the people who send / approve
    def test_d6_campaign_messages_masked_for_read_only(self):
        msg = self._plant('campaigns.CampaignMessage')
        RoleModuleAccess.objects.filter(role='pharmacist', module='campaigns').exclude(
            action='view').update(is_allowed=False)
        module_access.clear_cache()
        r = bearer_client(self.ua).get(f'/api/campaigns/{msg.campaign_id}/messages/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertNotIn(NUMBER_TOKEN, r.content.decode())
        RoleModuleAccess.objects.filter(role='pharmacist', module='campaigns').update(is_allowed=True)
        module_access.clear_cache()
        r = bearer_client(self.ua).get(f'/api/campaigns/{msg.campaign_id}/messages/')
        self.assertIn(NUMBER_TOKEN, r.content.decode(), 'senders / approvers see the numbers')

    # D8: referral leads — all-branch roles only
    def test_d8_leads_masked_for_branch_staff(self):
        self._plant('referral.ReferralLead')
        self.assertNotIn(NUMBER_TOKEN, bearer_client(self.ua).get('/api/referral/leads/').content.decode())
        self.assertIn(NUMBER_TOKEN, bearer_client(self.cc).get('/api/referral/leads/').content.decode())

    # B-2: lookups need the FULL number from branch staff; a fragment is refused
    def test_lookups_refuse_a_fragment_from_branch_staff(self):
        for url in ('/api/callcenter/calls/lookup/', '/api/delivery/customer-profile/'):
            with self.subTest(url=url):
                self.assertEqual(bearer_client(self.ub).get(url, {'phone': '7561'}).status_code, 400)
                r = bearer_client(self.ub).get(url, {'phone': NUMBER})
                self.assertEqual(r.status_code, 200, r.content[:300])
        r = bearer_client(self.cc).get('/api/callcenter/calls/lookup/', {'phone': '47561'})
        self.assertEqual(r.status_code, 200, 'call-center agents keep the fragment search')

    def test_own_customer_lookup_shows_the_number(self):
        r = bearer_client(self.ua).get(f'/api/customers/{self.cust.pk}/pos-summary/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertIn(NUMBER_TOKEN, r.content.decode())
        r = bearer_client(self.ub).get(f'/api/customers/{self.cust.pk}/pos-summary/')
        self.assertNotIn(NUMBER_TOKEN, r.content.decode())
