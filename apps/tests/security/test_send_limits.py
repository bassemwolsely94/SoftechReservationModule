"""
Round 2, R5 step 6 — automatic sends: rate limit and recipients.

Owner question 6 (default approved 2026-11-05): one recipient gets at most 1 automatic message of
each type per 10 minutes (`SEND_MIN_INTERVAL_SECONDS`). Before this batch only the morning brief
(once per Cairo day) and the counselling card (per item, unless «إعادة الإرسال») had a repeat
guard; phone alerts, call-back alerts and the insights texts had none. Now every sender claims
`apps.notifications.send_limits.claim(kind, number)` right before it sends.

Recipients: a staff alert goes only to a number held on the configured records — an eligible
staff member's phone (`StaffProfile.phone`, `phone_alerts_enabled`), the branch shared mobile
(`BranchSettings.alert_mobile`) or a brief recipient (`InsightRecipient.wa_number`) — and leaves
from the staff account named by SystemSetting `phone_alerts_channel_account`. A counselling card
goes only to a number on the customer's own record (S-1, owner OK 2026-11-05).

No real message is sent: WhatsApp and SMS are mocked.
"""
import uuid
from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.branches.models import Branch
from apps.notifications import send_limits
from apps.notifications.phone_alerts import sender
from apps.notifications.phone_alerts.models import PhoneAlert, SendThrottle


SEND_TPL = 'apps.whatsapp.sender.WhatsAppSender.send_template'
SEND_TXT = 'apps.whatsapp.sender.WhatsAppSender.send_text'


def _configured():
    return mock.patch('apps.whatsapp.sender.WhatsAppSender.is_configured',
                      new_callable=mock.PropertyMock, return_value=True)


def _staff_account():
    from apps.config.models import SystemSetting
    from apps.omni.models import ChannelAccount
    acc = ChannelAccount.objects.create(channel='whatsapp', name='Staff', phone_or_handle='201000000999',
                                        provider='meta_cloud', is_active=True)
    SystemSetting.objects.update_or_create(
        key='phone_alerts_channel_account',
        defaults={'label': 'x', 'value': str(acc.pk), 'value_type': 'integer'})
    return acc


class ClaimTests(TestCase):
    def test_one_per_recipient_per_type_per_window(self):
        t0 = timezone.now()
        self.assertTrue(send_limits.claim('phone_alert:x', '01012345678', now=t0))
        self.assertFalse(send_limits.claim('phone_alert:x', '01012345678', now=t0 + timedelta(minutes=9)))
        self.assertTrue(send_limits.claim('phone_alert:y', '01012345678', now=t0 + timedelta(minutes=1)))
        self.assertTrue(send_limits.claim('phone_alert:x', '01099999999', now=t0 + timedelta(minutes=1)))
        self.assertTrue(send_limits.claim('phone_alert:x', '01012345678', now=t0 + timedelta(minutes=10)))

    def test_every_way_of_writing_a_number_is_one_recipient(self):
        t0 = timezone.now()
        self.assertTrue(send_limits.claim('k', '01012345678', now=t0))
        for form in ('+201012345678', '201012345678', '0020 101 234 5678'):
            self.assertFalse(send_limits.claim('k', form, now=t0), form)

    def test_only_a_hash_of_the_number_is_stored(self):
        send_limits.claim('k', '01012345678')
        row = SendThrottle.objects.get()
        self.assertNotIn('1012345678', row.recipient_hash)
        self.assertEqual(len(row.recipient_hash), 64)

    @override_settings(SEND_MIN_INTERVAL_SECONDS=3600)
    def test_window_is_a_setting(self):
        t0 = timezone.now()
        send_limits.claim('k', '01012345678', now=t0)
        self.assertFalse(send_limits.claim('k', '01012345678', now=t0 + timedelta(minutes=30)))


