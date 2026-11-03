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
