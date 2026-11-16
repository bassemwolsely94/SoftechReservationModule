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
        for q in ('vol*ren*50*tab*', 'vol%ren%50%tab', 'voltaren 50%tab'):
            res = self.tiers(q)
            self.assertTrue(res, q)
            self.assertTrue(res[0][0].startswith('VOLTAREN 50MG'), (q, res))
        # 'VOL*REN*50' matches the 50 GM emulgel as well — same tier, no defined order between them
        res = self.tiers('VOL*REN*50')
        self.assertTrue(any(n.startswith('VOLTAREN 50MG') for n, _ in res), res)

    def test_parts_must_be_in_order_otherwise_any_order_tier(self):
        res = self.tiers('50*voltaren')
        # the 50 GM emulgel matches too — same tier, no defined order between them
        self.assertIn(('VOLTAREN 50MG 20TAB (2STRIPSX10) فولتارين 50مجم', 'any_order'), res)
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
        cache.clear()                                    # no cached '%x%' rows from another test
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


class LikeSpecialsAreLiteralTests(TestCase):
    """Round 2, R5: LIKE's own specials in typed text are matched as text, never as a pattern.
    `_` and `\` are always literal; `%` is literal in the exact-text tier (it ranks first) and,
    by the owner decision of 2026-10-05, a wildcard like `*` in the pattern tiers."""

    def setUp(self):
        P.reset_index()
        self.it = _items('ALPHA_BETA 10MG', 'ALPHAXBETA 10MG', 'GAMMA\DELTA SYRUP',
                         'GAMMAXDELTA SYRUP', 'ZETA 1% GEL', 'ZETA 1X GEL', "O'NEIL; DROP TABLE")

    def names(self, q):
        from apps.catalog.models import Item
        names = dict(Item.objects.values_list('id', 'name'))
        return [(names[i], t) for i, t in W.item_search(q) if t not in ('sound', 'approx')]

    def test_underscore_is_not_a_single_char_wildcard(self):
        self.assertEqual([n for n, _ in self.names('alpha_beta')], ['ALPHA_BETA 10MG'])

    def test_backslash_is_not_an_escape(self):
        self.assertEqual([n for n, _ in self.names('gamma\delta')], ['GAMMA\DELTA SYRUP'])

    def test_percent_is_literal_in_the_exact_text_tier(self):
        res = self.names('zeta 1% gel')
        self.assertEqual([n for n, t in res if t == 'literal'], ['ZETA 1% GEL'])
        self.assertEqual(res[0][0], 'ZETA 1% GEL')

    def test_quote_and_semicolon_are_plain_text(self):
        self.assertEqual([n for n, _ in self.names("o'neil; drop")], ["O'NEIL; DROP TABLE"])
        from apps.catalog.models import Item
        self.assertEqual(Item.objects.count(), 7)

    def test_wq_module_filter_keeps_specials_literal(self):
        from apps.catalog.models import Item
        got = set(Item.objects.filter(W.wq('alpha_beta', 'name')).values_list('name', flat=True))
        self.assertEqual(got, {'ALPHA_BETA 10MG'})
        got = set(Item.objects.filter(W.wq('gamma\delta', 'name')).values_list('name', flat=True))
        self.assertEqual(got, {'GAMMA\DELTA SYRUP'})


