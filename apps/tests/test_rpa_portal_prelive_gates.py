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
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.branches.models import Branch
from apps.invoices.models import VendorProfile
from apps.rpa.models import BuyListLine, PortalBasket, PortalJob, PortalLine, PortalRun, SupplierPortal
from apps.rpa.portal import jobs, queue, serializers

from .test_rpa_portal_queue import IDENTITY, ON, _World

ACC = {'identity_text': IDENTITY}


class _GateWorld(_World):

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


@override_settings(**ON)
class PreLiveGateTests(_GateWorld, TestCase):

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


@override_settings(**ON)
class PreLiveGateReviewTests(_GateWorld, TestCase):
    """Review follow-ups: R19 reaches newer baskets of the same lines, unreadable order rows, a read
    that comes back after a person acted, doubts kept on found reads."""

    def _cancelled_plain(self):
        """A live basket stuck at Submit, cleared by a sure read and cancelled without a hold."""
        b, hrun, ln, run = self._stuck_live()
        self._read(hrun, outcome='history_none', complete=True)
        b = queue.resolve(PortalBasket.objects.get(pk=b.pk), staff=self.boss, action='cancel')
        line = BuyListLine.objects.get(pk=PortalLine.objects.get(pk=ln.pk).buyline_id)
        self.assertEqual((b.status, line.chosen_supplier), ('cancelled', '565'))
        return b, ln, run, line

    def _new_job_on(self, line, statuses):
        """A newer approved job at the same portal that took `line` again."""
        job = PortalJob.objects.create(portal=self.portal, account=self.account, buylist=line.buylist,
                                       status='approved', dry_run=False, created_by=self.buyer,
                                       approved_by=self.buyer, approved_at=timezone.now())
        out = []
        for n, st in enumerate(statuses, start=1):
            nb = PortalBasket.objects.create(job=job, seq=n, status=st)
            PortalLine.objects.create(basket=nb, buyline=line, item=line.item, wanted_qty=4,
                                      supplier_key='52871', supplier_key_padded='52871'.zfill(18))
            out.append(nb)
        return out

    # ── 1. R19 reaches newer baskets of the same lines ───────────────────────────────────────

    def test_r19_late_sighting_pulls_newer_baskets_of_the_same_lines(self):
        a, ln, run, line = self._cancelled_plain()
        b_ready, c_pending = self._new_job_on(line, ('ready', 'pending'))
        fill = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])      # b_ready claimed
        self.assertEqual((fill.kind, fill.basket_id), ('fill', b_ready.pk))
        queue.report(PortalRun.objects.get(pk=run.pk), self.dev,
                     {'outcome': 'submit_seen', 'order_ref': 'PO900', 'account': ACC})
        for other in (b_ready, c_pending):
            other = PortalBasket.objects.get(pk=other.pk)
            self.assertEqual((other.status, other.needs_person_reason),
                             ('needs_person', f'submit_seen_other:{a.pk}'))
            self.assertIsNone(other.claimed_by_id)
            self.assertEqual(queue.suggested_order_ref(other), '')       # a basket id, not an order
        fill.refresh_from_db()
        self.assertEqual(fill.outcome, 'resolved')
        with self.assertRaises(queue.RunConflict):                       # the claimed fill stops
            queue.heartbeat(fill, self.dev)
        log = AuditLog.objects.filter(action='rpa_portal_needs_person',
                                      new_data__has_key='late_sighting_basket').latest('pk')
        self.assertEqual(log.new_data['late_sighting_basket'], a.pk)
        self.assertEqual(sorted(log.new_data['baskets']), sorted([b_ready.pk, c_pending.pk]))

    def test_r19_late_sighting_pulls_an_awaiting_submit_basket(self):
        a, ln, run, line = self._cancelled_plain()
        (b,) = self._new_job_on(line, ('ready',))
        fill = PortalRun.objects.get(pk=queue.claim_next(self.dev)['run_id'])
        nl = PortalBasket.objects.get(pk=b.pk).lines.get()
        queue.report(fill, self.dev, {'outcome': 'handover', 'steps': [{'label': 'add_line'}], 'account': ACC,
                                      'lines': [{'line_id': nl.pk, 'accepted_qty': 4, 'status': 'ok'}]})
        queue.report(PortalRun.objects.get(pk=run.pk), self.dev,
                     {'outcome': 'submit_seen', 'order_ref': 'PO901', 'account': ACC})
        b = PortalBasket.objects.get(pk=b.pk)
        self.assertEqual(b.status, 'needs_person')
        self.assertIn(f'submit_seen_other:{a.pk}', b.needs_person_reason)
        with self.assertRaises(queue.QueueError):                        # it reached Submit itself
            queue.resolve(b, staff=self.boss, action='retry')

    def test_r19_second_late_sighting_is_idempotent(self):
        a, ln, run, line = self._cancelled_plain()
        payload = {'outcome': 'submit_seen', 'order_ref': 'PO902', 'account': ACC}
        queue.report(PortalRun.objects.get(pk=run.pk), self.dev, dict(payload))
        line.refresh_from_db()
        tried, audits = list(line.tried), AuditLog.objects.count()
        (b,) = self._new_job_on(line, ('ready',))
        a2 = queue.report(PortalRun.objects.get(pk=run.pk), self.dev, dict(payload))
        line.refresh_from_db()
        self.assertEqual(line.tried, tried)
        self.assertEqual(a2.needs_person_reason, 'submit_seen:PO902')
        self.assertEqual(PortalBasket.objects.get(pk=b.pk).status, 'ready')      # nothing new seen
        self.assertEqual(AuditLog.objects.count(), audits + 1)          # only the sighting itself

    # ── 2. order rows whose number cannot be read ────────────────────────────────────────────

    def test_unreadable_order_rows_make_the_read_unclear(self):
        for outcome, orders in (('history_none', [{}]), ('history_found', [{}]),
                                ('history_found', [{'order_ref': ''}]), ('history_none', ['x'])):
            b, hrun, ln, _ = self._stuck_live()
            hrun, b = self._read(hrun, outcome=outcome, orders=orders, complete=True, truncated=False)
            self.assertEqual(hrun.outcome, 'history_unclear', (outcome, orders))
            self.assertIn('unreadable_orders', b.needs_person_reason)

    def test_complete_as_int_one_is_unclear(self):
        b, hrun, ln, _ = self._stuck_live()
        hrun, b = self._read(hrun, outcome='history_none', complete=1, truncated=False)
        self._assert_unclear(hrun, b, 'not_complete')

    # ── 3. a read that comes back after a person acted ───────────────────────────────────────

    def test_retry_refused_while_a_robot_reads_order_history(self):
        b, hrun, ln, _ = self._stuck_live()                 # the read is claimed by the robot
        with self.assertRaises(queue.QueueError):
            queue.resolve(b, staff=self.boss, action='retry', confirm_none=True, reason='checked')
        self.assertIsNone(PortalRun.objects.get(pk=hrun.pk).finished_at)
        hrun, b = self._read(hrun, outcome='history_found', complete=True,
                             orders=[{'order_ref': 'PO-B', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]}])
        self.assertEqual((b.status, b.needs_person_reason), ('needs_person', 'history_found:PO-B'))

    def test_queued_unclaimed_read_does_not_block_a_retry(self):
        job, b, run, ln = self._awaiting()
        PortalBasket.objects.filter(pk=b.pk).update(lease_until=run.started_at)
        queue.expire_leases()                                # a read is queued, nobody holds it
        b = queue.resolve(PortalBasket.objects.get(pk=b.pk), staff=self.boss, action='retry',
                          confirm_none=True, reason='checked the site')
        self.assertEqual(b.status, 'ready')

    def test_found_result_pulls_back_a_basket_that_moved_on(self):
        b, hrun, ln, _ = self._stuck_live()
        PortalBasket.objects.filter(pk=b.pk).update(status='ready', needs_person_reason='')
        hrun, b = self._read(hrun, outcome='history_found', complete=True,
                             orders=[{'order_ref': 'PO-B', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]}])
        self.assertEqual((hrun.outcome, b.status, b.needs_person_reason),
                         ('history_found', 'needs_person', 'history_found:PO-B'))

    def test_unclear_result_pulls_back_a_claimed_basket_and_stops_its_fill(self):
        b, hrun, ln, _ = self._stuck_live()
        PortalBasket.objects.filter(pk=b.pk).update(status='in_progress', claimed_by=self.dev)
        fill = PortalRun.objects.create(basket=b, kind='fill', device=self.dev, mode='live',
                                        started_at=hrun.started_at)
        hrun, b = self._read(hrun, outcome='history_none')
        self.assertEqual((hrun.outcome, b.status), ('history_unclear', 'needs_person'))
        self.assertTrue(b.needs_person_reason.startswith('history_unclear'))
        self.assertIsNone(b.claimed_by_id)
        self.assertEqual(PortalRun.objects.get(pk=fill.pk).outcome, 'resolved')

    def test_found_after_a_cancel_closed_the_read_is_still_taken(self):
        b, hrun, ln, _ = self._stuck_live()
        b = queue.resolve(b, staff=self.boss, action='cancel', confirm_placed_order_cancel=True, reason='x')
        self.assertEqual(PortalRun.objects.get(pk=hrun.pk).outcome, 'resolved')
        hrun, b = self._read(PortalRun.objects.get(pk=hrun.pk), outcome='history_found', complete=True,
                             orders=[{'order_ref': 'PO-C', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]}])
        self.assertEqual((hrun.outcome, b.status, b.needs_person_reason),
                         ('history_found', 'needs_person', 'history_found:PO-C'))

    def test_none_after_a_cancel_changes_nothing(self):
        b, hrun, ln, _ = self._stuck_live()
        queue.resolve(b, staff=self.boss, action='cancel', confirm_placed_order_cancel=True, reason='x')
        hrun, b = self._read(PortalRun.objects.get(pk=hrun.pk), outcome='history_none', complete=True)
        self.assertEqual((hrun.outcome, b.status), ('resolved', 'cancelled'))
        self.assertEqual(hrun.steps[-1]['label'], 'order_history')     # kept for the record

    def test_other_closed_reads_still_conflict(self):
        b, hrun, ln, _ = self._stuck_live()
        self._read(hrun, outcome='history_none', complete=True)
        with self.assertRaises(queue.RunConflict):
            queue.report(PortalRun.objects.get(pk=hrun.pk), self.dev,
                         {'outcome': 'history_found', 'account': ACC,
                          'orders': [{'order_ref': 'PO-D', 'lines': []}]})

    # ── 4. doubts kept on found reads ────────────────────────────────────────────────────────

    def test_found_read_keeps_its_doubts(self):
        b, hrun, ln, _ = self._stuck_live()
        hrun, b = self._read(hrun, outcome='history_found', truncated=True,
                             orders=[{'order_ref': 'PO-B', 'lines': [{'sku': ln.supplier_key, 'qty': 4}]}])
        self.assertEqual(hrun.outcome, 'history_found')
        self.assertIn('truncated', hrun.steps[-1]['doubts'])
        self.assertIn('not_complete', hrun.steps[-1]['doubts'])
        log = AuditLog.objects.filter(action='rpa_portal_needs_person').latest('pk')
        self.assertIn('truncated', log.new_data['doubts'])
