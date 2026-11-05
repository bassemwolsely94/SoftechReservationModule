"""
apps/tests/test_enrichment_r7.py — R7 per-app coverage for apps.enrichment.

Route groups (apps/enrichment/urls.py, mounted at /api/enrichment/):
  enrichments/            ItemEnrichmentViewSet       → EnrichmentQueueApiTests
  suggestions/            EnrichmentSuggestionViewSet → SuggestionReviewApiTests
  batches/                EnrichmentBatchViewSet      → BatchApiTests
  report/                 completeness_report         → ReportAndItemApiTests
  recompute-scores/       recompute_scores            → ReportAndItemApiTests
  items/<pk>/             item_enrichment_detail      → ReportAndItemApiTests
  items/<pk>/generate/    generate_for_item           → ReportAndItemApiTests

Permission: EnrichmentPermissionTests (catalog matrix — a salesperson is read-only on catalog).
Business rules: GeneratorRuleTests (exact rule-engine output, score maths) and
BatchAutoPublishRuleTests (a real batch auto-publishes only descriptive fields; clinical fields
stay pending). Every AI / OpenFDA call is mocked; nothing leaves the process.
"""
import json
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from apps.enrichment import ai_extractor
from apps.enrichment import suggestion_generator as sg
from apps.enrichment.gap_detector import compute_item_score, get_completeness_report, recompute_all_scores
from apps.enrichment.models import (
    ENRICHABLE_FIELDS, EnrichmentApprovalLog, EnrichmentBatch, EnrichmentSuggestion, ItemEnrichment,
)
from apps.tests.factories import make_item, make_user
from apps.tests.security.fixtures import bearer_client, seed_code_matrix
from core.middleware import module_access

BASE = '/api/enrichment'
NO_AI = mock.patch.object(sg, '_call_ai_extractor', return_value={})


def _rich_item(code='EN001', name='Panadol 500mg 20 tab'):
    item = make_item(name=name, softech_id=code)
    item.producer_name = 'GSK'
    item.origin_name_ar = 'مصر'
    item.origin_name = 'Egypt'
    item.shape_name_ar = 'أقراص'
    item.shape_name = 'Tablets'
    item.pack_qty = 20
    item.unit_name = 'قرص'
    item.effect_name_ar = 'مسكن'
    item.effect_name = 'Analgesic'
    item.medicine_type_name = 'OTC'
    item.active_ingredients = 'paracetamol'
    item.requires_fridge = False
    item.is_active = item.is_stockable = True
    item.save()
    return item


def _sug(item, field, value, conf=0.8, status='pending', source='rule_engine'):
    enr, _ = ItemEnrichment.objects.get_or_create(item=item)
    return EnrichmentSuggestion.objects.create(
        item=item, enrichment=enr, field_name=field, suggested_value=value,
        source=source, confidence=conf, status=status)


# ── business rules ───────────────────────────────────────────────────────────

