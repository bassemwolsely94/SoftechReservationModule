"""
Platform & abuse — upload size and import size (Batch 6, W-8).

Before: no per-file limit below nginx's 50 MB request cap — any upload field (payment proofs, task
attachments, reservation photos and voice notes, delivery POD, call-centre files) took a 50 MB file;
the Excel / CSV importers read every row of whatever they were given into memory.

Now: every uploaded file is capped by MAX_UPLOAD_FILE_SIZE (default 25 MB) as it streams in
(core.upload_safety.UploadSizeLimitHandler — a too-big file is a 400, nothing is stored), and the
importers stop at MAX_IMPORT_ROWS (default 50,000) with a clear message. Type: W-7's serving
allow-list already makes any odd private file a sandboxed download.
"""
import io
import shutil
import tempfile

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings

from apps.tests.factories import make_admin, make_item


def _xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile('rows.xlsx', buf.getvalue())


class UploadSizeTests(TestCase):

    def setUp(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        o = override_settings(MEDIA_ROOT=root)
        o.enable()
        self.addCleanup(o.disable)
        _, _, self.c = make_admin('w8_admin')
        self.item = make_item()

    @override_settings(MAX_UPLOAD_FILE_SIZE=200_000)
    def test_a_file_over_the_cap_is_refused_and_not_stored(self):
        from apps.product_experience.models import ProductMedia
        big = SimpleUploadedFile('big.pdf', b'%PDF-1.4\n' + b'0' * 300_000, content_type='application/pdf')
        r = self.c.post(f'/api/products/{self.item.softech_id}/media/upload/',
                        {'file': big, 'media_type': 'pdf'}, format='multipart')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(ProductMedia.objects.exists())

    @override_settings(MAX_UPLOAD_FILE_SIZE=200_000)
    def test_a_file_under_the_cap_is_taken(self):
        ok = SimpleUploadedFile('ok.pdf', b'%PDF-1.4\n' + b'0' * 1000, content_type='application/pdf')
        r = self.c.post(f'/api/products/{self.item.softech_id}/media/upload/',
                        {'file': ok, 'media_type': 'pdf'}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)


@override_settings(MAX_IMPORT_ROWS=10)
class ImportRowCapTests(SimpleTestCase):

    def test_supply_import_stops_at_the_cap(self):
        from apps.supply.views import _read_tabular
        with self.assertRaises(ValueError):
            _read_tabular(_xlsx([['code', 'qty']] + [[i, 1] for i in range(20)]))
        self.assertEqual(len(_read_tabular(_xlsx([['code', 'qty']] + [[i, 1] for i in range(5)]))), 6)

    def test_discount_import_stops_at_the_cap(self):
        from apps.discount_approvals.views import _parse_import_file
        rows, err = _parse_import_file(_xlsx([['code', 'pct']] + [[i, 5] for i in range(20)]))
        self.assertIsNone(rows)
        self.assertIn('10', err)
