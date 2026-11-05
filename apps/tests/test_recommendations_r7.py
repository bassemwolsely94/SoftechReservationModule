"""
apps/tests/test_recommendations_r7.py — R7 per-app coverage for apps.recommendations.

Route groups (/api/recommendations/) → tests:
  run/            latest_run         RecommendationApiTests.test_latest_run
  runs/           EngineRunListView  RecommendationApiTests.test_runs_list
  trigger/        trigger_engine     RecommendationApiTests.test_trigger_runs_engine / _conflict
  fbt/            FBTPairListView    RecommendationApiTests.test_fbt_list
  fbt/for-item/   fbt_for_item       RecommendationApiTests.test_fbt_for_item
  customer/       customer_recs      RecommendationApiTests.test_customer_recs
  basket-intel/   basket_intel       RecommendationApiTests.test_basket_intel_params
                                     (ranking itself is in test_basket_intelligence.py)

Permission: RecommendationPermissionTests (only admin / supervisor may start the engine).
Business rules: FbtEngineRuleTests (exact confidence / support / lift / score from synthetic
baskets; customer recs) and ClinicalSafetyFilterTests (a major interaction removes the
recommendation — pharmacy safety beats sales).
"""
import math
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.chronic.models import DrugInteraction
from apps.customers.models import CustomerHealthProfile, PurchaseHistory, PurchaseHistoryLine
from apps.recommendations.engine import get_customer_recs, get_fbt_for_item, run_fbt_engine
from apps.recommendations.models import (
    CustomerRecommendation, FrequentlyBoughtTogether, RecommendationEngineRun,
)
from apps.tests.factories import make_branch, make_customer, make_item, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

API = '/api/recommendations'


def _baskets():
    """10 invoices: 4×{A,B}, 2×{A}, 4×{C}. Customer X owns one {A} invoice."""
    branch = make_branch()
    a, b, c = make_item('Alpha', 'RC001'), make_item('Beta', 'RC002'), make_item('Gamma', 'RC003')
    other = make_customer('آخر', '01000000101')
    x = make_customer('عميل', '01000000102')
    plan = [[a, b]] * 4 + [[a]] * 2 + [[c]] * 4
    for n, items in enumerate(plan):
        ph = PurchaseHistory.objects.create(
            customer=x if n == 4 else other, softech_invoice_id=f'R7REC-{n}', branch=branch,
            doc_code='115', total_amount=Decimal('10'), invoice_date=timezone.now())
        for it in items:
            PurchaseHistoryLine.objects.create(purchase=ph, item=it, quantity=1, unit_price=10, line_total=10)
    return a, b, c, x


class FbtEngineRuleTests(TestCase):

    def test_pair_metrics_are_exact(self):
        a, b, c, x = _baskets()
        run = RecommendationEngineRun.objects.get(pk=run_fbt_engine(min_support=0.01, min_confidence=0.05))
        self.assertEqual((run.status, run.invoices_scanned, run.pairs_generated), ('success', 10, 2))
        ab = FrequentlyBoughtTogether.objects.get(run=run, item_a=a, item_b=b)
        ba = FrequentlyBoughtTogether.objects.get(run=run, item_a=b, item_b=a)
        self.assertEqual((ab.co_occurrences, ab.item_a_occurrences), (4, 6))
        self.assertEqual((ab.confidence, ab.support, ab.lift), (0.666667, 0.4, 1.6667))   # 4/6, 4/10, (4/6)/(4/10)
        self.assertEqual(ab.score, round(4 / 6 * math.log(5), 6))
        self.assertEqual((ba.confidence, ba.lift, ba.score), (1.0, 1.6667, round(math.log(5), 6)))
        self.assertFalse(FrequentlyBoughtTogether.objects.filter(run=run, item_a=c).exists())

        # Customer X bought only A → B is recommended, weighted by log(qty+1)
        rec = CustomerRecommendation.objects.get(run=run)
        self.assertEqual((rec.customer_id, rec.item_id), (x.id, b.id))
        self.assertEqual(rec.score, round(4 / 6 * math.log(5) * math.log(2), 6))
        self.assertEqual(rec.reason, 'اشترى معه 67% من العملاء')
        self.assertEqual(run.customers_scored, 1)

        self.assertEqual([r['softech_id'] for r in get_fbt_for_item(a.id)], ['RC002'])
        self.assertEqual(get_customer_recs(x.id)[0]['reason'], 'اشترى معه 67% من العملاء')

    def test_thresholds_filter_pairs(self):
        _baskets()
        run = RecommendationEngineRun.objects.get(pk=run_fbt_engine(min_support=0.5))      # 0.4 < 0.5
        self.assertEqual(run.pairs_generated, 0)
        run = RecommendationEngineRun.objects.get(pk=run_fbt_engine(min_support=0.01, min_confidence=0.9))
        self.assertEqual(run.pairs_generated, 1)                                             # only B→A (1.0)

    def test_too_few_invoices_skips_mining(self):
        run = RecommendationEngineRun.objects.get(pk=run_fbt_engine())
        self.assertEqual((run.status, run.invoices_scanned, run.pairs_generated), ('success', 0, 0))
        self.assertEqual(get_fbt_for_item(1), [])

    def test_failure_marks_run_failed(self):
        with mock.patch('apps.customers.models.PurchaseHistoryLine.objects.filter', side_effect=RuntimeError('db')):
            with self.assertRaises(RuntimeError):
                run_fbt_engine()
        run = RecommendationEngineRun.objects.get()
        self.assertEqual((run.status, run.error_message), ('failed', 'db'))

    def test_no_successful_run_means_no_recs(self):
        RecommendationEngineRun.objects.create(status='failed')
        self.assertEqual((get_fbt_for_item(1), get_customer_recs(1)), ([], []))