class GeneratorRuleTests(TestCase):

    def test_rule_engine_output_is_exact(self):
        item = _rich_item()
        with NO_AI:
            out = {c['field_name']: (c['suggested_value'], c['source'], c['confidence'])
                   for c in sg.generate_suggestions_for_item(item)}
        self.assertEqual(out['brand_name'], ('Panadol', 'rule_engine', 0.72))
        self.assertEqual(out['strength'], ('500mg', 'rule_engine', 0.72))
        self.assertEqual(out['manufacturer_en'], ('GSK', 'softech', 0.92))
        self.assertEqual(out['manufacturer_ar'], ('GSK', 'softech', 0.72))
        self.assertEqual(out['country_ar'], ('مصر', 'softech', 0.92))
        self.assertEqual(out['country_en'], ('Egypt', 'softech', 0.92))
        self.assertEqual(out['dosage_form_ar'], ('أقراص', 'softech', 0.92))
        self.assertEqual(out['dosage_form_en'], ('Tablets', 'softech', 0.92))
        self.assertEqual(out['pack_size_label'], ('20 قرص', 'softech', 0.92))
        self.assertEqual(out['indication_ar'], ('مسكن', 'softech', 0.92))
        self.assertEqual(out['indication_en'], ('Analgesic', 'softech', 0.92))
        self.assertEqual(out['rx_otc'], ('otc', 'softech', 0.92))
        self.assertEqual(out['name_ar'], ('Panadol — مسكن (أقراص)', 'rule_engine', 0.45))
        self.assertEqual(out['storage_condition'][1:], ('rule_engine', 0.45))
        self.assertEqual(out['medical_keywords_ar'], ('مسكن, paracetamol', 'softech', 0.72))
        self.assertEqual(out['medical_keywords_en'], ('Analgesic', 'softech', 0.72))
        self.assertEqual(out['seo_desc_ar'][0], 'Panadol 500mg 20 tab 500mg مسكن أقراص')
        self.assertNotIn('volume', out)   # no ml in the name

    def test_existing_pending_and_filled_fields_are_skipped(self):
        item = _rich_item()
        _sug(item, 'brand_name', 'X')
        enr = ItemEnrichment.objects.get(item=item)
        enr.country_en = 'Egypt'
        enr.save()
        with NO_AI:
            fields = {c['field_name'] for c in sg.generate_suggestions_for_item(item)}
            self.assertNotIn('brand_name', fields)
            self.assertNotIn('country_en', fields)
            self.assertIn('brand_name', {c['field_name'] for c in
                                         sg.generate_suggestions_for_item(item, overwrite_pending=True)})

    def test_fridge_and_rx_and_ai_fields(self):
        item = _rich_item('EN002', 'Insulin 100iu 10ml')
        item.requires_fridge = True
        item.medicine_type_name = 'Prescription'
        item.save()
        with mock.patch.object(sg, '_call_ai_extractor',
                               return_value={'atc_code': 'A10AB01', 'unknown_field': 'x'}):
            out = {c['field_name']: c for c in sg.generate_suggestions_for_item(item)}
        self.assertEqual(out['storage_condition']['suggested_value'], 'يحفظ في الثلاجة (2-8°م)')
        self.assertEqual(out['rx_otc']['suggested_value'], 'rx')
        self.assertEqual(out['volume']['suggested_value'], '10ml')
        self.assertEqual(out['strength']['suggested_value'], '100iu')
        self.assertEqual(out['atc_code']['source'], 'ai_extract')
        self.assertEqual(out['atc_code']['confidence'], 0.80)
        self.assertNotIn('unknown_field', out)

    def test_ai_extractor_failure_degrades_to_empty(self):
        item = make_item('Zzz', 'EN003')
        with mock.patch('apps.enrichment.ai_extractor.enrich_item_with_ai', side_effect=RuntimeError('x')):
            self.assertEqual(sg._call_ai_extractor(item), {})

    def test_completeness_score_maths(self):
        self.assertEqual(len(ENRICHABLE_FIELDS), 33)
        item = make_item('Score', 'EN004')
        enr, _ = ItemEnrichment.objects.get_or_create(item=item)
        self.assertEqual(enr.compute_score(), 0.0)
        enr.brand_name, enr.strength, enr.volume = 'B', '5mg', '10ml'
        self.assertEqual(enr.compute_score(), 9.1)            # 3/33 → 9.09 → 9.1
        enr.save()
        self.assertEqual(compute_item_score(item), 9.1)

    def test_recompute_all_scores_buckets(self):
        a, b = make_item('A1', 'EN005'), make_item('B1', 'EN006')
        enr = ItemEnrichment.objects.create(item=a)
        for f in ENRICHABLE_FIELDS[:27]:                       # 27/33 = 81.8 → complete
            setattr(enr, f, 'x' if f not in ('image_url', 'image_secondary_url') else 'http://x.test/a.png')
        enr.save()
        res = recompute_all_scores()
        mine = {e.item_id: e.completeness_score for e in ItemEnrichment.objects.filter(item__in=[a, b])}
        self.assertEqual(mine, {a.id: 81.8, b.id: 0.0})
        self.assertGreaterEqual(res['complete_80pct_plus'], 1)
        self.assertEqual(res['total'], res['complete_80pct_plus'] + res['partial_20_to_80'] + res['empty_under_20'])

    def test_batch_progress_pct(self):
        self.assertEqual(EnrichmentBatch(total_items=0).progress_pct, 0)
        self.assertEqual(EnrichmentBatch(total_items=3, processed_items=1).progress_pct, 33.3)


