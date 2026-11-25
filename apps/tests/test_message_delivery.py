"""Delivery checker — did a voucher OTP / portal login link reach the customer? (apps/whatsapp/delivery.py)"""
import datetime as dt
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.notifications.models import Notification
from apps.vouchers.models import VoucherOTP
from apps.whatsapp import delivery
from apps.whatsapp.models import WAConversation, WAMessage

from .factories import make_admin, make_branch
from .test_vouchers import _make_voucher, _voucher_url


def wa_msg(wamid, status='sent', minutes_ago=0, **kw):
    conv, _ = WAConversation.objects.get_or_create(wa_id='201012345678', defaults={'status': 'open'})
    m = WAMessage.objects.create(conversation=conv, direction='outbound', message_type='template', status=status,
                                 wamid=wamid, body='otp_delivery', **kw)
    at = timezone.now() - dt.timedelta(minutes=minutes_ago)
    WAMessage.objects.filter(pk=m.pk).update(sent_at=at, created_at=at)
    return m


class StateTests(TestCase):
    def test_states(self):
        self.assertEqual(delivery.status('')['state'], 'not_sent')
        self.assertEqual(delivery.status('wamid.unknown')['state'], 'pending')
        wa_msg('w1', 'sent')
        self.assertEqual(delivery.status('w1')['state'], 'sent')
        wa_msg('w2', 'sent', minutes_ago=5)
        self.assertEqual(delivery.status('w2')['state'], 'no_receipt')
        wa_msg('w3', 'delivered', minutes_ago=5)
        self.assertEqual(delivery.status('w3')['label'], 'وصل للعميل')
        wa_msg('w4', 'failed', error_code='131026', error_message='Message undeliverable')
        st = delivery.status('w4')
        self.assertEqual((st['state'], st['error']), ('failed', '131026 — Message undeliverable'))

    def test_webhook_silent(self):
        for i in range(5):
            wa_msg(f's{i}', 'sent', minutes_ago=30)
        self.assertTrue(delivery.webhook_silent())
        WAMessage.objects.filter(wamid='s0').update(status='delivered')
        self.assertFalse(delivery.webhook_silent())


@override_settings(WHATSAPP_TOKEN='test-token')
class OtpFlowTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_admin('admin_otp_delivery')
        self.voucher = _make_voucher(self.branch, self.profile)

    def _gen(self, send):
        with mock.patch('apps.vouchers.models.Voucher.check_full_eligibility', return_value=(True, '')), \
                mock.patch('apps.whatsapp.sender.WhatsAppSender.send_otp', side_effect=send):
            return self.client.post(_voucher_url(self.voucher.id, 'generate-otp'), {'phone': '01012345678'},
                                    format='json')

    def test_otp_keeps_its_message_and_reports_delivery(self):
        r = self._gen(lambda **kw: {'messages': [{'id': 'wamid.otp1'}]})
        self.assertEqual(r.status_code, 200, r.data)
        otp = VoucherOTP.objects.get(pk=r.data['otp_id'])
        self.assertEqual((otp.sent_via, otp.wamid), ('whatsapp_api', 'wamid.otp1'))
        url = _voucher_url(self.voucher.id, 'otp-status') + f'?otp_id={otp.pk}'
        self.assertEqual(self.client.get(url).data['state'], 'pending')
        wa_msg('wamid.otp1', 'delivered')
        s = self.client.get(url).data
        self.assertEqual((s['state'], s['sent_via']), ('delivered', 'whatsapp_api'))
        self.assertNotIn('code', s)
        self.assertEqual(self.client.get(_voucher_url(self.voucher.id, 'otp-status') + '?otp_id=999999').status_code,
                         404)

    def test_failed_send_is_recorded_as_qr(self):
        def boom(**kw):
            raise RuntimeError('meta down')
        r = self._gen(boom)
        self.assertEqual(r.status_code, 200)
        otp = VoucherOTP.objects.get(pk=r.data['otp_id'])
        self.assertEqual((otp.sent_via, otp.wamid), ('qr', ''))
        url = _voucher_url(self.voucher.id, 'otp-status') + f'?otp_id={otp.pk}'
        self.assertEqual(self.client.get(url).data['state'], 'not_sent')


class PortalLinkTests(TestCase):
    def test_login_link_keeps_its_message(self):
        from apps.customers.models import Customer
        from apps.portal.models import PortalLogin
        from apps.portal.services import issue_magic_link, send_magic_link
        c = Customer.objects.create(softech_pic='01HD9', name='سعيد', phone='01055667788')
        token = issue_magic_link(c)
        with mock.patch('apps.whatsapp.sender.WhatsAppSender.send_text',
                        return_value={'messages': [{'id': 'wamid.link1'}]}):
            self.assertTrue(send_magic_link(c, token))
        self.assertEqual(PortalLogin.objects.get(customer=c).wamid, 'wamid.link1')


class ReportTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.profile, _ = make_admin('admin_delivery_rep')
        self.voucher = _make_voucher(self.branch, self.profile)

    def _otp(self, wamid, sent_via):
        o = VoucherOTP.objects.create(voucher=self.voucher, phone='01012345678', code_hash='x', otp_salt='y',
                                      expires_at=timezone.now(), sent_via=sent_via, wamid=wamid)
        return o

    def test_report_and_notice(self):
        self._otp('r1', 'whatsapp_api')
        self._otp('r2', 'whatsapp_api')
        self._otp('', 'qr')
        wa_msg('r1', 'delivered', minutes_ago=10)
        wa_msg('r2', 'failed', minutes_ago=10, error_code='131026')
        rep = delivery.report(timezone.localdate())
        self.assertEqual(rep['total'], 3)
        self.assertEqual(rep['by_state'], {'delivered': 1, 'failed': 1, 'not_sent': 1})
        self.assertEqual(rep['delivery_rate'], 50.0)
        self.assertEqual(len(rep['problems']), 2)
        text = delivery.digest_text(rep)
        self.assertIn('••••5678', text)
        self.assertNotIn('01012345678', text)                        # phones masked
        self.assertEqual(delivery.notify(rep), 1)                     # the admin
        self.assertEqual(delivery.notify(rep), 0)                     # once a day
        self.assertEqual(Notification.objects.get().notification_type, 'message_delivery')

    def test_quiet_day_sends_nothing(self):
        self._otp('q1', 'whatsapp_api')
        wa_msg('q1', 'read', minutes_ago=10)
        rep = delivery.report(timezone.localdate())
        self.assertEqual(rep['problems'], [])
        self.assertEqual(delivery.notify(rep), 0)

    def test_command(self):
        import io
        from django.core.management import call_command
        out = io.StringIO()
        call_command('check_message_delivery', day=timezone.localdate().isoformat(), stdout=out)
        self.assertIn('OTP', out.getvalue())
