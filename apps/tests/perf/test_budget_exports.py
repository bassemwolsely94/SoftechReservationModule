"""
Query budgets for the export jobs (performance Stage 4, design §4 "export start ≤ 1 s"): starting a
job does no file work, and the status poll each open export makes every 1.5 s stays tiny — both flat
however many jobs the table holds.
"""
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.export_jobs.models import ExportJob

from ..factories import make_admin
from .budget import SLACK, _top_shapes, assert_budget, measure
from .budgets import BUDGETS


def _no_thread(target, *, args=(), kwargs=None, name=None, daemon=True):
    return None                     # the job stays queued: only the start is measured


class ExportJobBudgets(TestCase):
    def setUp(self):
        _, self.profile, self.client = make_admin('perf_export')
        _, self.other, _ = make_admin('perf_export_other')
        p = mock.patch('core.threads.start_thread', side_effect=_no_thread)
        p.start()
        self.addCleanup(p.stop)

    def _old_jobs(self, n=30):
        """Finished jobs of both users, half of them past the 48 h retention."""
        for i in range(n):
            j = ExportJob.objects.create(kind='purchasing', requested_by=self.other if i % 2 else self.profile,
                                         status=ExportJob.DONE if i % 3 else ExportJob.FAILED, data=b'x' * 10)
            if i % 2:
                ExportJob.objects.filter(pk=j.pk).update(created_at=timezone.now() - timedelta(hours=60))

    def test_status_poll(self):
        job = ExportJob.objects.create(kind='purchasing', requested_by=self.profile)
        assert_budget(self, 'export-jobs/<id>', self.client, f'/api/export-jobs/{job.pk}/',
                      grow=self._old_jobs, min_rows=1,
                      rows_of=lambda r: 1 if (getattr(r, 'data', None) or {}).get('id') == job.pk else 0)

    def test_start(self):
        from apps.purchasing.models import DemandCalculationRun
        DemandCalculationRun.objects.create(status='success')
        url = '/api/purchasing/export/jobs/?view=pivot'
        before, r1, _ = measure(self.client, url, method='post')
        self.assertEqual(r1.status_code, 202, r1.content[:200])
        ExportJob.objects.filter(pk=r1.data['id']).update(status=ExportJob.DONE)   # frees the one-active slot
        self._old_jobs()
        after, r2, queries = measure(self.client, url, method='post')
        self.assertEqual(r2.status_code, 202, r2.content[:200])
        self.assertFalse(any('itemdemandmetrics' in q['sql'] for q in queries), 'the start built the file')
        self.assertLessEqual(abs(after - before), SLACK, f'start grows with jobs ({before} → {after}):\n'
                                                         f'{_top_shapes(queries)}')
        ceiling = BUDGETS['purchasing/export/jobs'].ceiling
        self.assertLessEqual(after, ceiling, f'{after} queries > ceiling {ceiling}:\n{_top_shapes(queries)}')
