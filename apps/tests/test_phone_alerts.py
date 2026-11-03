from django.conf import settings
from django.test import TestCase

from apps.notifications.phone_alerts.events import EVENTS
from apps.notifications.phone_alerts.models import PhoneAlertPolicy


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
from datetime import time, timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from apps.access.models import Device, DeviceUser
from apps.branches.models import Branch, BranchSettings
from apps.hr.models import ShiftAssignment, ShiftTemplate
from apps.notifications.phone_alerts.models import WorkOwner
from apps.notifications.phone_alerts.recipients import on_shift_staff, resolve
from apps.users.models import StaffProfile


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

    def _device_user(self, staff, branch, age_h):
        d = Device.objects.create(secret_hash=f'h{staff.pk}', branch=branch, status='approved')
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

    def test_escalation_policy_list_else_escalation_owner(self):
        from apps.notifications.phone_alerts.models import PhoneAlert, PhoneAlertPolicy
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
        self.assertEqual([x.staff for x in resolve(EVENTS['transfer_status'], _Src(self.b1, p))], [p])