@override_settings(PHONE_ALERTS_SEND_ENABLED=True, MORNING_BRIEF_SEND_ENABLED=True)
class PhoneAlertLimitTests(TestCase):
    """Phone alerts, call-back alerts (`callback_overdue`) and the morning brief share one sender."""

    def setUp(self):
        _staff_account()

    def _alert(self, event='transfer_hq_submitted', phone='201000000041', kind='alert'):
        return PhoneAlert.objects.create(event=event, kind=kind, phone=phone)

    def _deliver_all(self, alerts, **kw):
        with _configured(), mock.patch(SEND_TPL, return_value={'messages': [{'id': 'w'}]}) as send:
            results = [sender.deliver(a, **kw).result for a in alerts]
        return results, send

    def test_second_alert_of_the_same_type_to_the_same_number_is_throttled(self):
        results, send = self._deliver_all([self._alert(), self._alert()])
        self.assertEqual(results, ['sent', 'throttled'])
        self.assertEqual(send.call_count, 1)

    def test_other_type_or_other_number_still_goes(self):
        results, send = self._deliver_all([self._alert(), self._alert(event='callback_overdue'),
                                           self._alert(phone='201000000042')])
        self.assertEqual(results, ['sent', 'sent', 'sent'])
        self.assertEqual(send.call_count, 3)

    def test_call_back_alerts_are_limited(self):
        results, _ = self._deliver_all([self._alert(event='callback_overdue') for _ in range(3)])
        self.assertEqual(results, ['sent', 'throttled', 'throttled'])

    def test_a_throttled_alert_is_not_marked_sent(self):
        a, b = self._alert(), self._alert()
        self._deliver_all([a, b])
        b.refresh_from_db()
        self.assertEqual(b.status, 'queued')
        self.assertEqual(b.wa_message_id, '')

    def test_morning_brief_is_limited_too(self):
        results, _ = self._deliver_all(
            [self._alert(event='morning_brief', kind='brief') for _ in range(2)],
            template='morning_brief', variables=[{'type': 'text', 'text': 'x'}], payloads=[])
        self.assertEqual(results, ['sent', 'throttled'])

    @override_settings(PHONE_ALERTS_SEND_ENABLED=False)
    def test_dry_run_reaches_nobody_so_uses_no_slot(self):
        results, send = self._deliver_all([self._alert(), self._alert()])
        self.assertEqual(results, ['dry_run', 'dry_run'])
        send.assert_not_called()
        self.assertFalse(SendThrottle.objects.exists())

    def test_a_send_that_reached_nobody_gives_the_slot_back(self):
        a, b = self._alert(), self._alert()
        with _configured(), mock.patch(SEND_TPL, side_effect=RuntimeError('meta 500')),                 mock.patch('core.sms.SmsSender.is_configured', new_callable=mock.PropertyMock,
                           return_value=False):
            self.assertEqual(sender.deliver(a).result, 'failed')
        results, _ = self._deliver_all([b])
        self.assertEqual(results, ['sent'])

    def test_sends_only_from_the_staff_account_to_the_alert_number(self):
        with _configured(), mock.patch(SEND_TPL, return_value={}) as send, \
                mock.patch('apps.whatsapp.sender.WhatsAppSender.__init__', return_value=None) as init:
            sender.deliver(self._alert(phone='201000000077'))
        self.assertEqual(send.call_args.kwargs['wa_id'], '201000000077')
        self.assertIsNotNone(init.call_args.kwargs.get('account'))     # never the customer number


class AlertRecipientTests(TestCase):
    """Who a staff alert can reach: only numbers held on the configured records."""

    @classmethod
    def setUpTestData(cls):
        from apps.branches.models import BranchSettings
        from apps.users.models import StaffProfile
        from apps.tests.factories import make_user
        cls.branch = Branch.objects.create(softech_branch_id='931', name='فرع ٣١')
        _, cls.on, _ = make_user('alert_on', branch=cls.branch)
        _, cls.off, _ = make_user('alert_off', branch=cls.branch)
        StaffProfile.objects.filter(pk=cls.on.pk).update(phone='01000000051', phone_alerts_enabled=True)
        StaffProfile.objects.filter(pk=cls.off.pk).update(phone='01000000052', phone_alerts_enabled=False)
        BranchSettings.objects.create(branch=cls.branch, alert_mobile='01000000053')

    def test_owner_alerts_reach_only_eligible_staff_phones(self):
        from apps.notifications.phone_alerts.events import EVENTS
        from apps.notifications.phone_alerts.models import WorkOwner
        from apps.notifications.phone_alerts.recipients import resolve
        WorkOwner.objects.create(kind='callcenter_callbacks', staff=self.on)
        WorkOwner.objects.create(kind='callcenter_callbacks', staff=self.off)
        event = next(e for e in EVENTS.values() if e.recipients == 'owner'
                     and e.owner_kind == 'callcenter_callbacks')
        phones = {r.phone for r in resolve(event, None)}
        self.assertEqual(phones, {'201000000051'})

    def test_brief_reaches_only_brief_recipients_and_the_branch_mobile(self):
        from apps.insights.brief import _phones
        from apps.insights.models import InsightRecipient
        InsightRecipient.objects.create(name='m', wa_number='01000000054', branch=self.branch,
                                        morning_brief=True)
        InsightRecipient.objects.create(name='n', wa_number='01000000055', branch=self.branch,
                                        morning_brief=False)
        self.assertEqual(_phones(self.branch), ['201000000054', '201000000053'])


