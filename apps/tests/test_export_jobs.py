"""Performance Stage 4 — the shared export job (apps/export_jobs) and the purchasing exports on it.

Synthetic data only. SOFTECH is never touched (ISR fulfilment's collect() is replaced by a fixed
snapshot). The PIC kind keeps its own tests in test_pic_export_jobs.py.
"""
import io
from datetime import date, timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from openpyxl import load_workbook

from apps.audit.models import AuditLog
from apps.export_jobs import registry, runner
from apps.export_jobs.models import ExportJob
from apps.export_jobs.registry import ExportFile, ExportKind
from apps.tests.factories import make_admin, make_user

JOBS = '/api/export-jobs/'


def _inline(target, *, args=(), kwargs=None, name=None, daemon=True):
    target(*args, **(kwargs or {}))


class _NoThread:
    """Records the job instead of running it (a job left queued)."""
    calls = 0

    def __call__(self, target, *, args=(), kwargs=None, name=None, daemon=True):
        self.calls += 1
        self.args = args


# ── a fake kind, so the runner is tested apart from any real export ─────────────────────────────

ALLOW = {'on': True}


def _fake_build(job, user, progress):
    progress(50, 'half')
    mode = (job.params.get('mode') or [''])[0]
    if mode == 'refuse':
        raise runner.JobError('رسالة للمستخدم')
    if mode == 'crash':
        raise RuntimeError('boom /secret/path')
    return ExportFile(data=b'PK-fake-bytes', file_name='fake_ملف.xlsx', rows={'s': 3}, meta={'f': 1})


def _fake_validate(request):
    if request.query_params.get('mode') == 'bad':
        raise ValueError('فلتر غير صحيح')
    return None


FAKE = ExportKind(key='fake', label='fake', allowed=lambda u: ALLOW['on'], build=_fake_build,
                  validate=_fake_validate, audit_action='pic_analytics_exported')
FAKE_SOFTECH = ExportKind(key='fake_softech', label='fake softech', allowed=lambda u: True, build=_fake_build,
                          needs_softech=True)
FAKE_KINDS = {'fake': 'apps.tests.test_export_jobs:FAKE', 'fake_softech': 'apps.tests.test_export_jobs:FAKE_SOFTECH'}


class RunnerTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.u1, cls.p1, cls.c1 = make_admin('xj_admin1')
        cls.u2, cls.p2, cls.c2 = make_admin('xj_admin2')

    def setUp(self):
        ALLOW['on'] = True
        p = mock.patch.dict(registry.KINDS, FAKE_KINDS)
        p.start()
        self.addCleanup(p.stop)
        t = mock.patch('core.threads.start_thread', side_effect=_inline)
        t.start()
        self.addCleanup(t.stop)

    def start(self, profile, mode=''):
        return runner.start('fake', profile, {'mode': [mode]} if mode else {})

    def test_start_runs_and_downloads_once_done(self):
        job, created = self.start(self.p1)
        self.assertTrue(created)
        st = self.c1.get(f'{JOBS}{job.pk}/').json()
        self.assertEqual((st['status'], st['progress_pct'], st['error'], st['kind']), ('done', 100, '', 'fake'))
        self.assertNotIn('data', st)
        r = self.c1.get(f'{JOBS}{job.pk}/download/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b'PK-fake-bytes')
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertIn('xlsx', r['Content-Disposition'])
        job.refresh_from_db()
        self.assertEqual((job.worker, job.rows, job.meta), ('thread', {'s': 3}, {'f': 1}))
        # the kind's audit row + the generic export_taken (ExportAuditMiddleware) at download only
        self.assertEqual(AuditLog.objects.filter(action='pic_analytics_exported').count(), 1)
        self.assertTrue(AuditLog.objects.filter(action='export_taken').exists())

    def test_status_poll_is_not_an_export(self):
        job, _ = self.start(self.p1)
        for _ in range(3):
            self.c1.get(f'{JOBS}{job.pk}/')
        self.assertFalse(AuditLog.objects.filter(action='export_taken').exists())

    def test_one_active_job_per_user_per_kind(self):
        with mock.patch('core.threads.start_thread', side_effect=_NoThread()):
            j1, c1 = self.start(self.p1)
            j2, c2 = self.start(self.p1)
            j3, c3 = runner.start('fake_softech', self.p1, {})
            j4, c4 = self.start(self.p2)
        self.assertEqual((c1, c2, c3, c4), (True, False, True, True))
        self.assertEqual(j2.pk, j1.pk)
        self.assertEqual(runner.start_response(j2, c2).status_code, 409)
        # not ready yet: no download
        self.assertEqual(self.c1.get(f'{JOBS}{j1.pk}/download/').status_code, 409)

    def test_other_user_gets_404(self):
        job, _ = self.start(self.p1)
        self.assertEqual(self.c2.get(f'{JOBS}{job.pk}/').status_code, 404)
        self.assertEqual(self.c2.get(f'{JOBS}{job.pk}/download/').status_code, 404)
        self.assertEqual(self.c1.get(f'{JOBS}999999/').status_code, 404)
        from rest_framework.test import APIClient
        self.assertEqual(APIClient().get(f'{JOBS}{job.pk}/').status_code, 401)

    def test_access_revoked_before_download_403(self):
        job, _ = self.start(self.p1)
        ALLOW['on'] = False
        self.assertEqual(self.c1.get(f'{JOBS}{job.pk}/download/').status_code, 403)
        self.assertFalse(AuditLog.objects.filter(action='pic_analytics_exported').exists())

    def test_access_revoked_before_run_fails(self):
        with mock.patch('core.threads.start_thread', side_effect=_NoThread()) as rec:
            job, _ = self.start(self.p1)
        ALLOW['on'] = False
        runner.run_job(job.pk)
        job.refresh_from_db()
        self.assertEqual((job.status, job.error), ('failed', runner.FAILED_MSG))
        self.assertTrue(rec.called)

    def test_job_error_text_shown_crash_text_hidden(self):
        job, _ = self.start(self.p1, 'refuse')
        job.refresh_from_db()
        self.assertEqual((job.status, job.error), ('failed', 'رسالة للمستخدم'))
        job2, _ = self.start(self.p1, 'crash')
        job2.refresh_from_db()
        self.assertEqual((job2.status, job2.error), ('failed', runner.FAILED_MSG))
        self.assertNotIn('secret', job2.error)

    def test_stale_rule_uses_last_progress(self):
        with mock.patch('core.threads.start_thread', side_effect=_NoThread()):
            old, _ = self.start(self.p1)
            fresh, _ = self.start(self.p2)
        long_ago = timezone.now() - timedelta(minutes=40)
        ExportJob.objects.filter(pk=old.pk).update(status='running', created_at=long_ago,
                                                   started_at=long_ago, heartbeat_at=timezone.now() - timedelta(minutes=16))
        # a long job still reporting progress is not stale, however old
        ExportJob.objects.filter(pk=fresh.pk).update(status='running', created_at=long_ago,
                                                     started_at=long_ago, heartbeat_at=timezone.now())
        self.assertEqual(runner.expire_stale(), 1)
        self.assertEqual(ExportJob.objects.get(pk=old.pk).error, runner.STALE_MSG)
        self.assertEqual(ExportJob.objects.get(pk=fresh.pk).status, 'running')

    def test_cleanup_deletes_after_48h(self):
        job, _ = self.start(self.p1)
        keep, _ = self.start(self.p2)
        ExportJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(hours=49))
        self.assertEqual(runner.cleanup(), (0, 1))
        self.assertEqual(list(ExportJob.objects.values_list('pk', flat=True)), [keep.pk])

    @override_settings(EXPORT_JOBS_RUNNER='service')
    def test_service_mode_leaves_queued_and_claims_with_skip_locked(self):
        rec = _NoThread()
        with mock.patch('core.threads.start_thread', side_effect=rec):
            job, _ = self.start(self.p1)
            soft, _ = runner.start('fake_softech', self.p1, {})
        self.assertEqual(rec.calls, 1)                        # only the SOFTECH kind took a thread
        self.assertEqual(ExportJob.objects.get(pk=job.pk).status, 'queued')
        self.assertEqual(runner.claim_next(), job.pk)        # the SOFTECH one is never offered
        self.assertIsNone(runner.claim_next())
        job.refresh_from_db()
        self.assertEqual((job.status, job.worker, job.progress_msg), ('running', 'service', runner.START_MSG))
        runner.execute(job.pk)
        self.assertEqual(ExportJob.objects.get(pk=job.pk).status, 'done')
        self.assertEqual(ExportJob.objects.get(pk=soft.pk).status, 'queued')   # its thread was not run here

    @override_settings(EXPORT_JOBS_RUNNER='service')
    def test_service_command_runs_queue_and_fails_orphans(self):
        with mock.patch('core.threads.start_thread', side_effect=_NoThread()):
            orphan, _ = self.start(self.p1)
            queued, _ = self.start(self.p2)
        ExportJob.objects.filter(pk=orphan.pk).update(status='running', worker='service',
                                                      started_at=timezone.now(), heartbeat_at=timezone.now())
        out = io.StringIO()
        call_command('run_export_jobs', '--once', stdout=out)
        self.assertEqual(ExportJob.objects.get(pk=orphan.pk).status, 'failed')
        self.assertEqual(ExportJob.objects.get(pk=queued.pk).status, 'done')
        self.assertIn('1 run', out.getvalue())

    def test_thread_claim_is_once_only(self):
        with mock.patch('core.threads.start_thread', side_effect=_NoThread()):
            job, _ = self.start(self.p1)
        self.assertTrue(runner._claim(job.pk, 'thread'))
        self.assertFalse(runner._claim(job.pk, 'service'))   # already running: never built twice

    def test_file_from_response(self):
        from django.http import HttpResponse, StreamingHttpResponse
        from rest_framework.response import Response
        r = HttpResponse(b'abc', content_type='x/y')
        r['Content-Disposition'] = 'attachment; filename="a.xlsx"'
        self.assertEqual(runner.file_from_response(r), (b'abc', 'a.xlsx', 'x/y'))
        s = StreamingHttpResponse(iter(['﻿a,b\r\n', 'ج,د\r\n']), content_type='text/csv; charset=utf-8')
        s['Content-Disposition'] = "attachment; filename*=UTF-8''b%20c.csv"
        body, name, _ = runner.file_from_response(s)
        self.assertEqual((body.decode('utf-8'), name), ('﻿a,b\r\nج,د\r\n', 'b c.csv'))
        with self.assertRaisesMessage(runner.JobError, 'لا توجد بيانات'):
            runner.file_from_response(Response({'detail': 'لا توجد بيانات'}, status=503))
        with self.assertRaisesMessage(runner.JobError, 'كبيرة'):
            runner.file_from_response(Response({'error': 'كبيرة'}, status=400))


