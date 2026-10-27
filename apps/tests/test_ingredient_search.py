"""
apps/tests/test_ingredient_search.py

Track A structured search: build_ingredient_search_index + the search API
(molecule / strength / dosage form / class), over the item↔molecule index.
"""
from django.core.management import call_command
from django.test import TestCase

from apps.catalog.models import Item
from apps.composition.models import (
    SoftechIngredientRaw, SoftechItemAI, ItemMoleculeIndex, IngredientParseCandidate,
)
from .factories import make_user


def _item(sid, name, shape=''):
    return Item.objects.create(softech_id=sid, name=name, shape_name=shape)


class SearchIndexTests(TestCase):
    def setUp(self):
        call_command('seed_ingredient_classes')
        # two items, both amlodipine (one 5mg tablet, one 10mg), one omeprazole cap
        _item('IT01', 'CONCOR AM 5', shape='TABLET')
        _item('IT02', 'MYODURA 10', shape='TABLET')
        _item('IT03', 'RISEK 20', shape='CAPSULE')
        SoftechIngredientRaw.objects.create(aicode=10, ainame='AMLODIPINE 5MG', item_count=1)
        SoftechIngredientRaw.objects.create(aicode=11, ainame='AMLODIPINE 10MG', item_count=1)
        SoftechIngredientRaw.objects.create(aicode=20, ainame='OMEPRAZOLE 20MG', item_count=1)
        SoftechItemAI.objects.create(item_softech_id='IT01', aicode=10)
        SoftechItemAI.objects.create(item_softech_id='IT02', aicode=11)
        SoftechItemAI.objects.create(item_softech_id='IT03', aicode=20)
        call_command('generate_ingredient_candidates')
        call_command('propose_ingredient_classes')
        call_command('build_ingredient_search_index')
        _, _, self.staff = make_user('ai_search', role='pharmacist')

    def test_index_rows_built(self):
        self.assertEqual(ItemMoleculeIndex.objects.count(), 3)
        row = ItemMoleculeIndex.objects.get(item_softech_id='IT01')
        self.assertEqual(row.molecule, 'AMLODIPINE')
        self.assertEqual(str(row.strength_value), '5.0000')
        self.assertEqual(row.dosage_form, 'TABLET')
        self.assertEqual(row.source, 'parsed')

    def test_search_by_molecule_returns_all_strengths(self):
        r = self.staff.get('/api/composition/search/?molecule=amlodipine')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['count'], 2)

    def test_search_by_molecule_and_strength(self):
        r = self.staff.get('/api/composition/search/?molecule=amlodipine&strength_value=10&strength_unit=mg')
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['item_softech_id'], 'IT02')

    def test_search_by_dosage_form(self):
        r = self.staff.get('/api/composition/search/?dosage_form=CAPSULE')
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['molecule'], 'OMEPRAZOLE')

    def test_search_by_class_key(self):
        r = self.staff.get('/api/composition/search/?class_key=calcium_channel_blockers')
        self.assertEqual(r.data['count'], 2)

    def test_molecules_autocomplete(self):
        r = self.staff.get('/api/composition/search/molecules/?q=amlo')
        self.assertEqual(r.status_code, 200)
        row = next(x for x in r.data if x['molecule'] == 'AMLODIPINE')
        self.assertEqual(row['items'], 2)

    def test_facets(self):
        r = self.staff.get('/api/composition/search/facets/')
        self.assertIn('TABLET', r.data['dosage_forms'])
        self.assertIn('CAPSULE', r.data['dosage_forms'])
        self.assertIn('mg', r.data['units'])
        self.assertTrue(any(c['key'] == 'ppi' for c in r.data['classes']))

    def test_approved_beats_parsed_source(self):
        cand = IngredientParseCandidate.objects.get(raw_aicode=20)
        from apps.composition import approve as eng
        eng.approve_candidate(cand, None)
        call_command('build_ingredient_search_index')
        row = ItemMoleculeIndex.objects.get(item_softech_id='IT03')
        self.assertEqual(row.source, 'approved')
        self.assertIsNotNone(row.active_ingredient)

    def test_requires_auth(self):
        from .factories import make_anon_client
        r = make_anon_client().get('/api/composition/search/?molecule=amlodipine')
        self.assertIn(r.status_code, (401, 403))

    def test_rebuild_endpoint(self):
        _, _, admin = make_user('ai_rebuild', role='admin')
        ItemMoleculeIndex.objects.all().delete()
        r = admin.post('/api/composition/search/rebuild/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['rows'], 3)   # rebuilt from scratch
        self.assertEqual(ItemMoleculeIndex.objects.count(), 3)

    def test_rebuild_requires_edit(self):
        _, _, viewer = make_user('ai_ro', role='viewer')
        self.assertEqual(viewer.post('/api/composition/search/rebuild/').status_code, 403)
