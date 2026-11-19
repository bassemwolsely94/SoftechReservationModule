"""Supplier-portal robot pre-live gates (PR 171 follow-up): an Order History read says
"history_none" (no order, the basket may be retried) only when it is SURE. Every doubt is a
'history_unclear' read: the basket stays with a person and is not retried on its say-so.

R17  an order in the window that is not on another basket and shares no code with this basket
     makes the read unclear (a person confirms it is not this basket's), never none.
R19  a late Submit sighting on a basket that was cancelled without holding its lines (job done)
     holds those lines again (off the supplier, a «may have ordered» note) and sends it to a person.
R20  a read that hit the cap (the robot says truncated, or cap-many orders came) is unclear.
R21  a read without a positive "complete" proof (paging not confirmed on the site) is unclear.
"""
from django.test import TestCase, override_settings

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.invoices.models import VendorProfile
from apps.rpa.models import BuyListLine, PortalBasket, PortalJob, PortalLine, PortalRun, SupplierPortal
from apps.rpa.portal import jobs, queue, serializers

from .test_rpa_portal_queue import IDENTITY, ON, _World

ACC = {'identity_text': IDENTITY}


@override_settings(**ON)
class PreLiveGateTests(_World, TestCase):

    def setUp(self):
        self.build_world('PLG')
        SupplierPortal.objects.filter(pk=self.portal.pk).update(live=True)
        self.portal.refresh_from_db()
        if not Branch.objects.filter(kind=Branch.KIND_HQ).exists():
            Branch.objects.create(softech_branch_id='100', name='HQ', kind=Branch.KIND_HQ)
        VendorProfile.objects.get_or_create(softech_personcode='565', defaults={'name': 'Pharma Overseas'})

    # ── helpers ──────────────────────────────────────────────────────────────────────────────

    def _awaiting(self):
        job, baskets = self.make_job(live=True)
        BuyListLine.objects.filter(buylist=job.buylist).update(reason='over need ok')
        run = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        b = PortalBasket.objects.get(pk=run.basket_id)
        ln = b.lines.get()
        b = queue.report(run, self.dev, {'outcome': 'handover', 'steps': [{'label': 'add_line'}],
                                         'lines': [{'line_id': ln.pk, 'accepted_qty': 4, 'status': 'ok'}],
                                         'account': ACC})
        self.assertEqual(b.status, 'awaiting_submit')
        return job, b, run, ln

    def _stuck_live(self):
        """A live basket whose lease ran out at Submit; its Order History read claimed."""
        job, b, run, ln = self._awaiting()
        PortalBasket.objects.filter(pk=b.pk).update(lease_until=run.started_at)
        queue.expire_leases()
        hrun = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        self.assertEqual(hrun.kind, 'history')
        return PortalBasket.objects.get(pk=b.pk), hrun, ln, run

    def _taken(self, b, ref, seq=9):
        PortalBasket.objects.create(job=b.job, seq=seq, status='recorded', portal_ref=ref,
                                    portal_key=f'{self.portal.key}:{ref}')

    def _read(self, hrun, **payload):
        payload.setdefault('account', ACC)
        queue.report(hrun, self.dev, payload)
        return PortalRun.objects.get(pk=hrun.pk), PortalBasket.objects.get(pk=hrun.basket_id)

    def _assert_unclear(self, hrun, b, doubt):
        self.assertEqual(hrun.outcome, 'history_unclear')
        self.assertEqual(b.status, 'needs_person')
        self.assertTrue(b.needs_person_reason.startswith('history_unclear'), b.needs_person_reason)
        self.assertIn(doubt, b.needs_person_reason)
        self.assertIn(doubt, hrun.steps[-1]['doubts'])
        # never permission to retry, and no order number is suggested from it
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry')
        self.assertEqual(queue.suggested_order_ref(b), '')
        self.assertTrue(queue.may_have_placed(b))
        log = AuditLog.objects.filter(action='rpa_portal_needs_person').latest('pk')
        self.assertEqual(log.new_data['run_id'], hrun.pk)
        self.assertEqual(log.new_data['needs_person_reason'], b.needs_person_reason)

    # ── a sure "none" still clears ───────────────────────────────────────────────────────────

    def test_complete_read_with_no_orders_is_none(self):
        b, hrun, ln, _ = self._stuck_live()
        hrun, b = self._read(hrun, outcome='history_none', complete=True, truncated=False)
        self.assertEqual(hrun.outcome, 'history_none')
        self.assertEqual(queue.resolve(b, staff=self.boss, action='retry').status, 'ready')

    def test_complete_read_with_only_other_baskets_orders_is_none(self):
        b, hrun, ln, _ = self._stuck_live()
        self._taken(b, 'PO-A')
        orders = [{'order_ref': 'PO-A', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]}]
        hrun, b = self._read(hrun, outcome='history_found', orders=orders, complete=True)
        self.assertEqual(hrun.outcome, 'history_none')
        self.assertEqual(queue.resolve(b, staff=self.boss, action='retry').status, 'ready')

    # ── R17 ──────────────────────────────────────────────────────────────────────────────────

    def test_r17_unowned_order_without_shared_code_is_unclear(self):
        b, hrun, ln, _ = self._stuck_live()
        self._taken(b, 'PO-A')
        orders = [{'order_ref': 'PO-A', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]},
                  {'order_ref': 'PO-X', 'lines': [{'sku': '77777', 'qty': 2}]}]
        hrun, b = self._read(hrun, outcome='history_found', orders=orders, complete=True)
        self._assert_unclear(hrun, b, 'other_orders')
        self.assertEqual(hrun.steps[-1]['unclear'], ['PO-X'])
        self.assertEqual(hrun.steps[-1]['matched'], [])

    def test_r17_unclear_is_settled_and_confirm_none_needs_a_reason(self):
        b, hrun, ln, _ = self._stuck_live()
        orders = [{'order_ref': 'PO-X', 'lines': [{'sku': '77777', 'qty': 2}]}]
        hrun, b = self._read(hrun, outcome='history_found', orders=orders, complete=True)
        self.assertEqual(hrun.outcome, 'history_unclear')
        self.assertEqual(queue.daily_history_check(), 0)        # settled: a person decides now
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry', confirm_none=True)
        b = queue.resolve(b, staff=self.boss, action='retry', confirm_none=True,
                          reason='PO-X طلب يدوي من الفرع، ليس لهذه السلة')
        self.assertEqual(b.status, 'ready')
        log = AuditLog.objects.filter(action='rpa_portal_resolved').latest('pk')
        self.assertTrue(log.new_data['confirmed_no_order'])

    def test_r17_cancel_after_unclear_needs_confirmation_and_holds_lines(self):
        b, hrun, ln, _ = self._stuck_live()
        hrun, b = self._read(hrun, outcome='history_found', complete=True,
                             orders=[{'order_ref': 'PO-X', 'lines': [{'sku': '77777', 'qty': 2}]}])
        with self.assertRaises(queue.PlacedOrderCancel):
            queue.resolve(b, staff=self.boss, action='cancel')
        b = queue.resolve(b, staff=self.boss, action='cancel', confirm_placed_order_cancel=True, reason='x')
        line = BuyListLine.objects.get(pk=PortalLine.objects.get(pk=ln.pk).buyline_id)
        self.assertEqual(line.chosen_supplier, '')
        self.assertTrue(line.tried[-1]['may_have_ordered'])

    def test_r17_a_later_complete_none_read_clears_the_unclear_one(self):
        b, hrun, ln, _ = self._stuck_live()
        hrun, b = self._read(hrun, outcome='history_found', complete=True,
                             orders=[{'order_ref': 'PO-X', 'lines': [{'sku': '77777', 'qty': 2}]}])
        self.assertEqual(hrun.outcome, 'history_unclear')
        # a person records PO-X on the basket it belongs to, then asks for a fresh read
        self._taken(b, 'PO-X')
        queue.request_history(b)
        hrun2 = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        hrun2, b = self._read(hrun2, outcome='history_found', complete=True,
                              orders=[{'order_ref': 'PO-X', 'lines': [{'sku': '77777', 'qty': 2}]}])
        self.assertEqual(hrun2.outcome, 'history_none')
        self.assertEqual(queue.resolve(b, staff=self.boss, action='retry').status, 'ready')

    # ── R20 ──────────────────────────────────────────────────────────────────────────────────

    def test_r20_truncated_read_is_unclear(self):
        b, hrun, ln, _ = self._stuck_live()
        self._taken(b, 'PO-A')
        hrun, b = self._read(hrun, outcome='history_found', complete=True, truncated=True,
                             orders=[{'order_ref': 'PO-A', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]}])
        self._assert_unclear(hrun, b, 'truncated')

    def test_r20_cap_many_orders_is_unclear(self):
        b, hrun, ln, _ = self._stuck_live()
        orders = []
        for n in range(queue.MAX_HISTORY_ORDERS):
            ref = f'PO-{n:03d}'
            self._taken(b, ref, seq=100 + n)
            orders.append({'order_ref': ref, 'lines': [{'sku': '77777', 'qty': 1}]})
        hrun, b = self._read(hrun, outcome='history_found', complete=True, truncated=False, orders=orders)
        self._assert_unclear(hrun, b, 'truncated')

    def test_r20_a_found_order_still_wins_over_truncation(self):
        b, hrun, ln, _ = self._stuck_live()
        hrun, b = self._read(hrun, outcome='history_found', complete=True, truncated=True,
                             orders=[{'order_ref': 'PO-B', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]}])
        self.assertEqual((hrun.outcome, b.needs_person_reason), ('history_found', 'history_found:PO-B'))

    # ── R21 ──────────────────────────────────────────────────────────────────────────────────

    def test_r21_none_without_a_complete_proof_is_unclear(self):
        b, hrun, ln, _ = self._stuck_live()
        hrun, b = self._read(hrun, outcome='history_none')
        self._assert_unclear(hrun, b, 'not_complete')

    def test_r21_complete_must_be_true_itself(self):
        for proof in ('yes', 1, 'true', None):
            b, hrun, ln, _ = self._stuck_live()
            hrun, b = self._read(hrun, outcome='history_none', complete=proof)
            self.assertEqual(hrun.outcome, 'history_unclear', proof)

    def test_r21_robot_reported_unclear_is_unclear(self):
        b, hrun, ln, _ = self._stuck_live()
        hrun, b = self._read(hrun, outcome='history_unclear', complete=False, truncated=False)
        self._assert_unclear(hrun, b, 'not_complete')

    # ── R19 ──────────────────────────────────────────────────────────────────────────────────

    def test_r19_late_sighting_on_a_cancelled_unheld_basket_holds_its_lines(self):
        b, hrun, ln, run = self._stuck_live()
        self._read(hrun, outcome='history_none', complete=True)
        b = queue.resolve(PortalBasket.objects.get(pk=b.pk), staff=self.boss, action='cancel')
        line = BuyListLine.objects.get(pk=PortalLine.objects.get(pk=ln.pk).buyline_id)
        self.assertEqual((b.status, line.chosen_supplier), ('cancelled', '565'))     # not held
        self.assertEqual(PortalJob.objects.get(pk=b.job_id).status, 'done')
        # the order shows up after all
        b = queue.report(PortalRun.objects.get(pk=run.pk), self.dev,
                         {'outcome': 'submit_seen', 'order_ref': 'PO777', 'account': ACC})
        self.assertEqual(b.status, 'needs_person')
        self.assertIn('submit_seen:PO777', b.needs_person_reason)
        line.refresh_from_db()
        self.assertEqual((line.remaining_qty, line.chosen_supplier), (4, ''))
        note = line.tried[-1]
        self.assertEqual((note['basket'], note['may_have_ordered'], note['portal_ref']), (b.pk, True, 'PO777'))
        log = AuditLog.objects.filter(action='rpa_portal_needs_person', new_data__has_key='held_buylines').latest('pk')
        self.assertEqual(log.new_data['held_buylines'], [line.pk])
        self.assertEqual(log.old_data['chosen_supplier'], {str(line.pk): '565'})
        # nothing orders them again by itself
        with self.assertRaises(jobs.JobError):
            jobs.create_job(line.buylist, portal=self.portal, account=self.account, staff=self.buyer)
        row = serializers.remainder_rows([line], {line.item_id: ['565', '30']})[0]
        self.assertEqual((row['may_have_ordered'], row['next_supplier']), (True, ''))
        # a person cancels it again (confirmed): the lines are not noted twice
        b = queue.resolve(b, staff=self.boss, action='cancel', confirm_placed_order_cancel=True, reason='x')
        line.refresh_from_db()
        self.assertEqual(sum(1 for t in line.tried if t.get('basket') == b.pk and t.get('may_have_ordered')), 1)

    def test_r19_late_sighting_on_an_already_held_basket_changes_no_line(self):
        b, hrun, ln, run = self._stuck_live()
        b = queue.resolve(b, staff=self.boss, action='cancel', confirm_placed_order_cancel=True, reason='x')
        line = BuyListLine.objects.get(pk=PortalLine.objects.get(pk=ln.pk).buyline_id)
        tried = list(line.tried)
        queue.report(PortalRun.objects.get(pk=run.pk), self.dev,
                     {'outcome': 'submit_seen', 'order_ref': 'PO778', 'account': ACC})
        line.refresh_from_db()
        self.assertEqual(line.tried, tried)
