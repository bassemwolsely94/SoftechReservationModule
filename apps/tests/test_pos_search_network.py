"""POS Speed Wave Task 1 — item-search rows carry thumbnail, strength, network stock,
next action and stock age (apps/catalog/pos_search.py)."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.catalog.models import ItemStock
from apps.catalog.pos_search import (
    extract_strength, network_stock, next_action, primary_thumbs)
from apps.product_experience.models import ProductMedia
from .factories import make_branch, make_branch2, make_item, make_user

URL = '/api/items/softech-search/'


def _stock(item, branch, qty, store='100'):
    return ItemStock.objects.create(item=item, branch=branch, softech_store_code=store,
                                    quantity_on_hand=qty)


def _media(item, name, **kw):
    return ProductMedia.objects.create(
        item=item, file=SimpleUploadedFile(name, b'x', content_type='image/jpeg'), **kw)


import shutil, tempfile
from django.test import override_settings

_MEDIA = tempfile.mkdtemp(prefix='posnet_media_')


@override_settings(MEDIA_ROOT=_MEDIA)
class PosSearchHelpersTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    def test_extract_strength(self):
        self.assertEqual(extract_strength('CONCOR 5MG 30 TAB'), '5 MG')
        self.assertEqual(extract_strength('CONCOR AM 5/10MG'), '5/10 MG')
        self.assertEqual(extract_strength('PANADOL EXTRA'), '')
        self.assertEqual(extract_strength('FUCIDIN 2% CREAM'), '2 %')

    def test_network_stock_excludes_quarantine_and_sorts(self):
        a, b = make_branch(), make_branch2()
        it = make_item('CONCOR 5MG', 'N0001')
        _stock(it, a, 4, '100')
        _stock(it, a, 9, '102')
        _stock(it, b, 7, '100')
        self.assertEqual(network_stock([it.id])[it.id],
                         [{'branch_id': b.id, 'qty': 7.0}, {'branch_id': a.id, 'qty': 4.0}])

    def test_network_stock_skips_non_operational_branch(self):
        a, b = make_branch(), make_branch2()
        b.is_operational = False
        b.save(update_fields=['is_operational'])
        it = make_item('CONCOR 5MG', 'N0002')
        _stock(it, a, 4)
        _stock(it, b, 7)
        self.assertEqual(network_stock([it.id])[it.id], [{'branch_id': a.id, 'qty': 4.0}])

    def test_next_action(self):
        bs = [{'branch_id': 1, 'qty': 0.0}, {'branch_id': 2, 'qty': 5.0},
              {'branch_id': 3, 'qty': 2.0}]
        self.assertEqual(next_action(3, bs, 1), {'kind': 'add'})
        self.assertEqual(next_action(0, bs, 1), {'kind': 'transfer', 'from_branch_id': 2})
        self.assertEqual(next_action(0, [], 1), {'kind': 'demand'})
        self.assertEqual(next_action(0, [{'branch_id': 1, 'qty': 0.0}], 1), {'kind': 'demand'})
        tie = [{'branch_id': 9, 'qty': 5.0}, {'branch_id': 4, 'qty': 5.0}]
        self.assertEqual(next_action(0, tie, 1), {'kind': 'transfer', 'from_branch_id': 4})

    def test_primary_thumb_prefers_primary_approved(self):
        it = make_item('CONCOR 5MG', 'N0003')
        _media(it, 'unapproved_primary.jpg', is_primary=True, approved=False)
        other = _media(it, 'second.jpg', is_primary=False, approved=True, order=2)
        self.assertEqual(primary_thumbs([it.id])[it.id], other.file.url)
        prim = _media(it, 'primary.jpg', is_primary=True, approved=True, order=5)
        self.assertEqual(primary_thumbs([it.id])[it.id], prim.file.url)


class PosSearchApiTests(TestCase):
    def setUp(self):
        self.a, self.b = make_branch(), make_branch2()
        _, _, self.client_ = make_user('pos_net_user', role='pharmacist')
        self.it = make_item('CONCOR 5MG 30 TAB', 'N0010')
        _stock(self.it, self.a, 0)
        _stock(self.it, self.b, 6)

    def test_search_network_flag_adds_fields(self):
        r = self.client_.get(URL, {'q': 'CONCOR', 'branch_id': self.a.id, 'network': '1'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('stock_as_of', r.data)
        row = next(x for x in r.data['results'] if x['item_id'] == self.it.id)
        for k in ('thumb', 'strength', 'branch_stock', 'next_action'):
            self.assertIn(k, row)
        self.assertEqual(row['strength'], '5 MG')
        self.assertEqual(row['next_action'], {'kind': 'transfer', 'from_branch_id': self.b.id})
        plain = self.client_.get(URL, {'q': 'CONCOR', 'branch_id': self.a.id})
        self.assertNotIn('stock_as_of', plain.data)
        prow = next(x for x in plain.data['results'] if x['item_id'] == self.it.id)
        for k in ('thumb', 'strength', 'branch_stock', 'next_action'):
            self.assertNotIn(k, prow)

    def test_search_network_live_row_without_item_id(self):
        from unittest.mock import patch
        live = [{'softech_id': 'LIVE1', 'name': 'NEWDRUG 10MG', 'name_scientific': '',
                 'barcode': '', 'pack_price': 1.0, 'unit_price': 1.0,
                 'requires_fridge': False, 'medicine_type': '', 'source': 'softech',
                 'item_id': None, 'tier': 'ordered', 'qty_at_branch': 0.0}]
        with patch('apps.catalog.views._softech_live_search', return_value=live):
            r = self.client_.get(URL, {'q': 'NEWDRUG', 'branch_id': self.a.id, 'network': '1'})
        row = next(x for x in r.data['results'] if x['softech_id'] == 'LIVE1')
        self.assertEqual(row['branch_stock'], [])
        self.assertIsNone(row['thumb'])
        self.assertEqual(row['next_action'], {'kind': 'demand'})

    # ── Final-review fixes ────────────────────────────────────────────────────
    def test_rows_carry_unit_fields(self):
        """POS adds lines straight from search rows → the Q (strips) modal needs the real
        pack size; a missing pack_qty defaulted to 1 and sold packs instead of strips."""
        self.it.pack_qty = 3
        self.it.unit_name = 'شريط'
        self.it.is_stockable = True
        self.it.batch_required = True
        self.it.save(update_fields=['pack_qty', 'unit_name', 'is_stockable', 'batch_required'])
        for params in ({'network': '1'}, {}):
            r = self.client_.get(URL, {'q': 'CONCOR', 'branch_id': self.a.id, **params})
            row = next(x for x in r.data['results'] if x['item_id'] == self.it.id)
            self.assertEqual(row['pack_qty'], 3)
            self.assertEqual(row['unit_name'], 'شريط')
            self.assertIs(row['is_stockable'], True)
            self.assertIs(row['batch_required'], True)

    def test_live_row_unit_fields_present(self):
        """Live SOFTECH rows: best effort — PG facts when the item is synced, else None."""
        from unittest.mock import MagicMock, patch
        from django.core.cache import cache
        from apps.catalog.views import _softech_live_search
        cache.delete('catalog:softech_search_down')
        self.addCleanup(cache.clear)                     # don't leave cached '%x%' rows for other tests
        self.it.pack_qty = 2
        self.it.save(update_fields=['pack_qty'])
        conn = MagicMock()
        conn.cursor.return_value.fetchall.return_value = [
            ('N0010', 'CONCOR 5MG 30 TAB', '', '', '', 10, 1, '0', '0', None, ''),
            ('LIVE3', 'UNSYNCED', '', '', '', 10, 1, '0', '0', None, '')]
        with patch('config.sybase.get_sybase_connection', return_value=conn):
            rows = {r['softech_id']: r for r in _softech_live_search('%x%', self.a.id)}
        self.assertEqual(rows['N0010']['pack_qty'], 2)
        self.assertIs(rows['N0010']['batch_required'], False)
        for k in ('pack_qty', 'unit_name', 'is_stockable', 'batch_required'):
            self.assertIsNone(rows['LIVE3'][k])

    def test_no_live_skips_softech_live_search(self):
        """Ruling: the POS search never reads SOFTECH live during a sale (no_live=1)."""
        from unittest.mock import patch
        with patch('apps.catalog.views._softech_live_search', return_value=[]) as live:
            r = self.client_.get(URL, {'q': 'ZZNOTHING', 'branch_id': self.a.id,
                                       'network': '1', 'no_live': '1'})
            self.assertEqual(r.status_code, 200)
            live.assert_not_called()
            self.client_.get(URL, {'q': 'ZZNOTHING', 'branch_id': self.a.id})
            live.assert_called_once()
