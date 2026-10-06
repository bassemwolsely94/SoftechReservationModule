"""
System-wide progressive learning for catalog matching (apps/shortage/learning.py), used
by every screen through apps/shortage/matching.find_best_matches.

  • exact memory → certain (1.0); CLOSE spelling (typo, extra/missing letter, dots,
    Arabic-Indic digits) → strong suggestion (0.90–0.98) — but only with IDENTICAL numbers
  • corrections → the replaced suggestion is pushed down; an alias pointing there weakens
  • one spelling → several items ("بيبيلاك 1....2....3") is remembered and re-applied
  • a close-spelling memory never hijacks a near-perfect catalog match of another product
"""
from decimal import Decimal

from django.test import TestCase

from apps.shortage import learning as LRN
from apps.shortage.matching import find_best_matches


def _items(*names):
    from apps.catalog.models import Item
    return [Item.objects.create(softech_id=str(920000 + i), name=n, pack_price=100, cost_price=80)
            for i, n in enumerate(names)]


class SpellingToleranceTests(TestCase):
    def setUp(self):
        self.omez10, self.omez20 = _items('OMEZ 10 14/CAP (2STRIPSX7)', 'OMEZ 20  MG 14CAP (2STRIPSX7)')
        LRN.learn_alias('اوميز 10', self.omez10, source='whatsapp')

    def test_exact_and_arabic_digits(self):
        for spelling in ('اوميز 10', 'أوميز ١٠', 'اوميز.. 10'):
            hit = LRN.lookup_alias(spelling)
            self.assertEqual((hit['item_id'], hit['score'], hit['learned']), (self.omez10.id, 1.0, True), spelling)

    def test_close_spelling_is_a_strong_suggestion(self):
        hit = LRN.lookup_alias('اومييز 10')                          # an extra letter
        self.assertEqual(hit['item_id'], self.omez10.id)
        self.assertTrue(hit['learned_fuzzy'])
        self.assertFalse(hit['learned'])
        self.assertTrue(0.90 <= hit['score'] <= 0.98)
        top = find_best_matches('اومييز 10', top_n=1)[0]           # flows through the matcher
        self.assertEqual(top['item_id'], self.omez10.id)

    def test_numbers_must_be_identical(self):
        self.assertIsNone(LRN.lookup_alias('اوميز 20'))
        self.assertIsNone(LRN.lookup_alias('اوميز 10 20'))

    def test_two_items_equally_close_means_no_guess(self):
        LRN.learn_alias('اوميس 10', self.omez20)                    # a rival memory, as close
        self.assertIsNone(LRN.lookup_alias('اوميش 10'))

    def test_repetition_wins_between_conflicting_memories(self):
        LRN.learn_alias('اوميز 10', self.omez20)
        self.assertEqual(LRN.lookup_alias('اوميز 10')['item_id'], self.omez10.id)   # 1 vs 1: tie → first
        LRN.learn_alias('اوميز 10', self.omez20)
        LRN.learn_alias('اوميز 10', self.omez20)
        self.assertEqual(LRN.lookup_alias('اوميز 10')['item_id'], self.omez20.id)   # 3 beats 1


class CorrectionTests(TestCase):
    def test_rejected_suggestion_drops_and_alias_weakens_then_forgiven(self):
        a5, a10 = _items('ARICEPT 5MG 14TAB (2STRIPSX7)', 'ARICEPT 10MG 14TAB (2STRIPSX7)')
        LRN.learn_alias('aricept tab', a5)
        self.assertEqual(find_best_matches('aricept tab', top_n=1)[0]['item_id'], a5.id)
        LRN.record_rejection('aricept tab', a5)                     # a person replaced it
        self.assertIsNone(LRN.lookup_alias('aricept tab'))          # alias (×1) removed
        top = find_best_matches('aricept tab', top_n=2)
        self.assertEqual(top[0]['item_id'], a10.id)                 # rejected one pushed down
        LRN.record_rejection('aricept  tab.', a5)                   # same spelling family
        self.assertEqual(LRN.rejections('aricept tab'), {a5.id: 2})
        LRN.learn_alias('aricept tab', a5)                          # confirmed later: forgives one
        self.assertEqual(LRN.rejections('aricept tab'), {a5.id: 1})

    def test_learn_correction(self):
        a, b = _items('PECTOL CHERRY 8TAB', 'PECTOL HONEY 8TAB')
        LRN.learn_correction('pectol x', suggested=a, chosen=[b], source='shortage')
        self.assertEqual(LRN.lookup_alias('pectol x')['item_id'], b.id)
        self.assertEqual(LRN.rejections('pectol x'), {a.id: 1})


