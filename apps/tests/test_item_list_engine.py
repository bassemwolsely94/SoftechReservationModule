"""
S2 Task 1 — `/api/items/?search=…&rank=engine`: the item list ranked by the search engine
(apps/catalog/wildcard.item_search) with the SAME row shape as the plain list, plus the tier
flags. Without `rank=engine` the list is unchanged (literal → pattern → any-order rank, then
the sort column).
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.catalog.models import Category, Item
from apps.shortage import phonetic as P

URL = '/api/items/'


class ItemListEngineTests(TestCase):
    def setUp(self):
        P.reset_index()
        cache.delete('catalog:softech_search_down')
        self.cat_a = Category.objects.create(softech_id='EA1', name='Analgesics')
        self.cat_b = Category.objects.create(softech_id='EB1', name='Other')
        seed = [
            ('VOLTAREN 50MG 20TAB', self.cat_a, 30),
            ('VOLTAREN 75MG/3ML 6AMP', self.cat_b, 45),
            ('DIVOL 500ML', self.cat_b, 20),
            ('CONCOR 5MG 30TAB', self.cat_a, 60),
            ('CONCOR COR 2.5MG 30TAB', self.cat_a, 40),
            ('CONCOR 10MG 30TAB', self.cat_b, 80),
            ('AUGMENTIN 1G 14 TAB', self.cat_b, 120),
            ('PANADOL EXTRA 24TAB', self.cat_a, 25),
            ('CATAFLAM 50MG 20TAB', self.cat_a, 35),
        ]
        # letter-only codes: a digit in softech_id would match the plain list's any-order rank
        self.it = {n: Item.objects.create(softech_id='ZQ' + chr(65 + i), name=n, category=c,
                                          pack_price=price, is_active=True)
                   for i, (n, c, price) in enumerate(seed)}
        from apps.chronic.models import ActiveIngredient, ItemIngredientMap
        dic = ActiveIngredient.objects.create(name='DICLOFENAC POTASSIUM')
        ItemIngredientMap.objects.create(item=self.it['CATAFLAM 50MG 20TAB'], active_ingredient=dic)
        self.user = get_user_model().objects.create_user(username='eng', password='x')
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def get(self, **params):
        r = self.c.get(URL, params)
        self.assertEqual(r.status_code, 200, r.content[:300])
        return r.json()

    def names(self, **params):
        return [x['name'] for x in self.get(**params)['results']]

    def test_engine_order(self):
        rows = self.get(search='vol*50', rank='engine')['results']
        names = [x['name'] for x in rows]
        self.assertIn('VOLTAREN 50MG 20TAB', names)
        self.assertIn('DIVOL 500ML', names)
        self.assertLess(names.index('VOLTAREN 50MG 20TAB'), names.index('DIVOL 500ML'))
        self.assertTrue(all('tier' in x for x in rows))
        self.assertEqual(rows[0]['tier'], 'starts')

    def test_plain_search_unchanged(self):
        # today's rule: literal text → pattern in order → any order, then name A→Z;
        # «vol*50» has no literal hit, both match the pattern → alphabetical
        rows = self.get(search='vol*50')['results']
        self.assertEqual([x['name'] for x in rows], ['DIVOL 500ML', 'VOLTAREN 50MG 20TAB'])
        self.assertTrue(all('tier' not in x for x in rows))
        # literal text first: «concor 5» literally in two names; «concor*5» would add none
        self.assertEqual(self.names(search='concor 5'),
                         ['CONCOR 5MG 30TAB', 'CONCOR COR 2.5MG 30TAB'])
        # any word order is the last rank
        self.assertEqual(self.names(search='50mg voltaren'), ['VOLTAREN 50MG 20TAB'])

    def test_engine_rows_have_same_keys_as_plain(self):
        plain = {x['id']: x for x in self.get(search='voltaren')['results']}
        engine = {x['id']: x for x in self.get(search='voltaren', rank='engine')['results']}
        iid = self.it['VOLTAREN 50MG 20TAB'].id
        self.assertIn(iid, plain)
        self.assertIn(iid, engine)
        p, e = plain[iid], engine[iid]
        self.assertTrue(set(p) <= set(e), set(p) - set(e))
        for k in p:
            self.assertEqual(p[k], e[k], k)

    def test_engine_respects_other_filters(self):
        rows = self.get(search='voltaren', rank='engine', category=self.cat_a.id)['results']
        self.assertEqual([x['name'] for x in rows], ['VOLTAREN 50MG 20TAB'])

    def test_engine_with_ordering(self):
        rows = self.get(search='concor', rank='engine', ordering='-pack_price')['results']
        self.assertEqual([x['name'] for x in rows],
                         ['CONCOR 10MG 30TAB', 'CONCOR 5MG 30TAB', 'CONCOR COR 2.5MG 30TAB'])

    def test_engine_ordering_tiebreak_pages_stably(self):
        # equal pack_price + ordering=pack_price: `id` is the final tiebreak, so page_size=1
        # walks every row exactly once, in a fixed order
        Item.objects.filter(name__startswith='CONCOR').update(pack_price=50)
        seen = []
        for page in (1, 2, 3):
            rows = self.get(search='concor', rank='engine', ordering='pack_price',
                            page_size=1, page=page)['results']
            self.assertEqual(len(rows), 1)
            seen.append(rows[0]['id'])
        expected = sorted(Item.objects.filter(name__startswith='CONCOR').values_list('id', flat=True))
        self.assertEqual(seen, expected)

    def test_engine_pagination(self):
        from apps.catalog.wildcard import item_search
        from apps.catalog.views import ENGINE_LIST_CAP
        n = len(item_search('concor', limit=ENGINE_LIST_CAP))
        self.assertEqual(n, 3)
        p1 = self.get(search='concor', rank='engine', page_size=2)
        p2 = self.get(search='concor', rank='engine', page_size=2, page=2)
        self.assertEqual(p1['count'], n)
        self.assertEqual(len(p1['results']), 2)
        self.assertEqual(len(p2['results']), 1)
        self.assertFalse({x['id'] for x in p1['results']} & {x['id'] for x in p2['results']})

    def test_plain_list_ignores_page_size(self):
        # only rank=engine reads page_size; the plain list keeps the global page size
        self.assertEqual(len(self.get(search='concor', page_size=2)['results']), 3)

    def test_engine_flags(self):
        rows = self.get(search='panadool', rank='engine')['results']
        self.assertTrue(rows)
        self.assertEqual(rows[0]['name'], 'PANADOL EXTRA 24TAB')
        self.assertIs(rows[0].get('approx'), True)
        self.assertEqual(rows[0]['tier'], 'approx')
        rows = self.get(search='diclofenac', rank='engine')['results']
        ing = [x for x in rows if x['tier'] == 'ingredient']
        self.assertEqual([x['name'] for x in ing], ['CATAFLAM 50MG 20TAB'])
        self.assertIs(ing[0]['ingredient'], True)
        self.assertEqual(ing[0]['ingredient_name'], 'DICLOFENAC POTASSIUM')
        # a plain name row carries no flag keys
        rows = self.get(search='voltaren', rank='engine')['results']
        self.assertNotIn('approx', rows[0])
        self.assertNotIn('ingredient_name', rows[0])

    def test_engine_query_count(self):
        """The list adds ≤ 8 queries to the engine's own (item_search: code lookup, the
        savepoint + SET LOCAL pair around the name rank, …) for page_size=10 — no N+1."""
        from apps.catalog.views import ENGINE_LIST_CAP
        from apps.catalog.wildcard import item_search
        with mock.patch('apps.shortage.learning.learned_item_ids', return_value=[]):
            self.get(search='concor', rank='engine', page_size=10)     # warm caches
            with CaptureQueriesContext(connection) as eng:
                item_search('concor', limit=ENGINE_LIST_CAP)
            with CaptureQueriesContext(connection) as ctx:
                self.get(search='concor', rank='engine', page_size=10)
        extra = len(ctx.captured_queries) - len(eng.captured_queries)
        self.assertLessEqual(extra, 8, '\n'.join(q['sql'][:160] for q in ctx.captured_queries))

    def _stock(self):
        """Branch A: 3 + 4 sellable for VOLTAREN 50 + 9 in quarantine store 102 (not sellable);
        branch B: 50. Returns (branch A, branch B)."""
        from apps.branches.models import Branch
        from apps.catalog.models import ItemStock
        a = Branch.objects.create(code='SA', name='SA', softech_branch_id='SA')
        b = Branch.objects.create(code='SB', name='SB', softech_branch_id='SB')
        v = self.it['VOLTAREN 50MG 20TAB']
        ItemStock.objects.create(item=v, branch=a, softech_store_code='1', quantity_on_hand=3)
        ItemStock.objects.create(item=v, branch=a, softech_store_code='2', quantity_on_hand=4)
        ItemStock.objects.create(item=v, branch=a, softech_store_code='102', quantity_on_hand=9)
        ItemStock.objects.create(item=v, branch=b, softech_store_code='1', quantity_on_hand=50)
        return a, b

    def test_engine_rows_carry_stock_at_the_branch(self):
        """S3 T5 fix: `branch=<pk>` → each engine row's sellable stock at THAT branch only."""
        a, b = self._stock()
        rows = {x['name']: x for x in self.get(search='voltaren', rank='engine', branch=a.id)['results']}
        self.assertEqual(rows['VOLTAREN 50MG 20TAB']['qty_at_branch'], 7.0)    # 102 + branch B left out
        self.assertEqual(rows['VOLTAREN 75MG/3ML 6AMP']['qty_at_branch'], 0.0)
        rows = {x['name']: x for x in self.get(search='voltaren', rank='engine', branch=b.id)['results']}
        self.assertEqual(rows['VOLTAREN 50MG 20TAB']['qty_at_branch'], 50.0)

    def test_no_branch_or_bad_branch_adds_no_stock_field(self):
        self._stock()
        for params in ({}, {'branch': 'abc'}, {'branch': ''}):
            rows = self.get(search='voltaren', rank='engine', **params)['results']
            self.assertTrue(rows)
            self.assertTrue(all('qty_at_branch' not in x for x in rows), params)
        # the plain list never carries it (its row shape is unchanged)
        rows = self.get(search='voltaren', branch=1)['results']
        self.assertTrue(all('qty_at_branch' not in x for x in rows))

    def test_branch_stock_adds_no_query(self):
        """qty_at_branch comes from the stock rows the list already prefetches: no N+1."""
        a, _ = self._stock()
        with mock.patch('apps.shortage.learning.learned_item_ids', return_value=[]):
            self.get(search='voltaren', rank='engine', page_size=10)     # warm caches
            with CaptureQueriesContext(connection) as plain:
                self.get(search='voltaren', rank='engine', page_size=10)
            with CaptureQueriesContext(connection) as br:
                self.get(search='voltaren', rank='engine', page_size=10, branch=a.id)
        self.assertEqual(len(br.captured_queries), len(plain.captured_queries),
                         '\n'.join(q['sql'][:160] for q in br.captured_queries))

    def test_engine_with_only_wildcards_falls_back_to_plain_list(self):
        rows = self.get(search='**', rank='engine')['results']
        self.assertEqual(len(rows), len(self.it))
        self.assertTrue(all('tier' not in x for x in rows))