class InsightsTextLimitTests(TestCase):
    """`generate_insights --send` (the 07:30 job; also run by hand): a re-run inside 10 minutes
    sends nothing a second time, and only InsightRecipient numbers are written to."""

    def test_rerun_sends_once(self):
        from apps.insights.management.commands.generate_insights import Command
        from apps.insights.models import InsightRecipient
        InsightRecipient.objects.create(name='m', wa_number='01000000061', period_types='day',
                                        active=True)
        run = mock.Mock(domain='sales', period_type='day', narrative_ar='نص')
        with mock.patch('apps.whatsapp.sender.WhatsAppSender.__init__', return_value=None), \
                mock.patch(SEND_TXT, return_value={}) as send:
            self.assertEqual(Command()._send(run), 1)
            self.assertEqual(Command()._send(run), 0)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs['wa_id'], '01000000061')


@override_settings(COUNSELLING_CONTENT_ENABLED=True, COUNSEL_CARD_SEND_ENABLED=True)
class CounselCardLimitTests(TestCase):
    def setUp(self):
        from apps.counselling import services
        from apps.customers.models import Customer
        from apps.tests.factories import make_branch, make_item, make_user
        from apps.whatsapp.models import WATemplate
        self.branch = make_branch()
        _, ph, _ = make_user('ph_lim', role='pharmacist', branch=self.branch)
        _, self.sp, _ = make_user('sp_lim', role='salesperson', branch=self.branch)
        self.cust = Customer.objects.create(name='منى أحمد علي', phone='01012345678', softech_pic='PL1')
        self.item = make_item('أوجمنتين 1 جم', 'LM001')
        self.item2 = make_item('بنادول', 'LM002')
        for it in (self.item, self.item2):
            sheet = services.create_sheet(ph, {'how_to_use_ar': 'بعد الأكل', 'dose_ar': 'قرص'}, [it.pk])
            services.approve(ph, sheet)
        WATemplate.objects.create(name='counsel_card', status='approved', body_text='x')
        self.fake = mock.Mock()
        self.fake.send_template.return_value = {'messages': [{'id': 'wamid.1'}]}

    def _send(self, **kw):
        from apps.counselling import cards
        args = dict(customer=self.cust, phone='', item_ids=[self.item.pk], actor=self.sp,
                    branch=self.branch, idempotency_key=uuid.uuid4().hex, sender=self.fake)
        args.update(kw)
        return cards.send_card(**args)

    def test_second_card_to_the_same_number_within_10_minutes_is_refused(self):
        from rest_framework.exceptions import ValidationError
        self.assertEqual(self._send().status, 'sent')
        for kw in ({'item_ids': [self.item2.pk]}, {'resend': True}):
            with self.subTest(**kw), self.assertRaises(ValidationError):
                self._send(**kw)
        self.assertEqual(self.fake.send_template.call_count, 1)

    def test_a_failed_card_gives_the_slot_back(self):
        self.fake.send_template.side_effect = [RuntimeError('meta 400'), {'messages': [{'id': 'w2'}]}]
        self.assertEqual(self._send().status, 'failed')
        self.assertEqual(self._send(resend=True).status, 'sent')

    def test_a_refused_card_does_not_use_the_slot(self):
        from rest_framework.exceptions import ValidationError
        from apps.counselling.models import CounselCardSend
        with override_settings(COUNSEL_CARD_DAILY_CAP=0), self.assertRaises(ValidationError):
            self._send()
        self.assertEqual(self._send().status, 'sent')
        self.assertEqual(CounselCardSend.objects.filter(status='sent').count(), 1)

    def test_card_goes_only_to_the_number_on_the_customer_record(self):
        # S-1 (owner OK 2026-11-05): the till can no longer type an outside number
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self._send(phone='01099998888')
