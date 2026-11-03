"""Weekly expiry-worklist WhatsApp goes through phone_alerts.sender (Task 10)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from apps.batches import expiry_audit
from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.notifications.phone_alerts import inbound, sender
from apps.notifications.phone_alerts.models import PhoneAlert, PhoneAlertAttempt
from apps.omni.models import ChannelAccount
from apps.users.models import StaffProfile

SEND_TPL = 'apps.whatsapp.sender.WhatsAppSender.send_template'
User = get_user_model()


def _conf():
    return mock.patch('apps.whatsapp.sender.WhatsAppSender.is_configured',
                      new_callable=mock.PropertyMock, return_value=True)


class WorklistWhatsAppTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch = Branch.objects.create(softech_branch_id='971', name='B971', name_ar='فرع الزيتون')
        cls.acc = ChannelAccount.objects.create(channel='whatsapp', name='Staff',
                                                phone_or_handle='201000000999',
                                                provider='meta_cloud', is_active=True)
        SystemSetting.objects.update_or_create(
            key='phone_alerts_channel_account',
            defaults={'label': 'x', 'value': str(cls.acc.pk), 'value_type': 'integer'})
        cls.mgr = cls._staff('m1', '01000000071', True)
        cls.no_optin = cls._staff('m2', '01000000072', False)
        cls.junk = cls._staff('m3', '123', True)

    @classmethod
    def _staff(cls, name, phone, optin):
        u = User.objects.create_user(name, password='x')
        return StaffProfile.objects.create(user=u, role='pharmacist', phone=phone, branch=cls.branch,
                                           notify_expiry_worklist_wa=optin)

    def _flag(self, on):
        SystemSetting.objects.update_or_create(
            key='expiry_worklist_whatsapp_enabled',
            defaults={'label': 'x', 'value': 'true' if on else 'false', 'value_type': 'boolean'})

    def _run(self):
        expiry_audit._maybe_whatsapp_worklist(
            [self.mgr, self.no_optin, self.junk], 'فرع الزيتون', 7, 'body')

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True)
    def test_worklist_whatsapp_no_typeerror(self):
        self._flag(True)
        with _conf(), mock.patch(SEND_TPL, return_value={'messages': [{'id': 'wamid.W'}]}) as send:
            self._run()
        alert = PhoneAlert.objects.get()
        self.assertEqual((alert.kind, alert.event, alert.phone, alert.recipient_staff),
                         ('brief', 'expiry_worklist', '201000000071', self.mgr))
        self.assertEqual(PhoneAlertAttempt.objects.filter(alert=alert, result='sent').count(), 1)
        kw = send.call_args.kwargs
        self.assertEqual(kw['template_name'], 'staff_alert')
        self.assertEqual([v['text'] for v in kw['variables']],
                         ['قائمة صلاحيات الأسبوع', 'فرع الزيتون', '7 صنف', '—'])
        self.assertEqual(kw['quick_reply_payloads'], [f'alert:{alert.token}:ack'])

    def test_worklist_needs_both_switches(self):
        with _conf(), mock.patch(SEND_TPL) as send:
            self._flag(True)
            with override_settings(PHONE_ALERTS_SEND_ENABLED=False):
                self._run()
            self._flag(False)
            with override_settings(PHONE_ALERTS_SEND_ENABLED=True):
                self._run()
        self.assertEqual(PhoneAlert.objects.count(), 0)
        send.assert_not_called()

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True)
    def test_brief_alert_ack_tap_is_harmless(self):
        self._flag(True)
        with _conf(), mock.patch(SEND_TPL, return_value={}):
            self._run()
        alert = PhoneAlert.objects.get()
        with mock.patch('apps.whatsapp.sender.WhatsAppSender.send_text'):
            out = inbound.handle_alert_tap(wa_id='201000000071', payload=f'alert:{alert.token}:ack',
                                           account=self.acc)
        alert.refresh_from_db()
        self.assertEqual((out, alert.status), ('acknowledged', 'acknowledged'))

    def test_expiry_event_uses_phone_alerts_switch_not_brief_switch(self):
        a = PhoneAlert(kind='brief', event='expiry_worklist', phone='201000000071')
        with override_settings(PHONE_ALERTS_SEND_ENABLED=False, MORNING_BRIEF_SEND_ENABLED=True):
            self.assertFalse(sender._sending_enabled(a))
        with override_settings(PHONE_ALERTS_SEND_ENABLED=True, MORNING_BRIEF_SEND_ENABLED=False):
            self.assertTrue(sender._sending_enabled(a))
