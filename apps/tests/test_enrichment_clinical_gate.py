"""
CLAUDE.md rule 10: an AI never decides clinical content. Enrichment batches may auto-approve
high-confidence suggestions for descriptive fields (brand, manufacturer, strength…), but never for
clinical ones (dose, indications, warnings, interactions…): those always wait for a pharmacist.
"""
from unittest import mock

from django.test import TestCase

from apps.enrichment import suggestion_generator as sg
from apps.enrichment.models import EnrichmentBatch, EnrichmentSuggestion, ItemEnrichment

from .factories import make_item


class ClinicalGateTests(TestCase):
    def test_clinical_fields_never_auto_publish(self):
        for f in ('dosage_ar', 'frequency_ar', 'indication_ar', 'warning_ar', 'contraindication_ar',
                  'drug_interactions_ar', 'side_effects_ar', 'pregnancy_category', 'rx_otc'):
            self.assertFalse(sg.may_auto_publish(f, 0.99, 0.9), f)
        self.assertTrue(sg.may_auto_publish('brand_name', 0.95, 0.9))
        self.assertFalse(sg.may_auto_publish('brand_name', 0.5, 0.9))

    def test_batch_leaves_clinical_suggestion_pending(self):
        item = make_item('بنادول 500', 'EG001')
        item.is_active = item.is_stockable = True
        item.save()
        enr, _ = ItemEnrichment.objects.get_or_create(item=item)
        batch = EnrichmentBatch.objects.create(scope_type='selected', scope_params={'item_ids': [item.pk]},
                                               auto_publish_threshold=0.9)

        def fake(it, batch=None, overwrite_pending=False):
            base = dict(item=it, enrichment=enr, batch=batch, current_value='', source='ai_extract',
                        confidence=0.99, status='pending')
            return [{**base, 'field_name': 'dosage_ar', 'suggested_value': 'قرصين'},
                    {**base, 'field_name': 'brand_name', 'suggested_value': 'بنادول'}]

        with mock.patch.object(sg, 'generate_suggestions_for_item', side_effect=fake):
            sg.bulk_generate_suggestions(batch)
        st = dict(EnrichmentSuggestion.objects.filter(item=item).values_list('field_name', 'status'))
        self.assertEqual(st, {'dosage_ar': 'pending', 'brand_name': 'approved'})
        enr.refresh_from_db()
        self.assertEqual(enr.dosage_ar, '')
