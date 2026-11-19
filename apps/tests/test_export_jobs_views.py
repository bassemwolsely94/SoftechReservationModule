"""Performance Stage 4, PR 2 — whitelisted export views started as jobs (apps/export_jobs/view_kinds.py).

POST <the export's own path>jobs/ replays the same view as the requester: the job's file must equal
the direct download's. Not-whitelisted paths answer 404; no permission answers 403.
"""
from unittest import mock

from django.test import TestCase

from apps.export_jobs import view_kinds
from apps.export_jobs.models import ExportJob
from apps.tests.factories import make_admin, make_item, make_user
from apps.tests.test_export_jobs import JOBS, _cells, _inline


class ViewKindTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user, cls.prof, cls.c = make_admin('xv_admin')
        it = make_item('صنف ناقص', 'XV1')
        type(it).objects.filter(pk=it.pk).update(in_shortage=True, shortage_source='manual', shortage_note='=1+1')

    def setUp(self):
        t = mock.patch('core.threads.start_thread', side_effect=_inline)
        t.start()
        self.addCleanup(t.stop)

    def via_job(self, path, query='', client=None):
        c = client or self.c
        r = c.post(f'{path}jobs/?{query}')
        self.assertEqual(r.status_code, 202, (path, r.content[:300]))
        job = ExportJob.objects.get(pk=r.json()['id'])
        self.assertEqual(job.status, 'done', (path, job.error))
        d = c.get(f'{JOBS}{job.pk}/download/')
        self.assertEqual(d.status_code, 200)
        return job, d

    def assert_same_file(self, path, query=''):
        direct = self.c.get(f'{path}?{query}')
        self.assertEqual(direct.status_code, 200, (path, direct.content[:300]))
        job, via = self.via_job(path, query)
        self.assertEqual(_cells(via.content), _cells(direct.content), path)
        self.assertEqual(via['Content-Disposition'], direct['Content-Disposition'], path)
        ExportJob.objects.all().delete()           # frees the one-active-per-kind slot
        return job

    def test_replay_keeps_the_requesters_ip(self):
        from core.client_ip import client_ip
        r = self.c.post('/api/stock-audit/findings/export/jobs/', REMOTE_ADDR='10.20.30.40')
        job = ExportJob.objects.get(pk=r.json()['id'])
        self.assertEqual(job.params['client_ip'], '10.20.30.40')
        req = view_kinds.ReplayRequest(user=self.user, ip=job.params['client_ip'])
        self.assertEqual(client_ip(req), '10.20.30.40')

    def test_every_whitelisted_view_resolves(self):
        for key, (dotted, *_r) in view_kinds.VIEW_EXPORTS.items():
            self.assertTrue(callable(view_kinds._load(dotted)), key)
            self.assertEqual(view_kinds.kind_for(key).key, key)

    def test_shortage_same_file(self):
        job = self.assert_same_file('/api/purchasing/shortage/export/', 'view=confirmed')
        self.assertEqual(job.kind, 'v:shortage')

    def test_stock_audit_same_file(self):
        self.assert_same_file('/api/stock-audit/findings/export/', 'from=2026-11-01&to=2026-11-19')

    def test_tax_history_exports_same_file(self):
        for path in ('/api/tax-invoicing/history/documents/export/', '/api/tax-invoicing/history/receipts/export/',
                     '/api/tax-invoicing/history/recon/export/', '/api/tax-invoicing/history/recon/uncoded/export/'):
            self.assert_same_file(path, 'system=preprod')

    def test_route_kwargs_kept(self):
        self.assertEqual(view_kinds.key_for_path('/api/tax-invoicing/history/receipts/export/'), 'v:eta_history')
        job, d = self.via_job('/api/tax-invoicing/history/receipts/export/', 'system=preprod')
        self.assertIn('eta-receipts-preprod', d['Content-Disposition'])

    def test_refusal_becomes_failed_job_with_its_message(self):
        r = self.c.post('/api/tax-invoicing/history/documents/export/jobs/')         # no system
        job = ExportJob.objects.get(pk=r.json()['id'])
        self.assertEqual(job.status, 'failed')
        self.assertIn('المنظومة', job.error)
        # advanced exports with no engine run: the old 503 message
        r = self.c.post('/api/purchasing/advanced-export/jobs/')
        job = ExportJob.objects.get(pk=r.json()['id'])
        self.assertEqual((job.kind, job.status), ('v:purchasing_advanced', 'failed'))
        self.assertIn('شغّل المحرك', job.error)

    def test_not_whitelisted_is_404(self):
        # (an app's own router may answer first, e.g. /api/customers/jobs/ is its detail route — 405 there)
        for path in ('/api/purchasing/metrics/jobs/', '/api/purchasing/summary/jobs/', '/api/nothing/here/jobs/'):
            self.assertEqual(self.c.post(path).status_code, 404, path)
        self.assertFalse(ExportJob.objects.exists())

    def test_app_routes_win_over_the_generic_one(self):
        from django.urls import resolve
        self.assertEqual(resolve('/api/purchasing/export/jobs/').url_name, 'purchasing-export-job')
        self.assertNotEqual(resolve('/api/pic-analytics/export/jobs/').url_name, 'export-job-start')
        self.assertEqual(resolve('/api/pic-analytics/export/jobs/').func.cls.__name__, 'export_jobs')
        self.assertEqual(resolve('/api/stock-audit/findings/export/jobs/').url_name, 'export-job-start')

    def test_without_permission_403(self):
        _u, _p, c = make_user('xv_sales', role='salesperson')
        self.assertEqual(c.post('/api/stock-audit/findings/export/jobs/').status_code, 403)   # own gate
        with mock.patch('core.permissions.matrix_allows', return_value=False):
            self.assertEqual(c.post('/api/tax-invoicing/history/recon/export/jobs/?system=preprod').status_code, 403)
        self.assertFalse(ExportJob.objects.exists())

    def test_start_asks_the_exports_module_gate(self):
        from core.middleware.module_access import required
        for path in ('/api/purchasing/advanced-export/', '/api/purchasing/shortage/export/',
                     '/api/tax-invoicing/history/recon/export/'):
            self.assertEqual(required(f'{path}jobs/', 'POST'), required(path, 'GET'), path)