class EngineCapAfterFiltersTests(TestCase):
    """The engine's row cap (ENGINE_LIST_CAP) cuts AFTER the list's other filters: item_search
    runs inside the filtered items (its `base`), so a filtered match ranked below the cap in the
    whole catalog is still found. The dropdown (page 1, page_size ≤ 10) ranks only the name
    window."""

    def setUp(self):
        P.reset_index()
        self.cat_a = Category.objects.create(softech_id='CA1', name='A')
        self.cat_b = Category.objects.create(softech_id='CB1', name='B')
        # five «TABX …» names that sort before the target, all in category A / supplier S1
        for i in range(5):
            Item.objects.create(softech_id=f'ZA{i}', name=f'TABX {chr(65 + i)} ITEM', category=self.cat_a,
                                supplier_code='S1', pack_price=10, is_active=True)
        self.target = Item.objects.create(softech_id='ZT1', name='TABX ZULU ITEM', category=self.cat_b,
                                          supplier_code='S2', pack_price=99, is_active=True)
        self.user = get_user_model().objects.create_user(username='cap', password='x')
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def ids(self, **params):
        r = self.c.get(URL, {'search': 'tabx', 'rank': 'engine', **params})
        self.assertEqual(r.status_code, 200, r.content[:300])
        return [x['id'] for x in r.json()['results']]

    def test_filtered_target_below_the_global_cap_is_found(self):
        from apps.catalog.wildcard import item_search
        with mock.patch('apps.catalog.views.ENGINE_LIST_CAP', 3):
            # the whole catalog's top 3 does NOT hold the target …
            self.assertNotIn(self.target.id, [i for i, _ in item_search('tabx', limit=3)])
            # … but every filter narrows the engine's own search first
            self.assertEqual(self.ids(supplier_code='S2'), [self.target.id])
            self.assertEqual(self.ids(category=self.cat_b.id), [self.target.id])
            self.assertEqual(self.ids(pack_price_min='50'), [self.target.id])
            self.assertEqual(len(self.ids(supplier_code='S1')), 3)

    def test_in_stock_filter_runs_inside_the_engine(self):
        from apps.branches.models import Branch
        from apps.catalog.models import ItemStock
        br = Branch.objects.create(code='T1', name='T1')
        ItemStock.objects.create(item=self.target, branch=br, quantity_on_hand=4)
        with mock.patch('apps.catalog.views.ENGINE_LIST_CAP', 3):
            self.assertEqual(self.ids(in_stock='true'), [self.target.id])

    def test_no_filter_passes_no_base(self):
        # without a filter the engine runs exactly as before (its default base)
        with mock.patch('apps.catalog.wildcard.item_search', return_value=[]) as m:
            self.ids()
            self.assertIsNone(m.call_args.kwargs['base'])
            self.ids(supplier_code='S2')
            self.assertIsNotNone(m.call_args.kwargs['base'])

    def test_learned_and_sound_rows_stay_inside_the_filter(self):
        with mock.patch('apps.shortage.learning.learned_item_ids',
                        return_value=[Item.objects.get(softech_id='ZA0').id, self.target.id]):
            self.assertEqual(self.ids(supplier_code='S2'), [self.target.id])

    def test_picker_page_uses_the_name_window(self):
        from apps.catalog.views import ENGINE_LIST_CAP
        from apps.catalog.wildcard import NAME_WINDOW
        with mock.patch('apps.catalog.wildcard.item_search', return_value=[]) as m:
            for params, cap in (({'page_size': 10}, NAME_WINDOW),
                                ({'page_size': 5, 'page': 1}, NAME_WINDOW),
                                ({'page_size': 30}, ENGINE_LIST_CAP),     # the Ctrl+F1 modal
                                ({'page_size': 10, 'page': 2}, ENGINE_LIST_CAP),
                                ({}, ENGINE_LIST_CAP)):
                # (page 2 of an empty mocked set answers 404 — only the engine call matters here)
                self.c.get(URL, {'search': 'tabx', 'rank': 'engine', **params})
                self.assertEqual(m.call_args.kwargs['limit'], cap, params)


