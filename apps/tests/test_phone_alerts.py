from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from apps.access.models import Device, DeviceUser
from apps.branches.models import Branch, BranchSettings
from apps.hr.models import ShiftAssignment, ShiftTemplate
from apps.notifications.phone_alerts.events import EVENTS
from apps.notifications.phone_alerts.models import PhoneAlert, PhoneAlertPolicy, WorkOwner
from apps.notifications.phone_alerts.recipients import on_shift_staff, resolve
from apps.tasks.models import OperationalTask, TaskAssignment
from apps.transfers.models import TransferRequest
from apps.users.models import StaffProfile


class PolicySeedTests(TestCase):
    def test_policy_seeded_for_v1_events(self):
        rows = {p.event: p for p in PhoneAlertPolicy.objects.all()}
        self.assertEqual(set(rows), set(EVENTS))
        self.assertEqual(len(rows), 7)
        for key, p in rows.items():
            self.assertEqual(p.mode, 'always' if key == 'escalation' else 'optional', key)
            self.assertEqual((p.remind_after_min, p.escalate_after_min, p.max_reminders), (15, 30, 2))

    def test_policy_absent_means_never(self):
        self.assertIsNone(PhoneAlertPolicy.for_event('x'))

    def test_switches_default_off(self):
        self.assertIs(settings.PHONE_ALERTS_SEND_ENABLED, False)
        self.assertIs(settings.MORNING_BRIEF_SEND_ENABLED, False)


# ── Task 2: recipient resolution + on shift ──────────────────────────────────

def _staff(name, phone, branch=None, **kw):
    u = User.objects.create_user(name, password='x')
    return StaffProfile.objects.create(user=u, role='salesperson', phone=phone, branch=branch, **kw)


class _Src:
    """Minimal reservation/transfer-like source."""
    def __init__(self, branch, assigned_to=None):
        self.branch = branch
        self.requesting_branch = branch
        self.assigned_to_id = assigned_to.pk if assigned_to else None


class RecipientTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b1 = Branch.objects.create(softech_branch_id='901', name='B1')
        cls.b2 = Branch.objects.create(softech_branch_id='902', name='B2')
        cls.ev_owner = EVENTS['reservation_sourcing']
        cls.ev_branch = EVENTS['reservation_status_urgent']

    def _device_user(self, staff, branch, age_h, status='approved'):
        d = Device.objects.create(secret_hash=f'h{staff.pk}', branch=branch, status=status)
        DeviceUser.objects.create(device=d, user=staff, last_seen=timezone.now() - timedelta(hours=age_h))

    def test_owner_branch_specific_beats_global(self):
        g = _staff('g', '01000000001')
        s = _staff('s', '01000000002')
        WorkOwner.objects.create(kind='reservation_sourcing', staff=g)
        WorkOwner.objects.create(kind='reservation_sourcing', staff=s, branch=self.b1)
        self.assertEqual([x.staff for x in resolve(self.ev_owner, _Src(self.b1))], [s])
        self.assertEqual([x.staff for x in resolve(self.ev_owner, _Src(self.b2))], [g])

    def test_owner_ignores_escalation_and_inactive_rows(self):
        a = _staff('a', '01000000003')
        b = _staff('b', '01000000004')
        WorkOwner.objects.create(kind='reservation_sourcing', staff=a, is_escalation=True)
        WorkOwner.objects.create(kind='reservation_sourcing', staff=b, active=False)
        self.assertEqual(resolve(self.ev_owner, _Src(self.b1)), [])

    def test_branch_group_includes_branch_mobile(self):
        BranchSettings.objects.create(branch=self.b1, alert_mobile='01099999999')
        r = resolve(self.ev_branch, _Src(self.b1))
        self.assertEqual([(x.staff, x.phone) for x in r], [(None, '201099999999')])

    def test_branch_without_settings_row_ok(self):
        self.assertEqual(resolve(self.ev_branch, _Src(self.b2)), [])

    def test_on_shift_uses_device_last_seen_4h(self):
        fresh = _staff('fresh', '01000000005', self.b1)
        stale = _staff('stale', '01000000006', self.b1)
        self._device_user(fresh, self.b1, 1)
        self._device_user(stale, self.b1, 5)
        self.assertEqual(on_shift_staff(self.b1), [fresh])

    def test_on_shift_uses_shift_assignment(self):
        st = _staff('shifty', '01000000007', self.b1)
        now = timezone.now()
        local = timezone.localtime(now)
        day = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'][local.weekday()]
        t = ShiftTemplate.objects.create(name='d', name_ar='د', branch=self.b1, start_time=time(0, 0),
                                         end_time=time(23, 59), days_of_week=day)
        ShiftAssignment.objects.create(staff=st, shift=t, valid_from=local.date())
        self.assertEqual(on_shift_staff(self.b1, now), [st])
        t.days_of_week = 'xxx'
        t.save()
        self.assertEqual(on_shift_staff(self.b1, now), [])

    def test_dedup_by_phone_across_groups(self):
        person = _staff('o', '01012345678', self.b1)
        self._device_user(person, self.b1, 0)
        BranchSettings.objects.create(branch=self.b1, alert_mobile='+20 101 234 5678')
        r = resolve(self.ev_branch, _Src(self.b1))
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].staff, person)   # staff wins over the bare branch mobile

    def test_actor_not_alerted(self):
        actor = _staff('actor', '01000000008', self.b1)
        other = _staff('other', '01000000009', self.b1)
        self._device_user(actor, self.b1, 0)
        self._device_user(other, self.b1, 0)
        r = resolve(self.ev_branch, _Src(self.b1), actor=actor)
        self.assertEqual([x.staff for x in r], [other])

    def test_opted_out_staff_skipped(self):
        off = _staff('off', '01000000010', self.b1, phone_alerts_enabled=False)
        nophone = _staff('np', '', self.b1)
        self._device_user(off, self.b1, 0)
        self._device_user(nophone, self.b1, 0)
        self.assertEqual(resolve(self.ev_branch, _Src(self.b1)), [])

    def test_device_path_requires_home_branch(self):
        visitor = _staff('visitor', '01000000020', self.b2)
        self._device_user(visitor, self.b1, 0)
        self.assertEqual(on_shift_staff(self.b1), [])

    def test_device_must_be_approved(self):
        a = _staff('pend', '01000000021', self.b1)
        b = _staff('rev', '01000000022', self.b1)
        self._device_user(a, self.b1, 0, status='pending')
        self._device_user(b, self.b1, 0, status='retired')
        self.assertEqual(on_shift_staff(self.b1), [])

    def test_implausible_phones_rejected(self):
        junk = _staff('junk', 'abc', self.b1)
        blank = _staff('blank', '  ', self.b1)
        self._device_user(junk, self.b1, 0)
        self._device_user(blank, self.b1, 0)
        BranchSettings.objects.create(branch=self.b1, alert_mobile='xyz')
        self.assertEqual(resolve(self.ev_branch, _Src(self.b1)), [])

    def test_overnight_shift(self):
        st = _staff('night', '01000000023', self.b1)
        t = ShiftTemplate.objects.create(name='n', name_ar='ن', branch=self.b1, start_time=time(22, 0),
                                         end_time=time(6, 0), days_of_week='monday')
        ShiftAssignment.objects.create(staff=st, shift=t, valid_from=datetime(2026, 1, 1).date())
        tz = timezone.get_current_timezone()
        mon_night = timezone.make_aware(datetime(2026, 11, 2, 23, 0), tz)    # Monday 23:00
        tue_early = timezone.make_aware(datetime(2026, 11, 3, 2, 0), tz)     # Tuesday 02:00 (Monday's shift)
        tue_night = timezone.make_aware(datetime(2026, 11, 3, 23, 0), tz)    # Tuesday 23:00: not a shift day
        mon_noon = timezone.make_aware(datetime(2026, 11, 2, 12, 0), tz)
        self.assertEqual(on_shift_staff(self.b1, mon_night), [st])
        self.assertEqual(on_shift_staff(self.b1, tue_early), [st])
        self.assertEqual(on_shift_staff(self.b1, tue_night), [])
        self.assertEqual(on_shift_staff(self.b1, mon_noon), [])

    def test_transfer_branch_is_requesting_branch(self):
        s = _staff('ts', '01000000024')
        WorkOwner.objects.create(kind='hq_transfer_dispatch', staff=s, branch=self.b1)
        other = _staff('to', '01000000025')
        WorkOwner.objects.create(kind='hq_transfer_dispatch', staff=other, branch=self.b2)
        tr = TransferRequest.objects.create(requesting_branch=self.b1, supplying_branch=self.b2)
        self.assertEqual([x.staff for x in resolve(EVENTS['transfer_hq_submitted'], tr)], [s])

    def test_task_branch_and_assignees(self):
        creator = _staff('tc', '01000000026', self.b1)
        a1 = _staff('t1', '01000000027')
        a2 = _staff('t2', '01000000028')
        task = OperationalTask.objects.create(title='x', created_by=creator, assigned_to=a1)
        TaskAssignment.objects.create(task=task, staff=a2)
        self.assertEqual([x.staff for x in resolve(EVENTS['task_assigned'], task)], [a1, a2])
        # No task.branch -> creator's branch drives branch-group resolution.
        from apps.notifications.phone_alerts.recipients import source_branch
        self.assertEqual(source_branch(EVENTS['task_assigned'], task), self.b1)
        task.branch = self.b2
        self.assertEqual(source_branch(EVENTS['task_assigned'], task), self.b2)

    def test_escalation_falls_back_to_supervisors_without_owner_kind(self):
        u = User.objects.create_user('sup', password='x')
        sup = StaffProfile.objects.create(user=u, role='supervisor', phone='01000000029')
        orig = PhoneAlert(event='task_assigned', phone='201')
        self.assertEqual([x.staff for x in resolve(EVENTS['escalation'], orig)], [sup])

    def test_escalation_policy_list_else_escalation_owner(self):
        esc_owner = _staff('eo', '01000000012')
        listed = _staff('li', '01000000013')
        WorkOwner.objects.create(kind='reservation_sourcing', staff=esc_owner, is_escalation=True)
        orig = PhoneAlert(event='reservation_sourcing', phone='201')   # unsaved: source None
        ev = EVENTS['escalation']
        self.assertEqual([x.staff for x in resolve(ev, orig)], [esc_owner])
        PhoneAlertPolicy.for_event('escalation').escalate_to.add(listed)
        self.assertEqual([x.staff for x in resolve(ev, orig)], [listed])

    def test_person_assigned_to(self):
        p = _staff('p', '01000000011')
        task = OperationalTask.objects.create(title='y', assigned_to=p)
        self.assertEqual([x.staff for x in resolve(EVENTS['task_assigned'], task)], [p])

    def test_transfer_status_goes_to_requesting_branch_group(self):
        on = _staff('on', '01000000030', self.b1)
        self._device_user(on, self.b1, 0)
        BranchSettings.objects.create(branch=self.b1, alert_mobile='01099999998')
        tr = TransferRequest.objects.create(requesting_branch=self.b1, supplying_branch=self.b2)
        r = resolve(EVENTS['transfer_status'], tr)
        self.assertEqual([(x.staff, x.phone) for x in r], [(on, '201000000030'), (None, '201099999998')])

    def test_task_status_goes_to_task_branch_group_with_creator_fallback(self):
        creator = _staff('tcr', '01000000031', self.b1)
        on1 = _staff('on1', '01000000032', self.b1)
        on2 = _staff('on2', '01000000033', self.b2)
        self._device_user(on1, self.b1, 0)
        self._device_user(on2, self.b2, 0)
        BranchSettings.objects.create(branch=self.b1, alert_mobile='01099999997')
        task = OperationalTask.objects.create(title='x', created_by=creator)   # no task.branch
        r = resolve(EVENTS['task_status'], task)
        self.assertEqual([(x.staff, x.phone) for x in r], [(on1, '201000000032'), (None, '201099999997')])
        task.branch = self.b2
        self.assertEqual([x.staff for x in resolve(EVENTS['task_status'], task)], [on2])


