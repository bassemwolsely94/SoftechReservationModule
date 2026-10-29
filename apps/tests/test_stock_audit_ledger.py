"""
apps/tests/test_stock_audit_ledger.py

Doc 32 Phase 1 — the read-only stktrans mirror (apps/stock_audit/ledger.py).
No Sybase: sync_ledger() takes an injected fetch(d1, d2) that returns rows in COLUMNS order.
"""
import datetime as _dt
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.stock_audit.ledger import COLUMNS, _chunks, prune_ledger, recent_range, row_to_line, sync_ledger
from apps.stock_audit.models import StockLedgerLine, StockLedgerSyncRun

D = _dt.date


def row(**kw):
    """A stktrans row as jConnect returns it (floats for decimals, naive datetimes)."""
    base = dict(
        branchcode='160', doccode='115', docnumber=936270.0, docdate=_dt.datetime(2026, 10, 20),
        trans_time=_dt.datetime(2026, 10, 20, 14, 5, 45), storecode='160', storecode2=None,
        usercode='166', personcode='4785', suppliercode=None, itemcode='119729',
        itemexpirydate=_dt.datetime(2028, 1, 1), transqty=1.0, newqty=3.0, bonusqty=0.0, retqty=0.0,
        transprice=45.0, transprice_total=45.0, newcostprice=27.5488, itemsaleprice=45.0,
        itemsalestax=5.5263, itemsaleprice_tax=39.4737, pharmacydiscp=0.0, additionaldiscp=14.0,
        custdiscp=0.0, specialdiscp=0.0, r_doccode='0', r_docnumber=0.0,
        r_docdate=_dt.datetime(1900, 1, 1), s_doccode=None, s_docnumber=None, s_docdate=None,
    )
    base.update(kw)
    return tuple(base[c] for c in COLUMNS)


class RowCleaningTests(SimpleTestCase):

    def test_values_are_cleaned_to_softech_precision(self):
        line = row_to_line(row(), {'119729': 7})
        self.assertEqual(line.docnumber, 936270)
        self.assertEqual(line.docdate, D(2026, 10, 20))
        self.assertEqual(line.transprice, Decimal('45.0000'))
        self.assertEqual(line.newcostprice, Decimal('27.5488'))
        self.assertEqual(line.additionaldiscp, Decimal('14.00'))
        self.assertEqual(line.item_id, 7)
        self.assertTrue(timezone.is_aware(line.trans_time))
        self.assertEqual(timezone.localtime(line.trans_time).hour, 14)   # wall clock kept

    def test_placeholder_references_become_empty(self):
        line = row_to_line(row(), {})
        self.assertIsNone(line.r_docnumber)       # 0 → None
        self.assertIsNone(line.r_docdate)         # 1900-01-01 → None
        self.assertEqual(line.storecode2, '')
        self.assertIsNone(line.item_id)           # item not in catalog

    def test_return_reference_kept(self):
        line = row_to_line(row(doccode='30', r_docnumber=417978.0,
                               r_docdate=_dt.datetime(2026, 10, 23)), {})
        self.assertEqual(line.r_docnumber, 417978)
        self.assertEqual(line.r_docdate, D(2026, 10, 23))

    def test_unusable_rows_are_skipped(self):
        self.assertIsNone(row_to_line(row(itemcode=None), {}))
        self.assertIsNone(row_to_line(row(docnumber=None), {}))
        self.assertIsNone(row_to_line(row(docdate=None), {}))

    def test_chunks_cover_range_exclusive_end(self):
        self.assertEqual(list(_chunks(D(2026, 10, 1), D(2026, 10, 16), 7)),
                         [(D(2026, 10, 1), D(2026, 10, 8)), (D(2026, 10, 8), D(2026, 10, 15)),
                          (D(2026, 10, 15), D(2026, 10, 16))])

    def test_recent_range_ends_tomorrow(self):
        self.assertEqual(recent_range(3, today=D(2026, 10, 26)), (D(2026, 10, 24), D(2026, 10, 27)))


