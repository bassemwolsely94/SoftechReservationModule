"""Marketplace channels (doc 38) — Task 1: access, seed grants, model constraints."""
from decimal import Decimal
from unittest.mock import patch

from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import ItemStock
from apps.marketplace.access import Access
from apps.marketplace.availability import platform_price, sellable_qty, snapshot
from apps.marketplace.eligibility import listing_problem
from apps.marketplace.models import (ChannelListing, ChannelStore, ExternalOrder, ExternalOrderLine,
                                     MarketplaceChannel, PushLog)
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


class MarketplacePushTests(TestCase):
    def setUp(self):
        from apps.marketplace.adapters import fake
        self.fake = fake
        fake.reset()
        self.addCleanup(fake.reset)
        self.branch = make_branch()
        self.channel = MarketplaceChannel.objects.create(code='push_test', name='تجربة', adapter='fake',
                                                         credentials={'secret': 's3'})
        self.store = ChannelStore.objects.create(channel=self.channel, branch=self.branch, is_active=True)
        self.item = make_item('صنف', 'PU001')
        ChannelListing.objects.create(channel=self.channel, item=self.item, approved=True)

    def _activate(self):
        self.channel.is_active = True
        self.channel.save()

    @override_settings(MARKETPLACE_PUSH_ENABLED=False)
    def test_push_is_dry_run_when_switch_off(self):
        from apps.marketplace.push import push_stock
        self._activate()
        logs = push_stock(self.channel)
        self.assertEqual(self.fake.CALLS, [])
        self.assertEqual(len(logs), 1)
        self.assertTrue(logs[0].dry_run and logs[0].ok)
        self.assertEqual(logs[0].kind, 'stock')
        self.assertEqual(len(logs[0].payload), 1)

    @override_settings(MARKETPLACE_PUSH_ENABLED=True)
    def test_push_dry_run_when_channel_inactive(self):
        from apps.marketplace.push import push_stock
        logs = push_stock(self.channel)
        self.assertEqual(self.fake.CALLS, [])
        self.assertTrue(logs[0].dry_run)

    @override_settings(MARKETPLACE_PUSH_ENABLED=True)
    def test_push_calls_adapter_when_on_and_active(self):
        from apps.marketplace.push import push_stock
        self._activate()
        logs = push_stock(self.channel)
        self.assertEqual([c[0] for c in self.fake.CALLS], ['push_stock'])
        self.assertFalse(logs[0].dry_run)
        self.assertTrue(logs[0].ok)

    @override_settings(MARKETPLACE_PUSH_ENABLED=True)
    def test_adapter_error_logged_not_raised(self):
        from apps.marketplace.push import push_stock
        self._activate()
        self.fake.FAIL_NEXT = True
        logs = push_stock(self.channel)
        self.assertFalse(logs[0].ok)
        self.assertEqual(logs[0].response['error'], 'RuntimeError')

    def test_inactive_store_skipped_when_store_none(self):
        from apps.marketplace.push import push_stock
        self.store.is_active = False
        self.store.save()
        self.assertEqual(push_stock(self.channel), [])

    @override_settings(MARKETPLACE_PUSH_ENABLED=False)
    def test_push_status_dry_run(self):
        from apps.marketplace.push import push_status
        self._activate()
        order = ExternalOrder.objects.create(channel=self.channel, store=self.store, branch=self.branch,
                                             external_id='P1', status=ExternalOrder.STATUS_ACCEPTED)
        log = push_status(order)
        self.assertEqual(log.kind, 'status')
        self.assertTrue(log.dry_run)
        self.assertEqual(self.fake.CALLS, [])

    def test_fake_webhook_signature_and_registry(self):
        from apps.marketplace.adapters import get_adapter

        class Req:
            headers = {'X-Fake-Signature': 's3'}
        self.assertTrue(get_adapter('fake', self.channel).verify_webhook(Req))
        Req.headers = {'X-Fake-Signature': 'bad'}
        self.assertFalse(get_adapter('fake', self.channel).verify_webhook(Req))
        self.assertFalse(get_adapter('manual', self.channel).verify_webhook(Req))
        with self.assertRaises(KeyError):
            get_adapter('nope')

    def test_fake_webhook_rejects_empty_or_missing(self):
        from apps.marketplace.adapters import get_adapter

        class Req:
            headers = {'X-Fake-Signature': ''}
        self.channel.credentials = {'secret': ''}
        self.assertFalse(get_adapter('fake', self.channel).verify_webhook(Req))   # empty secret, empty sig
        self.channel.credentials = {}
        Req.headers = {'X-Fake-Signature': 'x'}
        self.assertFalse(get_adapter('fake', self.channel).verify_webhook(Req))   # missing secret
        self.channel.credentials = {'secret': 's3'}
        Req.headers = {}
        self.assertFalse(get_adapter('fake', self.channel).verify_webhook(Req))   # missing header