# ── Task 3: dispatch + sender ────────────────────────────────────────────────
from unittest import mock

from django.test import override_settings

from apps.config.models import SystemSetting
from apps.notifications.phone_alerts import dispatch, sender
from apps.notifications.phone_alerts.models import PhoneAlertAttempt
from apps.omni.models import ChannelAccount

SEND_TPL = 'apps.whatsapp.sender.WhatsAppSender.send_template'


def _conf(value=True):
    return mock.patch('apps.whatsapp.sender.WhatsAppSender.is_configured',
                      new_callable=mock.PropertyMock, return_value=value)


def _sms_conf(value):
    return mock.patch('core.sms.SmsSender.is_configured', new_callable=mock.PropertyMock,
                      return_value=value)


def _account(active=True):
    return ChannelAccount.objects.create(channel='whatsapp', name='Staff', phone_or_handle='201000000999',
                                         provider='meta_cloud', is_active=active)


def _use_account(acc):
    SystemSetting.objects.update_or_create(
        key='phone_alerts_channel_account',
        defaults={'label': 'x', 'value': str(acc.pk), 'value_type': 'integer'})


class DispatchSenderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b1 = Branch.objects.create(softech_branch_id='911', name='فرع ١')
        cls.b2 = Branch.objects.create(softech_branch_id='912', name='فرع ٢')
        cls.owner = _staff('own', '01000000041')
        WorkOwner.objects.create(kind='hq_transfer_dispatch', staff=cls.owner)

    def _transfer(self, phone_alert=False):
        return TransferRequest.objects.create(requesting_branch=self.b1, supplying_branch=self.b2,
                                              phone_alert=phone_alert)

    def _fire(self, tr, **kw):
        with self.captureOnCommitCallbacks(execute=True):
            return dispatch.fire('transfer_hq_submitted', tr, **kw)

    def test_optional_needs_request(self):
        tr = self._transfer(phone_alert=False)
        self.assertEqual(self._fire(tr), [])
        self.assertEqual(PhoneAlert.objects.count(), 0)
        self.assertEqual(len(self._fire(tr, requested=True)), 1)
        tr2 = self._transfer(phone_alert=True)
        self.assertEqual(len(self._fire(tr2)), 1)

    def test_never_ignores_request(self):
        PhoneAlertPolicy.objects.filter(event='transfer_hq_submitted').update(mode='never')
        self.assertEqual(self._fire(self._transfer(True), requested=True), [])

    def test_always_sends_without_request(self):
        PhoneAlertPolicy.objects.filter(event='transfer_hq_submitted').update(mode='always')
        alerts = self._fire(self._transfer(False))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].phone, '201000000041')
        self.assertEqual(alerts[0].recipient_staff, self.owner)

    def test_unknown_event_returns_empty(self):
        self.assertEqual(dispatch.fire('nope', self._transfer(True)), [])

    @override_settings(PHONE_ALERTS_SEND_ENABLED=False)
    def test_dry_run_when_switch_off(self):
        _use_account(_account())
        with mock.patch(SEND_TPL) as send:
            alerts = self._fire(self._transfer(True))
        send.assert_not_called()
        a = PhoneAlert.objects.get(pk=alerts[0].pk)
        self.assertEqual(a.status, 'sent')
        self.assertIsNotNone(a.last_sent_at)
        self.assertEqual(list(a.attempts.values_list('result', flat=True)), ['dry_run'])

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True)
    def test_dry_run_when_no_account(self):
        with mock.patch(SEND_TPL) as send:
            alerts = self._fire(self._transfer(True))
        send.assert_not_called()
        self.assertEqual(alerts[0].attempts.get().result, 'dry_run')
        # inactive account is the same as none
        _use_account(_account(active=False))
        self.assertIsNone(sender.staff_account())

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True)
    def test_sends_payload_with_token(self):
        acc = _account()
        _use_account(acc)
        self.assertEqual(sender.staff_account(), acc)
        tr = self._transfer(True)
        with _conf(), mock.patch(SEND_TPL, return_value={'messages': [{'id': 'wamid.X'}]}) as send:
            alerts = self._fire(tr)
        a = PhoneAlert.objects.get(pk=alerts[0].pk)
        kw = send.call_args.kwargs
        self.assertEqual(kw['quick_reply_payloads'], [f'alert:{a.token}:ack'])
        self.assertEqual(kw['template_name'], 'staff_alert')
        self.assertEqual(kw['wa_id'], '201000000041')
        texts = [v['text'] for v in kw['variables']]
        self.assertEqual(texts[0], 'تحويل جديد للمخزن الرئيسي')
        self.assertEqual(texts[1], 'فرع ١')
        self.assertEqual(texts[3], str(tr.request_number or tr.pk))
        self.assertTrue(all('\n' not in t and t == t.strip() for t in texts))
        self.assertEqual((a.status, a.wa_message_id), ('sent', 'wamid.X'))
        self.assertEqual(a.attempts.get().result, 'sent')

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True)
    def test_reminder_prefix(self):
        _use_account(_account())
        self._fire(self._transfer(True))
        a = PhoneAlert.objects.get()
        with _conf(), mock.patch(SEND_TPL, return_value={}) as send:
            sender.deliver(a, reminder=True)
        self.assertTrue(send.call_args.kwargs['variables'][0]['text'].startswith('تذكير: '))

    def test_no_duplicate_open_alert(self):
        tr = self._transfer(True)
        self.assertEqual(len(self._fire(tr)), 1)
        self.assertEqual(self._fire(tr), [])
        self.assertEqual(PhoneAlert.objects.count(), 1)
        PhoneAlert.objects.update(status='acknowledged')
        self.assertEqual(len(self._fire(tr)), 1)

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True)
    def test_whatsapp_failure_falls_back_to_sms_when_configured(self):
        _use_account(_account())
        self._fire(self._transfer(True))
        a = PhoneAlert.objects.get()
        with _conf(), mock.patch(SEND_TPL, side_effect=RuntimeError('boom')), _sms_conf(True), \
                mock.patch('core.sms.SmsSender.send', return_value={'ok': True}) as sms:
            sender.deliver(a)
        a.refresh_from_db()
        self.assertEqual(a.status, 'sent')
        sms.assert_called_once()
        self.assertEqual(sms.call_args.args[0], '201000000041')
        self.assertEqual([(t.channel, t.result) for t in a.attempts.all()][-2:],
                         [('whatsapp', 'failed'), ('sms', 'sent')])

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True)
    def test_whatsapp_failure_without_sms_marks_failed_and_never_raises(self):
        _use_account(_account())
        self._fire(self._transfer(True))
        a = PhoneAlert.objects.get()
        with _conf(), mock.patch(SEND_TPL, side_effect=RuntimeError('boom')), _sms_conf(False):
            att = sender.deliver(a)
        a.refresh_from_db()
        self.assertEqual(a.status, 'failed')
        self.assertEqual(att.result, 'failed')
        self.assertIn('boom', att.error)

    def test_fire_never_raises(self):
        with mock.patch.object(dispatch, 'resolve', side_effect=RuntimeError('x')):
            self.assertEqual(dispatch.fire('transfer_hq_submitted', self._transfer(True)), [])


