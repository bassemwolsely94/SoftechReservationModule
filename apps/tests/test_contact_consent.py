"""P-05 — customer contact consent: one rule (apps/customers/consent.py) for every outbound sender."""
from unittest import mock

from django.test import TestCase

from apps.audit.models import AuditLog
from apps.customers import consent as C
from apps.customers.models import ContactConsent, Customer


def pics(qs):
    return set(qs.values_list('softech_pic', flat=True))


def cust(pic, phone=None, **kw):
    return Customer.objects.create(name='x', phone=phone or '0100' + pic[-4:].rjust(7, '0'), softech_pic=pic, **kw)


class RuleTests(TestCase):
    def test_purposes_and_account_state(self):
        a = cust('A1')
        self.assertEqual(C.decision(a, C.SERVICE), (True, 'ok'))                    # service: allowed by default
        for p in (C.REFILL, C.MARKETING, C.MARKETING_HEALTH):
            self.assertEqual(C.decision(a, p), (False, 'no_consent'))               # opt-in
        C.record(a, C.MARKETING, True, source='counter')
        self.assertTrue(C.can_contact(a, C.MARKETING))
        self.assertFalse(C.can_contact(a, C.MARKETING_HEALTH))                      # health offers asked separately
        self.assertFalse(C.can_contact(a, C.MARKETING, 'sms'))                      # per channel
        C.record(a, C.MARKETING, False, source='whatsapp_reply')
        self.assertEqual(C.decision(a, C.MARKETING), (False, 'withdrawn'))          # the later "no" wins
        C.record(a, C.SERVICE, False, source='staff')
        self.assertEqual(C.decision(a, C.SERVICE), (False, 'withdrawn'))

        closed, entity = cust('A2', softech_status='0'), cust('A3', softech_locked=True)
        for c in (closed, entity):
            C.record(c, C.MARKETING, True, source='counter')
        self.assertEqual(C.decision(closed, C.SERVICE), (False, 'account_state'))
        self.assertEqual(C.decision(closed, C.MARKETING), (False, 'account_state'))
        self.assertEqual(C.decision(entity, C.SERVICE), (True, 'ok'))               # entities: service only
        self.assertEqual(C.decision(entity, C.MARKETING), (False, 'account_state'))
        self.assertEqual(C.decision(None, C.SERVICE), (True, 'ok'))                 # phone-only restock request
        self.assertEqual(C.decision(None, C.REFILL), (False, 'no_customer'))
        with self.assertRaises(ValueError):
            C.decision(a, 'spam')

    def test_record_is_idempotent_and_audited(self):
        from apps.tests.factories import make_user
        _, staff, _ = make_user('cons', role='pharmacist')
        a = cust('B1')
        self.assertIsNotNone(C.record(a, C.REFILL, True, source='counter', user=staff))
        self.assertIsNone(C.record(a, C.REFILL, True, source='counter', user=staff))     # same answer: no row
        self.assertEqual(ContactConsent.objects.filter(customer=a).count(), 1)
        self.assertEqual(AuditLog.objects.filter(action='customer_updated', note__startswith='P-05').count(), 1)

    def test_bulk_filters_keep_customers_without_a_record(self):
        yes, no, none, closed = cust('C1'), cust('C2'), cust('C3'), cust('C4', softech_status='0')
        C.record(yes, C.MARKETING, True, source='counter')
        C.record(no, C.MARKETING, False, source='counter')
        C.record(no, C.SERVICE, False, source='counter')
        C.record(closed, C.MARKETING, True, source='counter')
        qs = Customer.objects.filter(softech_pic__startswith='C')
        self.assertEqual(pics(C.filter_allowed(qs, C.MARKETING)), {'C1'})
        self.assertEqual(pics(C.filter_allowed(qs, C.SERVICE)), {'C1', 'C3'})       # no record = allowed
        self.assertEqual(pics(C.exclude_withdrawn(qs, C.MARKETING, 'whatsapp')), {'C1', 'C3', 'C4'})
        self.assertEqual(C.decisions([yes.pk, no.pk, none.pk], C.MARKETING),
                         {yes.pk: True, no.pk: False, none.pk: None})


class StopReplyTests(TestCase):
    def test_stop_word_withdraws_everything_for_everyone_on_the_number(self):
        a, b, other = cust('D1', '01012345678'), cust('D2', '01112222333'), cust('D3', '01099999999')
        Customer.objects.filter(pk=b.pk).update(phone_alt='01012345678')
        for c in (a, b, other):
            C.record(c, C.MARKETING, True, source='counter')
        self.assertTrue(C.is_stop_word('  STOP '))
        self.assertTrue(C.is_stop_word('إيقاف'))
        self.assertFalse(C.is_stop_word('stop the order please'))
        from apps.whatsapp.webhook import _handle_inbound_message
        _handle_inbound_message({'from': '201012345678', 'id': 'wamid.stop1', 'type': 'text',
                                 'text': {'body': 'ايقاف'}}, {}, '')
        for c in (a, b):
            for p in C.PURPOSES:
                self.assertEqual(C.decision(c, p)[1], 'withdrawn', (c.softech_pic, p))
        self.assertTrue(C.can_contact(other, C.MARKETING))


