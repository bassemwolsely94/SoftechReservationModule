"""
Data lifecycle Stage 4, Task 4: the bundle page images (invoice_bundles/pages/batch_<id>/) are used only while a
bundle is being processed. After that nothing reads them: the batch and its invoices open without the folder,
reprocess renders again from the bundle's own source file, and only ingest (plus the model that names the
upload folder and the lifecycle app) touches that folder. These tests pin that finding so the bundle_pages
rule can be switched on knowing it.
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.invoices import ingest
from apps.invoices.models import InvoiceBatch, SupplierInvoice
from .factories import make_admin, make_branch

BATCH_URL = '/api/invoices/invoice-batches/'
INV_URL = '/api/invoices/invoices/'
# Files that may name the pages folder: the writer/reader, the model (upload_to) and the lifecycle app.
ALLOWED = ('apps/invoices/ingest.py', 'apps/invoices/models.py', 'apps/data_lifecycle/')


class BundlePagesCase(TestCase):
    def setUp(self):
        self.media = Path(tempfile.mkdtemp(prefix='bundle_pages_media_')).resolve()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        ov = override_settings(MEDIA_ROOT=self.media)
        ov.enable()
        self.addCleanup(ov.disable)
        call_command('seed_permissions', verbosity=0)
        self.user, self.profile, self.client = make_admin('bundle_pages_admin')
        self.branch = make_branch()
        self.batch = InvoiceBatch.objects.create(
            branch=self.branch, status='ready',
            source_file=SimpleUploadedFile('bundle.pdf', b'%PDF-1.4 fake bundle', content_type='application/pdf'))

    def _pages_dir(self):
        d = self.media / 'invoice_bundles' / 'pages' / f'batch_{self.batch.pk}'
        d.mkdir(parents=True, exist_ok=True)
        (d / 'page_001.png').write_bytes(b'png')
        return d


class FinalisedBatchTests(BundlePagesCase):
    def test_finalised_batch_works_without_pages(self):
        invoice = SupplierInvoice.objects.create(
            branch=self.branch, batch=self.batch, status='finalized',
            source_image=SimpleUploadedFile('inv.png', b'scan', content_type='image/png'))
        pages = self._pages_dir()
        shutil.rmtree(pages.parent)          # the lifecycle rule (or anyone) removed every page image
        self.assertFalse(pages.exists())

        r = self.client.get(f'{BATCH_URL}{self.batch.pk}/')
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.get(f'{INV_URL}{invoice.pk}/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['source_image_url'])


class ReprocessTests(BundlePagesCase):
    def test_reprocess_renders_from_source_file(self):
        def run_now(batch):
            ingest.process_bundle(batch.pk)

        with mock.patch('apps.invoices.ingest.start_async', side_effect=run_now), \
                mock.patch('apps.invoices.pdf.render_pages', return_value=[]) as render:
            r = self.client.post(f'{BATCH_URL}{self.batch.pk}/reprocess/')
        self.assertEqual(r.status_code, 200, r.content)
        render.assert_called_once()
        self.assertEqual(render.call_args.args[0], self.batch.source_file.path)


class OnlyIngestReadsPagesTests(TestCase):
    def test_only_ingest_reads_pages(self):
        root = Path(settings.BASE_DIR) if hasattr(settings, 'BASE_DIR') else Path(__file__).resolve().parents[2]
        offenders = []
        for path in (root / 'apps').rglob('*.py'):
            rel = path.relative_to(root).as_posix()
            if '/tests/' in rel or '/migrations/' in rel or rel.startswith(ALLOWED):
                continue
            text = path.read_text(encoding='utf-8', errors='ignore')
            if 'invoice_bundles' in text:
                offenders.append(rel)
        self.assertEqual(offenders, [], 'only ingest, the model and the lifecycle app may use invoice_bundles/pages')
