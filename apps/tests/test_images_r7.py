"""
R7 — apps/images per-app tests.

Route groups (apps/images/urls.py), one view test each:
  jobs/ (list+create)  jobs/bulk/  jobs/revise-all/  jobs/<pk>/  jobs/<pk>/cancel/
  candidates/  candidates/<pk>/review/  candidates/<pk>/redownload/
  products/search/  products/<item>/gallery|candidates|upload|set-primary|reorder|images/<pk>/
  report/  review-queue/  filter-meta/  insights/

Permission: the views sit under the `catalog` matrix module; viewer (catalog view only) may read
but not start jobs / review.
Business rules: the name normaliser, scorer helpers (file size, text match, duplicates), the
learned source weight, job de-duplication and the run_job pipeline (search / download / score
all mocked — no network, no thread).
"""
import importlib.util
import io
import shutil
import unittest
import tempfile
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections
from django.test import TestCase, override_settings

from apps.catalog.models import Item
from apps.images import pipeline
from apps.images.models import ImageApprovalInsight, ImageCandidate, ImageSearchJob, ProductNormalization
from apps.images.normalizer import normalize_item
from apps.images.scorer import _score_file_size, _score_text_match, are_duplicates
from apps.tests.factories import make_category, make_item, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

# imagehash is a production dependency left out of requirements-ci.txt (heavy); without it
# are_duplicates() is always False by design.
HAS_IMAGEHASH = importlib.util.find_spec('imagehash') is not None

API = '/api/images/'


def _png(size=(8, 8)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', size, (250, 250, 250)).save(buf, format='PNG')
    return buf.getvalue()


@override_settings(RBAC_ENFORCEMENT='log')
class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)
        ov = override_settings(MEDIA_ROOT=self.media)
        ov.enable()
        self.addCleanup(ov.disable)
        self.user, self.pharm, self.client_ = make_user('r7img_pharm', role='pharmacist')
        self.item = make_item('ARCOXIA 90mg 7 tabs', 'R7M1')
        self.item.producer_name = 'MSD Egypt'
        self.item.save()
        # never start the pool / a thread from a test
        p1 = mock.patch('apps.images.views._start_job_thread')
        self.start_job = p1.start()
        self.addCleanup(p1.stop)

    def tearDown(self):
        module_access.clear_cache()

    def job(self, **kw):
        return ImageSearchJob.objects.create(item=kw.pop('item', self.item), **kw)

    def cand(self, job=None, **kw):
        job = job or self.job(status='done')
        base = dict(job=job, item=job.item, source_url='https://img.example/a.jpg',
                    status='pending_review', total_score=0.6)
        base.update(kw)
        return ImageCandidate.objects.create(**base)

    def media_row(self, **kw):
        from apps.product_experience.models import ProductMedia
        base = dict(item=self.item, media_type='image', file='products/x.jpg', approved=True)
        base.update(kw)
        return ProductMedia.objects.create(**base)


# ── Permission ────────────────────────────────────────────────────────────────

