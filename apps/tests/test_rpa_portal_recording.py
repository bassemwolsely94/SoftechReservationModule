"""Task 8: recording what the portal robot saw — availability checks and placed orders.

The rule this file guards above all: a placed supplier order is recorded exactly once
(commit_order keyed `portal-basket-<pk>`), with the quantities Order History shows, and the
missing quantity goes back to the buyer as a remainder.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.catalog.models import Item
from apps.invoices.models import VendorProfile
from apps.rpa.models import (BuyList, BuyListLine, PortalAccount, PortalBasket, PortalJob,
                             PortalLine, SupplierPortal)
from apps.rpa.portal import recording
from apps.supply.models import AvailabilityBatch, SupplyDecision
from .factories import make_user


def _last_cost(cost):
    """purchase_history stub: every item's last buy at `cost`."""
    def fn(codes, **kw):
        return {(c, '565'): {'last': {'date': '2026-10-01', 'unit_cost': cost}} for c in codes}
    return fn


class _World:
    def build(self):
        _, self.buyer, _ = make_user('prec_buyer', role='purchasing', access_all=True)
        self.hq = Branch.objects.create(softech_branch_id='100', name='HQ', kind=Branch.KIND_HQ)
        self.vendor = VendorProfile.objects.create(name='Pharma Overseas', softech_personcode='565')
        self.portal, _ = SupplierPortal.objects.get_or_create(
            key='pharma_overseas', defaults={'supplier_code': '565'})
        self.account = PortalAccount.objects.create(portal=self.portal, label='main',
                                                    identity_text='HQ 565')
        self.items = [Item.objects.create(softech_id=f'PR{n}', name=f'ITEM {n}', is_active=True)
                      for n in range(4)]

    def make_basket(self, wanted, *, status='submitted', accepted=None, reason='over need ok',
                    dry_run=False, extra_baskets=()):
        """wanted: {sku: qty} in order. Returns (job, basket, {sku: PortalLine})."""
        bl = BuyList.objects.create(source_kind='upload', created_by=self.buyer)
        job = PortalJob.objects.create(portal=self.portal, account=self.account, buylist=bl,
                                       status='approved', dry_run=dry_run, created_by=self.buyer,
                                       approved_by=self.buyer, approved_at=timezone.now())
        basket = PortalBasket.objects.create(job=job, seq=1, status=status)
        lines = {}
        for n, (sku, qty) in enumerate(wanted.items()):
            item = self.items[n]
            bline = BuyListLine.objects.create(buylist=bl, seq=n + 1, item=item, needed_qty=qty,
                                               remaining_qty=qty, chosen_supplier='565',
                                               source_key=f'pr:{bl.pk}:{n}', reason=reason)
            acc = (accepted or {}).get(sku, qty)
            lines[sku] = PortalLine.objects.create(
                basket=basket, buyline=bline, item=item, wanted_qty=qty, accepted_qty=acc,
                status='ok', supplier_key=sku, supplier_key_padded=sku.zfill(18))
        for n, st in enumerate(extra_baskets, start=2):
            PortalBasket.objects.create(job=job, seq=n, status=st)
        return job, basket, lines


