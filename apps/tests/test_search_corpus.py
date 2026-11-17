"""Unified item search S1 — the golden corpus (apps/catalog/search_corpus.py) on a mini-catalog.

Every 2026-11-16 probe query must put the expected item in its top 1 / top 3 (and with the
expected tier, where the corpus names one) — through the engine and through the POS endpoint.
The real-catalog run with timings is `manage.py search_probe`.
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
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
        with mock.patch('apps.catalog.management.commands.search_probe.BUDGET_MS', 10_000):
            call_command('search_probe', repeat=1, with_temp_indexes=True, json_path=path,
                         stdout=io.StringIO())
        with open(path, encoding='utf-8') as f:
            out = json.load(f)
        self.assertEqual(out['missing_indexes'], [])
        self.assertEqual(len(out['records']), 56)
        for r in out['records']:
            self.assertTrue(r['paths']['A']['ok'] and r['paths']['D']['ok'], r['q'])
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