class PolicyAndAccessTests(TestCase):

    def test_job_status_is_not_an_export_but_start_and_download_are(self):
        from apps.access.policy import is_export
        self.assertFalse(is_export('/api/export-jobs/5/', 'GET'))
        self.assertFalse(is_export('/api/pic-analytics/export/jobs/5/', 'GET'))
        self.assertTrue(is_export('/api/export-jobs/5/download/', 'GET'))
        self.assertTrue(is_export('/api/pic-analytics/export/jobs/5/download/', 'GET'))
        self.assertTrue(is_export('/api/purchasing/export/jobs/', 'POST'))
        self.assertTrue(is_export('/api/purchasing/isr/fulfilment/export/jobs/', 'POST'))

    def test_start_asks_what_the_direct_export_asks(self):
        from core.middleware.module_access import required
        self.assertEqual(required('/api/purchasing/export/jobs/', 'POST'), required('/api/purchasing/export/', 'GET'))
        self.assertEqual(required('/api/purchasing/isr/fulfilment/export/jobs/', 'POST'),
                         required('/api/purchasing/isr/fulfilment/export/', 'POST'))
        self.assertIsNone(required('/api/export-jobs/3/download/', 'GET'))     # own gate in the view


# ── purchasing/export/ as a job: the same file ───────────────────────────────────────────────────