class RecordCheckTests(_World, TestCase):
    def setUp(self):
        self.build()

    def _payload(self, line, **kw):
        row = {'line_id': line.pk, 'accepted_qty': line.wanted_qty, 'status': 'ok', 'price': '100',
               'discount_pct': '0', 'bonus_text': '', 'supplier_expiry': None, 'message': ''}
        row.update(kw)
        return row

    def test_record_check_flags_short_expiry_and_price_jump(self):
        _, basket, lines = self.make_basket({'11': 5, '12': 5}, status='in_progress', dry_run=True)
        soon = (timezone.localdate() + timedelta(days=8 * 30)).isoformat()
        far = (timezone.localdate() + timedelta(days=24 * 30)).isoformat()
        with mock.patch('apps.supply.comparison.purchase_history', _last_cost(100)):
            recording.record_check(basket, [
                self._payload(lines['11'], supplier_expiry=soon, price='112', status='short',
                              accepted_qty=3, bonus_text='10+1', message='No Enough material Stock'),
                self._payload(lines['12'], supplier_expiry=far, price='105'),
            ])
        a, b = (PortalLine.objects.get(pk=lines[k].pk) for k in ('11', '12'))
        self.assertEqual(sorted(a.flags), ['price_jump', 'short_expiry'])
        self.assertEqual(a.status, 'short')            # flags only: the status is the site's answer
        self.assertEqual(a.accepted_qty, 3)
        self.assertEqual(a.price, Decimal('112'))
        self.assertEqual(a.bonus_text, '10+1')
        self.assertEqual(a.supplier_expiry, date.fromisoformat(soon))
        self.assertEqual(b.flags, [])
        self.assertEqual(b.status, 'ok')
        basket.refresh_from_db()
        self.assertEqual(basket.status, 'dry_run_ok')

    def test_record_check_writes_portal_availability_batch(self):
        _, basket, lines = self.make_basket({'11': 5, '12': 5, '13': 2}, status='in_progress',
                                            dry_run=True)
        exp = date(2027, 9, 30)
        with mock.patch('apps.supply.comparison.purchase_history', _last_cost(100)):
            batch = recording.record_check(basket, [
                self._payload(lines['11'], status='short', accepted_qty=3, supplier_expiry=exp.isoformat()),
                self._payload(lines['12'], status='out', accepted_qty=0),
                self._payload(lines['13']),
                {'line_id': 999999, 'accepted_qty': 1, 'status': 'ok'},     # not this basket's: ignored
            ])
        self.assertEqual(batch.source, AvailabilityBatch.SOURCE_PORTAL)
        self.assertEqual(batch.supplier_id, self.vendor.pk)
        rows = {ln.supplier_item_code: ln for ln in batch.lines.all()}
        self.assertEqual(set(rows), {'11', '12', '13'})
        self.assertEqual(rows['11'].supplier_qty, 3)
        self.assertEqual(rows['11'].signals, ['short'])
        self.assertEqual(rows['11'].expiry, exp.isoformat())
        self.assertEqual(rows['12'].signals, ['out_of_stock'])
        self.assertEqual(rows['13'].signals, [])
        self.assertEqual(rows['13'].item_id, lines['13'].item_id)
        self.assertEqual(PortalLine.objects.get(pk=lines['11'].pk).availability_line_id, rows['11'].pk)
        # a dry run orders nothing and leaves the buy list untouched
        self.assertEqual(SupplyDecision.objects.count(), 0)
        self.assertEqual(BuyListLine.objects.get(pk=lines['11'].buyline_id).remaining_qty, 5)

    def test_dry_run_of_last_basket_finishes_job(self):
        job, basket, lines = self.make_basket({'11': 5}, status='in_progress', dry_run=True)
        with mock.patch('apps.supply.comparison.purchase_history', _last_cost(100)):
            recording.record_check(basket, [self._payload(lines['11'])])
        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        self.assertEqual(job.buylist.status, 'open')      # nothing ordered: the list stays open


