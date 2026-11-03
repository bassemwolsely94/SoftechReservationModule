"""N5 / Task 4 - every export is audited; Excel and Word files are stamped."""
import io
import zipfile
from types import SimpleNamespace

import openpyxl
from django.core.cache import cache
from django.http import HttpResponse, StreamingHttpResponse
from django.test import RequestFactory, TestCase, override_settings

from apps.access.devices import DeviceInfo
from apps.access.export_middleware import ExportAuditMiddleware
from apps.access.network import NetworkInfo
from apps.audit.models import AuditLog
from apps.tests.factories import make_user
from core.export_stamp import ExportMark, stamp_ooxml

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
STAMPED = ('docProps/core.xml', 'docProps/custom.xml', '_rels/.rels', '[Content_Types].xml')


def _workbook_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws['A1'] = 'صنف'
    ws['B1'] = 12.5
    ws['A2'] = 'Panadol'
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


MARK = ExportMark(export_id='ex123abc', username='stamp_user', at='2026-11-03T10:00:00+02:00',
                  device='Front desk (dev-1)', zone='Z1', ip='10.0.0.5')


class StampTests(TestCase):

    def test_stamp_roundtrip_opens_and_keeps_cells(self):
        out = stamp_ooxml(_workbook_bytes(), MARK)
        wb = openpyxl.load_workbook(io.BytesIO(out))
        ws = wb.active
        self.assertEqual((ws['A1'].value, ws['B1'].value, ws['A2'].value),
                         ('صنف', 12.5, 'Panadol'))
        self.assertEqual(wb.properties.creator, 'stamp_user')
        self.assertEqual(wb.properties.lastModifiedBy, 'stamp_user')
        self.assertIn('ex123abc', wb.properties.keywords)
        self.assertIn('تصدير ex123abc', wb.properties.description)
        self.assertEqual(wb.custom_doc_props['ElR-ExportId'].value, 'ex123abc')
        self.assertEqual(wb.custom_doc_props['ElR-IP'].value, '10.0.0.5')

    def test_stamp_keeps_other_members_identical(self):
        src = _workbook_bytes()
        out = stamp_ooxml(src, MARK)
        zin, zout = zipfile.ZipFile(io.BytesIO(src)), zipfile.ZipFile(io.BytesIO(out))
        for name in zin.namelist():
            if name in STAMPED:
                continue
            self.assertEqual(zin.read(name), zout.read(name), name)
        self.assertIn('docProps/custom.xml', zout.namelist())

    def test_stamp_twice_replaces_custom(self):
        once = stamp_ooxml(_workbook_bytes(), MARK)
        twice = stamp_ooxml(once, ExportMark('second', 'u2', MARK.at, '', 'Z2', ''))
        wb = openpyxl.load_workbook(io.BytesIO(twice))
        self.assertEqual(wb.custom_doc_props['ElR-ExportId'].value, 'second')
        z = zipfile.ZipFile(io.BytesIO(twice))
        self.assertEqual(z.read('_rels/.rels').count(b'custom-properties'), 1)
        self.assertEqual(z.read('[Content_Types].xml').count(b'/docProps/custom.xml'), 1)

    def test_non_zip_raises_value_error(self):
        with self.assertRaises(ValueError):
            stamp_ooxml(b'not a zip', MARK)


class ExportMiddlewareTests(TestCase):

    def setUp(self):
        cache.clear()
        self.rf = RequestFactory()
        self.user, self.profile, _ = make_user('exp_user', role='supervisor')

    def _call(self, view, path='/api/customers/export/', user=True, **kw):
        req = self.rf.get(path, **kw)
        req.user = self.user if user else SimpleNamespace(is_authenticated=False)
        req.access = SimpleNamespace(
            zone='Z1', user_id=self.user.pk if user else None,
            device=DeviceInfo(public_id='dev-1', status='approved', name='Front desk', kind='pc'),
            network=NetworkInfo(zone='internal', ip='10.0.0.5', site=None))
        return ExportAuditMiddleware(view)(req)

    def _rows(self):
        return list(AuditLog.objects.filter(action='export_taken'))

    def test_xlsx_export_audited_and_stamped(self):
        body = _workbook_bytes()
        r = self._call(lambda req: HttpResponse(body, content_type=XLSX))
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        export_id = r['X-ElR-Export-Id']
        extra = rows[0].extra
        self.assertEqual(extra['export_id'], export_id)
        self.assertEqual(extra['zone'], 'Z1')
        self.assertEqual(extra['device_id'], 'dev-1')
        self.assertEqual(extra['ip'], '10.0.0.5')
        self.assertEqual(extra['path'], '/api/customers/export/')
        self.assertEqual(extra['bytes'], len(body))
        self.assertEqual(rows[0].user, self.profile)
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.custom_doc_props['ElR-ExportId'].value, export_id)
        self.assertEqual(wb.properties.creator, 'exp_user')
        self.assertEqual(int(r['Content-Length']), len(r.content))

    def test_corrupt_xlsx_passes_through(self):
        with self.assertLogs('elrezeiky.access', 'WARNING'):
            r = self._call(lambda req: HttpResponse(b'not a zip', content_type=XLSX))
        self.assertEqual(r.content, b'not a zip')
        self.assertEqual(len(self._rows()), 1)

    def test_streaming_export_audited_not_stamped(self):
        body = _workbook_bytes()
        r = self._call(lambda req: StreamingHttpResponse(iter([body]), content_type=XLSX))
        self.assertEqual(b''.join(r.streaming_content), body)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0].extra['bytes'])
        self.assertTrue(r['X-ElR-Export-Id'])

    @override_settings(EXPORT_STAMP_MAX_BYTES=10)
    def test_oversize_export_not_stamped(self):
        body = _workbook_bytes()
        r = self._call(lambda req: HttpResponse(body, content_type=XLSX))
        self.assertEqual(r.content, body)
        self.assertEqual(len(self._rows()), 1)

    def test_csv_export_audited_body_unchanged(self):
        def view(req):
            resp = HttpResponse(b'a,b\n1,2\n', content_type='text/csv')
            resp['Content-Disposition'] = 'attachment; filename="x.csv"'
            return resp
        r = self._call(view, path='/api/customers/list/')
        self.assertEqual(r.content, b'a,b\n1,2\n')
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].extra['content_type'], 'text/csv')

    def test_non_export_response_not_audited(self):
        r = self._call(lambda req: HttpResponse('{}', content_type='application/json'),
                       path='/api/customers/')
        self.assertFalse(r.has_header('X-ElR-Export-Id'))
        self.assertEqual(self._rows(), [])

    def test_failed_export_status_not_audited(self):
        self._call(lambda req: HttpResponse('no', status=403), path='/api/customers/export/')
        self.assertEqual(self._rows(), [])

    def test_anonymous_skipped(self):
        r = self._call(lambda req: HttpResponse(_workbook_bytes(), content_type=XLSX), user=False)
        self.assertFalse(r.has_header('X-ElR-Export-Id'))
        self.assertEqual(self._rows(), [])
