"""
apps/tests/test_hr_attendance_views.py

HR Attendance stage 1, Task 7: the staff API (month, days, issues, employees, link review,
unknown IDs, conflicts, machines, agents, grants). Company-level data: view / manage / admin gates
are checked server-side on every route.
"""
import datetime as _dt
import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.hr.attendance import agent_auth, employee_import, ingest, issues, links, resolve
from apps.hr.attendance.urls import urlpatterns
from apps.hr.models import (AttendanceAccess, AttendanceAgent, AttendanceDevice, AttendancePunch, CollectionRun,
                            ConflictConfirmation, DeviceUser, Employee, EmployeeLinkRejection,
                            GenericLogin, LeaveRequest, LeaveType, UnknownIdDecision)
from apps.tests.factories import make_branch, make_user
from apps.users.models import StaffProfile

URL = '/api/hr-attendance/'
MONEY_WORDS = ('salary', 'amount', 'deduct', 'penalty', 'net')


def keys_of(value):
    """Every dict key anywhere in a JSON value."""
    found = set()
    if isinstance(value, dict):
        for k, v in value.items():
            found.add(k)
            found |= keys_of(v)
    elif isinstance(value, list):
        for v in value:
            found |= keys_of(v)
    return found


@override_settings(HR_ATTENDANCE_ENABLED=True)
class Base(TestCase):

    def setUp(self):
        self.b1 = make_branch('فرع أ', 'B01')
        _, self.admin_p, self.admin = make_user('hv_admin', role='admin', branch=self.b1)
        _, self.mgr_p, self.mgr = make_user('hv_mgr', role='pharmacist', branch=self.b1)
        _, self.view_p, self.viewer = make_user('hv_view', role='pharmacist', branch=self.b1)
        _, self.out_p, self.outsider = make_user('hv_out', role='branch_manager', branch=self.b1)
        AttendanceAccess.objects.create(staff=self.mgr_p, level='manage', granted_by=self.admin_p)
        AttendanceAccess.objects.create(staff=self.view_p, level='view', granted_by=self.admin_p)
        self.device = AttendanceDevice.objects.create(serial='SN1', name='جهاز ١', ip='192.168.3.15')

    def employee(self, code='1001', name='سامر سامي', **kw):
        return Employee.objects.create(hr_number=code, name_ar=name, **kw)

    def staff(self, username, first='', last='', softech_user_id=''):
        _, profile, _ = make_user(username, role='pharmacist', branch=self.b1)
        profile.user.first_name, profile.user.last_name = first, last
        profile.user.save()
        if softech_user_id:
            profile.softech_user_id = softech_user_id
            profile.save()
        return profile

    def punch(self, code='1001', stamp=1, date=_dt.date(2026, 10, 1), time=_dt.time(9, 0),
              device=None, flag='', employee=None):
        return AttendancePunch.objects.create(
            device=device or self.device, user_code=code, raw_stamp=stamp, punch_date=date,
            punch_time=time, flag=flag, employee=employee)

    def post(self, client, path, body=None):
        return client.post(URL + path, json.dumps(body or {}), content_type='application/json')

    def patch(self, client, path, body):
        return client.patch(URL + path, json.dumps(body), content_type='application/json')

    def audited(self, action):
        return AuditLog.objects.filter(action=action)


# ── gates ────────────────────────────────────────────────────────────────────────────────────────

class GateTests(Base):
    """One row per staff route: (methods, level, a concrete path). The test also fails if urls.py
    gains a staff route this table doesn't list."""

    def table(self):
        e, d = self.employee('9001').pk, self.device.pk
        agent = AttendanceAgent.objects.create(name='a', token_hash='h' * 64)
        grant = AttendanceAccess.objects.get(staff=self.view_p)
        return {
            'me/': (['GET'], 'view', 'me/'),
            'month/': (['GET'], 'view', 'month/'),
            'month/export/': (['GET'], 'view', 'month/export/'),
            'employees/': (['GET'], 'view', 'employees/'),
            'employees/<int:pk>/days/': (['GET'], 'view', f'employees/{e}/days/'),
            'issues/': (['GET'], 'view', 'issues/'),
            'unknown-ids/': (['GET'], 'view', 'unknown-ids/'),
            'devices/': (['GET'], 'view', 'devices/'),
            'employees/<int:pk>/': (['PATCH'], 'manage', f'employees/{e}/'),
            'employees/<int:pk>/link/': (['POST'], 'manage', f'employees/{e}/link/'),
            'employees/<int:pk>/reject-link/': (['POST'], 'manage', f'employees/{e}/reject-link/'),
            'employees/<int:pk>/unlink/': (['POST'], 'manage', f'employees/{e}/unlink/'),
            'employees/<int:pk>/hold/': (['POST'], 'manage', f'employees/{e}/hold/'),
            'generic-login/': (['POST'], 'manage', 'generic-login/'),
            'not-generic-login/': (['POST'], 'manage', 'not-generic-login/'),
            'unknown-ids/<str:code>/create-employee/': (['POST'], 'manage', 'unknown-ids/555/create-employee/'),
            'unknown-ids/<str:code>/ignore/': (['POST'], 'manage', 'unknown-ids/555/ignore/'),
            'unknown-ids/<str:code>/unignore/': (['POST'], 'manage', 'unknown-ids/555/unignore/'),
            'conflicts/<str:code>/confirm/': (['POST'], 'manage', 'conflicts/555/confirm/'),
            'collect-now/': (['POST'], 'manage', 'collect-now/'),
            'devices/<int:pk>/': (['PATCH'], 'admin', f'devices/{d}/'),
            'agents/': (['GET'], 'admin', 'agents/'),
            'agents/issue/': (['POST'], 'admin', 'agents/issue/'),
            'agents/<int:pk>/revoke/': (['POST'], 'admin', f'agents/{agent.pk}/revoke/'),
            'grants/': (['GET', 'POST'], 'admin', 'grants/'),
            'grants/<int:pk>/revoke/': (['POST'], 'admin', f'grants/{grant.pk}/revoke/'),
        }

    def test_table_covers_every_staff_route(self):
        routes = {str(p.pattern) for p in urlpatterns if not str(p.pattern).startswith('agent/')}
        self.assertEqual(routes, set(self.table()))

    def call(self, client, method, path):
        return client.generic(method, URL + path, '{}', content_type='application/json')

    def test_every_endpoint_403_for_non_granted(self):
        for route, (methods, level, path) in self.table().items():
            for method in methods:
                r = self.call(self.outsider, method, path)
                self.assertEqual(r.status_code, 403, (route, method, 'outsider'))

    def test_higher_levels_are_refused_to_lower_grants(self):
        for route, (methods, level, path) in self.table().items():
            for method in methods:
                if level != 'view':
                    self.assertEqual(self.call(self.viewer, method, path).status_code, 403,
                                     (route, method, 'view grant'))
                if level == 'admin':
                    self.assertEqual(self.call(self.mgr, method, path).status_code, 403,
                                     (route, method, 'manage grant'))

    def test_view_endpoints_open_for_view_grant(self):
        for route, (methods, level, path) in self.table().items():
            if level == 'view':
                self.assertEqual(self.call(self.viewer, 'GET', path).status_code, 200, route)

    def test_anonymous_is_refused(self):
        from rest_framework.test import APIClient
        for route, (methods, level, path) in self.table().items():
            for method in methods:
                self.assertIn(self.call(APIClient(), method, path).status_code, (401, 403), route)

    def test_view_grant_cannot_confirm_link(self):
        e = self.employee()
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        self.assertEqual(self.post(self.viewer, f'employees/{e.pk}/link/', {'staff': staff.pk}).status_code, 403)
        e.refresh_from_db()
        self.assertIsNone(e.staff)

    def test_manage_grant_cannot_edit_device_or_issue_agent(self):
        r = self.patch(self.mgr, f'devices/{self.device.pk}/', {'name': 'x'})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.post(self.mgr, 'agents/issue/', {'name': 'x'}).status_code, 403)
        self.assertFalse(AttendanceAgent.objects.exists())
        self.device.refresh_from_db()
        self.assertEqual(self.device.name, 'جهاز ١')


