from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Item, ItemSupplierLink
from apps.invoices.models import VendorItemMapping, VendorProfile
from apps.rpa.models import (BuyList, BuyListLine, PortalAccount, PortalBasket, PortalJob,
                             PortalLine, PortalRun, SupplierPortal)
from apps.rpa.portal import skus
from .factories import make_user


class SkuTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        _, cls.staff, _ = make_user('sk_staff', role='purchasing')
        cls.portal, _ = SupplierPortal.objects.get_or_create(
            key='pharma_overseas', defaults={'supplier_code': '565'})
        cls.account = PortalAccount.objects.create(portal=cls.portal, label='main')
        cls.vendor = VendorProfile.objects.create(name='PO', softech_personcode='565')
        cls.a = Item.objects.create(softech_id='SK1', name='item a', is_active=True)
        cls.b = Item.objects.create(softech_id='SK2', name='item b', is_active=True)
        cls.bl = BuyList.objects.create(source_kind='upload', created_by=cls.staff)
        cls.job = PortalJob.objects.create(portal=cls.portal, account=cls.account, buylist=cls.bl,
                                           created_by=cls.staff)

    def _basket_line(self, item, key=''):
        basket = PortalBasket.objects.create(job=self.job, seq=self.job.baskets.count() + 1,
                                             status='ready' if key else 'pending')
        bline = BuyListLine.objects.create(buylist=self.bl, seq=basket.seq, item=item, needed_qty=2,
                                           remaining_qty=2, chosen_supplier='565',
                                           source_key=f'sk:{item.pk}')
        PortalLine.objects.create(basket=basket, buyline=bline, item=item, wanted_qty=2,
                                  supplier_key=key)
        return basket, bline

    def _run(self):
        return PortalRun.objects.create(discovery_job=self.job, kind='discovery',
                                        started_at=timezone.now())

    def _discover(self, bline, sku='000000000000052872'):
        return skus.record_discovery(self.job, [{'buyline_id': bline.pk, 'candidates': [
            {'name': 'ITEM A 10', 'sku': sku, 'price': '12.5', 'stock_mark': False},
            {'name': 'ITEM A 20', 'sku': '999', 'price': '20', 'stock_mark': True}]}], run=self._run())

    def test_canonical_sku(self):
        self.assertEqual(skus.canonical_sku('000000000000052872'), '52872')
        self.assertEqual(skus.canonical_sku(' 37216 '), '37216')
        self.assertEqual(skus.canonical_sku('ABC'), '')
        self.assertEqual(skus.padded_sku('52872'), '000000000000052872')

    def test_known_key_prefers_mapping_over_mirror(self):
        ItemSupplierLink.objects.create(item_code='SK1', supp_code='565', supp_item_code='0011')
        self.assertEqual(skus.known_key(self.portal, self.a), '11')
        VendorItemMapping.objects.create(vendor=self.vendor, raw_name_normalized='x', item=self.a,
                                         vendor_item_code='0099')
        self.assertEqual(skus.known_key(self.portal, self.a), '99')
        self.assertEqual(skus.known_key(self.portal, self.b), '')

    def test_discovery_creates_portal_batch(self):
        _, bline = self._basket_line(self.a)
        batch = self._discover(bline)
        self.assertEqual(batch.source, 'portal')
        self.assertEqual(batch.supplier_id, self.vendor.pk)
        lines = list(batch.lines.order_by('id'))
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].supplier_item_code, '52872')
        self.assertEqual(lines[0].raw_text, 'ITEM A 10')
        self.assertEqual(lines[1].signals, ['out_of_stock'])
        self.assertEqual(lines[0].match_reason['buyline_id'], bline.pk)
        self.assertFalse(lines[0].is_confirmed)

    def test_confirm_learns_mapping_and_readies_basket(self):
        basket, bline = self._basket_line(self.a)
        cand = self._discover(bline).lines.order_by('id').first()
        skus.confirm_discovery(cand, staff=self.staff)
        self.assertTrue(VendorItemMapping.objects.filter(
            vendor=self.vendor, vendor_item_code='52872', item=self.a).exists())
        basket.refresh_from_db()
        self.assertEqual(basket.status, 'ready')
        pl = basket.lines.get()
        self.assertEqual((pl.supplier_key, pl.supplier_key_padded), ('52872', '000000000000052872'))

    def test_confirm_conflict_kept_for_person(self):
        VendorItemMapping.objects.create(vendor=self.vendor, raw_name_normalized='other', item=self.b,
                                         vendor_item_code='52872')
        basket, bline = self._basket_line(self.a)
        cand = self._discover(bline).lines.order_by('id').first()
        skus.confirm_discovery(cand, staff=self.staff)
        cand.refresh_from_db()
        self.assertIn('vendor_code_conflict', cand.match_reason)
        basket.refresh_from_db()
        self.assertEqual(basket.status, 'pending')
        self.assertEqual(basket.lines.get().supplier_key, '')

    def test_basket_stays_pending_until_all_keys_known(self):
        basket, bline = self._basket_line(self.a)
        other = BuyListLine.objects.create(buylist=self.bl, seq=9, item=self.b, needed_qty=1,
                                           remaining_qty=1, chosen_supplier='565', source_key='sk:b')
        PortalLine.objects.create(basket=basket, buyline=other, item=self.b, wanted_qty=1)
        skus.confirm_discovery(self._discover(bline).lines.order_by('id').first(), staff=self.staff)
        basket.refresh_from_db()
        self.assertEqual(basket.status, 'pending')

    def test_none_of_these_returns_line_to_buyer(self):
        basket, bline = self._basket_line(self.a)
        skus.reject_discovery(bline, staff=self.staff)
        bline.refresh_from_db()
        self.assertEqual(bline.remaining_qty, 2)
        self.assertEqual(bline.chosen_supplier, '')
        self.assertEqual(bline.tried[-1]['accepted'], 0)
        self.assertEqual(basket.lines.get().status, 'not_found')
