"""The whole Stage 1 chain through the real HTTP APIs, as the owner's first dry run will walk it.

admin imports a .dld → admin sets its cancel keys on the draft → a second admin approves it →
admin enables the screen → a supervisor uploads the sheet and registers a device → a second
supervisor approves the job → the device claims → reports dry_run_ok; then a second document
goes to a person and the uploader settles it from the staff API.

Only SOFTECH is faked (find_issue_document → None): nothing here may reach a real server.
"""
import io
import json
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import Workbook
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.rpa.models import RpaDocument, RpaRun
from apps.tests.factories import make_branch, make_item, make_user

FIND = 'apps.rpa.dispatch.find_issue_document'
ON = dict(WRITER_INSTANCE=True, RPA_SOFTECH_ENTRY_ENABLED=True)
# DataLoad stores special keys as \{KEY}; columns: item code, TAB, qty, ENTER
DLD = ('begindelays\nCellDelay=0.2\nFormDelay=0.25\nenddelays\n'
       'beginheader\nData\tKey Strokes\tData\tKey Strokes\nendheader\n'
       'beginother\nWindow=إذن صرف لفرع\nendother\n'
       'begindata\n52001\t\\{TAB}\t2\t\\{ENTER}\nenddata\n')


def _sheet(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(['كود الصنف', 'الكمية', 'تاريخ الصلاحية'])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile('issue.xlsx', buf.getvalue())


@override_settings(**ON)
class StageOneChainTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.src = make_branch('فرع المصدر', 'E2EA')
        cls.dst = make_branch('فرع المستلم', 'E2EB')
        cls.src.db_host = '10.0.0.3'
        cls.src.save(update_fields=['db_host'])
        _, cls.adm, cls.adm_c = make_user('e2e_adm', role='admin', branch=cls.src)
        _, cls.adm2, cls.adm2_c = make_user('e2e_adm2', role='admin', branch=cls.src)
        _, cls.up, cls.up_c = make_user('e2e_up', role='supervisor', branch=cls.src)
        _, cls.ap, cls.ap_c = make_user('e2e_ap', role='supervisor', branch=cls.src)
        make_item('صنف أ', '52001')
        make_item('صنف ب', '52002')

    def setUp(self):
        p = mock.patch(FIND, return_value=None)
        self.find = p.start()
        self.addCleanup(p.stop)

    def ok(self, resp, code=200):
        self.assertEqual(resp.status_code, code, resp.content.decode()[:500])
        return resp.data

    def _setup_recipe_and_screen(self):
        rec = self.ok(self.adm_c.post('/api/rpa/recipes/', {
            'screen': 'issue_125', 'field_map': json.dumps(['itemcode', 'qty']),
            'file': SimpleUploadedFile('issue.dld', DLD.encode('utf-8'))}, format='multipart'), 201)
        self.ok(self.adm_c.patch(f'/api/rpa/recipes/{rec["id"]}/', {
            'cancel_keys': [{'kind': 'keys', 'value': r'\{ESC}'}],
            'popups': [{'title_contains': 'تأكيد', 'text_contains': 'إلغاء', 'answer_keys': r'\{ENTER}'}],
            'header_checklist': ['المخزن الرئيسي مختار']}, format='json'))
        self.assertEqual(self.ok(self.adm2_c.post(f'/api/rpa/recipes/{rec["id"]}/approve/'))['status'], 'approved')
        self.assertTrue(self.ok(self.adm_c.post('/api/rpa/screens/issue_125/', {'enabled': True},
                                                format='json'))['enabled'])

    def _upload_and_approve(self, rows, name):
        upload = _sheet(rows)
        upload.name = name
        job = self.ok(self.up_c.post('/api/rpa/jobs/', {
            'screen': 'issue_125', 'branch': self.src.id, 'target_branch': self.dst.id, 'file': upload},
            format='multipart'), 201)
        self.assertEqual(self.up_c.post(f'/api/rpa/jobs/{job["id"]}/approve/').status_code, 403)  # four eyes
        job = self.ok(self.ap_c.post(f'/api/rpa/jobs/{job["id"]}/approve/'))
        self.assertEqual(job['status'], 'approved')
        return job['documents'][0]

    def test_upload_approve_claim_dry_run_then_person_resolves(self):
        self._setup_recipe_and_screen()
        token = self.ok(self.up_c.post('/api/rpa/devices/', {'label': 'جهاز المخزن'}), 201)['token']
        agent = APIClient()
        agent.credentials(HTTP_X_ELR_RPA_AGENT=token)

        # ── document 1: dry run succeeds ──
        doc = self._upload_and_approve([['52001', 2, None]], 'a.xlsx')
        self.assertEqual(doc['reference'], f'RPA-{doc["id"]}')
        claim = self.ok(agent.post('/api/rpa/agent/claim/'))
        self.assertEqual((claim['mode'], claim['keyplan']['document']), ('dry_run', doc['id']))
        steps = claim['keyplan']['steps']
        self.assertEqual(steps[0]['send'], '52001{TAB}2{ENTER}')
        self.assertEqual((steps[-1]['send'], steps[-1]['final']), ('{ESC}', True))
        self.assertIn('المخزن الرئيسي مختار', claim['keyplan']['checklist'])
        self.ok(agent.post(f'/api/rpa/agent/documents/{doc["id"]}/heartbeat/'))
        report = self.ok(agent.post(f'/api/rpa/agent/documents/{doc["id"]}/report/', {
            'run_id': claim['run_id'], 'mode': 'dry_run', 'outcome': 'dry_run_ok',
            'steps': [{'i': 1, 'label': 'سطر 1', 'ok': True}]}, format='json'))
        self.assertEqual(report['status'], 'dry_run_ok')
        detail = self.ok(self.up_c.get(f'/api/rpa/documents/{doc["id"]}/'))
        self.assertEqual((detail['status'], detail['runs'][0]['outcome']), ('dry_run_ok', 'dry_run_ok'))
        self.assertEqual(self.find.call_count, 2)            # before typing, and after the dry run
        self.assertEqual(agent.post('/api/rpa/agent/claim/').status_code, 204)

        # ── document 2: the robot meets an unknown popup → a person decides ──
        doc2 = self._upload_and_approve([['52002', 1, None]], 'b.xlsx')
        claim2 = self.ok(agent.post('/api/rpa/agent/claim/'))
        self.ok(agent.post(f'/api/rpa/agent/documents/{doc2["id"]}/report/', {
            'run_id': claim2['run_id'], 'mode': 'dry_run', 'outcome': 'unknown_popup', 'steps': []},
            format='json'))
        detail = self.ok(self.up_c.get(f'/api/rpa/documents/{doc2["id"]}/'))
        self.assertEqual((detail['status'], detail['needs_person_reason']), ('needs_person', 'unknown_popup'))
        resolve = f'/api/rpa/documents/{doc2["id"]}/resolve/'
        self.assertEqual(self.up_c.post(resolve, {'reason': 'راجعت'}).status_code, 400)   # no decision
        settled = self.ok(self.up_c.post(resolve, {'decision': 'retry', 'reason': 'أغلقت النافذة'}))
        self.assertEqual(settled['status'], 'approved')
        claim3 = self.ok(agent.post('/api/rpa/agent/claim/'))
        self.assertEqual(claim3['keyplan']['document'], doc2['id'])
        self.assertEqual(RpaRun.objects.filter(document_id=doc2['id']).count(), 2)
        for action in ('rpa_recipe_imported', 'rpa_recipe_edited', 'rpa_recipe_approved', 'rpa_screen_changed',
                       'rpa_job_uploaded', 'rpa_job_approved', 'rpa_document_claimed', 'rpa_run_reported',
                       'rpa_document_needs_person', 'rpa_document_resolved'):
            self.assertTrue(AuditLog.objects.filter(action=action).exists(), action)

    def test_cancel_job_from_staff_api_needs_reason(self):
        self._setup_recipe_and_screen()
        doc = self._upload_and_approve([['52001', 3, None]], 'c.xlsx')
        job_id = RpaDocument.objects.get(pk=doc['id']).job_id
        self.assertEqual(self.ap_c.post(f'/api/rpa/jobs/{job_id}/cancel/', {}).status_code, 400)
        job = self.ok(self.ap_c.post(f'/api/rpa/jobs/{job_id}/cancel/', {'reason': 'الملف خطأ'}))
        self.assertEqual((job['status'], job['documents'][0]['status']), ('cancelled', 'cancelled'))