class RestockTests(TestCase):
    def test_restock_whatsapp_respects_a_service_no(self):
        from apps.demand import service
        a = cust('E1')
        demand = mock.Mock(customer=a, phone=a.phone)
        di = mock.Mock(contact_opt_out=False, demand=demand)
        C.record(a, C.SERVICE, False, source='staff')
        with mock.patch('apps.config.services.get_setting', return_value='true'), \
                mock.patch('apps.whatsapp.sender.WhatsAppSender') as WS:
            self.assertFalse(service._auto_whatsapp_restock(di))
        WS.assert_not_called()


class ApiTests(TestCase):
    def setUp(self):
        from apps.tests.factories import make_branch, make_user
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        for role, actions in (('pharmacist', ('view', 'edit')), ('salesperson', ('view',))):   # seed_permissions
            for act in actions:
                RoleModuleAccess.objects.create(role=role, module='customers', action=act)
        b = make_branch('A', '130')
        _, _, self.ph = make_user('cons_ph', role='pharmacist', branch=b, access_all=True)
        _, _, self.sp = make_user('cons_sp', role='salesperson', branch=b, access_all=True)
        self.c = cust('F1', preferred_branch=b)

    def test_get_and_record(self):
        url = f'/api/customers/{self.c.pk}/consent/'
        r = self.ph.get(url)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['purposes']['refill']['reason'], 'no_consent')
        r = self.ph.post(url, {'purpose': 'refill', 'granted': True}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['purposes']['refill']['allowed'])
        row = ContactConsent.objects.get(customer=self.c)
        self.assertEqual((row.source, row.channel, row.recorded_by.user.username), ('counter', 'whatsapp', 'cons_ph'))
        self.assertEqual(self.ph.post(url, {'purpose': 'refill', 'granted': 'yes'}, format='json').status_code, 400)
        self.assertEqual(self.ph.post(url, {'purpose': 'x', 'granted': True}, format='json').status_code, 400)
        self.assertEqual(self.sp.post(url, {'purpose': 'refill', 'granted': False}, format='json').status_code, 403)
        self.assertEqual(ContactConsent.objects.filter(customer=self.c).count(), 1)


class MigrationTests(TestCase):
    def test_refill_opt_outs_become_withdrawals(self):
        import importlib
        from django.apps import apps
        from apps.followups.models import RefillReminderOptOut
        a = cust('G1')
        RefillReminderOptOut.objects.create(customer=a, source='whatsapp_button')
        mig = importlib.import_module('apps.customers.migrations.0034_consent_from_refill_opt_outs')
        mig.forward(apps, None)
        self.assertEqual(C.decisions([a.pk], C.REFILL)[a.pk], False)
        self.assertEqual(C.decisions([a.pk], C.REFILL, 'call')[a.pk], False)


class MeasurementTests(TestCase):
    def test_coverage_counts_only_reachable_customers(self):
        yes, no, _never = cust('H1'), cust('H2'), cust('H3')
        cust('H4', softech_status='0')                       # closed: not reachable, not counted
        Customer.objects.create(name='g', phone='', softech_pic='H5')   # no phone: not counted
        C.record(yes, C.REFILL, True, source='counter')
        C.record(no, C.REFILL, True, source='counter')
        C.record(no, C.REFILL, False, source='whatsapp_reply')
        got = C.coverage(C.REFILL)
        self.assertEqual((got['reachable'], got['yes'], got['no'], got['not_asked']), (3, 1, 1, 1))
        self.assertEqual((got['asked_pct'], got['opt_out_pct']), (66.7, 50.0))
        self.assertEqual(got['recorded_30d'], {'counter': 2, 'whatsapp_reply': 1})

    def test_reminders_summary_carries_coverage(self):
        from apps.followups import refill_reminders as RR
        C.record(cust('J1'), C.REFILL, True, source='counter')
        self.assertEqual(RR.summary()['consent']['yes'], 1)

    def test_campaign_preview_shows_who_is_left_out(self):
        from apps.campaigns.models import WhatsAppCampaign
        from apps.tests.factories import make_user
        from apps.users.models import RoleModuleAccess
        from core.middleware import module_access
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        for act in ('view', 'create', 'edit'):
            RoleModuleAccess.objects.create(role='call_center', module='campaigns', action=act)
        _, _, api = make_user('meas_cc', role='call_center', access_all=True)
        a, _b, _c = cust('K1'), cust('K2'), cust('K3', softech_status='5')
        C.record(a, C.MARKETING, True, source='counter')
        camp = WhatsAppCampaign.objects.create(name='p', message_template='m')
        r = api.post(f'/api/campaigns/{camp.pk}/preview-audience/', {'target_filter': {}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['total_customers'], 1)
        self.assertGreaterEqual(r.data['excluded_by_consent'], 2)                 # K2 (no yes) + K3 (deceased)