class MarketplaceIntakeTests(TestCase):
    def setUp(self):
        from apps.marketplace.adapters.base import IncomingLine, IncomingOrder
        self.IL, self.IO = IncomingLine, IncomingOrder
        self.branch = make_branch()
        _, self.staff, _ = make_admin('intake_admin')
        self.channel = MarketplaceChannel.objects.create(code='in_test', name='تجربة', stock_buffer=Decimal('0'))
        self.store = ChannelStore.objects.create(channel=self.channel, branch=self.branch,
                                                 external_store_id='ST1', is_active=True)
        self.item = make_item('صنف', 'IN001')
        ItemStock.objects.create(item=self.item, branch=self.branch, softech_store_code='100',
                                 quantity_on_hand=Decimal('10'))
        self.listing = ChannelListing.objects.create(channel=self.channel, item=self.item, approved=True,
                                                     external_sku='SKU1')

    def _incoming(self, ext='E1', lines=None, store='ST1'):
        lines = lines if lines is not None else [self.IL('SKU1', 'صنف', Decimal('2'), Decimal('10'))]
        return self.IO(ext, store, 'عميل', '01000000000', 'عنوان', 'platform_paid', Decimal('20'), lines, {})

    def _ingest(self, **kw):
        from apps.marketplace import intake
        return intake.ingest(self.channel, self._incoming(**kw), source='api')

    def test_duplicate_webhook_is_one_order(self):
        o1, c1 = self._ingest()
        o2, c2 = self._ingest()
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(o1.pk, o2.pk)
        self.assertEqual(ExternalOrder.objects.count(), 1)
        self.assertEqual(o1.events.count(), 1)

    def test_unknown_store_creates_nothing(self):
        with self.assertRaises(ValueError):
            self._ingest(store='NOPE')
        self.assertEqual(ExternalOrder.objects.count(), 0)

    def test_accept_refuses_unlisted_or_blocked_line(self):
        from apps.marketplace import intake
        order, _ = self._ingest(ext='E2', lines=[self.IL('ZZZ', 'مجهول', Decimal('1'), Decimal('5'))])
        self.assertEqual(order.lines.get().problem, 'not_listed')
        with patch('apps.marketplace.to_pos.convert'), self.assertRaises(ValueError):
            intake.accept(order, self.staff)
        order.refresh_from_db()
        self.assertEqual(order.status, 'received')
        order2, _ = self._ingest(ext='E3')
        self.item.item_archive = True
        self.item.save()
        with patch('apps.marketplace.to_pos.convert'), self.assertRaises(ValueError):
            intake.accept(order2, self.staff)
        self.assertEqual(order2.lines.get().problem, 'blocked')

    def test_accept_refuses_oos_line(self):
        from apps.marketplace import intake
        order, _ = self._ingest(ext='E4', lines=[self.IL('SKU1', 'صنف', Decimal('6'), Decimal('10')),
                                                 self.IL('SKU1', 'صنف', Decimal('6'), Decimal('10'))])
        with patch('apps.marketplace.to_pos.convert'), self.assertRaises(ValueError):
            intake.accept(order, self.staff)
        self.assertEqual(order.lines.first().problem, 'out_of_stock')

    def test_accept_happy_path_and_convert_failure_rolls_back(self):
        from apps.marketplace import intake
        order, _ = self._ingest(ext='E5')
        with patch('apps.marketplace.to_pos.convert', side_effect=ValueError('x')), self.assertRaises(ValueError):
            intake.accept(order, self.staff)
        order.refresh_from_db()
        self.assertEqual(order.status, 'received')
        with patch('apps.marketplace.to_pos.convert') as conv, self.captureOnCommitCallbacks(execute=True):
            intake.accept(order, self.staff)
        conv.assert_called_once()
        order.refresh_from_db()
        self.assertEqual(order.status, 'accepted')
        self.assertTrue(PushLog.objects.filter(kind='status').exists())

    def test_illegal_transition_raises(self):
        from apps.marketplace import intake
        order, _ = self._ingest(ext='E6')
        for bad in ('delivered', 'preparing'):
            with self.assertRaises(ValueError) as cm:
                intake.set_status(order, bad, self.staff)
            self.assertEqual(str(cm.exception), 'انتقال غير مسموح')

    def test_every_transition_audited(self):
        from apps.audit.models import AuditLog
        from apps.marketplace import intake
        order, _ = self._ingest(ext='E7')
        with patch('apps.marketplace.to_pos.convert'):
            intake.accept(order, self.staff)
        for st in ('preparing', 'ready', 'handed_over', 'delivered'):
            intake.set_status(order, st, self.staff, note='ok')
        self.assertEqual(order.events.count(), 6)
        self.assertEqual(AuditLog.objects.filter(action__startswith='marketplace_order_').count(), 6)
        self.assertEqual(AuditLog.objects.filter(action='marketplace_order_delivered').count(), 1)
        blob = ' '.join(str(a.new_data) + str(a.old_data) + str(a.extra) for a in AuditLog.objects.all())
        self.assertNotIn('01000000000', blob)

    def test_reject_records_reason(self):
        from apps.marketplace import intake
        order, _ = self._ingest(ext='E8')
        intake.reject(order, self.staff, 'مغلق')
        order.refresh_from_db()
        self.assertEqual((order.status, order.reject_reason), ('rejected', 'مغلق'))
        with self.assertRaises(ValueError):
            intake.reject(order, self.staff, 'x')
