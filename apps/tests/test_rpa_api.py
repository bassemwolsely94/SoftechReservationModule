import io
import json
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
       'begindata\n\\{TAB}\t1\nenddata\n')   # DataLoad stores special keys as \{KEY}


def _xlsx(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(HEAD)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile('sheet.xlsx', buf.getvalue())


FIND = 'apps.rpa.dispatch.find_issue_document'


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_branch('RA', 'RPA1')
        cls.b = make_branch('RB', 'RPA2')
        for branch in (cls.a, cls.b):          # the verifier searches the source branch's server
            branch.db_host = '10.0.0.2'
            branch.save(update_fields=['db_host'])
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
            ('patch', f'/api/rpa/recipes/{rec.id}/'), ('post', '/api/rpa/screens/issue_125/'),
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
        self.assertEqual(self.sup_c.patch(f'/api/rpa/recipes/{rec.id}/', {'header_checklist': ['x']},
                                          format='json').status_code, 403)
        self.assertEqual(self.sup_c.post('/api/rpa/screens/issue_125/', {'enabled': True},
                                         format='json').status_code, 403)
        self.assertEqual(self.sup_c.get('/api/rpa/recipes/').status_code, 200)
        rec.refresh_from_db()
        self.assertEqual(rec.header_checklist, [])
        self.assertFalse(RpaScreen.objects.get(key='issue_125').enabled)


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

    def test_resolve_retry(self):
        job = self._job(status='approved')
        doc = job.documents.first()
        RpaDocument.objects.filter(pk=doc.pk).update(status='needs_person', needs_person_reason='unknown_popup')
        url = f'/api/rpa/documents/{doc.id}/resolve/'
        self.assertEqual(self.sup_c.post(url, {'reason': 'ok'}).status_code, 400)       # no decision
        with mock.patch(FIND, return_value=None):
            r = self.sup_c.post(url, {'decision': 'retry', 'reason': 'ok'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['status'], 'approved')
        self.assertEqual(r.data['reference'], f'RPA-{doc.id}')

    def test_retry_refused_when_softech_already_has_it(self):
        doc = self._job(status='approved').documents.first()
        RpaDocument.objects.filter(pk=doc.pk).update(status='needs_person')
        found = {'docnumber': 91, 'usercode': '', 'cust_branch_code': 'RPA2', 'matched_by': 'reference',
                 'lines': []}
        with mock.patch(FIND, return_value=found):
            r = self.sup_c.post(f'/api/rpa/documents/{doc.id}/resolve/', {'decision': 'retry', 'reason': 'x'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('91', r.data['detail'])
        doc.refresh_from_db()
        self.assertEqual(doc.status, 'needs_person')

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
        rid = r.data['id']
        self.assertEqual(self.adm_c.post(f'/api/rpa/recipes/{rid}/approve/').status_code, 403)  # importer
        # a .dld carries no cancel keys: approving it as is would make every dry run impossible
        refused = self.adm2_c.post(f'/api/rpa/recipes/{rid}/approve/')
        self.assertEqual(refused.status_code, 400)
        self.assertIn('مفاتيح الإلغاء', refused.data['detail'])
        bad = self.adm_c.patch(f'/api/rpa/recipes/{rid}/', {'cancel_keys': [{'kind': 'keys', 'value': '{ESC}'}]},
                               format='json')
        self.assertEqual(bad.status_code, 400)
        edit = self.adm_c.patch(f'/api/rpa/recipes/{rid}/', {
            'cancel_keys': [{'kind': 'keys', 'value': r'\{ESC}'}],
            'popups': [{'title_contains': 'تأكيد', 'text_contains': '', 'answer_keys': r'\{ENTER}'}],
            'header_checklist': ['تأكد من المخزن'], 'ref_cells': []}, format='json')
        self.assertEqual(edit.status_code, 200, edit.content)
        self.assertEqual(edit.data['cancel_keys'], [{'kind': 'keys', 'value': r'\{ESC}'}])
        self.assertEqual(edit.data['header_checklist'], ['تأكد من المخزن'])
        ok = self.adm2_c.post(f'/api/rpa/recipes/{rid}/approve/')
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(ok.data['status'], 'approved')
        frozen = self.adm_c.patch(f'/api/rpa/recipes/{rid}/', {'header_checklist': ['x']}, format='json')
        self.assertEqual(frozen.status_code, 400)

    def test_field_map_names_checked_at_import(self):
        dld = SimpleUploadedFile('t.dld', DLD.encode('utf-8'))
        r = self.adm_c.post('/api/rpa/recipes/', {'screen': 'issue_125', 'field_map': json.dumps(['price']),
                                                  'file': dld}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertIn('price', r.data['detail'])
        self.assertFalse(RpaRecipe.objects.exists())

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
        r = self.sup_c.post('/api/rpa/devices/', {'label': 'PC-1'})
        self.assertEqual(r.status_code, 201, r.content)
        token = r.data['token']
        self.assertGreaterEqual(len(token), 40)
        self.assertNotIn('token_hash', r.data['device'])
        lst = self.sup_c.get('/api/rpa/devices/')
        self.assertNotIn(token, lst.content.decode())
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
        self.assertEqual(self.sup_c.post('/api/rpa/devices/', {'label': ' '}).status_code, 400)
        self.assertFalse(RpaDevice.objects.exists())


class StatusTests(_Base):
    def test_status(self):
        now = timezone.now()
        RpaDevice.objects.create(staff=self.sup, created_by=self.sup, label='on', token_hash='s1',
                                 last_seen_at=now - timedelta(seconds=30))
        RpaDevice.objects.create(staff=self.sup, created_by=self.sup, label='old', token_hash='s2',
                                 last_seen_at=now - timedelta(minutes=5))
        RpaDevice.objects.create(staff=self.sup, created_by=self.sup, label='gone', token_hash='s3',
                                 last_seen_at=now, revoked_at=now)
        with self.settings(RPA_SOFTECH_ENTRY_ENABLED=True, WRITER_INSTANCE=True):
            r = self.sup_c.get('/api/rpa/status/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['switch_on'])
        self.assertEqual(r.data['last_claim_error'], '')
        # the flag alone, off the writer instance: claim_next hands nothing out, so neither does the strip
        with self.settings(RPA_SOFTECH_ENTRY_ENABLED=True, WRITER_INSTANCE=False):
            self.assertFalse(self.sup_c.get('/api/rpa/status/').data['switch_on'])
        self.assertEqual([d['label'] for d in r.data['my_devices_online']], ['on'])
        self.assertEqual(r.data['screens'][0]['key'], 'issue_125')
        with self.settings(RPA_SOFTECH_ENTRY_ENABLED=False):
            self.assertFalse(self.sup_c.get('/api/rpa/status/').data['switch_on'])


class FixRoundTests(_Base):
    def _file(self):
        return SimpleUploadedFile('same.xlsx', _xlsx([['1', 2, None]]).read())

    def test_every_ordering_key_works_and_unknown_is_400(self):
        from apps.rpa import views
        self._job()
        self._recipe('approved')
        RpaDevice.objects.create(staff=self.adm, created_by=self.adm, label='d', token_hash='o1')
        for url, keys in (('jobs', views.JOB_SORT_KEYS), ('recipes', views.RECIPE_SORT_KEYS),
                          ('devices', views.DEVICE_SORT_KEYS)):
            for key in keys:
                for prefix in ('', '-'):
                    r = self.adm_c.get(f'/api/rpa/{url}/?ordering={prefix}{key}')
                    self.assertEqual(r.status_code, 200, (url, prefix + key))
            self.assertEqual(self.adm_c.get(f'/api/rpa/{url}/?ordering=nope').status_code, 400, url)
        self.assertEqual(self.adm_c.get('/api/rpa/recipes/?ordering=created_at').status_code, 400)

    def test_non_string_reason_or_body_is_400(self):
        job = self._job()
        doc = job.documents.first()
        for body in ({'reason': ['x']}, {'reason': {'a': 1}}, {'decision': ['retry'], 'reason': 'x'}):
            if 'decision' not in body:
                r = self.sup2_c.post(f'/api/rpa/jobs/{job.id}/cancel/', body, format='json')
                self.assertEqual(r.status_code, 400, body)
            self.assertEqual(self.sup2_c.post(f'/api/rpa/documents/{doc.id}/resolve/', body,
                                              format='json').status_code, 400, body)
        r = self.sup2_c.post(f'/api/rpa/jobs/{job.id}/cancel/', ['x'], format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.sup2_c.post('/api/rpa/devices/', ['x'], format='json').status_code, 400)
        job.refresh_from_db()
        self.assertEqual(job.status, 'uploaded')

    def test_runtime_fault_is_not_masked_as_bad_file(self):
        with mock.patch('apps.rpa.views.workflow.create_job', side_effect=RuntimeError('db down')):
            with self.assertRaises(RuntimeError):
                self.sup_c.post('/api/rpa/jobs/', {'screen': 'issue_125', 'branch': self.a.id,
                                                   'target_branch': self.b.id, 'file': self._file()},
                                format='multipart')

    def test_duplicate_does_not_leak_other_branch_job_id(self):
        data = {'screen': 'issue_125', 'target_branch': self.a.id}
        first = self.adm_c.post('/api/rpa/jobs/', dict(data, branch=self.b.id, file=self._file()), format='multipart')
        self.assertEqual(first.status_code, 201, first.content)
        r = self.ph_c.post('/api/rpa/jobs/', {'screen': 'issue_125', 'branch': self.a.id,
                                              'target_branch': self.b.id, 'file': self._file()}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertNotIn('job_id', r.data)
        self.assertIn('detail', r.data)
        # in scope: the id is still returned
        again = self.adm_c.post('/api/rpa/jobs/', dict(data, branch=self.b.id, file=self._file()), format='multipart')
        self.assertEqual(again.status_code, 400, again.content)
        self.assertIn('job_id', again.data, again.content)   # CI once lacked it: keep the body in the message
        self.assertEqual(str(again.data['job_id']), str(first.data['id']))


class ScreenTests(_Base):
    def test_admin_enables_screen_and_live_is_refused(self):
        url = '/api/rpa/screens/issue_125/'
        self.assertEqual(self.adm_c.post(url, {'enabled': 'yes'}, format='json').status_code, 400)
        self.assertEqual(self.adm_c.post(url, {'enabled': True, 'live': True}, format='json').status_code, 400)
        self.assertEqual(self.adm_c.post(url, {'live': False}, format='json').status_code, 400)
        self.assertEqual(self.adm_c.post('/api/rpa/screens/stockcount/', {'enabled': True},
                                         format='json').status_code, 400)
        r = self.adm_c.post(url, {'enabled': True}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.data['enabled'], r.data['live']), (True, False))
        self.assertTrue(AuditLog.objects.filter(action='rpa_screen_changed').exists())
        self.assertFalse(RpaScreen.objects.get(key='stockcount').enabled)


class CorruptWorkbookTests(_Base):
    def test_key_error_and_xml_parse_error_are_400(self):
        from xml.etree.ElementTree import ParseError
        for exc in (KeyError('xl/worksheets/sheet1.xml'), ParseError('not well-formed')):
            with mock.patch('apps.rpa.workflow.parse_issue_sheet', side_effect=exc):
                r = self.sup_c.post('/api/rpa/jobs/', {'screen': 'issue_125', 'branch': self.a.id,
                                                       'target_branch': self.b.id,
                                                       'file': _xlsx([['1', 2, None]])}, format='multipart')
            self.assertEqual(r.status_code, 400, exc)
            self.assertNotIn('sheet1', r.content.decode())
