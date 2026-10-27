"""
apps/tests/test_transits_grid.py

Transfers grid behaviours the UI depends on:
  • every listed column can be ordered asc/desc via ?ordering=
  • doc number sorts NUMERICALLY (not '1000' < '999')
  • priority sorts by SEVERITY (green → critical), not alphabetically
  • branch columns sort by resolved name
  • the detail serializer enriches items with a partial-pack breakdown
  • doc_value is serialized at full precision (never rounded)
"""
from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.catalog.models import Item
from apps.transits.models import InTransitTransfer
from .factories import make_admin, make_branch, make_branch2, make_item

LIST_URL = '/api/transits/'


def _mk(doc, supply_code, recv_code, *, priority='green', item_count=1,
        doc_value='100.00', days=1, items=None, supply=None, recv=None):
    return InTransitTransfer.objects.create(
        erp_doc_number=doc,
        erp_supplying_branch_code=supply_code,
        erp_receiving_branch_code=recv_code,
        supplying_branch=supply, receiving_branch=recv,
        issue_date='2026-05-10',
        transit_status='in_transit',
        priority=priority,
        days_in_transit=days,
        item_count=item_count,
        doc_value=Decimal(doc_value),
        items_snapshot=items or [],
    )


class OrderingTests(TestCase):

    def setUp(self):
        self.hq   = make_branch('HQ', '100')
        self.giza = make_branch2('Giza', '140')
        _, _, self.client = make_admin('grid_admin')

        # numeric-vs-lexical trap: '999' must sort BEFORE '1000'
        _mk('999',  '100', '140', priority='green',    item_count=5,  doc_value='50.00',    days=2)
        _mk('1000', '100', '140', priority='critical', item_count=1,  doc_value='49949.99', days=9)
        _mk('1050', '100', '140', priority='yellow',   item_count=30, doc_value='7926.59',  days=4)

    def _docs(self, ordering):
        r = self.client.get(LIST_URL, {'ordering': ordering, 'page_size': 50})
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        rows = r.data.get('results', r.data)
        return [x['erp_doc_number'] for x in rows]

    def test_doc_number_numeric_both_directions(self):
        self.assertEqual(self._docs('doc_number_num'),  ['999', '1000', '1050'])
        self.assertEqual(self._docs('-doc_number_num'), ['1050', '1000', '999'])

    def test_priority_by_severity(self):
        # green(0) < yellow(1) < critical(4)
        self.assertEqual(self._docs('priority_rank'),  ['999', '1050', '1000'])
        self.assertEqual(self._docs('-priority_rank'), ['1000', '1050', '999'])

    def test_item_count_and_value(self):
        self.assertEqual(self._docs('item_count'),  ['1000', '999', '1050'])   # 1,5,30
        self.assertEqual(self._docs('-doc_value'),  ['1000', '1050', '999'])   # 49949.99,7926.59,50

    def test_branch_sort_keys_accepted(self):
        for key in ('supply_sort', '-supply_sort', 'recv_sort', '-recv_sort',
                    'transit_status', 'cancellation_available', 'issue_date'):
            r = self.client.get(LIST_URL, {'ordering': key, 'page_size': 5})
            self.assertEqual(r.status_code, status.HTTP_200_OK, key)


class ExactValueAndPartialQtyTests(TestCase):

    def setUp(self):
        self.hq  = make_branch('HQ', '100')
        self.br1 = make_branch2('Giza', '140')
        _, _, self.client = make_admin('grid_admin2')

        it = make_item('LANTUS SOLOSTAR 5PENS (XX) (FRIDGE)', 'IT001')
        it.pack_qty = 5
        it.save()

        # doc_value stored as 49949.99 — must serialize verbatim, not 49950
        self.t = _mk('900001', '100', '140', supply=self.hq, recv=self.br1,
                     doc_value='49949.99', item_count=1,
                     items=[{'itemcode': 'IT001',
                             'itemname': 'LANTUS SOLOSTAR 5PENS (XX) (FRIDGE)',
                             'qty': 1.6, 'unit_cost': 200,
                             'extended_cost': 1690.52,
                             'batch': None, 'expiry': None, 'near_expiry': False}])

    def test_doc_value_not_rounded(self):
        r = self.client.get(LIST_URL, {'page_size': 5})
        row = next(x for x in r.data.get('results', r.data)
                   if x['erp_doc_number'] == '900001')
        # DRF serializes DecimalField as a string preserving the 2 dp exactly
        self.assertEqual(str(row['doc_value']), '49949.99')

    def test_detail_items_have_partial_breakdown(self):
        r = self.client.get(f'{LIST_URL}{self.t.id}/')
        self.assertEqual(r.status_code, status.HTTP_200_OK)
        item = r.data['items_snapshot'][0]
        # exact qty preserved AND spelled out (1.6 packs × 5 pens = 8 = 1 pack + 3)
        self.assertEqual(item['qty'], 1.6)
        self.assertTrue(item['is_partial'])
        self.assertEqual(item['qty_text'], '1 علبة + 3 وحدة')
        # extended_cost passes through untouched
        self.assertEqual(item['extended_cost'], 1690.52)

    def test_detail_lists_batches_on_separate_lines(self):
        """Multi-batch item → detail view gets per-batch lines (SOFTECH-style)."""
        self.t.items_snapshot = [{
            'itemcode': 'IT001', 'itemname': 'LANTUS SOLOSTAR 5PENS (XX) (FRIDGE)',
            'qty': 3.0, 'unit_cost': 16649.99, 'extended_cost': 49949.99,
            'batch': None, 'expiry': '2028-02-02', 'near_expiry': False,
            'batches': [
                {'batch': None, 'expiry': '2028-02-02', 'qty': 1.0,
                 'unit_cost': 16649.99, 'extended_cost': 16649.99, 'near_expiry': False},
                {'batch': None, 'expiry': '2028-02-28', 'qty': 2.0,
                 'unit_cost': 16649.99, 'extended_cost': 33299.98, 'near_expiry': False},
            ],
        }]
        self.t.save()
        r = self.client.get(f'{LIST_URL}{self.t.id}/')
        item = r.data['items_snapshot'][0]
        self.assertEqual(item['batch_count'], 2)
        self.assertEqual(len(item['batches']), 2)
        # aggregate line still present and correct
        self.assertEqual(item['qty'], 3.0)
        # each batch carries its own qty/cost + partial breakdown
        b0, b1 = item['batches']
        self.assertEqual(b0['qty'], 1.0)
        self.assertEqual(b1['qty'], 2.0)
        self.assertEqual(b0['extended_cost'], 16649.99)
        self.assertIn('is_partial', b0)   # enriched per batch

    def test_whole_qty_has_no_breakdown(self):
        self.t.items_snapshot = [{
            'itemcode': 'IT001', 'itemname': 'X', 'qty': 3,
            'unit_cost': 200, 'extended_cost': 600,
            'batch': None, 'expiry': None, 'near_expiry': False}]
        self.t.save()
        r = self.client.get(f'{LIST_URL}{self.t.id}/')
        item = r.data['items_snapshot'][0]
        self.assertFalse(item['is_partial'])
        self.assertEqual(item['qty_text'], '')
