"""
apps/tests/test_phone_matching.py — the ONE phone-matching rule (core.phones), 2026-11-04.

An empty or short number must never match an arbitrary customer (`endswith('')` matches every
row), and a formatted number must match the customer stored in national form. Synthetic data.
"""
from types import SimpleNamespace

from django.test import TestCase

from apps.customers.models import Customer
from apps.erp.models import LocalCustomer
from core import phones
from .factories import make_admin, make_customer

STORED = '01000000010'
FORMATTED = '+20 100-000-0010'


class HelperTests(TestCase):

    def test_phone_key_forms(self):
        for raw in ('01000000010', '1000000010', '+201000000010', '00201000000010',
                    '0100-000-0010', '0100 000 0010', '٠١٠٠٠٠٠٠٠١٠', FORMATTED):
            self.assertEqual(phones.phone_key(raw), STORED, raw)

    def test_cairo_landline_with_and_without_02(self):
        self.assertEqual(phones.phone_key('24842067'), '0224842067')
        self.assertTrue(phones.same_phone('24842067', '0224842067'))
        self.assertTrue(phones.same_phone('+20 2 2484 2067', '0224842067'))

    def test_short_or_empty_gives_no_query(self):
        for raw in ('', None, '   ', '15', '123456', 'abc', '+20'):
            self.assertIsNone(phones.phone_q(raw), raw)
            self.assertFalse(phones.same_phone(raw, raw), raw)

    def test_phone_q_prefilters_last_8_on_each_field(self):
        q = phones.phone_q(FORMATTED, ('phone', 'phone_alt'))
        self.assertIn(('phone__endswith', '00000010'), q.children)
        self.assertIn(('phone_alt__endswith', '00000010'), q.children)

    def test_same_phone_is_exact(self):
        self.assertTrue(phones.same_phone(FORMATTED, STORED))
        self.assertFalse(phones.same_phone('01100000010', STORED))     # same last 8, other number

    def test_matching_confirms_exact_key(self):
        target = make_customer(name='هدف', phone=STORED)
        make_customer(name='ذيل مشابه', phone='01200000010')            # same last 8 digits
        self.assertEqual(phones.matching(Customer.objects.all(), FORMATTED), [target])
        self.assertEqual(phones.matching(Customer.objects.all(), ''), [])
        self.assertIsNone(phones.first_match(Customer.objects.all(), '10'))

    def test_first_match_prefers_phone_over_phone_alt(self):
        alt = Customer.objects.create(name='بديل', phone='01299999999', phone_alt=STORED)
        main = make_customer(name='أساسي', phone=STORED)
        self.assertEqual(phones.first_match(Customer.objects.all(), FORMATTED), main)
        main.delete()
        self.assertEqual(phones.first_match(Customer.objects.all(), FORMATTED), alt)