class DispatchFixRound1Tests(DispatchSenderTests):
    """Fix round 1 (inherits helpers; its own tests re-run harmlessly)."""

    def test_fire_failure_rolls_back_and_keeps_transaction_usable(self):
        second = _staff('own2', '01000000042')
        WorkOwner.objects.create(kind='hq_transfer_dispatch', staff=second)
        tr = self._transfer(True)
        real = PhoneAlert.objects.create
        calls = []

        def flaky(*a, **kw):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError('db')
            return real(*a, **kw)
        with mock.patch.object(PhoneAlert.objects, 'create', side_effect=flaky):
            self.assertEqual(dispatch.fire('transfer_hq_submitted', tr), [])
        self.assertEqual(PhoneAlert.objects.count(), 0)
        self.assertEqual(TransferRequest.objects.count(), 1)   # caller can keep querying

    def test_crash_guard_keeps_acknowledged_status(self):
        self._fire(self._transfer(True))
        a = PhoneAlert.objects.get()
        PhoneAlert.objects.filter(pk=a.pk).update(status='acknowledged')
        a.refresh_from_db()
        with mock.patch.object(sender, 'staff_account', side_effect=RuntimeError('x')):
            sender.deliver(a, reminder=True)
        a.refresh_from_db()
        self.assertEqual(a.status, 'acknowledged')

    def test_escalation_alert_describes_original_and_sets_escalation_of(self):
        PhoneAlertPolicy.objects.filter(event='escalation').update(mode='always')
        tr = self._transfer(True)
        self._fire(tr)
        orig = PhoneAlert.objects.get()
        sup = _staff('sup3', '01000000043')
        WorkOwner.objects.create(kind='hq_transfer_dispatch', staff=sup, is_escalation=True)
        with self.captureOnCommitCallbacks(execute=True):
            esc = dispatch.fire('escalation', orig)
        self.assertEqual(len(esc), 1)
        self.assertEqual(esc[0].escalation_of, orig)
        self.assertEqual(esc[0].recipient_staff, sup)
        variables, _ = sender.build_staff_alert(esc[0])
        texts = [v['text'] for v in variables]
        self.assertEqual(texts[0], 'تصعيد: تحويل جديد للمخزن الرئيسي')
        self.assertEqual(texts[1], 'فرع ١')
        self.assertEqual(texts[3], str(tr.request_number or tr.pk))

    @override_settings(PHONE_ALERTS_SEND_ENABLED=False, MORNING_BRIEF_SEND_ENABLED=True)
    def test_brief_kind_uses_brief_switch(self):
        acc = _account()
        _use_account(acc)
        self._fire(self._transfer(True))
        a = PhoneAlert.objects.get()
        a.kind = 'brief'
        with _conf(), mock.patch(SEND_TPL, return_value={}) as send:
            sender.deliver(a)
        send.assert_called_once()

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True)
    def test_sms_send_failure_marks_failed(self):
        _use_account(_account())
        self._fire(self._transfer(True))
        a = PhoneAlert.objects.get()
        with _conf(), mock.patch(SEND_TPL, side_effect=RuntimeError('boom')), _sms_conf(True), \
                mock.patch('core.sms.SmsSender.send', side_effect=RuntimeError('smsdown')):
            att = sender.deliver(a)
        a.refresh_from_db()
        self.assertEqual(a.status, 'failed')
        self.assertEqual((att.channel, att.result), ('sms', 'failed'))

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True)
    def test_inactive_account_through_deliver_is_dry_run(self):
        _use_account(_account(active=False))
        self._fire(self._transfer(True))
        a = PhoneAlert.objects.get()
        with mock.patch(SEND_TPL) as send:
            att = sender.deliver(a)
        send.assert_not_called()
        self.assertEqual(att.result, 'dry_run')


