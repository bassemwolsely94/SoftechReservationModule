"""
apps/tests/test_ingredient_classify.py

Deterministic class classifier (apps.composition.classify) + the seed /
propose commands that populate the pharmacology taxonomy.
"""
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from apps.chronic.models import IngredientClass
from apps.composition.classify import classify
from apps.composition.taxonomy import CLASSES, CLASS_KEYS, STEM_RULES, OVERRIDES, CONTAINS
from apps.composition.models import SoftechIngredientRaw, IngredientParseCandidate


class ClassifierTests(SimpleTestCase):
    def test_stem_matches(self):
        cases = {
            'AMLODIPINE': 'calcium_channel_blockers',
            'VALSARTAN': 'arbs',
            'ATORVASTATIN': 'statins',
            'OMEPRAZOLE': 'ppi',
            'CIPROFLOXACIN': 'fluoroquinolones',
            'AMOXICILLIN': 'penicillins',
            'AZITHROMYCIN': 'macrolides',
            'SITAGLIPTIN': 'dpp4_inhibitors',
            'EMPAGLIFLOZIN': 'sglt2_inhibitors',
            'IBUPROFEN': 'nsaids',
            'CEFTRIAXONE': 'cephalosporins',
            'RIVAROXABAN': 'doac',
            'FLUCONAZOLE': 'azole_antifungals',
            'DIAZEPAM': 'benzodiazepines',
            'FUROSEMIDE': 'loop_diuretics',
            'ERENUMAB': 'monoclonal_antibodies',
        }
        for mol, key in cases.items():
            got, rule, conf = classify(mol)
            self.assertEqual(got, key, f'{mol} → {got} (rule {rule}), expected {key}')
            self.assertGreaterEqual(conf, 0.8)

    def test_overrides_beat_stems(self):
        got, rule, conf = classify('METFORMIN')
        self.assertEqual(got, 'biguanides')
        self.assertEqual(conf, 1.0)

    def test_contains_insulin(self):
        got, _, _ = classify('INSULIN GLARGINE')
        self.assertEqual(got, 'insulins')

    def test_word_override_multiword(self):
        got, _, _ = classify('ASCORBIC ACID')
        self.assertEqual(got, 'vitamins')

    def test_unknown_returns_none(self):
        got, rule, conf = classify('ZZZ MADEUP MOLECULE')
        self.assertIsNone(got)
        self.assertEqual(conf, 0.0)

    def test_all_rule_targets_are_valid_keys(self):
        # every class_key referenced by a rule must exist in the taxonomy
        for _, _, key in STEM_RULES:
            self.assertIn(key, CLASS_KEYS, f'stem → unknown key {key}')
        for key in OVERRIDES.values():
            self.assertIn(key, CLASS_KEYS, f'override → unknown key {key}')
        for _, key in CONTAINS:
            self.assertIn(key, CLASS_KEYS, f'contains → unknown key {key}')

    def test_taxonomy_keys_unique(self):
        keys = [c[0] for c in CLASSES]
        self.assertEqual(len(keys), len(set(keys)))


class SeedAndProposeTests(TestCase):
    def test_seed_creates_taxonomy_and_maps_softech_codes(self):
        call_command('seed_ingredient_classes')
        self.assertEqual(IngredientClass.objects.count(), len(CLASSES))
        # SOFTECH's 23 carry a softech_code; extended ones don't.
        self.assertEqual(IngredientClass.objects.get(key='ppi').softech_code, '21')
        self.assertEqual(IngredientClass.objects.get(key='nsaids').softech_code, '')

    def test_seed_idempotent(self):
        call_command('seed_ingredient_classes')
        call_command('seed_ingredient_classes')
        self.assertEqual(IngredientClass.objects.count(), len(CLASSES))

    def test_propose_sets_class_on_candidates(self):
        call_command('seed_ingredient_classes')
        for aicode, name, n in [(1, 'AMLODIPINE 5MG', 10),
                                (2, 'OMEPRAZOLE 20MG', 8),
                                (3, 'N/A UNIDENTIFIED', 0)]:
            SoftechIngredientRaw.objects.create(aicode=aicode, ainame=name, item_count=n)
        call_command('generate_ingredient_candidates')
        call_command('propose_ingredient_classes')

        amlo = IngredientParseCandidate.objects.get(raw_aicode=1)
        self.assertEqual(amlo.proposed_class.key, 'calcium_channel_blockers')
        self.assertGreater(amlo.class_confidence, 0.0)
        self.assertEqual(amlo.parsed_components[0]['class_key'], 'calcium_channel_blockers')

        # placeholder gets no class
        junk = IngredientParseCandidate.objects.get(raw_aicode=3)
        self.assertIsNone(junk.proposed_class)

    def test_propose_dry_run_writes_nothing(self):
        call_command('seed_ingredient_classes')
        SoftechIngredientRaw.objects.create(aicode=1, ainame='AMLODIPINE 5MG', item_count=5)
        call_command('generate_ingredient_candidates')
        call_command('propose_ingredient_classes', '--dry-run')
        self.assertIsNone(IngredientParseCandidate.objects.get(raw_aicode=1).proposed_class)
