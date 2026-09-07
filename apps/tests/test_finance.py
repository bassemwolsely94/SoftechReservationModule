"""
apps/tests/test_finance.py

Covers the snapshot-driven Finance Intelligence endpoints:
  • dashboard — returns the consolidated FinancialSnapshot KPIs
  • P&L — revenue / COGS / gross profit / expenses / net profit structure
  • cash-flow — snapshot cash figures
  • expense breakdown — grouped totals by category
  • no-data → 404
  • auth required
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.finance.models import FinancialPeriod, FinancialSnapshot, ExpenseRecord
from .factories import make_branch, make_admin

DASHBOARD_URL = '/api/finance/dashboard/'
PNL_URL       = '/api/finance/pnl/'
CASHFLOW_URL  = '/api/finance/cash-flow/'
BREAKDOWN_URL = '/api/finance/expenses/breakdown/'
PERIODS_URL   = '/api/finance/periods/'


def _period(year=2026, month=3):
    return FinancialPeriod.objects.create(
        year=year, month=month, period_type='month',
        period_start=date(year, month, 1), period_end=date(year, month, 28),
    )


class FinanceDashboardTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_admin('finance_admin')
        self.period = _period()
        self.snap = FinancialSnapshot.objects.create(
            period=self.period, branch=None,
            gross_revenue=1000, returns_value=200, net_revenue=800,
            cogs=480, gross_profit=320, gross_margin_pct=Decimal('40.00'),
            total_expenses=70, payroll_expenses=50, rent_expenses=20,
            operating_profit=250, net_profit=250, net_margin_pct=Decimal('31.25'),
            cash_inflow=900, cash_outflow=650, net_cash_flow=250,
            inventory_value=5000, is_complete=True,
        )

    def test_requires_auth(self):
        self.assertEqual(APIClient().get(DASHBOARD_URL).status_code,
                         status.HTTP_401_UNAUTHORIZED)

    def test_dashboard_returns_snapshot(self):
        r = self.client.get(DASHBOARD_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(r.data['period_label'], '2026-03')
        self.assertEqual(float(r.data['net_revenue']), 800.0)
        self.assertEqual(float(r.data['net_profit']), 250.0)
        self.assertEqual(float(r.data['gross_margin_pct']), 40.0)
        self.assertTrue(r.data['is_complete'])

    def test_pnl_structure(self):
        r = self.client.get(PNL_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(float(r.data['revenue']['net_revenue']), 800.0)
        self.assertEqual(float(r.data['gross_profit']), 320.0)
        self.assertEqual(float(r.data['expenses']['total']), 70.0)
        self.assertEqual(float(r.data['net_profit']), 250.0)

    def test_cash_flow(self):
        r = self.client.get(CASHFLOW_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(float(r.data['net_cash_flow']), 250.0)

    def test_periods_list(self):
        r = self.client.get(PERIODS_URL)
        self.assertEqual(r.status_code, status.HTTP_200_OK)


class FinanceNoDataTests(TestCase):

    def setUp(self):
        _, self.profile, self.client = make_admin('finance_empty')

    def test_dashboard_404_without_data(self):
        self.assertEqual(self.client.get(DASHBOARD_URL).status_code,
                         status.HTTP_404_NOT_FOUND)


class FinanceExpenseBreakdownTests(TestCase):

    def setUp(self):
        self.branch = make_branch()
        _, self.profile, self.client = make_admin('finance_exp')
        self.period = _period()
        ExpenseRecord.objects.create(
            period=self.period, expense_date=date(2026, 3, 5),
            category='rent', amount=Decimal('20'), branch=self.branch,
        )
        ExpenseRecord.objects.create(
            period=self.period, expense_date=date(2026, 3, 6),
            category='payroll', amount=Decimal('50'), branch=self.branch,
        )

    def test_breakdown_totals_by_category(self):
        r = self.client.get(f'{BREAKDOWN_URL}?period_id={self.period.id}')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        self.assertEqual(float(r.data['total']), 70.0)
        cats = {row['category']: float(row['total']) for row in r.data['by_category']}
        self.assertEqual(cats['payroll'], 50.0)
        self.assertEqual(cats['rent'], 20.0)