class RecordOrderTests(_World, TestCase):
    def setUp(self):
        self.build()

    def test_record_order_uses_history_quantities_and_diff(self):
        _, basket, lines = self.make_basket({'11': 10, '12': 5})
        out = recording.record_order(basket, order_ref='PO-77',
                                     history_lines=[{'sku': '000011', 'qty': 8}], staff=self.buyer)
        self.assertEqual(out.status, 'recorded')
        key = f'portal-basket-{basket.pk}'
        decisions = list(SupplyDecision.objects.filter(order_ref=key))
        self.assertEqual([(d.item_id, d.decided_qty) for d in decisions],
                         [(lines['11'].item_id, Decimal('8'))])
        d = decisions[0]
        self.assertEqual(d.branch_id, self.hq.pk)
        self.assertEqual(d.supplier_id, self.vendor.pk)
        self.assertEqual(d.supplier_name, 'فارما أوفرسيز')
        self.assertEqual(d.result_refs['portal'],
                         {'account': 'main', 'order_ref': 'PO-77', 'basket': basket.pk})
        self.assertEqual([q['sku'] for q in out.diff['qty_changed']], ['11'])
        self.assertEqual(out.diff['qty_changed'][0]['handed_over'], 10)
        self.assertEqual(out.diff['qty_changed'][0]['recorded'], 8)
        self.assertEqual([r['sku'] for r in out.diff['removed']], ['12'])
        self.assertEqual(out.diff['added'], [])
        self.assertEqual((out.portal_ref, out.portal_key, out.order_ref),
                         ('PO-77', 'pharma_overseas:PO-77', key))
        a = BuyListLine.objects.get(pk=lines['11'].buyline_id)
        b = BuyListLine.objects.get(pk=lines['12'].buyline_id)
        self.assertEqual(a.remaining_qty, 2)
        self.assertEqual(b.remaining_qty, 5)           # B's 5 back as a remainder
        self.assertEqual(b.chosen_supplier, '')
        self.assertEqual(b.tried[-1]['supplier'], '565')
        self.assertEqual(b.tried[-1]['accepted'], 0)
        self.assertEqual(PortalLine.objects.get(pk=lines['12'].pk).status, 'removed')
        log = AuditLog.objects.filter(action='rpa_portal_basket_recorded').get()
        self.assertEqual(log.new_data['diff'], out.diff)

    def test_record_order_replay_same_ref_is_noop(self):
        _, basket, lines = self.make_basket({'11': 4, '12': 3})
        hist = [{'sku': '11', 'qty': 4}, {'sku': '12', 'qty': 3}]
        recording.record_order(basket, order_ref='PO-1', history_lines=hist, staff=self.buyer)
        again = recording.record_order(basket, order_ref='PO-1', history_lines=hist, staff=self.buyer)
        self.assertEqual(again.status, 'recorded')
        self.assertEqual(SupplyDecision.objects.filter(order_ref=f'portal-basket-{basket.pk}').count(), 2)
        self.assertEqual(BuyListLine.objects.get(pk=lines['11'].buyline_id).remaining_qty, 0)
        self.assertEqual(len(BuyListLine.objects.get(pk=lines['11'].buyline_id).tried), 1)
        self.assertEqual(AuditLog.objects.filter(action='rpa_portal_basket_recorded').count(), 1)

    def test_record_order_rerun_after_commit_does_not_apply_twice(self):
        """A basket sent back through record_order (e.g. a person links it again) replays
        commit_order and never takes the quantities off the buy list a second time."""
        _, basket, lines = self.make_basket({'11': 4})
        hist = [{'sku': '11', 'qty': 3}]
        recording.record_order(basket, order_ref='PO-2', history_lines=hist, staff=self.buyer)
        PortalBasket.objects.filter(pk=basket.pk).update(status='submitted')
        recording.record_order(basket, order_ref='PO-2', history_lines=hist, staff=self.buyer)
        bl = BuyListLine.objects.get(pk=lines['11'].buyline_id)
        self.assertEqual(bl.remaining_qty, 1)
        self.assertEqual(len(bl.tried), 1)
        self.assertEqual(SupplyDecision.objects.filter(order_ref=f'portal-basket-{basket.pk}').count(), 1)

    def test_record_order_replay_with_other_quantities_refused(self):
        _, basket, _ = self.make_basket({'11': 4})
        recording.record_order(basket, order_ref='PO-3', history_lines=[{'sku': '11', 'qty': 3}],
                               staff=self.buyer)
        PortalBasket.objects.filter(pk=basket.pk).update(status='submitted')
        with self.assertRaises(recording.RecordError):
            recording.record_order(basket, order_ref='PO-3', history_lines=[{'sku': '11', 'qty': 4}],
                                   staff=self.buyer)

    def test_record_order_different_ref_on_recorded_409(self):
        _, basket, _ = self.make_basket({'11': 4})
        recording.record_order(basket, order_ref='PO-1', history_lines=[{'sku': '11', 'qty': 4}],
                               staff=self.buyer)
        with self.assertRaises(recording.RecordError) as cm:
            recording.record_order(basket, order_ref='PO-2', history_lines=[{'sku': '11', 'qty': 4}],
                                   staff=self.buyer)
        self.assertEqual(cm.exception.status_code, 409)
        basket.refresh_from_db()
        self.assertEqual(basket.status, 'needs_person')
        self.assertIn('PO-2', basket.needs_person_reason)
        self.assertEqual(basket.portal_ref, 'PO-1')        # the first record stands
        self.assertEqual(SupplyDecision.objects.filter(order_ref=f'portal-basket-{basket.pk}').count(), 1)

    def test_record_order_need_check_failure_keeps_ref_and_needs_person(self):
        _, basket, lines = self.make_basket({'11': 4}, reason='')    # no demand + no reason
        out = recording.record_order(basket, order_ref='PO-9', history_lines=[{'sku': '11', 'qty': 4}],
                                     staff=self.buyer)
        self.assertEqual(out.status, 'needs_person')
        self.assertTrue(out.needs_person_reason.startswith('need_check'))
        self.assertEqual((out.portal_ref, out.portal_key), ('PO-9', 'pharma_overseas:PO-9'))
        self.assertEqual(SupplyDecision.objects.count(), 0)
        self.assertEqual(BuyListLine.objects.get(pk=lines['11'].buyline_id).remaining_qty, 4)

    def test_record_order_empty_history_is_not_everything_removed(self):
        _, basket, lines = self.make_basket({'11': 4})
        with self.assertRaises(recording.RecordError):
            recording.record_order(basket, order_ref='PO-5', history_lines=[], staff=self.buyer)
        basket.refresh_from_db()
        self.assertEqual(basket.status, 'submitted')
        self.assertEqual(basket.portal_ref, '')
        self.assertEqual(SupplyDecision.objects.count(), 0)
        bl = BuyListLine.objects.get(pk=lines['11'].buyline_id)
        self.assertEqual((bl.remaining_qty, bl.tried, bl.chosen_supplier), (4, [], '565'))

    def _assert_held_for_a_person(self, out, lines, ref):
        """Nothing credited to the buy list, nothing handed back as a remainder, a person flagged."""
        self.assertEqual(out.status, 'needs_person')
        self.assertEqual(out.needs_person_reason, f'history_unmatched:{ref}')
        self.assertEqual((out.portal_ref, out.portal_key), (ref, f'pharma_overseas:{ref}'))
        for ln in lines.values():
            bl = BuyListLine.objects.get(pk=ln.buyline_id)
            self.assertEqual((bl.remaining_qty, bl.tried, bl.chosen_supplier), (ln.wanted_qty, [], '565'))
            self.assertEqual(PortalLine.objects.get(pk=ln.pk).status, 'ok')
        self.assertEqual(out.job.__class__.objects.get(pk=out.job_id).status, 'approved')
        self.assertTrue(AuditLog.objects.filter(action='rpa_portal_needs_person',
                                                new_data__needs_person_reason=out.needs_person_reason).exists())

    def test_record_order_added_sku_not_ordered_and_flagged(self):
        _, basket, lines = self.make_basket({'11': 4, '12': 3})
        out = recording.record_order(basket, order_ref='PO-6', history_lines=[
            {'sku': '11', 'qty': 4}, {'sku': '99', 'qty': 2}], staff=self.buyer)
        self.assertEqual(out.diff['added'], [{'sku': '99', 'qty': 2}])
        self.assertEqual([r['sku'] for r in out.diff['removed']], ['12'])
        self.assertEqual(SupplyDecision.objects.count(), 0)       # nothing recorded until reconciled
        self._assert_held_for_a_person(out, lines, 'PO-6')          # 12 is NOT released

    def test_record_order_no_history_sku_matches_holds_every_line(self):
        _, basket, lines = self.make_basket({'11': 4})
        out = recording.record_order(basket, order_ref='PO-14', history_lines=[{'sku': '77', 'qty': 4}],
                                     staff=self.buyer)
        self.assertEqual(out.diff['added'], [{'sku': '77', 'qty': 4}])
        self.assertEqual(SupplyDecision.objects.count(), 0)
        self._assert_held_for_a_person(out, lines, 'PO-14')

    def test_record_order_unreadable_history_qty_holds_the_line(self):
        _, basket, lines = self.make_basket({'11': 4, '12': 3})
        out = recording.record_order(basket, order_ref='PO-15', history_lines=[
            {'sku': '11', 'qty': '4.000'}, {'sku': '12', 'qty': '2.5'}], staff=self.buyer)
        self.assertEqual(out.diff['added'], [{'sku': '12', 'qty': '2.5'}])
        self._assert_held_for_a_person(out, lines, 'PO-15')
        _, basket2, lines2 = self.make_basket({'11': 4})
        out2 = recording.record_order(basket2, order_ref='PO-16', history_lines=[{'sku': '11', 'qty': 'four'}],
                                      staff=self.buyer)
        self.assertEqual(out2.diff['added'], [{'sku': '11', 'qty': 'four'}])
        self.assertEqual(SupplyDecision.objects.filter(order_ref=f'portal-basket-{basket2.pk}').count(), 0)
        self._assert_held_for_a_person(out2, lines2, 'PO-16')

    def test_unmatched_basket_reconciled_by_a_person_records_once(self):
        _, basket, lines = self.make_basket({'11': 4, '12': 3})
        recording.record_order(basket, order_ref='PO-17', history_lines=[
            {'sku': '11', 'qty': 4}, {'sku': '99', 'qty': 3}], staff=self.buyer)
        PortalBasket.objects.filter(pk=basket.pk).update(status='submitted')   # resolve(link_order)
        out = recording.record_order(basket, order_ref='PO-17', history_lines=[
            {'sku': '11', 'qty': 4}, {'sku': '12', 'qty': 3}], staff=self.buyer)
        self.assertEqual(out.status, 'recorded')
        key = f'portal-basket-{basket.pk}'
        self.assertEqual(sorted(SupplyDecision.objects.filter(order_ref=key).values_list('decided_qty', flat=True)),
                         [Decimal('3'), Decimal('4')])
        for ln in lines.values():
            self.assertEqual(BuyListLine.objects.get(pk=ln.buyline_id).remaining_qty, 0)

    def test_record_order_ref_already_on_another_basket_refused(self):
        _, first, _ = self.make_basket({'11': 4})
        recording.record_order(first, order_ref='PO-8', history_lines=[{'sku': '11', 'qty': 4}],
                               staff=self.buyer)
        _, second, _ = self.make_basket({'12': 4})
        with self.assertRaises(recording.RecordError):
            recording.record_order(second, order_ref='PO-8', history_lines=[{'sku': '12', 'qty': 4}],
                                   staff=self.buyer)
        self.assertFalse(SupplyDecision.objects.filter(order_ref=f'portal-basket-{second.pk}').exists())

    def test_record_order_only_from_submitted(self):
        _, basket, _ = self.make_basket({'11': 4}, status='awaiting_submit')
        with self.assertRaises(recording.RecordError):
            recording.record_order(basket, order_ref='PO-4', history_lines=[{'sku': '11', 'qty': 4}],
                                   staff=self.buyer)

    def test_last_basket_recorded_finishes_job_and_closes_list(self):
        job, basket, lines = self.make_basket({'11': 4}, extra_baskets=('cancelled',))
        recording.record_order(basket, order_ref='PO-10', history_lines=[{'sku': '11', 'qty': 4}],
                               staff=self.buyer)
        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        self.assertEqual(job.buylist.status, 'closed')
        self.assertFalse(BuyListLine.objects.get(pk=lines['11'].buyline_id).open_guard)

    def test_job_stays_approved_while_a_basket_is_open(self):
        job, basket, _ = self.make_basket({'11': 4}, extra_baskets=('ready',))
        recording.record_order(basket, order_ref='PO-11', history_lines=[{'sku': '11', 'qty': 4}],
                               staff=self.buyer)
        job.refresh_from_db()
        self.assertEqual(job.status, 'approved')

    def test_list_with_remainder_stays_open(self):
        job, basket, lines = self.make_basket({'11': 4})
        recording.record_order(basket, order_ref='PO-12', history_lines=[{'sku': '11', 'qty': 3}],
                               staff=self.buyer)
        job.refresh_from_db()
        self.assertEqual(job.status, 'done')
        self.assertEqual(job.buylist.status, 'open')
        self.assertTrue(BuyListLine.objects.get(pk=lines['11'].buyline_id).open_guard)

    def test_cancelling_last_basket_finishes_job(self):
        from apps.rpa.portal import queue
        from apps.users.models import RoleModuleAccess
        for action in ('view', 'edit'):
            RoleModuleAccess.objects.update_or_create(role='supervisor', module='rpa', action=action,
                                                      defaults={'is_allowed': True})
        _, boss, _ = make_user('prec_boss', role='supervisor', access_all=True)
        job, basket, _ = self.make_basket({'11': 4}, status='needs_person', extra_baskets=('recorded',))
        queue.resolve(basket, staff=boss, action='cancel')
        job.refresh_from_db()
        self.assertEqual(job.status, 'done')

    def test_record_order_unreadable_history_sku_goes_to_a_person(self):
        _, basket, _ = self.make_basket({'11': 4})
        out = recording.record_order(basket, order_ref='PO-13', history_lines=[
            {'sku': '11', 'qty': 4}, {'sku': 'AB-7', 'qty': 1}], staff=self.buyer)
        self.assertEqual(out.diff['added'], [{'sku': 'AB-7', 'qty': 1}])
        self.assertEqual(out.needs_person_reason, 'history_unmatched:PO-13')

    def test_queue_keeps_unreadable_history_qty(self):
        from apps.rpa.portal import queue
        self.assertEqual(queue._clean_history([{'sku': '11', 'qty': '4.000'}, {'sku': '12', 'qty': 2.5},
                                               {'sku': '13', 'qty': 'x'}]),
                         [{'sku': '11', 'qty': 4}, {'sku': '12', 'qty': '2.5'}, {'sku': '13', 'qty': 'x'}])
