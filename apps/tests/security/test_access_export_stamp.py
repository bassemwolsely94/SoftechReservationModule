"""N5 / Task 4 - every export is audited; Excel and Word files are stamped."""
import io
import json
import zipfile
from types import SimpleNamespace
from unittest import mock

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
                  device='dev-1', zone='Z1')


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
        self.assertEqual(wb.custom_doc_props['ElR-Device'].value, 'dev-1')
        self.assertNotIn('ElR-IP', wb.custom_doc_props.names)

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
        twice = stamp_ooxml(once, ExportMark('second', 'u2', MARK.at, '', 'Z2'))
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

    def _call(self, view, path='/api/customers/export/', user=True, method='get',
              device_name='Front desk', **kw):
        req = getattr(self.rf, method)(path, **kw)
        req.user = self.user if user else SimpleNamespace(is_authenticated=False)
        req.access = SimpleNamespace(
            zone='Z1', user_id=self.user.pk if user else None,
            device=DeviceInfo(public_id='dev-1', status='approved', name=device_name, kind='pc'),
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

    def test_file_carries_no_ip_and_no_device_name(self):
        """Final review I2: files go to suppliers / insurers. The device appears by public_id only
        (its name carries the employee's name) and the IP not at all; both stay in the audit row."""
        r = self._call(lambda req: HttpResponse(_workbook_bytes(), content_type=XLSX),
                       device_name='Ahmed Front desk')
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        props = {p.name: p.value for p in wb.custom_doc_props.props}
        self.assertEqual(set(props), {'ElR-ExportId', 'ElR-User', 'ElR-At', 'ElR-Device', 'ElR-Zone'})
        self.assertEqual(props['ElR-Device'], 'dev-1')
        self.assertEqual(props['ElR-Zone'], 'Z1')
        package = zipfile.ZipFile(io.BytesIO(r.content))
        for part in ('docProps/core.xml', 'docProps/custom.xml'):
            xml = package.read(part).decode('utf-8')
            self.assertNotIn('10.0.0.5', xml, part)
            self.assertNotIn('Ahmed', xml, part)
        extra = self._rows()[0].extra
        self.assertEqual((extra['ip'], extra['device_name'], extra['device_id']),
                         ('10.0.0.5', 'Ahmed Front desk', 'dev-1'))

    def test_default_stamp_limit_is_20_mb(self):
        from django.conf import settings
        from apps.access import export_middleware
        self.assertEqual(settings.EXPORT_STAMP_MAX_BYTES, 20 * 1024 * 1024)
        self.assertEqual(export_middleware.DEFAULT_MAX_BYTES, 20 * 1024 * 1024)

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

    # fix round 1
    def test_head_and_304_not_audited(self):
        def view(req):
            resp = HttpResponse(b'', content_type=XLSX, status=304 if req.method == 'GET' else 200)
            resp['Content-Disposition'] = 'attachment; filename="x.xlsx"'
            return resp
        self._call(view, method='head')
        self._call(view)
        self.assertEqual(self._rows(), [])

    def test_inline_attachment_named_file_not_audited(self):
        def view(req):
            resp = HttpResponse(b'%PDF', content_type='application/pdf')
            resp['Content-Disposition'] = 'inline; filename="attachment.pdf"'
            return resp
        r = self._call(view, path='/api/customers/1/')
        self.assertFalse(r.has_header('X-ElR-Export-Id'))
        self.assertEqual(self._rows(), [])

    def test_control_character_username_stamps_and_roundtrips(self):
        bad = 'ab' + chr(1) + 'c' + chr(0x1f)
        mark = ExportMark('ex9', bad, MARK.at, 'dev' + chr(0x0b), 'Z1')
        wb = openpyxl.load_workbook(io.BytesIO(stamp_ooxml(_workbook_bytes(), mark)))
        self.assertEqual(wb.properties.creator, 'abc')
        self.assertEqual(wb.custom_doc_props['ElR-User'].value, 'abc')
        self.assertEqual(wb.custom_doc_props['ElR-Device'].value, 'dev')

    def test_device_without_name_labelled_by_public_id(self):
        r = self._call(lambda req: HttpResponse(_workbook_bytes(), content_type=XLSX),
                       device_name='')
        wb = openpyxl.load_workbook(io.BytesIO(r.content))
        self.assertEqual(wb.custom_doc_props['ElR-Device'].value, 'dev-1')

    def test_body_selected_export_audited(self):
        def view(req):
            req.body            # the view consumes the body, as DRF does
            return HttpResponse('{}', content_type='application/json')
        r = self._call(view, path='/api/reservations/bulk/', method='post',
                       data=json.dumps({'action': 'export', 'ids': [1]}),
                       content_type='application/json')
        self.assertTrue(r['X-ElR-Export-Id'])
        self.assertEqual(len(self._rows()), 1)
        self._call(view, path='/api/reservations/bulk/', method='post',
                   data=json.dumps({'action': 'cancel'}), content_type='application/json')
        self.assertEqual(len(self._rows()), 1)

    def test_audit_failure_on_every_alias_returns_response_unchanged(self):
        def view(req):
            resp = HttpResponse(b'a,b\n', content_type='text/csv')
            resp['Content-Disposition'] = 'attachment; filename="x.csv"'
            return resp
        with mock.patch('apps.audit.models.AuditLog.log', side_effect=RuntimeError('db down')), \
                mock.patch('apps.access.softech_gate._audit_aliases',
                           return_value=('audit_log', 'default')), \
                self.assertLogs('elrezeiky.access', 'WARNING') as cm:
            r = self._call(view, path='/api/customers/list/')
        self.assertEqual((r.status_code, r.content), (200, b'a,b\n'))
        self.assertTrue(any('export audit row lost' in line for line in cm.output))
        self.assertEqual(self._rows(), [])

    def test_ws_and_export_share_the_audit_helper(self):
        from apps.access import ws
        with mock.patch('apps.access.audit.write_access_audit', return_value=True) as m:
            self.assertTrue(ws._write_audit(self.user.pk, 'n', {}))
        m.assert_called_once_with('ws_zone_denied', self.user.pk, 'n', {}, label='ws')

    def test_anonymous_skipped(self):
        r = self._call(lambda req: HttpResponse(_workbook_bytes(), content_type=XLSX), user=False)
        self.assertFalse(r.has_header('X-ElR-Export-Id'))
        self.assertEqual(self._rows(), [])