class NoHijackTests(TestCase):
    def test_close_memory_never_beats_a_near_perfect_catalog_match(self):
        lary, lacy = _items('LARYPRO 30TAB', 'LACY PRO 30TAB')
        LRN.learn_alias('lary pro 30tab', lary)
        res = find_best_matches('lacy pro 30tab', top_n=3)
        self.assertEqual(res[0]['item_id'], lacy.id)                # the catalog's exact product
        self.assertIn(lary.id, [r['item_id'] for r in res])         # memory still offered


class GroupMemoryTests(TestCase):
    def setUp(self):
        self.b1, self.b2, self.b3 = _items('BEBELAC (1) FORMULA MILK 400GM', 'BEBELAC (2) FORMULA MILK 400GM',
                                           'BEBELAC (3) JUNIOR MILK 400GM')

    def test_group_learned_found_by_close_spelling_and_numbers(self):
        LRN.learn_alias_group('بيبيلاك 1....2....3', [self.b1, self.b2, self.b3], vendor_code='565')
        g = LRN.lookup_alias_group('بيبلاك 1..2..3', vendor_code='565')       # typo + dots
        self.assertEqual(g['item_ids'], [self.b1.id, self.b2.id, self.b3.id])
        self.assertTrue(g['learned_fuzzy'])
        self.assertIsNone(LRN.lookup_alias_group('بيبيلاك 1..2', vendor_code='565'))   # numbers differ
        self.assertIsNone(LRN.lookup_alias_group('بيبيلاك 1 2 3'))            # supplier-scoped only
        LRN.unlearn_alias_group('بيبيلاك 1 2 3', [self.b1, self.b2, self.b3], vendor_code='565')
        self.assertIsNone(LRN.lookup_alias_group('بيبيلاك 1 2 3', vendor_code='565'))

    def test_stronger_single_habit_wins(self):
        LRN.learn_alias_group('بيبيلاك 1 2 3', [self.b1, self.b2, self.b3])
        for _ in range(2):
            LRN.learn_alias('بيبيلاك 1 2 3', self.b1)
        self.assertIsNone(LRN.lookup_alias_group('بيبيلاك 1 2 3'))


class AvailabilityLearningTests(TestCase):
    """The supplier inbox: learns the PARSED name (not the raw line with price), re-splits a
    remembered multi-item line, and bulk confirm reinforces the group (no single aliases)."""

    def setUp(self):
        from apps.supply.models import AvailabilityBatch
        self.b1, self.b2, self.b3 = _items('BEBELAC (1) FORMULA MILK 400GM', 'BEBELAC (2) FORMULA MILK 400GM',
                                           'BEBELAC (3) JUNIOR MILK 400GM')
        self.batch = AvailabilityBatch.objects.create(supplier_name='565')

    def test_split_is_remembered_and_reapplied_next_time(self):
        from apps.catalog.models import ItemAlias, ItemAliasGroup
        from apps.supply import availability as av
        from apps.supply.models import AvailabilityBatch
        first = av.ingest_batch(self.batch, '🏷️بيبيلاك 1....2....3')[0]
        av.set_line_items(first, [self.b1.id, self.b2.id, self.b3.id])
        self.assertEqual(ItemAliasGroup.objects.get().use_count, 1)
        self.assertFalse(ItemAlias.objects.exists())                 # never taught 1:1

        nxt = AvailabilityBatch.objects.create(supplier_name='565')
        head = av.ingest_batch(nxt, '🏷️بيبلاك 1..2..3')[0]          # next week, a typo
        rows = list(nxt.lines.order_by('id'))
        self.assertEqual([r.item_id for r in rows], [self.b1.id, self.b2.id, self.b3.id])
        self.assertFalse(any(r.is_confirmed for r in rows))           # a suggestion
        self.assertEqual([r.split_from_id for r in rows], [None, head.pk, head.pk])
        av.confirm_matches(nxt)                                       # «تأكيد الواضحة»
        self.assertTrue(all(r.is_confirmed for r in nxt.lines.all()))
        # the new spelling is now remembered EXACTLY too (progressive: each variant learned)
        self.assertEqual(sorted(ItemAliasGroup.objects.values_list('normalized', flat=True)),
                         ['بيبلاك 1 2 3', 'بيبيلاك 1 2 3'])
        self.assertFalse(ItemAlias.objects.exists())
        third = AvailabilityBatch.objects.create(supplier_name='565')
        av.ingest_batch(third, 'بيبلاك 1..2..3')
        av.confirm_matches(third)
        self.assertEqual(ItemAliasGroup.objects.get(normalized='بيبلاك 1 2 3').use_count, 2)   # reinforced

    def test_single_confirmation_learns_the_name_part_and_rejects_replaced(self):
        from apps.catalog.models import ItemAlias
        from apps.supply import availability as av
        from apps.supply.models import AvailabilityLine
        ln = AvailabilityLine.objects.create(batch=self.batch, raw_text='Bebelac 1 متاح 20 بسعر 210', item=self.b2,
                                             match_reason={'name_part': 'Bebelac 1', 'suggested_item_id': self.b2.id},
                                             price=Decimal('210'))
        av.set_line_items(ln, [self.b1.id])                           # a person fixed it
        self.assertEqual(ItemAlias.objects.get().normalized, 'bebelac 1')
        self.assertEqual(LRN.rejections('Bebelac 1'), {self.b2.id: 1})


