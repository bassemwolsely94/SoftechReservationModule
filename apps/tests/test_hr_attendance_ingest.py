"""
apps/tests/test_hr_attendance_ingest.py

HR Attendance stage 1, Task 3: the agent ingest API. A lost or altered punch is the worst failure,
so a punch with unusable data is stored flagged, and resending is always safe.
"""
import datetime as _dt
import json
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.hr.attendance import agent_auth, ingest, resolve
from apps.hr.models import (AttendanceAgent, AttendanceDevice, AttendancePunch, CollectionRun,
                            DeviceUser, Employee)

SECRET = 'test-agent-secret'
HEADER = 'HTTP_X_ELR_ATTENDANCE_AGENT'
PREFIX = '/api/hr-attendance/agent/'
LONG_AGO = _dt.date(2026, 10, 1)


def punch(user_code='1001', raw_stamp=1000, date='2026-10-01', time='09:00:00', state=0, verify_mode=1):
    return {'user_code': user_code, 'raw_stamp': raw_stamp, 'date': date, 'time': time,
            'state': state, 'verify_mode': verify_mode}


@override_settings(HR_ATTENDANCE_ENABLED=True)
class IngestBase(TestCase):

    def setUp(self):
        self.agent = AttendanceAgent.objects.create(name='office', token_hash=agent_auth.hash_secret(SECRET))
        self.device = AttendanceDevice.objects.create(serial='SN1', name='جهاز ١', ip='192.168.3.15',
                                                      agent=self.agent)
        self.api = APIClient()
        self.api.credentials(**{HEADER: SECRET})

    def post(self, endpoint, body, client=None):
        # json.dumps, as the agent does: its ASCII escapes can carry text no client encoder would send
        return (client or self.api).post(f'{PREFIX}{endpoint}/', json.dumps(body), content_type='application/json')

    def send(self, rows, serial='SN1'):
        return self.post('punches', {'device_serial': serial, 'punches': rows})

    def roster(self, users, serial='SN1'):
        return self.post('roster', {'device_serial': serial, 'users': users})

    def run_body(self, **over):
        body = {'device_serial': 'SN1', 'started_at': '2026-10-01T10:00:00.123456',
                'finished_at': '2026-10-01T10:01:00.000000', 'records_read': 5,
                'oldest_date': '2026-09-01', 'newest_date': '2026-10-01', 'drift_seconds': -180,
                'device_log_count': 3906, 'status': 'success', 'error': '', 'spool_waiting': 0}
        body.update(over)
        return body

    def employee(self, code='1001', **over):
        return Employee.objects.create(hr_number=code, name_ar=f'موظف {code}', **over)


class AuthTests(IngestBase):

    def test_no_or_wrong_or_revoked_secret_is_401(self):
        self.assertEqual(APIClient().get(f'{PREFIX}config/').status_code, 401)
        wrong = APIClient()
        wrong.credentials(**{HEADER: 'nope'})
        self.assertEqual(wrong.get(f'{PREFIX}config/').status_code, 401)
        self.assertEqual(self.post('punches', {}, client=wrong).status_code, 401)
        self.agent.revoked_at = timezone.now()
        self.agent.save()
        self.assertEqual(self.api.get(f'{PREFIX}config/').status_code, 401)

    def test_non_ascii_secret_is_401_not_a_crash(self):
        odd = APIClient()
        odd.credentials(**{HEADER: 'سر\udcff'})
        self.assertEqual(odd.get(f'{PREFIX}config/').status_code, 401)

    @override_settings(HR_ATTENDANCE_ENABLED=False)
    def test_switch_off_is_503(self):
        for resp in (self.api.get(f'{PREFIX}config/'), self.send([punch()]),
                     self.roster([]), self.post('runs', self.run_body())):
            self.assertEqual(resp.status_code, 503)
            self.assertIsInstance(resp.json(), dict)
        self.assertEqual(APIClient().get(f'{PREFIX}config/').status_code, 503)
        self.assertEqual(AttendancePunch.objects.count(), 0)

    def test_agent_secret_opens_only_agent_endpoints(self):
        self.assertIn(self.api.get('/api/hr-attendance/me/').status_code, (401, 403))

    def test_staff_session_does_not_open_agent_endpoints(self):
        from apps.tests.factories import make_branch, make_user
        _, _, admin = make_user('ha_ingest_admin', role='admin', branch=make_branch('فرع أ', 'B01'))
        self.assertIn(admin.get(f'{PREFIX}config/').status_code, (401, 403))

    def test_device_not_assigned_is_403(self):
        other = AttendanceAgent.objects.create(name='other', token_hash=agent_auth.hash_secret('x'))
        AttendanceDevice.objects.create(serial='SN2', name='٢', agent=other)
        AttendanceDevice.objects.create(serial='SN3', name='٣')
        for serial in ('SN2', 'SN3', 'nope'):
            self.assertEqual(self.send([punch()], serial=serial).status_code, 403)
            self.assertEqual(self.roster([], serial=serial).status_code, 403)
            self.assertEqual(self.post('runs', self.run_body(device_serial=serial)).status_code, 403)
        self.assertEqual(AttendancePunch.objects.count(), 0)

    @override_settings(PUBLIC_API_ENFORCEMENT='enforce')
    def test_agent_route_passes_the_anonymous_gate(self):
        self.assertEqual(self.api.get(f'{PREFIX}config/').status_code, 200)
        self.assertEqual(self.send([punch()]).status_code, 200)