class CodeTierTests(TestCase):
    """Exact code / barcode must hit the b-tree index (no UPPER()); partial codes are a
    last-place `code_part` tier that never runs on the POS path."""

    def setUp(self):
        from apps.catalog.models import Item, ItemBarcode
        self.augmentin = Item.objects.create(softech_id='3690', name='AUGMENTIN 1G (1000MG) 14 TAB',
                                             pack_price=10, is_active=True)
        ItemBarcode.objects.create(item=self.augmentin, barcode='6221025032348')
        self.souvenir = Item.objects.create(softech_id='990001', name='SOUVENIR ROGO COLORE 250M(3690) PERFUME',
                                            pack_price=10, is_active=True)
        self.concor = Item.objects.create(softech_id='136900', name='CONCOR 5MG 30TAB',
                                          pack_price=10, is_active=True)

    def test_exact_code_uses_index(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            res = W.item_search('3690')
        sql = ' '.join(q['sql'] for q in ctx.captured_queries)
        self.assertNotIn('UPPER("catalog_item"."softech_id")', sql)
        self.assertNotIn('UPPER("catalog_itembarcode"."barcode")', sql)
        # PostgreSQL renders iexact as UPPER("col"::text): catch any UPPER() on the code columns
        self.assertNotRegex(sql, r'UPPER\("catalog_item(barcode)?"\."(softech_id|barcode)"')
        self.assertEqual(res[0], (self.augmentin.id, 'code'))

    def test_barcode_exact(self):
        self.assertEqual(W.item_search('6221025032348')[0], (self.augmentin.id, 'code'))

    def test_code_part_outside_pos(self):
        res = W.item_search('690')
        self.assertIn((self.augmentin.id, 'code_part'), res)
        self.assertIn((self.concor.id, 'code_part'), res)
        tiers = [t for _, t in res]
        first_part = tiers.index('code_part')
        self.assertTrue(all(t == 'code_part' for t in tiers[first_part:]))
        ids = [i for i, _ in res]
        self.assertLess(ids.index(self.souvenir.id), first_part)

    def test_code_part_never_on_pos_path(self):
        res = W.item_search('690', code_prefix=False)
        self.assertNotIn('code_part', [t for _, t in res])


class FoldTests(TestCase):
    """Names are matched on a folded form (Arabic letter variants, Arabic digits, space runs)
    served by the trigram expression indexes (catalog migration 0044)."""

    def test_fold_query(self):
        self.assertEqual(W.fold_query('  أوجمنتين   ١ جم '), 'اوجمنتين 1 جم')
        self.assertEqual(W.fold_query('vol*ren'), 'VOL*REN')

    def test_arabic_digits_fold(self):
        self.assertEqual(W.pattern('كونجستال ٢٠'), '%كونجستال 20%')

    def test_hamza_matches_literally(self):
        ids = _items('AUGMENTIN 156MG SYRUP 80ML اوجمنتين 156مجم شراب')
        iid = next(iter(ids.values())).id
        res = dict(W.item_search('أوجمنتين'))
        self.assertIn(iid, res)
        self.assertNotIn(res[iid], ('sound', 'approx', 'any_order'))
        self.assertIn(res[iid], {'literal', 'ordered', 'starts', 'word', 'contains'})

    def test_db_side_fold_on_stored_names(self):
        # the STORED names carry أ ة ى ; the queries are typed with ا ه ي — only the SQL
        # translate() (argument order!) can make these meet
        ids = _items('أوميز 20 كبسولة', 'فيتامين سى', 'مؤسسة  ئ  كريم')
        by = {n: i.id for n, i in ids.items()}
        for q, name in (('اوميز', 'أوميز 20 كبسولة'), ('كبسوله', 'أوميز 20 كبسولة'),
                        ('سي', 'فيتامين سى'), ('موسسه', 'مؤسسة  ئ  كريم'),
                        ('ي كريم', 'مؤسسة  ئ  كريم')):
            res = dict(W.item_search(q))
            self.assertIn(by[name], res, q)
            self.assertIn(res[by[name]], {'literal', 'ordered', 'starts', 'word', 'contains'}, (q, res))
            self.assertNotIn(res[by[name]], ('sound', 'approx', 'any_order'), q)

    def test_spaces_collapse(self):
        ids = _items('VOLTAREN   1% 15  GM  EMULGEL')
        iid = next(iter(ids.values())).id
        res = W.item_search('VOLTAREN 1% 15 GM')
        self.assertEqual(res[0][0], iid)
        self.assertNotIn(res[0][1], ('sound', 'approx', 'any_order'))
        self.assertIn(res[0][1], {'literal', 'ordered', 'starts', 'word', 'contains'})

    def test_fold_sql_null_safe(self):
        from apps.catalog.models import Item
        _items('NULLSAFE ONE')
        Item.objects.update(name_scientific='')
        self.assertEqual(Item.objects.filter(name_scientific__fulike='%X%').count(), 0)
        self.assertEqual(Item.objects.filter(name__fulike='%NULLSAFE%').count(), 1)

    def test_index_used(self):
        from django.db import connection
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL only')
        from apps.catalog.models import Item
        with connection.cursor() as cur:
            cur.execute('SET LOCAL enable_seqscan = off')
            cur.execute('SET LOCAL enable_indexscan = off')    # not a full b-tree walk: bitmap on the trigram index
            sql, params = Item.objects.filter(name__fulike='%PANADOL%').values('id').query.sql_with_params()
            cur.execute('EXPLAIN ' + sql, params)
            plan = '\n'.join(r[0] for r in cur.fetchall())
            sql, params = Item.objects.filter(name_scientific__fulike='%PANADOL%').values('id').query.sql_with_params()
            cur.execute('EXPLAIN ' + sql, params)
            plan2 = '\n'.join(r[0] for r in cur.fetchall())
        self.assertIn('catalog_item_name_fold_trgm', plan)
        self.assertIn('catalog_item_sci_fold_trgm', plan2)
