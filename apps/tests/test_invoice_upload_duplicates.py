"""
Data Lifecycle Stage 4, Task 3: uploading the same invoice file again shows a calm notice
(200 {'duplicate_of': ...}) and saves nothing, unless the user continues with allow_duplicate=1.
OCR / ingest start-up is stubbed; the scan is stored byte for byte.
"""
import hashlib
import shutil
import tempfile
from io import StringIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.invoices.models import InvoiceBatch, SupplierInvoice
from .factories import make_admin, make_branch, make_user

PDF_A = b'%PDF-1.4 first invoice scan \x00\x01\x02\xff'
PDF_B = b'%PDF-1.4 a different scan \x00\x09'
INV_URL = '/api/invoices/invoices/'
BATCH_URL = '/api/invoices/invoice-batches/'


def pdf(data, name='scan.pdf'):
    return SimpleUploadedFile(name, data, content_type='application/pdf')


class UploadDuplicateTests(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp(prefix='inv_dup_media_')
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        ov = override_settings(MEDIA_ROOT=media)
        ov.enable()
        self.addCleanup(ov.disable)
        call_command('seed_permissions', verbosity=0)
        self.user, self.profile, self.client = make_admin('dup_admin')
        self.br = make_branch()
        p1 = mock.patch('apps.invoices.views.SupplierInvoiceViewSet._run_ocr_async')
        p2 = mock.patch('apps.invoices.ingest.start_async')
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def _post_invoice(self, data=PDF_A, **extra):
        body = {'branch': self.br.pk, 'source_image': pdf(data), **extra}
        return self.client.post(INV_URL, body, format='multipart')

    def _post_batch(self, data=PDF_A, **extra):
        body = {'branch': self.br.pk, 'source_file': pdf(data), **extra}
        return self.client.post(BATCH_URL, body, format='multipart')

    def test_repeat_invoice_file_shows_notice_and_saves_nothing(self):
        first = self._post_invoice()
        self.assertEqual(first.status_code, 201, first.content)
        second = self._post_invoice()
        self.assertEqual(second.status_code, 200, second.content)
        dup = second.json()['duplicate_of']
        self.assertEqual(dup['kind'], 'invoice')
        self.assertEqual(dup['id'], first.json()['id'])
        self.assertEqual(SupplierInvoice.objects.count(), 1)

    def test_continue_creates_with_allow_duplicate(self):
        self._post_invoice()
        r = self._post_invoice(allow_duplicate='1')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(SupplierInvoice.objects.count(), 2)

    def test_different_file_creates_normally(self):
        self._post_invoice(PDF_A)
        r = self._post_invoice(PDF_B)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(SupplierInvoice.objects.count(), 2)

    def test_batch_repeat_and_cross_kind(self):
        self.assertEqual(self._post_invoice().status_code, 201)
        r = self._post_batch()
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['duplicate_of']['kind'], 'invoice')
        self.assertEqual(InvoiceBatch.objects.count(), 0)
        b = self._post_batch(PDF_B)
        self.assertEqual(b.status_code, 201, b.content)
        again = self._post_batch(PDF_B)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()['duplicate_of']['kind'], 'batch')
        self.assertEqual(again.json()['duplicate_of']['id'], b.json()['id'])

    def test_invoice_scan_stored_byte_for_byte(self):
        r = self._post_invoice()
        inv = SupplierInvoice.objects.get(pk=r.json()['id'])
        with inv.source_image.open('rb') as fh:
            self.assertEqual(fh.read(), PDF_A)

    def test_hash_stored(self):
        r = self._post_invoice()
        inv = SupplierInvoice.objects.get(pk=r.json()['id'])
        self.assertEqual(inv.source_sha256, hashlib.sha256(PDF_A).hexdigest())
        b = self._post_batch(PDF_B)
        self.assertEqual(InvoiceBatch.objects.get(pk=b.json()['id']).source_sha256,
                         hashlib.sha256(PDF_B).hexdigest())

    def test_backfill_dry_run_changes_nothing_apply_fills(self):
        plain = SupplierInvoice.objects.create(branch=self.br, supplier_name='S', source_image=pdf(PDF_A))
        batch = InvoiceBatch.objects.create(branch=self.br, source_file=pdf(PDF_B))
        child = SupplierInvoice.objects.create(branch=self.br, supplier_name='C', batch=batch,
                                               source_image=pdf(b'%PDF-1.4 page'))
        call_command('backfill_upload_hashes', stdout=StringIO())
        for o in (plain, batch, child):
            o.refresh_from_db()
            self.assertEqual(o.source_sha256, '')
        call_command('backfill_upload_hashes', '--apply', stdout=StringIO())
        for o in (plain, batch, child):
            o.refresh_from_db()
        self.assertEqual(plain.source_sha256, hashlib.sha256(PDF_A).hexdigest())
        self.assertEqual(batch.source_sha256, hashlib.sha256(PDF_B).hexdigest())
        self.assertEqual(child.source_sha256, '')

    def test_no_file_no_check(self):
        r1 = self.client.post(INV_URL, {'branch': self.br.pk}, format='multipart')
        r2 = self.client.post(INV_URL, {'branch': self.br.pk}, format='multipart')
        self.assertEqual((r1.status_code, r2.status_code), (201, 201))
        self.assertEqual(SupplierInvoice.objects.count(), 2)

    def test_permission_unchanged(self):
        _u, _p, client = make_user('dup_nobody', role='delivery')
        r = client.post(INV_URL, {'branch': self.br.pk, 'source_image': pdf(PDF_A)}, format='multipart')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(SupplierInvoice.objects.count(), 0)