class ConfigTests(IngestBase):

    def test_lists_only_active_devices_of_this_agent(self):
        other = AttendanceAgent.objects.create(name='other', token_hash=agent_auth.hash_secret('x'))
        AttendanceDevice.objects.create(serial='SN2', name='٢', agent=other)
        AttendanceDevice.objects.create(serial='SN3', name='٣', agent=self.agent, is_active=False)
        body = self.api.get(f'{PREFIX}config/').json()
        server_time = body.pop('server_time')
        self.assertEqual(body, {'agent': 'office', 'collect_now': False, 'devices': [
            {'serial': 'SN1', 'name': 'جهاز ١', 'ip': '192.168.3.15', 'port': 4370}]})
        # an aware ISO time within a minute of now, which the agent measures its PC clock against
        moment = _dt.datetime.fromisoformat(server_time)
        self.assertIsNotNone(moment.tzinfo)
        self.assertLess(abs((timezone.now() - moment).total_seconds()), 60)
        # and it is Cairo local time: the zone the agent's naive stamps are read in
        self.assertEqual(moment.utcoffset(), timezone.localtime().utcoffset())

    def test_collect_now_and_last_seen(self):
        self.agent.collect_requested_at = timezone.now()
        self.agent.save()
        self.assertTrue(self.api.get(f'{PREFIX}config/').json()['collect_now'])
        self.agent.refresh_from_db()
        self.assertIsNotNone(self.agent.last_seen_at)


