"""Unified item search S1 — the golden corpus (apps/catalog/search_corpus.py) on a mini-catalog.

Every 2026-11-16 probe query must put the expected item in its top 1 / top 3 (and with the
expected tier, where the corpus names one) — through the engine and through the POS endpoint.
The real-catalog run with timings is `manage.py search_probe`.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.catalog import wildcard as W
from apps.catalog.search_corpus import CORPUS, SEED_BARCODES, SEED_INGREDIENTS, SEED_NAMES, check
from apps.shortage import phonetic as P


class CorpusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item, ItemBarcode
        from apps.chronic.models import ActiveIngredient, ItemIngredientMap
        items = {sid: Item.objects.create(softech_id=sid, name=name, name_scientific=sci,
                                          pack_price=10, is_active=True)
                 for sid, name, sci in SEED_NAMES}
        for sid, barcode in SEED_BARCODES:
            ItemBarcode.objects.create(item=items[sid], barcode=barcode)
        for sid, ing in SEED_INGREDIENTS:
            ai, _ = ActiveIngredient.objects.get_or_create(name=ing)
            ItemIngredientMap.objects.create(item=items[sid], active_ingredient=ai)
        cls.names = {i.id: i.name for i in items.values()}

    def setUp(self):
        P.reset_index()                                # the sound index of THIS mini-catalog
        cache.delete('catalog:softech_search_down')

    def test_corpus_shape(self):
        self.assertEqual(len(CORPUS), 56)
        self.assertEqual(len({e['q'] for e in CORPUS}), 56)
        self.assertEqual(len({sid for sid, _, _ in SEED_NAMES}), len(SEED_NAMES))
        for e in CORPUS:
            self.assertIn(e.get('top', 1), (1, 3), e['q'])

    def test_corpus(self):
        for e in CORPUS:
            with self.subTest(q=e['q']):
                rows = [(self.names.get(i), t) for i, t in W.item_search(e['q'])]
                self.assertTrue(check(e, rows), (e['expect'], e.get('tier'), rows[:e.get('top', 1) + 2]))

    def test_corpus_via_endpoint(self):
        user = get_user_model().objects.create_user(username='corpus', password='x')
        c = APIClient()
        c.force_authenticate(user)
        for e in CORPUS:
            with self.subTest(q=e['q']):
                r = c.get('/api/items/softech-search/', {'q': e['q'], 'no_live': '1'})
                self.assertEqual(r.status_code, 200)
                rows = [(x['name'], x.get('tier')) for x in r.json()['results']]
                self.assertTrue(check(e, rows), (e['expect'], e.get('tier'), rows[:e.get('top', 1) + 2]))

    def test_search_probe_command(self):
        # the ms budget is judged on real data only (spec §9) — here: every path runs, A and D
        # pass, nothing is kept, a JSON report is written
        import io
        import json
        import os
        import tempfile
        from unittest import mock
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from apps.catalog.models import Item
        with self.assertRaises(CommandError):                 # needs a superuser to call as
            call_command('search_probe', repeat=1, stdout=io.StringIO())
        get_user_model().objects.create_superuser(username='probe', password='x')
        before = Item.objects.count()
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        self.addCleanup(os.remove, path)
        probe = 'apps.catalog.management.commands.search_probe'
        with mock.patch(f'{probe}.BUDGET_MS', 10_000), mock.patch(f'{probe}.B_BUDGET_MS', 10_000):
            call_command('search_probe', repeat=1, with_temp_indexes=True, json_path=path,
                         stdout=io.StringIO())
        with open(path, encoding='utf-8') as f:
            out = json.load(f)
        self.assertEqual(out['missing_indexes'], [])
        self.assertEqual(len(out['records']), 56)
        for r in out['records']:
            self.assertTrue(all(r['paths'][p]['ok'] for p in 'ABD'), (r['q'], r['paths']['B']))
            self.assertEqual(set(r['paths']), {'A', 'B', 'C', 'D'})
        self.assertEqual(Item.objects.count(), before)

    def test_check_helper(self):
        e = {'q': 'x', 'expect': r'^AUG', 'top': 3, 'tier': 'word'}
        self.assertTrue(check(e, [('AUGMACILLIN', 'word'), ('X', 'word')]))
        self.assertFalse(check(e, [('A', 'word'), ('B', 'word'), ('C', 'word'), ('AUGMENTIN', 'word')]))
        self.assertFalse(check(e, [('AUGMENTIN', 'sound')]))
        # a name match with the wrong tier doesn't end the scan: the next top-N row may fit both
        self.assertTrue(check(e, [('AUGMENTIN', 'sound'), ('AUGMACILLIN', 'word')]))
        self.assertFalse(check({'q': 'x', 'expect': '.'}, []))


class ProbeGateTests(SimpleTestCase):
    """search_probe: path B (the item list, rank=engine) is gated; --with-temp-indexes touches
    only the indexes that are missing or built on another expression."""

    def test_probe_path_b_gated(self):
        from apps.catalog.management.commands import search_probe as SP
        self.assertIn('B', SP.GATED)
        self.assertEqual(SP.budget_ms('B'), 150)
        self.assertEqual(SP.budget_ms('D'), SP.BUDGET_MS)
        self.assertIsNone(SP.budget_ms('A'))

    def test_temp_indexes_drop_only_differing(self):
        import importlib
        from apps.catalog.management.commands import search_probe as SP
        m = importlib.import_module('apps.catalog.migrations.0047_fold_marks_narrow')
        mig = next(s for s in m.CREATE if 'catalog_item_name_fold_prefix' in s)

        def live(expr_from):
            # what pg_get_indexdef prints for that index (casts, parens, schema, USING btree)
            return ('CREATE INDEX catalog_item_name_fold_prefix ON public.catalog_item USING btree '
                    "(regexp_replace(translate(upper((COALESCE(name, ''::character varying))::text), '"
                    + expr_from + "'::text, 'ااااهيوي'::text), '\\s+'::text, ' '::text, 'g'::text) "
                    'text_pattern_ops)')
        v2_from = W.FOLD_FROM + W._TASHKEEL_CHARS
        v1_from = W.FOLD_FROM + ''.join(map(chr, [0x0640, *range(0x064B, 0x0660), 0x0670,
                                                  *range(0x06D6, 0x06EE)]))
        self.assertTrue(SP.indexdef_matches(live(v2_from), mig))
        self.assertFalse(SP.indexdef_matches(live(v1_from), mig))
        self.assertFalse(SP.indexdef_matches(live(v2_from).replace("' '::text", "''::text"), mig))
        sql = SP.index_sql()
        names = SP.index_names()
        defs = {n: live(v2_from) if n == 'catalog_item_name_fold_prefix' else None for n in names}
        drop, create = SP.plan_temp_indexes(defs)
        self.assertEqual(drop, [])
        self.assertEqual(create, [n for n in names if n != 'catalog_item_name_fold_prefix'])
        defs['catalog_item_name_fold_prefix'] = live(v1_from)
        drop, create = SP.plan_temp_indexes(defs)
        self.assertEqual(drop, ['catalog_item_name_fold_prefix'])
        self.assertEqual(create, names)
        self.assertEqual(len(sql), len(names))


class ProbeLiveIndexTests(TestCase):
    """On the test DB (catalog migrations applied) every search index matches its migration:
    --with-temp-indexes would drop and lock nothing."""

    def test_no_index_differs_after_migrate(self):
        from django.db import connection
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL only')
        from apps.catalog.management.commands import search_probe as SP
        self.assertEqual(SP.plan_temp_indexes(SP.live_indexdefs()), ([], []))


class Migration0047LockWindowTests(TestCase):
    """catalog 0047 builds the new fold indexes under temporary names FIRST (SHARE lock: reads go
    on), and only then drops the old ones (ACCESS EXCLUSIVE) and renames — so the exclusive lock
    never spans the four builds. Both directions end on the final names."""

    def mig(self):
        import importlib
        return importlib.import_module('apps.catalog.migrations.0047_fold_marks_narrow')

    def test_builds_before_the_exclusive_part(self):
        m = self.mig()
        for sql in (m.SQL, m.REVERSE):
            kinds = ['create' if s.startswith('CREATE') else 'rename' if s.startswith('ALTER')
                     else 'drop_tmp' if s.endswith(m.TMP) else 'drop' for s in sql]
            self.assertEqual(kinds, ['drop_tmp'] * 4 + ['create'] * 4 + ['drop'] * 4 + ['rename'] * 4)
            # every build goes to a temporary name; the old (final) names are dropped only after
            self.assertTrue(all(m.TMP + ' ON ' in s for s in sql if s.startswith('CREATE')))
            self.assertEqual(sql[8:12], m.DROP)
            self.assertEqual(sql[12:], m.RENAME)
        # search_probe reads the FINAL-name statements
        from apps.catalog.management.commands import search_probe as SP
        self.assertEqual(SP.index_names()[:4], list(m.NAMES))
        self.assertTrue(all(m.TMP not in s for s in m.CREATE))

    def test_reverse_then_forward_on_the_test_db(self):
        from django.db import connection
        if connection.vendor != 'postgresql':
            self.skipTest('PostgreSQL only')
        from apps.catalog.management.commands import search_probe as SP
        m = self.mig()
        with connection.cursor() as c:
            for s in m.REVERSE:
                c.execute(s)
            live = SP.live_indexdefs()
            for name, v1 in zip(m.NAMES, m.CREATE_V1):
                self.assertTrue(SP.indexdef_matches(live[name], v1), name)
            for s in m.SQL:
                c.execute(s)
            c.execute('SELECT count(*) FROM pg_class WHERE relname = ANY(%s)', [[n + m.TMP for n in m.NAMES]])
            self.assertEqual(c.fetchone()[0], 0)
        self.assertEqual(SP.plan_temp_indexes(SP.live_indexdefs()), ([], []))
