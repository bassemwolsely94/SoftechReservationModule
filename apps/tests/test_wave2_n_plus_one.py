"""
apps/tests/test_wave2_n_plus_one.py — full audit Wave 2, PERF-4.

  • core.branch_scope.branch_ids is memoised per profile (it ran per serialized row) — and the memo
    must never serve a changed branch scope: every change to a profile, its allowed / restricted
    branches, the user or a branch invalidates it, even when made through another instance.
  • /api/reservations/ and /api/customers/ list queries no longer grow with the number of rows.
"""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.customers.models import Customer
from apps.reservations.models import Reservation, ReservationLine
from apps.users.models import StaffProfile
from core import branch_scope

from .factories import make_branch, make_branch2, make_item, make_pharmacist


class BranchScopeMemoTests(TestCase):
    def setUp(self):
        self.b1 = make_branch()
        self.b2 = make_branch2()
        _, self.profile, _ = make_pharmacist('memo_pharma', branch=self.b1)

    def test_repeat_calls_hit_the_database_once(self):
        branch_scope.branch_ids(self.profile)
        with CaptureQueriesContext(connection) as ctx:
            for _ in range(20):
                self.assertEqual(branch_scope.branch_ids(self.profile), {self.b1.pk})
        self.assertEqual(len(ctx.captured_queries), 0)

    def test_returns_a_copy(self):
        branch_scope.branch_ids(self.profile).add(999)
        self.assertEqual(branch_scope.branch_ids(self.profile), {self.b1.pk})

    def test_allowed_branch_added_through_another_instance_is_seen(self):
        self.assertEqual(branch_scope.branch_ids(self.profile), {self.b1.pk})
        StaffProfile.objects.get(pk=self.profile.pk).allowed_branches.add(self.b2)
        self.assertEqual(branch_scope.branch_ids(self.profile), {self.b1.pk, self.b2.pk})

    def test_restricted_branch_wins_at_once(self):
        self.profile.allowed_branches.add(self.b2)
        self.assertEqual(branch_scope.branch_ids(self.profile), {self.b1.pk, self.b2.pk})
        StaffProfile.objects.get(pk=self.profile.pk).restricted_branches.add(self.b2)
        self.assertEqual(branch_scope.branch_ids(self.profile), {self.b1.pk})

    def test_deactivated_profile_sees_nothing_at_once(self):
        branch_scope.branch_ids(self.profile)
        other = StaffProfile.objects.get(pk=self.profile.pk)
        other.is_active = False
        other.save()
        self.profile.refresh_from_db()
        self.assertEqual(branch_scope.branch_ids(self.profile), set())

    def test_role_change_on_the_same_instance_is_seen(self):
        self.assertEqual(branch_scope.branch_ids(self.profile), {self.b1.pk})
        self.profile.role = 'call_center'          # all-branch role, not yet saved
        self.assertIsNone(branch_scope.branch_ids(self.profile))


class ListQueriesDoNotGrowTests(TestCase):
    """The number of queries for a list page must not depend on how many rows it shows."""

    def setUp(self):
        self.branch = make_branch()
        self.item = make_item()
        _, self.profile, self.client_ = make_pharmacist('n1_pharma', branch=self.branch)

    def _count(self, url):
        with CaptureQueriesContext(connection) as ctx:
            r = self.client_.get(url)
        self.assertEqual(r.status_code, 200, r.content[:300])
        self._last = [q['sql'] for q in ctx.captured_queries]
        return len(self._last)

    def _assert_same(self, url, few_sql):
        many = self._count(url)
        if many != len(few_sql):
            grown = [q for q in self._last if self._last.count(q) > few_sql.count(q)]
            extra = '\n'.join(sorted(set(self._last) - set(few_sql)) or grown)
            self.fail(f'{url}: {len(few_sql)} queries for few rows, {many} for more:\n{extra[:3000]}')

    def _reservations(self, n, start):
        for i in range(start, start + n):
            res = Reservation.objects.create(item=self.item, branch=self.branch, quantity_requested=1,
                                             contact_name=f'عميل {i}', contact_phone=f'010{i:08d}',
                                             created_by=self.profile)
            ReservationLine.objects.create(reservation=res, item=self.item, quantity_requested=2)

    def _customers(self, n, start):
        for i in range(start, start + n):
            Customer.objects.create(name=f'عميل {i}', phone=f'011{i:08d}', is_guest=False,
                                    preferred_branch=self.branch)

    def test_reservation_list(self):
        self._reservations(3, 0)
        self._count('/api/reservations/')            # warm-up: one-time lookups (content types, permissions)
        self._count('/api/reservations/')
        few = self._last
        self._reservations(12, 100)
        self._assert_same('/api/reservations/', few)

    def test_customer_list(self):
        self._customers(3, 0)
        self._count('/api/customers/')            # warm-up: one-time lookups (content types, permissions)
        self._count('/api/customers/')
        few = self._last
        self._customers(12, 100)
        self._assert_same('/api/customers/', few)
