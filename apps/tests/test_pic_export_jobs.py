"""PIC Analytics — the background Excel export (export/jobs/, doc 33 §15). Synthetic data only (CallBase)."""
from datetime import timedelta
from io import BytesIO
from unittest import mock

import openpyxl
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.pic_analytics import jobs
from apps.pic_analytics.models import PicAnalyticsAccess, PicExportJob
from apps.tests.factories import make_user
from apps.tests.test_pic_api import PERIOD, ApiBase, sheet_headers

BASE = '/api/pic-analytics/export/'


def _inline(target, *, args=(), kwargs=None, name=None, daemon=True):
    target(*args, **(kwargs or {}))


class _NoThread:
    """Records the job instead of running it (a job left queued/running)."""
    def __call__(self, target, *, args=(), kwargs=None, name=None, daemon=True):
        self.args = args


class ExportJobTests(ApiBase):

    def setUp(self):
        p = mock.patch('core.threads.start_thread', side_effect=_inline)
        self.start = p.start()
        self.addCleanup(p.stop)

    def post(self, client, extra=''):
        return client.post(f'{BASE}jobs/?{PERIOD}{extra}')

    def run_job(self, client, extra=''):
        r = self.post(client, extra)
        self.assertEqual(r.status_code, 202, r.content[:300])
        return r.json()['id']

    def download(self, client, pk):
        return client.get(f'{BASE}jobs/{pk}/download/')

    def wb(self, resp):
        self.assertEqual(resp.status_code, 200, resp.content[:300])
        return openpyxl.load_workbook(BytesIO(resp.content))

    def test_post_runs_and_download_matches_old_export(self):
        pk = self.run_job(self.admin_c)
        st = self.admin_c.get(f'{BASE}jobs/{pk}/').json()
        self.assertEqual((st['status'], st['progress_pct'], st['error']), ('done', 100, ''))
        self.assertEqual(st['file_name'], 'pic-analytics_2026-10-01_2026-10-20.xlsx')
        self.assertNotIn('data', st)
        r = self.download(self.admin_c, pk)
        self.assertIn('pic-analytics_2026-10-01_2026-10-20.xlsx', r['Content-Disposition'])
        new = self.wb(r)
        old = self.wb(self.admin_c.get(f'{BASE}?{PERIOD}'))
        self.assertEqual(new.sheetnames, old.sheetnames)
        self.assertEqual(sheet_headers(new), sheet_headers(old))
        self.assertEqual(new['العملاء'].max_row, old['العملاء'].max_row)

    def test_progress_reported_between_sheets(self):
        from apps.pic_analytics import export
        seen = []
        real = export.build_workbook

        def spy(*a, **kw):
            prog = kw['progress']
            kw['progress'] = lambda pct, msg: (seen.append((pct, msg)), prog(pct, msg))
            return real(*a, **kw)
        with mock.patch('apps.pic_analytics.export.build_workbook', side_effect=spy):
            self.run_job(self.admin_c)
        pcts = [p for p, _m in seen]
        self.assertEqual(pcts, sorted(pcts))
        self.assertIn('ورقة العملاء…', [m for _p, m in seen])

    def test_build_workbook_unchanged_without_progress(self):
        from django.test import RequestFactory

        from apps.pic_analytics.access import Access
        from apps.pic_analytics.export import build_workbook
        from apps.pic_analytics.queries.filters import Filters
        acc = Access(self.admin_p.user)
        f = Filters.from_request(RequestFactory().get(f'/x/?{PERIOD}'), acc)
        da, ca = build_workbook(f, acc, 'x')
        db, cb = build_workbook(f, acc, 'x', progress=lambda p, m: None)
        self.assertEqual(ca, cb)
        values = lambda d: {ws.title: [r for r in ws.iter_rows(values_only=True) if r[0] != 'تاريخ التصدير']  # noqa: E731
                            for ws in openpyxl.load_workbook(BytesIO(d)).worksheets}
        self.assertEqual(values(da), values(db))

    def test_branch_manager_job_no_gp_no_calls(self):
        pk = self.run_job(self.mgr_c)
        wb = self.wb(self.download(self.mgr_c, pk))
        self.assertEqual(wb.sheetnames, ['الفلاتر والتعريفات', 'نظرة عامة', 'العملاء', 'الفروع', 'البائعون',
                                         'القنوات', 'الأصناف', 'الولاء والتكرار', 'متأخرون عن الشراء'])
        for title, headers in sheet_headers(wb).items():
            for h in headers:
                for bad in ('تكلفة', 'ربح', 'هامش'):
                    self.assertNotIn(bad, str(h), (title, h))

    def test_other_user_gets_404(self):
        pk = self.run_job(self.admin_c)
        for c in (self.mgr_c, self.ph_c):
            self.assertEqual(c.get(f'{BASE}jobs/{pk}/').status_code, 404)
            self.assertEqual(self.download(c, pk).status_code, 404)
        self.assertEqual(self.admin_c.get(f'{BASE}jobs/999999/').status_code, 404)
        self.assertFalse(AuditLog.objects.filter(action='pic_analytics_exported').exists())

    def test_no_export_permission(self):
        self.assertEqual(self.post(self.ph_c).status_code, 403)
        self.assertFalse(PicExportJob.objects.exists())
        # access revoked after the job finished -> the download is refused
        pk = self.run_job(self.mgr_c)
        PicAnalyticsAccess.objects.filter(staff=self.mgr_p).update(revoked_at=timezone.now())
        self.assertEqual(self.download(self.mgr_c, pk).status_code, 403)
        self.assertFalse(AuditLog.objects.filter(action='pic_analytics_exported').exists())

    def test_anonymous(self):
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().post(f'{BASE}jobs/?{PERIOD}').status_code, 401)

    def test_second_concurrent_job_409(self):
        rec = _NoThread()
        with mock.patch('core.threads.start_thread', side_effect=rec):
            r1 = self.post(self.admin_c)
            self.assertEqual(r1.status_code, 202)
            r2 = self.post(self.admin_c)
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(r2.json()['id'], r1.json()['id'])
        self.assertEqual(PicExportJob.objects.count(), 1)
        # not ready yet: no download
        self.assertEqual(self.download(self.admin_c, r1.json()['id']).status_code, 409)
        # another user is not blocked by it
        self.assertEqual(self.post(self.mgr_c).status_code, 202)

    def test_bad_filter_400_no_job(self):
        self.assertEqual(self.admin_c.post(f'{BASE}jobs/?from=x&to=y').status_code, 400)
        self.assertEqual(self.admin_c.post(f'{BASE}jobs/?from=2026-10-05&to=2026-10-01').status_code, 400)
        self.assertFalse(PicExportJob.objects.exists())

    def test_stale_running_job_reported_failed(self):
        with mock.patch('core.threads.start_thread', side_effect=_NoThread()):
            pk = self.post(self.admin_c).json()['id']
        PicExportJob.objects.filter(pk=pk).update(status='running',
                                                  created_at=timezone.now() - timedelta(minutes=16))
        st = self.admin_c.get(f'{BASE}jobs/{pk}/').json()
        self.assertEqual(st['status'], 'failed')
        self.assertTrue(st['error'])
        self.assertEqual(self.post(self.admin_c).status_code, 202)      # no longer blocks a new one

    def test_worker_failure_is_safe(self):
        with mock.patch('apps.pic_analytics.export.build_workbook', side_effect=RuntimeError('boom /secret/path')):
            pk = self.run_job(self.admin_c)
        st = self.admin_c.get(f'{BASE}jobs/{pk}/').json()
        self.assertEqual((st['status'], st['error']), ('failed', jobs.FAILED_MSG))
        self.assertEqual(self.download(self.admin_c, pk).status_code, 409)

    def test_cleanup_deletes_old_jobs(self):
        pk = self.run_job(self.admin_c)
        keep = self.run_job(self.mgr_c)
        PicExportJob.objects.filter(pk=pk).update(created_at=timezone.now() - timedelta(hours=49))
        self.assertEqual(jobs.cleanup(), (0, 1))
        self.assertEqual(list(PicExportJob.objects.values_list('pk', flat=True)), [keep])
        # and on every POST
        PicExportJob.objects.filter(pk=keep).update(created_at=timezone.now() - timedelta(hours=49))
        self.run_job(self.admin_c)
        self.assertFalse(PicExportJob.objects.filter(pk=keep).exists())

    def test_nightly_cleanup_never_breaks_facts(self):
        from apps.sync import tasks
        with mock.patch('django.core.management.call_command') as cc, \
                mock.patch('apps.pic_analytics.jobs.cleanup', side_effect=RuntimeError('x')) as cl:
            tasks._run_pic_facts()
        cc.assert_called_once_with('build_pic_facts')
        cl.assert_called_once()

    def test_audit_written_at_download(self):
        pk = self.run_job(self.admin_c, '&salesperson=u1')
        self.assertFalse(AuditLog.objects.filter(action='pic_analytics_exported').exists())
        self.download(self.admin_c, pk)
        self.download(self.admin_c, pk)
        logs = AuditLog.objects.filter(action='pic_analytics_exported')
        self.assertEqual(logs.count(), 2)                                  # once per download
        e = logs.first()
        self.assertEqual(e.extra['filters']['salesperson'], 'u1')
        self.assertEqual(e.extra['rows']['العملاء'], 1)
        self.assertEqual(e.extra['job_id'], pk)


class ExportJobPlainUserTests(ApiBase):

    def test_supervisor_without_export_403(self):
        # a management viewer without the 'export' action cannot start a job
        from apps.pic_analytics import access as acc_mod
        _u, p, c = make_user('q_viewonly', role='admin', branch=self.ba)
        with mock.patch.object(acc_mod, '_mgmt', side_effect=lambda prof, action: action == 'view'):
            self.assertEqual(c.post(f'{BASE}jobs/?{PERIOD}').status_code, 403)
        self.assertFalse(PicExportJob.objects.exists())
