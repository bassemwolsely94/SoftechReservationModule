"""
apps/tests/test_sort_s3_ordering.py

Sortable-grid sweep (batch S3): paged / server-cut lists take a whitelisted `ordering`, so the headers sort ALL
rows on the server. Every view has real rows (an empty table skips the ordered query, so a bad field path
would still answer 200), every whitelisted field is requested ascending and descending (must be HTTP 200),
and each view has one ordering assertion. Equal sort values must page without repeats or gaps (pk tiebreak).
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.forecasting.models import ForecastRun
from .factories import make_admin, make_category, make_item


class _Base(TestCase):
    def setUp(self):
        self.user, self.profile, self.client = make_admin('sort_s3')

    def every_field(self, url, fields):
        for f in fields:
            for o in (f, '-' + f):
                r = self.client.get(url, {'ordering': o})
                self.assertEqual(r.status_code, 200, '%s ?ordering=%s -> %s' % (url, o, r.status_code))


class ForecastingOrderingTests(_Base):
    def setUp(self):
        super().setUp()
        from apps.catalog.models import Category
        from apps.forecasting.models import ForecastAccuracy, SeasonalityIndex
        ForecastRun.objects.create(items_processed=30, triggered_by=self.profile)
        ForecastRun.objects.create(items_processed=10)
        ForecastRun.objects.create(items_processed=20, triggered_by=self.profile)
        for code, name, f in (('F-A', 'أ', 5), ('F-B', 'ب', 9)):
            ForecastAccuracy.objects.create(item=make_item(softech_id=code, name=name), branch=self.profile.branch,
                                            forecast_date=date(2026, 1, f), forecast_30d=Decimal(f))
        cat = make_category()
        SeasonalityIndex.objects.create(item=make_item(softech_id='F-A', name='أ'), month=1, index_value=Decimal('1.1'))
        SeasonalityIndex.objects.create(item=make_item(softech_id='F-B', name='ب'), month=2, index_value=Decimal('0.9'))
        SeasonalityIndex.objects.create(category=cat, month=3, index_value=Decimal('1.0'))   # no item

    def test_every_whitelisted_field_is_200(self):
        self.every_field('/api/forecasting/runs/', ['started_at', 'completed_at', 'items_processed', 'status',
                                                    'triggered_by_sort'])
        self.every_field('/api/forecasting/accuracy/', ['item__name', 'branch__name', 'forecast_date',
                                                        'forecast_30d', 'actual_30d', 'mape', 'mae'])
        self.every_field('/api/forecasting/seasonality/', ['item__name', 'category__name', 'month',
                                                           'index_value', 'computed_at'])

    def test_runs_order_by_items_processed_and_unassigned_last(self):
        got = lambda q: [r['items_processed'] for r in
                         self.client.get('/api/forecasting/runs/' + q).data['results']]
        self.assertEqual(got('?ordering=items_processed'), [10, 20, 30])
        self.assertEqual(got('?ordering=-items_processed'), [30, 20, 10])
        # the run without a staff member (10) is last in both directions of the «بواسطة» key
        self.assertEqual(got('?ordering=triggered_by_sort')[-1], 10)
        self.assertEqual(got('?ordering=-triggered_by_sort')[-1], 10)

    def test_accuracy_order(self):
        got = lambda q: [r['item_name'] for r in self.client.get('/api/forecasting/accuracy/' + q).data['results']]
        self.assertEqual(got('?ordering=forecast_30d'), ['أ', 'ب'])
        self.assertEqual(got('?ordering=-forecast_30d'), ['ب', 'أ'])

    def test_seasonality_category_only_rows_last_both_directions(self):
        got = lambda q: [r['item_name'] for r in self.client.get('/api/forecasting/seasonality/' + q).data['results']]
        self.assertEqual(got('?ordering=item__name'), ['أ', 'ب', ''])
        self.assertEqual(got('?ordering=-item__name'), ['ب', 'أ', ''])


class OtherPagedListsOrderingTests(_Base):
    def test_ingredient_search_fields_and_order(self):
        from apps.composition.models import ItemMoleculeIndex
        for i, (mol, name, sv) in enumerate((('zinc', 'ب', 5), ('amoxil', 'أ', 10))):
            ItemMoleculeIndex.objects.create(item_softech_id='M-%d' % i, aicode=i, molecule=mol, item_name=name,
                                             strength_value=Decimal(sv), dosage_form='قرص')
        self.every_field('/api/composition/search/', ['item_name', 'molecule', 'strength_value', 'dosage_form',
                                                      'ingredient_class__name', 'source'])
        got = lambda q: [r['molecule'] for r in self.client.get('/api/composition/search/' + q).data['results']]
        self.assertEqual(got('?ordering=molecule'), ['amoxil', 'zinc'])
        self.assertEqual(got('?ordering=-molecule'), ['zinc', 'amoxil'])

    def test_pricing_approvals_fields_and_order(self):
        from apps.discount_approvals.models import ItemPriceChangeRequest
        for code, name in (('P-B', 'ب'), ('P-A', 'أ')):
            ItemPriceChangeRequest.objects.create(item=make_item(softech_id=code, name=name), requested_by=self.user,
                                                  old_values={}, new_values={'x': '1'}, reason='r')
        self.every_field('/api/pricing-approvals/', ['item__name', 'requested_by__first_name',
                                                     'requested_at', 'status'])
        got = lambda q: [r['item_name'] for r in self.client.get('/api/pricing-approvals/' + q).data['results']]
        self.assertEqual(got('?ordering=item__name'), ['أ', 'ب'])
        self.assertEqual(got('?ordering=-item__name'), ['ب', 'أ'])

    def test_recommendation_pairs_fields_and_order(self):
        from apps.recommendations.models import FrequentlyBoughtTogether, RecommendationEngineRun
        run = RecommendationEngineRun.objects.create(status='success')
        a, b, c = (make_item(softech_id=x, name=n) for x, n in (('R-A', 'أ'), ('R-B', 'ب'), ('R-C', 'ج')))
        FrequentlyBoughtTogether.objects.create(run=run, item_a=a, item_b=b, score=1, lift=3, support=0.1,
                                                confidence=0.2, co_occurrences=4)
        FrequentlyBoughtTogether.objects.create(run=run, item_a=c, item_b=a, score=2, lift=1, support=0.2,
                                                confidence=0.1, co_occurrences=2)
        self.every_field('/api/recommendations/fbt/', ['score', 'confidence', 'co_occurrences', 'lift', 'support',
                                                       'item_a__name', 'item_b__name'])
        got = lambda q: [r['item_a_name'] for r in self.client.get('/api/recommendations/fbt/' + q).data['results']]
        self.assertEqual(got('?ordering=item_a__name'), ['أ', 'ج'])
        self.assertEqual(got('?ordering=-item_a__name'), ['ج', 'أ'])

    def test_offers_fields_and_order(self):
        from apps.offers.models import Offer
        for name, prio in (('ب', 2), ('أ', 1)):
            Offer.objects.create(name=name, offer_type='bxgy', priority=prio)
        self.every_field('/api/offers/', ['priority', 'name', 'name_ar', 'offer_type', 'status',
                                          'authorization_source', 'created_at'])
        got = lambda q: [r['name'] for r in self.client.get('/api/offers/' + q).data['results']]
        self.assertEqual(got('?ordering=priority'), ['أ', 'ب'])
        self.assertEqual(got('?ordering=-priority'), ['ب', 'أ'])

    def test_equal_sort_values_page_without_repeats_or_gaps(self):
        from apps.offers.models import Offer
        ids = {Offer.objects.create(name='o%d' % i, offer_type='bxgy', priority=1).id for i in range(120)}
        seen = []
        url = '/api/offers/?ordering=priority'
        while url:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            seen += [o['id'] for o in r.data['results']]
            url = r.data['next']
        self.assertEqual(len(seen), len(set(seen)))      # no repeats
        self.assertEqual(set(seen), ids)                 # no gaps


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
        self.assertGreaterEqual(len(names('')), 2)
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
        self.assertGreaterEqual(len(names('')), 2)
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
