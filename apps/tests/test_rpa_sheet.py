import datetime
import io
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.rpa import workflow
from apps.rpa.models import RpaDocument, RpaJob, RpaLine, RpaScreen
from apps.rpa.sheet import build_lines, parse_issue_sheet
from apps.tests.factories import make_branch, make_item
from apps.users.models import StaffProfile


def _xlsx(headers, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


HEAD = ['كود الصنف', 'الكمية', 'تاريخ الصلاحية']


def _doc():
    user = get_user_model().objects.create_user(username='rpa_t4_doc', password='x')
    staff = StaffProfile.objects.get_or_create(user=user, defaults={'role': 'admin'})[0]
    job = RpaJob.objects.create(screen=RpaScreen.objects.get(key='issue_125'),
                                branch=make_branch('A', 'T4A'), created_by=staff)
    return RpaDocument.objects.create(job=job, seq=1)


class SheetParseTests(TestCase):
    def test_arabic_headers_and_blank_rows(self):
        data = _xlsx(HEAD, [['100', 5, '1/5/25'], ['101', 2, None], ['102', 1, None],
                            [None, None, None], [None, None, None], [None, None, None], [None, None, None]])
        rows = parse_issue_sheet(data, 'x.xlsx')
        self.assertEqual(len(rows), 3)
        self.assertEqual([r['itemcode'] for r in rows], ['100', '101', '102'])
        self.assertEqual(rows[0]['row_no'], 2)

    def test_english_aliases(self):
        rows = parse_issue_sheet(_xlsx(['Item Code', 'Qty', 'Exp'], [['7', 1, None]]), 'x.xlsx')
        self.assertEqual(rows[0]['itemcode'], '7')

    def test_qty_and_code_normalisation(self):
        make_item('x', '52')
        doc = _doc()
        build_lines(doc, [
            {'row_no': 2, 'itemcode': '52.0', 'qty': '5', 'expiry': None},
            {'row_no': 3, 'itemcode': ' 52 ', 'qty': 5.0, 'expiry': None},
        ])
        lines = list(doc.lines.all())
        self.assertEqual([ln.itemcode for ln in lines], ['52', '52'])
        self.assertEqual([ln.qty for ln in lines], [Decimal('5'), Decimal('5')])
        self.assertTrue(all(ln.status == 'matched' and ln.item for ln in lines))

    def test_bad_qty_is_error(self):
        make_item('x', '53')
        doc = _doc()
        build_lines(doc, [{'row_no': 2, 'itemcode': '53', 'qty': '0', 'expiry': None},
                          {'row_no': 3, 'itemcode': '53', 'qty': 'abc', 'expiry': None}])
        self.assertEqual([ln.status for ln in doc.lines.all()], ['error', 'error'])

    def test_out_of_range_qty_is_error_not_crash(self):
        make_item('x', '56')
        doc = _doc()
        build_lines(doc, [{'row_no': 2, 'itemcode': '56', 'qty': '1e20', 'expiry': None},
                          {'row_no': 3, 'itemcode': '56', 'qty': '1.123456', 'expiry': None},
                          {'row_no': 4, 'itemcode': '56', 'qty': '12345678', 'expiry': None},
                          {'row_no': 5, 'itemcode': '56', 'qty': '1.50000', 'expiry': None}])
        ln = list(doc.lines.all())
        self.assertEqual([x.status for x in ln], ['error', 'error', 'error', 'matched'])
        self.assertEqual(ln[0].message, 'الكمية غير صالحة')

    def test_expiry_formats(self):
        make_item('x', '54')
        doc = _doc()
        build_lines(doc, [
            {'row_no': 2, 'itemcode': '54', 'qty': '1', 'expiry': datetime.datetime(2026, 3, 1)},
            {'row_no': 3, 'itemcode': '54', 'qty': '1', 'expiry': '1/5/25'},
            {'row_no': 4, 'itemcode': '54', 'qty': '1', 'expiry': '1/5/2025'},
            {'row_no': 5, 'itemcode': '54', 'qty': '1', 'expiry': 'abc'},
        ])
        ln = list(doc.lines.all())
        self.assertEqual(ln[0].expiry, datetime.date(2026, 3, 1))
        self.assertEqual(ln[1].expiry, datetime.date(2025, 5, 1))
        self.assertEqual(ln[2].expiry, datetime.date(2025, 5, 1))
        self.assertEqual(ln[3].status, 'error')
        self.assertEqual(ln[3].message, 'تاريخ صلاحية غير مفهوم')

    def test_duplicate_rows_kept_with_warning(self):
        make_item('x', '55')
        doc = _doc()
        build_lines(doc, [{'row_no': 2, 'itemcode': '55', 'qty': '1', 'expiry': '1/5/25'},
                          {'row_no': 3, 'itemcode': '55', 'qty': '2', 'expiry': '1/5/25'}])
        ln = list(doc.lines.all())
        self.assertEqual(len(ln), 2)
        self.assertEqual(ln[0].warning, '')
        self.assertEqual(ln[1].warning, 'صنف مكرر في الملف')

    def test_unknown_code_unmatched(self):
        doc = _doc()
        build_lines(doc, [{'row_no': 2, 'itemcode': '999999', 'qty': '1', 'expiry': None}])
        line = doc.lines.get()
        self.assertEqual((line.status, line.message, line.item), ('unmatched', 'كود غير موجود', None))


class CreateJobTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username='rpa_t4', password='x')
        self.staff = StaffProfile.objects.get_or_create(user=user, defaults={'role': 'admin'})[0]
        self.a = make_branch('أ', 'T4A')
        self.b = make_branch('ب', 'T4B')
        make_item('x', '60')

    def _up(self, qty=1):
        return SimpleUploadedFile('s.xlsx', _xlsx(HEAD, [['60', qty, None]]))

    def _create(self, **kw):
        args = dict(profile=self.staff, screen_key='issue_125', branch=self.a, target_branch=self.b,
                    store_code='1', upload=self._up())
        args.update(kw)
        return workflow.create_job(**args)

    def test_creates_job_document_lines_audit(self):
        job = self._create()
        self.assertEqual(job.status, 'uploaded')
        self.assertEqual(job.filename, 's.xlsx')
        self.assertEqual(len(job.upload_sha256), 64)
        self.assertEqual(job.documents.get().seq, 1)
        self.assertEqual(RpaLine.objects.filter(document__job=job).count(), 1)
        self.assertTrue(AuditLog.objects.filter(action='rpa_job_uploaded', object_id=str(job.pk)).exists())

    def test_same_file_twice_refused(self):
        job = self._create()
        with self.assertRaises(ValidationError) as ctx:
            self._create()
        self.assertEqual(str(ctx.exception.detail['job_id']), str(job.pk))
        job.status = 'cancelled'
        job.save()
        self._create()   # cancelled jobs do not block a re-upload

    def test_branch_110_and_same_target_refused(self):
        with self.assertRaises(ValidationError):
            self._create(target_branch=self.a)
        b110 = make_branch('مغلق', '110')
        with self.assertRaises(ValidationError):
            self._create(branch=b110)
        self.assertEqual(RpaJob.objects.count(), 0)

    def test_target_branch_110_or_missing_refused(self):
        b110 = make_branch('مغلق', '110')
        with self.assertRaises(ValidationError):
            self._create(target_branch=b110)
        with self.assertRaises(ValidationError):
            self._create(target_branch=None)
        self.assertEqual(RpaJob.objects.count(), 0)

    def test_create_takes_screen_lock(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            self._create()
        self.assertTrue(any('FOR UPDATE' in q['sql'] and 'rpa_rpascreen' in q['sql'] for q in ctx.captured_queries))

    def test_out_of_scope_branch_refused(self):
        user = get_user_model().objects.create_user(username='rpa_t4_sp', password='x')
        sp = StaffProfile.objects.get_or_create(user=user, defaults={'role': 'salesperson'})[0]
        sp.branch = self.b
        sp.save()
        with self.assertRaises(PermissionDenied):
            self._create(profile=sp)
