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

    def test_engine_with_only_wildcards_falls_back_to_plain_list(self):
        rows = self.get(search='**', rank='engine')['results']
        self.assertEqual(len(rows), len(self.it))
        self.assertTrue(all('tier' not in x for x in rows))
