"""
Image enrichment — best-seller-first (Pareto) ordering.

Batch launch, revise-all and the review queue must work on the items that sell
the most (by quantity AND value) before the long tail, and the report must show
how much of monthly sales is covered by approved images.
"""
import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.catalog.models import Item
from apps.images import views
from apps.images.models import ImageCandidate, ImageSearchJob
from apps.images.pipeline import build_item_queryset, sales_coverage, sales_ranks
from apps.product_experience.models import ProductMedia
from apps.purchasing.models import DemandCalculationRun, ItemDemandAggregated


class SalesPriorityTests(TestCase):
    def setUp(self):
        self.run = DemandCalculationRun.objects.create(status='success')
        today = datetime.date.today()

        def item(code, qty, value):
            it = Item.objects.create(softech_id=code, name=f'ITEM {code}', is_stockable=True)
            if qty is not None:
                ItemDemandAggregated.objects.create(run=self.run, item=it, calc_date=today,
                                                    total_monthly_avg=qty, total_monthly_value=value)
            return it

        # Names are deliberately in reverse sales order, so name order would be wrong.
        self.both    = item('Z', qty=100, value=10000)   # top on qty AND value
        self.qty     = item('Y', qty=500, value=5)       # top on qty, last on value
        self.value   = item('X', qty=0.5, value=20000)   # top on value, last on qty
        self.weak    = item('W', qty=1,   value=10)      # sells, but little
        self.unsold  = item('A', qty=None, value=None)   # no demand row at all

    def _approve_image(self, item):
        ProductMedia.objects.create(item=item, media_type='image', approved=True, file='x.jpg')

    def test_no_image_scope_is_best_seller_first_not_alphabetical(self):
        got = build_item_queryset({'scope': 'no_image', 'limit': 10})
        self.assertEqual(got[0], self.both)                  # strong on both measures leads
        self.assertEqual(got[-2], self.weak)
        self.assertEqual(got[-1], self.unsold)               # no sales → last

    def test_combined_score_balances_qty_and_value(self):
        ranks = sales_ranks()
        self.assertGreater(ranks[self.both.id]['score'], ranks[self.qty.id]['score'])
        self.assertGreater(ranks[self.both.id]['score'], ranks[self.value.id]['score'])
        self.assertNotIn(self.unsold.id, ranks)

    def test_no_image_scope_skips_items_already_done(self):
        self._approve_image(self.both)
        got = build_item_queryset({'scope': 'no_image', 'limit': 10})
        self.assertNotIn(self.both, got)

    def test_limit_takes_the_top_sellers(self):
        got = build_item_queryset({'scope': 'no_image', 'limit': 1})
        self.assertEqual(got, [self.both])

    def test_single_measure_scopes(self):
        self.assertEqual(build_item_queryset({'scope': 'top_qty', 'limit': 1}), [self.qty])
        self.assertEqual(build_item_queryset({'scope': 'top_value', 'limit': 1}), [self.value])
        # sold-only: the unsold item never appears
        self.assertNotIn(self.unsold, build_item_queryset({'scope': 'top_qty', 'limit': 10}))

    def test_all_active_scope_keeps_items_with_images_but_ranked(self):
        self._approve_image(self.both)
        got = build_item_queryset({'scope': 'all_active', 'limit': 10})
        self.assertEqual(got[0], self.both)

    def test_falls_back_to_name_order_without_a_demand_run(self):
        self.run.status = 'failed'
        self.run.save()
        names = [i.name for i in build_item_queryset({'scope': 'no_image', 'limit': 10})]
        self.assertEqual(names, sorted(names))

    def test_sales_coverage(self):
        self._approve_image(self.value)                      # 20000 of 30015 value, 0.5 of 601.5 qty
        cov = sales_coverage()
        self.assertEqual(cov['sales_coverage_value_pct'], round(20000 / 30015 * 100, 1))
        self.assertEqual(cov['sales_coverage_qty_pct'], round(0.5 / 601.5 * 100, 1))
        self.assertEqual(cov['sold_items'], 4)
        self.assertEqual(cov['sold_items_with_image'], 1)

    def _get(self, view, path):
        user = get_user_model().objects.create_user(username='u', password='x')
        req = APIRequestFactory().get(path)
        force_authenticate(req, user=user)
        return view(req)

    def test_review_queue_puts_best_sellers_first(self):
        def cand(item, score):
            job = ImageSearchJob.objects.create(item=item)
            return ImageCandidate.objects.create(job=job, item=item, source_url='http://x/a.jpg',
                                                 status='pending_review', total_score=score)
        weak_hi = cand(self.weak, 0.95)
        both_lo = cand(self.both, 0.50)
        both_hi = cand(self.both, 0.70)
        resp = self._get(views.review_queue, '/api/images/review-queue/')
        self.assertEqual([c['id'] for c in resp.data], [both_hi.id, both_lo.id, weak_hi.id])

    def test_report_includes_sales_coverage(self):
        resp = self._get(views.images_report, '/api/images/report/')
        for key in ('sales_coverage_value_pct', 'sales_coverage_qty_pct', 'sold_items'):
            self.assertIn(key, resp.data)