class ImagesPermissionTests(_Base):

    def test_viewer_reads_but_cannot_start_or_review(self):
        viewer, _, _ = make_user('r7img_viewer', role='viewer')
        c = bearer_client(viewer)
        self.assertEqual(c.get(API + 'jobs/').status_code, 200)
        r = c.post(API + 'jobs/', {'item_id': self.item.id}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertFalse(ImageSearchJob.objects.exists())
        cand = self.cand()
        self.assertEqual(c.post(f'{API}candidates/{cand.id}/review/', {'action': 'reject'},
                                format='json').status_code, 403)
        cand.refresh_from_db()
        self.assertEqual(cand.status, 'pending_review')

    def test_delivery_cannot_delete_gallery_images(self):
        m = self.media_row()
        u, _, _ = make_user('r7img_delivery', role='delivery')
        r = bearer_client(u).delete(f'{API}products/{self.item.id}/images/{m.id}/')
        self.assertEqual(r.status_code, 403)


# ── Jobs ──────────────────────────────────────────────────────────────────────

class JobViewTests(_Base):

    def test_create_dedups_open_job_and_starts_once(self):
        r = self.client_.post(API + 'jobs/', {'item_id': self.item.id, 'priority': 3}, format='json')
        self.assertEqual(r.status_code, 201)
        job_id = r.data['id']
        self.assertEqual(r.data['priority'], 3)
        self.start_job.assert_called_once_with(job_id)
        ImageSearchJob.objects.filter(pk=job_id).update(status='running')
        r = self.client_.post(API + 'jobs/', {'item_id': self.item.id}, format='json')
        self.assertEqual(r.data['id'], job_id)                 # same open job, not a second one
        self.assertEqual(self.start_job.call_count, 1)
        self.assertEqual(self.client_.post(API + 'jobs/', {'item_id': 999999}, format='json').status_code, 404)
        self.assertEqual(self.client_.post(API + 'jobs/', {'item_id': self.item.id, 'priority': 9},
                                           format='json').status_code, 400)

    def test_list_filters_and_ordering(self):
        a = self.job(status='done', best_score=0.9)
        b = self.job(status='failed', best_score=0.2)
        r = self.client_.get(API + 'jobs/', {'status': 'done'})
        self.assertEqual([j['id'] for j in r.data], [a.id])
        r = self.client_.get(API + 'jobs/', {'ordering': 'best_score'})
        self.assertEqual([j['id'] for j in r.data], [b.id, a.id])
        self.assertEqual(self.client_.get(API + 'jobs/', {'ordering': 'evil'}).status_code, 400)
        self.assertEqual(self.client_.get(API + 'jobs/', {'ordering': '-duration'}).status_code, 200)

    def test_detail_and_cancel(self):
        j = self.job(status='pending')
        r = self.client_.get(f'{API}jobs/{j.id}/')
        self.assertEqual((r.status_code, r.data['triggered_by_name']), (200, 'نظام تلقائي'))
        self.assertEqual(self.client_.get(f'{API}jobs/999999/').status_code, 404)
        r = self.client_.post(f'{API}jobs/{j.id}/cancel/')
        self.assertEqual(r.status_code, 200)
        j.refresh_from_db()
        self.assertEqual(j.status, 'cancelled')
        self.assertIsNotNone(j.finished_at)
        self.assertEqual(self.client_.post(f'{API}jobs/{j.id}/cancel/').status_code, 400)
        self.assertEqual(self.client_.post(f'{API}jobs/999999/cancel/').status_code, 404)

    def test_bulk_creates_for_items_without_image(self):
        other = make_item('PANADOL 500mg', 'R7M2')
        self.media_row(item=other)                              # already has an image → excluded
        r = self.client_.post(API + 'jobs/bulk/', {'scope': 'no_image', 'limit': 50}, format='json')
        self.assertEqual(r.status_code, 200)
        items_with_jobs = set(ImageSearchJob.objects.values_list('item_id', flat=True))
        self.assertIn(self.item.id, items_with_jobs)
        self.assertNotIn(other.id, items_with_jobs)
        self.assertEqual(r.data['created'], self.start_job.call_count)
        self.assertEqual(r.data['total_matched'], r.data['created'] + r.data['skipped'])

    def test_revise_all_skips_items_already_scoring_well(self):
        Item.objects.exclude(pk=self.item.pk).update(is_active=False)
        self.job(status='done', best_score=0.95)
        r = self.client_.post(API + 'jobs/revise-all/', {'min_score': 0.9}, format='json')
        self.assertEqual(r.data['created'], 0)
        r = self.client_.post(API + 'jobs/revise-all/', {'min_score': 0.99, 'category_id': self.item.category_id,
                                                         'producer_name': 'MSD'}, format='json')
        self.assertEqual(r.data['created'], 1)
        self.assertEqual(ImageSearchJob.objects.filter(status='pending', priority=3).count(), 1)


# ── Candidates ────────────────────────────────────────────────────────────────

class CandidateViewTests(_Base):

    def test_list_filters(self):
        hi = self.cand(total_score=0.9, score_breakdown={'watermark_score': 0.1})
        lo = self.cand(total_score=0.3, score_breakdown={'watermark_score': 0.8})
        self.cand(status='rejected')
        r = self.client_.get(API + 'candidates/')
        self.assertEqual([c['id'] for c in r.data], [hi.id, lo.id])
        r = self.client_.get(API + 'candidates/', {'min_score': '0.5'})
        self.assertEqual([c['id'] for c in r.data], [hi.id])
        r = self.client_.get(API + 'candidates/', {'max_watermark': '0.5', 'item': self.item.id})
        self.assertEqual([c['id'] for c in r.data], [hi.id])
        self.assertEqual(len(self.client_.get(API + 'candidates/', {'status': 'all'}).data), 3)

    def test_review_reject_and_approve(self):
        ProductNormalization.objects.create(item=self.item, brand='ARCOXIA')
        c1 = self.cand(source_type='drugs_com')
        r = self.client_.post(f'{API}candidates/{c1.id}/review/', {'action': 'reject', 'note': 'blurry'},
                              format='json')
        self.assertEqual(r.data, {'status': 'rejected'})
        c1.refresh_from_db()
        self.assertEqual((c1.status, c1.review_note, c1.reviewed_by), ('rejected', 'blurry', self.user))
        c2 = self.cand(source_type='drugs_com', local_file='image_candidates/a.jpg', quality_score=0.8)
        r = self.client_.post(f'{API}candidates/{c2.id}/review/', {'action': 'approve'}, format='json')
        self.assertEqual(r.data, {'status': 'approved'})
        from apps.product_experience.models import ProductMedia
        m = ProductMedia.objects.get(item=self.item)
        self.assertTrue(m.is_primary and m.approved)
        ins = ImageApprovalInsight.objects.get(brand='ARCOXIA', source_type='drugs_com')
        self.assertEqual((ins.approved, ins.considered, ins.avg_quality_score), (1, 2, 0.8))
        self.assertEqual(self.client_.post(f'{API}candidates/{c2.id}/review/', {'action': 'nope'},
                                           format='json').status_code, 400)
        self.assertEqual(self.client_.post(f'{API}candidates/999999/review/', {'action': 'reject'},
                                           format='json').status_code, 404)

    def test_approving_a_candidate_with_no_file_is_refused_and_the_primary_stays(self):
        """The data lifecycle empties unreviewed rows and keeps them. Approving one must not take the primary slot."""
        from apps.product_experience.models import ProductMedia
        primary = self.media_row(is_primary=True)
        for value in ('', None):
            c = self.cand(local_file=value)
            r = self.client_.post(f'{API}candidates/{c.id}/review/', {'action': 'approve'}, format='json')
            self.assertEqual(r.status_code, 400, value)
            self.assertIn('detail', r.data)
            c.refresh_from_db()
            self.assertEqual((c.status, c.reviewed_at), ('pending_review', None))
            primary.refresh_from_db()
            self.assertTrue(primary.is_primary)
            self.assertEqual(list(ProductMedia.objects.filter(item=self.item)), [primary])
            with self.assertRaises(pipeline.CandidateHasNoFile):
                pipeline.approve_candidate(c, user=self.user)
            primary.refresh_from_db()
            self.assertTrue(primary.is_primary)

            # Rejecting such a row still works.
            r = self.client_.post(f'{API}candidates/{c.id}/review/', {'action': 'reject'}, format='json')
            self.assertEqual(r.data, {'status': 'rejected'})

    def test_redownload_runs_worker_and_handles_dead_link(self):
        c = self.cand(status='rejected')
        with mock.patch('apps.images.views.start_thread', side_effect=lambda f, **kw: f()), \
                mock.patch('apps.images.downloader.download_image', return_value=None) as dl:
            r = self.client_.post(f'{API}candidates/{c.id}/redownload/')
        self.assertEqual(r.status_code, 200)
        dl.assert_called_once_with('https://img.example/a.jpg')
        c.refresh_from_db()
        self.assertEqual(c.status, 'rejected')                    # nothing downloaded → unchanged
        self.assertEqual(self.client_.post(f'{API}candidates/999999/redownload/').status_code, 404)

    def test_redownload_rescores(self):
        c = self.cand(status='rejected')
        scores = {'cleaned_bytes': None, 'was_cleaned': False, 'quality_score': 0.7,
                  'confidence_score': 0.6, 'total_score': 0.65, 'breakdown': {'resolution': 1.0},
                  'watermark_score': 0.05, 'width': 8, 'height': 8}
        with mock.patch('apps.images.views.start_thread', side_effect=lambda f, **kw: f()), \
                mock.patch('apps.images.downloader.download_image', return_value=(_png(), 'png')), \
                mock.patch('apps.images.scorer.score_image', return_value=scores), \
                mock.patch('apps.images.scorer.compute_phash', return_value='ff00'):
            self.client_.post(f'{API}candidates/{c.id}/redownload/')
        c.refresh_from_db()
        self.assertEqual((c.status, c.total_score, c.phash, c.width), ('scored', 0.65, 'ff00', 8))
        self.assertEqual(c.score_breakdown, {'resolution': 1.0, 'watermark_score': 0.05})
        self.assertTrue(c.local_file.name)


# ── Product gallery ───────────────────────────────────────────────────────────

class GalleryViewTests(_Base):

    def test_search_with_image_status(self):
        no_img = make_item('BRUFEN 400mg', 'R7M3')
        self.media_row(is_primary=True)
        self.cand()
        r = self.client_.get(API + 'products/search/', {'q': 'R7M', 'has_image': 'yes'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([x['id'] for x in r.data['results']], [self.item.id])
        row = r.data['results'][0]
        self.assertEqual((row['has_image'], row['approved_count'], row['pending_count']), (True, 1, 1))
        self.assertTrue(row['primary_thumb'].endswith('products/x.jpg'))
        r = self.client_.get(API + 'products/search/', {'q': 'R7M', 'has_image': 'no'})
        self.assertEqual([x['id'] for x in r.data['results']], [no_img.id])
        r = self.client_.get(API + 'products/search/', {'q': 'R7M', 'has_image': 'pending',
                                                        'producer_name': 'MSD',
                                                        'category_id': self.item.category_id})
        self.assertEqual((r.data['total'], r.data['pages']), (1, 1))

    def test_gallery_and_item_candidates(self):
        self.media_row(order=1)
        self.media_row(order=0, is_primary=True)
        r = self.client_.get(f'{API}products/{self.item.id}/gallery/')
        self.assertEqual([i['order'] for i in r.data['images']], [0, 1])
        self.assertEqual(self.client_.get(f'{API}products/999999/gallery/').status_code, 404)
        self.cand(status='rejected')
        self.cand()
        self.assertEqual(len(self.client_.get(f'{API}products/{self.item.id}/candidates/').data), 2)
        self.assertEqual(len(self.client_.get(f'{API}products/{self.item.id}/candidates/',
                                              {'status': 'rejected'}).data), 1)
        self.assertEqual(self.client_.get(f'{API}products/999999/candidates/').status_code, 404)

    def test_upload_validates_real_image(self):
        url = f'{API}products/{self.item.id}/upload/'
        self.assertEqual(self.client_.post(url, {}, format='multipart').status_code, 400)
        fake = SimpleUploadedFile('a.png', b'not an image', content_type='image/png')
        self.assertEqual(self.client_.post(url, {'file': fake}, format='multipart').status_code, 400)
        old = self.media_row(is_primary=True)
        good = SimpleUploadedFile('a.png', _png(), content_type='image/png')
        r = self.client_.post(url, {'file': good}, format='multipart')
        self.assertEqual(r.status_code, 201, r.data)
        from apps.product_experience.models import ProductMedia
        new = ProductMedia.objects.get(pk=r.data['media_id'])
        old.refresh_from_db()
        self.assertEqual((new.is_primary, new.source, old.is_primary), (True, 'manual', False))
        self.assertTrue(new.file.name.startswith('products/') or 'manual_R7M1_' in new.file.name)
        self.assertEqual(self.client_.post(f'{API}products/999999/upload/', {}, format='multipart').status_code, 404)

    def test_set_primary_reorder_delete(self):
        a = self.media_row(is_primary=True, order=0)
        b = self.media_row(order=1, approved=False)
        r = self.client_.post(f'{API}products/{self.item.id}/set-primary/{b.id}/')
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.is_primary, b.is_primary, b.approved, b.order), (False, True, True, 0))
        self.assertEqual(self.client_.post(f'{API}products/{self.item.id}/set-primary/999999/').status_code, 404)

        r = self.client_.patch(f'{API}products/{self.item.id}/reorder/', {'order': [a.id, b.id]}, format='json')
        self.assertEqual(r.status_code, 200)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.order, a.is_primary, b.order, b.is_primary), (0, True, 1, False))
        self.assertEqual(self.client_.patch(f'{API}products/{self.item.id}/reorder/', {}, format='json').status_code, 400)

        r = self.client_.delete(f'{API}products/{self.item.id}/images/{a.id}/')
        self.assertEqual(r.status_code, 200)
        b.refresh_from_db()
        self.assertTrue(b.is_primary)                              # next one promoted
        self.assertEqual(self.client_.delete(f'{API}products/{self.item.id}/images/{a.id}/').status_code, 404)


