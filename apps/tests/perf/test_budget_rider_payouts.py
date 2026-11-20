"""
Query budgets for the C22 rider payout ledger lists (/delivery/analytics → 💵 أجور الطيارين): a branch
manager's rides and periods lists run the same number of queries with few or many rows.
"""
import datetime as dt

from django.test import TestCase

from apps.delivery.models import DeliveryDriver
from apps.rider_payouts import ledger

from ..factories import make_branch, make_pharmacist
from .budget import assert_budget

DAY = dt.date(2026, 10, 5)


class RiderPayoutBudgets(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_pharmacist('perf_payout_mgr', branch=self.branch)
        self.n = 0

    def _rides(self, n=20):
        """n riders with a ride each (each its own period), so both lists grow."""
        for _ in range(n):
            self.n += 1
            driver = DeliveryDriver.objects.create(full_name=f'طيار {self.n}', mobile=f'0109{self.n:07d}',
                                                   branch=self.branch)
            ledger.add_ride(driver=driver, branch=self.branch, ride_date=DAY, deliveries=2, actor=self.profile)

    def test_rides_list(self):
        self._rides(2)
        assert_budget(self, 'delivery/payouts/rides', self.client, '/api/delivery/payouts/rides/?month=2026-10',
                      grow=self._rides, min_rows=20)

    def test_periods_list(self):
        self._rides(2)
        assert_budget(self, 'delivery/payouts/periods', self.client,
                      '/api/delivery/payouts/periods/?month=2026-10', grow=self._rides, min_rows=20)
