"""
Query budgets for the routes every open screen polls (performance stage 1, design
docs/superpowers/specs/2026-11-19-performance-boost-design.md §4 "polled"): the bell, sync status,
data freshness and the dashboard summary. Each call must run the same number of queries with few
or many rows, and no more than its ceiling in apps/tests/perf/budgets.py.
"""
from django.test import TestCase

from apps.notifications.models import Notification
from apps.reservations.models import Reservation
from apps.sync.models import SyncLog, SyncRun

from ..factories import make_admin, make_branch, make_item, make_salesperson
from .budget import assert_budget


class HarnessSelfTest(TestCase):
    def test_refuses_a_403(self):
        _, _, client = make_salesperson('perf_403')
        with self.assertRaises(AssertionError):
            assert_budget(self, 'sync/freshness', client, '/api/sync/slow-requests/',
                          grow=lambda: None, min_rows=0)

    def test_refuses_rows_that_never_arrive(self):
        _, _, client = make_admin('perf_rows')
        with self.assertRaises(AssertionError):
            assert_budget(self, 'notifications/', client, '/api/notifications/',
                          grow=lambda: None, min_rows=5)


class PolledRouteBudgets(TestCase):
    def setUp(self):
        _, self.profile, self.client = make_admin('perf_admin')
        self.branch = make_branch()
        self.item = make_item()
        self._n = 0

    def _notifications(self, n=30, global_only=False):
        # Notification.save() derives the category from the type, so pick one type per category.
        # The list without ?category= is the global bell; the counts route groups every category.
        by_cat = {}
        for t, c in Notification.TYPE_CATEGORY.items():
            by_cat.setdefault(c, t)
        cats = ([Notification.CATEGORY_GLOBAL] if global_only else
                [Notification.CATEGORY_GLOBAL, Notification.CATEGORY_DEMAND, Notification.CATEGORY_FOLLOWUPS])
        types = [by_cat.get(c, 'reservation_status') for c in cats]
        for i in range(n):
            self._n += 1
            Notification.objects.create(recipient=self.profile, notification_type=types[i % len(types)],
                                        title=f'perf {self._n}')

    def _reservations(self, n=30):
        statuses = [c[0] for c in Reservation._meta.get_field('status').choices]
        for i in range(n):
            self._n += 1
            Reservation.objects.create(item=self.item, branch=self.branch, quantity_requested=1,
                                       contact_name=f'عميل {self._n}', contact_phone=f'010{self._n:08d}',
                                       created_by=self.profile, status=statuses[i % len(statuses)])

    def _sync_runs(self, n=10):
        for _ in range(n):
            run = SyncRun.objects.create(status='completed')
            for table in ('items', 'stock', 'customers', 'sales'):
                SyncLog.objects.create(sync_run=run, table_name=table, records_processed=5)

    def test_notifications_list(self):
        self._notifications(3, global_only=True)
        assert_budget(self, 'notifications/', self.client, '/api/notifications/',
                      grow=lambda: self._notifications(30, global_only=True), min_rows=20)

    def test_category_counts(self):
        self._notifications(3)
        assert_budget(self, 'notifications/category-counts', self.client,
                      '/api/notifications/category-counts/', grow=self._notifications, min_rows=0)

    def test_sync_status(self):
        self._sync_runs(1)
        assert_budget(self, 'sync/status', self.client, '/api/sync/status/',
                      grow=self._sync_runs, min_rows=0)

    def test_sync_freshness(self):
        self._sync_runs(1)
        assert_budget(self, 'sync/freshness', self.client, '/api/sync/freshness/',
                      grow=self._sync_runs, min_rows=0)

    def test_dashboard_summary(self):
        self._reservations(3)
        assert_budget(self, 'dashboard/summary', self.client, '/api/dashboard/summary/',
                      grow=self._reservations, min_rows=0)
