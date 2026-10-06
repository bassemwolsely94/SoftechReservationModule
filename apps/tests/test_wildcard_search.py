"""
System-wide item search rules (apps/catalog/wildcard.py) — owner decision 2026-10-05:
`*` and `%` are both wildcards, always "contains", parts in the order typed, space literal;
exact literal text ranks first, then the pattern, then the same words in any order; typos /
Arabic by sound when nothing matches.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.catalog import wildcard as W
from apps.shortage import phonetic as P


class ParseTests(SimpleTestCase):
    def test_star_and_percent_are_the_same_wildcard(self):
        self.assertEqual(W.pattern('vol*ren*50*tab*'), '%VOL%REN%50%TAB%')
        self.assertEqual(W.pattern('vol%ren%50%tab'), '%VOL%REN%50%TAB%')
        self.assertEqual(W.pattern('voltaren 50%tab'), '%VOLTAREN 50%TAB%')    # space kept literal

    def test_literal_pattern_escapes_like_specials(self):
        self.assertEqual(W.literal_pattern('1% cream'), '%1\\% CREAM%')
        self.assertEqual(W.pattern('a_b'), '%A\\_B%')                           # _ is not a wildcard

    def test_terms(self):
        p = W.parse('  50   voltaren*tab ')
        self.assertEqual(p['raw'], '50 voltaren*tab')
        self.assertEqual(p['terms'], ['50', 'voltaren', 'tab'])
        self.assertTrue(p['wild'])
        self.assertEqual(W.parse('**')['segments'], [])


def _items(*names, active=True):
    from apps.catalog.models import Item
    return {n: Item.objects.create(softech_id=str(940000 + i + (0 if active else 500)), name=n,
                                   pack_price=10, is_active=active)
            for i, n in enumerate(names)}


class ItemSearchTests(TestCase):
    def setUp(self):
        P.reset_index()
        self.it = _items(
            'VOLTAREN 50MG 20TAB (2STRIPSX10) فولتارين 50مجم', 'VOLTAREN 1% EMULGEL 50GM',
            'VOLTAREN 75MG/3ML 6AMP', 'TINOX 1% CREAM 15 GM', 'BETNOVATE 0.1 CREAM 30GM',
            'IVERZINE 1% CREAM 30 GM', 'CATAFLAM  50MG 20TAB', 'PANADOL EXTRA 24TAB',
            'AUGMENTIN 1G (1000MG) 14 TAB')

    def tiers(self, q, **kw):
        from apps.catalog.models import Item
        names = dict(Item.objects.values_list('id', 'name'))
        return [(names[i], t) for i, t in W.item_search(q, **kw)]

    def test_softech_style_wildcards(self):
        for q in ('vol*ren*50*tab*', 'vol%ren%50%tab', 'voltaren 50%tab', 'VOL*REN*50'):
            res = self.tiers(q)
            self.assertTrue(res, q)
            self.assertTrue(res[0][0].startswith('VOLTAREN 50MG'), (q, res))

    def test_parts_must_be_in_order_otherwise_any_order_tier(self):
        res = self.tiers('50*voltaren')
        self.assertEqual(res[0], ('VOLTAREN 50MG 20TAB (2STRIPSX10) فولتارين 50مجم', 'any_order'))
        self.assertTrue(all(t == 'any_order' for _, t in res))

    def test_exact_text_first(self):
        # «1% cream» as a pattern also matches BETNOVATE 0.1 CREAM — but the items that
        # literally say "1% CREAM" lead
        res = self.tiers('1% cream')
        names = [n for n, _ in res]
        self.assertIn('BETNOVATE 0.1 CREAM 30GM', names)
        lit = [n for n, t in res if t == 'literal']
        self.assertEqual(set(lit), {'TINOX 1% CREAM 15 GM', 'IVERZINE 1% CREAM 30 GM'})
        self.assertLess(max(names.index(n) for n in lit), names.index('BETNOVATE 0.1 CREAM 30GM'))

    def test_space_is_literal(self):
        res = self.tiers('volta ren')        # not "volta*ren" — only the any-order tier finds it
        self.assertTrue(res)
        self.assertTrue(all(t == 'any_order' for _, t in res))

    def test_code_first(self):
        code = self.it['CATAFLAM  50MG 20TAB'].softech_id
        self.assertEqual(self.tiers(code)[0], ('CATAFLAM  50MG 20TAB', 'code'))

    def test_inactive_items_hidden(self):
        _items('VOLTAREN OLD 50MG TAB', active=False)
        self.assertNotIn('VOLTAREN OLD 50MG TAB', [n for n, _ in self.tiers('voltaren')])

    def test_typo_fallback_only_when_nothing_found(self):
        res = self.tiers('voltren 50')      # 50MG tab and 50GM gel both fit — both lead
        self.assertEqual({t for _, t in res}, {'approx'})
        self.assertEqual({n for n, _ in res[:2]}, {'VOLTAREN 50MG 20TAB (2STRIPSX10) فولتارين 50مجم',
                                                   'VOLTAREN 1% EMULGEL 50GM'})
        self.assertEqual(self.tiers('voltren 50 tab')[0][0], 'VOLTAREN 50MG 20TAB (2STRIPSX10) فولتارين 50مجم')
        self.assertEqual(self.tiers('agmentin 1g')[0], ('AUGMENTIN 1G (1000MG) 14 TAB', 'approx'))
        self.assertEqual(self.tiers('panadool extra')[0][0], 'PANADOL EXTRA 24TAB')
        self.assertEqual(self.tiers('xqzvw'), [])                     # gibberish → no guess
        self.assertNotIn('approx', {t for _, t in self.tiers('voltaren')})

    def test_arabic_by_sound(self):
        res = self.tiers('كتافلام')
        self.assertTrue(res)
        self.assertEqual(res[0][0], 'CATAFLAM  50MG 20TAB')

    def test_wq_for_module_filters(self):
        from apps.catalog.models import Item
        qs = Item.objects.filter(W.wq('vol*50', 'name'))
        self.assertEqual({i.name for i in qs}, {'VOLTAREN 50MG 20TAB (2STRIPSX10) فولتارين 50مجم',
                                                'VOLTAREN 1% EMULGEL 50GM'})
        # any word order
        self.assertEqual(Item.objects.filter(W.wq('cream tinox', 'name')).count(), 1)
        # empty query filters nothing
        self.assertEqual(Item.objects.filter(W.wq('', 'name')).count(), Item.objects.count())


class SearchEndpointTests(TestCase):
    def setUp(self):
        P.reset_index()
        cache.delete('catalog:softech_search_down')
        _items('VOLTAREN 50MG 20TAB', 'TINOX 1% CREAM 15 GM', 'BETNOVATE 0.1 CREAM 30GM',
               'IVERZINE 1% CREAM 30 GM')
        self.user = get_user_model().objects.create_user(username='wild', password='x')
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def test_item_list_search_ranks_literal_first(self):
        r = self.c.get('/api/items/', {'search': '1% cream', 'ordering': 'name'})
        self.assertEqual(r.status_code, 200)
        rows = r.json().get('results', r.json())
        names = [x['name'] for x in rows]
        self.assertEqual(names[:2], ['IVERZINE 1% CREAM 30 GM', 'TINOX 1% CREAM 15 GM'])
        self.assertIn('BETNOVATE 0.1 CREAM 30GM', names[2:])

    def test_softech_search_pg_first_without_softech(self):
        with mock.patch('apps.catalog.views._softech_live_search') as live:
            r = self.c.get('/api/items/softech-search/', {'q': 'vol*ren*50*tab*'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['results'][0]['name'], 'VOLTAREN 50MG 20TAB')
        live.assert_not_called()                         # PG had it — SOFTECH not asked

    def test_softech_breaker(self):
        from apps.catalog.views import _softech_live_search
        with mock.patch('config.sybase.get_sybase_connection', side_effect=OSError('down')) as conn:
            self.assertEqual(_softech_live_search('%x%', None), [])
            self.assertEqual(_softech_live_search('%x%', None), [])
        self.assertEqual(conn.call_count, 1)             # second call short-circuits
        cache.delete('catalog:softech_search_down')

    def test_softech_search_flags_approx(self):
        with mock.patch('apps.catalog.views._softech_live_search', return_value=[]):
            r = self.c.get('/api/items/softech-search/', {'q': 'voltren 50'})
        res = r.json()['results']
        self.assertTrue(res and res[0]['name'] == 'VOLTAREN 50MG 20TAB' and res[0].get('approx'))
