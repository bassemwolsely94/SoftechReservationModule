"""
apps/tests/test_hr_attendance_linkedgates_models.py

HR Attendance, Linked Gates Task 1: the nullable per-employee day cut-off and the append-only
Linked Gates punch mirror.
"""
import datetime as _dt
import importlib

from django.apps import apps as django_apps
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.hr.attendance import days, resolve
from apps.hr.models import (AttendanceDevice, AttendancePunch, Employee, LinkedGatesPunch)

_MIGRATION = importlib.import_module('apps.hr.migrations.0015_attendance_linkedgates')


def _emp(code, **over):
    return Employee.objects.create(hr_number=code, name_ar=f'موظف {code}', **over)


def _lg(check_id=1, version=1, **over):
    fields = dict(lg_check_id=check_id, version=version, enroll_no=7,
                  check_time=timezone.make_aware(_dt.datetime(2026, 10, 1, 9, 0)), in_out_mode=0)
    fields.update(over)
    return LinkedGatesPunch.objects.create(**fields)


class DayBoundaryNullableTests(TestCase):

    def test_day_boundary_nullable_and_migrated(self):
        e = _emp('1', day_boundary=None)
        e.refresh_from_db()
        self.assertIsNone(e.day_boundary)
        self.assertEqual(days.effective_boundary(e), _dt.time(4, 0))

        default_one = _emp('2', day_boundary=_dt.time(4, 0))
        custom = _emp('3', day_boundary=_dt.time(6, 0))
        _MIGRATION.null_default_boundaries(django_apps, None)
        default_one.refresh_from_db()
        custom.refresh_from_db()
        self.assertIsNone(default_one.day_boundary)
        self.assertEqual(custom.day_boundary, _dt.time(6, 0))
        self.assertEqual(days.effective_boundary(custom), _dt.time(6, 0))


class LinkedGatesPunchTests(TestCase):

    def test_lg_punch_append_only(self):
        p = _lg()
        p.check_time = p.check_time + _dt.timedelta(minutes=5)
        with self.assertRaises(PermissionError):
            p.save()
        p.refresh_from_db()
        self.assertEqual(p.check_time.astimezone(timezone.get_current_timezone()).hour, 9)

        p.superseded_at = timezone.now()          # bookkeeping only: allowed
        p.save()
        p.lg_removed = True
        p.save()
        p.refresh_from_db()
        self.assertIsNotNone(p.superseded_at)
        self.assertTrue(p.lg_removed)

        with self.assertRaises(PermissionError):
            p.delete()
        self.assertTrue(LinkedGatesPunch.objects.filter(pk=p.pk).exists())

    def test_lg_punch_unique_version(self):
        _lg(check_id=5, version=1)
        _lg(check_id=5, version=2)                # a new version of the same check is fine
        with self.assertRaises(IntegrityError), transaction.atomic():
            _lg(check_id=5, version=1)


class EligibleNullBoundaryTests(TestCase):

    def test_eligible_with_null_boundary(self):
        device = AttendanceDevice.objects.create(serial='SN1', name='جهاز')
        start = _dt.date(2026, 10, 1)
        e = _emp('9', day_boundary=None, start_date=start)
        mk = lambda stamp, t: AttendancePunch.objects.create(    # noqa: E731 - local test helper
            device=device, user_code='9', raw_stamp=stamp, punch_date=start, punch_time=t)
        before = mk(1, _dt.time(3, 0))     # before 04:00 on start day: belongs to the day before
        after = mk(2, _dt.time(4, 30))
        ids = set(AttendancePunch.objects.filter(resolve.eligible_q(e)).values_list('pk', flat=True))
        self.assertEqual(ids, {after.pk})
        self.assertNotIn(before.pk, ids)