class PunchTests(IngestBase):

    def test_resend_creates_no_duplicates(self):
        rows = [punch(raw_stamp=1), punch(raw_stamp=2)]
        self.assertEqual(self.send(rows).json(), {'accepted': 2, 'duplicate': 0})
        self.assertEqual(self.send(rows).json(), {'accepted': 0, 'duplicate': 2})
        self.assertEqual(AttendancePunch.objects.count(), 2)

    def test_counts_use_the_full_key(self):
        # Two people in the same second: a pre-query on raw_stamp alone would call the second a duplicate.
        self.send([punch(user_code='1', raw_stamp=5)])
        body = self.send([punch(user_code='1', raw_stamp=5), punch(user_code='2', raw_stamp=5),
                          punch(user_code='1', raw_stamp=5, state=1)]).json()
        self.assertEqual(body, {'accepted': 2, 'duplicate': 1})
        self.assertEqual(AttendancePunch.objects.count(), 3)

    def test_counts_add_up_with_duplicates_inside_a_batch(self):
        body = self.send([punch(raw_stamp=7), punch(raw_stamp=7)]).json()
        self.assertEqual(body, {'accepted': 1, 'duplicate': 1})

    def test_more_than_2000_is_413(self):
        too_many = [punch(raw_stamp=i) for i in range(2001)]
        self.assertEqual(self.send(too_many).status_code, 413)
        self.assertEqual(AttendancePunch.objects.count(), 0)
        self.assertEqual(self.send(too_many[:2000]).json(), {'accepted': 2000, 'duplicate': 0})

    def test_bad_year_stored_flagged(self):
        today = timezone.localdate()
        rows = [punch(raw_stamp=1, date='2133-05-06'), punch(raw_stamp=2, date='2014-12-31'),
                punch(raw_stamp=3, date=(today + _dt.timedelta(days=2)).isoformat())]
        self.assertEqual(self.send(rows).json(), {'accepted': 3, 'duplicate': 0})
        stored = AttendancePunch.objects.get(raw_stamp=1)
        self.assertEqual(stored.flag, 'bad_date')
        self.assertEqual(stored.punch_date, _dt.date(2133, 5, 6))
        self.assertEqual(AttendancePunch.objects.filter(flag='bad_date').count(), 3)

    def test_good_dates_at_the_limits_are_not_flagged(self):
        today = timezone.localdate()
        self.send([punch(raw_stamp=1, date='2015-01-01'),
                   punch(raw_stamp=2, date=(today + _dt.timedelta(days=1)).isoformat())])
        self.assertEqual(AttendancePunch.objects.filter(flag='').count(), 2)

    def test_undecodable_date_stored(self):
        self.assertEqual(self.send([punch(raw_stamp=123, date=None, time=None)]).json()['accepted'], 1)
        stored = AttendancePunch.objects.get(raw_stamp=123)
        self.assertEqual(stored.flag, 'bad_date')
        self.assertIsNone(stored.punch_date)
        self.assertIsNone(stored.punch_time)

    def test_unusable_date_or_time_text_is_stored_flagged_not_refused(self):
        rows = [punch(raw_stamp=1, date='2026-02-31'), punch(raw_stamp=2, date='junk'),
                punch(raw_stamp=3, date=20261001), punch(raw_stamp=4, time='25:99:00'),
                punch(raw_stamp=5, time=None)]
        self.assertEqual(self.send(rows).json(), {'accepted': 5, 'duplicate': 0})
        self.assertEqual(AttendancePunch.objects.filter(flag='bad_date').count(), 5)

    def test_stored_values_are_exactly_as_sent(self):
        self.send([punch(user_code='0905', raw_stamp=4_294_967_295, state=255, verify_mode=15)])
        stored = AttendancePunch.objects.get()
        self.assertEqual((stored.user_code, stored.raw_stamp, stored.state, stored.verify_mode, stored.flag),
                         ('0905', 4_294_967_295, 255, 15, ''))
        self.assertEqual((stored.punch_date, stored.punch_time), (LONG_AGO, _dt.time(9, 0)))

    def test_malformed_request_is_refused_whole(self):
        for rows in ('x', None, ['x'], [punch(raw_stamp=1), punch(raw_stamp='2')],
                     [punch(raw_stamp=1), punch(raw_stamp=-1)], [punch(raw_stamp=True)],
                     [punch(raw_stamp=2 ** 63)], [punch(user_code=5)], [punch(user_code='x' * 31)],
                     [punch(user_code='a\x00b')], [punch(state='in')], [punch(state=70000)],
                     [punch(verify_mode=None)], [punch(user_code='a' + chr(0xD800))]):
            resp = self.send(rows)
            self.assertEqual(resp.status_code, 400, rows)
            self.assertIsInstance(resp.json(), dict)
        self.assertEqual(AttendancePunch.objects.count(), 0)

    def test_not_json_is_400_and_answers_an_object(self):
        resp = self.api.post(f'{PREFIX}punches/', '{nope', content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIsInstance(resp.json(), dict)
        resp = self.api.post(f'{PREFIX}punches/', '[1]', content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_resend_with_different_data_never_changes_the_stored_punch(self):
        self.send([punch(date='2026-10-01', time='09:00:00', verify_mode=1)])
        before = AttendancePunch.objects.values().get()
        body = self.send([punch(date='2026-10-02', time='17:00:00', verify_mode=9)]).json()
        self.assertEqual(body, {'accepted': 0, 'duplicate': 1})
        self.assertEqual(AttendancePunch.objects.values().get(), before)

    def test_batch_holds_the_device_lock(self):
        # The counts are true only while no other batch for this machine can insert in between.
        with CaptureQueriesContext(connection) as ctx:
            ingest.store_punches(self.device, [punch()])
        self.assertTrue(any('FOR UPDATE' in q['sql'] and 'hr_attendancedevice' in q['sql']
                            for q in ctx.captured_queries))

    def test_agents_cannot_edit_or_delete(self):
        for endpoint in ('config', 'punches', 'roster', 'runs'):
            url = f'{PREFIX}{endpoint}/'
            for call in (self.api.put, self.api.patch, self.api.delete):
                self.assertEqual(call(url, {}, format='json').status_code, 405, (endpoint, call))

    def test_inactive_device_still_stores_its_punches(self):
        self.device.is_active = False
        self.device.save()
        self.assertEqual(self.send([punch()]).json()['accepted'], 1)

    def test_error_text_uses_public_error(self):
        boom = RuntimeError('password=hunter2 at 10.0.0.1')
        with mock.patch('apps.hr.attendance.agent_views.ingest.store_punches', side_effect=boom):
            with self.assertLogs('elrezeiky.errors', 'ERROR') as logs:
                resp = self.send([punch()])
        self.assertEqual(resp.status_code, 500)
        self.assertIn('مرجع', resp.json()['detail'])
        self.assertNotIn('hunter2', resp.content.decode('utf-8'))
        self.assertNotIn('hunter2', ''.join(logs.output))

    def test_failed_resolution_never_refuses_stored_punches(self):
        with mock.patch('apps.hr.attendance.ingest.resolve.resolve_user_code',
                        side_effect=RuntimeError('boom')):
            with self.assertLogs('elrezeiky.hr_attendance', 'ERROR') as logs:
                body = self.send([punch()]).json()
        self.assertEqual(body, {'accepted': 1, 'duplicate': 0})
        self.assertEqual(AttendancePunch.objects.count(), 1)
        self.assertNotIn('1001', ''.join(logs.output))

    def test_one_failing_code_does_not_stop_the_others(self):
        with mock.patch('apps.hr.attendance.ingest.resolve.resolve_user_code',
                        side_effect=RuntimeError('boom')) as resolving:
            with self.assertLogs('elrezeiky.hr_attendance', 'ERROR'):
                self.send([punch(user_code='1', raw_stamp=1), punch(user_code='2', raw_stamp=2)])
        self.assertEqual(resolving.call_count, 2)


class IsBadDateTests(TestCase):

    def test_limits(self):
        today = _dt.date(2026, 11, 7)
        self.assertTrue(ingest.is_bad_date(None, today))
        self.assertTrue(ingest.is_bad_date(_dt.date(2014, 12, 31), today))
        self.assertFalse(ingest.is_bad_date(_dt.date(2015, 1, 1), today))
        self.assertFalse(ingest.is_bad_date(_dt.date(2026, 11, 8), today))
        self.assertTrue(ingest.is_bad_date(_dt.date(2026, 11, 9), today))


class ResolveTests(IngestBase):

    def stored(self, raw_stamp=1000):
        return AttendancePunch.objects.get(raw_stamp=raw_stamp)

    def test_punch_resolves_to_employee(self):
        emp = self.employee()
        self.send([punch()])
        self.assertEqual(self.stored().employee, emp)

    def test_unknown_id_stays_unresolved_then_resolves_when_added(self):
        self.send([punch()])
        self.assertIsNone(self.stored().employee)
        emp = self.employee()
        resolve.resolve_user_code('1001')
        self.assertEqual(self.stored().employee, emp)

    def test_resend_heals_an_id_added_later(self):
        self.send([punch()])
        emp = self.employee()
        self.assertEqual(self.send([punch()]).json(), {'accepted': 0, 'duplicate': 1})
        self.assertEqual(self.stored().employee, emp)

    def test_punch_outside_employment_dates_unresolved(self):
        emp = self.employee(start_date=_dt.date(2026, 9, 15), end_date=_dt.date(2026, 9, 30))
        self.send([punch(raw_stamp=1, date='2026-09-14'), punch(raw_stamp=2, date='2026-09-15'),
                   punch(raw_stamp=3, date='2026-09-30'), punch(raw_stamp=4, date='2026-10-01')])
        self.assertEqual({p.raw_stamp for p in AttendancePunch.objects.filter(employee=emp)}, {2, 3})

    def test_employment_end_uses_the_work_date(self):
        # 02:00 the morning after end_date still belongs to end_date's work day
        emp = self.employee(end_date=_dt.date(2026, 9, 30))
        self.send([punch(raw_stamp=1, date='2026-10-01', time='02:00:00'),
                   punch(raw_stamp=2, date='2026-10-01', time='09:00:00'),
                   punch(raw_stamp=3, date='2026-10-02', time='02:00:00')])
        self.assertEqual({p.raw_stamp for p in AttendancePunch.objects.filter(employee=emp)}, {1})

    def test_employment_start_uses_the_work_date(self):
        # 02:00 on start_date belongs to the day before, so it stays unresolved
        emp = self.employee(start_date=_dt.date(2026, 9, 15))
        self.send([punch(raw_stamp=1, date='2026-09-15', time='02:00:00'),
                   punch(raw_stamp=2, date='2026-09-15', time='09:00:00'),
                   punch(raw_stamp=3, date='2026-09-16', time='02:00:00')])
        self.assertEqual({p.raw_stamp for p in AttendancePunch.objects.filter(employee=emp)}, {2, 3})

    def test_changed_dates_unlink_on_the_next_resolve(self):
        emp = self.employee()
        self.send([punch()])
        self.assertEqual(self.stored().employee, emp)
        Employee.objects.filter(pk=emp.pk).update(end_date=_dt.date(2026, 9, 1))
        resolve.resolve_user_code('1001')
        self.assertIsNone(self.stored().employee)

    def test_hold_resolution_keeps_punches_unresolved(self):
        emp = self.employee(hold_resolution=True, hold_reason='مراجعة')
        self.send([punch()])
        self.assertIsNone(self.stored().employee)
        Employee.objects.filter(pk=emp.pk).update(hold_resolution=False)
        resolve.resolve_user_code('1001')
        self.assertEqual(self.stored().employee, emp)

    def test_flagged_punch_is_not_resolved(self):
        self.employee()
        self.send([punch(raw_stamp=1, date='2133-05-06'), punch(raw_stamp=2, date=None, time=None)])
        self.assertEqual(AttendancePunch.objects.filter(employee__isnull=False).count(), 0)

    def test_uid_slot_codes_never_resolve(self):
        self.employee('uid-5')
        self.send([punch(user_code='uid-5')])
        stored = AttendancePunch.objects.get(user_code='uid-5')
        self.assertIsNone(stored.employee)
        resolve.resolve_user_code('uid-5')
        self.assertIsNone(AttendancePunch.objects.get(user_code='uid-5').employee)

    def test_uid_slots_on_two_machines_are_not_a_conflict(self):
        other = AttendanceDevice.objects.create(serial='SN2', name='٢')
        DeviceUser.objects.create(device=self.device, user_code='uid-5', device_name='SamerSami')
        DeviceUser.objects.create(device=other, user_code='uid-5', device_name='AhmedAli')
        self.assertEqual(resolve.conflicting_user_codes(), set())

    def test_two_real_names_on_two_machines_is_conflict(self):
        other = AttendanceDevice.objects.create(serial='SN2', name='٢')
        DeviceUser.objects.create(device=self.device, user_code='7', device_name='SamerSami')
        DeviceUser.objects.create(device=other, user_code='7', device_name='AhmedAli')
        self.assertEqual(resolve.conflicting_user_codes(), {'7'})

    def test_same_or_unreal_names_are_not_a_conflict(self):
        devices = [AttendanceDevice.objects.create(serial=f'X{i}', name=str(i)) for i in range(4)]
        for device, name in zip(devices, ('Samer Sami', 'SamerSami', '8', '')):
            DeviceUser.objects.create(device=device, user_code='8', device_name=name)
        self.assertEqual(resolve.conflicting_user_codes(), set())

    def test_is_real_name(self):
        self.assertFalse(resolve.is_real_name('', '7'))
        self.assertFalse(resolve.is_real_name('   ', '7'))
        self.assertFalse(resolve.is_real_name(None, '7'))
        self.assertFalse(resolve.is_real_name(' 7 ', '7'))
        self.assertFalse(resolve.is_real_name('1234', '7'))
        self.assertTrue(resolve.is_real_name('SamerSami', '7'))
        self.assertTrue(resolve.is_real_name('سامر', '7'))

    def test_conflict_blocks_resolution(self):
        self.employee('7')
        other = AttendanceDevice.objects.create(serial='SN2', name='٢')
        DeviceUser.objects.create(device=self.device, user_code='7', device_name='SamerSami')
        DeviceUser.objects.create(device=other, user_code='7', device_name='AhmedAli')
        self.send([punch(user_code='7')])
        self.assertIsNone(AttendancePunch.objects.get(user_code='7').employee)


class RosterTests(IngestBase):

    def test_stores_and_answers_an_object(self):
        resp = self.roster([{'user_code': '7', 'name': 'SamerSami', 'is_admin': True},
                            {'user_code': 'uid-9', 'name': '', 'is_admin': False}])
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), dict)
        row = DeviceUser.objects.get(user_code='7')
        self.assertEqual((row.device, row.device_name, row.is_admin), (self.device, 'SamerSami', True))
        self.assertIsNotNone(row.last_seen_at)
        self.assertEqual(DeviceUser.objects.count(), 2)

    def test_second_roster_updates_and_removes_nothing(self):
        self.roster([{'user_code': '7', 'name': 'A', 'is_admin': False},
                     {'user_code': '8', 'name': 'B', 'is_admin': False}])
        first_seen = DeviceUser.objects.get(user_code='7').first_seen_at
        self.roster([{'user_code': '7', 'name': 'C', 'is_admin': False}])
        row = DeviceUser.objects.get(user_code='7')
        self.assertEqual((row.device_name, row.first_seen_at), ('C', first_seen))
        self.assertTrue(DeviceUser.objects.filter(user_code='8').exists())

    def test_long_name_is_cut_not_refused(self):
        self.assertEqual(self.roster([{'user_code': '7', 'name': 'n' * 300 + '\x00', 'is_admin': False}]).status_code, 200)
        self.assertEqual(DeviceUser.objects.get().device_name, 'n' * 120)

    def test_unstorable_name_text_is_cleaned_not_refused(self):
        self.assertEqual(self.roster([{'user_code': '7', 'name': 'Sa' + chr(0xD800) + 'mer', 'is_admin': False}]).status_code, 200)
        self.assertEqual(DeviceUser.objects.get().device_name, 'Samer')

    def test_oversized_roster_is_413(self):
        users = [{'user_code': str(i), 'name': '', 'is_admin': False}
                 for i in range(ingest.MAX_ROSTER_USERS + 1)]
        self.assertEqual(self.roster(users).status_code, 413)
        self.assertEqual(DeviceUser.objects.count(), 0)

    def test_malformed_roster_is_400(self):
        for users in ('x', None, ['x'], [{'name': 'A'}], [{'user_code': 5, 'name': 'A'}],
                      [{'user_code': 'x' * 31, 'name': 'A'}], [{'user_code': 'a' + chr(0xD800), 'name': 'A'}]):
            self.assertEqual(self.roster(users).status_code, 400, users)
        self.assertEqual(DeviceUser.objects.count(), 0)

    def test_new_conflict_unresolves_and_clearing_it_resolves_again(self):
        emp = self.employee('7')
        other = AttendanceDevice.objects.create(serial='SN2', name='٢', agent=self.agent)
        self.roster([{'user_code': '7', 'name': 'SamerSami', 'is_admin': False}])
        self.send([punch(user_code='7')])
        self.assertEqual(AttendancePunch.objects.get().employee, emp)
        self.roster([{'user_code': '7', 'name': 'AhmedAli', 'is_admin': False}], serial=other.serial)
        self.assertIsNone(AttendancePunch.objects.get().employee)
        self.roster([{'user_code': '7', 'name': 'Samer Sami', 'is_admin': False}], serial=other.serial)
        self.assertEqual(AttendancePunch.objects.get().employee, emp)


