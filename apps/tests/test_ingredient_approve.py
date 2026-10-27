"""
apps/tests/test_ingredient_approve.py

Batch 2B — the reconciliation approval engine + review write-actions.
Approving candidates realises canonical molecules/strengths (dedup automatic),
supports combinations, non-drug disposition, reject, and manual class override.
RBAC-gated on catalog/edit. No SOFTECH writes.
"""
from django.core.management import call_command
from django.test import TestCase

from apps.chronic.models import ActiveIngredient, IngredientStrength, IngredientClass
from apps.composition.models import (
    SoftechIngredientRaw, IngredientParseCandidate, CandidateMolecule,
)
from .factories import make_user

BASE = '/api/composition/candidates/'


class ApproveEngineTests(TestCase):
    def setUp(self):
        call_command('seed_ingredient_classes')
        for aicode, name, n in [
            (100, 'AMLODIPINE 5MG', 12),
            (101, 'AMLODIPINE 10MG', 8),                 # same molecule, other strength
            (102, 'AMLODIPINE 10MG + VALSARTAN 160MG', 4),  # combination
            (103, 'REVITALASH EYELASH SERUM', 3),        # non-drug
            (104, 'N/A UNIDENTIFIED', 0),                # placeholder
        ]:
            SoftechIngredientRaw.objects.create(aicode=aicode, ainame=name, item_count=n)
        call_command('generate_ingredient_candidates')
        call_command('propose_ingredient_classes')
        _, _, self.admin = make_user('ai_admin', role='admin')
        _, _, self.viewer = make_user('ai_viewer', role='viewer')

    def _cand(self, aicode):
        return IngredientParseCandidate.objects.get(raw_aicode=aicode)

    def test_approve_single_creates_molecule_and_strength(self):
        r = self.admin.post(f'{BASE}{self._cand(100).id}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        ai = ActiveIngredient.objects.get(name='AMLODIPINE')
        self.assertTrue(ai.is_verified)
        self.assertEqual(ai.ingredient_class.key, 'calcium_channel_blockers')
        self.assertTrue(IngredientStrength.objects.filter(
            active_ingredient=ai, strength_value=5, strength_unit='mg').exists())
        self.assertEqual(self._cand(100).status, 'approved')

    def test_dedup_same_molecule_two_strengths(self):
        self.admin.post(f'{BASE}{self._cand(100).id}/approve/', {}, format='json')
        self.admin.post(f'{BASE}{self._cand(101).id}/approve/', {}, format='json')
        # ONE molecule, TWO strengths
        self.assertEqual(ActiveIngredient.objects.filter(name='AMLODIPINE').count(), 1)
        ai = ActiveIngredient.objects.get(name='AMLODIPINE')
        self.assertEqual(ai.strengths.count(), 2)

    def test_approve_combination_links_both_molecules(self):
        r = self.admin.post(f'{BASE}{self._cand(102).id}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 200)
        cand = self._cand(102)
        links = CandidateMolecule.objects.filter(candidate=cand)
        self.assertEqual(links.count(), 2)
        names = set(links.values_list('active_ingredient__name', flat=True))
        self.assertEqual(names, {'AMLODIPINE', 'VALSARTAN'})
        self.assertEqual(cand.canonical_ingredient.name, 'AMLODIPINE')  # primary

    def test_reapprove_is_idempotent(self):
        cid = self._cand(102).id
        self.admin.post(f'{BASE}{cid}/approve/', {}, format='json')
        self.admin.post(f'{BASE}{cid}/approve/', {}, format='json')
        self.assertEqual(CandidateMolecule.objects.filter(candidate_id=cid).count(), 2)

    def test_non_drug_creates_no_molecule(self):
        r = self.admin.post(f'{BASE}{self._cand(103).id}/non-drug/',
                            {'class_key': 'cosmetics'}, format='json')
        self.assertEqual(r.status_code, 200)
        cand = self._cand(103)
        self.assertTrue(cand.is_non_drug)
        self.assertEqual(cand.proposed_class.key, 'cosmetics')
        self.assertIsNone(cand.canonical_ingredient)
        self.assertFalse(ActiveIngredient.objects.filter(name__icontains='REVITALASH').exists())

    def test_non_drug_rejects_bad_class(self):
        r = self.admin.post(f'{BASE}{self._cand(103).id}/non-drug/',
                            {'class_key': 'statins'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_approve_placeholder_rejected(self):
        r = self.admin.post(f'{BASE}{self._cand(104).id}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_reject(self):
        r = self.admin.post(f'{BASE}{self._cand(100).id}/reject/',
                            {'notes': 'bad row'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self._cand(100).status, 'rejected')

    def test_class_override_on_approve(self):
        klass = IngredientClass.objects.get(key='antivirals')
        self.admin.post(f'{BASE}{self._cand(100).id}/approve/',
                        {'class_id': klass.id}, format='json')
        self.assertEqual(ActiveIngredient.objects.get(name='AMLODIPINE').ingredient_class.key,
                         'antivirals')

    def test_viewer_cannot_approve(self):
        r = self.viewer.post(f'{BASE}{self._cand(100).id}/approve/', {}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self._cand(100).status, 'pending')

    def test_molecule_groups(self):
        r = self.admin.get(f'{BASE}molecule_groups/?q=AMLODIPINE')
        self.assertEqual(r.status_code, 200)
        amlo = next(g for g in r.data['groups'] if g['molecule'] == 'AMLODIPINE')
        self.assertEqual(amlo['total'], 3)  # 5mg, 10mg, combo all group under AMLODIPINE

    def test_classes_endpoint(self):
        r = self.admin.get('/api/composition/classes/?q=statin')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(any(c['key'] == 'statins' for c in r.data))

    def test_view_linked_items(self):
        from apps.composition.models import SoftechItemAI
        from apps.catalog.models import Item
        Item.objects.create(softech_id='P1', name='NORVASC 5', shape_name='TABLET')
        SoftechItemAI.objects.create(item_softech_id='P1', aicode=100)
        SoftechItemAI.objects.create(item_softech_id='P2', aicode=100)   # not in catalog
        r = self.admin.get(f'{BASE}{self._cand(100).id}/items/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 2)
        p1 = next(x for x in r.data if x['softech_id'] == 'P1')
        self.assertEqual(p1['name'], 'NORVASC 5')
        self.assertIsNotNone(p1['item_id'])

    def test_edit_cleans_name_and_drops_junk_then_approves(self):
        # combo where the reviewer renames one molecule and drops a junk component
        cand = self._cand(102)
        payload = {'components': [
            {'molecule': 'amlodipine', 'strength_value': 10, 'strength_unit': 'mg', 'include': True},
            {'molecule': 'valsartan', 'strength_value': 160, 'strength_unit': 'mg', 'include': True},
            {'molecule': 'CALORIES', 'include': False},   # junk → dropped
        ]}
        r = self.admin.post(f'{BASE}{cand.id}/edit/', payload, format='json')
        self.assertEqual(r.status_code, 200)
        cand.refresh_from_db()
        self.assertEqual(cand.parsed_components[0]['molecule'], 'AMLODIPINE')   # upper-normalized
        # approve realises ONLY the two kept molecules
        self.admin.post(f'{BASE}{cand.id}/approve/', {}, format='json')
        mols = set(CandidateMolecule.objects.filter(candidate=cand)
                   .values_list('active_ingredient__name', flat=True))
        self.assertEqual(mols, {'AMLODIPINE', 'VALSARTAN'})

    def test_edit_requires_edit_permission(self):
        r = self.viewer.post(f'{BASE}{self._cand(100).id}/edit/',
                             {'components': [{'molecule': 'X'}]}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_create_new_class(self):
        r = self.admin.post('/api/composition/classes/', {
            'name': 'Ophthalmic Lubricants (Custom)',
            'name_ar': 'مرطبات العين (مخصص)',
        }, format='json')
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.data['key'].startswith('ophthalmic_lubricants'))
        self.assertEqual(IngredientClass.objects.filter(name_ar='مرطبات العين (مخصص)').count(), 1)
        # duplicate name rejected
        r2 = self.admin.post('/api/composition/classes/', {
            'name': 'Ophthalmic Lubricants (Custom)'}, format='json')
        self.assertEqual(r2.status_code, 400)

    def test_viewer_cannot_create_class(self):
        r = self.viewer.post('/api/composition/classes/', {'name': 'X Class'}, format='json')
        self.assertEqual(r.status_code, 403)
