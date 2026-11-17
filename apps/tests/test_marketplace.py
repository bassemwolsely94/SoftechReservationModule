"""Marketplace channels (doc 38) — Task 1: access, seed grants, model constraints."""
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import ItemStock
from apps.marketplace.access import Access
from apps.marketplace.availability import platform_price, sellable_qty, snapshot
from apps.marketplace.eligibility import listing_problem
from apps.marketplace.models import (ChannelListing, ChannelStore, ExternalOrder, ExternalOrderLine,
                                     MarketplaceChannel)
from apps.pos_orders.models import SoftechSalesOrder
from apps.tests.factories import make_admin, make_branch, make_branch2, make_item, make_pharmacist
from apps.users.management.commands.seed_permissions import PERMISSIONS


class MarketplaceAccessTests(TestCase):
    def test_flag_off_hides_everything(self):
        user, _, _ = make_admin('mp_admin_off')
        with override_settings(MARKETPLACE_ENABLED=False):
            a = Access(user)
            self.assertIs(a.can_view, False)
            self.assertIs(a.can_create, False)
            self.assertIs(a.can_approve, False)
            self.assertIs(a.can_edit, False)

    @override_settings(MARKETPLACE_ENABLED=True)
    def test_flag_on_admin_sees_all(self):
        user, _, _ = make_admin('mp_admin_on')
        a = Access(user)
        self.assertTrue(a.can_view and a.can_create and a.can_approve and a.can_edit)
        self.assertEqual(set(a.as_dict()), {'can_view', 'can_create', 'can_approve', 'can_edit'})

    def test_seed_grants_match_brief(self):
        self.assertEqual(PERMISSIONS['supervisor']['marketplace'], {'view', 'create', 'approve', 'edit', 'export'})
        self.assertEqual(PERMISSIONS['pharmacist']['marketplace'], {'view', 'create'})
        self.assertEqual(PERMISSIONS['call_center']['marketplace'], {'view', 'create'})
        self.assertEqual(PERMISSIONS['quality_manager']['marketplace'], {'view', 'export'})
        self.assertEqual(PERMISSIONS['purchasing']['marketplace'], {'view'})
        self.assertNotIn('marketplace', PERMISSIONS['viewer'])

    @override_settings(MARKETPLACE_ENABLED=True)
    def test_pharmacist_has_view_and_create_not_approve(self):
        from django.core.management import call_command
        call_command('seed_permissions', verbosity=0)
        user, _, _ = make_pharmacist('mp_pharma')
        a = Access(user)
        self.assertTrue(a.can_view)
        self.assertTrue(a.can_create)
        self.assertFalse(a.can_approve)
        self.assertFalse(a.can_edit)


