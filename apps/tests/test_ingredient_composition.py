"""
apps/tests/test_ingredient_composition.py

Batch 1 of the active-ingredient reconciliation pipeline (apps.composition):
candidate generation from the SOFTECH mirror + the read-only reconciliation API.
No SOFTECH access — the mirror is seeded directly.
"""
from django.core.management import call_command
from django.test import TestCase

from apps.composition.models import SoftechIngredientRaw, IngredientParseCandidate
from .factories import make_user

RAW = [
    (100, 'AMLODIPINE 5MG', 12),
    (101, 'AMLODIPINE 10MG + VALSARTAN 160MG', 4),
    (102, 'N/A UNIDENTIFIED', 0),
    (103, 'METFORMIN 500MG', 30),
]


class CandidateGenerationTests(TestCase):
    def setUp(self):
        for aicode, ainame, n in RAW:
            SoftechIngredientRaw.objects.create(aicode=aicode, ainame=ainame, item_count=n)

    def test_generate_creates_one_candidate_per_raw(self):
        call_command('generate_ingredient_candidates')
        self.assertEqual(IngredientParseCandidate.objects.count(), len(RAW))

    def test_combination_and_placeholder_flags(self):
        call_command('generate_ingredient_candidates')
        combo = IngredientParseCandidate.objects.get(raw_aicode=101)
        self.assertTrue(combo.is_combination)
        self.assertEqual(combo.primary_molecule, 'AMLODIPINE')

        junk = IngredientParseCandidate.objects.get(raw_aicode=102)
        self.assertTrue(junk.is_placeholder)
        self.assertEqual(junk.status, IngredientParseCandidate.STATUS_NEEDS_REVIEW)

    def test_idempotent_and_preserves_review(self):
        call_command('generate_ingredient_candidates')
        cand = IngredientParseCandidate.objects.get(raw_aicode=100)
        cand.status = IngredientParseCandidate.STATUS_APPROVED
        cand.save()
        # Re-run: no duplicates, and the approved row is left alone.
        call_command('generate_ingredient_candidates')
        self.assertEqual(IngredientParseCandidate.objects.count(), len(RAW))
        cand.refresh_from_db()
        self.assertEqual(cand.status, IngredientParseCandidate.STATUS_APPROVED)

    def test_dry_run_writes_nothing(self):
        call_command('generate_ingredient_candidates', '--dry-run')
        self.assertEqual(IngredientParseCandidate.objects.count(), 0)


class ReconciliationApiTests(TestCase):
    def setUp(self):
        for aicode, ainame, n in RAW:
            SoftechIngredientRaw.objects.create(aicode=aicode, ainame=ainame, item_count=n)
        call_command('generate_ingredient_candidates')
        _, _, self.staff = make_user('ai_recon', role='pharmacist')

    def test_requires_auth(self):
        from .factories import make_anon_client
        r = make_anon_client().get('/api/composition/candidates/')
        self.assertIn(r.status_code, (401, 403))

    def test_list_candidates(self):
        r = self.staff.get('/api/composition/candidates/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['count'], len(RAW))

    def test_filter_combos(self):
        r = self.staff.get('/api/composition/candidates/?combos=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['count'], 1)
        self.assertEqual(r.data['results'][0]['raw_aicode'], 101)

    def test_summary(self):
        r = self.staff.get('/api/composition/candidates/summary/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['raw_rows'], len(RAW))
        self.assertEqual(r.data['combinations'], 1)
        self.assertEqual(r.data['placeholders'], 1)
        # AMLODIPINE, VALSARTAN, METFORMIN → 3 distinct molecules (junk excluded)
        self.assertEqual(r.data['distinct_proposed_molecules'], 3)
        self.assertEqual(r.data['item_links_covered'], 46)

    def test_raw_mirror_list(self):
        r = self.staff.get('/api/composition/raw/?used_only=1')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['count'], 3)  # excludes the item_count=0 placeholder