class SyncLedgerTests(TestCase):

    def fetch_from(self, rows):
        """Fake HQ: return the rows whose docdate is inside [d1, d2)."""
        calls = []

        def fetch(d1, d2):
            calls.append((d1, d2))
            return [r for r in rows if d1 <= r[COLUMNS.index('docdate')].date() < d2]
        fetch.calls = calls
        return fetch

    def test_rerun_is_idempotent(self):
        rows = [row(), row(itemcode='000544', docnumber=936271.0)]
        for _ in range(2):
            s = sync_ledger(D(2026, 10, 20), D(2026, 10, 21), fetch=self.fetch_from(rows), prune=False)
        self.assertEqual(s['status'], 'success')
        self.assertEqual(StockLedgerLine.objects.count(), 2)

    def test_identical_lines_are_both_kept(self):
        # stktrans has no line id: two identical rows are two real lines (e.g. scanned twice).
        sync_ledger(D(2026, 10, 20), D(2026, 10, 21), fetch=self.fetch_from([row(), row()]), prune=False)
        self.assertEqual(StockLedgerLine.objects.count(), 2)

    def test_lines_deleted_in_softech_disappear(self):
        sync_ledger(D(2026, 10, 20), D(2026, 10, 21),
                    fetch=self.fetch_from([row(), row(docnumber=1.0)]), prune=False)
        sync_ledger(D(2026, 10, 20), D(2026, 10, 21), fetch=self.fetch_from([row()]), prune=False)
        self.assertEqual(list(StockLedgerLine.objects.values_list('docnumber', flat=True)), [936270])

    def test_days_outside_the_range_are_untouched(self):
        sync_ledger(D(2026, 10, 19), D(2026, 10, 21), prune=False, fetch=self.fetch_from(
            [row(docdate=_dt.datetime(2026, 10, 19)), row()]))
        sync_ledger(D(2026, 10, 20), D(2026, 10, 21), fetch=self.fetch_from([]), prune=False)
        self.assertEqual(list(StockLedgerLine.objects.values_list('docdate', flat=True)), [D(2026, 10, 19)])

    def test_failed_chunk_keeps_old_rows_and_reports_partial(self):
        sync_ledger(D(2026, 10, 1), D(2026, 10, 21), chunk_days=7, prune=False, fetch=self.fetch_from(
            [row(docdate=_dt.datetime(2026, 10, 2)), row()]))

        def flaky(d1, d2):
            if d1 == D(2026, 10, 1):
                raise RuntimeError('JZ0T3 read timeout')
            return []
        run = StockLedgerSyncRun.objects.create(triggered_by='test')
        s = sync_ledger(D(2026, 10, 1), D(2026, 10, 21), chunk_days=7, fetch=flaky, run=run, prune=False)
        self.assertEqual(s['status'], 'partial')
        run.refresh_from_db()
        self.assertEqual((run.status, run.chunks_ok, run.chunks_failed), ('partial', 2, 1))
        self.assertIn('JZ0T3', run.detail['2026-10-01']['error'])
        # the failed week kept its line; the replaced week (with 10-20) is now empty
        self.assertEqual(list(StockLedgerLine.objects.values_list('docdate', flat=True)), [D(2026, 10, 2)])
        self.assertIsNotNone(run.finished_at)

    def test_all_chunks_failed_is_failed(self):
        def down(d1, d2):
            raise RuntimeError('unreachable')
        self.assertEqual(sync_ledger(D(2026, 10, 1), D(2026, 10, 3), fetch=down)['status'], 'failed')

    @override_settings(STOCK_AUDIT_WINDOW_DAYS=30)
    def test_prune_drops_lines_beyond_window(self):
        sync_ledger(D(2026, 9, 1), D(2026, 10, 27), chunk_days=60, prune=False, fetch=self.fetch_from(
            [row(docdate=_dt.datetime(2026, 9, 1)), row(docdate=_dt.datetime(2026, 10, 25))]))
        self.assertEqual(prune_ledger(today=D(2026, 10, 26)), 1)
        self.assertEqual(list(StockLedgerLine.objects.values_list('docdate', flat=True)), [D(2026, 10, 25)])


class CommandAndFreshnessTests(TestCase):

    def test_command_records_a_run(self):
        out = StringIO()
        with patch('apps.stock_audit.ledger._HqFetcher.__call__', return_value=[row()]):
            call_command('sync_stock_ledger', '--from', '2026-10-20', '--to', '2026-10-21', stdout=out)
        run = StockLedgerSyncRun.objects.get()
        self.assertEqual((run.status, run.rows_synced, run.date_from), ('success', 1, D(2026, 10, 20)))
        self.assertIn('success', out.getvalue())

    def test_freshness_domain_reads_ledger_runs(self):
        from apps.sync.freshness import get_freshness
        self.assertTrue(get_freshness(['stock_audit'])['domains']['stock_audit']['stale'])   # never synced
        StockLedgerSyncRun.objects.create(status='success', finished_at=timezone.now())
        f = get_freshness(['stock_audit'])['domains']['stock_audit']
        self.assertFalse(f['stale'])
        self.assertEqual(f['cadence_minutes'], 120)

    @override_settings(STOCK_AUDIT_ENABLED=False)
    def test_scheduler_job_respects_kill_switch(self):
        from apps.sync.tasks import _run_stock_ledger_sync
        with patch('django.core.management.call_command') as cc:
            _run_stock_ledger_sync()
        cc.assert_not_called()