class MarketplaceModelTests(TestCase):
    def test_external_order_unique_per_channel(self):
        branch = make_branch()
        ch = MarketplaceChannel.objects.create(code='manual_test', name='تجربة', adapter='manual')
        store = ChannelStore.objects.create(channel=ch, branch=branch)
        ExternalOrder.objects.create(channel=ch, store=store, branch=branch, external_id='A1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExternalOrder.objects.create(channel=ch, store=store, branch=branch, external_id='A1')
        # same external id on another channel is fine
        ch2 = MarketplaceChannel.objects.create(code='fake_two', name='ثانية', adapter='fake')
        store2 = ChannelStore.objects.create(channel=ch2, branch=branch)
        ExternalOrder.objects.create(channel=ch2, store=store2, branch=branch, external_id='A1')


class MarketplaceAvailabilityTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.channel = MarketplaceChannel.objects.create(code='av_test', name='تجربة', stock_buffer=Decimal('1'))
        self.store = ChannelStore.objects.create(channel=self.channel, branch=self.branch)
        self.item = make_item('صنف', 'AV001')

    def _listing(self, approved=True, **kw):
        return ChannelListing.objects.create(channel=self.channel, item=self.item, approved=approved, **kw)

    def _stock(self, qty, store_code='100'):
        return ItemStock.objects.create(item=self.item, branch=self.branch, softech_store_code=store_code,
                                        quantity_on_hand=Decimal(qty))

    def test_unapproved_listing_not_sellable(self):
        self._stock(10)
        l = self._listing(approved=False)
        self.assertEqual(listing_problem(l), 'not_approved')
        self.assertEqual(sellable_qty(l, self.branch), 0)

    def test_blocked_item_not_sellable(self):
        self._stock(10)
        self.item.item_archive = True
        self.item.save()
        l = self._listing()
        self.assertEqual(listing_problem(l), 'blocked')
        self.assertEqual(sellable_qty(l, self.branch), 0)

    def test_restricted_item_flagged(self):
        self.item.nosale_classif = '30'
        self.item.save()
        self.assertEqual(listing_problem(self._listing()), 'restricted')

    def test_fridge_needs_allow_flag(self):
        self.item.requires_fridge = True
        self.item.save()
        l = self._listing()
        self.assertEqual(listing_problem(l), 'fridge')
        l.allow_fridge = True
        l.save()
        self.assertEqual(listing_problem(l), '')

    def test_quarantine_stores_excluded(self):
        self._stock(5, '102')
        self._stock(3, '100')
        self.assertEqual(sellable_qty(self._listing(), self.branch), 2)

    def test_open_orders_reserve_stock(self):
        self._stock(10)
        l = self._listing()
        order = ExternalOrder.objects.create(channel=self.channel, store=self.store, branch=self.branch,
                                             external_id='R1', status=ExternalOrder.STATUS_ACCEPTED)
        ExternalOrderLine.objects.create(order=order, listing=l, item=self.item, qty=Decimal('2'))
        self.assertEqual(sellable_qty(l, self.branch), 7)  # 10 - 2 - buffer 1

    def test_max_qty_caps_and_floor(self):
        self._stock('10.9')
        self.channel.max_qty_per_item = 4
        self.channel.save()
        self.assertEqual(sellable_qty(self._listing(), self.branch), 4)
        self.channel.max_qty_per_item = None
        self.channel.save()
        self.assertEqual(sellable_qty(ChannelListing.objects.get(item=self.item), self.branch), 9)

    def test_price_shelf_is_pack_price_tax(self):
        self.item.pack_price_tax = Decimal('10.00')
        self.item.save()
        self.assertEqual(platform_price(self._listing()), Decimal('10.00'))

    def test_price_plus_pct_rounds_to_quarter(self):
        self.item.pack_price_tax = Decimal('10.00')
        self.item.save()
        self.channel.price_rule = 'shelf_plus_pct'
        self.channel.price_pct = Decimal('12')
        self.channel.save()
        self.assertEqual(platform_price(self._listing()), Decimal('11.25'))

    def test_snapshot_rows(self):
        self._stock(10)
        l = self._listing(external_sku='SKU1')
        rows = snapshot(self.channel, self.store)
        self.assertEqual(rows, [{'listing_id': l.id, 'item_id': self.item.id, 'external_sku': 'SKU1',
                                 'qty': 9, 'price': platform_price(l), 'problem': ''}])

    def _price(self, shelf, pct):
        self.item.pack_price_tax = Decimal(shelf)
        self.item.save()
        self.channel.price_rule = 'shelf_plus_pct'
        self.channel.price_pct = Decimal(pct)
        self.channel.save()
        return platform_price(self._listing())

    def test_price_exact_tie_goes_up(self):
        # raw 8.90 * 1.25 = 11.125 -> 44.5 quarters -> half-up 45 -> 11.25
        self.assertEqual(self._price('8.90', '25.00'), Decimal('11.25'))

    def test_price_rounds_down(self):
        self.assertEqual(self._price('10.00', '11.00'), Decimal('11.00'))  # raw 11.10

    def test_shelf_price_two_dp(self):
        self.item.pack_price_tax = Decimal('10')
        self.item.save()
        self.assertEqual(str(platform_price(self._listing())), '10.00')

    def test_settled_pos_order_does_not_reserve(self):
        self._stock(10)
        l = self._listing()
        pos = SoftechSalesOrder.objects.create(branch=self.branch, status=SoftechSalesOrder.STATUS_SETTLED,
                                               channel='contract', softech_branchcode='1', store_code='100')
        order = ExternalOrder.objects.create(channel=self.channel, store=self.store, branch=self.branch,
                                             external_id='S1', status=ExternalOrder.STATUS_READY, pos_order=pos)
        ExternalOrderLine.objects.create(order=order, listing=l, item=self.item, qty=Decimal('2'))
        self.assertEqual(sellable_qty(l, self.branch), 9)

    def test_other_branch_stock_ignored(self):
        other = make_branch2()
        ItemStock.objects.create(item=self.item, branch=other, softech_store_code='100', quantity_on_hand=50)
        self._stock(3)
        self.assertEqual(sellable_qty(self._listing(), self.branch), 2)

    def test_over_reservation_floors_at_zero(self):
        self._stock(2)
        l = self._listing()
        order = ExternalOrder.objects.create(channel=self.channel, store=self.store, branch=self.branch,
                                             external_id='O1', status=ExternalOrder.STATUS_PREPARING)
        ExternalOrderLine.objects.create(order=order, listing=l, item=self.item, qty=Decimal('5'))
        self.assertEqual(sellable_qty(l, self.branch), 0)
        self.assertEqual(snapshot(self.channel, self.store)[0]['qty'], 0)

    def test_snapshot_query_count_constant(self):
        self._stock(10)
        self._listing()
        with CaptureQueriesContext(connection) as one:
            snapshot(self.channel, self.store)
        for n in range(2):
            it = make_item(f'x{n}', f'AV10{n}')
            ChannelListing.objects.create(channel=self.channel, item=it, approved=True)
        with CaptureQueriesContext(connection) as three:
            rows = snapshot(self.channel, self.store)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(one), len(three))