class SearchBoxesUseMemoryTests(TestCase):
    """Item pickers (softech-search) and Ctrl+K (universal search) surface what people
    confirmed for a spelling — even Arabic for an English catalog name. Read-only."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.omez, = _items('OMEZ 10 14/CAP (2STRIPSX7)')
        LRN.learn_alias('اوميز 10', self.omez, source='whatsapp')
        self.user = get_user_model().objects.create_superuser('srch', password='x')

    def test_item_picker_search(self):
        from unittest import mock
        from rest_framework.test import APIClient
        c = APIClient()
        c.force_authenticate(self.user)
        with mock.patch('config.sybase.get_sybase_connection', side_effect=RuntimeError('offline')):
            r = c.get('/api/items/softech-search/', {'q': 'اومييز 10'})        # a typo, Arabic
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['results'][0]['item_id'], r.data['results'][0]['learned']), (self.omez.id, True))
        from apps.catalog.models import ItemAlias
        self.assertEqual(ItemAlias.objects.get().use_count, 1)              # searching never teaches

    def test_ctrl_k_universal_search(self):
        from apps.catalog.universal import universal_search
        items = universal_search('اوميز ١٠', types=['items'])['items']
        self.assertEqual((items[0]['id'], items[0]['learned']), (self.omez.id, True))


class PosAndShortageUseCaseTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient
        from apps.users.models import StaffProfile
        self.user = get_user_model().objects.create_superuser('uc', password='x')
        StaffProfile.objects.create(user=self.user, role='admin')      # POS RBAC needs a profile
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def test_pos_prescription_learns_the_replaced_suggestion(self):
        a, b = _items('CONCOR 5MG 30TAB', 'CONCOR 10MG 30TAB')
        r = self.c.post('/api/pos-orders/prescription-ocr/teach/',
                        {'raw_name': 'كونكور', 'item_id': b.id, 'suggested_item_id': a.id}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(LRN.lookup_alias('كونكور')['item_id'], b.id)
        self.assertEqual(LRN.rejections('كونكور'), {a.id: 1})

    def test_shortage_import_splits_a_remembered_group(self):
        from apps.branches.models import Branch
        from apps.shortage.models import ShortageList
        p1, p2 = _items('STREPSILS COOL 16LOZ', 'STREPSILS HONEY 24LOZ')
        LRN.learn_alias_group('ستربسلز كل النكهات', [p1, p2], source='whatsapp')
        sl = ShortageList.objects.create(branch=Branch.objects.create(name='B', softech_branch_id='130'))
        r = self.c.post(f'/api/shortage/lists/{sl.pk}/bulk-import/', {'lines': ['ستربسلز كل النكهات 2']}, format='json')
        self.assertEqual(r.status_code, 200)
        rows = list(sl.items.order_by('id'))
        self.assertEqual([(x.item_id, float(x.quantity_needed), x.is_confirmed) for x in rows],
                         [(p1.id, 2.0, False), (p2.id, 2.0, False)])


class BranchRequestLearningTests(TestCase):
    def test_group_memory_applies_to_whatsapp_lines(self):
        from apps.supply import branch_requests as W
        p1, p2 = _items('PECTOL CHERRY + VITAMIN C 8TAB', 'PECTOL HONEY 8TAB')
        LRN.learn_alias_group('pectol mix', [p1, p2], source='whatsapp')
        frag = W.extract('Pectol mix')[0]
        out = W.resolve(frag)
        self.assertEqual((out['item'].id, out['extra_ids'], out['flags']), (p1.id, [p2.id], ['learned_group']))