# ── linking ──────────────────────────────────────────────────────────────────────────────────────

class LinkTests(Base):

    def test_same_number_alone_is_not_linked(self):
        other = self.staff('hv_other', 'منى', 'علي', softech_user_id='1001')
        preview = employee_import.ImportPreview(rows=[{
            'row': 3, 'hr_number': '1001', 'name_ar': 'سامر سامي', 'department': '', 'section': '',
            'work_location': '', 'job_title': '', 'daily_hours': None}])
        employee_import.apply(preview)
        ingest.store_punches(self.device, [{'user_code': '1001', 'raw_stamp': 5, 'date': '2026-10-01',
                                            'time': '09:00:00', 'state': 0, 'verify_mode': 1}])
        emp = Employee.objects.get(hr_number='1001')
        self.assertIsNone(emp.staff)
        self.assertNotIn(other.pk, [s['staff_id'] for s in links.suggest(emp)])
        row = [r for r in self.viewer.get(URL + 'employees/').json()['rows'] if r['id'] == emp.pk][0]
        self.assertIsNone(row['staff'])
        self.assertEqual(row['suggestions'], [])

    def test_name_match_is_suggested(self):
        emp = self.employee('1001', 'سامر سامي محمد')
        good = self.staff('hv_good', 'سامر', 'سامي')
        self.staff('hv_bad', 'منى', 'علي')
        found = links.suggest(emp)
        self.assertEqual([s['staff_id'] for s in found], [good.pk])
        self.assertTrue(found[0]['reason'])
        self.assertIn('name', found[0])

    def test_confirm_link_writes_hr_code_and_audits(self):
        emp = self.employee()
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        r = self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': staff.pk})
        self.assertEqual(r.status_code, 200, r.content)
        emp.refresh_from_db()
        staff.refresh_from_db()
        self.assertEqual((emp.staff, staff.hr_code), (staff, '1001'))
        log = self.audited('hr_attendance_link_confirm').get()
        self.assertEqual(log.user, self.mgr_p)

    def test_generic_login_cannot_be_linked(self):
        emp = self.employee()
        cashier = self.staff('cashier_1')
        self.assertTrue(links.is_generic_login(cashier))
        self.assertEqual(self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': cashier.pk}).status_code, 400)
        marked = self.staff('hv_shared', 'حساب', 'مشترك')
        self.assertFalse(links.is_generic_login(marked))
        self.assertEqual(self.post(self.mgr, 'generic-login/', {'staff': marked.pk}).status_code, 200)
        self.assertTrue(GenericLogin.objects.filter(staff=marked).exists())
        self.assertTrue(links.is_generic_login(marked))
        self.assertEqual(self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': marked.pk}).status_code, 400)
        self.assertIsNone(Employee.objects.get(pk=emp.pk).staff)
        self.assertTrue(self.audited('hr_attendance_generic_login').exists())

    def test_only_a_shared_login_refusal_carries_the_generic_code(self):
        emp, other = self.employee('1001'), self.employee('1002', 'أحمد علي')
        cashier = self.staff('cashier_1')
        refused = self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': cashier.pk})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()['code'], 'generic_login')
        # a different refusal (this login already belongs to another employee) has no code
        person = self.staff('hv_person', 'سامر', 'سامي')
        self.assertEqual(self.post(self.mgr, f'employees/{other.pk}/link/', {'staff': person.pk}).status_code, 200)
        taken = self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': person.pk})
        self.assertEqual(taken.status_code, 400)
        self.assertNotIn('code', taken.json())

    def test_not_generic_override_allows_linking_and_generic_blocks_again(self):
        emp = self.employee('1001', 'سامر سامي')
        tester = self.staff('hv_t1', 'Tester', 'سامي')       # "test" in the name: regex hit
        self.assertTrue(links.is_generic_login(tester))
        self.assertEqual(self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': tester.pk}).status_code, 400)
        # reason is required
        self.assertEqual(self.post(self.mgr, 'not-generic-login/', {'staff': tester.pk}).status_code, 400)
        self.assertEqual(self.viewer.post(URL + 'not-generic-login/', {'staff': tester.pk}, format='json')
                         .status_code, 403)
        r = self.post(self.mgr, 'not-generic-login/', {'staff': tester.pk, 'reason': 'موظف حقيقي اسمه Tester'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(links.is_generic_login(tester))
        self.assertTrue(self.audited('hr_attendance_not_generic_login').exists())
        self.assertEqual(self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': tester.pk}).status_code, 200)
        self.post(self.mgr, f'employees/{emp.pk}/unlink/')
        # marking generic after the override blocks linking again
        self.assertEqual(self.post(self.mgr, 'generic-login/', {'staff': tester.pk}).status_code, 200)
        self.assertTrue(links.is_generic_login(tester))
        self.assertEqual(self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': tester.pk}).status_code, 400)

    def test_not_generic_clears_a_mistaken_generic_mark(self):
        emp = self.employee('1001', 'سامر سامي')
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        self.post(self.mgr, 'generic-login/', {'staff': staff.pk})
        self.assertTrue(links.is_generic_login(staff))
        self.post(self.mgr, 'not-generic-login/', {'staff': staff.pk, 'reason': 'ضغطة بالخطأ'})
        self.assertFalse(links.is_generic_login(staff))
        self.assertEqual([s['staff_id'] for s in links.suggest(emp)], [staff.pk])

    def test_generic_names_are_matched_in_arabic_and_english(self):
        for username in ('Cash2', 'TEST_user', 'branch5', 'x_كاشير', 'فرع المعادي'):
            self.assertTrue(links.is_generic_login(self.staff(username)), username)

    def test_generic_logins_are_never_suggested(self):
        emp = self.employee('1001', 'سامر سامي')
        cashier = self.staff('cashier_9', 'سامر', 'سامي')
        self.assertEqual(links.suggest(emp), [])
        self.assertTrue(links.is_generic_login(cashier))

    def test_reject_is_not_suggested_again(self):
        emp = self.employee('1001', 'سامر سامي')
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        self.assertEqual(len(links.suggest(emp)), 1)
        r = self.post(self.mgr, f'employees/{emp.pk}/reject-link/', {'staff': staff.pk})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(EmployeeLinkRejection.objects.filter(employee=emp, staff=staff).exists())
        self.assertEqual(links.suggest(emp), [])
        self.assertTrue(self.audited('hr_attendance_link_reject').exists())

    def test_one_staff_one_employee(self):
        a, b = self.employee('1001'), self.employee('1002', 'منى علي')
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        self.assertEqual(self.post(self.mgr, f'employees/{a.pk}/link/', {'staff': staff.pk}).status_code, 200)
        r = self.post(self.mgr, f'employees/{b.pk}/link/', {'staff': staff.pk})
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(Employee.objects.get(pk=b.pk).staff)
        staff.refresh_from_db()
        self.assertEqual(staff.hr_code, '1001')
        # and an employee who already has a login must be unlinked before taking another
        other = self.staff('hv_s2', 'علي', 'حسن')
        self.assertEqual(self.post(self.mgr, f'employees/{a.pk}/link/', {'staff': other.pk}).status_code, 400)

    def test_hr_code_clash_returns_400_and_writes_nothing(self):
        emp = self.employee('1001')
        holder = self.staff('hv_holder', 'علي', 'حسن')
        holder.hr_code = '1001'
        holder.save()
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        r = self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': staff.pk})
        self.assertEqual(r.status_code, 400)
        emp.refresh_from_db()
        staff.refresh_from_db()
        self.assertEqual((emp.staff, staff.hr_code), (None, ''))
        self.assertFalse(self.audited('hr_attendance_link_confirm').exists())

    def test_staff_with_a_different_code_is_refused(self):
        emp = self.employee('1001')
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        staff.hr_code = '7777'
        staff.save()
        self.assertEqual(self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': staff.pk}).status_code, 400)
        staff.refresh_from_db()
        self.assertEqual(staff.hr_code, '7777')

    def test_unlink_clears_hr_code_and_keeps_request_codes(self):
        emp = self.employee()
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': staff.pk})
        ltype = LeaveType.objects.create(code='annual', name='Annual', name_ar='سنوية')
        req = LeaveRequest.objects.create(
            leave_type=ltype, start_date=_dt.date(2026, 10, 1), end_date=_dt.date(2026, 10, 1),
            days_requested=1, status='approved', staff=staff, employee_hr_code='1001')
        r = self.post(self.mgr, f'employees/{emp.pk}/unlink/')
        self.assertEqual(r.status_code, 200)
        emp.refresh_from_db()
        staff.refresh_from_db()
        req.refresh_from_db()
        self.assertEqual((emp.staff, staff.hr_code, req.employee_hr_code), (None, '', '1001'))
        self.assertTrue(self.audited('hr_attendance_link_unlink').exists())

    def test_unlink_without_a_link_is_400(self):
        emp = self.employee()
        self.assertEqual(self.post(self.mgr, f'employees/{emp.pk}/unlink/').status_code, 400)

    def test_cannot_mark_a_linked_login_generic(self):
        emp = self.employee()
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': staff.pk})
        self.assertEqual(self.post(self.mgr, 'generic-login/', {'staff': staff.pk}).status_code, 400)
        self.assertFalse(GenericLogin.objects.exists())

    def test_unknown_staff_id_is_400(self):
        emp = self.employee()
        for body in ({}, {'staff': 'x'}, {'staff': 999999}):
            self.assertEqual(self.post(self.mgr, f'employees/{emp.pk}/link/', body).status_code, 400, body)


# ── month and days ───────────────────────────────────────────────────────────────────────────────

class MonthTests(Base):

    def setUp(self):
        super().setUp()
        self.emp = self.employee('1001', daily_hours=8)
        self.punch(stamp=1, time=_dt.time(9, 0), employee=self.emp)
        self.punch(stamp=2, time=_dt.time(17, 30), employee=self.emp)
        self.punch(stamp=3, date=_dt.date(2026, 10, 2), time=_dt.time(9, 0), employee=self.emp)

    def test_month_rows_and_totals(self):
        r = self.viewer.get(URL + 'month/?month=2026-10')
        self.assertEqual(r.status_code, 200)
        row = [x for x in r.json()['rows'] if x['id'] == self.emp.pk][0]
        self.assertEqual(row['days_with_punches'], 2)
        self.assertEqual(row['days_needing_review'], 1)
        self.assertEqual(float(row['worked_hours']), 8.5)
        self.assertEqual(r.json()['month'], '2026-10')

    def test_month_has_no_money_keys(self):
        for path in ('month/?month=2026-10', f'employees/{self.emp.pk}/days/?month=2026-10',
                     'employees/', 'issues/', 'devices/', 'unknown-ids/'):
            body = self.viewer.get(URL + path).json()
            for key in keys_of(body):
                for word in MONEY_WORDS:
                    self.assertNotIn(word, key.lower(), (path, key))

    def test_bad_month_is_400(self):
        for m in ('2026-13', 'x', '2026-1', '0000-01'):
            self.assertEqual(self.viewer.get(URL + f'month/?month={m}').status_code, 400, m)

    def test_days_endpoint_lists_every_date_with_raw_punches(self):
        r = self.viewer.get(URL + f'employees/{self.emp.pk}/days/?month=2026-10')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body['days']), 31)
        first = body['days'][0]
        self.assertEqual(first['work_date'], '2026-10-01')
        self.assertEqual(len(first['raw']), 2)
        self.assertEqual(first['raw'][0]['machine'], 'جهاز ١')
        self.assertEqual(body['totals']['days_with_punches'], 2)
        self.assertEqual(body['employee']['hr_number'], '1001')

    def test_days_for_unknown_employee_is_404(self):
        self.assertEqual(self.viewer.get(URL + 'employees/999999/days/?month=2026-10').status_code, 404)

    def test_sorting_whitelist(self):
        self.employee('1002', 'أحمد علي')
        ordered = [r['hr_number'] for r in self.viewer.get(URL + 'employees/?ordering=-hr_number').json()['rows']]
        self.assertEqual(ordered, ['1002', '1001'])
        for bad in ('softech_usercode', 'staff__user__password', '-nonsense', 'hold_reason;drop'):
            r = self.viewer.get(URL + f'employees/?ordering={bad}')
            self.assertEqual(r.status_code, 200, bad)
            self.assertEqual([x['hr_number'] for x in r.json()['rows']], ['1001', '1002'], bad)
        r = self.viewer.get(URL + 'month/?month=2026-10&ordering=-days_with_punches')
        self.assertEqual(r.status_code, 200)
        r = self.viewer.get(URL + 'month/?month=2026-10&ordering=password')
        self.assertEqual(r.status_code, 200)

    def test_employees_filters(self):
        self.employee('1002', 'أحمد علي', status='left')
        rows = self.viewer.get(URL + 'employees/?status=left').json()['rows']
        self.assertEqual([r['hr_number'] for r in rows], ['1002'])
        rows = self.viewer.get(URL + 'employees/?q=سامر').json()['rows']
        self.assertEqual([r['hr_number'] for r in rows], ['1001'])


# ── issues and unknown ids ───────────────────────────────────────────────────────────────────────

class IssueTests(Base):

    def test_issues_groups_unknown_ids_per_id(self):
        other = AttendanceDevice.objects.create(serial='SN2', name='جهاز ٢')
        self.punch('555', 1, _dt.date(2026, 10, 1))
        self.punch('555', 2, _dt.date(2026, 10, 5), device=other)
        self.punch('555', 3, _dt.date(2026, 10, 3))
        self.punch('666', 4, _dt.date(2026, 10, 2))
        rows = [r for r in issues.list_issues() if r['kind'] == 'unknown_id']
        by = {r['user_code']: r for r in rows}
        self.assertEqual(set(by), {'555', '666'})
        self.assertEqual(by['555']['count'], 3)
        self.assertEqual(by['555']['last_punch'], '2026-10-05')
        self.assertEqual(by['555']['machines'], sorted(['جهاز ١', 'جهاز ٢']))
        viewed = self.viewer.get(URL + 'unknown-ids/').json()
        self.assertEqual({r['user_code'] for r in viewed['rows']}, {'555', '666'})

    def test_known_ids_are_not_unknown(self):
        self.employee('555')
        self.punch('555', 1)
        self.assertEqual([r for r in issues.list_issues() if r['kind'] == 'unknown_id'], [])

    def test_ignored_id_leaves_issues(self):
        self.punch('555', 1)
        self.assertEqual(self.post(self.mgr, 'unknown-ids/555/ignore/', {}).status_code, 400)
        self.assertEqual(self.post(self.mgr, 'unknown-ids/555/ignore/', {'reason': '  '}).status_code, 400)
        self.assertEqual(len([r for r in issues.list_issues() if r['kind'] == 'unknown_id']), 1)
        r = self.post(self.mgr, 'unknown-ids/555/ignore/', {'reason': 'زائر قديم'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([r for r in issues.list_issues() if r['kind'] == 'unknown_id'], [])
        self.assertEqual(UnknownIdDecision.objects.get(user_code='555').reason, 'زائر قديم')
        self.assertTrue(self.audited('hr_attendance_unknown_ignore').exists())
        ignored = self.viewer.get(URL + 'unknown-ids/').json()['ignored']
        self.assertEqual([i['user_code'] for i in ignored], ['555'])

    def test_ignored_id_is_listed_on_issues_with_its_reason_and_can_be_undone(self):
        self.punch('555', 1)
        self.post(self.mgr, 'unknown-ids/555/ignore/', {'reason': 'زائر قديم'})
        listed = self.viewer.get(URL + 'issues/').json()
        self.assertEqual([(i['user_code'], i['reason']) for i in listed['ignored']], [('555', 'زائر قديم')])
        self.assertEqual(listed['rows'], [])
        # view level can't undo; manage can, once, and it is audited
        self.assertEqual(self.post(self.viewer, 'unknown-ids/555/unignore/').status_code, 403)
        self.assertEqual(self.post(self.mgr, 'unknown-ids/555/unignore/').status_code, 200)
        self.assertFalse(UnknownIdDecision.objects.filter(user_code='555').exists())
        log = self.audited('hr_attendance_unknown_unignore').get()
        self.assertEqual((log.user, log.extra['user_code']), (self.mgr_p, '555'))
        self.assertEqual(self.viewer.get(URL + 'issues/').json()['ignored'], [])
        self.assertEqual([r['user_code'] for r in issues.list_issues() if r['kind'] == 'unknown_id'], ['555'])
        self.assertEqual(self.post(self.mgr, 'unknown-ids/555/unignore/').status_code, 400)

    def test_create_employee_from_unknown_id_resolves_old_punches(self):
        p1 = self.punch('555', 1)
        p2 = self.punch('555', 2, flag='bad_date', date=_dt.date(2133, 1, 1))
        r = self.post(self.mgr, 'unknown-ids/555/create-employee/',
                      {'name_ar': 'ضيف دائم', 'employee_type': 'non_payroll', 'department': 'x'})
        self.assertEqual(r.status_code, 201, r.content)
        emp = Employee.objects.get(hr_number='555')
        self.assertEqual((emp.employee_type, emp.name_ar), ('non_payroll', 'ضيف دائم'))
        p1.refresh_from_db()
        p2.refresh_from_db()
        self.assertEqual(p1.employee, emp)
        self.assertIsNone(p2.employee)   # a flagged punch is never resolved
        self.assertTrue(self.audited('hr_attendance_employee_create').exists())

    def test_create_employee_defaults_to_non_payroll_and_validates(self):
        self.punch('555', 1)
        self.assertEqual(self.post(self.mgr, 'unknown-ids/555/create-employee/', {}).status_code, 400)
        bad = self.post(self.mgr, 'unknown-ids/555/create-employee/', {'name_ar': 'س', 'employee_type': 'boss'})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(self.post(self.mgr, 'unknown-ids/555/create-employee/', {'name_ar': 'س'}).status_code, 201)
        self.assertEqual(Employee.objects.get(hr_number='555').employee_type, 'non_payroll')
        self.assertEqual(self.post(self.mgr, 'unknown-ids/555/create-employee/', {'name_ar': 'س'}).status_code, 400)

    def test_slot_ids_cannot_become_employees(self):
        self.punch('uid-5', 1)
        self.assertEqual(self.post(self.mgr, 'unknown-ids/uid-5/create-employee/', {'name_ar': 'س'}).status_code, 400)
        self.assertFalse(Employee.objects.exists())

    def test_issues_lists_bad_dates_drift_and_conflicts(self):
        self.punch('555', 1, date=_dt.date(2133, 5, 6), flag='bad_date')
        self.punch('555', 2, date=_dt.date(1900, 5, 6), flag='bad_date')
        AttendanceDevice.objects.filter(pk=self.device.pk).update(last_drift_seconds=-900)
        other = AttendanceDevice.objects.create(serial='SN2', name='جهاز ٢', last_drift_seconds=20)
        self.employee('7')
        DeviceUser.objects.create(device=self.device, user_code='7', device_name='SamerSami')
        DeviceUser.objects.create(device=other, user_code='7', device_name='AhmedAli')
        found = self.viewer.get(URL + 'issues/').json()['rows']
        kinds = {r['kind'] for r in found}
        self.assertTrue({'bad_date', 'drift', 'conflict', 'unknown_id'} <= kinds, kinds)
        bad = [r for r in found if r['kind'] == 'bad_date'][0]
        self.assertEqual((bad['machine'], bad['count']), ('جهاز ١', 2))
        drift = [r for r in found if r['kind'] == 'drift']
        self.assertEqual([d['machine'] for d in drift], ['جهاز ١'])
        conflict = [r for r in found if r['kind'] == 'conflict'][0]
        self.assertEqual(conflict['user_code'], '7')
        self.assertEqual(sorted(conflict['names']), ['AhmedAli', 'SamerSami'])

    def test_punches_outside_the_employment_dates_are_an_issue(self):
        emp = self.employee('7', start_date=_dt.date(2026, 10, 10), end_date=_dt.date(2026, 10, 20))
        self.punch('7', 1, _dt.date(2026, 10, 2))      # before the start
        self.punch('7', 2, _dt.date(2026, 10, 5))      # before the start
        self.punch('7', 3, _dt.date(2026, 10, 12))     # inside
        self.punch('7', 4, _dt.date(2026, 10, 28))     # after the end
        self.punch('7', 5, _dt.date(2133, 1, 1), flag='bad_date')   # a bad date is its own issue
        resolve.resolve_user_code('7')
        rows = [r for r in self.viewer.get(URL + 'issues/').json()['rows'] if r['kind'] == 'outside_dates']
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row['employee'], row['user_code'], row['count']), (emp.pk, '7', 3))
        self.assertEqual((row['oldest'], row['newest']), ('2026-10-02', '2026-10-28'))
        self.assertEqual((row['start_date'], row['end_date']), ('2026-10-10', '2026-10-20'))

    def test_outside_dates_clears_when_the_date_is_corrected(self):
        emp = self.employee('7', start_date=_dt.date(2026, 11, 1))     # mistyped start
        self.punch('7', 1, _dt.date(2026, 10, 12))
        resolve.resolve_user_code('7')
        self.assertEqual(len([r for r in issues.list_issues() if r['kind'] == 'outside_dates']), 1)
        self.assertEqual(self.patch(self.mgr, f'employees/{emp.pk}/', {'start_date': '2026-10-01'}).status_code, 200)
        self.assertEqual([r for r in issues.list_issues() if r['kind'] == 'outside_dates'], [])

    def test_held_or_undated_employee_has_no_outside_dates_row(self):
        self.employee('7', hold_resolution=True, hold_reason='x', start_date=_dt.date(2026, 11, 1))
        self.employee('8')
        self.punch('7', 1, _dt.date(2026, 10, 12))
        self.punch('8', 2, _dt.date(2026, 10, 12))
        self.assertEqual([r for r in issues.list_issues() if r['kind'] == 'outside_dates'], [])

    def test_end_date_before_start_date_is_refused(self):
        emp = self.employee('7', start_date=_dt.date(2026, 10, 10))
        refused = self.patch(self.mgr, f'employees/{emp.pk}/', {'end_date': '2026-10-01'})
        self.assertEqual(refused.status_code, 400)
        self.assertIn('end_date', refused.json())
        both = self.patch(self.mgr, f'employees/{emp.pk}/', {'start_date': '2026-11-01', 'end_date': '2026-10-01'})
        self.assertEqual(both.status_code, 400)
        # moving the start past the stored end is refused too
        emp.end_date = _dt.date(2026, 10, 20)
        emp.save()
        self.assertEqual(self.patch(self.mgr, f'employees/{emp.pk}/', {'start_date': '2026-10-25'}).status_code, 400)
        ok = self.patch(self.mgr, f'employees/{emp.pk}/', {'end_date': '2026-10-10'})
        self.assertEqual(ok.status_code, 200)
        emp.refresh_from_db()
        self.assertEqual(emp.end_date, _dt.date(2026, 10, 10))

    def test_creating_from_an_unknown_id_refuses_backwards_dates(self):
        self.punch('555', 1)
        refused = self.post(self.mgr, 'unknown-ids/555/create-employee/',
                            {'name_ar': 'س', 'start_date': '2026-10-10', 'end_date': '2026-10-01'})
        self.assertEqual(refused.status_code, 400)
        self.assertFalse(Employee.objects.filter(hr_number='555').exists())

    def test_held_employee_shows_with_unresolved_punch_count(self):
        emp = self.employee('7', hold_resolution=True, hold_reason='مراجعة')
        self.punch('7', 1)
        held = [r for r in issues.list_issues() if r['kind'] == 'held']
        self.assertEqual([(h['employee'], h['count']) for h in held], [(emp.pk, 1)])


# ── conflicts ────────────────────────────────────────────────────────────────────────────────────

class ConflictTests(Base):

    def setUp(self):
        super().setUp()
        self.emp = self.employee('7', 'سامر سامي')
        self.other = AttendanceDevice.objects.create(serial='SN2', name='جهاز ٢')
        DeviceUser.objects.create(device=self.device, user_code='7', device_name='Samer')
        DeviceUser.objects.create(device=self.other, user_code='7', device_name='SamerSami')
        self.p = self.punch('7', 1)

    def test_samer_vs_samersami_is_still_a_conflict_until_confirmed(self):
        self.assertEqual(resolve.conflicting_user_codes(), {'7'})
        resolve.resolve_user_code('7')
        self.p.refresh_from_db()
        self.assertIsNone(self.p.employee)

    def test_employees_list_shows_machine_names_and_conflict(self):
        row = [r for r in self.viewer.get(URL + 'employees/').json()['rows'] if r['id'] == self.emp.pk][0]
        self.assertEqual(sorted(row['machine_names']), ['Samer', 'SamerSami'])
        self.assertTrue(row['conflict'])
        self.assertFalse(row['conflict_confirmed'])

    def test_confirm_needs_a_reason_and_the_right_employee(self):
        path = 'conflicts/7/confirm/'
        self.assertEqual(self.post(self.mgr, path, {'employee': self.emp.pk}).status_code, 400)
        self.assertEqual(self.post(self.mgr, path, {'employee': self.emp.pk, 'reason': ' '}).status_code, 400)
        self.assertEqual(self.post(self.mgr, path, {'reason': 'ok'}).status_code, 400)
        wrong = self.employee('8', 'غيره')
        self.assertEqual(self.post(self.mgr, path, {'employee': wrong.pk, 'reason': 'ok'}).status_code, 400)
        self.assertFalse(ConflictConfirmation.objects.exists())

    def test_confirm_resolves_despite_the_conflict_and_audits(self):
        r = self.post(self.mgr, 'conflicts/7/confirm/', {'employee': self.emp.pk, 'reason': 'نفس الشخص'})
        self.assertEqual(r.status_code, 200, r.content)
        self.p.refresh_from_db()
        self.assertEqual(self.p.employee, self.emp)
        self.assertEqual(ConflictConfirmation.objects.get().reason, 'نفس الشخص')
        self.assertEqual(self.audited('hr_attendance_conflict_confirm').get().user, self.mgr_p)
        rows = self.viewer.get(URL + 'issues/').json()['rows']
        self.assertEqual([r for r in rows if r['kind'] == 'conflict'], [])
        row = [r for r in self.viewer.get(URL + 'employees/').json()['rows'] if r['id'] == self.emp.pk][0]
        self.assertTrue(row['conflict'] and row['conflict_confirmed'])
        # a later punch resolves too
        later = self.punch('7', 2)
        resolve.resolve_user_code('7')
        later.refresh_from_db()
        self.assertEqual(later.employee, self.emp)

    def test_a_third_name_after_confirm_reopens_the_conflict(self):
        self.post(self.mgr, 'conflicts/7/confirm/', {'employee': self.emp.pk, 'reason': 'نفس الشخص'})
        self.assertEqual(ConflictConfirmation.objects.get().names, ['samer', 'samersami'])
        DeviceUser.objects.create(device=AttendanceDevice.objects.create(serial='SN3', name='جهاز ٣'),
                                  user_code='7', device_name='MohamedAli')
        late = self.punch('7', 2)
        resolve.resolve_user_code('7')
        late.refresh_from_db()
        self.p.refresh_from_db()
        self.assertIsNone(late.employee)
        self.assertIsNone(self.p.employee)
        rows = self.viewer.get(URL + 'issues/').json()['rows']
        self.assertEqual([r['user_code'] for r in rows if r['kind'] == 'conflict'], ['7'])
        row = [r for r in self.viewer.get(URL + 'employees/').json()['rows'] if r['id'] == self.emp.pk][0]
        self.assertFalse(row['conflict_confirmed'])
        # confirming again covers the new name
        self.post(self.mgr, 'conflicts/7/confirm/', {'employee': self.emp.pk, 'reason': 'ثلاثة أسماء لشخص واحد'})
        late.refresh_from_db()
        self.assertEqual(late.employee, self.emp)

    def test_confirming_a_non_conflict_is_400(self):
        emp = self.employee('9')
        r = self.post(self.mgr, 'conflicts/9/confirm/', {'employee': emp.pk, 'reason': 'x'})
        self.assertEqual(r.status_code, 400)

    def test_confirmation_follows_the_employee_not_a_changed_number(self):
        self.post(self.mgr, 'conflicts/7/confirm/', {'employee': self.emp.pk, 'reason': 'نفس الشخص'})
        self.patch(self.mgr, f'employees/{self.emp.pk}/', {'hr_number': '77'})
        self.p.refresh_from_db()
        self.assertIsNone(self.p.employee)   # code 7 no longer belongs to this employee


# ── editing ──────────────────────────────────────────────────────────────────────────────────────

class EditTests(Base):

    def setUp(self):
        super().setUp()
        self.emp = self.employee('1001', 'سامر سامي')
        self.p = self.punch('1001', 1, _dt.date(2026, 10, 1), employee=self.emp)

    def test_edit_fields_and_audit_with_before_after(self):
        r = self.patch(self.mgr, f'employees/{self.emp.pk}/',
                       {'department': 'المبيعات', 'job_title': 'صيدلي', 'daily_hours': '8.5',
                        'status': 'left', 'employee_type': 'non_payroll'})
        self.assertEqual(r.status_code, 200, r.content)
        self.emp.refresh_from_db()
        self.assertEqual((self.emp.department, self.emp.status, self.emp.employee_type),
                         ('المبيعات', 'left', 'non_payroll'))
        log = self.audited('hr_attendance_employee_edit').get()
        self.assertEqual(log.changes['department'], ['', 'المبيعات'])
        self.assertTrue(self.audited('hr_attendance_employee_status').exists())

    def test_pbx_extensions_saved_cleaned_and_validated(self):
        url = f'employees/{self.emp.pk}/'
        r = self.patch(self.mgr, url, {'pbx_extensions': [' 201', '201', '', '33']})
        self.assertEqual(r.status_code, 200, r.content)
        self.emp.refresh_from_db()
        self.assertEqual(self.emp.pbx_extensions, ['201', '33'])
        self.assertEqual(r.json()['pbx_extensions'], ['201', '33'])
        self.assertEqual(self.patch(self.mgr, url, {'pbx_extensions': ['12a']}).status_code, 400)

    def test_hand_edit_of_job_title_records_manual_assignment(self):
        from datetime import timedelta
        from django.utils import timezone
        from apps.hr import assignments as asg
        from apps.hr.models import EmployeeAssignment
        EmployeeAssignment.objects.create(employee=self.emp, job_title='', valid_from=asg.SEED_EPOCH,
                                          source='seed')
        r = self.patch(self.mgr, f'employees/{self.emp.pk}/', {'job_title': 'صيدلي'})
        self.assertEqual(r.status_code, 200, r.content)
        today = timezone.localdate()
        old, new = EmployeeAssignment.objects.filter(employee=self.emp).order_by('valid_from')
        self.assertEqual(old.valid_to, today - timedelta(days=1))
        self.assertEqual((new.job_title, new.source, new.valid_from, new.valid_to),
                         ('صيدلي', 'manual', today, None))

    def test_unknown_and_protected_fields_are_ignored(self):
        self.patch(self.mgr, f'employees/{self.emp.pk}/', {'staff': 5, 'softech_usercode': 'x', 'id': 99})
        self.emp.refresh_from_db()
        self.assertIsNone(self.emp.staff)
        self.assertEqual(self.emp.softech_usercode, '')

    def test_bad_values_are_400(self):
        for body in ({'status': 'gone'}, {'daily_hours': 'abc'}, {'start_date': 'x'},
                     {'name_ar': ''}, {'day_boundary': '25:00'}):
            self.assertEqual(self.patch(self.mgr, f'employees/{self.emp.pk}/', body).status_code, 400, body)

    def test_end_date_change_re_resolves(self):
        r = self.patch(self.mgr, f'employees/{self.emp.pk}/', {'end_date': '2026-09-01'})
        self.assertEqual(r.status_code, 200)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.employee)
        self.patch(self.mgr, f'employees/{self.emp.pk}/', {'end_date': None})
        self.p.refresh_from_db()
        self.assertEqual(self.p.employee, self.emp)

    def test_hold_re_resolves_both_ways(self):
        self.assertEqual(self.post(self.mgr, f'employees/{self.emp.pk}/hold/', {'hold': True}).status_code, 400)
        r = self.post(self.mgr, f'employees/{self.emp.pk}/hold/', {'hold': True, 'reason': 'مراجعة'})
        self.assertEqual(r.status_code, 200)
        self.p.refresh_from_db()
        self.assertIsNone(self.p.employee)
        self.assertTrue(self.audited('hr_attendance_employee_hold').exists())
        self.post(self.mgr, f'employees/{self.emp.pk}/hold/', {'hold': False})
        self.p.refresh_from_db()
        self.assertEqual(self.p.employee, self.emp)
        self.emp.refresh_from_db()
        self.assertEqual((self.emp.hold_resolution, self.emp.hold_reason), (False, ''))

    def test_hr_number_change_re_resolves_old_and_new_and_moves_hr_code(self):
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        self.post(self.mgr, f'employees/{self.emp.pk}/link/', {'staff': staff.pk})
        later = self.punch('2002', 2, _dt.date(2026, 10, 2))
        r = self.patch(self.mgr, f'employees/{self.emp.pk}/', {'hr_number': '2002'})
        self.assertEqual(r.status_code, 200, r.content)
        self.p.refresh_from_db()
        later.refresh_from_db()
        staff.refresh_from_db()
        self.assertIsNone(self.p.employee)
        self.assertEqual(later.employee, self.emp)
        self.assertEqual(staff.hr_code, '2002')

    def test_hr_number_change_clashing_with_a_login_code_is_400_and_writes_nothing(self):
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        self.post(self.mgr, f'employees/{self.emp.pk}/link/', {'staff': staff.pk})
        holder = self.staff('hv_holder', 'علي', 'حسن')
        holder.hr_code = '2002'
        holder.save()
        r = self.patch(self.mgr, f'employees/{self.emp.pk}/', {'hr_number': '2002', 'department': 'x'})
        self.assertEqual(r.status_code, 400)
        self.emp.refresh_from_db()
        staff.refresh_from_db()
        self.assertEqual((self.emp.hr_number, self.emp.department, staff.hr_code), ('1001', '', '1001'))

    def test_duplicate_hr_number_is_400(self):
        self.employee('3003')
        self.assertEqual(self.patch(self.mgr, f'employees/{self.emp.pk}/', {'hr_number': '3003'}).status_code, 400)

    def test_work_date_boundary_change_re_resolves(self):
        early = self.punch('1001', 9, _dt.date(2026, 10, 1), _dt.time(3, 0))
        self.patch(self.mgr, f'employees/{self.emp.pk}/', {'start_date': '2026-10-01'})
        early.refresh_from_db()
        self.assertIsNone(early.employee)       # 03:00 on the start date is the day before
        self.patch(self.mgr, f'employees/{self.emp.pk}/', {'day_boundary': '02:00:00'})
        early.refresh_from_db()
        self.assertEqual(early.employee, self.emp)


# ── machines, agents, grants, collect now ────────────────────────────────────────────────────────

class AdminTests(Base):

    def test_devices_list_hides_ip_from_non_admin(self):
        body = self.viewer.get(URL + 'devices/').json()
        self.assertNotIn('ip', body['rows'][0])
        self.assertEqual(body['rows'][0]['serial'], 'SN1')
        self.assertIn('ip', self.admin.get(URL + 'devices/').json()['rows'][0])

    def test_run_error_text_is_for_admins_only(self):
        CollectionRun.objects.create(device=self.device, started_at=timezone.now(), status='failed',
                                     error='timeout reaching 192.168.3.15')
        seen = self.viewer.get(URL + 'devices/').json()['rows'][0]['last_run']
        self.assertEqual(seen['status'], 'failed')
        self.assertNotIn('error', seen)
        self.assertNotIn('192.168', json.dumps(self.mgr.get(URL + 'devices/').json()))
        self.assertIn('192.168.3.15', self.admin.get(URL + 'devices/').json()['rows'][0]['last_run']['error'])

    def test_device_edit_by_admin_is_audited_and_serial_is_fixed(self):
        agent = AttendanceAgent.objects.create(name='a', token_hash='h' * 64)
        r = self.patch(self.admin, f'devices/{self.device.pk}/',
                       {'name': 'HQ', 'location_label': 'الإدارة', 'agent': agent.pk, 'branch': self.b1.pk,
                        'is_active': False, 'serial': 'HACK'})
        self.assertEqual(r.status_code, 200, r.content)
        self.device.refresh_from_db()
        self.assertEqual((self.device.name, self.device.location_label, self.device.agent,
                          self.device.branch, self.device.is_active, self.device.serial),
                         ('HQ', 'الإدارة', agent, self.b1, False, 'SN1'))
        self.assertTrue(self.audited('hr_attendance_device_edit').exists())

    def test_device_edit_rejects_bad_values(self):
        for body in ({'port': 'x'}, {'agent': 9999}, {'branch': 9999}, {'name': ''}):
            self.assertEqual(self.patch(self.admin, f'devices/{self.device.pk}/', body).status_code, 400, body)

    def test_issue_agent_returns_secret_once_and_audits_without_it(self):
        r = self.post(self.admin, 'agents/issue/', {'name': 'PC المكتب'})
        self.assertEqual(r.status_code, 201, r.content)
        secret = r.json()['secret']
        agent = AttendanceAgent.objects.get(pk=r.json()['id'])
        self.assertEqual(agent.token_hash, agent_auth.hash_secret(secret))
        self.assertEqual(agent.created_by, self.admin_p)
        self.assertIn('no-store', r['Cache-Control'])
        listed = self.admin.get(URL + 'agents/')
        self.assertNotIn(secret, listed.content.decode())
        self.assertNotIn('token_hash', listed.content.decode())
        log = self.audited('hr_attendance_agent_issue').get()
        self.assertNotIn(secret, json.dumps([log.note, log.extra, log.changes, log.new_data, log.old_data],
                                            ensure_ascii=False, default=str))
        self.assertEqual(self.post(self.admin, 'agents/issue/', {'name': ' '}).status_code, 400)

    def test_revoke_agent(self):
        agent = AttendanceAgent.objects.create(name='a', token_hash='h' * 64)
        self.assertEqual(self.post(self.admin, f'agents/{agent.pk}/revoke/').status_code, 200)
        agent.refresh_from_db()
        self.assertIsNotNone(agent.revoked_at)
        self.assertTrue(self.audited('hr_attendance_agent_revoke').exists())
        self.assertEqual(self.post(self.admin, f'agents/{agent.pk}/revoke/').status_code, 400)
        self.assertEqual(self.post(self.admin, 'agents/99999/revoke/').status_code, 404)

    def test_grants_create_list_revoke(self):
        newbie = self.staff('hv_new', 'جديد', 'موظف')
        r = self.post(self.admin, 'grants/', {'staff': newbie.pk, 'level': 'manage'})
        self.assertEqual(r.status_code, 201, r.content)
        gid = r.json()['id']
        self.assertEqual(self.post(self.admin, 'grants/', {'staff': newbie.pk, 'level': 'view'}).status_code, 400)
        self.assertEqual(self.post(self.admin, 'grants/', {'staff': newbie.pk, 'level': 'root'}).status_code, 400)
        rows = self.admin.get(URL + 'grants/').json()['rows']
        self.assertIn(gid, [g['id'] for g in rows])
        self.assertEqual(self.post(self.admin, f'grants/{gid}/revoke/').status_code, 200)
        self.assertIsNotNone(AttendanceAccess.objects.get(pk=gid).revoked_at)
        self.assertEqual(self.post(self.admin, f'grants/{gid}/revoke/').status_code, 400)
        self.assertTrue(self.audited('hr_attendance_grant_create').exists())
        self.assertTrue(self.audited('hr_attendance_grant_revoke').exists())

    def test_collect_now_sets_flag_and_audits(self):
        agent = AttendanceAgent.objects.create(name='a', token_hash='h' * 64)
        self.device.agent = agent
        self.device.save()
        idle = AttendanceAgent.objects.create(name='idle', token_hash='i' * 64)
        r = self.post(self.mgr, 'collect-now/')
        self.assertEqual(r.status_code, 200)
        agent.refresh_from_db()
        idle.refresh_from_db()
        self.assertIsNotNone(agent.collect_requested_at)
        self.assertIsNone(idle.collect_requested_at)
        self.assertEqual(r.json()['agents'], 1)
        self.assertTrue(self.audited('hr_attendance_collect_now').exists())

    def test_collect_now_with_no_agent_is_400(self):
        self.assertEqual(self.post(self.mgr, 'collect-now/').status_code, 400)

    def test_all_changes_audited(self):
        emp = self.employee()
        staff = self.staff('hv_s1', 'سامر', 'سامي')
        self.post(self.mgr, f'employees/{emp.pk}/link/', {'staff': staff.pk})
        other = self.employee('1002', 'منى علي')
        stranger = self.staff('hv_s2', 'منى', 'علي')
        self.post(self.mgr, f'employees/{other.pk}/reject-link/', {'staff': stranger.pk})
        self.patch(self.mgr, f'employees/{emp.pk}/', {'department': 'x', 'status': 'left'})
        self.patch(self.admin, f'devices/{self.device.pk}/', {'name': 'y'})
        agent = AttendanceAgent.objects.get(pk=self.post(self.admin, 'agents/issue/', {'name': 'z'}).json()['id'])
        self.post(self.admin, f'agents/{agent.pk}/revoke/')
        actions = set(AuditLog.objects.filter(action__startswith='hr_attendance_').values_list('action', flat=True))
        self.assertEqual(actions, {
            'hr_attendance_link_confirm', 'hr_attendance_link_reject', 'hr_attendance_employee_edit',
            'hr_attendance_employee_status', 'hr_attendance_device_edit', 'hr_attendance_agent_issue',
            'hr_attendance_agent_revoke'})


# ── seed ─────────────────────────────────────────────────────────────────────────────────────────

class SeedTests(TestCase):

    def run_seed(self):
        call_command('seed_attendance_devices', stdout=StringIO())

    def test_seed_devices_is_idempotent(self):
        self.run_seed()
        self.run_seed()
        self.assertEqual(AttendanceDevice.objects.count(), 8)
        by = {d.name: d for d in AttendanceDevice.objects.all()}
        self.assertEqual(by['Alia'].serial, 'A2ML173860738')
        self.assertEqual(by['Alia'].ip, '192.168.30.15')
        self.assertEqual(by['8'].serial, 'A8ME185060308')
        self.assertEqual((by['Alia'].location_label, by['8'].location_label), ('', ''))
        self.assertTrue(all(d.branch is None and d.port == 4370 for d in by.values()))
        self.assertTrue(all(d.location_label for n, d in by.items() if n not in ('Alia', '8')))
        self.assertEqual(by['Giza'].model_name, 'K14')

    def test_seed_never_overwrites_an_edit(self):
        self.run_seed()
        AttendanceDevice.objects.filter(name='Alia').update(location_label='فرع العليا', ip='10.0.0.9')
        self.run_seed()
        alia = AttendanceDevice.objects.get(name='Alia')
        self.assertEqual((alia.location_label, alia.ip), ('فرع العليا', '10.0.0.9'))