def _cells(content):
    wb = load_workbook(io.BytesIO(content))
    return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}


class PurchasingExportJobTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from apps.branches.models import Branch
        from apps.purchasing.models import DemandCalculationRun, ItemDemandMetrics
        from apps.tests.factories import make_item
        cls.calc_run = DemandCalculationRun.objects.create(status='success')
        items = [make_item(f'XJ{i}', f'S{i}') for i in range(6)]
        for code, kind, order in [('100', Branch.KIND_HQ, 0), ('160', Branch.KIND_RETAIL, 1),
                                  ('170', Branch.KIND_RETAIL, 2)]:
            b = Branch.objects.create(softech_branch_id=code, code=code, name=f'B{code}', name_ar=f'فرع {code}',
                                      kind=kind, display_order=order)
            for n, it in enumerate(items):
                ItemDemandMetrics.objects.create(run=cls.calc_run, item=it, branch=b, calc_date=date(2026, 11, 1),
                                                 current_stock=n, monthly_avg=10 + n, gap=n % 3, abc_class='ABC'[n % 3])
        cls.user, cls.prof, cls.c = make_admin('xj_buyer')

    def setUp(self):
        from apps.branches.models import _reset_hq_code_cache
        _reset_hq_code_cache()
        self.addCleanup(_reset_hq_code_cache)
        t = mock.patch('core.threads.start_thread', side_effect=_inline)
        t.start()
        self.addCleanup(t.stop)

    def via_job(self, query):
        r = self.c.post(f'/api/purchasing/export/jobs/?{query}')
        self.assertEqual(r.status_code, 202, r.content[:300])
        pk = r.json()['id']
        st = self.c.get(f'{JOBS}{pk}/').json()
        self.assertEqual(st['status'], 'done', st)
        d = self.c.get(f'{JOBS}{pk}/download/')
        self.assertEqual(d.status_code, 200)
        return d

    def test_same_file_as_direct_export(self):
        for query in ('view=pivot', 'view=metrics', 'view=aggregated', 'view=metrics&abc_class=A',
                      'view=pivot&coverage_months=2&round_at=total&round_dir=nearest'):
            direct = self.c.get(f'/api/purchasing/export/?{query}')
            self.assertEqual(direct.status_code, 200, query)
            job = self.via_job(query)
            self.assertEqual(_cells(job.content), _cells(direct.content), query)
            self.assertEqual(job['Content-Disposition'], direct['Content-Disposition'], query)
            # each job finished before the next start: one active job per kind never blocks it
            ExportJob.objects.all().delete()

    def test_csv_same_bytes(self):
        direct = self.c.get('/api/purchasing/export/?view=metrics&format=csv')
        job = self.via_job('view=metrics&format=csv')
        self.assertEqual(job.content, b''.join(direct.streaming_content))
        self.assertIn('text/csv', job['Content-Type'])

    def test_no_engine_run_answered_now(self):
        from apps.purchasing.models import DemandCalculationRun
        DemandCalculationRun.objects.update(status='failed')
        r = self.c.post('/api/purchasing/export/jobs/?view=pivot')
        self.assertEqual(r.status_code, 503)
        self.assertFalse(ExportJob.objects.exists())

    def test_without_purchasing_403(self):
        _u, _p, c = make_user('xj_plain', role='salesperson')
        with mock.patch('apps.purchasing.export_jobs.matrix_allows', return_value=False):
            self.assertEqual(c.post('/api/purchasing/export/jobs/?view=pivot').status_code, 403)
        self.assertFalse(ExportJob.objects.exists())

    def test_start_is_cheap(self):
        """The start does no file work: a flat, small number of queries whatever the data size."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with mock.patch('core.threads.start_thread', side_effect=_NoThread()):
            with CaptureQueriesContext(connection) as ctx:
                r = self.c.post('/api/purchasing/export/jobs/?view=pivot')
        self.assertEqual(r.status_code, 202)
        self.assertFalse(any('purchasing_itemdemandmetrics' in q['sql'] for q in ctx.captured_queries))
        self.assertLess(len(ctx.captured_queries), 40)


# ── isr/fulfilment/export/ as a job ─────────────────────────────────────────────────────────────

@override_settings(SUPPLY_ERP_GROUPS='10,19,21,27')
class IsrFulfilmentExportJobTests(TestCase):

    def setUp(self):
        from django.core.cache import cache

        from apps.tests.factories import make_hq
        from apps.tests.test_isr_fulfillment import _user
        make_hq('100', self)
        cache.clear()
        from rest_framework.test import APIClient
        self.c = APIClient()
        self.u = _user('18', group=19)
        self.c.force_authenticate(self.u)
        t = mock.patch('core.threads.start_thread', side_effect=_inline)
        t.start()
        self.addCleanup(t.stop)

    def test_same_workbook_as_direct_export(self):
        from apps.purchasing import isr_fulfillment as F
        from apps.tests.test_isr_fulfillment import _snap
        body = {'isrs': '261609', 'coverage': 2, 'basis': 'requested'}
        with mock.patch.object(F, 'collect', return_value=_snap()):
            direct = self.c.post('/api/purchasing/isr/fulfilment/export/', body, format='json')
            r = self.c.post('/api/purchasing/isr/fulfilment/export/jobs/', body, format='json')
        self.assertEqual(r.status_code, 202, r.content[:300])
        job = ExportJob.objects.get(pk=r.json()['id'])
        self.assertEqual((job.kind, job.worker, job.status), ('isr_fulfilment', 'thread', 'done'))
        d = self.c.get(f'{JOBS}{job.pk}/download/')
        self.assertEqual(d.status_code, 200)
        self.assertIn('isr_fulfillment_261609', d['Content-Disposition'])
        self.assertEqual(_cells(d.content), _cells(direct.content))

    @override_settings(EXPORT_JOBS_RUNNER='service')
    def test_reads_softech_so_never_left_for_the_service(self):
        from apps.purchasing import isr_fulfillment as F
        from apps.tests.test_isr_fulfillment import _snap
        with mock.patch.object(F, 'collect', return_value=_snap()):
            r = self.c.post('/api/purchasing/isr/fulfilment/export/jobs/', {'isrs': '261609'}, format='json')
        self.assertEqual(ExportJob.objects.get(pk=r.json()['id']).status, 'done')
        self.assertIsNone(runner.claim_next())

    def test_bad_input_400_and_missing_isr_failed_with_message(self):
        from apps.purchasing import isr_fulfillment as F
        self.assertEqual(self.c.post('/api/purchasing/isr/fulfilment/export/jobs/', {'isrs': 'abc'},
                                     format='json').status_code, 400)
        self.assertFalse(ExportJob.objects.exists())
        with mock.patch.object(F, 'collect', side_effect=F.IsrNotFound(['999'])):
            r = self.c.post('/api/purchasing/isr/fulfilment/export/jobs/', {'isrs': '999'}, format='json')
        job = ExportJob.objects.get(pk=r.json()['id'])
        self.assertEqual(job.status, 'failed')
        self.assertIn('999', job.error)

    def test_needs_supply_access(self):
        from apps.tests.test_isr_fulfillment import _user
        self.c.force_authenticate(_user('1399', group=14))
        self.assertEqual(self.c.post('/api/purchasing/isr/fulfilment/export/jobs/', {'isrs': '261609'},
                                     format='json').status_code, 403)