# ── Task 4: inbound taps, remarks, staff inbox separation ────────────────────
from django.contrib.contenttypes.models import ContentType

from apps.notifications.models import Notification
from apps.notifications.phone_alerts import inbound
from apps.reservations.models import Reservation, ReservationActivity
from apps.tasks.models import TaskMessage
from apps.transfers.models import TransferRequestMessage
from apps.whatsapp import button_registry, webhook
from apps.whatsapp.models import WAConversation, WAMessage

from .factories import make_item


def _wh(value):
    return {'object': 'whatsapp_business_account',
            'entry': [{'id': '1', 'changes': [{'value': value}]}]}


class InboundTests(TestCase):
    PHONE = '01000000051'
    WA = '201000000051'

    @classmethod
    def setUpTestData(cls):
        cls.b1 = Branch.objects.create(softech_branch_id='921', name='فرع ١')
        cls.b2 = Branch.objects.create(softech_branch_id='922', name='فرع ٢')
        cls.person = _staff('pers', cls.PHONE, cls.b2)

    def setUp(self):
        self.acc = _account()
        _use_account(self.acc)
        self.tr = TransferRequest.objects.create(requesting_branch=self.b1, supplying_branch=self.b2)

    def _alert(self, source=None, phone=None, **kw):
        source = source or self.tr
        return PhoneAlert.objects.create(
            event='transfer_status', source_ct=ContentType.objects.get_for_model(source),
            source_id=source.pk, recipient_staff=self.person, phone=phone or self.WA, **kw)

    def _tap(self, alert, wa=None):
        return inbound.handle_alert_tap(wa_id=wa or self.WA, payload=f'alert:{alert.token}:ack',
                                        account=self.acc)

    def _post_webhook(self, messages=None, statuses=None, pid='555'):
        value = {'metadata': {'phone_number_id': pid, 'display_phone_number': '1'}}
        if messages:
            value['messages'] = messages
        if statuses:
            value['statuses'] = statuses
        webhook.process_webhook(_wh(value))

    # status callbacks
    def test_status_callback_updates_alert_not_downgrade(self):
        a = self._alert(status='sent', wa_message_id='wamid.A')
        self._post_webhook(statuses=[{'id': 'wamid.A', 'status': 'delivered'}])
        a.refresh_from_db()
        self.assertEqual(a.status, 'delivered')
        self._post_webhook(statuses=[{'id': 'wamid.A', 'status': 'read'}])
        a.refresh_from_db()
        self.assertEqual(a.status, 'read')
        self._post_webhook(statuses=[{'id': 'wamid.A', 'status': 'delivered'}])
        a.refresh_from_db()
        self.assertEqual(a.status, 'read')                      # no downgrade
        self.assertEqual(list(a.attempts.values_list('result', flat=True)), ['delivered', 'read', 'delivered'])
        for st in ('acknowledged', 'escalated', 'expired'):
            PhoneAlert.objects.filter(pk=a.pk).update(status=st)
            self._post_webhook(statuses=[{'id': 'wamid.A', 'status': 'read'},
                                         {'id': 'wamid.A', 'status': 'failed',
                                          'errors': [{'code': 131, 'title': 'x'}]}])
            a.refresh_from_db()
            self.assertEqual(a.status, st)
        self.assertEqual(a.attempts.filter(result='failed').first().error, '131 x')

    # tap
    def test_tap_acknowledges_and_posts_chatter(self):
        a = self._alert(status='sent')
        self.assertEqual(self._tap(a), 'acknowledged')
        a.refresh_from_db()
        self.assertEqual((a.status, a.ack_at is not None), ('acknowledged', True))
        msg = TransferRequestMessage.objects.get(request=self.tr)
        self.assertIn(self.person.full_name, msg.message)
        self.assertIn('استلم', msg.message)
        self.assertEqual(msg.created_by, self.person)

    def test_tap_from_other_phone_ignored(self):
        a = self._alert(status='sent')
        self.assertEqual(self._tap(a, wa='201099999999'), 'wrong_sender')
        a.refresh_from_db()
        self.assertEqual((a.status, a.ack_at), ('sent', None))
        self.assertFalse(TransferRequestMessage.objects.exists())

    def test_second_tap_noop(self):
        a = self._alert(status='sent')
        self._tap(a)
        first = PhoneAlert.objects.get(pk=a.pk).ack_at
        self.assertEqual(self._tap(a), 'duplicate')
        self.assertEqual(PhoneAlert.objects.get(pk=a.pk).ack_at, first)
        self.assertEqual(TransferRequestMessage.objects.count(), 1)

    def test_tap_unknown_token_and_foreign_payload(self):
        self.assertEqual(inbound.handle_alert_tap(wa_id=self.WA, payload='alert:nope:ack'), 'unknown')
        self.assertEqual(inbound.handle_alert_tap(wa_id=self.WA, payload='refill:1:stop'), 'not_ours')

    @override_settings(PHONE_ALERTS_SEND_ENABLED=True)
    def test_tap_replies_with_confirmation(self):
        a = self._alert(status='sent')
        with _conf(), mock.patch('apps.whatsapp.sender.WhatsAppSender.send_text') as send:
            self._tap(a)
        send.assert_called_once()
        self.assertEqual(send.call_args.kwargs['body'], inbound.REPLY_TEXT)

    def test_chatter_for_reservation_and_task(self):
        res = Reservation.objects.create(item=make_item(), branch=self.b1, quantity_requested=1,
                                         contact_name='ع', contact_phone='01033333333')
        other = _staff('r1', '01000000052', self.b1)
        a = self._alert(source=res)
        self._tap(a)
        act = ReservationActivity.objects.get(reservation=res)
        self.assertEqual((act.activity_type, act.created_by), ('note', self.person))
        self.assertTrue(Notification.objects.filter(recipient=other, reservation=res).exists())
        task = OperationalTask.objects.create(title='t', created_by=other)
        a2 = self._alert(source=task)
        self._tap(a2)
        self.assertEqual(TaskMessage.objects.get(task=task).message_type, 'comment')

    def test_escalation_tap_posts_to_original_source(self):
        orig = self._alert(status='sent')
        esc = PhoneAlert.objects.create(
            event='escalation', source_ct=ContentType.objects.get_for_model(PhoneAlert), source_id=orig.pk,
            escalation_of=orig, recipient_staff=self.person, phone=self.WA, status='sent')
        self._tap(esc)
        self.assertEqual(TransferRequestMessage.objects.filter(request=self.tr).count(), 1)

    # remarks
    def _text(self, text, context='', wa=None):
        return inbound.handle_free_text(wa_id=wa or self.WA, text=text, context_wamid=context,
                                        account=self.acc)

    def test_remark_attached_by_quote(self):
        a = self._alert(status='sent', wa_message_id='wamid.Q')
        b = self._alert(status='acknowledged', ack_at=timezone.now())
        self.assertEqual(self._text('هنوصل بعد ساعة', context='wamid.Q'), 'remark')
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.remark, b.remark), ('هنوصل بعد ساعة', ''))
        self.assertIn('هنوصل بعد ساعة', TransferRequestMessage.objects.get().message)

    def test_quote_from_other_phone_not_attached(self):
        a = self._alert(status='sent', wa_message_id='wamid.Q')
        self.assertEqual(self._text('x', context='wamid.Q', wa='201099999999'), 'unmatched')
        a.refresh_from_db()
        self.assertEqual(a.remark, '')

    def test_remark_attached_single_recent_ack(self):
        a = self._alert(status='acknowledged', ack_at=timezone.now() - timedelta(minutes=5))
        self.assertEqual(self._text('ملاحظة'), 'remark')
        a.refresh_from_db()
        self.assertEqual(a.remark, 'ملاحظة')
        self.assertEqual(self._text('تانية'), 'unmatched')       # now has a remark: nothing open

    def test_remark_old_ack_not_attached(self):
        self._alert(status='acknowledged', ack_at=timezone.now() - timedelta(minutes=45))
        self.assertEqual(self._text('متأخر'), 'unmatched')

    def test_remark_ambiguous_not_attached(self):
        a = self._alert(status='acknowledged', ack_at=timezone.now())
        b = self._alert(status='acknowledged', ack_at=timezone.now())
        self.assertEqual(self._text('أي واحد؟'), 'unmatched')
        for x in (a, b):
            x.refresh_from_db()
            self.assertEqual(x.remark, '')
        self.assertFalse(TransferRequestMessage.objects.exists())

    # webhook routing
    def _inbound(self, kind, pid):
        base = {'from': self.WA, 'timestamp': '1'}
        if kind == 'button':
            return {**base, 'id': 'wamid.in1', 'type': 'button',
                    'button': {'text': 'استلمت', 'payload': pid}}
        return {**base, 'id': 'wamid.in2', 'type': 'text', 'text': {'body': pid}}

    def test_staff_account_message_not_in_customer_inbox(self):
        self.acc.provider_ref = '555'
        self.acc.save()
        a = self._alert(status='sent')
        self._post_webhook([self._inbound('button', f'alert:{a.token}:ack')])
        a.refresh_from_db()
        self.assertEqual(a.status, 'acknowledged')
        self._post_webhook([self._inbound('text', 'ملاحظة من الموبايل')])
        a.refresh_from_db()
        self.assertEqual(a.remark, 'ملاحظة من الموبايل')
        self.assertFalse(WAConversation.objects.filter(wa_id=self.WA).exists())
        self.assertFalse(WAMessage.objects.filter(direction='inbound').exists())

    def test_customer_account_still_in_inbox_and_routes_button(self):
        other = ChannelAccount.objects.create(channel='whatsapp', name='Cust', phone_or_handle='1',
                                              provider='meta_cloud', provider_ref='777')
        a = self._alert(status='sent')
        self._post_webhook([self._inbound('button', f'alert:{a.token}:ack')], pid='777')
        self.assertEqual(WAConversation.objects.get(wa_id=self.WA).account, other)
        self.assertEqual(WAMessage.objects.filter(direction='inbound').count(), 1)
        a.refresh_from_db()
        self.assertEqual(a.status, 'acknowledged')

    def test_refill_payload_still_routed(self):
        with mock.patch('apps.followups.refill_reminders.handle_button_reply', return_value='branch') as h:
            out = button_registry.dispatch(wa_id=self.WA, payload='refill:1:branch', account=None)
        self.assertEqual(out, 'branch')
        h.assert_called_once()
        self.assertEqual(button_registry.dispatch(wa_id=self.WA, payload='refill:999999:branch'), 'unknown')
        self.assertEqual(button_registry.dispatch(wa_id=self.WA, payload='zzz'), 'not_ours')


