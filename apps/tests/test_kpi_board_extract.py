"""KPI board maths extracted to apps.forecasting.kpi_board (Task 9 of phone alerts).

The view's JSON is pinned to a hand-computed golden that held BEFORE the extraction, so the
refactor is proven behaviour-neutral, and ``branch_mtd`` is proven equal to the view's cells."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from apps.branches.models import Branch
from apps.forecasting.models import KpiActualRollup as K
from apps.incentives.models import SalesTarget
from apps.tests.factories import make_user


class KpiBoardExtractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = Branch.objects.create(softech_branch_id='951', code='951', name='A', name_ar='فرع أ')
        cls.b = Branch.objects.create(softech_branch_id='952', code='952', name='B', name_ar='فرع ب')
        for br, val in ((cls.a, '12000.50'), (cls.b, '4000')):
            K.objects.create(branch=br, year=2026, month=5, metric=K.M_CASH_DELIVERY, value=Decimal(val))
        for br in (cls.a, cls.b):
            SalesTarget.objects.create(scope_type='branch', branch=br, metric=K.M_CASH_DELIVERY,
                                       period_start=date(2026, 5, 1), period_end=date(2026, 5, 31),
                                       target_value=Decimal('10000'))
        _, _, cls.client_ = make_user('kpi_admin', role='admin', access_all=True)

    def _board(self):
        r = self.client_.get('/api/forecasting/kpi-board/', {'year': 2026, 'month': 5})
        self.assertEqual(r.status_code, 200)
        return r.json()

    def test_view_json_unchanged_golden(self):
        data = self._board()
        self.assertEqual((data['data_through'], data['days_elapsed'], data['days_total']),
                         ('2026-05-31', 31, 31))
        rows = {r['branch_id']: r for r in data['branches']}
        ca = rows[self.a.id]['cells'][K.M_CASH_DELIVERY]
        cb = rows[self.b.id]['cells'][K.M_CASH_DELIVERY]
        self.assertEqual(ca, {'actual': 12000.5, 'target': 10000.0, 'target_todate': 10000.0,
                              'pct': 120.0, 'pct_full': 120.0, 'pace': 'met', 'target_id': ca['target_id']})
        self.assertEqual(cb, {'actual': 4000.0, 'target': 10000.0, 'target_todate': 10000.0,
                              'pct': 40.0, 'pct_full': 40.0, 'pace': 'missed', 'target_id': cb['target_id']})
        self.assertEqual(data['totals'][K.M_CASH_DELIVERY]['actual'], 16000.5)

    def test_branch_mtd_matches_view(self):
        from apps.forecasting import kpi_board
        data = self._board()
        rows = {r['branch_id']: r['cells'][K.M_CASH_DELIVERY] for r in data['branches']}
        out = kpi_board.branch_mtd([self.a.id, self.b.id], 2026, 5)
        for bid, cell in rows.items():
            got = out[bid]
            self.assertEqual(got['actual'], Decimal(str(cell['actual'])))
            self.assertEqual(got['target'], Decimal(str(cell['target'])))
            self.assertEqual(got['pct'], Decimal(str(cell['pct'])))
            self.assertEqual(got['as_of'], date(2026, 5, 31))
            self.assertIsNone(got['daily_needed'])          # month over

    def test_branch_mtd_daily_needed_and_missing_target(self):
        from apps.forecasting import kpi_board
        c = Branch.objects.create(softech_branch_id='953', code='953', name='C', name_ar='فرع ج')
        K.objects.create(branch=c, year=2026, month=5, metric=K.M_CASH_DELIVERY, value=Decimal('500'))
        # pretend we are mid-month: data through the 20th → 11 days left for branch A (target 10000)
        with mock.patch.object(kpi_board, 'latest_complete_date', return_value=date(2026, 5, 20)):
            out = kpi_board.branch_mtd([self.a.id, self.b.id, c.id], 2026, 5)
        self.assertEqual(out[self.b.id]['daily_needed'], Decimal('545.45'))   # (10000-4000)/11
        self.assertEqual(out[self.a.id]['daily_needed'], Decimal('0.00'))     # already above target
        self.assertIsNone(out[c.id]['target'])
        self.assertIsNone(out[c.id]['pct'])
        self.assertIsNone(out[c.id]['daily_needed'])
        self.assertEqual(out[c.id]['actual'], Decimal('500.0'))
