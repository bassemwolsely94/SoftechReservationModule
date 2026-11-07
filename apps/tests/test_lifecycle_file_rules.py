"""
Data lifecycle Stage 3: what the file rules select (design §5.1, §6 Stage 3, §8).

A mistake here can lose a real document later, so these tests are about what must stay: a prescription one month
too young, a file another record still uses, an image of an item that came back, a bundle with an invoice still in
review, a prescription whose row was lost. The rules stay in preview until the VPS.
"""
import datetime
import logging
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.db import connections
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from apps.callcenter.models import CallLog
from apps.data_lifecycle import holding, rules_files, runner
from apps.data_lifecycle.holding import FileStranded, HoldError, restore
from apps.data_lifecycle.models import HeldFile, LifecycleRulePolicy, LifecycleRunLine, ObsoleteItemSeen, UnreferencedFileSeen
from apps.data_lifecycle.policy import has_fresh_preview, set_policy
from apps.data_lifecycle.references import TEXT_PATH_FIELDS, build_reference_index
from apps.data_lifecycle.register import RULES
from apps.data_lifecycle.rules_files import refresh_obsolete_seen, refresh_unreferenced_seen
from apps.data_lifecycle.runner import preview_rule, run_lifecycle_rules
from apps.enrichment.models import ItemEnrichment
from apps.images import pipeline
from apps.images.models import ImageCandidate, ImageSearchJob
from apps.invoices.models import InvoiceBatch, SupplierInvoice
from apps.notifications.models import Notification
from apps.pos_orders.models import SoftechSalesOrder
from apps.product_experience.models import ProductMedia
from apps.reservations.models import Reservation, ReservationImage
from apps.reservations.serializers import ReservationImageSerializer
from apps.usage_print.models import UsageSheet
from apps.vision.models import OcrSample

from .factories import make_admin, make_branch, make_item

DAY = datetime.timedelta(days=1)
THREE_YEARS = 1095
FIVE_YEARS = 1825


def days_ago(days):
    return timezone.now() - days * DAY