class BatchAutoPublishRuleTests(TestCase):
    """The real generator through a real batch: descriptive high-confidence fields auto-publish,
    clinical ones (indication, rx/otc, storage) always wait for a pharmacist (CLAUDE.md rule 10)."""

    def test_batch_auto_publishes_descriptive_only(self):
        item = _rich_item()
        batch = EnrichmentBatch.objects.create(scope_type='selected', scope_params={'item_ids': [item.pk]},
                                               auto_publish_threshold=0.9)
        with NO_AI:
            sg.bulk_generate_suggestions(batch)
        st = dict(EnrichmentSuggestion.objects.filter(item=item).values_list('field_name', 'status'))
        approved = {f for f, s in st.items() if s == 'approved'}
        self.assertEqual(approved, {'manufacturer_en', 'country_ar', 'country_en',
                                    'dosage_form_ar', 'dosage_form_en', 'pack_size_label'})
        for clinical in ('indication_ar', 'indication_en', 'rx_otc', 'storage_condition'):
            self.assertEqual(st[clinical], 'pending', clinical)
        enr = ItemEnrichment.objects.get(item=item)
        self.assertEqual((enr.manufacturer_en, enr.pack_size_label), ('GSK', '20 قرص'))
        self.assertEqual((enr.indication_ar, enr.rx_otc, enr.storage_condition), ('', '', ''))
        self.assertEqual(enr.completeness_score, 18.2)          # 6/33
        batch.refresh_from_db()
        self.assertEqual((batch.status, batch.total_items, batch.processed_items, batch.auto_published),
                         ('success', 1, 1, 6))
        self.assertEqual(batch.suggestions_generated, len(st))

    def test_batch_scopes_and_error_path(self):
        item = _rich_item()
        for scope, params in (('category', {'category_id': item.category_id}),
                              ('supplier', {'supplier_code': 'NOPE'}),
                              ('low_score', {'threshold': 50})):
            b = EnrichmentBatch.objects.create(scope_type=scope, scope_params=params)
            with mock.patch.object(sg, 'generate_suggestions_for_item', return_value=[]):
                sg.bulk_generate_suggestions(b)
            b.refresh_from_db()
            self.assertEqual(b.status, 'success', scope)
        self.assertEqual(EnrichmentBatch.objects.get(scope_type='supplier').total_items, 0)
        b = EnrichmentBatch.objects.create(scope_type='selected', scope_params={'item_ids': [item.pk]})
        with mock.patch.object(sg, 'generate_suggestions_for_item', side_effect=ValueError('boom')):
            sg.bulk_generate_suggestions(b)
        b.refresh_from_db()
        self.assertEqual((b.status, b.error_count), ('failed', 1))
        self.assertIn('boom', b.error_log)


# ── AI extractor pure helpers (no network) ───────────────────────────────────

