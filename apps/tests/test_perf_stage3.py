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
