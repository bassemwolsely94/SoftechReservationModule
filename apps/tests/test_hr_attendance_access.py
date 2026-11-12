"""
apps/tests/test_hr_attendance_access.py

HR Attendance stage 1 (design 2026-11-07): who may open the module, and the append-only punch
ledger. Company-level data: admin, or a named grantee (view / manage), nobody else.
"""
import datetime as _dt

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.hr.attendance.access import Access, can_open, manager_recipients
from apps.hr.models import AttendanceAccess, AttendanceDevice, AttendancePunch
from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess


class Base(TestCase):

    def setUp(self):
        self.b1 = make_branch('فرع أ', 'B01')
        _, self.admin_p, self.admin = make_user('ha_admin', role='admin', branch=self.b1)
        _, self.hr_p, self.hr = make_user('ha_hr', role='pharmacist', branch=self.b1)
        _, self.bm_p, self.bm = make_user('ha_bm', role='branch_manager', branch=self.b1)

    def grant(self, profile, level):
        return AttendanceAccess.objects.create(staff=profile, level=level, granted_by=self.admin_p)


class AccessTests(Base):

    def test_admin_can_do_everything(self):
        a = Access(self.admin_p.user)
        self.assertTrue(a.can_view and a.can_export and a.can_manage and a.can_admin)
        self.assertTrue(can_open(self.admin_p.user))

    def test_view_grant_can_view_and_export_not_manage(self):
        self.grant(self.hr_p, 'view')
        a = Access(self.hr_p.user)
        self.assertTrue(a.can_view and a.can_export)
        self.assertFalse(a.can_manage or a.can_admin)

    def test_manage_grant_can_manage_not_admin(self):
        self.grant(self.hr_p, 'manage')
        a = Access(self.hr_p.user)
        self.assertTrue(a.can_view and a.can_export and a.can_manage)
        self.assertFalse(a.can_admin)

    def test_revoked_grant_has_no_access(self):
        g = self.grant(self.hr_p, 'manage')
        g.revoked_at = timezone.now()
        g.save()
        a = Access(self.hr_p.user)
        self.assertFalse(a.can_view or a.can_export or a.can_manage or a.can_admin)
        self.assertFalse(can_open(self.hr_p.user))

    def test_inactive_staff_with_a_grant_is_refused(self):
        for level in ('view', 'manage'):
            with self.subTest(level=level):
                grant = self.grant(self.hr_p, level)
                self.hr_p.is_active = False
                self.hr_p.save(update_fields=['is_active'])
                a = Access(self.hr_p.user)
                self.assertFalse(a.can_view or a.can_export or a.can_manage or a.can_admin)
                self.assertFalse(can_open(self.hr_p.user))
                self.assertNotIn(self.hr_p, manager_recipients())
                grant.delete()
                self.hr_p.is_active = True
                self.hr_p.save(update_fields=['is_active'])

    def test_inactive_admin_is_refused(self):
        self.admin_p.is_active = False
        self.admin_p.save(update_fields=['is_active'])
        a = Access(self.admin_p.user)
        self.assertFalse(a.can_view or a.can_manage or a.can_admin)
        self.assertNotIn(self.admin_p, manager_recipients())

    def test_branch_manager_gets_403_on_me(self):
        self.assertEqual(self.bm.get('/api/hr-attendance/me/').status_code, 403)

    def test_grantee_and_admin_open_me(self):
        self.grant(self.hr_p, 'view')
        r = self.hr.get('/api/hr-attendance/me/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['can_view'])
        self.assertEqual(self.admin.get('/api/hr-attendance/me/').status_code, 200)
        self.assertTrue(self.hr.get('/api/auth/me/').json()['can_hr_attendance'])
        self.assertFalse(self.bm.get('/api/auth/me/').json()['can_hr_attendance'])

    def test_hr_self_service_module_does_not_open_attendance(self):
        RoleModuleAccess.objects.update_or_create(
            role='pharmacist', module='hr', action='view', defaults={'is_allowed': True})
        self.assertEqual(self.hr.get('/api/hr-attendance/me/').status_code, 403)

    def test_manager_recipients_are_admins_and_active_manage_grants(self):
        g = self.grant(self.hr_p, 'manage')
        self.grant(self.bm_p, 'view')
        self.assertEqual({p.pk for p in manager_recipients()}, {self.admin_p.pk, self.hr_p.pk})
        g.revoked_at = timezone.now()
        g.save()
        self.assertEqual({p.pk for p in manager_recipients()}, {self.admin_p.pk})


class PunchLedgerTests(TestCase):

    def setUp(self):
        self.dev = AttendanceDevice.objects.create(serial='SN1', name='جهاز ١')
        self.punch = AttendancePunch.objects.create(
            device=self.dev, user_code='7', raw_stamp=1_000_000, state=0, verify_mode=1,
            punch_date=_dt.date(2026, 11, 1), punch_time=_dt.time(9, 0))

    def test_punch_save_existing_raises(self):
        self.punch.state = 1
        with self.assertRaises(PermissionError):
            self.punch.save()

    def test_punch_delete_raises(self):
        with self.assertRaises(PermissionError):
            self.punch.delete()

    def test_punch_unique_on_device_user_stamp_state(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            AttendancePunch.objects.create(device=self.dev, user_code='7', raw_stamp=1_000_000, state=0)
        AttendancePunch.objects.create(device=self.dev, user_code='7', raw_stamp=1_000_000, state=1)
