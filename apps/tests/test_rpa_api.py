import io
import json
import sys
import types
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.rpa.models import RpaDevice, RpaDocument, RpaJob, RpaLine, RpaRecipe, RpaScreen
from apps.tests.factories import make_branch, make_item, make_user
from apps.users.models import RoleModuleAccess

HEAD = ['كود الصنف', 'الكمية', 'تاريخ الصلاحية']
DLD = ('begindelays\nCellDelay=0.2\nFormDelay=0.25\nenddelays\n'
       'beginheader\nKey Strokes\tData\nendheader\nbeginother\nWindow=Issue\nendother\n'
       'begindata\n{TAB}\t1\nenddata\n')


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(HEAD)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile('sheet.xlsx', buf.getvalue())


def _fake_issue_device(*, staff, label, created_by):
    device = RpaDevice.objects.create(staff=staff, created_by=created_by, label=label,
                                      token_hash=f'h-{label}-{staff.id}')
    return device, 'TOKEN-SHOWN-ONCE'


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_branch('RA', 'RPA1')
        cls.b = make_branch('RB', 'RPA2')
        cls.screen = RpaScreen.objects.get(key='issue_125')
        _, cls.sup, cls.sup_c = make_user('rpa_sup', role='supervisor', branch=cls.a)
        _, cls.sup2, cls.sup2_c = make_user('rpa_sup2', role='supervisor', branch=cls.a)
        _, cls.adm, cls.adm_c = make_user('rpa_adm', role='admin', branch=cls.a)
        _, cls.adm2, cls.adm2_c = make_user('rpa_adm2', role='admin', branch=cls.a)
        _, cls.cc, cls.cc_c = make_user('rpa_cc', role='call_center', branch=cls.a)
        _, cls.ph, cls.ph_c = make_user('rpa_ph', role='pharmacist', branch=cls.a)
        RoleModuleAccess.objects.filter(role='pharmacist', module='rpa').update(is_allowed=True)
        cls.anon = APIClient()

    def _job(self, branch=None, creator=None, status='uploaded'):
        job = RpaJob.objects.create(screen=self.screen, branch=branch or self.a, target_branch=self.b,
                                    created_by=creator or self.sup, status=status)
        doc = RpaDocument.objects.create(job=job, seq=1)
        RpaLine.objects.create(document=doc, row_no=2, itemcode='1', qty=1, status='matched')
        return job

    def _recipe(self, status='draft', creator=None, version=1):
        return RpaRecipe.objects.create(screen=self.screen, version=version, status=status,
                                        created_by=creator or self.adm)


class AccessTests(_Base):
    def test_anonymous_401_and_call_center_403_everywhere(self):
        job, rec = self._job(), self._recipe()
        doc = job.documents.first()
        dev = RpaDevice.objects.create(staff=self.sup, created_by=self.sup, label='d', token_hash='x1')
        calls = [
            ('get', '/api/rpa/jobs/'), ('post', '/api/rpa/jobs/'),
            ('get', f'/api/rpa/jobs/{job.id}/'), ('post', f'/api/rpa/jobs/{job.id}/approve/'),
            ('post', f'/api/rpa/jobs/{job.id}/cancel/'), ('get', f'/api/rpa/documents/{doc.id}/'),
            ('post', f'/api/rpa/documents/{doc.id}/resolve/'), ('get', '/api/rpa/recipes/'),
            ('post', '/api/rpa/recipes/'), ('post', f'/api/rpa/recipes/{rec.id}/approve/'),
            ('get', '/api/rpa/devices/'), ('post', '/api/rpa/devices/'),
            ('post', f'/api/rpa/devices/{dev.id}/revoke/'), ('get', '/api/rpa/status/'),
        ]
        for method, url in calls:
            self.assertEqual(getattr(self.anon, method)(url).status_code, 401, (method, url))
            self.assertEqual(getattr(self.cc_c, method)(url).status_code, 403, (method, url))

    def test_recipes_write_is_admin_only(self):
        rec = self._recipe()
        self.assertEqual(self.sup_c.post('/api/rpa/recipes/', {}).status_code, 403)
        self.assertEqual(self.sup_c.post(f'/api/rpa/recipes/{rec.id}/approve/').status_code, 403)
        self.assertEqual(self.sup_c.get('/api/rpa/recipes/').status_code, 200)


