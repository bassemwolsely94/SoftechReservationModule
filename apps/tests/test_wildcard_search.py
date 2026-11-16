"""
System-wide item search rules (apps/catalog/wildcard.py) — owner decision 2026-10-05:
`*` and `%` are both wildcards, always "contains", parts in the order typed, space literal;
the name starts with it, then a part starts a word, then contains (exact literal text before
the pattern), then the same words in any order; whole typed numbers lead each tier; typos /
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
        lit = {'TINOX 1% CREAM 15 GM', 'IVERZINE 1% CREAM 30 GM'}
        self.assertEqual(set(names[:2]), lit)
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
        # both names START with the pattern ZETA 1*GEL; the one saying exactly "1% GEL" leads
        self.assertEqual(res[:2], [('ZETA 1% GEL', 'starts'), ('ZETA 1X GEL', 'starts')])

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
        self.assertIn(res[iid], {'starts', 'word', 'contains'})

    def test_db_side_fold_on_stored_names(self):
        # the STORED names carry أ ة ى ; the queries are typed with ا ه ي — only the SQL
        # translate() (argument order!) can make these meet
        ids = _items('أوميز 20 كبسولة', 'فيتامين سى', 'مؤسسة  ئ  كريم')
        by = {n: i.id for n, i in ids.items()}
        for q, name in (('اوميز', 'أوميز 20 كبسولة'), ('كبسوله', 'أوميز 20 كبسولة'),
                        # ≥3 letters: D7 makes a 2-letter «سي» starts-only
                        ('مين سي', 'فيتامين سى'), ('موسسه', 'مؤسسة  ئ  كريم'),
                        ('ي كريم', 'مؤسسة  ئ  كريم')):
            res = dict(W.item_search(q))
            self.assertIn(by[name], res, q)
            self.assertIn(res[by[name]], {'starts', 'word', 'contains'}, (q, res))
            self.assertNotIn(res[by[name]], ('sound', 'approx', 'any_order'), q)

    def test_spaces_collapse(self):
        ids = _items('VOLTAREN   1% 15  GM  EMULGEL')
        iid = next(iter(ids.values())).id
        res = W.item_search('VOLTAREN 1% 15 GM')
        self.assertEqual(res[0][0], iid)
        self.assertNotIn(res[0][1], ('sound', 'approx', 'any_order'))
        self.assertIn(res[0][1], {'starts', 'contains'})

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


class RankingTests(TestCase):
    """SOFTECH-ordered ranking (design §5.2): starts → word → contains (literal text, then the
    pattern) → any order; inside a tier whole typed numbers first (D2), then name A→Z; a hit
    only in name_scientific one step below the same hit in name."""

    def setUp(self):
        from apps.catalog.models import Item
        P.reset_index()
        self.it = _items(
            'VOLTAREN 50MG 20TAB', 'DIVOL KIDS SHAMPOO 500ML', 'CONCOR 5MG 30TAB',
            'CONCOR COR 2.5MG 30TAB', 'CONCOR 10MG 30TAB', 'CONCOR AMLO 5MG/5MG 30TAB',
            'PANADOL EXTRA 24TAB', 'FIRST SURG PAD DRESSING', 'HEPATICUM 140 MG 30CAP',
            'TINOX 1% CREAM 15 GM', 'BETNOVATE 0.1 CREAM 30GM', 'SOMEBRAND',
            'AUGMENTIN (1G) TAB')
        Item.objects.filter(name='SOMEBRAND').update(name_scientific='PANADOL GENERIC')

    def tiers(self, q, **kw):
        from apps.catalog.models import Item
        names = dict(Item.objects.values_list('id', 'name'))
        return [(names[i], t) for i, t in W.item_search(q, **kw)]

    def names(self, q):
        return [n for n, _ in self.tiers(q)]

    def test_starts_before_contains(self):
        res = self.tiers('vol*50')
        self.assertEqual(res[0], ('VOLTAREN 50MG 20TAB', 'starts'))
        names = [n for n, _ in res]
        self.assertIn('DIVOL KIDS SHAMPOO 500ML', names)
        self.assertGreater(names.index('DIVOL KIDS SHAMPOO 500ML'), 0)
        self.assertEqual(dict(res)['DIVOL KIDS SHAMPOO 500ML'], 'contains')

    def test_whole_number_first_but_all_digits_match(self):
        names = self.names('concor 5')
        self.assertEqual(names[0], 'CONCOR 5MG 30TAB')
        self.assertIn('CONCOR COR 2.5MG 30TAB', names)                 # D2: digits match anywhere
        self.assertLess(names.index('CONCOR AMLO 5MG/5MG 30TAB'), names.index('CONCOR COR 2.5MG 30TAB'))

    def test_whole_number_boost_with_arabic_digits(self):
        self.assertEqual(self.tiers('concor ٥')[0][0], 'CONCOR 5MG 30TAB')

    def test_decimal_is_one_number(self):
        # «2» is not a whole-number hit inside 2.5 either: the plain 2-something wins the boost
        from apps.catalog.models import Item
        Item.objects.create(softech_id='941990', name='CONCOR COR 2MG 30TAB', pack_price=10, is_active=True)
        names = self.names('concor cor 2')
        self.assertEqual(names[:2], ['CONCOR COR 2MG 30TAB', 'CONCOR COR 2.5MG 30TAB'])

    def test_two_letters_starts_only(self):
        res = self.tiers('pa')
        self.assertTrue(res)
        self.assertTrue(all(t == 'starts' for _, t in res), res)
        names = [n for n, _ in res]
        self.assertIn('PANADOL EXTRA 24TAB', names)
        self.assertNotIn('FIRST SURG PAD DRESSING', names)
        self.assertNotIn('HEPATICUM 140 MG 30CAP', names)
        # two digits are no name either (D7: names need 3 characters) — «14» ≠ HEPATICUM 140
        self.assertNotIn('HEPATICUM 140 MG 30CAP', self.names('14'))
        self.assertIn('HEPATICUM 140 MG 30CAP', self.names('140'))

    def test_word_tier(self):
        self.assertIn(('FIRST SURG PAD DRESSING', 'word'), self.tiers('pad'))

    def test_literal_text_before_pattern_in_contains(self):
        names = self.names('1% cream')
        self.assertIn('BETNOVATE 0.1 CREAM 30GM', names)
        self.assertLess(names.index('TINOX 1% CREAM 15 GM'), names.index('BETNOVATE 0.1 CREAM 30GM'))

    def test_name_before_scientific(self):
        res = self.tiers('panadol')
        names = [n for n, _ in res]
        self.assertIn('PANADOL EXTRA 24TAB', names)
        self.assertIn('SOMEBRAND', names)
        self.assertLess(names.index('PANADOL EXTRA 24TAB'), names.index('SOMEBRAND'))
        self.assertEqual(dict(res)['SOMEBRAND'], 'starts')       # same tier name, lower rank

    def test_same_tier_sorted_by_name(self):
        res = self.tiers('concor')
        starts = [n for n, t in res if t == 'starts']
        self.assertEqual(starts, sorted(starts))                  # no numbers typed → name A→Z
        self.assertLess(starts.index('CONCOR 10MG 30TAB'), starts.index('CONCOR 5MG 30TAB'))
        # with a number: whole-number score first, then name
        res = self.tiers('concor*5')
        starts = [n for n, t in res if t == 'starts']
        self.assertEqual(starts[:2], ['CONCOR 5MG 30TAB', 'CONCOR AMLO 5MG/5MG 30TAB'])
        self.assertEqual(starts[2:], sorted(starts[2:]))
        self.assertIn('CONCOR COR 2.5MG 30TAB', starts[2:])

    def test_one_letter_returns_nothing(self):
        # D7: names need 3 characters, 2 = starts-with; 1 letter is no search at all
        self.assertEqual(W.item_search('a'), [])
        self.assertEqual(W.item_search('a*'), [])
        # one digit stays an exact code lookup
        from apps.catalog.models import Item
        it = Item.objects.create(softech_id='7', name='SEVEN TEST ITEM', pack_price=1, is_active=True)
        self.assertEqual(W.item_search('7'), [(it.id, 'code')])

    def test_starts_hits_survive_the_candidate_cap(self):
        # broad queries rank at most NAME_CAP pattern candidates — but every `starts` hit is
        # always a candidate, so the best rows can't fall outside a sample
        from apps.catalog.models import Item
        Item.objects.bulk_create([Item(softech_id=f'96{i:04d}', name=f'AAA DIVOLX {i:03d}', pack_price=1,
                                       is_active=True) for i in range(12)])
        with mock.patch.object(W, 'NAME_CAP', 3):
            res = self.tiers('vol')
        self.assertEqual(res[0], ('VOLTAREN 50MG 20TAB', 'starts'))

    def test_prefix_index_used(self):
        from django.db import connection
        from apps.catalog.models import Item
        # an empty test table plans on any index, so check the index is built on EXACTLY the
        # expression the lookup renders (PostgreSQL only matches an identical expression)
        sql, _ = Item.objects.filter(name__fulike='X%').values('id').query.sql_with_params()
        with connection.cursor() as cur:
            cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname IN "
                        "('catalog_item_name_fold_prefix', 'catalog_item_sci_fold_prefix')")
            defs = [r[0] for r in cur.fetchall()]
        self.assertEqual(len(defs), 2)
        self.assertTrue(all('text_pattern_ops' in d and 'translate(upper(regexp_replace' in d for d in defs))
        self.assertIn('translate(upper(regexp_replace', sql)

    def test_punctuation_only_returns_nothing(self):
        for q in ('**', '%', '-', '()', '  '):
            self.assertEqual(W.item_search(q), [], q)

    def test_regex_specials_are_plain_text(self):
        for q in ('augmentin (1g)', 'c++', 'a[b', 'a' + chr(92), '(?', '^$|.*'):
            W.item_search(q)                                      # never a regex error
        self.assertIn('AUGMENTIN (1G) TAB', self.names('augmentin (1g)'))

    def test_query_count_bounded(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as ctx:
            W.item_search('voltaren 50')
        # data round-trips: code+barcode (one UNION) · learned memory (3) · ranked names ·
        # any-order top-up. The SAVEPOINT / SET LOCAL enable_seqscan pair around the ranked
        # query (_trigram_indexes: keeps the planner on the trigram index) is not counted.
        data = [q['sql'] for q in ctx.captured_queries
                if not q['sql'].startswith(('SAVEPOINT', 'RELEASE SAVEPOINT', 'SET LOCAL'))]
        self.assertLessEqual(len(data), 6, [q[:120] for q in data])
        self.assertLessEqual(len(ctx.captured_queries), 10)

    def test_code_part_is_lazy(self):
        # the name tiers already fill `limit` → the code_part scans (no index) never run
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.catalog.models import Item
        Item.objects.bulk_create([Item(softech_id=f'95{i:04d}', name=f'BRAND 500{i} MG', pack_price=1,
                                       is_active=True) for i in range(5)])
        with CaptureQueriesContext(connection) as ctx:
            res = W.item_search('500', limit=3)
        self.assertEqual(len(res), 3)
        self.assertNotIn('code_part', [t for _, t in res])
        sql = ' '.join(q['sql'] for q in ctx.captured_queries)
        self.assertNotRegex(sql, r'"softech_id"::text LIKE|"barcode"::text LIKE')
        # not enough name hits → code_part runs and comes last
        res = W.item_search('0003', limit=60)        # inside 950003: no prefix, no name
        self.assertIn('code_part', [t for _, t in res])


class SynonymTests(TestCase):
    """Appendix A: a typed token also searches its canonical form — whole word or a unit glued
    to a number, one direction only (design §6 item 4)."""

    def setUp(self):
        P.reset_index()
        self.it = _items('AUGMENTIN 457MG/5ML SYRUP 70ML', 'AUGMENTIN 1G 14 TAB اوجمنتين',
                         'GLUCOSE GEL', 'VITAMIN C 500MG 30TAB', 'ZYRTEC ORAL DROPS 10ML')

    def tiers(self, q):
        from apps.catalog.models import Item
        names = dict(Item.objects.values_list('id', 'name'))
        return [(names[i], t) for i, t in W.item_search(q)]

    def test_form_abbreviation(self):
        res = self.tiers('augmentin syp')
        self.assertEqual(res[0], ('AUGMENTIN 457MG/5ML SYRUP 70ML', 'synonym'))

    def test_arabic_unit(self):
        # the name has NO Arabic: «جم» can only reach `1G` through the table (G / GM)
        from apps.catalog.models import Item
        Item.objects.filter(name__startswith='AUGMENTIN 1G').update(name='AUGMENTIN 1G 14 TAB')
        res = self.tiers('augmentin 1 جم')
        names = [n for n, _ in res]
        self.assertEqual(dict(res).get('AUGMENTIN 1G 14 TAB'), 'synonym')
        if 'AUGMENTIN 457MG/5ML SYRUP 70ML' in names:
            self.assertLess(names.index('AUGMENTIN 1G 14 TAB'),
                            names.index('AUGMENTIN 457MG/5ML SYRUP 70ML'))

    def test_vit(self):
        # «فيتامين» is not in the name in any spelling: only the table reaches VITAMIN
        self.assertEqual(dict(self.tiers('فيتامين c')).get('VITAMIN C 500MG 30TAB'), 'synonym')

    def test_whole_word_only(self):
        from apps.catalog.models import Item
        Item.objects.create(softech_id='941100', name='ZYRTEC 10G GEL', pack_price=1, is_active=True)
        Item.objects.create(softech_id='941101', name='ZYRTEC GRAPE DROPS 10ML', pack_price=1, is_active=True)
        res = dict(self.tiers('zyrtec جم'))
        self.assertEqual(res.get('ZYRTEC 10G GEL'), 'synonym')
        # its only G is inside GRAPE → never a synonym hit (the Arabic query may still reach it
        # by SOUND of «zyrtec», a separate, lower tier)
        self.assertNotEqual(res.get('ZYRTEC GRAPE DROPS 10ML'), 'synonym')

    def test_one_direction(self):
        from apps.catalog import search_synonyms as S
        self.assertIsNone(S.expand_terms(['SYRUP']))
        self.assertEqual(S.expand_terms(['AUGMENTIN', 'SYP']), [('AUGMENTIN',), ('SYP', 'SYRUP')])
        self.assertEqual(S.SYNONYMS['فوار'], ('SACH', 'EFF'))
        self.assertEqual(S.SYNONYMS['G'], ('G', 'GM'))

    def test_typed_form_still_literal(self):
        res = self.tiers('augmentin syrup')
        self.assertEqual(res[0][0], 'AUGMENTIN 457MG/5ML SYRUP 70ML')
        # the words are not adjacent in the name → any_order; what matters: typed form is literal
        self.assertIn(res[0][1], ('starts', 'contains', 'any_order'))


class TypoTests(TestCase):
    """Single-word typos on LONG, realistic names (the short names in ItemSearchTests hid the
    bug: with no extra words or numbers typed, the word / number terms scored 0 and the brand
    stayed under APPROX_MIN)."""

    def setUp(self):
        P.reset_index()
        self.it = _items(
            'PANADOL ADVANCE 500MG 24TAB LOCAL EGYPT (2STRIPSX12) SMALL OLD SIZE',
            'PANADOL EXTRA  48TAB (EGYPT) (4STRIPSX12)',
            'VOLTAREN - SR - 100MG 20TAB (2STRIPSX10) فولتارين 100 مجم',
            'AUGMENTIN 1G (1000MG) 14 TAB (2STRIPSX7) اوجمنتين 1جم 14قرص',
            'CATAFLAM  50MG 20TAB (2STRIPSX10)',
            'ANTIFLAM 50MG 20TAB')

    def names(self, ids):
        from apps.catalog.models import Item
        names = dict(Item.objects.values_list('id', 'name'))
        return [names[i] for i in ids]

    def test_single_word_typos(self):
        from apps.catalog.models import Item
        base = Item.objects.filter(is_active=True)
        for q, brand in (('panadool', 'PANADOL'), ('voltren', 'VOLTAREN'), ('agmentin', 'AUGMENTIN')):
            res = self.names(W._approx_ids(q, 20, base))
            self.assertTrue(res, q)
            self.assertTrue(res[0].startswith(brand), (q, res))
            # and through the search box
            first = W.item_search(q)
            self.assertTrue(first, q)
            self.assertEqual(first[0][1], 'approx', q)
            self.assertTrue(self.names([first[0][0]])[0].startswith(brand), (q, first))

    def test_spelled_beats_sounds_like(self):
        res = self.names([i for i, _ in W.item_search('cataflm 50')])
        self.assertTrue(res)
        self.assertTrue(res[0].startswith('CATAFLAM'), res)
        self.assertNotEqual(res[0], 'ANTIFLAM 50MG 20TAB')

    def test_gibberish_no_guess(self):
        self.assertEqual(W.item_search('xqzvw'), [])

    def test_existing_multiword_typos_unchanged(self):
        # the short-name catalog of ItemSearchTests, run unchanged after this fix
        from apps.catalog.models import Item
        Item.objects.all().delete()
        t = ItemSearchTests('test_typo_fallback_only_when_nothing_found')
        t.setUp()
        t.test_typo_fallback_only_when_nothing_found()


class SoundTierTests(TestCase):
    """The Arabic `sound` tier fits the 40 ms budget: the in-memory sound index re-ranked in
    place (apps/shortage/phonetic.quick_ids), not the full shared matcher — and no lookup at
    all when the earlier tiers already filled the result."""

    def setUp(self):
        P.reset_index()
        self.it = _items(
            'PANADOL ADVANCE 500MG 24TAB LOCAL EGYPT (2STRIPSX12) SMALL OLD SIZE',
            'NEXIUM 40MG 28TAB (LOCAL)  (4STRIPSX7)', 'ZYRTEC 10MG 20TAB',
            'CATAFLAM  50MG 20TAB (2STRIPSX10)', 'CATAFLAM 25MG 20TAB (2STRIPSX10)',
            'CATAFLAM  75 MG  5 SUPP', 'CERELAC RICE WITH MILK 125GM',
            'BRUFEN 400MG 30TAB (3STRIPSX10)', 'VOLTAREN 50MG 20TAB فولتارين 50مجم')

    def first(self, q, **kw):
        from apps.catalog.models import Item
        res = W.item_search(q, **kw)
        return (Item.objects.get(id=res[0][0]).name, res[0][1]) if res else None

    def test_arabic_brands_by_sound_without_the_heavy_matcher(self):
        cases = (('بنادول', 'PANADOL'), ('بانادول', 'PANADOL'), ('نيكسيوم', 'NEXIUM'),
                 ('زيرتك', 'ZYRTEC'), ('كتافلام', 'CATAFLAM'), ('سيريلاك', 'CERELAC'),
                 ('بروفين', 'BRUFEN'), ('كاتافلام 50', 'CATAFLAM  50MG'))
        with mock.patch('apps.shortage.matching.find_best_matches', return_value=[]) as heavy:
            for q, brand in cases:
                got = self.first(q)
                self.assertIsNotNone(got, q)
                self.assertTrue(got[0].startswith(brand), (q, got))
                self.assertEqual(got[1], 'sound', q)
            heavy.assert_not_called()

    def test_number_picks_the_strength(self):
        self.assertEqual(self.first('كاتافلام 25')[0], 'CATAFLAM 25MG 20TAB (2STRIPSX10)')

    def test_latin_or_short_query_has_no_sound(self):
        self.assertEqual(P.quick_ids('cataflam'), [])
        self.assertEqual(P.quick_ids('كت'), [])

    def test_no_sound_lookup_when_result_already_full(self):
        # «فولتارين» is in the name: the name tier alone fills limit=1 — the sound lookup is
        # skipped (what it adds would be cut off anyway)
        with mock.patch('apps.shortage.phonetic.quick_ids', return_value=[]) as q:
            self.assertEqual(self.first('فولتارين', limit=1)[0], 'VOLTAREN 50MG 20TAB فولتارين 50مجم')
            q.assert_not_called()
        with mock.patch('apps.shortage.phonetic.quick_ids', return_value=[]) as q:
            W.item_search('كتافلام')
            q.assert_called_once()