class ClinicalSafetyFilterTests(TestCase):
    """CLAUDE.md rule 4: an item with a MAJOR interaction against the customer's own medicines
    or declared allergies is never recommended."""

    def setUp(self):
        self.run = RecommendationEngineRun.objects.create(status='success')
        self.cust = make_customer('مريض', '01000000201')
        self.risky = make_item('Aspocid', 'RC010')
        self.risky.active_ingredients = 'Aspirin, Caffeine'
        self.risky.save()
        self.safe = make_item('Vitamin', 'RC011')
        for item, score in ((self.risky, 0.9), (self.safe, 0.5)):
            CustomerRecommendation.objects.create(run=self.run, customer=self.cust, item=item, score=score)
        DrugInteraction.objects.create(ingredient_a='aspirin', ingredient_b='warfarin', severity='major')

    def _codes(self, **kw):
        return [r['softech_id'] for r in get_customer_recs(self.cust.id, **kw)]

    def test_major_interaction_removes_item(self):
        self.assertEqual(self._codes(), ['RC010', 'RC011'])                  # no health profile yet
        CustomerHealthProfile.objects.create(customer=self.cust, active_medications=[{'ingredient': 'Warfarin'}])
        self.assertEqual(self._codes(), ['RC011'])
        self.assertEqual(self._codes(apply_clinical_filter=False), ['RC010', 'RC011'])

    def test_allergy_and_non_major_interactions(self):
        DrugInteraction.objects.create(ingredient_a='caffeine', ingredient_b='lithium', severity='moderate')
        hp = CustomerHealthProfile.objects.create(customer=self.cust, active_medications=[{'ingredient': 'lithium'}])
        self.assertEqual(self._codes(), ['RC010', 'RC011'])                  # moderate only → kept
        hp.known_allergies = [{'ingredient': 'Warfarin'}]
        hp.save()
        self.assertEqual(self._codes(), ['RC011'])
        self.assertEqual(self._codes(limit=1), ['RC011'])


class RecommendationApiTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _, _, cls.admin = make_user('r7rec_admin', role='admin', access_all=True)
        _, _, cls.pharm = make_user('r7rec_pharm', role='pharmacist')

    def test_latest_run(self):
        self.assertEqual(self.pharm.get(f'{API}/run/').status_code, 404)
        run = RecommendationEngineRun.objects.create(status='success', pairs_generated=3)
        r = self.pharm.get(f'{API}/run/')
        self.assertEqual((r.status_code, r.data['id'], r.data['pairs_generated']), (200, run.id, 3))

    def test_runs_list(self):
        RecommendationEngineRun.objects.create(status='failed')
        r = self.pharm.get(f'{API}/runs/')
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual([x['status'] for x in rows], ['failed'])

    def test_trigger_runs_engine(self):
        _baskets()
        with mock.patch('apps.recommendations.views.start_thread', side_effect=lambda fn: fn()):
            r = self.admin.post(f'{API}/trigger/', {'lookback_days': 30, 'min_support': 0.01,
                                                    'min_confidence': 0.05}, format='json')
        self.assertEqual((r.status_code, r.data['queued']), (200, True))
        run = RecommendationEngineRun.objects.get()
        self.assertEqual((run.status, run.lookback_days, run.min_support, run.pairs_generated),
                         ('success', 30, 0.01, 2))

    def test_trigger_conflict_when_running(self):
        RecommendationEngineRun.objects.create(status='running')
        with mock.patch('apps.recommendations.views.start_thread') as st:
            self.assertEqual(self.admin.post(f'{API}/trigger/').status_code, 409)
        st.assert_not_called()

    def test_fbt_list(self):
        a, b, c, _ = _baskets()
        empty = self.pharm.get(f'{API}/fbt/').data                  # no successful run yet
        self.assertEqual(len(empty['results'] if isinstance(empty, dict) else empty), 0)
        run_fbt_engine(min_support=0.01)
        r = self.pharm.get(f'{API}/fbt/', {'item_a': a.id})
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual([(x['item_a'], x['item_b']) for x in rows], [(a.id, b.id)])
        r = self.pharm.get(f'{API}/fbt/', {'search': 'Beta', 'ordering': 'confidence'})
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual([x['confidence'] for x in rows], [0.666667, 1.0])

    def test_fbt_for_item(self):
        a, *_ = _baskets()
        run_fbt_engine(min_support=0.01)
        self.assertEqual(self.pharm.get(f'{API}/fbt/for-item/').status_code, 400)
        r = self.pharm.get(f'{API}/fbt/for-item/', {'item_id': a.id, 'limit': 50})
        self.assertEqual([x['softech_id'] for x in r.data], ['RC002'])
        self.assertEqual(r.data[0]['co_occurrences'], 4)

    def test_customer_recs(self):
        *_, x = _baskets()
        run_fbt_engine(min_support=0.01)
        self.assertEqual(self.pharm.get(f'{API}/customer/').status_code, 400)
        r = self.pharm.get(f'{API}/customer/', {'customer_id': x.id})
        self.assertEqual([(i['softech_id'], i['clinical_safe']) for i in r.data], [('RC002', True)])

    def test_basket_intel_params(self):
        r = self.pharm.get(f'{API}/basket-intel/', {'items': ' , ', 'customer': 'abc', 'branch': 'x',
                                                    'limit': 'lots'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, {'count': 0, 'results': []})

    def test_bad_numbers_are_400_not_500(self):
        self.assertEqual(self.pharm.get(f'{API}/fbt/for-item/', {'item_id': 'abc'}).status_code, 400)
        self.assertEqual(self.pharm.get(f'{API}/fbt/for-item/', {'item_id': 1, 'limit': 'x'}).status_code, 400)
        self.assertEqual(self.pharm.get(f'{API}/customer/', {'customer_id': 'abc'}).status_code, 400)

    def test_trigger_bad_numbers_are_400_not_500(self):
        with mock.patch('apps.recommendations.views.start_thread'):
            r = self.admin.post(f'{API}/trigger/', {'lookback_days': 'year'}, format='json')
        self.assertEqual(r.status_code, 400)


@override_settings(RBAC_ENFORCEMENT='log')
class RecommendationPermissionTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def test_only_admin_or_supervisor_may_trigger(self):
        with mock.patch('apps.recommendations.views.start_thread') as st:
            for role in ('pharmacist', 'salesperson', 'call_center', 'viewer'):
                client = bearer_client(make_user(f'r7rec_{role}', role=role)[0])
                self.assertEqual(client.post(f'{API}/trigger/').status_code, 403, role)
            st.assert_not_called()
            sup = bearer_client(make_user('r7rec_sup', role='supervisor', access_all=True)[0])
            self.assertEqual(sup.post(f'{API}/trigger/').status_code, 200)
        self.assertEqual(st.call_count, 1)
        self.assertFalse(RecommendationEngineRun.objects.exists())   # thread mocked: nothing started