# ── Task 4 fix round 1 ───────────────────────────────────────────────────────
from apps.notifications.phone_alerts.models import PhoneAlertAttempt as _Attempt

from .factories import make_admin


class InboundFixRound1Tests(InboundTests):
    """Re-runs every InboundTests case too (flag set where the account is the staff number)."""

    def test_staff_threads_hidden_from_customer_inbox(self):
        ChannelAccount.objects.filter(pk=self.acc.pk).update(is_staff_alerts=True)
        a = self._alert(status='sent')
        from apps.whatsapp.sender import WhatsAppSender
        WhatsAppSender(account=self.acc)._record_outbound(self.WA, 'template', body='x')
        WhatsAppSender(account=self.acc)._record_outbound(self.WA, 'text', body=inbound.REPLY_TEXT)
        self.assertEqual(WAConversation.objects.filter(account=self.acc).count(), 1)
        cust = ChannelAccount.objects.create(channel='whatsapp', name='C', phone_or_handle='1',
                                             provider='meta_cloud', provider_ref='888')
        c = WAConversation.objects.create(account=cust, wa_id='201111111111', unread_count=3)
        WAConversation.objects.filter(account=self.acc).update(unread_count=9)
        _, _, client = make_admin('inbox_admin')
        data = client.get('/api/whatsapp/conversations/').json()
        rows = data['results'] if isinstance(data, dict) else data
        self.assertEqual([r['id'] for r in rows], [c.pk])
        staff_conv = WAConversation.objects.get(account=self.acc)
        self.assertEqual(client.get(f'/api/whatsapp/conversations/{staff_conv.pk}/').status_code, 404)
        omni = client.get('/api/omni/wallboard/')
        self.assertEqual(omni.status_code, 200)
        self.assertEqual(omni.json()['conversations']['wa_unread'], 3)
        del a

    def test_flagged_account_no_longer_configured_still_routes_to_staff(self):
        self.acc.provider_ref = '555'
        self.acc.is_staff_alerts = True
        self.acc.save()
        SystemSetting.objects.filter(key='phone_alerts_channel_account').delete()
        self.assertIsNone(sender.staff_account())
        a = self._alert(status='sent')
        self._post_webhook([self._inbound('button', f'alert:{a.token}:ack')])
        a.refresh_from_db()
        self.assertEqual(a.status, 'acknowledged')
        self.assertFalse(WAConversation.objects.filter(wa_id=self.WA).exists())

    def test_reply_quoting_first_send_after_reminder_attaches(self):
        a = self._alert(status='sent', wa_message_id='wamid.SECOND')
        _Attempt.objects.create(alert=a, result='sent', provider_message_id='wamid.FIRST')
        _Attempt.objects.create(alert=a, result='sent', provider_message_id='wamid.SECOND')
        self.assertEqual(self._text('رد على الأولى', context='wamid.FIRST'), 'remark')
        a.refresh_from_db()
        self.assertEqual(a.remark, 'رد على الأولى')

    def test_late_receipt_for_first_send_recorded(self):
        a = self._alert(status='sent', wa_message_id='wamid.SECOND')
        _Attempt.objects.create(alert=a, result='sent', provider_message_id='wamid.FIRST')
        self._post_webhook(statuses=[{'id': 'wamid.FIRST', 'status': 'delivered'}])
        self.assertTrue(a.attempts.filter(result='delivered', provider_message_id='wamid.FIRST').exists())

    def test_late_tap_on_expired_or_escalated_records_ack(self):
        for st in ('expired', 'escalated'):
            a = self._alert(status=st)
            self.assertEqual(self._tap(a), 'acknowledged')
            a.refresh_from_db()
            self.assertEqual((a.status, a.ack_at is not None), ('acknowledged', True))

    def test_unsupported_staff_message_type_logged(self):
        self.acc.provider_ref = '555'
        self.acc.save()
        with self.assertLogs('elrezeiky.whatsapp', level='INFO') as cm:
            self._post_webhook([{'from': self.WA, 'id': 'wamid.v', 'timestamp': '1', 'type': 'audio',
                                 'audio': {'id': 'm1'}}])
        self.assertTrue(any('unsupported audio' in m for m in cm.output))


    def test_staff_account_messages_not_ingested_into_omni(self):
        from django.core.management import call_command
        from apps.omni.models import Conversation, TimelineEvent
        ChannelAccount.objects.filter(pk=self.acc.pk).update(is_staff_alerts=True)
        self.acc.refresh_from_db()
        from apps.whatsapp.sender import WhatsAppSender
        WhatsAppSender(account=self.acc)._record_outbound(self.WA, 'template', body='alert')
        WhatsAppSender(account=self.acc)._record_outbound(self.WA, 'text', body=inbound.REPLY_TEXT)
        self.assertEqual(WAMessage.objects.filter(conversation__account=self.acc).count(), 2)
        self.assertEqual((Conversation.objects.count(), TimelineEvent.objects.count()), (0, 0))
        call_command('backfill_omni', verbosity=0)
        self.assertEqual((Conversation.objects.count(), TimelineEvent.objects.count()), (0, 0))
        # a customer account is still ingested
        cust = ChannelAccount.objects.create(channel='whatsapp', name='C2', phone_or_handle='2',
                                             provider='meta_cloud', provider_ref='889')
        WhatsAppSender(account=cust)._record_outbound('201122222222', 'text', body='hi')
        self.assertEqual(TimelineEvent.objects.count(), 1)


