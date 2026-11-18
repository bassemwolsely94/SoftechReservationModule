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
from apps.marketplace.models import (SettlementBatch, ChannelListing, ChannelStore, ExternalOrder, ExternalOrderLine,
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
        with patch('apps.marketplace.to_pos.convert') as conv, self.assertRaises(ValueError):
            intake.accept(order, self.staff)
        conv.assert_not_called()
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
        with patch('apps.marketplace.to_pos.convert') as conv, self.assertRaises(ValueError):
            intake.accept(order, self.staff)
        conv.assert_not_called()
        self.assertEqual(order.lines.first().problem, 'out_of_stock')
        self.assertEqual([l.problem for l in order.lines.all()], ['out_of_stock', 'out_of_stock'])

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

    def test_second_accept_raises_and_no_second_draft(self):
        from apps.marketplace import intake
        self.channel.softech_personcode = 'P100'
        self.channel.save()
        order, _ = self._ingest(ext='E9')
        intake.accept(order, self.staff)
        with self.assertRaises(ValueError):
            intake.accept(order, self.staff)
        self.assertEqual(SoftechSalesOrder.objects.count(), 1)

    def test_end_to_end_accept_creates_real_draft(self):
        from apps.marketplace import intake
        self.channel.softech_personcode = 'P100'
        self.channel.save()
        order, _ = self._ingest(ext='E10')
        with self.captureOnCommitCallbacks(execute=True):
            intake.accept(order, self.staff)
        order.refresh_from_db()
        self.assertEqual(order.status, 'accepted')
        self.assertEqual(order.pos_order.status, 'draft')
        self.assertEqual(order.pos_order.cust_branch_code, 'P100')
        self.assertTrue(PushLog.objects.filter(kind='status').exists())


class MarketplaceToPosTests(TestCase):
    def setUp(self):
        from apps.marketplace.adapters.base import IncomingLine, IncomingOrder
        self.branch = make_branch()
        _, self.staff, _ = make_admin('topos_admin')
        self.staff.softech_user_id = ' 123456789 '
        self.staff.save()
        self.channel = MarketplaceChannel.objects.create(code='tp_test', name='منصة', softech_personcode='PL01',
                                                         stock_buffer=Decimal('0'))
        ChannelStore.objects.create(channel=self.channel, branch=self.branch, external_store_id='S', is_active=True)
        self.item = make_item('صنف', 'TP001')
        self.item.pack_price = Decimal('10')
        self.item.pack_price_tax = Decimal('11.40')
        self.item.sale_tax_pct = Decimal('14')
        self.item.save()
        ItemStock.objects.create(item=self.item, branch=self.branch, softech_store_code='100',
                                 quantity_on_hand=Decimal('10'))
        ChannelListing.objects.create(channel=self.channel, item=self.item, approved=True, external_sku='K')
        from apps.marketplace import intake
        inc = IncomingOrder('X1', 'S', 'c', '', 'a', 'platform_paid', Decimal('20'),
                            [IncomingLine('K', 'صنف', Decimal('2'), Decimal('10'))], {})
        self.order, _ = intake.ingest(self.channel, inc, source='api')

    def test_convert_creates_contract_draft_on_platform_account(self):
        from apps.audit.models import AuditLog
        from apps.marketplace import to_pos
        draft = to_pos.convert(self.order, self.staff)
        self.assertEqual((draft.channel, draft.status, draft.doc_kind), ('contract', 'draft', 'sale'))
        self.assertEqual(draft.cust_branch_code, 'PL01')
        self.assertEqual(draft.branch, self.branch)
        self.assertEqual(draft.softech_branchcode, self.branch.softech_branch_id)
        self.assertIn('X1', draft.notes)
        self.assertEqual(draft.seller_usercode, '12345')
        self.assertEqual(draft.lines.count(), 1)
        line = draft.lines.get()
        self.assertEqual((line.qty, line.item_sale_price, line.item_sale_price_tax, line.sale_tax_pct, line.cust_discp),
                         (Decimal('2'), Decimal('10'), Decimal('11.40'), Decimal('14'), 0))
        self.order.refresh_from_db()
        self.assertEqual(self.order.pos_order_id, draft.pk)
        self.assertTrue(AuditLog.objects.filter(action='marketplace_pos_draft_created').exists())

    def test_convert_twice_returns_same_draft(self):
        from apps.marketplace import to_pos
        d1 = to_pos.convert(self.order, self.staff)
        self.order.pos_order = None
        self.order.save()
        d2 = to_pos.convert(self.order, self.staff)
        self.assertEqual(d1.pk, d2.pk)
        self.assertEqual(SoftechSalesOrder.objects.count(), 1)
        self.assertEqual(d1.lines.count(), 1)
        self.order.refresh_from_db()
        self.assertEqual(self.order.pos_order_id, d1.pk)

    def test_convert_without_personcode_refused(self):
        from apps.marketplace import to_pos
        self.channel.softech_personcode = ' '
        self.channel.save()
        self.order.refresh_from_db()
        with self.assertRaisesMessage(ValueError, 'حساب المنصة في SOFTECH غير محدد'):
            to_pos.convert(self.order, self.staff)
        self.assertEqual(SoftechSalesOrder.objects.count(), 0)

    def test_convert_never_calls_writer(self):
        from apps.marketplace import to_pos
        with patch('apps.pos_orders.writer.push_order') as w:
            to_pos.convert(self.order, self.staff)
        w.assert_not_called()


@override_settings(MARKETPLACE_ENABLED=True, MARKETPLACE_PUSH_ENABLED=False)
class MarketplaceApiTests(TestCase):
    """Task 6: /api/marketplace/ — flag, permissions, branch scope, masking, manual intake, webhook."""

    def setUp(self):
        self.branch = make_branch()
        self.branch2 = make_branch2()
        self.admin_user, self.admin, self.client_admin = make_admin('api_admin')
        self.channel = MarketplaceChannel.objects.create(
            code='api_test', name='منصة', softech_personcode='PL01', stock_buffer=Decimal('0'),
            adapter='fake', is_active=True, credentials={'secret': 'top-secret-value'})
        self.store = ChannelStore.objects.create(channel=self.channel, branch=self.branch,
                                                 external_store_id='S1', is_active=True)
        self.store2 = ChannelStore.objects.create(channel=self.channel, branch=self.branch2,
                                                  external_store_id='S2', is_active=True)
        self.item = make_item('صنف', 'API001')
        self.item.pack_price = Decimal('10')
        self.item.pack_price_tax = Decimal('11.40')
        self.item.sale_tax_pct = Decimal('14')
        self.item.save()
        for b in (self.branch, self.branch2):
            ItemStock.objects.create(item=self.item, branch=b, softech_store_code='100',
                                     quantity_on_hand=Decimal('10'))
        self.listing = ChannelListing.objects.create(channel=self.channel, item=self.item, approved=True,
                                                     external_sku='SKU1')

    def _order(self, ext, store=None, phone='01011112222'):
        store = store or self.store
        return ExternalOrder.objects.create(channel=self.channel, store=store, branch=store.branch,
                                            external_id=ext, customer_phone=phone)

    def _webhook_body(self, ext='W1'):
        return {'external_id': ext, 'external_store_id': 'S1', 'customer_name': 'عميل',
                'customer_phone': '01099998888', 'address': 'عنوان', 'payment_mode': 'platform_paid',
                'total': '20', 'lines': [{'external_sku': 'SKU1', 'name': 'صنف', 'qty': '2', 'unit_price': '10'}]}

    def _hook(self, code='api_test', body=None, sig='top-secret-value'):
        extra = {'HTTP_X_FAKE_SIGNATURE': sig} if sig is not None else {}
        return self.client.post(f'/api/marketplace/webhooks/{code}/', body if body is not None else self._webhook_body(),
                                content_type='application/json', **extra)

    def test_flag_off_404(self):
        with override_settings(MARKETPLACE_ENABLED=False):
            for path in ('/api/marketplace/channels/', '/api/marketplace/orders/', '/api/marketplace/listings/'):
                self.assertEqual(self.client_admin.get(path).status_code, 404, path)
            self.assertEqual(self._hook().status_code, 404)

    def test_other_branch_order_hidden(self):
        mine = self._order('M1')
        other = self._order('O1', store=self.store2)
        _, _, client = make_pharmacist('api_ph_branch', branch=self.branch)
        r = client.get('/api/marketplace/orders/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        ids = {row['id'] for row in r.json()['results']}
        self.assertIn(mine.id, ids)
        self.assertNotIn(other.id, ids)
        self.assertEqual(client.get(f'/api/marketplace/orders/{other.id}/').status_code, 404)
        self.assertEqual(client.post(f'/api/marketplace/orders/{other.id}/accept/').status_code, 404)
        self.assertEqual(client.get(f'/api/marketplace/orders/{mine.id}/').status_code, 200)

    def test_manual_intake_end_to_end(self):
        body = {'channel': self.channel.id, 'branch': self.branch.id, 'external_id': 'MAN-1',
                'customer_name': 'عميل', 'customer_phone': '01055554444', 'address': 'عنوان',
                'payment_mode': 'cash_on_delivery',
                'lines': [{'item_id': self.item.id, 'qty': 2, 'unit_price': '12.50'}]}
        r = self.client_admin.post('/api/marketplace/orders/manual/', body, format='json')
        self.assertEqual(r.status_code, 201, r.content[:300])
        order = ExternalOrder.objects.get(pk=r.json()['id'])
        self.assertEqual((order.source, order.branch_id, order.platform_total), ('manual', self.branch.id, Decimal('25')))
        self.assertEqual(order.lines.get().listing_id, self.listing.id)
        again = self.client_admin.post('/api/marketplace/orders/manual/', body, format='json')
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()['id'], order.id)
        with self.captureOnCommitCallbacks(execute=True):
            acc = self.client_admin.post(f'/api/marketplace/orders/{order.id}/accept/')
        self.assertEqual(acc.status_code, 200, acc.content[:300])
        order.refresh_from_db()
        self.assertEqual(order.status, 'accepted')
        self.assertEqual(order.pos_order.status, 'draft')
        self.assertEqual(acc.json()['pos_order']['id'], order.pos_order_id)
        bad = self.client_admin.post(f'/api/marketplace/orders/{order.id}/accept/')
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.json()['detail'], 'انتقال غير مسموح')
        st = self.client_admin.post(f'/api/marketplace/orders/{order.id}/status/',
                                    {'to_status': 'preparing', 'note': 'ok'}, format='json')
        self.assertEqual(st.status_code, 200, st.content[:300])
        self.assertEqual(st.json()['status'], 'preparing')

    def test_manual_intake_other_branch_refused(self):
        _, _, client = make_pharmacist('api_ph_manual', branch=self.branch)
        body = {'channel': self.channel.id, 'branch': self.branch2.id, 'external_id': 'MAN-X',
                'lines': [{'item_id': self.item.id, 'qty': 1, 'unit_price': '1'}]}
        self.assertEqual(client.post('/api/marketplace/orders/manual/', body, format='json').status_code, 403)
        self.assertFalse(ExternalOrder.objects.exists())

    def test_reject_flow(self):
        order = self._order('RJ1')
        r = self.client_admin.post(f'/api/marketplace/orders/{order.id}/reject/', {'reason': 'مغلق'}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        order.refresh_from_db()
        self.assertEqual((order.status, order.reject_reason), ('rejected', 'مغلق'))

    def test_webhook_creates_and_duplicate_200(self):
        r = self._hook()
        self.assertEqual(r.status_code, 201, r.content[:300])
        oid = r.json()['id']
        self.assertEqual(ExternalOrder.objects.get(pk=oid).source, 'api')
        r2 = self._hook()
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()['id'], oid)
        self.assertEqual(ExternalOrder.objects.count(), 1)

    def test_webhook_bad_signature_403(self):
        r = self._hook(sig='wrong')
        self.assertEqual(r.status_code, 403)
        self.assertNotIn('secret', r.content.decode())
        self.assertEqual(self._hook(sig=None).status_code, 403)
        self.assertFalse(ExternalOrder.objects.exists())

    def test_webhook_unknown_store_422_nothing_stored(self):
        body = self._webhook_body()
        body['external_store_id'] = 'NOPE'
        r = self._hook(body=body)
        self.assertEqual(r.status_code, 422)
        self.assertNotIn('01099998888', r.content.decode())
        self.assertFalse(ExternalOrder.objects.exists())
        bad = self._hook(body={'external_id': 'B1', 'external_store_id': 'S1', 'lines': [{'qty': 'abc'}]})
        self.assertEqual(bad.status_code, 422)
        self.assertFalse(ExternalOrder.objects.exists())

    def test_webhook_disabled_channel_404(self):
        self.channel.is_active = False
        self.channel.save()
        self.assertEqual(self._hook().status_code, 404)
        MarketplaceChannel.objects.create(code='man_hook', name='يدوي', adapter='manual', is_active=True)
        self.assertEqual(self._hook(code='man_hook', body={}).status_code, 404)
        self.assertEqual(self._hook(code='nope', body={}).status_code, 404)

    def test_credentials_never_returned(self):
        secret = 'top-secret-value'
        r = self.client_admin.get('/api/marketplace/channels/')
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(secret, r.content.decode())
        self.assertNotIn('credentials', r.json()['results'][0])
        d = self.client_admin.get(f'/api/marketplace/channels/{self.channel.id}/')
        self.assertEqual(d.status_code, 200)
        self.assertNotIn(secret, d.content.decode())
        p = self.client_admin.patch(f'/api/marketplace/channels/{self.channel.id}/',
                                    {'credentials': {'secret': 'new-secret-xyz'}, 'name': 'جديد'}, format='json')
        self.assertEqual(p.status_code, 200, p.content[:300])
        self.assertNotIn('new-secret-xyz', p.content.decode())
        self.channel.refresh_from_db()
        self.assertEqual(self.channel.credentials, {'secret': 'new-secret-xyz'})
        c = self.client_admin.post('/api/marketplace/channels/', {'code': 'new_ch', 'name': 'ن',
                                   'credentials': {'secret': 'zzz-created'}}, format='json')
        self.assertEqual(c.status_code, 201, c.content[:300])
        self.assertNotIn('zzz-created', c.content.decode())
        push = self.client_admin.post(f'/api/marketplace/channels/{self.channel.id}/push-stock/')
        self.assertEqual(push.status_code, 200, push.content[:300])
        self.assertEqual(len(push.json()), 2)
        self.assertTrue(all(row['dry_run'] for row in push.json()))
        log = self.client_admin.get('/api/marketplace/push-log/', {'channel': self.channel.id})
        self.assertEqual(log.status_code, 200)
        self.assertEqual(len(log.json()['results']), 2)
        self.assertNotIn('new-secret-xyz', log.content.decode())
        self.assertNotIn('credentials', log.content.decode())

    def test_phone_masked_in_list(self):
        self._order('PH1', phone='01011112222')
        r = self.client_admin.get('/api/marketplace/orders/')
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNotIn('01011112222', body)
        self.assertTrue(r.json()['results'][0]['customer_phone'].endswith('222'))
        self.assertNotIn('raw_payload', body)

    def test_pharmacist_cannot_approve_listing(self):
        from django.core.management import call_command
        call_command('seed_permissions', verbosity=0)
        new = ChannelListing.objects.create(channel=self.channel, item=make_item('آخر', 'API002'))
        _, _, client = make_pharmacist('api_ph_approve', branch=self.branch)
        r = client.post(f'/api/marketplace/listings/{new.id}/approve/')
        self.assertEqual(r.status_code, 403)
        new.refresh_from_db()
        self.assertFalse(new.approved)
        self.assertEqual(client.patch(f'/api/marketplace/channels/{self.channel.id}/', {'name': 'x'},
                                      format='json').status_code, 403)

    def test_listing_approve_unapprove_audited(self):
        from apps.audit.models import AuditLog
        new = ChannelListing.objects.create(channel=self.channel, item=make_item('آخر', 'API003'))
        r = self.client_admin.post(f'/api/marketplace/listings/{new.id}/approve/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        new.refresh_from_db()
        self.assertTrue(new.approved)
        self.assertEqual(new.approved_by_id, self.admin.id)
        self.assertIsNotNone(new.approved_at)
        self.assertTrue(AuditLog.objects.filter(action='marketplace_listing_approved').exists())
        self.client_admin.post(f'/api/marketplace/listings/{new.id}/unapprove/')
        new.refresh_from_db()
        self.assertFalse(new.approved)
        self.assertIsNone(new.approved_by_id)
        self.assertTrue(AuditLog.objects.filter(action='marketplace_listing_unapproved').exists())

    def test_listings_list_problem_and_qty(self):
        r = self.client_admin.get('/api/marketplace/listings/', {'channel': self.channel.id, 'branch': self.branch.id})
        self.assertEqual(r.status_code, 200, r.content[:300])
        row = r.json()['results'][0]
        self.assertEqual((row['problem'], row['qty']), ('', '10'))
        c = self.client_admin.post('/api/marketplace/listings/', {'channel': self.channel.id,
                                   'item': make_item('ب', 'API004').id, 'approved': True}, format='json')
        self.assertEqual(c.status_code, 201, c.content[:300])
        self.assertFalse(ChannelListing.objects.get(pk=c.json()['id']).approved)

    def test_stores_branch_scoped(self):
        _, _, client = make_pharmacist('api_ph_store', branch=self.branch)
        r = client.get('/api/marketplace/stores/')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual({row['id'] for row in r.json()['results']}, {self.store.id})


class MarketplaceMiddlewareTests(TestCase):
    def test_webhooks_exempt_only_exact_prefix(self):
        from core.middleware.module_access import required
        self.assertIsNone(required('/api/marketplace/webhooks/x/', 'POST'))
        self.assertIsNotNone(required('/api/marketplace/orders/', 'GET'))
        self.assertIsNotNone(required('/api/marketplace/webhooks-evil/', 'POST'))
        self.assertEqual(required('/api/marketplace/listings/1/approve/', 'POST'), ('marketplace', ('approve',)))
        self.assertEqual(required('/api/marketplace/listings/1/unapprove/', 'POST'), ('marketplace', ('approve',)))
        self.assertEqual(required('/api/marketplace/channels/', 'POST'), ('marketplace', ('edit',)))
        self.assertEqual(required('/api/marketplace/channels/1/push-stock/', 'POST'), ('marketplace', ('edit',)))
        self.assertEqual(required('/api/marketplace/stores/1/', 'PATCH'), ('marketplace', ('edit',)))
        self.assertEqual(required('/api/marketplace/channels/', 'GET'), ('marketplace', ('view',)))
        self.assertEqual(required('/api/marketplace/orders/manual/', 'POST')[0], 'marketplace')
        self.assertIn('create', required('/api/marketplace/orders/manual/', 'POST')[1])


class MarketplaceSettlementTests(TestCase):
    """Task 7: settlement file import + matching."""

    def setUp(self):
        from datetime import date
        self.today = date.today()
        self.branch = make_branch()
        self.channel = MarketplaceChannel.objects.create(code='st_test', name='منصة', adapter='manual')
        self.store = ChannelStore.objects.create(channel=self.channel, branch=self.branch)
        self.cmap = {'external_id': 'order', 'gross': 'gross', 'commission': 'comm',
                     'delivery_fee': 'fee', 'net': 'net'}

    def _order(self, ext, total, status='delivered'):
        return ExternalOrder.objects.create(channel=self.channel, store=self.store, branch=self.branch,
                                            external_id=ext, platform_total=Decimal(total), status=status)

    def _file(self, rows, name='payout.csv'):
        import io
        text = 'order,gross,comm,fee,net\n' + ''.join(','.join(f'"{c}"' for c in r) + '\n' for r in rows)
        f = io.BytesIO(text.encode('utf-8-sig'))
        f.name = name
        return f

    def _run(self, rows, **kw):
        from apps.marketplace import settlement
        batch = settlement.import_csv(self.channel, self._file(rows), self.cmap, None,
                                      period_from=self.today, period_to=self.today)
        return batch, settlement.match(batch)

    def test_unmatched_and_mismatch_become_exceptions(self):
        self._order('A1', '100')
        batch, counts = self._run([('A1', '90.00', '5', '0', '85'), ('ZZ', '10', '1', '0', '9')])
        by = {l.external_id: l for l in batch.lines.all()}
        self.assertEqual(by['A1'].match_status, 'amount_mismatch')
        self.assertEqual(by['ZZ'].match_status, 'unmatched')
        self.assertIsNone(by['ZZ'].order)
        self.assertEqual(counts['amount_mismatch'], 1)
        self.assertEqual(counts['unmatched'], 1)

    def test_matched_within_half_pound(self):
        self._order('B1', '100.00')
        self._order('B2', '100.00')
        self._order('B3', '1234.50')
        batch, counts = self._run([('B1', '99.50', '0', '0', '0'),
                                   ('B2', '100.51', '0', '0', '0'),
                                   ('B3', '1,234.50', '0', '0', '0')])
        by = {l.external_id: l for l in batch.lines.all()}
        self.assertEqual(by['B1'].match_status, 'matched')       # 99.50 vs 100: diff 0.50
        self.assertEqual(by['B2'].match_status, 'amount_mismatch')  # 0.51 off
        self.assertEqual(by['B3'].match_status, 'matched')       # thousands separator
        self.assertEqual(counts['matched'], 2)

    def test_delivered_order_missing_from_file_flagged(self):
        from apps.marketplace import settlement
        self._order('C1', '50')
        self._order('C2', '60')
        self._order('C3', '70', status='accepted')
        batch, counts = self._run([('C1', '50', '0', '0', '0')])
        missing = list(batch.lines.filter(match_status='not_in_file'))
        self.assertEqual([l.external_id for l in missing], ['C2'])
        self.assertEqual(counts['not_in_file'], 1)
        # re-runnable: no duplicates, orders untouched
        settlement.match(batch)
        self.assertEqual(batch.lines.filter(match_status='not_in_file').count(), 1)
        self.assertEqual(ExternalOrder.objects.get(external_id='C2').status, 'delivered')

    def test_bad_amount_does_not_crash_and_arabic_digits(self):
        self._order('D1', '12')
        batch, _ = self._run([('D1', '١٢', '0', '0', '0'), ('D2', 'abc', '0', '0', '0')])
        by = {l.external_id: l for l in batch.lines.all()}
        self.assertEqual(by['D1'].match_status, 'matched')
        self.assertEqual(by['D2'].match_status, 'unmatched')
        self.assertTrue(by['D2'].note)

    def test_rejects_bad_extension_and_big_file(self):
        from apps.marketplace import settlement
        with self.assertRaises(ValueError):
            settlement.import_csv(self.channel, self._file([], 'x.pdf'), self.cmap, None)
        with self.assertRaises(ValueError):
            settlement.import_csv(self.channel, self._file([('a',) * 5] * 1, 'x.csv'), {}, None)

    def test_duplicate_file_rows_flagged(self):
        self._order('F1', '100')
        batch, counts = self._run([('F1', '100', '0', '0', '0'), ('F1', '100', '0', '0', '0')])
        lines = list(batch.lines.order_by('id'))
        self.assertEqual([l.match_status for l in lines], ['matched', 'amount_mismatch'])
        self.assertIn('مكرر', lines[1].note)
        self.assertEqual(counts['matched'], 1)

    def test_missing_mapped_column_rejected(self):
        from apps.marketplace import settlement
        for bad in ({**self.cmap, 'external_id': 'nope'}, {**self.cmap, 'gross': 'nope'}):
            with self.assertRaisesMessage(ValueError, 'column_missing'):
                settlement.import_csv(self.channel, self._file([('A', '1', '0', '0', '0')]), bad, None)
        self.assertEqual(SettlementBatch.objects.count(), 0)

    def test_missing_mapped_column_rejected_xlsx(self):
        import io
        import openpyxl
        from apps.marketplace import settlement
        wb = openpyxl.Workbook()
        wb.active.append(['order', 'gross'])
        wb.active.append(['A', 5])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = 'p.xlsx'
        with self.assertRaisesMessage(ValueError, 'column_missing'):
            settlement.import_csv(self.channel, buf, {'external_id': 'order', 'gross': 'oops'}, None)
        buf.seek(0)
        b = settlement.import_csv(self.channel, buf, {'external_id': 'order', 'gross': 'gross'}, None)
        self.assertEqual(b.lines.get().gross, Decimal('5.00'))

    def test_over_size_and_over_rows_rejected(self):
        from apps.marketplace import settlement
        with patch.object(settlement, 'MAX_BYTES', 50):
            with self.assertRaisesMessage(ValueError, 'file_too_large'):
                settlement.import_csv(self.channel, self._file([('A' * 10, '1', '0', '0', '0')] * 5),
                                      self.cmap, None)
        with patch.object(settlement, 'MAX_ROWS', 3):
            with self.assertRaisesMessage(ValueError, 'too_many_rows'):
                settlement.import_csv(self.channel, self._file([('A', '1', '0', '0', '0')] * 4), self.cmap, None)

    @override_settings(MARKETPLACE_ENABLED=True)
    def test_api_upload_and_read(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        import json
        _, _, client = make_admin('st_admin')
        self._order('E1', '40')
        f = self._file([('E1', '40', '0', '0', '0'), ('E9', '5', '0', '0', '0')])
        up = SimpleUploadedFile('payout.csv', f.read(), content_type='text/csv')
        r = client.post('/api/marketplace/settlements/', {
            'channel': self.channel.id, 'file': up, 'column_map': json.dumps(self.cmap),
            'period_from': self.today.isoformat(), 'period_to': self.today.isoformat()}, format='multipart')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()['match']['matched'], 1)
        bid = r.json()['id']
        self.assertEqual(client.get('/api/marketplace/settlements/').status_code, 200)
        d = client.get(f'/api/marketplace/settlements/{bid}/?status=unmatched').json()
        self.assertEqual([l['external_id'] for l in d['lines']], ['E9'])
        with override_settings(MARKETPLACE_ENABLED=False):
            self.assertEqual(client.get('/api/marketplace/settlements/').status_code, 404)

    def test_middleware_settlement_post_is_edit(self):
        from core.middleware.module_access import required
        self.assertEqual(required('/api/marketplace/settlements/', 'POST'), ('marketplace', ('edit',)))
        self.assertEqual(required('/api/marketplace/settlements/', 'GET'), ('marketplace', ('view',)))
