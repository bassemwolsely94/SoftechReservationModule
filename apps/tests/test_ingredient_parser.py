"""
apps/tests/test_ingredient_parser.py

Deterministic active-ingredient name parser (apps.composition.parser).
Pure logic — no DB — so it runs as a SimpleTestCase.
"""
from django.test import SimpleTestCase

from apps.composition.parser import parse


class ParserTests(SimpleTestCase):
    def test_single_molecule_with_strength(self):
        r = parse('AMLODIPINE 10MG')
        self.assertFalse(r.is_combination)
        self.assertFalse(r.is_placeholder)
        self.assertEqual(len(r.components), 1)
        c = r.components[0]
        self.assertEqual(c.molecule, 'AMLODIPINE')
        self.assertEqual(c.strength_value, 10.0)
        self.assertEqual(c.strength_unit, 'mg')

    def test_decimal_strength(self):
        r = parse('AMLODIPINE 2.5 MG')
        self.assertEqual(r.components[0].strength_value, 2.5)
        self.assertEqual(r.components[0].strength_unit, 'mg')

    def test_combination_on_plus(self):
        r = parse('AMLODIPINE 10MG + VALSARTAN 160MG')
        self.assertTrue(r.is_combination)
        self.assertEqual(r.molecules, ['AMLODIPINE', 'VALSARTAN'])
        self.assertEqual(r.components[1].strength_value, 160.0)

    def test_combination_on_slash(self):
        r = parse('AMLODIPINE / ATORVASTATIN')
        self.assertTrue(r.is_combination)
        self.assertEqual(r.molecules, ['AMLODIPINE', 'ATORVASTATIN'])

    def test_strength_ratio_not_split_as_combo(self):
        # "mg/5ml" must stay one strength, NOT split into two molecules.
        r = parse('PARACETAMOL 120MG/5ML')
        self.assertFalse(r.is_combination)
        self.assertEqual(r.components[0].molecule, 'PARACETAMOL')
        self.assertEqual(r.components[0].strength_unit, 'mg/5ml')

    def test_salt_form_extracted(self):
        r = parse('AMLODIPINE BESYLATE 5MG')
        self.assertEqual(r.components[0].molecule, 'AMLODIPINE')
        self.assertEqual(r.components[0].salt, 'besylate')

    def test_as_salt_parenthetical(self):
        r = parse('AMLODIPINE (AS BESYLATE) 5MG')
        self.assertEqual(r.components[0].molecule, 'AMLODIPINE')
        self.assertEqual(r.components[0].salt, 'besylate')

    def test_unit_normalization(self):
        self.assertEqual(parse('FOLIC 5UG').components[0].strength_unit, 'mcg')
        self.assertEqual(parse('X 1GM').components[0].strength_unit, 'g')

    def test_placeholder_detected(self):
        for junk in ('N/A UNIDENTIFIED', '', '   ', 'UnDefined Item', '-'):
            r = parse(junk)
            self.assertTrue(r.is_placeholder, junk)
            self.assertEqual(r.confidence, 0.0, junk)
            self.assertEqual(r.components, [])

    def test_confidence_high_for_clean_single(self):
        self.assertGreaterEqual(parse('METFORMIN 500MG').confidence, 0.9)

    def test_to_json_roundtrip_shape(self):
        d = parse('AMLODIPINE 5MG').to_json()
        self.assertEqual(
            set(d.keys()),
            {'raw_name', 'components', 'is_combination', 'is_placeholder',
             'confidence', 'parser_version'},
        )
        self.assertEqual(
            set(d['components'][0].keys()),
            {'molecule', 'salt', 'strength_value', 'strength_unit', 'raw_fragment'},
        )