class FileRuleCase(TestCase):
    """A temporary media folder and hold folder, and helpers to age what is in them."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.media = self.tmp / 'media'
        self.media.mkdir()
        override = override_settings(MEDIA_ROOT=self.media, LIFECYCLE_HOLD_ROOT=self.tmp / 'media_hold')
        override.enable()
        self.addCleanup(override.disable)
        self.branch = make_branch()
        self.item = make_item()
        self.job = ImageSearchJob.objects.create(item=self.item)

    def _put(self, name, data=b'bytes', age_days=None):
        path = self.media / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if age_days is not None:
            stamp = days_ago(age_days).timestamp()
            os.utime(path, (stamp, stamp))
        return path

    def _age(self, obj, field, days):
        type(obj).objects.filter(pk=obj.pk).update(**{field: days_ago(days)})

    def _paths(self, key):
        return sorted(c.path for c in RULES[key].candidates())

    def _candidate(self, name, *, status='rejected', item=None, url=None, **fields):
        self._put(name)
        return ImageCandidate.objects.create(job=self.job, item=item or self.item, local_file=name, status=status,
                                             source_url=url or f'http://x.example/{name}', **fields)

    def _on(self, key):
        """Turn this rule on and make it the only one for the length of the `with`."""
        LifecycleRulePolicy.objects.update_or_create(rule_key=key, defaults={'mode': 'on', 'reason': 'test'})
        return mock.patch.dict(RULES, {key: RULES[key]}, clear=True)

    def _line(self, key):
        return LifecycleRunLine.objects.filter(rule_key=key).order_by('-pk').first()

    def _obsolete_item(self, softech_id='OB001', first_seen_days=None, **flags):
        item = make_item(softech_id, softech_id)
        type(item).objects.filter(pk=item.pk).update(**(flags or {'no_more_use': True}))
        if first_seen_days is not None:
            ObsoleteItemSeen.objects.create(item=item, first_seen_at=days_ago(first_seen_days))
        return item


class PrescriptionTests(FileRuleCase):
    def _rows(self):
        order = SoftechSalesOrder.objects.create(
            branch=self.branch, softech_branchcode='B01', store_code='101', channel='cash', doc_kind='sale',
            prescription_image='pos_orders/prescriptions/2023/a.jpg')
        sheet = UsageSheet.objects.create(
            branch=self.branch, docnumber='1', docdate=datetime.date(2023, 1, 1), softech_invoice_id='rx-1',
            prescription_image='usage_print/prescriptions/2023/a.jpg')
        call = CallLog.objects.create(phone_number='01012345678', branch=self.branch,
                                      prescription_image='callcenter/prescriptions/2023/a.jpg')
        reservation = Reservation.objects.create(item=self.item, branch=self.branch, quantity_requested=1,
                                                 contact_name='عميل', contact_phone='01011111111',
                                                 image='reservations/2023/a.jpg')
        extra = ReservationImage.objects.create(reservation=reservation, image='reservations/2023/b.jpg')
        rows = ((order, 'prescription_image', 'created_at'), (sheet, 'prescription_image', 'created_at'),
                (call, 'prescription_image', 'called_at'), (reservation, 'image', 'created_at'),
                (extra, 'image', 'uploaded_at'))
        for row, field, _ in rows:
            self._put(getattr(row, field).name)
        return rows

    def test_prescription_2y11m_stays(self):
        for row, _, date_field in self._rows():
            self._age(row, date_field, THREE_YEARS - 30)
        self.assertEqual(self._paths('prescriptions'), [])

    def test_prescription_3y1m_moves(self):
        rows = self._rows()
        for row, _, date_field in rows:
            self._age(row, date_field, THREE_YEARS + 30)
        expected = sorted(getattr(row, field).name for row, field, _ in rows)
        self.assertEqual(self._paths('prescriptions'), expected)

        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('prescriptions'):
            self.assertEqual(run_lifecycle_rules(), 5)

        for row, field, _ in rows:
            with self.subTest(model=type(row).__name__):
                name = getattr(row, field).name
                self.assertFalse((self.media / name).exists())
                row.refresh_from_db()
                self.assertFalse(getattr(row, field))    # the row stays, its file is gone
                self.assertTrue(HeldFile.objects.filter(original_path=name, rule_key='prescriptions').exists())

    def test_one_field_too_young_keeps_only_that_field(self):
        rows = self._rows()
        for row, _, date_field in rows:
            self._age(row, date_field, THREE_YEARS + 30)
        young, field, date_field = rows[0]
        self._age(young, date_field, THREE_YEARS - 30)
        self.assertNotIn(getattr(young, field).name, self._paths('prescriptions'))
        self.assertEqual(len(self._paths('prescriptions')), 4)

    def test_reservation_screen_survives_a_removed_image(self):
        """The row stays with an empty image, and the serializer must not raise on it."""
        rows = self._rows()
        extra = rows[-1][0]
        ReservationImage.objects.filter(pk=extra.pk).update(image='')
        extra.refresh_from_db()
        self.assertIsNone(ReservationImageSerializer(extra).data['image_url'])

    def test_longer_period_from_the_admin_is_obeyed(self):
        rows = self._rows()
        for row, _, date_field in rows:
            self._age(row, date_field, THREE_YEARS + 30)
        _, admin, _ = make_admin('rx_admin')
        set_policy('prescriptions', keep_days=THREE_YEARS + 60, user=admin, reason='x')
        self.assertEqual(self._paths('prescriptions'), [])


class OcrTests(FileRuleCase):
    def _sample(self, module, name, days):
        self._put(name)
        sample = OcrSample.objects.create(module=module, image=name, raw_readings=[{'readings': ['بنادول']}],
                                          confirmations=[{'reading': 'بنادول'}])
        self._age(sample, 'created_at', days)
        return sample

    def test_pos_rx_image_moves_text_stays(self):
        sample = self._sample('pos_rx', 'vision/ocr/2023/a.jpg', THREE_YEARS + 30)
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('ocr_pos_rx'):
            self.assertEqual(run_lifecycle_rules(), 1)
        sample.refresh_from_db()
        self.assertFalse(sample.image)
        self.assertEqual(sample.raw_readings, [{'readings': ['بنادول']}])
        self.assertEqual(sample.confirmations, [{'reading': 'بنادول'}])

    def test_young_pos_rx_stays(self):
        self._sample('pos_rx', 'vision/ocr/2023/a.jpg', THREE_YEARS - 30)
        self.assertEqual(self._paths('ocr_pos_rx'), [])

    def test_purchasing_invoice_sample_never_selected(self):
        for module in ('purchasing_invoice', 'purchasing_shortage', 'pos_voice', 'other'):
            self._sample(module, f'vision/ocr/2020/{module}.jpg', 5000)
        self.assertEqual(self._paths('ocr_pos_rx'), [])


class DatedRuleTests(FileRuleCase):
    def test_every_dated_rule_queries_cleanly_on_empty_tables(self):
        """Every target and date field of the register really can be queried."""
        for key in ('prescriptions', 'ocr_pos_rx', 'conversations', 'financial_docs', 'delivery_proof',
                    'staff_messages'):
            with self.subTest(rule=key):
                self.assertEqual(self._paths(key), [])

    def test_financial_document_keeps_five_years_and_its_row(self):
        name = 'invoice_images/a.pdf'
        self._put(name)
        invoice = SupplierInvoice.objects.create(branch=self.branch, source_image=name, invoice_number='77')
        self._age(invoice, 'created_at', FIVE_YEARS - 30)
        self.assertEqual(self._paths('financial_docs'), [])
        self._age(invoice, 'created_at', FIVE_YEARS + 30)
        self.assertEqual(self._paths('financial_docs'), [name])
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('financial_docs'):
            self.assertEqual(run_lifecycle_rules(), 1)
        invoice.refresh_from_db()
        self.assertEqual(invoice.invoice_number, '77')
        self.assertFalse(invoice.source_image)

    def test_two_rows_on_one_path_move_as_one_candidate(self):
        name = 'reservations/2023/shared.jpg'
        self._put(name)
        first = Reservation.objects.create(item=self.item, branch=self.branch, quantity_requested=1, contact_name='أ',
                                           contact_phone='01011111111', image=name)
        second = Reservation.objects.create(item=self.item, branch=self.branch, quantity_requested=1, contact_name='ب',
                                            contact_phone='01011111112', image=name)
        for row in (first, second):
            self._age(row, 'created_at', THREE_YEARS + 30)
        candidates = RULES['prescriptions'].candidates()
        self.assertEqual([len(c.rows) for c in candidates], [2])

    def test_file_used_by_a_younger_row_stays(self):
        name = 'reservations/2023/shared.jpg'
        self._put(name)
        old = Reservation.objects.create(item=self.item, branch=self.branch, quantity_requested=1, contact_name='أ',
                                         contact_phone='01011111111', image=name)
        Reservation.objects.create(item=self.item, branch=self.branch, quantity_requested=1, contact_name='ب',
                                   contact_phone='01011111112', image=name)
        self._age(old, 'created_at', THREE_YEARS + 30)
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('prescriptions'):
            self.assertEqual(run_lifecycle_rules(), 0)
        self.assertTrue((self.media / name).exists())
        self.assertEqual(self._line('prescriptions').skipped_shared, 1)
        old.refresh_from_db()
        self.assertTrue(old.image)


class ImageStatusTests(FileRuleCase):
    def test_rejected_30_days(self):
        old = self._candidate('image_candidates/old.jpg', status='rejected')
        self._age(old, 'created_at', 60)
        self._age(old, 'reviewed_at', 31)
        self.assertEqual(self._paths('images_rejected'), ['image_candidates/old.jpg'])

        # Found long ago, rejected today: the 30 days start today.
        self._age(old, 'reviewed_at', 0)
        self.assertEqual(self._paths('images_rejected'), [])

    def test_rejected_with_no_review_date_ages_from_creation(self):
        row = self._candidate('image_candidates/old.jpg', status='rejected')
        self._age(row, 'created_at', 31)
        self.assertIsNone(ImageCandidate.objects.get(pk=row.pk).reviewed_at)
        self.assertEqual(self._paths('images_rejected'), ['image_candidates/old.jpg'])
        self._age(row, 'created_at', 29)
        self.assertEqual(self._paths('images_rejected'), [])

    def test_unreviewed_180_days_row_kept(self):
        rows = [self._candidate(f'image_candidates/{status}.jpg', status=status)
                for status in ('scored', 'pending_review')]
        for row in rows:
            self._age(row, 'created_at', 179)
        self.assertEqual(self._paths('images_unreviewed'), [])
        for row in rows:
            self._age(row, 'created_at', 181)
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('images_unreviewed'):
            self.assertEqual(run_lifecycle_rules(), 2)
        for row in rows:
            row.refresh_from_db()
            self.assertFalse(row.local_file)
            self.assertTrue(row.source_url)      # the row still stops a re-download

    def test_new_and_error_have_no_rule(self):
        for status in ('new', 'error'):
            row = self._candidate(f'image_candidates/{status}.jpg', status=status)
            self._age(row, 'created_at', 5000)
        for key in ('images_rejected', 'images_unreviewed', 'images_obsolete'):
            self.assertEqual(self._paths(key), [], key)

    def test_auto_approved_on_live_item_never_selected(self):
        refresh_obsolete_seen()
        for status in ('approved', 'auto_approved'):
            row = self._candidate(f'image_candidates/{status}.jpg', status=status)
            self._age(row, 'created_at', 5000)
            self._age(row, 'reviewed_at', 5000)
        media = ProductMedia.objects.create(item=self.item, file='products/a.jpg', thumbnail='products/t.jpg')
        self._put('products/a.jpg')
        self._put('products/t.jpg')
        ProductMedia.objects.filter(pk=media.pk).update(created_at=days_ago(5000))
        for key, rule in RULES.items():
            if rule.kind == 'file' and key != 'unreferenced':
                self.assertEqual(self._paths(key), [], key)
        refresh_unreferenced_seen()
        self.assertFalse(UnreferencedFileSeen.objects.exists())

    def test_rejected_file_shared_with_a_live_product_image_stays(self):
        row = self._candidate('image_candidates/shared.jpg', status='rejected')
        self._age(row, 'created_at', 60)
        ProductMedia.objects.create(item=self.item, file='image_candidates/shared.jpg')
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('images_rejected'):
            self.assertEqual(run_lifecycle_rules(), 0)
        self.assertTrue((self.media / 'image_candidates/shared.jpg').exists())
        self.assertEqual(self._line('images_rejected').skipped_shared, 1)


class ObsoleteTests(FileRuleCase):
    def test_every_kind_of_obsolete_starts_the_clock(self):
        flagged = [self._obsolete_item('OB001', no_more_use=True), self._obsolete_item('OB002', item_archive=True),
                   self._obsolete_item('OB003', is_active=False)]
        self.assertEqual(refresh_obsolete_seen(), 3)
        self.assertEqual(set(ObsoleteItemSeen.objects.values_list('item_id', flat=True)), {i.pk for i in flagged})
        self.assertFalse(ObsoleteItemSeen.objects.filter(item=self.item).exists())

    def test_obsolete_clock_starts_when_first_seen(self):
        """The item has been obsolete for years in SOFTECH, but we only saw it today."""
        item = self._obsolete_item()
        row = self._candidate('image_candidates/a.jpg', status='approved', item=item)
        self._age(row, 'created_at', 5000)
        t0 = days_ago(89)
        refresh_obsolete_seen(now=t0)
        self.assertEqual(self._paths('images_obsolete'), [])

        refresh_obsolete_seen()     # a later scan must not move the first date
        self.assertEqual(ObsoleteItemSeen.objects.get(item=item).first_seen_at, t0)
        self.assertEqual(self._paths('images_obsolete'), [])

        ObsoleteItemSeen.objects.filter(item=item).update(first_seen_at=days_ago(91))
        self.assertEqual(self._paths('images_obsolete'), ['image_candidates/a.jpg'])

    def test_returning_to_use_clears_and_image_survives(self):
        item = self._obsolete_item(first_seen_days=100)
        self._candidate('image_candidates/a.jpg', status='approved', item=item)
        self.assertEqual(self._paths('images_obsolete'), ['image_candidates/a.jpg'])

        # The item is back. Even before a refresh sees that, its image is not selected.
        type(item).objects.filter(pk=item.pk).update(no_more_use=False)
        self.assertEqual(self._paths('images_obsolete'), [])

        refresh_obsolete_seen()
        seen = ObsoleteItemSeen.objects.get(item=item)
        self.assertIsNotNone(seen.cleared_at)
        self.assertEqual(self._paths('images_obsolete'), [])
        self.assertTrue((self.media / 'image_candidates/a.jpg').exists())

        # Obsolete again: the count starts over, it does not resume.
        type(item).objects.filter(pk=item.pk).update(no_more_use=True)
        refresh_obsolete_seen()
        seen.refresh_from_db()
        self.assertIsNone(seen.cleared_at)
        self.assertGreater(seen.first_seen_at, days_ago(1))
        self.assertEqual(self._paths('images_obsolete'), [])

    def test_item_flag_is_never_changed_by_the_refresh(self):
        item = self._obsolete_item()
        refresh_obsolete_seen()
        item.refresh_from_db()
        self.assertTrue(item.no_more_use)
        self.assertTrue(item.is_active)

    def test_thumbnail_is_its_own_candidate(self):
        item = self._obsolete_item(first_seen_days=100)
        self._put('products/a.jpg')
        self._put('products/t.jpg')
        ProductMedia.objects.create(item=item, file='products/a.jpg', thumbnail='products/t.jpg')
        candidates = {c.path: c for c in RULES['images_obsolete'].candidates()}
        self.assertEqual(set(candidates), {'products/a.jpg', 'products/t.jpg'})
        self.assertEqual([r.field for r in candidates['products/t.jpg'].rows], ['thumbnail'])

    def test_file_shared_with_a_live_item_stays(self):
        item = self._obsolete_item(first_seen_days=100)
        name = 'image_candidates/shared.jpg'
        self._candidate(name, status='approved', item=item)
        ProductMedia.objects.create(item=self.item, file=name)      # self.item is live
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('images_obsolete'):
            self.assertEqual(run_lifecycle_rules(), 0)
        self.assertTrue((self.media / name).exists())
        self.assertEqual(self._line('images_obsolete').skipped_shared, 1)

    def test_obsolete_group_clears_enrichment_url_and_restore_returns_it(self):
        item = self._obsolete_item(first_seen_days=100)
        name = 'image_candidates/a.jpg'
        candidate = self._candidate(name, status='approved', item=item)
        # bulk_create: the thumbnail signal fails on these bytes and leaves the file open, which Windows will not move.
        media = ProductMedia.objects.bulk_create([ProductMedia(item=item, file=name, approved=True, is_primary=True)])[0]
        url = f'http://host.example/media/{name}?sig=1'
        enrichment = ItemEnrichment.objects.create(item=item, image_url=url)

        candidates = RULES['images_obsolete'].candidates()
        self.assertEqual(len(candidates), 1)
        self.assertEqual({r.model for r in candidates[0].rows},
                         {'images.ImageCandidate', 'product_experience.ProductMedia', 'enrichment.ItemEnrichment'})

        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('images_obsolete'):
            self.assertEqual(run_lifecycle_rules(), 1)
        for row in (candidate, media, enrichment):
            row.refresh_from_db()
        self.assertFalse(candidate.local_file)
        self.assertFalse(media.file)
        self.assertEqual(enrichment.image_url, '')
        self.assertFalse((self.media / name).exists())

        _, admin, _ = make_admin('obsolete_admin')
        restore(HeldFile.objects.get(rule_key='images_obsolete').pk, admin)
        for row in (candidate, media, enrichment):
            row.refresh_from_db()
        self.assertEqual(candidate.local_file.name, name)
        self.assertEqual(media.file.name, name)
        self.assertEqual(enrichment.image_url, url)
        self.assertTrue((self.media / name).exists())


class PipelineFilterTests(FileRuleCase):
    def test_seen_urls_still_blocks_rejected_redownload(self):
        for status in ('rejected', 'scored', 'pending_review'):
            row = self._candidate(f'image_candidates/{status}.jpg', status=status, url=f'http://x.example/{status}',
                                  phash=f'ph{status}')
            ImageCandidate.objects.filter(pk=row.pk).update(local_file='')    # the rule removed the file
        seen_urls, phashes = pipeline._seen_before(self.item)
        self.assertEqual(seen_urls, {f'http://x.example/{s}' for s in ('rejected', 'scored', 'pending_review')})
        self.assertEqual(set(phashes), {'phrejected', 'phscored', 'phpending_review'})

    def test_returned_item_can_refetch_removed_image(self):
        kept = self._candidate('image_candidates/kept.jpg', status='approved', url='http://x.example/kept', phash='k')
        for status, field_value in (('approved', ''), ('auto_approved', ''), ('approved', None)):
            row = self._candidate(f'image_candidates/gone{status}{field_value}.jpg', status=status,
                                  url=f'http://x.example/gone{status}{field_value}', phash=f'g{status}{field_value}')
            ImageCandidate.objects.filter(pk=row.pk).update(local_file=field_value)
        seen_urls, phashes = pipeline._seen_before(self.item)
        self.assertEqual(seen_urls, {kept.source_url})
        self.assertEqual(phashes, ['k'])

    def test_item_with_only_an_emptied_media_row_counts_as_having_no_image(self):
        ProductMedia.objects.create(item=self.item, media_type='image', approved=True, file='')
        self.assertNotIn(self.item.pk, set(pipeline._items_with_approved_image()))

        patcher = mock.patch.object(connections['default'], 'close')     # run_job closes the connection before HTTP
        patcher.start()
        self.addCleanup(patcher.stop)
        job = pipeline.create_job(self.item, priority=2)
        with mock.patch('apps.images.searcher.search_all_sources', return_value=[]) as search:
            pipeline.run_job(job)
        search.assert_called_once()
        job.refresh_from_db()
        self.assertNotEqual(job.status, 'skipped')

    def test_item_with_a_real_media_file_still_counts(self):
        self._put('products/a.jpg')
        ProductMedia.objects.create(item=self.item, media_type='image', approved=True, file='products/a.jpg')
        self.assertIn(self.item.pk, set(pipeline._items_with_approved_image()))


class BundlePagesTests(FileRuleCase):
    def _batch(self, status, pages=2, page_age_days=60, updated_days=60):
        batch = InvoiceBatch.objects.create(branch=self.branch, status=status, source_file='invoice_bundles/src.pdf')
        InvoiceBatch.objects.filter(pk=batch.pk).update(updated_at=days_ago(updated_days))
        self._put('invoice_bundles/src.pdf', age_days=5000)
        for number in range(pages):
            self._put(f'invoice_bundles/pages/batch_{batch.pk}/page_{number}.png', age_days=page_age_days)
        return batch

    def _invoice(self, batch, status, updated_days=60):
        invoice = SupplierInvoice.objects.create(branch=self.branch, batch=batch, status=status)
        SupplierInvoice.objects.filter(pk=invoice.pk).update(updated_at=days_ago(updated_days))
        return invoice

    def _pages(self, batch):
        return [f'invoice_bundles/pages/batch_{batch.pk}/page_{n}.png' for n in range(2)]

    def test_bundle_pages_wait_for_every_invoice(self):
        batch = self._batch('ready')
        self._invoice(batch, 'finalized')
        held_up_by = self._invoice(batch, 'review')
        self.assertEqual(self._paths('bundle_pages'), [])

        for status in ('pending', 'processing', 'confirmed', 'queued', 'pushing', 'push_failed'):
            SupplierInvoice.objects.filter(pk=held_up_by.pk).update(status=status)
            self.assertEqual(self._paths('bundle_pages'), [], status)

        # Everything settled, but the last one only 29 days ago.
        SupplierInvoice.objects.filter(pk=held_up_by.pk).update(status='rejected', updated_at=days_ago(29))
        self.assertEqual(self._paths('bundle_pages'), [])

        SupplierInvoice.objects.filter(pk=held_up_by.pk).update(updated_at=days_ago(31))
        self.assertEqual(self._paths('bundle_pages'), self._pages(batch))
        for candidate in RULES['bundle_pages'].candidates():
            self.assertEqual(candidate.rows, [])
            self.assertGreater(candidate.size, 0)

        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('bundle_pages'):
            self.assertEqual(run_lifecycle_rules(), 2)
        batch.refresh_from_db()
        self.assertEqual(batch.source_file.name, 'invoice_bundles/src.pdf')     # the source PDF stays
        self.assertTrue((self.media / 'invoice_bundles/src.pdf').exists())
        self.assertFalse(any((self.media / path).exists() for path in self._pages(batch)))

    def test_processing_or_pending_batch_never_moves(self):
        for status in ('processing', 'pending'):
            batch = self._batch(status, updated_days=5000, page_age_days=5000)
            self._invoice(batch, 'finalized', updated_days=5000)
            self.assertEqual(self._paths('bundle_pages'), [], status)

    def test_failed_batch_moves_after_30_days(self):
        young = self._batch('failed', updated_days=29, page_age_days=29)
        self.assertEqual(self._paths('bundle_pages'), [])
        InvoiceBatch.objects.filter(pk=young.pk).update(updated_at=days_ago(31))
        for path in self._pages(young):
            stamp = days_ago(31).timestamp()
            os.utime(self.media / path, (stamp, stamp))
        self.assertEqual(self._paths('bundle_pages'), self._pages(young))

    def test_failed_batch_with_a_recent_reprocess_waits(self):
        """Saving the status does not touch updated_at, so a fresh page says the failure is recent."""
        self._batch('failed', updated_days=5000, page_age_days=3)
        self.assertEqual(self._paths('bundle_pages'), [])

    def test_failed_batch_with_an_invoice_in_review_waits(self):
        batch = self._batch('failed')
        self._invoice(batch, 'review')
        self.assertEqual(self._paths('bundle_pages'), [])

    def test_ready_batch_with_no_invoices_stays(self):
        self._batch('ready')
        self.assertEqual(self._paths('bundle_pages'), [])

    def test_folder_with_no_batch_row_stays(self):
        self._put('invoice_bundles/pages/batch_999999/page_0.png', age_days=5000)
        self.assertEqual(self._paths('bundle_pages'), [])


class UnreferencedTests(FileRuleCase):
    def test_unreferenced_needs_two_scans_30_days_apart(self):
        self._put('junk/a.bin', age_days=500)
        refresh_unreferenced_seen(now=days_ago(29))
        self.assertEqual(self._paths('unreferenced'), [])     # one scan only

        refresh_unreferenced_seen()                          # second scan, 29 days later
        self.assertEqual(self._paths('unreferenced'), [])

        UnreferencedFileSeen.objects.update(first_seen_at=days_ago(30), last_seen_at=days_ago(1))
        self.assertEqual(self._paths('unreferenced'), [])     # the file is 30 days on the list, the scans 29 apart
        UnreferencedFileSeen.objects.update(first_seen_at=days_ago(32))
        self.assertEqual(self._paths('unreferenced'), ['junk/a.bin'])

        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('unreferenced'):
            self.assertEqual(run_lifecycle_rules(), 1)
        held = HeldFile.objects.get(rule_key='unreferenced')
        self.assertEqual((held.original_path, held.rows), ('junk/a.bin', []))

    def test_file_that_gained_a_record_or_vanished_loses_its_clock(self):
        self._put('junk/used.jpg')
        self._put('junk/gone.bin')
        self.assertEqual(refresh_unreferenced_seen(now=days_ago(40)), 2)
        ProductMedia.objects.create(item=self.item, file='junk/used.jpg')
        (self.media / 'junk/gone.bin').unlink()
        self.assertEqual(refresh_unreferenced_seen(), 0)
        self.assertFalse(UnreferencedFileSeen.objects.exists())

    def test_referenced_file_is_never_seen(self):
        self._put('junk/used.jpg')
        ProductMedia.objects.create(item=self.item, file='junk/used.jpg')
        self._put('junk/by_url.jpg')
        ItemEnrichment.objects.create(item=self.item, image_url='http://host/media/junk/by_url.jpg')
        self.assertEqual(refresh_unreferenced_seen(), 0)

    def test_secondary_image_url_counts_as_a_reference(self):
        self.assertIn(('enrichment.ItemEnrichment', 'image_secondary_url'), TEXT_PATH_FIELDS)
        self._put('junk/second.jpg')
        ItemEnrichment.objects.create(item=self.item, image_secondary_url='http://host/media/junk/second.jpg')
        self.assertEqual(refresh_unreferenced_seen(), 0)

    def test_reports_folder_excluded(self):
        self._put('reports/a.xlsx', age_days=5000)
        self._put('invoice_bundles/pages/batch_1/page_0.png', age_days=5000)
        self.assertEqual(refresh_unreferenced_seen(now=days_ago(60)), 0)
        self.assertEqual(refresh_unreferenced_seen(), 0)
        self.assertFalse(UnreferencedFileSeen.objects.exists())
        # A row left from before must not select it either.
        UnreferencedFileSeen.objects.create(path='reports/a.xlsx', first_seen_at=days_ago(60))
        self.assertEqual(self._paths('unreferenced'), [])

    def test_orphan_prescription_needs_three_years(self):
        # The last three are conversation folders: they may hold prescriptions, so they take the same period.
        for folder in ('reservations', 'pos_orders/prescriptions', 'usage_print/prescriptions',
                       'callcenter/prescriptions', 'vision/ocr',
                       'whatsapp/media', 'callcenter/attachments', 'callcenter/case_events'):
            self._put(f'{folder}/young.jpg', age_days=THREE_YEARS - 30)
            self._put(f'{folder}/old.jpg', age_days=THREE_YEARS + 30)
        refresh_unreferenced_seen(now=days_ago(40))
        refresh_unreferenced_seen()
        paths = self._paths('unreferenced')
        self.assertEqual(len(paths), 8)
        self.assertTrue(all(path.endswith('old.jpg') for path in paths), paths)

    def test_orphan_conversation_file_follows_the_conversations_period(self):
        self._put('whatsapp/media/old.jpg', age_days=THREE_YEARS + 30)
        refresh_unreferenced_seen(now=days_ago(40))
        refresh_unreferenced_seen()
        self.assertEqual(self._paths('unreferenced'), ['whatsapp/media/old.jpg'])
        _, admin, _ = make_admin('conversation_admin')
        set_policy('conversations', keep_days=THREE_YEARS + 60, user=admin, reason='x')
        self.assertEqual(self._paths('unreferenced'), [])

    def test_orphan_financial_document_needs_five_years(self):
        for folder in ('invoice_images', 'invoice_bundles', 'payments/screenshots', 'hr/receipts'):
            self._put(f'{folder}/young.pdf', age_days=FIVE_YEARS - 30)
            self._put(f'{folder}/old.pdf', age_days=FIVE_YEARS + 30)
        refresh_unreferenced_seen(now=days_ago(40))
        refresh_unreferenced_seen()
        paths = self._paths('unreferenced')
        self.assertEqual(len(paths), 4)
        self.assertTrue(all(path.endswith('old.pdf') for path in paths), paths)

    def test_similar_folder_name_is_not_a_prescription_folder(self):
        self._put('reservation_activities/a.jpg', age_days=100)
        refresh_unreferenced_seen(now=days_ago(40))
        refresh_unreferenced_seen()
        self.assertEqual(self._paths('unreferenced'), ['reservation_activities/a.jpg'])


class RunnerTests(FileRuleCase):
    def _rejected(self, count, prefix='image_candidates/r'):
        rows = []
        for number in range(count):
            row = self._candidate(f'{prefix}{number}.jpg', status='rejected')
            self._age(row, 'created_at', 60)
            rows.append(row)
        return rows

    def test_file_rules_only_preview_off_vps(self):
        row = self._rejected(1)[0]
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=False), self._on('images_rejected'):
            self.assertEqual(run_lifecycle_rules(), 0)
        self.assertTrue((self.media / row.local_file.name).exists())
        row.refresh_from_db()
        self.assertTrue(row.local_file)
        self.assertFalse(HeldFile.objects.exists())
        line = self._line('images_rejected')
        self.assertTrue(line.is_preview)
        self.assertEqual((line.count, line.bytes), (1, 5))

    def test_real_matches_preview_on_unchanged_data(self):
        self._rejected(3)
        shared = self._candidate('image_candidates/shared.jpg', status='rejected')
        self._age(shared, 'created_at', 60)
        ProductMedia.objects.create(item=self.item, file='image_candidates/shared.jpg')

        preview = preview_rule('images_rejected')
        self.assertEqual((preview.count, preview.bytes, preview.skipped_shared), (3, 15, 1))
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('images_rejected'):
            self.assertEqual(run_lifecycle_rules(), 3)
        real = self._line('images_rejected')
        self.assertFalse(real.is_preview)
        self.assertEqual((real.count, real.bytes, real.skipped_shared), (3, 15, 1))
        self.assertEqual(real.error, '')

    def test_breaker_counts_the_files_that_would_move(self):
        make_admin('breaker_admin')
        self._rejected(2)
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('images_rejected'), \
                mock.patch.dict(RULES, {'images_rejected': replace(RULES['images_rejected'], margin=1)}):
            self.assertEqual(run_lifecycle_rules(), 0)
        line = self._line('images_rejected')
        self.assertTrue(line.stopped_by_breaker)
        self.assertEqual(line.count, 0)
        self.assertFalse(HeldFile.objects.exists())

    def test_one_failure_is_on_the_line_and_the_rest_move(self):
        rows = self._rejected(3)
        real = holding.hold_file

        def fail_first(path, row_list, key):
            if path.endswith('r0.jpg'):
                raise HoldError('refused')
            return real(path, row_list, key)

        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('images_rejected'), \
                mock.patch.object(holding, 'hold_file', side_effect=fail_first), \
                self.assertLogs('elrezeiky.sync', logging.ERROR) as logs:
            self.assertEqual(run_lifecycle_rules(), 2)
        line = self._line('images_rejected')
        self.assertEqual((line.count, line.bytes), (2, 10))
        self.assertIn(f'images.ImageCandidate#{rows[0].pk}', line.error)
        self.assertIn(f'images.ImageCandidate#{rows[0].pk}', '\n'.join(logs.output))
        self.assertNotIn('r0.jpg', line.error)
        self.assertNotIn('r0.jpg', '\n'.join(logs.output))

    def test_stranded_file_is_recorded_and_the_rest_move(self):
        rows = self._rejected(2)
        real = holding.hold_file

        def strand_first(path, row_list, key):
            if path.endswith('r0.jpg'):
                raise FileStranded('stranded')
            return real(path, row_list, key)

        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('images_rejected'), \
                mock.patch.object(holding, 'hold_file', side_effect=strand_first):
            self.assertEqual(run_lifecycle_rules(), 1)
        line = self._line('images_rejected')
        self.assertIn('FileStranded', line.error)
        self.assertIn(str(rows[0].pk), line.error)

    def test_failed_file_without_a_record_names_no_file(self):
        self._put('junk/secret_name.bin', age_days=500)
        UnreferencedFileSeen.objects.create(path='junk/secret_name.bin', first_seen_at=days_ago(40))
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('unreferenced'), \
                mock.patch.object(holding, 'hold_file', side_effect=HoldError('refused')), \
                self.assertLogs('elrezeiky.sync', logging.ERROR) as logs:
            self.assertEqual(run_lifecycle_rules(), 0)
        self.assertTrue(self._line('unreferenced').error)
        self.assertNotIn('secret_name', self._line('unreferenced').error)
        self.assertNotIn('secret_name', '\n'.join(logs.output))

    def test_row_whose_file_is_missing_is_not_counted_and_is_logged(self):
        self._rejected(25)
        gone = ImageCandidate.objects.create(job=self.job, item=self.item, local_file='image_candidates/secret_gone.jpg',
                                             status='rejected', source_url='http://x.example/gone')
        self._age(gone, 'created_at', 60)
        with self.assertLogs('elrezeiky.sync', logging.WARNING) as logs:
            candidates = RULES['images_rejected'].candidates()
        self.assertEqual(len(candidates), 25)
        self.assertIn('1', '\n'.join(logs.output))
        self.assertNotIn('secret_gone', '\n'.join(logs.output))

        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('images_rejected'):
            self.assertEqual(run_lifecycle_rules(), 25)
        line = self._line('images_rejected')
        self.assertEqual((line.count, line.error), (25, ''))
        gone.refresh_from_db()
        self.assertTrue(gone.local_file)        # untouched: nothing was moved for it

    def test_candidate_path_outside_media_is_treated_as_missing(self):
        row = ImageCandidate.objects.create(job=self.job, item=self.item, local_file='../media_hold/x.jpg',
                                            status='rejected', source_url='http://x.example/o')
        self._age(row, 'created_at', 60)
        (self.tmp / 'media_hold').mkdir()
        (self.tmp / 'media_hold/x.jpg').write_bytes(b'x')
        self.assertEqual(self._paths('images_rejected'), [])

    def test_reference_index_is_built_once_per_run(self):
        self._rejected(1)
        with mock.patch.object(runner, 'build_reference_index', wraps=build_reference_index) as build:
            run_lifecycle_rules()
        self.assertEqual(build.call_count, 1)

    def test_refreshes_run_in_preview_and_not_when_off(self):
        item = self._obsolete_item()
        self._put('junk/a.bin')
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=False):
            LifecycleRulePolicy.objects.create(rule_key='images_obsolete', mode='off', reason='x')
            LifecycleRulePolicy.objects.create(rule_key='unreferenced', mode='off', reason='x')
            run_lifecycle_rules()
            self.assertFalse(ObsoleteItemSeen.objects.exists())
            self.assertFalse(UnreferencedFileSeen.objects.exists())

            LifecycleRulePolicy.objects.all().delete()      # default mode: preview
            run_lifecycle_rules()
        self.assertTrue(ObsoleteItemSeen.objects.filter(item=item).exists())
        self.assertTrue(UnreferencedFileSeen.objects.filter(path='junk/a.bin').exists())
        self.assertTrue(self._line('images_obsolete').is_preview)

    def test_manual_preview_changes_nothing_but_its_line(self):
        self._obsolete_item()
        self._put('junk/a.bin')
        preview_rule('images_obsolete')
        preview_rule('unreferenced')
        self.assertFalse(ObsoleteItemSeen.objects.exists())
        self.assertFalse(UnreferencedFileSeen.objects.exists())

    def test_real_run_refreshes_before_it_selects(self):
        item = self._obsolete_item(first_seen_days=100)
        self._candidate('image_candidates/a.jpg', status='approved', item=item)
        type(item).objects.filter(pk=item.pk).update(no_more_use=False)
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on('images_obsolete'):
            self.assertEqual(run_lifecycle_rules(), 0)
        self.assertIsNotNone(ObsoleteItemSeen.objects.get(item=item).cleared_at)


class RestoreSticksTests(FileRuleCase):
    """An admin who restores a file has decided it stays. The next nightly run must not take it again."""

    def setUp(self):
        super().setUp()
        _, self.admin, _ = make_admin('restore_admin')

    def _run(self, key, expected):
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True), self._on(key):
            self.assertEqual(run_lifecycle_rules(), expected)

    def _restore(self, key):
        restore(HeldFile.objects.get(rule_key=key).pk, self.admin)

    def test_restored_row_file_stays_and_its_row_stays_filled(self):
        name = 'image_candidates/a.jpg'
        row = self._candidate(name, status='rejected')
        self._age(row, 'created_at', 60)
        self._run('images_rejected', 1)
        self.assertFalse((self.media / name).exists())

        self._restore('images_rejected')
        self._run('images_rejected', 0)
        self._run('images_rejected', 0)

        self.assertTrue((self.media / name).exists())
        row.refresh_from_db()
        self.assertEqual(row.local_file.name, name)
        self.assertEqual(HeldFile.objects.filter(rule_key='images_rejected').count(), 1)
        self.assertEqual(self._paths('images_rejected'), [])
        self.assertEqual(preview_rule('images_rejected').count, 0)

    def test_restored_unreferenced_file_stays(self):
        name = 'junk/a.bin'
        self._put(name, age_days=500)
        UnreferencedFileSeen.objects.create(path=name, first_seen_at=days_ago(40))
        self._run('unreferenced', 1)
        self._restore('unreferenced')

        self._run('unreferenced', 0)
        self.assertTrue((self.media / name).exists())
        UnreferencedFileSeen.objects.update(first_seen_at=days_ago(40))    # even with the two scans satisfied
        self._run('unreferenced', 0)
        self.assertTrue((self.media / name).exists())
        self.assertEqual(HeldFile.objects.filter(rule_key='unreferenced').count(), 1)

    def test_restored_bundle_page_stays(self):
        batch = InvoiceBatch.objects.create(branch=self.branch, status='failed')
        InvoiceBatch.objects.filter(pk=batch.pk).update(updated_at=days_ago(60))
        name = f'invoice_bundles/pages/batch_{batch.pk}/page_0.png'
        self._put(name, age_days=60)
        self._run('bundle_pages', 1)
        self._restore('bundle_pages')
        # The restored page keeps its old date, so only the restore record can hold it back.
        self._run('bundle_pages', 0)
        self.assertTrue((self.media / name).exists())

    def test_restore_under_one_rule_holds_under_every_other(self):
        item = self._obsolete_item(first_seen_days=100)
        name = 'image_candidates/a.jpg'
        row = self._candidate(name, status='rejected', item=item)
        self._age(row, 'created_at', 60)
        self._run('images_rejected', 1)
        self._restore('images_rejected')
        self._run('images_obsolete', 0)
        self.assertTrue((self.media / name).exists())

    def test_held_but_not_restored_or_purged_path_does_not_block(self):
        """Only a restore holds a path. A new file at a path that was purged is an ordinary file."""
        name = 'image_candidates/a.jpg'
        row = self._candidate(name, status='rejected')
        self._age(row, 'created_at', 60)
        HeldFile.objects.create(original_path=name, hold_path='x.jpg', rule_key='images_rejected', sha256='0' * 64,
                                purge_after=timezone.now(), purged_at=timezone.now())
        self.assertEqual(self._paths('images_rejected'), [name])

    def test_skipped_restored_files_are_counted_in_the_log(self):
        name = 'image_candidates/secret_name.jpg'
        row = self._candidate(name, status='rejected')
        self._age(row, 'created_at', 60)
        self._run('images_rejected', 1)
        self._restore('images_rejected')
        with self.assertLogs('elrezeiky.sync', logging.INFO) as logs:
            self.assertEqual(self._paths('images_rejected'), [])
        output = '\n'.join(logs.output)
        self.assertIn('images_rejected: 1 ', output)
        self.assertNotIn('secret_name', output)


class WrongFolderGuardTests(FileRuleCase):
    def _referenced(self, present, missing):
        for number in range(present):
            name = f'image_candidates/here{number}.jpg'
            self._put(name)
            row = ImageCandidate.objects.create(job=self.job, item=self.item, local_file=name, status='rejected',
                                                source_url=f'http://x.example/h{number}')
            self._age(row, 'created_at', 60)
        for number in range(missing):
            ImageCandidate.objects.create(job=self.job, item=self.item, local_file=f'image_candidates/gone{number}.jpg',
                                          status='new', source_url=f'http://x.example/g{number}')

    def test_missing_media_stops_file_rules(self):
        make_admin('guard_admin')
        self._referenced(present=18, missing=2)     # 10% missing
        self._put('junk/a.bin')
        before = Notification.objects.filter(notification_type='sync_failure').count()
        LifecycleRulePolicy.objects.create(rule_key='images_rejected', mode='on', reason='test')
        with override_settings(LIFECYCLE_FILE_RULES_ENABLED=True),                 mock.patch.dict(RULES, {k: RULES[k] for k in ('images_rejected', 'unreferenced')}, clear=True):
            self.assertEqual(run_lifecycle_rules(), 0)
            run_lifecycle_rules()      # a second run the same day: no second alert
        self.assertFalse(HeldFile.objects.exists())
        self.assertFalse(UnreferencedFileSeen.objects.exists())     # no clock starts against a wrong folder
        for key in ('images_rejected', 'unreferenced'):
            line = self._line(key)
            self.assertEqual(line.count, 0, key)
            self.assertTrue(line.error, key)
        self.assertEqual(Notification.objects.filter(notification_type='sync_failure').count() - before, 1)

    def test_stopped_preview_does_not_count_as_fresh(self):
        make_admin('guard_admin2')
        self._referenced(present=1, missing=1)
        line = preview_rule('images_rejected')
        self.assertEqual(line.count, 0)
        self.assertTrue(line.error)
        self.assertFalse(has_fresh_preview('images_rejected'))

    def test_exactly_five_percent_missing_still_runs(self):
        self._referenced(present=19, missing=1)     # 5%: the limit is "more than"
        line = preview_rule('images_rejected')
        self.assertEqual((line.count, line.error), (19, ''))

    def test_row_rules_keep_running(self):
        make_admin('guard_admin3')
        self._referenced(present=1, missing=1)
        run_lifecycle_rules()
        self.assertEqual(self._line('transit_alert_notes').error, '')


class TestMediaRootTests(SimpleTestCase):
    def test_tests_do_not_write_to_the_real_media_folder(self):
        self.assertNotEqual(Path(settings.MEDIA_ROOT).resolve(), (Path(settings.BASE_DIR) / 'media').resolve())
        self.assertTrue(Path(settings.MEDIA_ROOT).is_dir())


class ModuleContractTests(SimpleTestCase):
    def test_every_file_rule_has_a_real_selection(self):
        for key, rule in RULES.items():
            if rule.kind == 'file':
                self.assertEqual(rule.candidates.__module__, rules_files.__name__, key)

    def test_only_the_two_seen_rules_refresh(self):
        self.assertEqual({k for k, r in RULES.items() if r.refresh}, {'images_obsolete', 'unreferenced'})