class AiExtractorHelperTests(SimpleTestCase):

    def test_clean_result_filters_fields_and_bad_rx(self):
        self.assertEqual(ai_extractor._clean_result({'brand_name': ' Panadol ', 'rx_otc': 'maybe',
                                                     'atc_code': '""', 'bogus': 'x'}),
                         {'brand_name': 'Panadol'})
        self.assertEqual(ai_extractor._clean_result({'rx_otc': 'rx'}), {'rx_otc': 'rx'})

    def test_extract_json(self):
        self.assertEqual(ai_extractor._extract_json('```json\n{"a": 1}\n```'), {'a': 1})
        self.assertEqual(ai_extractor._extract_json('no json'), {})
        self.assertEqual(ai_extractor._extract_json('{bad json}'), {})

    def test_fda_join_truncates(self):
        self.assertEqual(ai_extractor._fda_join([]), '')
        self.assertEqual(ai_extractor._fda_join(['a  b', 'c']), 'a b c')
        self.assertEqual(ai_extractor._fda_join(['aaa bbb ccc'], max_chars=6), 'aaa…')

    def _fake_urlopen(self, payload):
        resp = mock.MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        cm = mock.MagicMock()
        cm.__enter__.return_value = resp
        return mock.patch.object(ai_extractor.urllib.request, 'urlopen', return_value=cm)

    def test_scrape_openfda_maps_label(self):
        label = {'indications_and_usage': ['Pain relief'], 'warnings': ['Liver'],
                 'adverse_reactions': ['Nausea'], 'drug_interactions': ['Warfarin'],
                 'pregnancy': ['Pregnancy Category C applies'], 'dosage_and_administration': ['1 tab'],
                 'openfda': {'pharm_class_epc': ['Analgesic'], 'product_type': ['HUMAN OTC DRUG']}}
        with self._fake_urlopen({'results': [label]}):
            out = ai_extractor.scrape_openfda('Panadol 500')
        self.assertEqual(out, {'indication_en': 'Pain relief', 'warning_ar': 'Liver',
                               'side_effects_en': 'Nausea', 'drug_interactions_ar': 'Warfarin',
                               'pregnancy_category': 'C', 'dosage_ar': '1 tab',
                               'medical_keywords_en': 'Analgesic', 'rx_otc': 'otc'})
        with self._fake_urlopen({'results': []}):
            self.assertEqual(ai_extractor.scrape_openfda('Panadol'), {})
        self.assertEqual(ai_extractor.scrape_openfda('ab'), {})            # brand too short
        with mock.patch.object(ai_extractor.urllib.request, 'urlopen', side_effect=OSError('offline')):
            self.assertEqual(ai_extractor.scrape_openfda('Panadol'), {})

    @override_settings(GEMINI_API_KEY='', GEMINI_API_KEY_2='', OPENAI_API_KEY='')
    def test_provider_chain_without_keys_returns_empty(self):
        item = mock.MagicMock(pk=1)
        self.assertEqual(ai_extractor._provider_chain(item, 'p'), ({}, ''))

    @override_settings(GEMINI_API_KEY='k1', GEMINI_API_KEY_2='', OPENAI_API_KEY='k3',
                       GEMINI_MODEL='g', OPENAI_MODEL='o')
    def test_provider_chain_falls_through_to_openai(self):
        item = mock.MagicMock(pk=1)
        with mock.patch.object(ai_extractor, '_call_gemini', return_value={}) as g, \
                mock.patch.object(ai_extractor, '_call_openai', return_value={'brand_name': 'B'}):
            self.assertEqual(ai_extractor._provider_chain(item, 'p'), ({'brand_name': 'B'}, 'o'))
        self.assertEqual(g.call_count, 1)

    def test_enrich_item_merges_fda_under_ai(self):
        item = mock.MagicMock(name='x')
        with mock.patch.object(ai_extractor, 'scrape_openfda', return_value={'a': 'fda', 'b': 'fda'}), \
                mock.patch.object(ai_extractor, 'extract_with_ai_fallback', return_value={'b': 'ai'}):
            self.assertEqual(ai_extractor.enrich_item_with_ai(item), {'a': 'fda', 'b': 'ai'})


# ── API: route groups ────────────────────────────────────────────────────────

class _ApiBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user, cls.profile, cls.client_ = make_user('r7enr_admin', role='admin', access_all=True)
        cls.item = _rich_item()


class EnrichmentQueueApiTests(_ApiBase):

    def test_list_creates_stubs_filters_and_orders(self):
        other = make_item('Brufen 400mg', 'EN010')
        r = self.client_.get(f'{BASE}/enrichments/', {'search': 'Panadol', 'ordering': '-item__name'})
        self.assertEqual(r.status_code, 200)
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual([x['item_code'] for x in rows], ['EN001'])
        self.assertTrue(ItemEnrichment.objects.filter(item=other).exists())   # stub created
        _sug(self.item, 'brand_name', 'Panadol')
        r = self.client_.get(f'{BASE}/enrichments/', {'has_pending': '1', 'score_min': '0', 'score_max': 'x',
                                                      'is_published': 'false', 'category': 'zz-none',
                                                      'ordering': 'bogus'})
        self.assertEqual(r.status_code, 200)
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual(rows, [])
        r = self.client_.get(f'{BASE}/enrichments/', {'has_pending': 'true', 'category': str(self.item.category_id)})
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual([(x['item_code'], x['pending_count']) for x in rows], [('EN001', 1)])

    def test_patch_updates_field_and_score(self):
        enr, _ = ItemEnrichment.objects.get_or_create(item=self.item)
        r = self.client_.patch(f'{BASE}/enrichments/{enr.pk}/', {'brand_name': 'Panadol'}, format='json')
        self.assertEqual(r.status_code, 200)
        enr.refresh_from_db()
        self.assertEqual((enr.brand_name, enr.completeness_score, enr.enriched_by_id),
                         ('Panadol', 3.0, self.user.id))
        self.assertEqual(self.client_.get(f'{BASE}/enrichments/{enr.pk}/').data['pending_count'], 0)
        self.assertEqual(self.client_.delete(f'{BASE}/enrichments/{enr.pk}/').status_code, 405)