# ── Task 5: reminder / escalation / expiry tick ──────────────────────────────
from apps.notifications.phone_alerts import jobs


class EventIsOpenTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.b1 = Branch.objects.create(softech_branch_id='931', name='ف١')
        cls.b2 = Branch.objects.create(softech_branch_id='932', name='ف٢')
        cls.person = _staff('iop', '01000000061', cls.b1)

    def _res(self):
        return Reservation.objects.create(item=make_item(), branch=self.b1, quantity_requested=1,
                                          contact_name='ع', contact_phone='01033333333')

    def test_reservation_open_only_when_pending_for_sourcing(self):
        res = self._res()
        ev = EVENTS['reservation_sourcing']
        self.assertEqual(res.status, 'pending')
        self.assertTrue(ev.is_open(res))
        res.status = 'fulfilled'
        self.assertFalse(ev.is_open(res))

    def test_reservation_urgent_status_open_until_closed(self):
        res = self._res()
        ev = EVENTS['reservation_status_urgent']
        self.assertTrue(ev.is_open(res))
        for closed in ('fulfilled', 'cancelled', 'expired'):
            res.status = closed
            self.assertFalse(ev.is_open(res), closed)

    def test_transfer_open_and_closed(self):
        tr = TransferRequest.objects.create(requesting_branch=self.b1, supplying_branch=self.b2)
        for key in ('transfer_hq_submitted', 'transfer_status'):
            self.assertTrue(EVENTS[key].is_open(tr), key)
        for closed in ('sent_to_erp', 'completed', 'rejected', 'cancelled'):
            tr.status = closed
            for key in ('transfer_hq_submitted', 'transfer_status'):
                self.assertFalse(EVENTS[key].is_open(tr), (key, closed))

    def test_task_open_and_closed(self):
        task = OperationalTask.objects.create(title='t', created_by=self.person)
        for key in ('task_assigned', 'task_status'):
            self.assertTrue(EVENTS[key].is_open(task), key)
        for closed in ('completed', 'cancelled'):
            task.status = closed
            for key in ('task_assigned', 'task_status'):
                self.assertFalse(EVENTS[key].is_open(task), (key, closed))

    def test_deleted_source_is_closed(self):
        for ev in EVENTS.values():
            self.assertFalse(ev.is_open(None), ev.key)

    def test_escalation_open_follows_original(self):
        tr = TransferRequest.objects.create(requesting_branch=self.b1, supplying_branch=self.b2)
        ct = ContentType.objects.get_for_model(tr)
        orig = PhoneAlert.objects.create(event='transfer_hq_submitted', source_ct=ct, source_id=tr.pk,
                                         phone='201000000061', status='escalated')
        esc = PhoneAlert.objects.create(
            event='escalation', phone='201000000062', escalation_of=orig, status='sent',
            source_ct=ContentType.objects.get_for_model(PhoneAlert), source_id=orig.pk)
        ev = EVENTS['escalation']

        def fresh():
            return PhoneAlert.objects.get(pk=esc.pk)

        # an escalated original keeps its escalation open until it is acknowledged
        self.assertTrue(ev.is_open(fresh()))
        for done in ('acknowledged', 'expired'):
            PhoneAlert.objects.filter(pk=orig.pk).update(status=done)
            self.assertFalse(ev.is_open(fresh()), done)
        PhoneAlert.objects.filter(pk=orig.pk).update(status='escalated')
        self.assertTrue(ev.is_open(fresh()))
        tr.status = 'completed'
        tr.save()
        self.assertFalse(ev.is_open(fresh()))


