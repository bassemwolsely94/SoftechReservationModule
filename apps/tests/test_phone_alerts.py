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
        from apps.notifications.phone_alerts.recipients import _source_branch
        self.assertEqual(_source_branch(EVENTS['task_assigned'], task), self.b1)
        task.branch = self.b2
        self.assertEqual(_source_branch(EVENTS['task_assigned'], task), self.b2)

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