class SuggestionReviewApiTests(_ApiBase):

    def test_list_filters(self):
        s = _sug(self.item, 'brand_name', 'Panadol', conf=0.9)
        _sug(self.item, 'strength', '500mg', status='rejected')
        r = self.client_.get(f'{BASE}/suggestions/', {'item': self.item.pk, 'field': 'brand_name', 'batch': ''})
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual([x['id'] for x in rows], [s.id])
        r = self.client_.get(f'{BASE}/suggestions/', {'item': self.item.pk, 'status': 'all'})
        rows = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual(len(rows), 2)

    def test_approve_as_is_and_edited_and_twice(self):
        s = _sug(self.item, 'brand_name', 'Panadol', conf=0.9)
        r = self.client_.post(f'{BASE}/suggestions/{s.pk}/approve/', {}, format='json')
        self.assertEqual((r.status_code, r.data['status']), (200, 'approved'))
        self.assertEqual(ItemEnrichment.objects.get(item=self.item).brand_name, 'Panadol')
        # a reviewed row leaves the default (pending) queue; addressed with status=all it is refused
        self.assertEqual(self.client_.post(f'{BASE}/suggestions/{s.pk}/approve/').status_code, 404)
        r = self.client_.post(f'{BASE}/suggestions/{s.pk}/approve/?status=all', {}, format='json')
        self.assertEqual(r.status_code, 400)                       # already reviewed
        s2 = _sug(self.item, 'strength', '500mg')
        r = self.client_.post(f'{BASE}/suggestions/{s2.pk}/approve/', {'value': '500 mg'}, format='json')
        self.assertEqual((r.data['status'], r.data['approved_value']), ('edited', '500 mg'))
        log = EnrichmentApprovalLog.objects.get(field_name='strength')
        self.assertEqual((log.outcome, log.accepted_value, log.reviewer_id), ('edited', '500 mg', self.user.id))

    def test_reject_logs(self):
        s = _sug(self.item, 'dosage_ar', 'قرصين')
        r = self.client_.post(f'{BASE}/suggestions/{s.pk}/reject/', {'notes': 'خطأ'}, format='json')
        self.assertEqual((r.status_code, r.data['status'], r.data['notes']), (200, 'rejected', 'خطأ'))
        self.assertEqual(EnrichmentApprovalLog.objects.get(field_name='dosage_ar').outcome, 'rejected')
        self.assertEqual(ItemEnrichment.objects.get(item=self.item).dosage_ar, '')

    def test_bulk_approve_fills_only_empty_fields_above_threshold(self):
        enr, _ = ItemEnrichment.objects.get_or_create(item=self.item)
        enr.country_en = 'Egypt'
        enr.save()
        _sug(self.item, 'brand_name', 'Panadol', conf=0.9)
        _sug(self.item, 'country_en', 'UK', conf=0.95)
        low = _sug(self.item, 'strength', '500mg', conf=0.5)
        r = self.client_.post(f'{BASE}/suggestions/bulk-approve/',
                              {'item_id': self.item.pk, 'min_confidence': 0.8}, format='json')
        self.assertEqual(r.data, {'approved': 2})
        enr.refresh_from_db()
        self.assertEqual((enr.brand_name, enr.country_en, enr.strength), ('Panadol', 'Egypt', ''))
        low.refresh_from_db()
        self.assertEqual(low.status, 'pending')
        self.assertEqual(self.client_.post(f'{BASE}/suggestions/bulk-approve/', {}, format='json').status_code, 400)
        r = self.client_.post(f'{BASE}/suggestions/bulk-approve/', {'item_id': self.item.pk}, format='json')
        self.assertEqual(r.data, {'approved': 0})


