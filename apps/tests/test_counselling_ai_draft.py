"""Project 4 — AI-drafted counselling sheets stay drafts; only a pharmacist approves."""
import inspect
from unittest import mock

from django.test import TestCase, override_settings

from apps.counselling import ai_draft
from apps.counselling.models import CounsellingContent

from .factories import make_item, make_user

URL = '/api/counselling/content/ai-draft/'
RAW = {'how_to_use_ar': 'يبلع مع الماء', 'dose_ar': 'قرص', 'frequency_code': '1x2', 'with_food': 'after',
       'evil_key': 'x', 'status': 'approved'}


@override_settings(COUNSELLING_CONTENT_ENABLED=True)
class AiDraftTests(TestCase):
    def setUp(self):
        _, self.ph, self.ph_c = make_user('ph_ai', role='pharmacist')
        _, _, self.sp_c = make_user('sp_ai', role='salesperson')
        self.item = make_item('بنادول اكسترا', 'AI001')

    @mock.patch('apps.enrichment.ai_extractor.complete_json', return_value=(RAW, 'gemini-2.5-flash'))
    def test_ai_draft_is_draft_with_source_and_model(self, _m):
        r = self.ph_c.post(URL, {'item_id': self.item.pk}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        c = CounsellingContent.objects.get(pk=r.data['id'])
        self.assertEqual((c.status, c.source, c.ai_model), ('draft', 'ai_draft', 'gemini-2.5-flash'))
        self.assertIsNone(c.approved_version)

    @mock.patch('apps.enrichment.ai_extractor.complete_json', return_value=(RAW, 'm'))
    def test_ai_draft_unknown_keys_dropped(self, _m):
        c = ai_draft.draft_for_item(self.ph, self.item)
        self.assertEqual(c.dose_ar, 'قرص')
        self.assertEqual(c.with_food, 'after')
        self.assertEqual(c.status, 'draft')     # an AI 'status' key is ignored

    def test_ai_draft_module_never_approves(self):
        src = inspect.getsource(ai_draft)
        self.assertNotIn('approve(', src)
        self.assertNotIn("'approved'", src)

    @mock.patch('apps.enrichment.ai_extractor.complete_json', return_value=({}, ''))
    def test_ai_failure_raises_clean_error(self, _m):
        r = self.ph_c.post(URL, {'item_id': self.item.pk}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertFalse(CounsellingContent.objects.exists())

    def test_salesperson_cannot_ai_draft(self):
        self.assertEqual(self.sp_c.post(URL, {'item_id': self.item.pk}, format='json').status_code, 403)
