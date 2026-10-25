"""Live SOFTECH item search (doc 30, F10): the same pattern within a few minutes is
answered from the cache — no second login + items scan; branch column per request."""
from unittest import mock

from django.core.cache import cache
from django.test import TestCase

from apps.catalog import views as V

ROW = ['900001', 'NEW ITEM', 'sci', '622000', 'C1', 50.0, 5.0, '0', 0, 0, 'tab']


class _Cur:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        pass

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _Cur(self.rows)

    def close(self):
        pass


class LiveSearchCacheTests(TestCase):

    def setUp(self):
        cache.clear()

    def test_same_pattern_one_softech_call(self):
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn([ROW])) as conn:
            a = V._softech_live_search('%new%', None)
            b = V._softech_live_search('%new%', '3')
        self.assertEqual(conn.call_count, 1)
        self.assertEqual([r['softech_id'] for r in a], ['900001'])
        self.assertEqual((a[0]['qty_at_branch'], b[0]['qty_at_branch']), (None, 0.0))

    def test_other_pattern_asks_softech(self):
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn([ROW])) as conn:
            V._softech_live_search('%new%', None)
            V._softech_live_search('%other%', None)
        self.assertEqual(conn.call_count, 2)

    def test_misses_cached_for_a_shorter_time(self):
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn([])), \
             mock.patch.object(cache, 'set', wraps=cache.set) as setter:
            self.assertEqual(V._softech_live_search('%zzz%', None), [])
        self.assertEqual(setter.call_args[0][2], V._SOFTECH_SEARCH_MISS_TTL)

    def test_cached_rows_not_mutated_by_callers(self):
        with mock.patch('config.sybase.get_sybase_connection', return_value=_Conn([ROW])):
            V._softech_live_search('%new%', None)[0]['name'] = 'changed'
            self.assertEqual(V._softech_live_search('%new%', None)[0]['name'], 'NEW ITEM')

    def test_breaker_still_applies_when_not_cached(self):
        with mock.patch('config.sybase.get_sybase_connection', side_effect=OSError('down')) as conn:
            self.assertEqual(V._softech_live_search('%a%', None), [])
            self.assertEqual(V._softech_live_search('%b%', None), [])
        self.assertEqual(conn.call_count, 1)