class BatchApiTests(_ApiBase):

    def test_create_list_detail_cancel(self):
        with mock.patch('apps.enrichment.views.start_thread') as st:
            r = self.client_.post(f'{BASE}/batches/', {'name': 'دفعة', 'scope_type': 'selected',
                                                       'scope_params': {'item_ids': [self.item.pk]}},
                                  format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(st.call_count, 1)
        bid = r.data['id']
        self.assertEqual(EnrichmentBatch.objects.get(pk=bid).created_by_id, self.user.id)
        self.assertEqual(self.client_.get(f'{BASE}/batches/').status_code, 200)
        self.assertEqual(self.client_.get(f'{BASE}/batches/{bid}/').data['status'], 'pending')
        r = self.client_.post(f'{BASE}/batches/{bid}/cancel/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(EnrichmentBatch.objects.get(pk=bid).status, 'cancelled')
        self.assertEqual(self.client_.post(f'{BASE}/batches/{bid}/cancel/').status_code, 400)

    def test_background_runner_marks_failure(self):
        from apps.enrichment.views import _start_batch_thread
        b = EnrichmentBatch.objects.create(scope_type='all')
        with mock.patch('apps.enrichment.views.start_thread', side_effect=lambda fn: fn()), \
                mock.patch.object(sg, 'bulk_generate_suggestions', side_effect=RuntimeError('kaput')):
            _start_batch_thread(b.pk)
            _start_batch_thread(999999)                              # missing → silently ignored
        b.refresh_from_db()
        self.assertEqual(b.status, 'failed')
        self.assertIn('kaput', b.error_log)


class ReportAndItemApiTests(_ApiBase):

    def test_report(self):
        _sug(self.item, 'brand_name', 'Panadol')
        r = self.client_.get(f'{BASE}/report/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['suggestions_pending'], 1)
        self.assertEqual(r.data['top_pending_items'][0]['item_code'], 'EN001')
        self.assertEqual(r.data, get_completeness_report())

    def test_recompute_scores_runs_in_background(self):
        with mock.patch('apps.enrichment.views.start_thread', side_effect=lambda fn: fn()):
            r = self.client_.post(f'{BASE}/recompute-scores/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(ItemEnrichment.objects.filter(item=self.item).exists())

    def test_item_detail(self):
        _sug(self.item, 'brand_name', 'Panadol')
        r = self.client_.get(f'{BASE}/items/{self.item.pk}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['softech']['producer_name'], 'GSK')
        self.assertEqual(r.data['softech']['pack_qty'], 20)
        self.assertEqual([s['field_name'] for s in r.data['suggestions']], ['brand_name'])
        self.assertEqual(self.client_.get(f'{BASE}/items/999999/').status_code, 404)

    def test_generate_for_item_never_auto_approves(self):
        """The single-item pipeline only proposes: every row is pending, the record is untouched."""
        with NO_AI:
            r = self.client_.post(f'{BASE}/items/{self.item.pk}/generate/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['generated'], r.data['created'])
        self.assertIn('indication_ar', r.data['fields'])
        self.assertEqual(set(EnrichmentSuggestion.objects.filter(item=self.item)
                             .values_list('status', flat=True)), {'pending'})
        enr = ItemEnrichment.objects.get(item=self.item)
        self.assertEqual((enr.indication_ar, enr.manufacturer_en, enr.completeness_score), ('', '', 0.0))
        self.assertEqual(self.client_.post(f'{BASE}/items/999999/generate/').status_code, 404)


# ── permission ───────────────────────────────────────────────────────────────

@override_settings(RBAC_ENFORCEMENT='log')
class EnrichmentPermissionTests(TestCase):
    """A salesperson is read-only on catalog: may look, may not approve or start a batch."""

    def setUp(self):
        seed_code_matrix()
        self.item = _rich_item()
        self.sug = _sug(self.item, 'dosage_ar', 'قرصين', conf=0.99)
        self.client_ = bearer_client(make_user('r7enr_sales', role='salesperson')[0])

    def tearDown(self):
        module_access.clear_cache()

    def test_salesperson_cannot_approve_or_start_batches(self):
        self.assertEqual(self.client_.post(f'{BASE}/suggestions/{self.sug.pk}/approve/').status_code, 403)
        self.assertEqual(self.client_.post(f'{BASE}/suggestions/bulk-approve/',
                                           {'item_id': self.item.pk}, format='json').status_code, 403)
        self.assertEqual(self.client_.post(f'{BASE}/batches/', {'scope_type': 'all'},
                                           format='json').status_code, 403)
        self.assertEqual(self.client_.post(f'{BASE}/recompute-scores/').status_code, 403)
        self.sug.refresh_from_db()
        self.assertEqual(self.sug.status, 'pending')
        self.assertFalse(EnrichmentBatch.objects.exists())

    def test_salesperson_can_read(self):
        self.assertEqual(self.client_.get(f'{BASE}/report/').status_code, 200)
        self.assertEqual(self.client_.get(f'{BASE}/batches/').status_code, 200)