class RunTests(IngestBase):

    def test_success_is_stored_and_updates_the_device(self):
        resp = self.post('runs', self.run_body())
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.json(), dict)
        run = CollectionRun.objects.get()
        self.assertEqual((run.agent, run.device, run.status), (self.agent, self.device, 'success'))
        self.assertEqual((run.records_read, run.drift_seconds, run.device_log_count), (5, -180, 3906))
        self.assertEqual((run.oldest_date, run.newest_date), (_dt.date(2026, 9, 1), LONG_AGO))
        self.assertEqual(timezone.localtime(run.started_at).replace(tzinfo=None),
                         _dt.datetime(2026, 10, 1, 10, 0, 0, 123456))
        self.device.refresh_from_db()
        self.assertEqual((self.device.last_status, self.device.last_drift_seconds, self.device.last_log_count),
                         ('success', -180, 3906))
        self.assertEqual(self.device.last_contact_at, run.finished_at)

    def test_counts_are_unknown_not_zero(self):
        self.post('runs', self.run_body())
        run = CollectionRun.objects.get()
        self.assertIsNone(run.new_count)
        self.assertIsNone(run.duplicate_count)

    def test_spool_waiting_is_stored_and_optional(self):
        self.post('runs', self.run_body(spool_waiting=12, unknown_key='ignored'))
        self.assertEqual(CollectionRun.objects.get().spool_waiting, 12)
        body = self.run_body(started_at='2026-10-01T11:00:00')
        del body['spool_waiting']
        self.assertEqual(self.post('runs', body).status_code, 200)
        self.assertIsNone(CollectionRun.objects.order_by('-started_at').first().spool_waiting)

    def test_failed_run_keeps_last_contact(self):
        self.post('runs', self.run_body())
        self.device.refresh_from_db()
        contact = self.device.last_contact_at
        self.post('runs', self.run_body(started_at='2026-10-01T11:00:00', finished_at='2026-10-01T11:00:30',
                                        status='failed', error='TimeoutError', drift_seconds=None,
                                        device_log_count=None, records_read=0))
        self.device.refresh_from_db()
        self.assertEqual((self.device.last_status, self.device.last_contact_at), ('failed', contact))
        self.assertEqual((self.device.last_drift_seconds, self.device.last_log_count), (-180, 3906))

    def test_success_with_unknown_clock_does_not_show_the_old_drift(self):
        self.post('runs', self.run_body())
        self.post('runs', self.run_body(started_at='2026-10-01T11:00:00', finished_at='2026-10-01T11:00:30',
                                        drift_seconds=None, device_log_count=None))
        self.device.refresh_from_db()
        self.assertIsNone(self.device.last_drift_seconds)
        self.assertEqual(self.device.last_log_count, 3906)

    def test_null_fields_are_kept_null_on_a_success_run(self):
        resp = self.post('runs', self.run_body(drift_seconds=None, device_log_count=None, oldest_date=None,
                                               newest_date=None, finished_at=None))
        self.assertEqual(resp.status_code, 200)
        run = CollectionRun.objects.get()
        self.assertIsNone(run.drift_seconds)
        self.assertIsNone(run.device_log_count)
        self.assertIsNone(run.oldest_date)
        self.assertIsNone(run.finished_at)

    def test_runs_arriving_twice_store_one_row(self):
        self.agent.collect_requested_at = timezone.now()
        self.agent.save()
        self.assertEqual(self.post('runs', self.run_body(collect_done=True)).status_code, 200)
        self.agent.refresh_from_db()
        self.assertIsNone(self.agent.collect_requested_at)
        # A newer request must survive the replay of the old run.
        requested = timezone.now()
        AttendanceAgent.objects.filter(pk=self.agent.pk).update(collect_requested_at=requested)
        self.assertEqual(self.post('runs', self.run_body(collect_done=True, status='failed')).status_code, 200)
        self.assertEqual(CollectionRun.objects.count(), 1)
        self.assertEqual(CollectionRun.objects.get().status, 'success')
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.collect_requested_at, requested)

    def test_collect_request_clears_only_on_collect_done(self):
        requested = timezone.now()
        AttendanceAgent.objects.filter(pk=self.agent.pk).update(collect_requested_at=requested)
        self.post('runs', self.run_body())
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.collect_requested_at, requested)
        self.post('runs', self.run_body(started_at='2026-10-01T11:00:00', status='failed', collect_done=True))
        self.agent.refresh_from_db()
        self.assertIsNone(self.agent.collect_requested_at)

    def test_bad_dates_are_left_out_of_the_range(self):
        self.post('runs', self.run_body(oldest_date='1900-01-01', newest_date='2133-05-06'))
        run = CollectionRun.objects.get()
        self.assertIsNone(run.oldest_date)
        self.assertIsNone(run.newest_date)

    def test_error_text_is_redacted_and_cut(self):
        self.post('runs', self.run_body(error='password=hunter2 ' + 'x' * 400))
        run = CollectionRun.objects.get()
        self.assertNotIn('hunter2', run.error)
        self.assertEqual(len(run.error), 255)

    def test_pc_offset_is_stored_and_optional(self):
        self.post('runs', self.run_body(pc_offset_seconds=-3601))
        self.assertEqual(CollectionRun.objects.get().pc_offset_seconds, -3601)
        older = self.run_body(started_at='2026-10-01T11:00:00')
        self.assertEqual(self.post('runs', older).status_code, 200)
        self.assertIsNone(CollectionRun.objects.order_by('-started_at').first().pc_offset_seconds)

    def test_junk_pc_offset_is_stored_as_none_not_refused(self):
        for day, junk in enumerate(('late', 1.5, True, None, [1]), start=2):
            body = self.run_body(started_at=f'2026-10-0{day}T10:00:00', pc_offset_seconds=junk)
            self.assertEqual(self.post('runs', body).status_code, 200, junk)
        self.assertFalse(CollectionRun.objects.filter(pc_offset_seconds__isnull=False).exists())

    def test_pc_offset_decades_off_is_clamped(self):
        self.post('runs', self.run_body(pc_offset_seconds=9_000_000_000))
        self.assertEqual(CollectionRun.objects.get().pc_offset_seconds, 2_147_483_647)

    def test_clock_decades_off_does_not_refuse_the_run(self):
        # A machine stuck in 2133 reports a drift larger than an int column holds.
        resp = self.post('runs', self.run_body(drift_seconds=3_500_000_000))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(CollectionRun.objects.get().drift_seconds, 2_147_483_647)

    def test_pc_clock_set_ahead_once_does_not_freeze_the_device_state(self):
        ahead = (timezone.localtime() + _dt.timedelta(days=1500)).replace(tzinfo=None).isoformat()
        self.post('runs', self.run_body(started_at=ahead, finished_at=ahead))
        self.post('runs', self.run_body(status='failed', drift_seconds=None))
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_status, 'failed')

    def test_older_run_arriving_late_does_not_move_last_contact_back(self):
        self.post('runs', self.run_body(started_at='2026-10-01T12:00:00', finished_at='2026-10-01T12:01:00'))
        self.device.refresh_from_db()
        contact = self.device.last_contact_at
        self.post('runs', self.run_body())
        self.device.refresh_from_db()
        self.assertEqual(self.device.last_contact_at, contact)
        self.assertEqual(CollectionRun.objects.count(), 2)

    def test_last_contact_never_passes_the_server_clock(self):
        future = (timezone.localtime() + _dt.timedelta(days=3)).replace(tzinfo=None).isoformat()
        before = timezone.now()
        self.post('runs', self.run_body(started_at=future, finished_at=future))
        self.device.refresh_from_db()
        self.assertLessEqual(self.device.last_contact_at, timezone.now())
        self.assertGreaterEqual(self.device.last_contact_at, before)

    def test_malformed_run_is_400(self):
        for over in ({'started_at': None}, {'started_at': 'junk'}, {'started_at': '2026-13-45T00:00:00'},
                     {'status': 'maybe'}, {'status': []}, {'device_serial': 5},
                     {'device_serial': 'a\x00b'}):
            self.assertEqual(self.post('runs', self.run_body(**over)).status_code, 400, over)
        self.assertEqual(CollectionRun.objects.count(), 0)

    def test_every_post_answers_json_with_the_exact_routes(self):
        for endpoint, body in (('punches', {'device_serial': 'SN1', 'punches': []}),
                               ('roster', {'device_serial': 'SN1', 'users': []}),
                               ('runs', self.run_body())):
            resp = self.post(endpoint, body)
            self.assertEqual(resp.status_code, 200, endpoint)
            self.assertIsInstance(json.loads(resp.content), dict)


class IssueCommandTests(TestCase):

    def test_prints_secret_once_and_stores_only_the_hash(self):
        out = StringIO()
        call_command('issue_attendance_agent', 'office pc', stdout=out)
        agent = AttendanceAgent.objects.get()
        secret = out.getvalue().strip().splitlines()[-1].strip()
        self.assertEqual(agent.name, 'office pc')
        self.assertNotIn(secret, agent.token_hash)
        self.assertEqual(agent.token_hash, agent_auth.hash_secret(secret))
        self.assertGreaterEqual(len(secret), 40)

    def test_is_audited_without_the_secret(self):
        out = StringIO()
        call_command('issue_attendance_agent', 'office pc', stdout=out)
        secret = out.getvalue().strip().splitlines()[-1].strip()
        entry = AuditLog.objects.filter(action='hr_attendance_agent_issue').get()
        self.assertNotIn(secret, str(entry.__dict__))
