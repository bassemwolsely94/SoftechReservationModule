"""
Platform & abuse — voucher redemption codes (Batch 6, W-1 / W-2; owner 2026-11-01).

Before: `generate-otp` handed the requesting staff member the plain 6-digit code twice — in the
wa.me link text and as a QR image of the code — so staff could redeem without the customer; and
a private voucher's code went to whatever phone the staff member typed.

Now (owner): the server alone sends the code to the customer on WhatsApp (Cloud API); the staff
response carries no code — only a link that opens the chat without it. If the code can't be sent,
the request fails and the code is cancelled. A private voucher's code goes only to its customer's
phone on file.
"""
import datetime
import json
from unittest import mock

from django.test import TestCase

from apps.tests.factories import make_admin, make_branch, make_customer
from apps.vouchers.models import Voucher, VoucherOTP

from .baseline import pending

URL = '/api/vouchers/vouchers/{}/generate-otp/'


def _voucher(branch, by, **kw):
    return Voucher.objects.create(code=Voucher.generate_code(), title='ق', voucher_type='discount_pct',
                                  discount_pct=10, branch=branch, created_by=by, status='active', max_uses=10,
                                  valid_from=datetime.date.today(), **kw)


class _Sender:
    """Stands in for apps.whatsapp.sender.WhatsAppSender — records what the server sends."""
    sent = []
    configured = True

    def __init__(self, *a, **k):
        pass

    @property
    def is_configured(self):
        return type(self).configured

    def send_otp(self, wa_id, otp_display, **k):
        type(self).sent.append((wa_id, otp_display))
        return {'ok': True}


class OtpDeliveryTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.admin, self.c = make_admin('w1_admin')
        self.voucher = _voucher(self.branch, self.admin)
        _Sender.sent, _Sender.configured = [], True

    def _generate(self, phone='01012345678'):
        with mock.patch('apps.whatsapp.sender.WhatsAppSender', _Sender):
            return self.c.post(URL.format(self.voucher.pk), {'phone': phone}, format='json')

    @pending('W-1')
    def test_the_code_reaches_the_customer_only(self):
        r = self._generate()
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(len(_Sender.sent), 1)
        code = _Sender.sent[0][1]
        body = json.dumps(r.data, default=str)
        self.assertNotIn(code, body)                      # nowhere in what staff receive
        self.assertNotIn('qr_code', r.data)
        self.assertNotIn('text=', r.data.get('whatsapp_url', ''))

    @pending('W-1')
    def test_no_send_means_no_code(self):
        _Sender.configured = False
        r = self._generate()
        self.assertEqual(r.status_code, 503, r.data)
        self.assertNotIn('qr_code', r.data)
        self.assertFalse(VoucherOTP.objects.filter(voucher=self.voucher, is_used=False).exists())


class PrivateVoucherPhoneTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.admin, self.c = make_admin('w2_admin')
        self.customer = make_customer(phone='01098765432')
        self.voucher = _voucher(self.branch, self.admin, voucher_category='private', customer=self.customer)
        _Sender.sent, _Sender.configured = [], True

    def _generate(self, phone):
        with mock.patch('apps.whatsapp.sender.WhatsAppSender', _Sender):
            return self.c.post(URL.format(self.voucher.pk), {'phone': phone}, format='json')

    def test_a_private_voucher_code_goes_only_to_its_customer(self):
        self.assertEqual(self._generate('01011112222').status_code, 400)
        self.assertEqual(_Sender.sent, [])
        self.assertEqual(self._generate('01098765432').status_code, 200)


class OtpAdminTests(TestCase):
    """W-11: the code hash is an HMAC keyed only by its salt — showing both lets anyone with admin
    access recover the 6-digit code offline in seconds. Django admin must show neither."""

    def test_admin_shows_neither_the_code_hash_nor_its_salt(self):
        from django.contrib.auth import get_user_model
        boss = get_user_model().objects.create_superuser('w11_root', 'w11@example.com', 'x-Unused-9!')
        self.client.force_login(boss)
        _, admin_profile, _ = make_admin('w11_admin')
        voucher = _voucher(make_branch(), admin_profile)
        otp = VoucherOTP.create_for_voucher(voucher, '01012345678')[0]
        for url in (f'/admin/vouchers/voucherotp/{otp.pk}/change/', f'/admin/vouchers/voucher/{voucher.pk}/change/',
                    '/admin/vouchers/voucherotp/'):
            body = self.client.get(url).content.decode('utf-8')
            self.assertNotIn(otp.code_hash, body, url)
            self.assertNotIn(otp.otp_salt, body, url)
