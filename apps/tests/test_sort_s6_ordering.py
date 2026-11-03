"""
apps/tests/test_sort_s6_ordering.py

Sortable-grid sweep (batch S6): the audit-log grid and the staff-user grids order on the server (both lists are
paged). Every whitelisted field is requested asc + desc (rule 9: HTTP 200), the order has a unique tiebreak,
and the slim staff picker can never be ordered by a column it does not show.
"""
from django.test import TestCase

from apps.audit.models import AuditLog
from .factories import make_admin, make_pharmacist, make_user


class AuditLogOrderingTests(TestCase):
    def setUp(self):
        _, self.profile, self.client = make_admin('sort_s6_audit')

    def test_every_whitelisted_field_is_200(self):
        for f in ('created_at', 'action', 'user_name', 'model_name'):
            for o in (f, '-' + f):
                r = self.client.get('/api/audit/logs/', {'ordering': o})
                self.assertEqual(r.status_code, 200, o)

    def test_orders_by_model_name_with_stable_ties(self):
        for m in ('Zeta', 'Alpha', 'Alpha', 'Mid'):
            AuditLog.objects.create(action='user_login', model_name=m, object_id='1')
        r = self.client.get('/api/audit/logs/', {'ordering': 'model_name', 'page_size': 100})
        names = [x['model_name'] for x in r.data['results']]
        self.assertEqual(names, sorted(names))
        ids = [x['id'] for x in r.data['results'] if x['model_name'] == 'Alpha']
        self.assertEqual(ids, sorted(ids))        # pk tiebreak keeps ties in a fixed order


class StaffOrderingTests(TestCase):
    def setUp(self):
        _, self.admin_profile, self.client = make_admin('sort_s6_admin')
        make_user('sort_s6_zed', role='pharmacist')
        make_user('sort_s6_amy', role='salesperson')

    def test_every_whitelisted_field_is_200(self):
        for f in ('user__username', 'user__first_name', 'user__last_name', 'role', 'branch__name',
                  'is_active', 'softech_username'):
            for o in (f, '-' + f):
                r = self.client.get('/api/users/staff/', {'ordering': o})
                self.assertEqual(r.status_code, 200, o)

    def test_orders_by_username_both_ways(self):
        asc = [x['username'] for x in self.client.get('/api/users/staff/', {'ordering': 'user__username'}).data['results']]
        desc = [x['username'] for x in self.client.get('/api/users/staff/', {'ordering': '-user__username'}).data['results']]
        self.assertEqual(asc, sorted(asc))
        self.assertEqual(desc, asc[::-1])

    def test_picker_cannot_order_by_softech_username(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.create(role='admin', module='users', action='view')   # module counts as seeded
        user, profile, client = make_pharmacist('sort_s6_picker')
        from apps.users.views import StaffProfileViewSet
        v = StaffProfileViewSet()

        class _Req:
            pass
        v.request = _Req()
        v.request.user = user
        self.assertNotIn('softech_username', v.ordering_fields)
        self.assertIn('role', v.ordering_fields)
        # an admin does get it
        v.request.user = self.admin_profile.user
        self.assertIn('softech_username', v.ordering_fields)
