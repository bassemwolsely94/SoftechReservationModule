"""Final-review fix wave (supplier-portal RPA Stage 1): a placed order never ends in a dead end that
only an unguarded cancel can leave, and nothing it may have ordered is ordered again silently.

C1  an order seen with no readable lines: retry refused, link needs lines (a person types them),
    cancel needs a confirmation + reason and then holds the buy lines for a person;
    a finished job still gets its stuck basket's Order History read.
I1  a retried handover (lost answer) is not a handover; a later Submit sighting is still taken in.
I2  an Order History read reports every order in its window; only an order that is not on another
    basket and shares a code with this one counts; confirm_none over a found order needs a reason.
I3  cancelling a job never overwrites a basket a robot just claimed.
I4  a linked basket stops needing a person; a recorded basket's reason is cleared by «acknowledge».
M-a pick / send-other take only known supplier codes; the Excel file name is safe.
M-b the approval audit carries the over-need reasons.
M-c the API keeps a buyer off another buyer's job and applies four-eyes.
"""
from decimal import Decimal
from unittest import mock

from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.config.models import SystemSetting
from apps.invoices.models import VendorProfile
from apps.rpa.models import (BuyList, BuyListLine, PortalBasket, PortalJob, PortalLine, PortalRun,
                             SupplierPortal)
from apps.rpa.portal import buylist as bl_service
from apps.rpa.portal import jobs, queue, recording, serializers
from apps.supply.models import SupplyDecision

from .test_rpa_portal_queue import HEADER, IDENTITY, ON, _World

ACC = {'identity_text': IDENTITY}


