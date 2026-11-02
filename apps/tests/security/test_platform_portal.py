"""
Platform & abuse — the customer portal (Batch 6, W-5; owner 2026-11-01).

Before: a magic link worked as often as anyone liked for its 15 minutes, and its full text was
saved in the WhatsApp inbox, so any staff member who could read the inbox could open a customer's
session. Sessions were stateless signed tokens — logging out only forgot the token in the browser
and nothing could end a session early. The link request was throttled per phone + IP, so changing
IP kept the WhatsApp messages coming to one number. A reorder took any quantity (0, negative,
99,999,999) as often as the customer liked.

Now: one link = one login, recorded in `PortalLogin`; the session is that row and ends on logout or
when staff revoke it; the inbox keeps a placeholder, not the link; link requests are limited per
phone and per IP; a reorder line is 1–20 and a customer places at most 10 online reorders a day
(owner: any catalogue item).
"""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.customers.models import Customer
from apps.reservations.models import Reservation
from apps.tests.factories import make_branch, make_item

LINK, AUTH, ME, LOGOUT, REORDER = ('/api/portal/request-link/', '/api/portal/auth/', '/api/portal/me/',
                                   '/api/portal/logout/', '/api/portal/reorder/')


class _Base(TestCase):

    def setUp(self):
        cache.clear()                                   # throttle history
        self.branch = make_branch()
        self.customer = Customer.objects.create(softech_pic='01W5100', name='سعيد علي',
                                                phone='01055667788', preferred_branch=self.branch)

    def _magic_token(self):
        """Ask for a link the way the customer does; return the token the server sent."""
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as sender:
            self.client.post(LINK, {'phone': '01055667788'}, content_type='application/json')
        call = sender.return_value.send_text.call_args
        body = call.kwargs.get('body') or call.args[1]
        return body.split('/portal/auth/')[1].split()[0]

    def _session(self):
        r = self.client.post(AUTH, {'token': self._magic_token()}, content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        return {'HTTP_AUTHORIZATION': f"Portal {r.json()['session_token']}"}


class MagicLinkTests(_Base):

    def test_a_link_logs_in_once(self):
        token = self._magic_token()
        first = self.client.post(AUTH, {'token': token}, content_type='application/json')
        again = self.client.post(AUTH, {'token': token}, content_type='application/json')
        self.assertEqual((first.status_code, again.status_code), (200, 400))

    def test_the_inbox_keeps_no_link(self):
        from apps.whatsapp.models import WAMessage
        with mock.patch('apps.whatsapp.sender.WhatsAppSender._post', return_value={'messages': [{'id': 'w1'}]}):
            self.client.post(LINK, {'phone': '01055667788'}, content_type='application/json')
        bodies = list(WAMessage.objects.values_list('body', flat=True))
        self.assertTrue(bodies, 'the send should still be recorded in the inbox')
        self.assertFalse(any('/portal/auth/' in b for b in bodies), bodies)

    def test_requests_are_limited_per_phone_whatever_the_ip(self):
        codes = []
        with mock.patch('apps.whatsapp.sender.WhatsAppSender'):
            for i in range(8):
                codes.append(self.client.post(LINK, {'phone': '01055667788'}, content_type='application/json',
                                              REMOTE_ADDR=f'10.0.0.{i + 1}').status_code)
        self.assertIn(429, codes)


class SessionTests(_Base):

    def test_logout_ends_the_session(self):
        h = self._session()
        self.assertEqual(self.client.get(ME, **h).status_code, 200)
        self.assertEqual(self.client.post(LOGOUT, **h).status_code, 204)
        self.assertEqual(self.client.get(ME, **h).status_code, 401)

    def test_staff_can_end_every_session_of_a_customer(self):
        from apps.portal.models import PortalLogin
        h = self._session()
        PortalLogin.revoke_all(self.customer)
        self.assertEqual(self.client.get(ME, **h).status_code, 401)


class ReorderBoundsTests(_Base):

    def setUp(self):
        super().setUp()
        self.item = make_item()
        self.h = self._session()

    def _reorder(self, qty):
        return self.client.post(REORDER, {'item': self.item.pk, 'quantity': qty},
                                content_type='application/json', **self.h)

    def test_quantity_is_1_to_20(self):
        self.assertEqual([self._reorder(q).status_code for q in (0, -1, 21, 99999999)], [400] * 4)
        self.assertEqual(self._reorder(20).status_code, 201)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_at_most_10_reorders_a_day(self):
        codes = [self._reorder(1).status_code for _ in range(11)]
        self.assertEqual(codes[:10], [201] * 10)
        self.assertEqual(codes[10], 429)
        self.assertEqual(Reservation.objects.filter(customer=self.customer).count(), 10)
