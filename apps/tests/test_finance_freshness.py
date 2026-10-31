"""
apps/tests/test_finance_freshness.py

P-43 (docs/product-review/06_SPEC_P-43): finance screens never show stale numbers silently.
  • the nightly finance sync (last 3 months, journal + expenses + treasury) is scheduled
  • a month that loses the SOFTECH connection is retried once
  • freshness exposes finance_pl / finance_expenses / finance_journal, stale after 3× cadence
"""
import datetime
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.sync import tasks
from apps.sync.freshness import get_freshness


class FinanceNightlyJobTests(TestCase):

    def test_registered_at_0215(self):
        from .test_scheduler_jobs import _FakeScheduler
        captured = {}

        class _Capture(_FakeScheduler):
            def add_job(self, func, trigger, *args, **kwargs):
                captured[kwargs.get('id')] = kwargs
                super().add_job(func, trigger, *args, **kwargs)

        with mock.patch.object(tasks, 'BackgroundScheduler', _Capture), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
        self.assertIn('finance_nightly_sync', captured)
        self.assertEqual((captured['finance_nightly_sync']['hour'],
                          captured['finance_nightly_sync']['minute']), (2, 15))

    def test_syncs_three_months_and_retries_a_dropped_month_once(self):
        calls = []

        class _Engine:
            def __init__(self, year, month, sync_run=None, **kw):
                self.ym = (year, month)

            def run(self):
                calls.append(self.ym)
                if len(calls) == 1:
                    raise Exception('JZ0C0: Connection is already closed.')
                return {'status': 'success'}

        with mock.patch('apps.finance.engine.sync_engine.FinanceSyncEngine', _Engine):
            tasks._run_finance_nightly_sync()
        self.assertEqual(len(calls), 4)            # 3 months + 1 retry
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(len(set(calls)), 3)


class FinanceFreshnessTests(TestCase):

    def _run(self, hours_ago, journal=0, expenses=0):
        from apps.finance.models import FinanceSyncRun
        r = FinanceSyncRun.objects.create(status='success', records_synced={
            'journal_entries': journal, 'expense_records': expenses})
        FinanceSyncRun.objects.filter(pk=r.pk).update(
            finished_at=timezone.now() - datetime.timedelta(hours=hours_ago))

    def test_domains_present(self):
        keys = {'finance_pl', 'finance_expenses', 'finance_journal', 'ap_reconciliation'}
        d = get_freshness(list(keys))['domains']
        self.assertEqual(set(d), keys)
        self.assertTrue(all(v['stale'] for v in d.values()))     # never synced

    def test_recent_journal_run_is_fresh_old_one_stale(self):
        self._run(hours_ago=5, journal=120, expenses=0)
        d = get_freshness(['finance_journal', 'finance_expenses'])['domains']
        self.assertFalse(d['finance_journal']['stale'])
        self.assertTrue(d['finance_expenses']['stale'])           # that run carried no expenses

        from apps.finance.models import FinanceSyncRun
        FinanceSyncRun.objects.all().delete()
        self._run(hours_ago=24 * 4, journal=120)                   # older than 3 × 1 day
        self.assertTrue(get_freshness(['finance_journal'])['domains']['finance_journal']['stale'])