class TickTests(TestCase):
    T0 = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)

    @classmethod
    def setUpTestData(cls):
        cls.b1 = Branch.objects.create(softech_branch_id='941', name='فرع ١')
        cls.b2 = Branch.objects.create(softech_branch_id='942', name='فرع ٢')
        cls.owner = _staff('tk_own', '01000000071')
        cls.boss = _staff('tk_boss', '01000000072')
        WorkOwner.objects.create(kind='hq_transfer_dispatch', staff=cls.owner)
        WorkOwner.objects.create(kind='hq_transfer_dispatch', staff=cls.boss, is_escalation=True)

    def setUp(self):
        PhoneAlertPolicy.objects.filter(event='escalation').update(mode='always')
        self.tr = TransferRequest.objects.create(requesting_branch=self.b1, supplying_branch=self.b2)

    def _alert(self, status='sent', at=None, **kw):
        at = at or self.T0
        a = PhoneAlert.objects.create(
            event='transfer_hq_submitted', source_ct=ContentType.objects.get_for_model(self.tr),
            source_id=self.tr.pk, recipient_staff=self.owner, phone='201000000071',
            status=status, **kw)
        PhoneAlert.objects.filter(pk=a.pk).update(created_at=at, last_sent_at=at)
        return PhoneAlert.objects.get(pk=a.pk)

    def _min(self, n):
        return self.T0 + timedelta(minutes=n)

    def _no_escalation(self):
        PhoneAlertPolicy.objects.filter(event='transfer_hq_submitted').update(escalate_after_min=9999)

    def test_nothing_before_15_min(self):
        a = self._alert()
        self.assertEqual(jobs.tick(now=self._min(14)), {'reminded': 0, 'escalated': 0, 'expired': 0})
        a.refresh_from_db()
        self.assertEqual((a.status, a.reminders_sent), ('sent', 0))

    def test_reminder_after_15_min(self):
        self._no_escalation()
        a = self._alert()
        self.assertEqual(jobs.tick(now=self._min(15))['reminded'], 1)
        a.refresh_from_db()
        self.assertEqual((a.reminders_sent, a.status), (1, 'sent'))
        self.assertEqual(a.attempts.get().result, 'dry_run')
        # the next reminder is measured from the last send, not from creation
        self.assertEqual(jobs.tick(now=self._min(16))['reminded'], 0)

    def test_max_two_reminders(self):
        self._no_escalation()
        a = self._alert()
        total = 0
        for m in (15, 40, 70, 100):
            total += jobs.tick(now=self._min(m))['reminded']
            PhoneAlert.objects.filter(pk=a.pk).update(last_sent_at=self._min(m))
        a.refresh_from_db()
        self.assertEqual((total, a.reminders_sent), (2, 2))

    def test_escalates_after_30_min_once(self):
        a = self._alert()
        self.assertEqual(jobs.tick(now=self._min(30))['escalated'], 1)
        a.refresh_from_db()
        self.assertEqual((a.status, a.escalated_at), ('escalated', self._min(30)))
        esc = PhoneAlert.objects.get(event='escalation')
        self.assertEqual((esc.escalation_of, esc.recipient_staff), (a, self.boss))
        self.assertEqual(jobs.tick(now=self._min(31))['escalated'], 0)
        self.assertEqual(PhoneAlert.objects.filter(event='escalation').count(), 1)

    def test_escalation_alert_never_escalates_again(self):
        self._alert()
        jobs.tick(now=self._min(30))
        esc = PhoneAlert.objects.get(event='escalation')
        PhoneAlert.objects.filter(pk=esc.pk).update(created_at=self._min(30), last_sent_at=self._min(30))
        self.assertEqual(jobs.tick(now=self._min(120))['escalated'], 0)
        self.assertEqual(PhoneAlert.objects.filter(event='escalation').count(), 1)

    def test_closed_source_expires_alert(self):
        a = self._alert()
        self.tr.status = 'completed'
        self.tr.save()
        self.assertEqual(jobs.tick(now=self._min(60)), {'reminded': 0, 'escalated': 0, 'expired': 1})
        a.refresh_from_db()
        self.assertEqual(a.status, 'expired')
        self.assertFalse(a.attempts.exists())
        self.assertFalse(PhoneAlert.objects.filter(event='escalation').exists())

    def test_deleted_source_expires_alert(self):
        a = self._alert()
        self.tr.delete()
        self.assertEqual(jobs.tick(now=self._min(60))['expired'], 1)
        a.refresh_from_db()
        self.assertEqual(a.status, 'expired')

    def test_acknowledged_not_reminded(self):
        for status in ('acknowledged', 'queued', 'failed', 'expired', 'escalated'):
            self._alert(status=status)
        self.assertEqual(jobs.tick(now=self._min(120)), {'reminded': 0, 'escalated': 0, 'expired': 0})

    def test_delivered_and_read_are_open(self):
        self._no_escalation()
        self._alert(status='delivered')
        self._alert(status='read')
        self.assertEqual(jobs.tick(now=self._min(15))['reminded'], 2)

    def test_night_time_still_reminds(self):
        self._no_escalation()
        night = self.T0.replace(hour=3, minute=0) - timedelta(minutes=15)
        a = self._alert(at=night)
        self.assertEqual(jobs.tick(now=night + timedelta(minutes=15))['reminded'], 1)
        a.refresh_from_db()
        self.assertEqual(a.reminders_sent, 1)

    def test_event_without_policy_is_skipped(self):
        a = self._alert()
        PhoneAlertPolicy.objects.filter(event='transfer_hq_submitted').delete()
        b = PhoneAlert.objects.create(event='morning_brief', kind='brief', phone='201000000071', status='sent')
        PhoneAlert.objects.filter(pk=b.pk).update(created_at=self.T0, last_sent_at=self.T0)
        self.assertEqual(jobs.tick(now=self._min(120)), {'reminded': 0, 'escalated': 0, 'expired': 0})
        a.refresh_from_db()
        self.assertEqual(a.status, 'sent')

    def test_tick_survives_one_bad_alert(self):
        self._no_escalation()
        self._alert()
        good = self._alert()
        with mock.patch.object(jobs.sender, 'deliver', side_effect=[RuntimeError('boom'), None]):
            counts = jobs.tick(now=self._min(15))
        self.assertEqual(counts['reminded'], 1)
        good.refresh_from_db()
        self.assertEqual(good.reminders_sent, 1)

    def test_scheduler_wrapper_swallows_errors(self):
        from apps.sync import tasks
        with mock.patch.object(jobs, 'tick', side_effect=RuntimeError('x')):
            tasks._run_phone_alerts_tick()
        with mock.patch.object(jobs, 'tick') as t:
            tasks._run_phone_alerts_tick()
        t.assert_called_once_with()

    # fix round 1
    def test_fire_raising_rolls_back_and_next_tick_escalates(self):
        a = self._alert()
        with mock.patch.object(jobs.dispatch, 'fire', side_effect=RuntimeError('boom')):
            counts = jobs.tick(now=self._min(30))
        self.assertEqual(counts['escalated'], 0)
        a.refresh_from_db()
        self.assertEqual((a.status, a.escalated_at), ('sent', None))
        self.assertEqual(jobs.tick(now=self._min(31))['escalated'], 1)
        a.refresh_from_db()
        self.assertEqual(a.status, 'escalated')
        self.assertEqual(PhoneAlert.objects.filter(event='escalation').count(), 1)

    def test_real_fire_internal_failure_keeps_alert_open_then_retries(self):
        a = self._alert()
        with mock.patch.object(dispatch, 'resolve', side_effect=RuntimeError('boom')):
            counts = jobs.tick(now=self._min(30))
        self.assertEqual(counts['escalated'], 0)
        a.refresh_from_db()
        self.assertEqual((a.status, a.escalated_at), ('sent', None))
        self.assertEqual(jobs.tick(now=self._min(31))['escalated'], 1)
        a.refresh_from_db()
        self.assertEqual(a.status, 'escalated')

    def test_fire_without_flag_still_swallows_same_failure(self):
        a = self._alert()
        with mock.patch.object(dispatch, 'resolve', side_effect=RuntimeError('boom')):
            self.assertEqual(dispatch.fire('escalation', a, requested=True), [])
            with self.assertRaises(RuntimeError):
                dispatch.fire('escalation', a, requested=True, raise_errors=True)

    def test_fire_returning_nothing_marks_escalated_but_not_counted(self):
        PhoneAlertPolicy.objects.filter(event='escalation').update(mode='never')
        a = self._alert()
        self.assertEqual(jobs.tick(now=self._min(30))['escalated'], 0)
        a.refresh_from_db()
        self.assertEqual(a.status, 'escalated')
        self.assertFalse(PhoneAlert.objects.filter(event='escalation').exists())

    def test_escalating_tick_sends_no_reminder(self):
        a = self._alert()
        counts = jobs.tick(now=self._min(30))
        self.assertEqual(counts, {'reminded': 0, 'escalated': 1, 'expired': 0})
        a.refresh_from_db()
        self.assertEqual(a.reminders_sent, 0)
        self.assertFalse(a.attempts.exists())

    def test_failed_reminder_delivery_consumes_the_reminder(self):
        self._no_escalation()
        a = self._alert()
        with mock.patch.object(jobs.sender, 'deliver', side_effect=RuntimeError('boom')):
            jobs.tick(now=self._min(15))
        a.refresh_from_db()
        self.assertEqual(a.reminders_sent, 1)
        self.assertEqual(a.last_sent_at, self._min(15))
        # at-most-once: no immediate retry on the next tick
        self.assertEqual(jobs.tick(now=self._min(16))['reminded'], 0)
        a.refresh_from_db()
        self.assertEqual(a.reminders_sent, 1)


# ── Task 6: workflow hooks ───────────────────────────────────────────────────