class JobTests(_Base):
    def _post(self, client=None, **over):
        data = {'screen': 'issue_125', 'branch': self.a.id, 'target_branch': self.b.id, 'store_code': '101',
                'file': over.pop('file', None) or _xlsx([['1', 2, None]])}
        data.update(over)
        return (client or self.sup_c).post('/api/rpa/jobs/', data, format='multipart')

    def test_create_job_and_list(self):
        make_item('RP1', 'صنف')
        resp = self._post(file=_xlsx([['RP1', 2, None]]))
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.data['branch_name'], 'RA')
        self.assertEqual(resp.data['target_branch_name'], 'RB')
        self.assertTrue(resp.data['dry_run'])
        lst = self.sup_c.get('/api/rpa/jobs/')
        self.assertEqual(lst.status_code, 200)
        self.assertEqual(lst.data['count'], 1)

    def test_stage1_only_issue_screen(self):
        for key in ('stockcount', 'nope'):
            r = self._post(screen=key)
            self.assertEqual(r.status_code, 400, key)
            self.assertNotIn('Traceback', r.content.decode())

    def test_live_job_refused(self):
        for val in ('false', '0'):
            self.assertEqual(self._post(dry_run=val).status_code, 400)
        self.assertEqual(RpaJob.objects.count(), 0)

    def test_bad_file_is_400_not_500(self):
        bad = SimpleUploadedFile('x.xlsx', b'this is not a workbook')
        r = self._post(file=bad)
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('openpyxl', r.content.decode())
        r = self._post(file=SimpleUploadedFile('x.csv', b'\xff\xfe\x00bad\xff'))
        self.assertEqual(r.status_code, 400)
        no_cols = Workbook()
        no_cols.active.append(['a', 'b'])
        buf = io.BytesIO()
        no_cols.save(buf)
        r = self._post(file=SimpleUploadedFile('y.xlsx', buf.getvalue()))
        self.assertEqual(r.status_code, 400)

    def test_missing_file_and_oversize(self):
        r = self.sup_c.post('/api/rpa/jobs/', {'screen': 'issue_125', 'branch': self.a.id,
                                               'target_branch': self.b.id}, format='multipart')
        self.assertEqual(r.status_code, 400)
        with mock.patch('apps.rpa.views.max_upload_bytes', return_value=10):
            self.assertEqual(self._post().status_code, 400)

    def test_jobs_branch_scoped(self):
        ja, jb = self._job(self.a), self._job(self.b)
        r = self.ph_c.get('/api/rpa/jobs/')
        self.assertEqual([j['id'] for j in r.data['results']], [ja.id])
        self.assertEqual(self.ph_c.get(f'/api/rpa/jobs/{ja.id}/').status_code, 200)
        self.assertEqual(self.ph_c.get(f'/api/rpa/jobs/{jb.id}/').status_code, 404)
        self.assertEqual(self.ph_c.post(f'/api/rpa/jobs/{jb.id}/approve/').status_code, 404)
        self.assertEqual(self.ph_c.post(f'/api/rpa/jobs/{jb.id}/cancel/', {'reason': 'x'}).status_code, 404)
        doc_b = jb.documents.first()
        self.assertEqual(self.ph_c.get(f'/api/rpa/documents/{doc_b.id}/').status_code, 404)
        self.assertEqual(self.ph_c.post(f'/api/rpa/documents/{doc_b.id}/resolve/', {}).status_code, 404)
        jb.refresh_from_db()
        self.assertEqual(jb.status, 'uploaded')
        # a pharmacist cannot upload for another branch either
        r = self._post(client=self.ph_c, branch=self.b.id, target_branch=self.a.id)
        self.assertEqual(r.status_code, 403)
        # all-branch role sees both
        self.assertEqual(self.adm_c.get('/api/rpa/jobs/').data['count'], 2)

    def test_ordering_whitelist(self):
        self._job()
        for key in ('id', 'created_at', 'screen', 'branch', 'target_branch', 'filename', 'status'):
            for prefix in ('', '-'):
                r = self.sup_c.get(f'/api/rpa/jobs/?ordering={prefix}{key}')
                self.assertEqual(r.status_code, 200, prefix + key)
        self.assertEqual(self.sup_c.get('/api/rpa/jobs/?ordering=created_by__password').status_code, 400)

    def test_branch_sort_uses_names(self):
        ja, jb = self._job(self.b), self._job(self.a)
        ids = [j['id'] for j in self.adm_c.get('/api/rpa/jobs/?ordering=branch').data['results']]
        self.assertEqual(ids, [jb.id, ja.id])   # RA before RB

    def test_detail_shows_documents_and_lines(self):
        job = self._job()
        r = self.sup_c.get(f'/api/rpa/jobs/{job.id}/')
        self.assertEqual(r.data['documents'][0]['lines'][0]['row_no'], 2)
        self.assertEqual(r.data['branch_name'], 'RA')

    def test_approve_and_cancel(self):
        self._recipe('approved')
        job = self._job(creator=self.sup)
        self.assertEqual(self.sup_c.post(f'/api/rpa/jobs/{job.id}/approve/').status_code, 403)   # own upload
        r = self.sup2_c.post(f'/api/rpa/jobs/{job.id}/approve/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['status'], 'approved')
        self.assertEqual(self.sup2_c.post(f'/api/rpa/jobs/{job.id}/cancel/', {}).status_code, 400)  # no reason
        r = self.sup2_c.post(f'/api/rpa/jobs/{job.id}/cancel/', {'reason': 'خطأ'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['status'], 'cancelled')


class DocumentTests(_Base):
    def test_document_detail_has_runs(self):
        job = self._job()
        doc = job.documents.first()
        r = self.sup_c.get(f'/api/rpa/documents/{doc.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['runs'], [])

    def test_resolve_delegates(self):
        job = self._job()
        doc = job.documents.first()
        fake = types.ModuleType('apps.rpa.dispatch')
        calls = []
        fake.resolve_document = lambda d, p, decision, reason: calls.append((d.id, p.id, decision, reason))
        with mock.patch.dict(sys.modules, {'apps.rpa.dispatch': fake}):
            r = self.sup_c.post(f'/api/rpa/documents/{doc.id}/resolve/', {'decision': 'retry', 'reason': 'ok'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(calls, [(doc.id, self.sup.id, 'retry', 'ok')])

    def test_resolve_needs_edit_grant(self):
        doc = self._job().documents.first()
        _, _, purchasing_c = make_user('rpa_pur', role='purchasing', branch=self.a)   # view+create only
        r = purchasing_c.post(f'/api/rpa/documents/{doc.id}/resolve/', {'decision': 'retry', 'reason': 'x'})
        self.assertEqual(r.status_code, 403)


class RecipeTests(_Base):
    def test_import_and_approve_recipe(self):
        dld = SimpleUploadedFile('t.dld', DLD.encode('utf-8'))
        r = self.adm_c.post('/api/rpa/recipes/', {'screen': 'issue_125', 'field_map': json.dumps(['itemcode']),
                                                  'file': dld}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['status'], 'draft')
        self.assertEqual(self.adm_c.post(f'/api/rpa/recipes/{r.data["id"]}/approve/').status_code, 403)  # importer
        ok = self.adm2_c.post(f'/api/rpa/recipes/{r.data["id"]}/approve/')
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.data['status'], 'approved')

    def test_bad_dld_is_400(self):
        bad = SimpleUploadedFile('t.dld', b'garbage')
        r = self.adm_c.post('/api/rpa/recipes/', {'screen': 'issue_125', 'field_map': '["a"]', 'file': bad},
                            format='multipart')
        self.assertEqual(r.status_code, 400)
        r = self.adm_c.post('/api/rpa/recipes/', {'screen': 'issue_125', 'field_map': 'not json',
                                                  'file': SimpleUploadedFile('t.dld', DLD.encode())},
                            format='multipart')
        self.assertEqual(r.status_code, 400)
        r = self.adm_c.post('/api/rpa/recipes/', {'screen': 'issue_125', 'field_map': '["a","b"]',
                                                  'file': SimpleUploadedFile('t.dld', DLD.encode())},
                            format='multipart')
        self.assertEqual(r.status_code, 400)


class DeviceTests(_Base):
    def test_token_shown_once(self):
        fake = types.ModuleType('apps.rpa.auth')
        fake.issue_device = _fake_issue_device
        with mock.patch.dict(sys.modules, {'apps.rpa.auth': fake}):
            r = self.sup_c.post('/api/rpa/devices/', {'label': 'PC-1'})
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['token'], 'TOKEN-SHOWN-ONCE')
        self.assertNotIn('token_hash', r.data['device'])
        lst = self.sup_c.get('/api/rpa/devices/')
        self.assertNotIn('TOKEN-SHOWN-ONCE', lst.content.decode())
        self.assertNotIn('token', lst.content.decode())

    def test_own_devices_and_revoke(self):
        mine = RpaDevice.objects.create(staff=self.sup, created_by=self.sup, label='m', token_hash='h1')
        theirs = RpaDevice.objects.create(staff=self.sup2, created_by=self.sup2, label='t', token_hash='h2')
        ids = [d['id'] for d in self.sup_c.get('/api/rpa/devices/').data['results']]
        self.assertEqual(ids, [mine.id])
        self.assertEqual(len(self.adm_c.get('/api/rpa/devices/').data['results']), 2)
        self.assertEqual(self.sup_c.post(f'/api/rpa/devices/{theirs.id}/revoke/').status_code, 404)
        self.assertEqual(self.sup_c.post(f'/api/rpa/devices/{mine.id}/revoke/').status_code, 200)
        mine.refresh_from_db()
        self.assertIsNotNone(mine.revoked_at)
        self.assertTrue(AuditLog.objects.filter(action='rpa_device_revoked').exists())
        self.assertEqual(self.adm_c.post(f'/api/rpa/devices/{theirs.id}/revoke/').status_code, 200)

    def test_empty_label_400(self):
        fake = types.ModuleType('apps.rpa.auth')
        fake.issue_device = _fake_issue_device
        with mock.patch.dict(sys.modules, {'apps.rpa.auth': fake}):
            self.assertEqual(self.sup_c.post('/api/rpa/devices/', {'label': ' '}).status_code, 400)


class StatusTests(_Base):
    def test_status(self):
        now = timezone.now()
        RpaDevice.objects.create(staff=self.sup, created_by=self.sup, label='on', token_hash='s1',
                                 last_seen_at=now - timedelta(seconds=30))
        RpaDevice.objects.create(staff=self.sup, created_by=self.sup, label='old', token_hash='s2',
                                 last_seen_at=now - timedelta(minutes=5))
        RpaDevice.objects.create(staff=self.sup, created_by=self.sup, label='gone', token_hash='s3',
                                 last_seen_at=now, revoked_at=now)
        with self.settings(RPA_SOFTECH_ENTRY_ENABLED=True):
            r = self.sup_c.get('/api/rpa/status/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['switch_on'])
        self.assertEqual([d['label'] for d in r.data['my_devices_online']], ['on'])
        self.assertEqual(r.data['screens'][0]['key'], 'issue_125')
        with self.settings(RPA_SOFTECH_ENTRY_ENABLED=False):
            self.assertFalse(self.sup_c.get('/api/rpa/status/').data['switch_on'])