class DeliveryProfileTests(TestCase):
    URL = '/api/delivery/customer-profile/'

    def setUp(self):
        _, _, self.client = make_admin()
        self.customer = make_customer(phone=STORED)

    def test_short_number_is_refused(self):
        r = self.client.get(self.URL, {'phone': '10'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('اكتب الرقم كامل', r.data['detail'])

    def test_formatted_number_finds_customer(self):
        r = self.client.get(self.URL, {'phone': FORMATTED})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['customer']['id'], self.customer.pk)

    def test_unknown_number_finds_nobody(self):
        r = self.client.get(self.URL, {'phone': '01299999999'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['found'])


class ErpLookupTests(TestCase):
    """apps/erp/urls.py is not mounted in config/urls.py today, so the view is called directly."""

    def setUp(self):
        self.user = make_admin()[0]
        self.lc = LocalCustomer.objects.create(phcode='T1HD1', name='عميل محلي', phone=STORED)

    def _get(self, phone):
        from rest_framework.test import APIRequestFactory, force_authenticate
        from apps.erp.views import LocalCustomerViewSet
        request = APIRequestFactory().get('/lookup/', {'phone': phone})
        force_authenticate(request, user=self.user)
        return LocalCustomerViewSet.as_view({'get': 'lookup'})(request)

    def test_short_number_is_refused(self):
        self.assertEqual(self._get('0010').status_code, 400)

    def test_formatted_number_finds_local_customer(self):
        r = self._get(FORMATTED)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['found'])
        self.assertEqual(r.data['customer']['phcode'], 'T1HD1')

    def test_near_miss_is_not_found(self):
        self.assertFalse(self._get('01100000010').data['found'])


class FollowupPhcodeTests(TestCase):

    def setUp(self):
        LocalCustomer.objects.create(phcode='T1HD1', name='أ', phone=STORED)
        LocalCustomer.objects.create(phcode='T1HD2', name='ب', phone='01299999999')

    def test_empty_phone_collects_no_phcodes(self):
        from apps.followups.services import customer_phcodes
        c = Customer.objects.create(name='بلا رقم', phone='')
        self.assertEqual(customer_phcodes(c), [])

    def test_formatted_phone_collects_its_own_phcode_only(self):
        from apps.followups.services import customer_phcodes
        c = Customer.objects.create(name='منسق', phone=FORMATTED)
        self.assertEqual(customer_phcodes(c), ['T1HD1'])


class ReferralFraudTests(TestCase):

    def _engine(self, lead_phone, referrer):
        from apps.referral.fraud import FraudEngine
        return FraudEngine(SimpleNamespace(pk=0, lead_phone=lead_phone, referrer=referrer))

    def test_empty_phones_are_not_self_referral(self):
        referrer = Customer.objects.create(name='مُحيل', phone=' ', phone_alt='')
        e = self._engine('', referrer)
        e._check_self_referral()
        self.assertNotIn('self_referral', e.flags)

    def test_formatted_lead_phone_is_self_referral(self):
        referrer = make_customer(phone=STORED)
        e = self._engine(FORMATTED, referrer)
        e._check_self_referral()
        self.assertIn('self_referral', e.flags)

    def test_empty_lead_phone_is_not_an_existing_customer(self):
        make_customer(phone=STORED)
        referrer = make_customer(name='مُحيل', phone='01299999999')
        e = self._engine('', referrer)
        e._check_duplicate_phone()
        e._check_circular_referral()
        self.assertEqual(e.flags, [])

    def test_formatted_lead_phone_is_an_existing_customer(self):
        make_customer(phone=STORED)
        referrer = make_customer(name='مُحيل', phone='01299999999')
        e = self._engine(FORMATTED, referrer)
        e._check_duplicate_phone()
        self.assertIn('duplicate_phone', e.flags)


class VoucherPhoneTests(TestCase):

    def test_same_phone(self):
        from apps.vouchers.models import _same_phone
        self.assertTrue(_same_phone(FORMATTED, '', STORED))
        self.assertFalse(_same_phone('', '', STORED))
        self.assertFalse(_same_phone('0010', '0010'))
        self.assertTrue(_same_phone('24842067', '0224842067'))


class WhatsAppAndOmniTests(TestCase):

    def test_wa_id_matches_national_customer_only(self):
        from apps.whatsapp.models import WAConversation
        make_customer(name='آخر', phone='01299999999')
        target = make_customer(phone=STORED)
        conv = WAConversation.objects.create(wa_id='201000000010')
        self.assertEqual(conv.customer_id, target.pk)

    def test_short_wa_id_matches_nobody(self):
        from apps.whatsapp.models import WAConversation
        make_customer(phone=STORED)
        conv = WAConversation.objects.create(wa_id='10')
        self.assertIsNone(conv.customer_id)

    def test_omni_short_phone_never_reuses_a_conversation(self):
        from apps.omni import services
        c1 = services.resolve_conversation(phone=STORED, channel='voice')
        c2 = services.resolve_conversation(phone='10', channel='voice')
        self.assertNotEqual(c1.pk, c2.pk)
        c3 = services.resolve_conversation(phone=FORMATTED, channel='voice')
        self.assertEqual(c1.pk, c3.pk)


class PortalLookupTests(TestCase):

    def test_portal_needs_exact_number(self):
        from apps.portal.services import find_customer_by_phone
        c = Customer.objects.create(name='بوابة', phone=STORED, softech_pic='T1HD9')
        self.assertEqual(find_customer_by_phone(FORMATTED), c)
        self.assertIsNone(find_customer_by_phone('0000010'))
        self.assertIsNone(find_customer_by_phone(''))
