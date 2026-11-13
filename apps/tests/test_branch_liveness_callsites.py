"""
Branch.kind is the single liveness authority (branch classification piece 1, Task 4).

Every "is this branch live" filter moved from is_active / is_operational onto kind:
live() = hq + retail, retail() = retail. Closed, pending and call-center rows never appear
where a live list is meant, even when their legacy is_active / is_operational flags say True.
HQ literals became call-time hq_code() lookups.
"""
import datetime as dt
from decimal import Decimal

from django.test import TestCase

from apps.branches.models import Branch, _reset_hq_code_cache

D = Decimal


def mk(code, kind, **kw):
    kw.setdefault('name', f'B{code}')
    return Branch.objects.create(softech_branch_id=code, code=code, kind=kind, **kw)


class _Base(TestCase):
    def setUp(self):
        # test-transaction rollback fires no signals, so drop the hq_code() cache by hand
        _reset_hq_code_cache()
        self.addCleanup(_reset_hq_code_cache)
        Branch.objects.all().delete()


class AnalyticsBranchesTests(_Base):

    def test_analytics_branches_retail_minus_excluded(self):
        from apps.config.models import SystemSetting
        from apps.forecasting.kpi import analytics_branches
        mk('100', Branch.KIND_HQ)
        mk('130', Branch.KIND_RETAIL)
        mk('140', Branch.KIND_RETAIL, is_operational=False)          # paused: stays in (spec §6.9)
        mk('150', Branch.KIND_RETAIL)                                # owner-excluded below
        mk('110', Branch.KIND_CLOSED, is_operational=True)           # legacy flags say "on" — kind wins
        mk('P1', Branch.KIND_PENDING, is_operational=True)
        mk('CC', Branch.KIND_CALL_CENTER, is_operational=True)
        SystemSetting.objects.update_or_create(key='analytics_excluded_branches',
                                               defaults={'value': '100,150'})
        codes = sorted(analytics_branches().values_list('softech_branch_id', flat=True))
        self.assertEqual(codes, ['130', '140'])


class RateWriterTargetsTests(_Base):

    def test_rate_writer_targets_unchanged_on_live_set(self):
        """HQ + 5 retail + closed + pending, all with a server and the legacy flags on: the writer
        set is today's set (retail with a server) minus closed/pending — it can only shrink."""
        from apps.purchasing.rate_writer import _eligible_branches
        mk('100', Branch.KIND_HQ, db_host='10.0.0.100')
        for c in ('130', '140', '150', '160', '170'):
            mk(c, Branch.KIND_RETAIL, db_host=f'10.0.0.{c}')
        mk('110', Branch.KIND_CLOSED, db_host='10.0.0.110', is_operational=True)
        mk('B01', Branch.KIND_PENDING, db_host='10.0.0.201', is_operational=True)
        mk('180', Branch.KIND_RETAIL, db_host='')                    # no server: never (unchanged)
        mk('190', Branch.KIND_RETAIL, db_host='10.0.0.190', is_operational=False)   # paused: unchanged
        got = sorted(b.softech_branch_id for b in _eligible_branches())
        self.assertEqual(got, ['130', '140', '150', '160', '170'])
        self.assertEqual([b.softech_branch_id for b in _eligible_branches(['110', '140'])], ['140'])


class DeadStockTests(_Base):

    def test_dead_stock_ignores_closed_branches_by_kind(self):
        """A closed branch (any code — not just 110) never yields a dead-stock line."""
        from apps.catalog.models import Item
        from apps.purchasing import dead_stock
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        from django.utils import timezone
        today = dt.date(2026, 11, 1)
        mk('100', Branch.KIND_HQ)
        b130, b140 = mk('130', Branch.KIND_RETAIL), mk('140', Branch.KIND_RETAIL)
        z9 = mk('Z9', Branch.KIND_CLOSED)                            # is_active=True (legacy default)
        pend = mk('P1', Branch.KIND_PENDING)
        run = DemandCalculationRun.objects.create(status='success', finished_at=timezone.now())
        dead = Item.objects.create(softech_id='DD', name='راكد', cost_price=D('50'))
        for b, stock, rate, gap in ((b130, 6, 0, 0), (b140, 0, 2, 8), (z9, 6, 0, 0), (pend, 6, 0, 0)):
            ItemDemandMetrics.objects.create(run=run, item=dead, branch=b, calc_date=today,
                                             current_stock=stock, monthly_avg=rate, gap=gap)
        lines, _ = dead_stock.build(run, today)
        self.assertEqual(sorted(l['branch'] for l in lines), ['130'])


class PhoneAlertBranchListTests(_Base):

    def test_phone_alert_branch_list_live_only(self):
        from apps.notifications.phone_alerts.views import _mobile_rows
        hq, r = mk('100', Branch.KIND_HQ), mk('130', Branch.KIND_RETAIL)
        mk('110', Branch.KIND_CLOSED)
        mk('P1', Branch.KIND_PENDING)
        mk('CC', Branch.KIND_CALL_CENTER)
        self.assertEqual({row['branch_id'] for row in _mobile_rows()}, {hq.pk, r.pk})


class HqLookupTests(_Base):

    def test_hq_helpers_follow_the_hq_row_not_a_literal(self):
        """The ISR route guard and the purchasing/finance helpers read HQ from kind, at call time."""
        from apps.finance.queries import sybase_gl
        from apps.purchasing import dead_stock, distribution, distribution_plan, isr_guards, isr_writer
        from apps.purchasing.models import IsrPush as P
        mk('971', Branch.KIND_HQ)
        mk('130', Branch.KIND_RETAIL)
        for mod in (isr_guards, isr_writer, distribution, distribution_plan, dead_stock, sybase_gl):
            self.assertEqual(mod._hq(), '971', mod.__name__)
        self.assertIn("= '971'", sybase_gl.sql_transfer_legs_pointing_at([('5', dt.date(2026, 1, 1))]))
        isr_guards.validate_route(P.KIND_HQ_TO_BRANCH, '971', '130')       # no error
        with self.assertRaises(isr_guards.GuardError):
            isr_guards.validate_route(P.KIND_HQ_TO_BRANCH, '100', '130')

    def test_status_drift_nodes_are_retail_with_a_server(self):
        from apps.customers.status_drift import _nodes
        mk('100', Branch.KIND_HQ, db_host='10.0.0.100')
        mk('130', Branch.KIND_RETAIL, db_host='10.0.0.130')
        mk('110', Branch.KIND_CLOSED, db_host='10.0.0.110', is_operational=True)
        mk('P1', Branch.KIND_PENDING, db_host='10.0.0.201', is_operational=True)
        self.assertEqual([n[2] for n in _nodes()], ['130'])
