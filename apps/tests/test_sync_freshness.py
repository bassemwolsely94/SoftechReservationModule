"""
apps/tests/test_sync_freshness.py

Per-domain data freshness (apps/sync/freshness.py + /api/sync/freshness/).
Verifies each domain reads its own last SUCCESSFUL per-table SyncLog, that the
stale threshold tracks the lane cadence, and that the sales timeseries carries
data_through / completeness.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.branches.models import Branch
from apps.catalog.models import Item
from apps.customers.models import Customer, PurchaseHistory
from apps.sync.models import SyncRun, SyncLog
from apps.sync.freshness import get_freshness
from apps.tests.factories import make_admin


def _run(status, when, tables):
    """Create a SyncRun (status, started/completed=when) with a SyncLog per table."""
    run = SyncRun.objects.create(status=status)
    SyncRun.objects.filter(pk=run.pk).update(started_at=when, completed_at=when)
    for t in tables:
        log = SyncLog.objects.create(sync_run=run, table_name=t, records_processed=1)
        SyncLog.objects.filter(pk=log.pk).update(created_at=when)
    return run


class FreshnessCoreTests(TestCase):
    def test_stock_and_sales_fresh_from_recent_success(self):
        now = timezone.now()
        _run('success', now - timedelta(minutes=2), ['stkbal', 'stktrans', 'branches'])
        f = get_freshness(['stock', 'sales'])['domains']
        self.assertFalse(f['stock']['stale'])
        self.assertFalse(f['sales']['stale'])
        self.assertIsNotNone(f['stock']['last_success_at'])
        self.assertLessEqual(f['stock']['age_seconds'], 200)

    def test_slow_domain_goes_stale(self):
        now = timezone.now()
        # catalog last succeeded 6h ago; slow cadence 60m × factor 3 = 180m → stale
        _run('success', now - timedelta(hours=6), ['items', 'itembarcodes'])
        f = get_freshness(['catalog'])['domains']
        self.assertTrue(f['catalog']['stale'])
        self.assertEqual(f['catalog']['lane'], 'slow')

    def test_never_synced_domain_is_stale_with_nulls(self):
        f = get_freshness(['customers'])['domains']
        self.assertTrue(f['customers']['stale'])
        self.assertIsNone(f['customers']['last_success_at'])

    def test_running_or_failed_run_is_not_counted_as_success(self):
        now = timezone.now()
        _run('failed', now - timedelta(minutes=1), ['stkbal'])
        _run('running', now, ['stkbal'])
        f = get_freshness(['stock'])['domains']
        # no SUCCESSFUL stkbal log yet → stale, but an attempt IS recorded
        self.assertTrue(f['stock']['stale'])
        self.assertIsNone(f['stock']['last_success_at'])
        self.assertIsNotNone(f['stock']['last_attempt_at'])
        self.assertTrue(f['stock']['last_run_failed'] in (True, False))

    def test_sales_carries_data_through_and_completeness(self):
        now = timezone.now()
        _run('success', now - timedelta(minutes=2), ['stktrans'])
        b = Branch.objects.create(softech_branch_id='991', code='991', name='F', name_ar='ف')
        c = Customer.objects.create(name='c', softech_id='CF1')
        it = Item.objects.create(softech_id='IF1', name='x', medicine_type='10')
        # seed every day of the trailing window so there are no empty/low gaps
        today = timezone.localdate()
        for d in range(1, 15):
            day = today - timedelta(days=d)
            for n in range(5):
                PurchaseHistory.objects.create(
                    customer=c, branch=b, softech_invoice_id=f'INV{d}-{n}', doc_code='115',
                    total_amount=Decimal('100'),
                    invoice_date=timezone.make_aware(timezone.datetime(day.year, day.month, day.day, 12)),
                    sales_channel='91', sales_person_type='10')
        f = get_freshness(['sales'])['domains']['sales']
        self.assertEqual(f['data_through'], (today - timedelta(days=1)).isoformat())
        self.assertEqual(f['behind_days'], 0)
        self.assertTrue(f['complete'])
        self.assertEqual(f['empty_days'], [])


class FreshnessCustomSourceTests(TestCase):
    def test_expiry_reads_stock_expiry_run(self):
        from apps.batches.models import StockExpirySyncRun
        now = timezone.now()
        # a recent 'partial' sweep still counts as refreshed data
        StockExpirySyncRun.objects.create(status='partial', finished_at=now - timedelta(hours=2))
        f = get_freshness(['expiry'])['domains']['expiry']
        self.assertFalse(f['stale'])
        self.assertEqual(f['cadence_minutes'], 1440)
        self.assertIsNotNone(f['last_success_at'])

    def test_expiry_goes_stale_after_days(self):
        from apps.batches.models import StockExpirySyncRun
        now = timezone.now()
        StockExpirySyncRun.objects.create(status='success', finished_at=now - timedelta(days=5))
        f = get_freshness(['expiry'])['domains']['expiry']
        self.assertTrue(f['stale'])   # 5 days > 1440m × 3 = 3 days

    def test_purchases_reads_procurement_run(self):
        from apps.procurement.models import ProcurementEngineRun
        now = timezone.now()
        # ordered by started_at (= creation order): create the success first, then
        # a later failed run, so the latest run is the failed one.
        ProcurementEngineRun.objects.create(status='success', finished_at=now - timedelta(hours=3))
        ProcurementEngineRun.objects.create(status='failed', finished_at=now - timedelta(hours=1))
        f = get_freshness(['purchases'])['domains']['purchases']
        self.assertFalse(f['stale'])            # the earlier success is still recent
        self.assertIsNotNone(f['last_success_at'])
        self.assertTrue(f['last_run_failed'])   # latest run failed


class FreshnessEndpointTests(TestCase):
    def test_endpoint_filters_by_domains(self):
        _, _, client = make_admin()
        now = timezone.now()
        _run('success', now - timedelta(minutes=2), ['stkbal'])
        resp = client.get('/api/sync/freshness/?domains=stock,sales')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(set(resp.data['domains'].keys()), {'stock', 'sales'})
        self.assertIn('server_now', resp.data)

    def test_endpoint_requires_auth(self):
        from apps.tests.factories import make_anon_client
        self.assertIn(make_anon_client().get('/api/sync/freshness/').status_code, (401, 403))