# ── Stats ─────────────────────────────────────────────────────────────────────

class StatsViewTests(_Base):

    def test_report_counts(self):
        self.media_row()
        self.cand()
        self.job(status='failed')
        r = self.client_.get(API + 'report/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['items_with_image'], r.data['pending_review'], r.data['jobs_failed']), (1, 1, 1))
        total = Item.objects.filter(is_active=True).count()
        self.assertEqual(r.data['coverage_pct'], round(1 / total * 100, 1))

    def test_review_queue_and_filter_meta_and_insights(self):
        lo = self.cand(total_score=0.4)
        hi = self.cand(total_score=0.8)
        r = self.client_.get(API + 'review-queue/')
        self.assertEqual([c['id'] for c in r.data], [hi.id, lo.id])
        r = self.client_.get(API + 'filter-meta/')
        self.assertIn('MSD Egypt', r.data['producers'])
        self.assertIn(self.item.category_id, [c['id'] for c in r.data['categories']])
        ImageApprovalInsight.objects.create(brand='ARCOXIA', source_type='drugs_com', approved=3,
                                            considered=4, avg_quality_score=0.75)
        ImageApprovalInsight.objects.create(brand='OTHER', source_type='bing', approved=1, considered=2)
        r = self.client_.get(API + 'insights/')
        self.assertEqual((r.data['total_brands_learned'], r.data['total_approved_tracked']), (2, 4))
        self.assertEqual(r.data['top_sources'], [{
            'brand': 'ARCOXIA', 'source_type': 'drugs_com', 'approved': 3, 'considered': 4,
            'approval_rate': 75.0, 'weight': 1.3, 'avg_quality_score': 75.0}])


# ── Business rules ────────────────────────────────────────────────────────────

class NormalizerRuleTests(TestCase):

    def test_english_name_parse(self):
        item = Item(name='Arcoxia 90 mg film coated 7 tabs', producer_name='MSD Egypt')
        self.assertEqual(normalize_item(item), {
            'canonical_name': 'Arcoxia 90 mg 7 tabs',
            'normalized_name': 'arcoxia 90 mg 7 tabs',
            'search_query_en': 'ARCOXIA 90mg MSD',
            'search_query_ar': 'ARCOXIA 90mg',
            'brand': 'ARCOXIA',
            'strength': '90mg',
            'dosage_form': 'tablet',
            'pack_size': '7 tabs',
            'parse_confidence': 1.0,
        })

    def test_arabic_numerals_shape_and_unit_alias(self):
        item = Item(name='بانادول ٥٠٠ gm', shape_name='Syrup', shape_name_ar='شراب')
        out = normalize_item(item)
        self.assertEqual((out['strength'], out['dosage_form'], out['brand']), ('500g', 'syrup', 'بانادول'))
        self.assertEqual(out['search_query_en'], 'بانادول 500g syrup')
        self.assertEqual(out['search_query_ar'], 'بانادول 500g شراب')

    def test_empty_name_low_confidence(self):
        out = normalize_item(Item(name=''))
        self.assertEqual((out['brand'], out['strength'], out['parse_confidence']), ('', '', 0.3))
        self.assertEqual(out['search_query_en'], '')


class ScorerAndLearningRuleTests(TestCase):

    def test_file_size_score(self):
        self.assertEqual(_score_file_size(4_999), 0.0)
        self.assertAlmostEqual(_score_file_size(10_000), 0.7)
        self.assertEqual(_score_file_size(100_000), 1.0)

    def test_text_match(self):
        self.assertEqual(_score_text_match('', '', '', {}), 0.5)
        meta = {'title': 'Arcoxia 90 tablets'}
        self.assertAlmostEqual(_score_text_match('ARCOXIA', '90mg', 'tablet', meta), (1.0 + 0.8 + 0.6) / 3)
        self.assertEqual(_score_text_match('PANADOL', '', '', meta), 0.0)

    @unittest.skipUnless(HAS_IMAGEHASH, 'imagehash not installed (CI slim set)')
    def test_duplicates(self):
        self.assertTrue(are_duplicates('ffffffffffffffff', 'fffffffffffffff0'))
        self.assertFalse(are_duplicates('ffffffffffffffff', '0000000000000000'))
        self.assertFalse(are_duplicates('', 'ffffffffffffffff'))
        self.assertFalse(are_duplicates('zz', 'ffffffffffffffff'))

    def test_learned_weight(self):
        w = lambda **kw: ImageApprovalInsight(brand='B', source_type='s', **kw).weight  # noqa: E731
        self.assertEqual(w(approved=2, considered=2), 1.0)                         # < 3 considered
        self.assertEqual(w(approved=3, considered=3), 1.5)
        self.assertEqual(w(approved=0, considered=10), 0.5)
        self.assertEqual(w(approved=1, considered=4, avg_quality_score=1.0), 0.85)
        self.assertEqual(ImageApprovalInsight(approved=0, considered=0).approval_rate, 0.0)

    def test_rolling_quality_average(self):
        item = make_item('ARCOXIA R7avg', 'R7M9')
        ProductNormalization.objects.create(item=item, brand='ARCOXIA')
        job = ImageSearchJob.objects.create(item=item)
        for q in (0.6, 0.8):
            c = ImageCandidate.objects.create(job=job, item=item, source_url='https://x/a.jpg',
                                              source_type='bing', quality_score=q)
            pipeline._record_approval_insight(c, approved=True)
        ins = ImageApprovalInsight.objects.get(brand='ARCOXIA', source_type='bing')
        self.assertEqual(ins.approved, 2)
        self.assertAlmostEqual(ins.avg_quality_score, 0.7)


@override_settings(RBAC_ENFORCEMENT='log')
class RunJobPipelineTests(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)
        ov = override_settings(MEDIA_ROOT=self.media)
        ov.enable()
        self.addCleanup(ov.disable)
        self.item = make_item('ARCOXIA 90mg tabs', 'R7P1')
        # run_job closes the DB connection before HTTP I/O — keep the test transaction alive
        p = mock.patch.object(connections['default'], 'close')
        p.start()
        self.addCleanup(p.stop)

    def _scores(self, total):
        return {'cleaned_bytes': None, 'was_cleaned': False, 'quality_score': 0.8,
                'confidence_score': 0.7, 'total_score': total, 'breakdown': {}, 'watermark_score': 0.0,
                'width': 8, 'height': 8, 'format': 'PNG'}

    def _run(self, results, totals, phashes=None):
        job = pipeline.create_job(self.item, priority=2, auto_approve_threshold=0.78)
        it = iter(totals)
        ph = iter(phashes or [''] * len(totals))
        with mock.patch('apps.images.searcher.search_all_sources', return_value=results), \
                mock.patch('apps.images.downloader.download_image', return_value=(_png(), 'png')), \
                mock.patch('apps.images.scorer.score_image', side_effect=lambda *a, **k: self._scores(next(it))), \
                mock.patch('apps.images.scorer.compute_phash', side_effect=lambda b: next(ph)):
            pipeline.run_job(job)
        job.refresh_from_db()
        return job

    def _res(self, n):
        return [{'source_url': f'https://img.example/{i}.jpg', 'source_type': 'drugs_com'} for i in range(n)]

    def test_best_candidate_auto_approved_rest_to_review(self):
        job = self._run(self._res(3), [0.9, 0.5, 0.2])
        self.assertEqual((job.status, job.candidates_found, job.candidates_scored, job.best_score,
                          job.attempt_count), ('done', 3, 2, 0.9, 1))
        statuses = sorted(ImageCandidate.objects.filter(job=job).values_list('status', flat=True))
        self.assertEqual(statuses, ['auto_approved', 'pending_review'])
        norm = ProductNormalization.objects.get(item=self.item)
        self.assertEqual((norm.brand, norm.strength), ('ARCOXIA', '90mg'))

    def test_below_auto_threshold_all_go_to_review(self):
        job = self._run(self._res(2), [0.6, 0.5])
        self.assertEqual(job.status, 'done')
        self.assertEqual(ImageCandidate.objects.filter(job=job, status='pending_review').count(), 2)

    def test_no_results_and_all_low_fail(self):
        job = self._run([], [])
        self.assertEqual((job.status, job.last_error), ('failed', 'No image URLs found in any source'))
        ImageSearchJob.objects.all().delete()
        job = self._run(self._res(1), [0.1])
        self.assertEqual((job.status, job.last_error),
                         ('failed', 'All candidates below quality/watermark threshold'))

    @unittest.skipUnless(HAS_IMAGEHASH, 'imagehash not installed (CI slim set)')
    def test_duplicate_phash_dropped(self):
        job = self._run(self._res(2), [0.6, 0.6], phashes=['ffffffffffffffff', 'fffffffffffffffe'])
        self.assertEqual(job.candidates_scored, 1)

    def test_item_with_image_is_skipped(self):
        from apps.product_experience.models import ProductMedia
        ProductMedia.objects.create(item=self.item, media_type='image', file='products/x.jpg', approved=True)
        job = pipeline.create_job(self.item)
        pipeline.run_job(job)
        job.refresh_from_db()
        self.assertEqual(job.status, 'skipped')
