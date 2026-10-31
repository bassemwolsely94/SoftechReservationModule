"""
apps/tests/test_shortage_sourcing_mirror.py

P-33 (d): the shortage supplier exports read our mirrors (catalog.ItemSupplierLink + procurement.
PurchaseLine) instead of SOFTECH; the live read is only a fallback when a mirror is stale. Same output
shape, plus meta['source'] so the file can say where the numbers came from.
"""
import datetime as dt
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.shortage import supplier_sourcing as S


class MirrorSourcingTests(TestCase):

    def setUp(self):
        from apps.catalog.models import ItemSupplierLink
        from apps.invoices.models import VendorProfile
        from apps.procurement.models import PurchaseLine
        VendorProfile.objects.create(name='Pharma Overseas', softech_personcode='565', is_main=True)
        VendorProfile.objects.create(name='Ibn Sina', softech_personcode='260', is_main=True)
        ItemSupplierLink.objects.create(item_code='A1', supp_code='565', supp_item_code='PO-77')
        ItemSupplierLink.objects.create(item_code='A1', supp_code='260', supp_item_code='')
        ItemSupplierLink.objects.create(item_code='A1', supp_code='999', supp_item_code='X')     # not a main vendor
        for doc, sup, day, price in (('1', '565', dt.date(2026, 9, 1), '40'), ('2', '565', dt.date(2026, 10, 1), '42'),
                                     ('3', '260', dt.date(2026, 8, 1), '39')):
            PurchaseLine.objects.create(branch_code='100', supplier_code=sup, doc_number=doc, doc_date=day,
                                        item_code='A1', doccode='10', unit_price=Decimal(price))
        PurchaseLine.objects.create(branch_code='130', supplier_code='565', doc_number='9', doc_date=dt.date(2026, 10, 20),
                                    item_code='A1', doccode='10', unit_price=Decimal('1'))          # not branch 100
        PurchaseLine.objects.create(branch_code='100', supplier_code='565', doc_number='8', doc_date=dt.date(2026, 10, 25),
                                    item_code='A1', doccode='120', unit_price=Decimal('1'))         # a return
        self.fresh = mock.patch.object(S, '_mirrors_fresh', return_value=True)

    def test_mirror_gives_the_same_shape_without_softech(self):
        meta = {}
        with self.fresh, mock.patch.object(S, '_open', side_effect=AssertionError('SOFTECH opened')):
            out = S.build_sourcing(['A1'], meta=meta)
        self.assertEqual(meta['source'], 'mirror')
        a = out['A1']
        self.assertEqual(a['suppliers'], {'565': {'code': 'PO-77', 'name': 'Pharma Overseas'},
                                          '260': {'code': '', 'name': 'Ibn Sina'}})
        self.assertEqual(a['history']['565'], {'name': 'Pharma Overseas', 'cost': 42.0, 'date': dt.date(2026, 10, 1)})
        self.assertEqual(a['history']['260']['cost'], 39.0)
        self.assertEqual(a['last_bought']['suppcode'], '565')
        self.assertEqual(a['last_bought']['date'], dt.date(2026, 10, 1))

    def test_restrict_to_one_supplier(self):
        with self.fresh, mock.patch.object(S, '_open', side_effect=AssertionError('SOFTECH opened')):
            out = S.build_sourcing(['A1'], restrict_supplier='260')
        self.assertEqual(set(out['A1']['suppliers']), {'260'})
        self.assertEqual(out['A1']['last_bought']['suppcode'], '260')

    def test_stale_mirror_falls_back_to_softech(self):
        meta = {}
        with mock.patch.object(S, '_mirrors_fresh', return_value=False), \
             mock.patch.object(S, '_from_softech', return_value={'A1': {'suppliers': {}, 'history': {},
                                                                       'last_bought': None}}) as live:
            S.build_sourcing(['A1'], meta=meta)
        self.assertTrue(live.called)
        self.assertEqual(meta['source'], 'live')

    def test_freshness_rule(self):
        from apps.catalog.models import ItemSupplierLink
        with mock.patch('apps.sync.freshness.get_freshness',
                        return_value={'domains': {'purchases': {'stale': False}}}):
            self.assertTrue(S._mirrors_fresh())
            ItemSupplierLink.objects.update(synced_at=timezone.now() - dt.timedelta(hours=49))
            self.assertFalse(S._mirrors_fresh())
        ItemSupplierLink.objects.update(synced_at=timezone.now())
        with mock.patch('apps.sync.freshness.get_freshness',
                        return_value={'domains': {'purchases': {'stale': True}}}):
            self.assertFalse(S._mirrors_fresh())