class FilteredSoundAndTypoTests(TestCase):
    """S3 Task 1 — a filter in the Ctrl+F1 modal narrows the «بالنطق» (sound) and «تقريبي»
    (approx) tiers too: the sound index drops items outside the filter BEFORE it keeps its best
    candidates, so a filtered item ranked below the whole catalog's cut is still found."""

    QUERY_AR = 'بنادول'          # sounds like PANADOL (skeleton BNDL)

    def setUp(self):
        P.reset_index()
        cache.delete('catalog:softech_search_down')
        self.cat_a = Category.objects.create(softech_id='FA1', name='Crowd')
        self.cat_b = Category.objects.create(softech_id='FB1', name='Target')
        # more perfect sound-alikes than the index keeps per lookup (60) and than `limit` …
        for i in range(65):
            Item.objects.create(softech_id=f'FS{i:03d}', name='PANADOL TAB', category=self.cat_a,
                                pack_price=10, is_active=True)
        # … and one weaker (still ≥ 0.75) sound-alike, the only item in category B
        self.target = Item.objects.create(softech_id='FT001', name='BANADORL TAB', category=self.cat_b,
                                          pack_price=10, is_active=True)
        self.user = get_user_model().objects.create_user(username='snd', password='x')
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def test_filtered_sound_match_outside_global_top(self):
        from apps.catalog.wildcard import item_search
        # the whole catalog's sound tier does not reach the target …
        self.assertNotIn(self.target.id, [i for i, _ in item_search(self.QUERY_AR)])
        # … the filtered one does, as a sound row
        got = item_search(self.QUERY_AR, base=Item.objects.filter(category=self.cat_b))
        self.assertEqual(got, [(self.target.id, 'sound')])

    def test_filtered_sound_match_through_the_modal_list(self):
        r = self.c.get(URL, {'search': self.QUERY_AR, 'rank': 'engine', 'category': self.cat_b.id,
                             'page_size': 30})
        self.assertEqual(r.status_code, 200, r.content[:300])
        rows = r.json()['results']
        self.assertEqual([x['id'] for x in rows], [self.target.id])
        self.assertTrue(rows[0].get('sound'), rows[0])

    def test_filtered_typo_match_outside_global_top(self):
        from apps.catalog.wildcard import item_search
        with mock.patch('apps.shortage.matching.find_best_matches', return_value=[]):
            self.assertNotIn(self.target.id, [i for i, _ in item_search('panadool')])
            got = item_search('panadool', base=Item.objects.filter(category=self.cat_b))
        self.assertEqual(got, [(self.target.id, 'approx')])

    def test_filter_still_drops_items_outside_it(self):
        from apps.catalog.wildcard import item_search
        crowd = set(Item.objects.filter(category=self.cat_a).values_list('id', flat=True))
        got = item_search(self.QUERY_AR, base=Item.objects.filter(category=self.cat_a), limit=5)
        self.assertEqual(len(got), 5)
        self.assertTrue(all(i in crowd and t == 'sound' for i, t in got), got)
