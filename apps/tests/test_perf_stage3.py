"""
apps/tests/test_perf_stage3.py

Performance Stage 3 (docs/superpowers/plans/2026-11-19-perf-stage3-polled-screens.md): the polled
screens and the slow summaries answer exactly as before, with a query count that does not grow
with the data. "Before" is the frozen pre-change code in apps/tests/perf_reference/.
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

NOW = timezone.now().replace(microsecond=0)


def _at(minutes_ago):
    return NOW - datetime.timedelta(minutes=minutes_ago)


def _count_queries(fn, *args, **kwargs):
    with CaptureQueriesContext(connection) as ctx:
        fn(*args, **kwargs)
    return len(ctx.captured_queries)


# ── 1. GET /api/sync/freshness/ ────────────────────────────────────────────────────────────────

class FreshnessSameAnswerTests(TestCase):
    """New get_freshness == the pre-change get_freshness on the same data, in ≤ 8 queries."""

    def _seed(self, n=1):
        from apps.sync.models import SyncLog, SyncRun
        from apps.batches.models import StockExpirySyncRun
        from apps.procurement.models import ProcurementEngineRun
        from apps.pbx.models import CdrSyncRun
        from apps.finance.models import FinanceSyncRun

        for i in range(n):
            ok = SyncRun.objects.create(status='success')
            bad = SyncRun.objects.create(status='failed')
            SyncRun.objects.filter(pk=ok.pk).update(started_at=_at(30 + i))
            SyncRun.objects.filter(pk=bad.pk).update(started_at=_at(5 + i))
            for t, m in (('stkbal', 12), ('stktrans', 14), ('items', 200), ('itembarcodes', 190),
                         ('localcustomers', 75), ('users', 400)):
                SyncLog.objects.filter(pk=SyncLog.objects.create(sync_run=ok, table_name=t).pk) \
                    .update(created_at=_at(m + i))
            # a later attempt that failed — counts as an attempt, never a success
            for t in ('stkbal', 'items'):
                SyncLog.objects.filter(pk=SyncLog.objects.create(sync_run=bad, table_name=t).pk) \
                    .update(created_at=_at(3 + i))

            # expiry: newest run failed, an older partial counts as success
            p = StockExpirySyncRun.objects.create(status='partial')
            StockExpirySyncRun.objects.filter(pk=p.pk).update(started_at=_at(600 + i), finished_at=_at(590 + i))
            f = StockExpirySyncRun.objects.create(status='failed')
            StockExpirySyncRun.objects.filter(pk=f.pk).update(started_at=_at(60 + i), finished_at=None)
            # purchases: newest is a success without finished_at (falls back to started_at)
            s = ProcurementEngineRun.objects.create(status='success')
            ProcurementEngineRun.objects.filter(pk=s.pk).update(started_at=_at(100 + i), finished_at=None)
            # calls: only a running row (no success at all)
            r = CdrSyncRun.objects.create(status='running')
            CdrSyncRun.objects.filter(pk=r.pk).update(started_at=_at(4 + i))
            # finance: the expense run brought rows, the journal run did not
            fe = FinanceSyncRun.objects.create(status='success', records_synced={'expense_records': 5})
            FinanceSyncRun.objects.filter(pk=fe.pk).update(started_at=_at(300 + i), finished_at=_at(295 + i))
            fj = FinanceSyncRun.objects.create(status='success', records_synced={'journal_entries': 0})
            FinanceSyncRun.objects.filter(pk=fj.pk).update(started_at=_at(200 + i), finished_at=_at(199 + i))

    def _both(self):
        from apps.sync.freshness import get_freshness
        from apps.tests.perf_reference.freshness_before import get_freshness as before
        with mock.patch('django.utils.timezone.now', return_value=NOW):
            return get_freshness(), before()

    def test_same_answer_with_data(self):
        self._seed()
        new, old = self._both()
        self.assertEqual(new, old)
        # sanity: the seed actually exercised the interesting branches
        d = new['domains']
        self.assertTrue(d['stock']['last_run_failed'])
        self.assertNotEqual(d['stock']['last_success_at'], d['stock']['last_attempt_at'])
        self.assertTrue(d['expiry']['last_run_failed'])
        self.assertIsNotNone(d['expiry']['last_success_at'])
        self.assertIsNone(d['calls']['last_success_at'])
        self.assertIsNotNone(d['finance_expenses']['last_success_at'])
        self.assertIsNone(d['finance_journal']['last_success_at'])

    def test_same_answer_empty(self):
        new, old = self._both()
        self.assertEqual(new, old)

    def test_same_answer_for_a_subset(self):
        from apps.sync.freshness import get_freshness
        from apps.tests.perf_reference.freshness_before import get_freshness as before
        self._seed()
        with mock.patch('django.utils.timezone.now', return_value=NOW):
            for wanted in (['stock'], ['sales', 'expiry'], ['calls', 'nope'], ['finance_journal']):
                self.assertEqual(get_freshness(wanted), before(wanted), wanted)

    def test_query_count_is_small_and_flat(self):
        from apps.sync.freshness import get_freshness
        self._seed(1)
        small = _count_queries(get_freshness)
        self._seed(3)
        self.assertEqual(_count_queries(get_freshness), small)
        self.assertLessEqual(small, 8)


# ── 2. GET /api/dashboard/summary/ ─────────────────────────────────────────────────────────────

class DashboardSummarySameAnswerTests(TestCase):
    """New dashboard_summary == the pre-change view on the same data, for a chain-wide admin and a
    branch pharmacist, in a query count that does not grow with the data."""

    @classmethod
    def setUpTestData(cls):
        from apps.tests.factories import make_admin, make_branch, make_branch2, make_pharmacist
        cls.b1, cls.b2 = make_branch(), make_branch2()
        cls.admin = make_admin('perf_dash_admin')
        cls.pharm = make_pharmacist('perf_dash_pharm', branch=cls.b1)

    def _seed(self, n=1):
        from apps.customers.models import Customer, PurchaseHistory
        from apps.followups.models import FollowUpTask
        from apps.reservations.models import Reservation
        from apps.transfers.models import TransferRequest
        from apps.tests.factories import make_item
        today = datetime.date.today()
        staff = self.admin[1]
        base = Reservation.objects.count()
        item = make_item(softech_id=f'PD{base:04d}')
        k = 0
        for _ in range(n):
            for branch in (self.b1, self.b2):
                for status in ('pending', 'available', 'contacted', 'confirmed', 'fulfilled', 'cancelled'):
                    for priority in ('normal', 'urgent', 'chronic'):
                        k += 1
                        r = Reservation.objects.create(
                            item=item, branch=branch, quantity_requested=1, contact_name='عميل',
                            contact_phone='01033333333', created_by=staff, status=status, priority=priority,
                            follow_up_date=today if k % 2 else today + datetime.timedelta(days=3))
                        if k % 3 == 0:
                            Reservation.objects.filter(pk=r.pk).update(
                                updated_at=timezone.now() - datetime.timedelta(days=10))
            cust = Customer.objects.create(name=f'عميل {base}-{k}', phone=f'0101{base:03d}{k:04d}',
                                           churn_segment='high')
            Customer.objects.create(name=f'عميل ح {base}-{k}', phone=f'0102{base:03d}{k:04d}',
                                    churn_segment='critical')
            Customer.objects.create(name=f'حساب {base}-{k}', phone=f'0103{base:03d}{k:04d}',
                                    is_account_placeholder=True)
            for i, (doc, branch, days) in enumerate((('115', self.b1, 1), ('115', self.b2, 2),
                                                      ('30', self.b1, 1), ('115', self.b1, 30))):
                PurchaseHistory.objects.create(
                    customer=cust, branch=branch, softech_invoice_id=f'pd{base}-{k}-{i}', doc_code=doc,
                    total_amount=Decimal('100.25') * (i + 1),
                    invoice_date=timezone.now() - datetime.timedelta(days=days))
            for status, due in (('pending', today), ('pending', today - datetime.timedelta(days=2)),
                                ('called', today - datetime.timedelta(days=1)), ('missed', today)):
                FollowUpTask.objects.create(customer=cust, due_date=due, status=status)
            for status, supplier in (('pending', self.b2), ('sent_to_erp', self.b1), ('approved', self.b1)):
                TransferRequest.objects.create(requesting_branch=self.b2 if supplier == self.b1 else self.b1,
                                               supplying_branch=supplier, created_by=staff, status=status)

    def _call(self, view, user, query=''):
        from rest_framework.test import APIRequestFactory, force_authenticate
        req = APIRequestFactory().get('/api/dashboard/summary/' + query)
        force_authenticate(req, user=user)
        data = view(req).data
        data.pop('generated_at')
        return data

    def _assert_same(self):
        from apps.dashboard.views import dashboard_summary
        from apps.tests.perf_reference.dashboard_before import dashboard_summary as before
        for user, query in ((self.admin[0], ''), (self.admin[0], f'?branch={self.b2.id}'),
                            (self.pharm[0], ''), (self.pharm[0], f'?branch={self.b2.id}')):
            new, old = self._call(dashboard_summary, user, query), self._call(before, user, query)
            self.assertEqual(new, old, (user.username, query))
        return new

    def test_same_answer_with_data(self):
        self._seed()
        last = self._assert_same()
        self.assertGreater(last['reservations']['active_total'], 0)

    def test_same_answer_empty(self):
        self._assert_same()

    def test_query_count_is_small_and_flat(self):
        from apps.dashboard.views import dashboard_summary
        self._seed(1)
        small = _count_queries(self._call, dashboard_summary, self.admin[0])
        self._seed(3)
        self.assertEqual(_count_queries(self._call, dashboard_summary, self.admin[0]), small)
        self.assertLessEqual(small, 12)