class WorkflowHookTests(TestCase):
    """Reservation / transfer / task APIs call fire() once per real transition."""

    @classmethod
    def setUpTestData(cls):
        from .factories import make_admin, make_item, make_pharmacist
        cls.branch = Branch.objects.create(softech_branch_id='951', name='Req')
        cls.hq = Branch.objects.create(softech_branch_id='952', name='HQ', kind=Branch.KIND_HQ)
        cls.other = Branch.objects.create(softech_branch_id='953', name='Other')
        cls.item = make_item(softech_id='PA6')
        _, cls.pharm, cls.pharm_client = make_pharmacist('pa6_pharm', branch=cls.branch)
        _, cls.admin, cls.admin_client = make_admin('pa6_admin')
        cls.owner = _staff('pa6_owner', '01000000601')
        WorkOwner.objects.create(kind='reservation_sourcing', staff=cls.owner)
        WorkOwner.objects.create(kind='hq_transfer_dispatch', staff=cls.owner)
        cls.assignee = _staff('pa6_assignee', '01000000602', branch=cls.branch)

    def _mode(self, event, mode):
        PhoneAlertPolicy.objects.update_or_create(event=event, defaults={'mode': mode})

    def _alerts(self, event=None):
        qs = PhoneAlert.objects.all()
        return qs.filter(event=event) if event else qs

    def _fired(self, fn):
        """Run ``fn`` with hooks.fire recorded (and neutralised); return the event keys fired."""
        from apps.notifications.phone_alerts import hooks
        calls, orig = [], hooks.fire
        hooks.fire = lambda *a, **k: calls.append(a[0])
        try:
            fn()
        finally:
            hooks.fire = orig
        return calls

    def _reservation(self, **extra):
        body = {'item': self.item.id, 'branch': self.branch.id, 'quantity_requested': 1,
                'contact_phone': '01099999999', 'contact_name': 'ع'}
        body.update(extra)
        return self.pharm_client.post('/api/reservations/', body, format='json')

    def _transfer(self, supplying, **extra):
        from apps.transfers.models import TransferRequest, TransferRequestItem
        r = self.pharm_client.post('/api/transfers/', {
            'requesting_branch': self.branch.id, 'supplying_branch': supplying.id, **extra,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        tr = TransferRequest.objects.get(pk=r.data['id'])
        TransferRequestItem.objects.create(request=tr, item=self.item, quantity=2)
        return tr

    # reservations
    def test_reservation_pending_alerts_sourcing_owner(self):
        r = self._reservation(phone_alert=True)
        self.assertEqual(r.status_code, 201, r.data)
        alerts = self._alerts('reservation_sourcing')
        self.assertEqual([a.recipient_staff_id for a in alerts], [self.owner.pk])
        self.assertTrue(r.data['phone_alert'])

    def test_reservation_without_toggle_sends_nothing(self):
        self.assertEqual(self._reservation().status_code, 201)
        self.assertEqual(self._alerts().count(), 0)

    def test_urgent_reservation_status_change_fires_once(self):
        rid = self._reservation(priority='urgent', phone_alert=True).data['id']
        self.assertEqual(self._fired(lambda: self.pharm_client.post(
            f'/api/reservations/{rid}/change-status/', {'status': 'available'}, format='json')),
            ['reservation_status_urgent'])

    def test_creation_is_not_a_status_alert_and_normal_priority_is_silent(self):
        self.assertEqual(self._fired(lambda: self._reservation(priority='urgent')),
                         ['reservation_sourcing'])
        rid = self._reservation().data['id']
        self.assertEqual(self._fired(lambda: self.pharm_client.post(
            f'/api/reservations/{rid}/change-status/', {'status': 'available'}, format='json')), [])

    # transfers
    def test_transfer_from_hq_alerts_dispatcher(self):
        tr = self._transfer(self.hq, phone_alert=True)
        self.assertTrue(tr.phone_alert)
        r = self.pharm_client.post(f'/api/transfers/{tr.pk}/submit/')
        self.assertEqual(r.status_code, 200, r.data)
        alerts = self._alerts('transfer_hq_submitted')
        self.assertEqual([a.recipient_staff_id for a in alerts], [self.owner.pk])
        self.assertEqual(self._alerts('transfer_status').count(), 0)   # submit is not also a status alert

    def test_transfer_from_branch_not_dispatcher(self):
        tr = self._transfer(self.other, phone_alert=True)
        self.assertEqual(self._fired(lambda: self.pharm_client.post(f'/api/transfers/{tr.pk}/submit/')), [])

    def test_transfer_later_status_change_fires_transfer_status(self):
        tr = self._transfer(self.other, phone_alert=True)
        self.pharm_client.post(f'/api/transfers/{tr.pk}/submit/')
        self.assertEqual(self._fired(lambda: self.pharm_client.post(f'/api/transfers/{tr.pk}/cancel/')),
                         ['transfer_status'])

    # tasks
    def test_task_assign_alerts_assignee(self):
        r = self.admin_client.post('/api/tasks/', {
            'title': 'مهمة', 'assigned_to': self.assignee.pk, 'phone_alert': True,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        alerts = self._alerts('task_assigned')
        self.assertEqual([a.recipient_staff_id for a in alerts], [self.assignee.pk])

    def test_task_status_change_fires_task_status(self):
        t = OperationalTask.objects.create(title='x', created_by=self.admin, branch=self.branch,
                                           assigned_to=self.assignee, phone_alert=True)
        self.assertEqual(self._fired(lambda: self.admin_client.post(f'/api/tasks/{t.pk}/complete/')),
                         ['task_status'])

    # toggle rule
    def test_toggle_ignored_when_policy_never(self):
        self._mode('reservation_sourcing', 'never')
        r = self._reservation(phone_alert=True)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(r.data['phone_alert'])
        self.assertEqual(self._alerts().count(), 0)

    def test_toggle_ignored_when_policy_absent(self):
        PhoneAlertPolicy.objects.filter(event='task_assigned').delete()
        r = self.admin_client.post('/api/tasks/', {
            'title': 'م', 'assigned_to': self.assignee.pk, 'phone_alert': True}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertFalse(OperationalTask.objects.get(title='م').phone_alert)
        self.assertEqual(self._alerts().count(), 0)

    def test_always_sends_without_toggle(self):
        self._mode('reservation_sourcing', 'always')
        r = self._reservation()
        self.assertEqual(r.status_code, 201, r.data)
        self.assertTrue(r.data['phone_alert'])
        self.assertEqual(self._alerts('reservation_sourcing').count(), 1)

    def test_transfer_toggle_follows_supplier_event(self):
        self._mode('transfer_hq_submitted', 'never')
        self._mode('transfer_status', 'optional')
        self.assertFalse(self._transfer(self.hq, phone_alert=True).phone_alert)
        self.assertTrue(self._transfer(self.other, phone_alert=True).phone_alert)

    # read-only status
    def test_detail_exposes_phone_alert_status(self):
        rid = self._reservation(phone_alert=True).data['id']
        d = self.pharm_client.get(f'/api/reservations/{rid}/').data
        self.assertEqual(d['phone_alert_status'], 'queued')
        self.assertEqual(d['phone_alert_remark'], '')
        a = self._alerts('reservation_sourcing').get()
        PhoneAlert.objects.create(event='reservation_sourcing', source_ct=a.source_ct,
                                  source_id=a.source_id, phone='201000000699')   # newer, still queued
        PhoneAlert.objects.filter(pk=a.pk).update(status='acknowledged', remark='جاري')
        d = self.pharm_client.get(f'/api/reservations/{rid}/').data
        self.assertEqual(d['phone_alert_status'], 'acknowledged')   # acknowledged beats the newer one
        self.assertEqual(d['phone_alert_remark'], 'جاري')

    def test_list_status_does_not_query_per_row(self):
        for _ in range(3):
            self._reservation(phone_alert=True)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            r = self.pharm_client.get('/api/reservations/')
        self.assertEqual(r.status_code, 200)
        rows = r.data['results'] if isinstance(r.data, dict) and 'results' in r.data else r.data
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(x['phone_alert_status'] == 'queued' for x in rows))
        self.assertEqual(sum('notifications_phonealert' in q['sql'] for q in ctx.captured_queries), 1)
