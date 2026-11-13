"""core.multi_filter — the shared parser behind every multi-select filter dropdown."""
from django.http import QueryDict
from django.test import SimpleTestCase

from core.multi_filter import multi_ids, multi_values


class MultiFilterTests(SimpleTestCase):
    def test_comma_and_repeated_forms(self):
        q = QueryDict('status=draft,submitted&status=paid&status=draft')
        self.assertEqual(multi_values(q, 'status'), ['draft', 'submitted', 'paid'])   # order kept, no repeats

    def test_empty_means_no_filter(self):
        self.assertEqual(multi_values(QueryDict('status='), 'status'), [])
        self.assertEqual(multi_values(QueryDict(''), 'status'), [])
        self.assertEqual(multi_values(QueryDict('status=,, ,'), 'status'), [])

    def test_ids_drop_junk(self):
        self.assertEqual(multi_ids(QueryDict('b=3, 7,x,-1,7'), 'b'), [3, 7])

    def test_plain_dict_and_list(self):
        self.assertEqual(multi_ids({'b': [1, '2']}, 'b'), [1, 2])
        self.assertEqual(multi_values({'s': 'a'}, 's'), ['a'])

    def test_capped(self):
        q = QueryDict('b=' + ','.join(str(i) for i in range(900)))
        self.assertEqual(len(multi_ids(q, 'b')), 500)
