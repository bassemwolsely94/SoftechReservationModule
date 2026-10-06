"""
apps/portal/tests.py

Security + flow tests for the customer self-service portal. The emphasis is on
ISOLATION: a portal session can only touch its own customer's data, a portal
token is useless on staff APIs, and a staff JWT is useless on portal APIs.
"""
from unittest import mock

from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.customers.models import Customer
from apps.reservations.models import Reservation
from apps.portal.tokens import (
    make_magic_token, make_session_token, read_session_token,
)
from apps.tests.factories import make_branch, make_item, make_user


class PortalTestBase(APITestCase):
    def setUp(self):
        cache.clear()  # throttle history lives in the cache
        self.branch = make_branch()
        self.customer = Customer.objects.create(
            softech_pic='01HD100', name='سعيد علي',
            phone='01055667788', is_guest=False, preferred_branch=self.branch,
        )
        self.other = Customer.objects.create(
            softech_pic='01HD200', name='منى حسن',
            phone='01099887766', is_guest=False,
        )

    def session_headers(self, customer=None):
        c = customer or self.customer
        return {'HTTP_AUTHORIZATION': f'Portal {make_session_token(c.softech_pic)}'}


class RequestLinkTests(PortalTestBase):
    def test_always_200_no_existence_leak(self):
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as Sender:
            r1 = self.client.post(reverse('portal-request-link'), {'phone': '01055667788'})
            r2 = self.client.post(reverse('portal-request-link'), {'phone': '01000000000'})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json(), r2.json())  # identical body → no leak

    def test_whatsapp_sent_only_when_customer_found(self):
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as Sender:
            self.client.post(reverse('portal-request-link'), {'phone': '01055667788'})
            self.assertTrue(Sender.return_value.send_text.called)
        with mock.patch('apps.whatsapp.sender.WhatsAppSender') as Sender2:
            self.client.post(reverse('portal-request-link'), {'phone': '01000000000'})
            self.assertFalse(Sender2.return_value.send_text.called)

    def test_throttle_blocks_after_limit(self):
        url = reverse('portal-request-link')
        codes = []
        with mock.patch('apps.whatsapp.sender.WhatsAppSender'):
            for _ in range(7):
                codes.append(self.client.post(url, {'phone': '01055667788'}).status_code)
        self.assertIn(429, codes)  # default rate is 5/min


class AuthExchangeTests(PortalTestBase):
    def test_valid_magic_token_yields_session(self):
        token = make_magic_token(self.customer.softech_pic)
        r = self.client.post(reverse('portal-auth'), {'token': token})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(read_session_token(body['session_token']), self.customer.softech_pic)
        self.assertEqual(body['customer']['name'], 'سعيد علي')

    def test_garbage_token_rejected(self):
        r = self.client.post(reverse('portal-auth'), {'token': 'not-a-real-token'})
        self.assertEqual(r.status_code, 400)

    def test_session_token_not_accepted_as_magic(self):
        # A session-salt token must NOT be exchangeable at the magic-link endpoint.
        session = make_session_token(self.customer.softech_pic)
        r = self.client.post(reverse('portal-auth'), {'token': session})
        self.assertEqual(r.status_code, 400)


class CrossAuthIsolationTests(PortalTestBase):
    def test_portal_token_rejected_on_staff_api(self):
        token = make_session_token(self.customer.softech_pic)
        r = self.client.get('/api/customers/', HTTP_AUTHORIZATION=f'Portal {token}')
        self.assertEqual(r.status_code, 401)

    def test_staff_jwt_rejected_on_portal_api(self):
        user, _profile, _client = make_user('staff_portal_test', role='admin')
        access = str(AccessToken.for_user(user))
        r = self.client.get(reverse('portal-me'), HTTP_AUTHORIZATION=f'Bearer {access}')
        self.assertEqual(r.status_code, 401)

    def test_portal_api_requires_session(self):
        r = self.client.get(reverse('portal-me'))
        self.assertEqual(r.status_code, 401)


class ScopedReadTests(PortalTestBase):
    def test_me_returns_authenticated_customer(self):
        r = self.client.get(reverse('portal-me'), **self.session_headers())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['name'], 'سعيد علي')

    def test_orders_scoped_to_customer(self):
        item = make_item()
        Reservation.objects.create(
            customer=self.customer, item=item, branch=self.branch,
            quantity_requested=1, status='pending',
            contact_name='سعيد علي', contact_phone='01055667788',
        )
        Reservation.objects.create(
            customer=self.other, item=item, branch=self.branch,
            quantity_requested=1, status='pending',
            contact_name='منى حسن', contact_phone='01099887766',
        )
        r = self.client.get(reverse('portal-orders'), **self.session_headers())
        self.assertEqual(r.status_code, 200)
        res = r.json()['reservations']
        self.assertEqual(len(res), 1)  # only this customer's reservation


class ReorderTests(PortalTestBase):
    def test_reorder_creates_scoped_reservation(self):
        item = make_item()
        # Maliciously try to pass another customer/branch — must be ignored.
        r = self.client.post(
            reverse('portal-reorder'),
            {'item': item.id, 'quantity': 2, 'customer': self.other.id, 'branch': 99999},
            **self.session_headers(),
        )
        self.assertEqual(r.status_code, 201)
        resv = Reservation.objects.get(pk=r.json()['id'])
        self.assertEqual(resv.customer_id, self.customer.id)   # NOT self.other
        self.assertEqual(resv.branch_id, self.branch.id)       # server-resolved
        self.assertEqual(resv.order_source, 'online')
        self.assertEqual(resv.item_id, item.id)

    def test_reorder_accepts_manual_name(self):
        r = self.client.post(
            reverse('portal-reorder'),
            {'manual_item_name': 'دواء غير مكوَّد'},
            **self.session_headers(),
        )
        self.assertEqual(r.status_code, 201)

    def test_reorder_requires_an_item(self):
        r = self.client.post(reverse('portal-reorder'), {}, **self.session_headers())
        self.assertEqual(r.status_code, 400)
