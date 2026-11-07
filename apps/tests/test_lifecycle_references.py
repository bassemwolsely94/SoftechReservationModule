"""
Data lifecycle Stage 3: the reference index (design §6 Stage 3).

A file is movable only when every record that uses it is one of the rule's own candidate rows. Checks found
607 product images and 4 OCR samples sharing a file with another row, and 299 enrichment rows holding a media
URL in text, so those cases are tested here.
"""

from django.test import TestCase

from apps.data_lifecycle.references import (
    TEXT_PATH_FIELDS, FileCandidate, Ref, build_reference_index, media_path_from_url, partition,
)
from apps.enrichment.models import ItemEnrichment
from apps.images.models import ImageCandidate, ImageSearchJob
from apps.invoices.models import SupplierInvoice
from apps.product_experience.models import ProductMedia
from apps.vision.models import OcrSample

from .factories import make_branch, make_item

SHARED = 'image_candidates/2024/05/shared.jpg'


def ref_of(obj, field):
    model = type(obj)._meta.label
    return Ref(model, obj.pk, field, getattr(obj, field).name)


class UrlFormsCase(TestCase):
    def test_url_forms(self):
        for url in ('/media/image_candidates/x.jpg',
                    'http://host.example/media/image_candidates/x.jpg',
                    'https://host/media/image_candidates/x.jpg?exp=1&sig=abc'):
            self.assertEqual(media_path_from_url(url), 'image_candidates/x.jpg')
        self.assertIsNone(media_path_from_url('http://elsewhere.example/images/x.jpg'))
        self.assertIsNone(media_path_from_url('/media/'))
        self.assertIsNone(media_path_from_url('/media/../secret.jpg'))
        self.assertIsNone(media_path_from_url(''))
        self.assertIsNone(media_path_from_url(None))


class IndexCase(TestCase):
    def setUp(self):
        self.item = make_item()
        job = ImageSearchJob.objects.create(item=self.item)
        self.candidate = ImageCandidate.objects.create(
            job=job, item=self.item, source_url='http://x.example/a.jpg', local_file=SHARED, status='rejected')

    def _candidate(self):
        return FileCandidate(SHARED, [ref_of(self.candidate, 'local_file')])

    def test_shared_path_is_skipped_and_counted(self):
        media = ProductMedia.objects.create(item=self.item, file=SHARED)
        index = build_reference_index()
        self.assertEqual({r.model for r in index[SHARED]}, {'images.ImageCandidate', 'product_experience.ProductMedia'})
        movable, skipped = partition([self._candidate()], index)
        self.assertEqual((movable, len(skipped)), ([], 1))
        self.assertIn(media.pk, {r.pk for r in index[SHARED]})

    def test_unshared_path_is_movable(self):
        movable, skipped = partition([self._candidate()], build_reference_index())
        self.assertEqual((len(movable), skipped), (1, []))

    def test_backslash_paths_are_normalised(self):
        ProductMedia.objects.create(item=self.item, file=SHARED.replace('/', chr(92)))
        movable, skipped = partition([self._candidate()], build_reference_index())
        self.assertEqual((movable, len(skipped)), ([], 1))

    def test_enrichment_url_counts_as_reference(self):
        self.assertIn(('enrichment.ItemEnrichment', 'image_url'), TEXT_PATH_FIELDS)
        enrichment = ItemEnrichment.objects.create(item=self.item, image_url=f'http://host/media/{SHARED}?sig=1')
        index = build_reference_index()
        self.assertIn(Ref('enrichment.ItemEnrichment', enrichment.pk, 'image_url', enrichment.image_url), index[SHARED])
        movable, skipped = partition([self._candidate()], index)
        self.assertEqual((movable, len(skipped)), ([], 1))

    def test_candidate_without_rows_is_skipped_when_anything_uses_it(self):
        movable, skipped = partition([FileCandidate(SHARED, [])], build_reference_index())
        self.assertEqual((movable, len(skipped)), ([], 1))
        movable, skipped = partition([FileCandidate('nobody/uses.jpg', [])], build_reference_index())
        self.assertEqual((len(movable), skipped), (1, []))

    def test_empty_values_are_not_references(self):
        ProductMedia.objects.create(item=self.item, file='')
        self.assertNotIn('', build_reference_index())


class InvoiceImageCase(TestCase):
    def test_invoice_image_shared_with_ocr_sample_stays(self):
        name = 'invoices/2024/scan.jpg'
        invoice = SupplierInvoice.objects.create(branch=make_branch(), source_image=name)
        sample = OcrSample.objects.create(module='purchasing_invoice', image=name)
        index = build_reference_index()
        self.assertEqual({r.model for r in index[name]}, {'invoices.SupplierInvoice', 'vision.OcrSample'})
        movable, skipped = partition([FileCandidate(name, [ref_of(invoice, 'source_image')])], index)
        self.assertEqual((movable, len(skipped)), ([], 1))
        # Both rows are the rule's own: the file may go.
        both = FileCandidate(name, [ref_of(invoice, 'source_image'), ref_of(sample, 'image')])
        movable, skipped = partition([both], index)
        self.assertEqual((len(movable), skipped), (1, []))
