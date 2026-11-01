"""
apps/tests/test_screen_usage.py

P-57 (docs/product-review/06_SPEC_P-57): screen-usage telemetry from day 1.
  • a visit stores the ROUTE PATTERN only — never ids or query strings
  • the same route within 30 s is not stored twice
  • per-staff report: admin and HR only; a branch manager sees only their branch's totals
  • rows older than 12 months are removed by retention
"""
import datetime

from django.test import TestCase
from django.utils import timezone

from apps.audit.models import ScreenView
from .factories import make_admin, make_branch, make_branch2, make_user


class CaptureTests(TestCase):

    def setUp(self):
        _, self.staff, self.client_ = make_user('sv_pharm', role='pharmacist')

    def test_stores_pattern_not_ids_or_query(self):
        r = self.client_.post('/api/audit/screen-view/', {'route': '/transits/123?x=1', 'tab': 'grid'},
                              format='json')
        self.assertEqual(r.status_code, 204)
        row = ScreenView.objects.get()
        self.assertEqual(row.route, '/transits/:id')
        self.assertEqual(row.tab, 'grid')
        self.assertEqual(row.staff, self.staff)
        self.assertEqual(row.role, 'pharmacist')
        self.assertEqual(row.branch, self.staff.branch)

    def test_long_numbers_and_uuids_become_ids(self):
        self.client_.post('/api/audit/screen-view/',
                          {'route': '/customers/01012345678/orders/3f2a9c1e-1111-4222-8333-123456789abc'},
                          format='json')
        self.assertEqual(ScreenView.objects.get().route, '/customers/:id/orders/:id')

    def test_same_route_within_30s_is_not_repeated(self):
        for _ in range(3):
            self.client_.post('/api/audit/screen-view/', {'route': '/pos'}, format='json')
        self.client_.post('/api/audit/screen-view/', {'route': '/transits'}, format='json')
        self.assertEqual(ScreenView.objects.count(), 2)

    def test_anonymous_rejected(self):
        from rest_framework.test import APIClient
        r = APIClient().post('/api/audit/screen-view/', {'route': '/pos'}, format='json')
        self.assertIn(r.status_code, (401, 403))
        self.assertEqual(ScreenView.objects.count(), 0)


class ReportAccessTests(TestCase):

    def setUp(self):
        self.b1 = make_branch('فرع ١', '140')
        self.b2 = make_branch2('فرع ٢', '150')
        _, self.manager, self.manager_client = make_user('sv_mgr', role='pharmacist', branch=self.b1)
        _, self.other, _ = make_user('sv_other', role='salesperson', branch=self.b2)
        _, self.seller, self.seller_client = make_user('sv_sales', role='salesperson', branch=self.b1)
        ScreenView.objects.create(staff=self.manager, role='pharmacist', branch=self.b1, route='/pos')
        ScreenView.objects.create(staff=self.other, role='salesperson', branch=self.b2, route='/pos')
        ScreenView.objects.create(staff=self.other, role='salesperson', branch=self.b2, route='/transits')

    def test_per_staff_admin_only(self):
        self.assertEqual(self.manager_client.get('/api/audit/usage/?view=staff').status_code, 403)
        _, _, admin = make_admin('sv_admin')
        rows = admin.get('/api/audit/usage/?view=staff').json()['rows']
        self.assertEqual({r['staff_id'] for r in rows}, {self.manager.pk, self.other.pk})

    def test_hr_grant_sees_per_staff(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.update_or_create(role='supervisor', module='hr', action='approve',
                                                  defaults={'is_allowed': True})
        _, _, hr = make_user('sv_hr', role='supervisor', branch=self.b1)
        self.assertEqual(hr.get('/api/audit/usage/?view=staff').status_code, 200)

    def test_branch_manager_sees_only_own_branch(self):
        rows = self.manager_client.get('/api/audit/usage/?view=screens').json()['rows']
        self.assertEqual(rows, [{'route': '/pos', 'visits': 1, 'users': 1}])

    def test_other_roles_refused(self):
        self.assertEqual(self.seller_client.get('/api/audit/usage/?view=screens').status_code, 403)

    def test_zero_use_screens_listed(self):
        _, _, admin = make_admin('sv_admin2')
        d = admin.get('/api/audit/usage/?view=screens&known=/pos,/transits,/finance').json()
        self.assertEqual(d['zero_use'], ['/finance'])


class RetentionTests(TestCase):

    def test_older_than_12_months_removed(self):
        from apps.sync.maintenance import prune_screen_views
        _, staff, _ = make_user('sv_ret')
        old = ScreenView.objects.create(staff=staff, role='pharmacist', route='/pos')
        new = ScreenView.objects.create(staff=staff, role='pharmacist', route='/pos')
        ScreenView.objects.filter(pk=old.pk).update(at=timezone.now() - datetime.timedelta(days=366))
        prune_screen_views()
        self.assertEqual(list(ScreenView.objects.values_list('pk', flat=True)), [new.pk])


class NoticeTests(TestCase):

    def test_notice_posted_once(self):
        from django.core.management import call_command
        from apps.notifications.models import Announcement
        call_command('post_usage_notice')
        call_command('post_usage_notice')
        self.assertEqual(Announcement.objects.filter(title='تسجيل استخدام الشاشات').count(), 1)
