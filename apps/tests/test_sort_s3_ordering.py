"""
apps/tests/test_sort_s3_ordering.py

Sortable-grid sweep (batch S3): paged / server-cut lists take a whitelisted `ordering`, so the headers sort ALL
rows on the server. Every whitelisted field is requested ascending and descending (rule 9: must be HTTP 200),
plus a small data check per view and the 400 for unknown fields where the view validates.
"""
from django.test import TestCase

from apps.forecasting.models import ForecastRun
from .factories import make_admin, make_item


class _Base(TestCase):
    def setUp(self):
        _, _, self.client = make_admin('sort_s3')

    def every_field(self, url, fields):
        for f in fields:
            for o in (f, '-' + f):
                r = self.client.get(url, {'ordering': o})
                self.assertEqual(r.status_code, 200, '%s ?ordering=%s -> %s' % (url, o, r.status_code))


class ForecastingOrderingTests(_Base):
    def test_every_whitelisted_field_is_200(self):
        self.every_field('/api/forecasting/runs/', ['started_at', 'completed_at', 'items_processed', 'status',
                                                    'triggered_by__user__first_name'])
        self.every_field('/api/forecasting/accuracy/', ['item__name', 'branch__name', 'forecast_date',
                                                        'forecast_30d', 'actual_30d', 'mape', 'mae'])
        self.every_field('/api/forecasting/seasonality/', ['item__name', 'category__name', 'month',
                                                           'index_value', 'computed_at'])

    def test_runs_order_by_items_processed(self):
        for n in (30, 10, 20):
            ForecastRun.objects.create(items_processed=n)
        got = lambda q: [r['items_processed'] for r in
                         self.client.get('/api/forecasting/runs/' + q).data['results']]
        self.assertEqual(got('?ordering=items_processed'), [10, 20, 30])
        self.assertEqual(got('?ordering=-items_processed'), [30, 20, 10])


class OtherPagedListsOrderingTests(_Base):
    def test_ingredient_search_fields(self):
        self.every_field('/api/composition/search/', ['item_name', 'molecule', 'strength_value', 'dosage_form',
                                                      'ingredient_class__name', 'source'])

    def test_pricing_approvals_fields(self):
        self.every_field('/api/pricing-approvals/', ['item__name', 'requested_by__first_name',
                                                     'requested_at', 'status'])

    def test_recommendation_pairs_fields(self):
        self.every_field('/api/recommendations/fbt/', ['score', 'confidence', 'co_occurrences', 'lift', 'support',
                                                       'item_a__name', 'item_b__name'])

    def test_offers_fields(self):
        self.every_field('/api/offers/', ['priority', 'name', 'name_ar', 'offer_type', 'status',
                                          'authorization_source', 'created_at'])


class EnrichmentQueueOrderingTests(_Base):
    def test_fields_and_name_order(self):
        make_item(softech_id='S3-B', name='ب صنف')
        make_item(softech_id='S3-A', name='أ صنف')
        for f in ('completeness_score', 'item__name', 'item__softech_id', 'is_published', 'last_enriched_at',
                  'pending_count_ann'):
            for o in (f, '-' + f):
                r = self.client.get('/api/enrichment/enrichments/', {'ordering': o})
                self.assertEqual(r.status_code, 200, o)
        names = lambda q: [x['item_name'] for x in
                           self.client.get('/api/enrichment/enrichments/' + q).data['results']]
        self.assertEqual(names('?ordering=item__name'), sorted(names('?ordering=item__name')))
        self.assertEqual(names('?ordering=-item__name'), list(reversed(names('?ordering=item__name'))))


class ChronicItemsOrderingTests(_Base):
    def test_fields_and_unknown_is_400(self):
        make_item(softech_id='C-1', name='ب')
        make_item(softech_id='C-2', name='أ')
        for f in ('name', 'softech_id', 'ingredient', 'classification'):
            for o in (f, '-' + f):
                self.assertEqual(self.client.get('/api/chronic/items/', {'ordering': o}).status_code, 200, o)
        self.assertEqual(self.client.get('/api/chronic/items/', {'ordering': 'barcode'}).status_code, 400)
        names = lambda q: [x['name'] for x in self.client.get('/api/chronic/items/' + q).data['results']]
        self.assertEqual(names('?ordering=name'), sorted(names('?ordering=name')))
        self.assertEqual(names('?ordering=-name'), sorted(names('?ordering=name'), reverse=True))


class ImageJobsOrderingTests(_Base):
    def test_fields_and_unknown_is_400(self):
        from apps.images.models import ImageSearchJob
        for code, status in (('I-1', 'done'), ('I-2', 'pending')):
            ImageSearchJob.objects.create(item=make_item(softech_id=code, name=code), status=status)
        for f in ('id', 'item__name', 'status', 'candidates_scored', 'best_score', 'duration',
                  'triggered_by__first_name', 'created_at'):
            for o in (f, '-' + f):
                self.assertEqual(self.client.get('/api/images/jobs/', {'ordering': o}).status_code, 200, o)
        self.assertEqual(self.client.get('/api/images/jobs/', {'ordering': 'last_error'}).status_code, 400)
        ids = lambda q: [x['item_code'] for x in self.client.get('/api/images/jobs/' + q).data]
        self.assertEqual(ids('?ordering=item__name'), ['I-1', 'I-2'])
        self.assertEqual(ids('?ordering=-item__name'), ['I-2', 'I-1'])