@override_settings(**ON)
class OrderSafetyTests(_World, TestCase):

    def setUp(self):
        self.build_world('POS')
        SupplierPortal.objects.filter(pk=self.portal.pk).update(live=True)
        self.portal.refresh_from_db()
        if not Branch.objects.filter(kind=Branch.KIND_HQ).exists():
            Branch.objects.create(softech_branch_id='100', name='HQ', kind=Branch.KIND_HQ)
        VendorProfile.objects.get_or_create(softech_personcode='565', defaults={'name': 'Pharma Overseas'})

    # ── helpers ──────────────────────────────────────────────────────────────────────────────

    def _awaiting(self, statuses=('ready',)):
        """A live basket handed over for Submit. Returns (job, basket, run, line)."""
        job, baskets = self.make_job(live=True, statuses=statuses)
        BuyListLine.objects.filter(buylist=job.buylist).update(reason='over need ok')
        run = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        b = PortalBasket.objects.get(pk=run.basket_id)
        ln = b.lines.get()
        b = queue.report(run, self.dev, {'outcome': 'handover', 'steps': [{'label': 'add_line'}],
                                         'lines': [{'line_id': ln.pk, 'accepted_qty': 4, 'status': 'ok'}],
                                         'account': ACC})
        self.assertEqual(b.status, 'awaiting_submit')
        return job, b, run, ln

    def _record_failed(self):
        job, b, run, ln = self._awaiting()
        b = queue.report(run, self.dev, {'outcome': 'submit_seen', 'order_ref': 'PO123',
                                         'history_lines': [], 'account': ACC})
        self.assertEqual((b.status, b.needs_person_reason, b.portal_ref), ('needs_person', 'record_failed:PO123', ''))
        self.assertIsNotNone(b.submitted_seen_at)
        return job, b, run, ln

    def _buyline(self, ln):
        return BuyListLine.objects.get(pk=PortalLine.objects.get(pk=ln.pk).buyline_id)

    # ── C1 ───────────────────────────────────────────────────────────────────────────────────

    def test_empty_history_cancel_needs_confirmation_and_holds_the_lines(self):
        job, b, run, ln = self._record_failed()
        with self.assertRaises(queue.QueueError):                        # retry: an order was seen
            queue.resolve(b, staff=self.boss, action='retry', confirm_none=True, reason='x')
        with self.assertRaises(recording.RecordError):                   # no lines to link with
            queue.resolve(b, staff=self.boss, action='link_order', order_ref='PO123')
        with self.assertRaises(queue.PlacedOrderCancel):                  # cancel: not without a word
            queue.resolve(b, staff=self.boss, action='cancel')
        with self.assertRaises(queue.PlacedOrderCancel):
            queue.resolve(b, staff=self.boss, action='cancel', confirm_placed_order_cancel=True)
        detail = serializers.basket_detail(PortalBasket.objects.get(pk=b.pk))
        self.assertTrue(detail['cancel_needs_confirmation'])
        self.assertEqual(detail['suggested_order_ref'], 'PO123')

        b = queue.resolve(b, staff=self.boss, action='cancel', confirm_placed_order_cancel=True,
                          reason='المورد ألغى الطلب بالتليفون')
        self.assertEqual(b.status, 'cancelled')
        line = self._buyline(ln)
        # the items are NOT orderable again by themselves: off the supplier, a note in `tried`
        self.assertEqual((line.remaining_qty, line.chosen_supplier), (4, ''))
        self.assertTrue(line.tried[-1]['may_have_ordered'])
        self.assertEqual(line.tried[-1]['portal_ref'], 'PO123')
        log = AuditLog.objects.filter(action='rpa_portal_resolved').latest('pk')
        self.assertEqual(log.new_data['held_buylines'], [line.pk])
        self.assertEqual(log.new_data['cancelled_portal_ref'], 'PO123')
        with self.assertRaises(jobs.JobError):                           # a new job does not take them
            jobs.create_job(line.buylist, portal=self.portal, account=self.account, staff=self.buyer)
        row = serializers.remainder_rows([line], {line.item_id: ['565', '30']})[0]
        self.assertTrue(row['may_have_ordered'])
        self.assertEqual(row['next_supplier'], '')                       # no one-key reorder

    def test_live_basket_stuck_before_history_cancel_needs_confirmation(self):
        job, baskets = self.make_job(live=True)
        run = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        b = queue.report(run, self.dev, {'outcome': 'timeout', 'account': ACC})
        self.assertTrue(queue.may_have_placed(b))
        with self.assertRaises(queue.PlacedOrderCancel):
            queue.resolve(b, staff=self.boss, action='cancel')
        # an Order History read that found nothing clears it: a plain cancel then
        hrun = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        queue.report(hrun, self.dev, {'outcome': 'history_none', 'account': ACC})
        b = queue.resolve(PortalBasket.objects.get(pk=b.pk), staff=self.boss, action='cancel')
        self.assertEqual(b.status, 'cancelled')
        self.assertEqual(self._buyline(b.lines.get()).chosen_supplier, '565')

    def test_link_with_person_lines_records_and_clears_the_reason(self):
        job, b, run, ln = self._record_failed()
        with self.assertRaises(queue.QueueError):                        # whole packs only
            queue.resolve(b, staff=self.boss, action='link_order', order_ref='PO123',
                          history_lines=[{'sku': ln.supplier_key, 'qty': '2.5'}])
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='link_order', order_ref='PO123',
                          history_lines=[{'sku': 'AB', 'qty': 2}])
        b = queue.resolve(b, staff=self.boss, action='link_order', order_ref='PO123',
                          history_lines=[{'sku': ln.supplier_key, 'qty': 3}])
        self.assertEqual((b.status, b.portal_ref, b.needs_person_reason), ('recorded', 'PO123', ''))
        self.assertFalse(queue.needs_person(b))
        self.assertEqual(SupplyDecision.objects.get(order_ref=f'portal-basket-{b.pk}').decided_qty, Decimal('3'))
        line = self._buyline(ln)
        self.assertEqual(line.remaining_qty, 1)                           # the rest is a remainder
        log = AuditLog.objects.filter(action='rpa_portal_resolved').latest('pk')
        self.assertEqual(log.old_data['needs_person_reason'], 'record_failed:PO123')
        self.assertEqual(log.new_data['history_lines'], [{'sku': ln.supplier_key, 'qty': 3}])

    def test_history_unmatched_is_reconciled_with_person_lines(self):
        job, b, run, ln = self._awaiting()
        b = queue.report(run, self.dev, {'outcome': 'submit_seen', 'order_ref': 'PO5', 'account': ACC,
                                         'history_lines': [{'sku': ln.supplier_key, 'qty': 4},
                                                           {'sku': '99999', 'qty': 1}]})
        self.assertEqual(b.needs_person_reason, 'history_unmatched:PO5')
        detail = serializers.basket_detail(b)
        self.assertEqual(detail['suggested_order_ref'], 'PO5')
        self.assertEqual(detail['history_orders'][0]['order_ref'], 'PO5')       # the editor's prefill
        self.assertEqual(len(detail['history_orders'][0]['lines']), 2)
        b = queue.resolve(b, staff=self.boss, action='link_order', order_ref='PO5',
                          history_lines=[{'sku': ln.supplier_key, 'qty': 4}])
        self.assertEqual((b.status, b.needs_person_reason), ('recorded', ''))
        self.assertEqual(self._buyline(ln).remaining_qty, 0)

    def test_cancelled_basket_linked_later_is_credited_once(self):
        job, b, run, ln = self._record_failed()
        queue.resolve(b, staff=self.boss, action='cancel', confirm_placed_order_cancel=True, reason='x')
        self.assertEqual(PortalJob.objects.get(pk=job.pk).status, 'done')
        # the order shows up after all: a late sighting pulls the basket of the done job back
        b = queue.report(PortalRun.objects.get(pk=run.pk), self.dev,
                         {'outcome': 'submit_seen', 'order_ref': 'PO124', 'account': ACC})
        self.assertEqual(b.status, 'needs_person')
        # and its Order History read is still handed out, although the job is done
        claim = queue.claim_next(self.dev)
        self.assertEqual(claim['plan']['kind'], 'history')
        queue.report(PortalRun.objects.get(pk=claim['run_id']), self.dev,
                     {'outcome': 'history_found', 'account': ACC,
                      'orders': [{'order_ref': 'PO124', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]}]})
        b = queue.resolve(PortalBasket.objects.get(pk=b.pk), staff=self.boss, action='link_order', order_ref='PO124')
        self.assertEqual(b.status, 'recorded')
        line = self._buyline(ln)
        self.assertEqual(line.remaining_qty, 0)
        self.assertEqual(SupplyDecision.objects.filter(order_ref=f'portal-basket-{b.pk}').count(), 1)

    # ── I1 ───────────────────────────────────────────────────────────────────────────────────

    def test_retried_handover_is_not_a_handover_and_late_sighting_is_taken(self):
        job, b, run, ln = self._awaiting()
        api = APIClient()
        api.credentials(**{HEADER: self.secret})
        payload = {'outcome': 'handover', 'steps': [{'label': 'add_line'}], 'account': ACC,
                   'lines': [{'line_id': ln.pk, 'accepted_qty': 4, 'status': 'ok'}]}
        r = api.post(f'/api/rpa/agent/portal/runs/{run.pk}/report/', payload, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertNotEqual(r.json()['status'], 'awaiting_submit')          # the robot says no Submit
        self.assertEqual(PortalBasket.objects.get(pk=b.pk).needs_person_reason, 'handover_twice')
        r = api.post(f'/api/rpa/agent/portal/runs/{run.pk}/report/',
                     {'outcome': 'submit_seen', 'order_ref': 'PO9', 'account': ACC,
                      'history_lines': [{'sku': ln.supplier_key, 'qty': 4}]}, format='json')
        self.assertEqual(r.status_code, 200, r.content)                     # never a 409
        b = PortalBasket.objects.get(pk=b.pk)
        self.assertIsNotNone(b.submitted_seen_at)
        self.assertIn('submit_seen:PO9', b.needs_person_reason)
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry', confirm_none=True, reason='x')

    def test_late_sighting_after_operator_stop_is_taken(self):
        job, b, run, ln = self._awaiting()
        b = queue.report(run, self.dev, {'outcome': 'stopped_by_operator', 'account': ACC})
        self.assertEqual(b.status, 'needs_person')
        b = queue.report(PortalRun.objects.get(pk=run.pk), self.dev,
                         {'outcome': 'submit_seen', 'order_ref': 'PO10', 'account': ACC})
        self.assertIsNotNone(b.submitted_seen_at)
        self.assertIn('submit_seen:PO10', b.needs_person_reason)

    def test_late_sighting_on_recorded_basket(self):
        job, b, run, ln = self._awaiting()
        b = queue.report(run, self.dev, {'outcome': 'submit_seen', 'order_ref': 'PO11', 'account': ACC,
                                         'history_lines': [{'sku': ln.supplier_key, 'qty': 4}]})
        self.assertEqual(b.status, 'recorded')
        run.refresh_from_db()
        # the same sighting again (a lost answer, retried): nothing changes
        b = queue.report(run, self.dev, {'outcome': 'submit_seen', 'order_ref': 'PO11', 'account': ACC})
        self.assertEqual((b.status, b.needs_person_reason), ('recorded', ''))
        # another order number: a second order may exist - a person looks
        b = queue.report(run, self.dev, {'outcome': 'submit_seen', 'order_ref': 'PO12', 'account': ACC})
        self.assertEqual((b.status, b.needs_person_reason), ('recorded', 'submit_seen:PO12'))
        self.assertTrue(queue.needs_person(b))
        # I4: acknowledge clears it, with a written reason, audited
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='acknowledge')
        with self.assertRaises(PermissionDenied):
            queue.resolve(b, staff=self.buyer, action='acknowledge', reason='checked')
        b = queue.resolve(b, staff=self.boss, action='acknowledge', reason='PO12 = طلب يدوي آخر')
        self.assertFalse(queue.needs_person(b))
        log = AuditLog.objects.filter(action='rpa_portal_resolved').latest('pk')
        self.assertEqual((log.old_data['needs_person_reason'], log.new_data['action']), ('submit_seen:PO12', 'acknowledge'))
        with self.assertRaises(queue.QueueError):                         # nothing left to acknowledge
            queue.resolve(b, staff=self.boss, action='acknowledge', reason='again')

    # ── I2 ───────────────────────────────────────────────────────────────────────────────────

    def _stuck_live(self):
        """A live basket whose lease ran out at Submit; its Order History read claimed."""
        job, b, run, ln = self._awaiting()
        PortalBasket.objects.filter(pk=b.pk).update(lease_until=run.started_at)
        queue.expire_leases()
        hrun = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        self.assertEqual(hrun.kind, 'history')
        return PortalBasket.objects.get(pk=b.pk), hrun, ln

    def test_history_with_several_orders_picks_only_this_baskets(self):
        b, hrun, ln = self._stuck_live()
        PortalBasket.objects.create(job=b.job, seq=9, status='recorded', portal_ref='PO-A',
                                    portal_key=f'{self.portal.key}:PO-A')
        orders = [{'order_ref': 'PO-A', 'date': '2026-11-18', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]},
                  {'order_ref': 'PO-X', 'date': '2026-11-18', 'lines': [{'sku': '77777', 'qty': 2}]},
                  {'order_ref': 'PO-B', 'date': '2026-11-18', 'lines': [{'sku': ln.supplier_key, 'qty': 3}]}]
        queue.report(hrun, self.dev, {'outcome': 'history_found', 'account': ACC, 'orders': orders,
                                      'order_ref': 'PO-A'})       # an old robot's guess is ignored
        b = PortalBasket.objects.get(pk=b.pk)
        self.assertEqual(b.needs_person_reason, 'history_found:PO-B')
        self.assertEqual(queue.suggested_order_ref(b), 'PO-B')
        self.assertEqual(queue._history_lines_for(b, 'PO-B'), [{'sku': ln.supplier_key, 'qty': 3}])
        # confirm_none over a found order needs a written reason (audited)
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry', confirm_none=True)
        b = queue.resolve(b, staff=self.boss, action='retry', confirm_none=True,
                          reason='PO-B طلب الفرع يدوياً، ليس لهذه السلة')
        self.assertEqual(b.status, 'ready')
        log = AuditLog.objects.filter(action='rpa_portal_resolved').latest('pk')
        self.assertTrue(log.new_data['confirmed_no_order'])
        self.assertIn('PO-B', log.new_data['reason'])

    def test_history_with_only_other_baskets_orders_is_none(self):
        b, hrun, ln = self._stuck_live()
        PortalBasket.objects.create(job=b.job, seq=9, status='recorded', portal_ref='PO-A',
                                    portal_key=f'{self.portal.key}:PO-A')
        orders = [{'order_ref': 'PO-A', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]},
                  {'order_ref': 'PO-X', 'lines': [{'sku': '77777', 'qty': 2}]}]
        queue.report(hrun, self.dev, {'outcome': 'history_found', 'account': ACC, 'orders': orders})
        self.assertEqual(PortalRun.objects.get(pk=hrun.pk).outcome, 'history_none')
        b = queue.resolve(PortalBasket.objects.get(pk=b.pk), staff=self.boss, action='retry')
        self.assertEqual(b.status, 'ready')

    def test_history_order_with_unreadable_row_counts_as_found(self):
        b, hrun, ln = self._stuck_live()
        orders = [{'order_ref': 'PO-Y', 'lines': [{'sku': '77777', 'qty': 2}, {'sku': '', 'qty': 'more rows'}]},
                  {'order_ref': 'PO-Z', 'lines': []}]
        queue.report(hrun, self.dev, {'outcome': 'history_found', 'account': ACC, 'orders': orders})
        b = PortalBasket.objects.get(pk=b.pk)
        self.assertEqual(b.needs_person_reason, 'history_found:PO-Y,PO-Z')
        self.assertEqual(queue.suggested_order_ref(b), '')                 # several: a person picks
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry')

    def test_history_old_shape_still_read(self):
        b, hrun, ln = self._stuck_live()
        queue.report(hrun, self.dev, {'outcome': 'history_found', 'account': ACC, 'order_ref': 'PO-OLD',
                                      'history_lines': [{'sku': ln.supplier_key, 'qty': 4}]})
        self.assertEqual(PortalBasket.objects.get(pk=b.pk).needs_person_reason, 'history_found:PO-OLD')

    # ── I3 ───────────────────────────────────────────────────────────────────────────────────

    def test_cancel_job_never_overwrites_a_claimed_basket(self):
        job, (b,) = self.make_job(live=False)
        stale = list(PortalBasket.objects.filter(job=job))                  # read as 'ready'

        def claim_in_between(j):
            self.assertIsNotNone(queue.claim_next(self.dev))               # a robot claims it now
            return stale
        with mock.patch('apps.rpa.portal.jobs._lock_baskets', side_effect=claim_in_between):
            with self.assertRaises(jobs.JobError):
                jobs.cancel_job(job, staff=self.buyer, reason='x')
        # nothing was cancelled (the claim, made inside this test's transaction, rolled back with it)
        self.assertNotEqual(PortalBasket.objects.get(pk=b.pk).status, 'cancelled')
        self.assertEqual(PortalJob.objects.get(pk=job.pk).status, 'approved')

    def test_cancel_job_cancels_waiting_baskets(self):
        job, baskets = self.make_job(statuses=('ready', 'pending'))
        jobs.cancel_job(job, staff=self.buyer, reason='x')
        self.assertEqual(set(PortalBasket.objects.filter(job=job).values_list('status', flat=True)), {'cancelled'})


