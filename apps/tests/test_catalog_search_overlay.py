"""
apps/tests/test_catalog_search_overlay.py

Product-intelligence overlay (Commerce-OS Phase 1, batch 2): locks in the
deterministic Arabic-folding search normalization and the derived POS safety
flags. Pure functions / attribute stubs — no DB (SimpleTestCase).
"""
from types import SimpleNamespace
from django.test import SimpleTestCase

from apps.catalog.search_index import normalize_search_text, build_search_name, search_name_for
from apps.catalog import safety


class NormalizeTests(SimpleTestCase):
    def test_none_and_blank_safe(self):
        self.assertEqual(normalize_search_text(None), '')
        self.assertEqual(normalize_search_text(''), '')
        self.assertEqual(normalize_search_text('   '), '')

    def test_alef_forms_fold_to_bare_alef(self):
        for variant in ('أدوية', 'إدوية', 'آدوية', 'ٱدوية'):
            self.assertTrue(normalize_search_text(variant).startswith('ا'))

    def test_teh_marbuta_and_alef_maksura_and_tatweel(self):
        # ة→ه, ى→ي, tatweel removed, whitespace collapsed
        self.assertEqual(normalize_search_text('قاعدة'), 'قاعده')
        self.assertEqual(normalize_search_text('مستشفى'), 'مستشفي')
        self.assertEqual(normalize_search_text('تـطـويـل'), 'تطويل')
        self.assertEqual(normalize_search_text('a   b\tc'), 'a b c')

    def test_tashkeel_stripped(self):
        self.assertEqual(normalize_search_text('مُحَمَّد'), 'محمد')

    def test_latin_lowercased(self):
        self.assertEqual(normalize_search_text('BubbleS'), 'bubbles')


class BuildSearchNameTests(SimpleTestCase):
    def test_concatenates_code_barcode_names_deduped(self):
        s = build_search_name(softech_id='127397', barcode='6221048',
                              name='Panadol', name_scientific='Paracetamol')
        self.assertIn('127397', s)
        self.assertIn('6221048', s)
        self.assertIn('panadol', s)
        self.assertIn('paracetamol', s)

    def test_empty_and_duplicate_parts_dropped(self):
        # same normalized value only appears once; blanks skipped
        s = build_search_name(softech_id='1', name='قاعدة', name_scientific='قاعده', barcode='')
        self.assertEqual(s.split().count('قاعده'), 1)

    def test_search_name_for_reads_instance_attrs(self):
        stub = SimpleNamespace(softech_id='9', name='Zinc', name_scientific='', barcode='xyz')
        s = search_name_for(stub)
        self.assertIn('9', s)
        self.assertIn('zinc', s)
        self.assertIn('xyz', s)


def _item(**kw):
    base = dict(is_active=True, item_archive=False, no_more_use=False,
                customer_trans='', nosale_classif='', in_shortage=False, requires_fridge=False)
    base.update(kw)
    return SimpleNamespace(**base)


class SafetyFlagTests(SimpleTestCase):
    def test_clean_item_has_no_flags(self):
        self.assertEqual(safety.item_safety_flags(_item()), [])
        self.assertFalse(safety.blocks_sale(_item()))

    def test_fridge_is_info_only_not_block(self):
        flags = safety.item_safety_flags(_item(requires_fridge=True))
        self.assertEqual([f['code'] for f in flags], ['fridge'])
        self.assertEqual(flags[0]['severity'], 'info')
        self.assertFalse(safety.blocks_sale(_item(requires_fridge=True)))

    def test_sale_stopped_blocks(self):
        self.assertTrue(safety.blocks_sale(_item(customer_trans='3')))

    def test_return_only_warns_not_block(self):
        flags = safety.item_safety_flags(_item(customer_trans='2'))
        self.assertEqual(flags[0]['code'], 'return_only')
        self.assertEqual(flags[0]['severity'], 'warn')
        self.assertFalse(safety.blocks_sale(_item(customer_trans='2')))

    def test_nosale_classif_10_and_blank_are_normal(self):
        self.assertEqual(safety.item_safety_flags(_item(nosale_classif='10')), [])
        self.assertEqual(safety.item_safety_flags(_item(nosale_classif='')), [])

    def test_nosale_classif_restricted_warns(self):
        flags = safety.item_safety_flags(_item(nosale_classif='20'))
        self.assertEqual(flags[0]['code'], 'dispense_restricted')
        self.assertEqual(flags[0]['severity'], 'warn')

    def test_severity_ordering_blocks_first(self):
        flags = safety.item_safety_flags(
            _item(is_active=False, item_archive=True, requires_fridge=True, in_shortage=True))
        severities = [f['severity'] for f in flags]
        self.assertEqual(severities, sorted(severities, key={'block': 0, 'warn': 1, 'info': 2}.get))
        self.assertEqual(flags[0]['severity'], 'block')

    def test_no_controlled_substance_flag_invented(self):
        # We must never emit a narcotics/controlled flag — column is unidentified.
        codes = {f['code'] for f in safety.item_safety_flags(_item(nosale_classif='31'))}
        self.assertNotIn('controlled', codes)
        self.assertNotIn('narcotic', codes)