class SupplierCodeTests(TestCase):
    """M-a: only known supplier codes are picked or sent; the Excel name never breaks the answer."""

    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.users.models import RoleModuleAccess
        from .factories import make_user
        for action in ('view', 'create'):
            RoleModuleAccess.objects.update_or_create(role='purchasing', module='rpa', action=action,
                                                      defaults={'is_allowed': True})
        cls.hq = Branch.objects.filter(kind=Branch.KIND_HQ).first() or Branch.objects.create(
            softech_branch_id='100', name='HQ', kind=Branch.KIND_HQ)
        _, cls.buyer, cls.buyer_c = make_user('psc_buyer', role='purchasing', branch=cls.hq, access_all=True)
        cls.item = Item.objects.create(softech_id='PSC1', name='ITEM PSC', is_active=True)

    def _line(self, supplier):
        b = BuyList.objects.create(source_kind='upload', created_by=self.buyer)
        return b, BuyListLine.objects.create(buylist=b, seq=1, item=self.item, needed_qty=2, remaining_qty=2,
                                             chosen_supplier=supplier, source_key=f'psc:{b.pk}')

    def test_pick_refuses_unknown_supplier(self):
        _, line = self._line('')
        with self.assertRaises(bl_service.BuyListError):
            bl_service.pick(line, 'NOPE', staff=self.buyer)
        r = self.buyer_c.post(f'/api/rpa/portal/buylists/{line.buylist_id}/pick/',
                             {'line_id': line.pk, 'supplier': 'x"\n'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(BuyListLine.objects.get(pk=line.pk).chosen_supplier, '')

    def test_send_other_refuses_unknown_supplier_before_recording(self):
        b, _ = self._line('NOPE')
        with self.assertRaises(bl_service.BuyListError):
            bl_service.send_other(b, 'NOPE', staff=self.buyer)
        self.assertFalse(SupplyDecision.objects.exists())

    def test_xlsx_name_is_safe_for_odd_codes(self):
        VendorProfile.objects.create(name='odd', softech_personcode='3"0;x')
        b, _ = self._line('3"0;x')
        r = self.buyer_c.post(f'/api/rpa/portal/buylists/{b.pk}/send-other/?format=xlsx',
                              {'supplier': '3"0;x'}, format='json')
        self.assertEqual(r.status_code, 200, r.content[:300])
        self.assertEqual(r['Content-Disposition'], f'attachment; filename="order-30x-{b.pk}.xlsx"')


class JobApiTests(TestCase):
    """M-b / M-c: the approval audit says why; a buyer cannot touch another buyer's job; four-eyes
    through the API."""

    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.rpa.models import PortalAccount
        from apps.users.models import RoleModuleAccess
        from .factories import make_user
        for role, actions in (('purchasing', ('view', 'create')), ('supervisor', ('view', 'create', 'approve'))):
            for action in actions:
                RoleModuleAccess.objects.update_or_create(role=role, module='rpa', action=action,
                                                          defaults={'is_allowed': True})
        cls.hq = Branch.objects.filter(kind=Branch.KIND_HQ).first() or Branch.objects.create(
            softech_branch_id='100', name='HQ', kind=Branch.KIND_HQ)
        _, cls.buyer, cls.buyer_c = make_user('pja_buyer', role='purchasing', branch=cls.hq, access_all=True)
        _, cls.buyer2, cls.buyer2_c = make_user('pja_buyer2', role='purchasing', branch=cls.hq, access_all=True)
        _, cls.boss, cls.boss_c = make_user('pja_boss', role='supervisor', branch=cls.hq, access_all=True)
        cls.portal, _ = SupplierPortal.objects.get_or_create(key='pharma_overseas', defaults={'supplier_code': '565'})
        cls.account = PortalAccount.objects.create(portal=cls.portal, label='main', identity_text='HQ 565')
        VendorProfile.objects.get_or_create(softech_personcode='565', defaults={'name': 'PO'})
        cls.items = [Item.objects.create(softech_id=f'PJA{n}', name=f'ITEM {n}', is_active=True,
                                         pack_price=Decimal('10')) for n in range(2)]

    def _job(self):
        b = BuyList.objects.create(source_kind='upload', created_by=self.buyer)
        for n, item in enumerate(self.items, start=1):
            BuyListLine.objects.create(buylist=b, seq=n, item=item, needed_qty=3, remaining_qty=3,
                                       chosen_supplier='565', source_key=f'pja:{b.pk}:{n}')
        return jobs.create_job(b, portal=self.portal, account=self.account, staff=self.buyer)

    @staticmethod
    def _preview(exceed=()):
        def fn(lines, **kw):
            return {'lines': [{'item_id': ln['item_id'], 'qty': ln['qty'], 'exceeds_need': ln['item_id'] in exceed}
                              for ln in lines]}
        return fn

    def test_other_buyer_gets_404_on_approve_and_cancel(self):
        job = self._job()
        with mock.patch('apps.supply.execution.preview_order', self._preview()):
            r = self.buyer2_c.post(f'/api/rpa/portal/jobs/{job.pk}/approve/', {'reasons': {}}, format='json')
        self.assertEqual(r.status_code, 404)
        r = self.buyer2_c.post(f'/api/rpa/portal/jobs/{job.pk}/cancel/', {'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 404)
        self.assertEqual(PortalJob.objects.get(pk=job.pk).status, 'draft')

    def test_four_eyes_through_the_api(self):
        SystemSetting.objects.update_or_create(key='portal_four_eyes_above', defaults={'value': '1'})
        job = self._job()
        with mock.patch('apps.supply.execution.preview_order', self._preview()), \
                mock.patch('apps.supply.comparison.purchase_history', return_value={}):
            r = self.buyer_c.post(f'/api/rpa/portal/jobs/{job.pk}/approve/', {'reasons': {}}, format='json')
            self.assertEqual(r.status_code, 403, r.content)
            self.assertEqual(PortalJob.objects.get(pk=job.pk).status, 'draft')
            r = self.boss_c.post(f'/api/rpa/portal/jobs/{job.pk}/approve/', {'reasons': {}}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(PortalJob.objects.get(pk=job.pk).approved_by_id, self.boss.pk)

    def test_approval_audit_carries_over_need_reasons(self):
        job = self._job()
        first = job.buylist.lines.order_by('seq').first()
        with mock.patch('apps.supply.execution.preview_order', self._preview(exceed={first.item_id})), \
                mock.patch('apps.supply.comparison.purchase_history', return_value={}):
            jobs.approve_job(job, staff=self.buyer, reasons={first.pk: 'عرض بونص'})
        log = AuditLog.objects.filter(action='rpa_portal_job_approved').latest('pk')
        self.assertEqual(log.extra['over_need_reasons'], {str(first.pk): 'عرض بونص'})
        self.assertEqual(Decimal(log.extra['estimated_value']), Decimal('60'))
