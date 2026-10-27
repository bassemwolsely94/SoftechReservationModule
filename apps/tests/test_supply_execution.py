"""
Phase-5 tests for supply execution (doc 24 §11/§14/§17/§31/§32/§40).

Owner decisions: internal transfers → DRAFT TransferRequests; purchases → order list only.
Covers idempotency, no double allocation of surplus, live revalidation, overrides +
reasons, all-or-nothing orders, pending-order netting, and receipt settlement.
"""
from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from apps.supply import cases as case_svc
from apps.supply import execution as exe
from apps.supply.engine import recommend
from apps.supply.engine.allocation import transferable_surplus
from apps.supply.models import (AvailabilityBatch, AvailabilityLine, SupplyCase,
                                 SupplyDecision)
from .factories import make_user

S = SupplyCase


def _run():
    from apps.purchasing.models import DemandCalculationRun
    return DemandCalculationRun.objects.create(status='success', calc_date=date.today())


def _metric(run, item, branch, *, stock=0, safety=0, gap=0):
    from apps.purchasing.models import ItemDemandMetrics
    return ItemDemandMetrics.objects.create(run=run, item=item, branch=branch,
                                            calc_date=date.today(), current_stock=stock,
                                            safety_stock=safety, gap=gap)


def _live(item, branch, qty):
    from apps.catalog.models import ItemStock
    return ItemStock.objects.create(item=item, branch=branch,
                                    softech_store_code=branch.softech_branch_id,
                                    quantity_on_hand=qty)


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        cls.item = Item.objects.create(softech_id='700001', name='RECORMON 4000 IU', is_active=True)
        cls.dest = Branch.objects.create(softech_branch_id='130', name='B130')
        cls.donor = Branch.objects.create(softech_branch_id='140', name='B140')
        cls.other = Branch.objects.create(softech_branch_id='150', name='B150')
        cls.user, cls.staff, _ = make_user('exec_buyer', role='purchasing')

    def _case_needing(self, gap=5, donor_stock=9, donor_safety=2, live_donor=None):
        run = _run()
        _metric(run, self.item, self.dest, stock=0, gap=gap)
        _metric(run, self.item, self.donor, stock=donor_stock, safety=donor_safety)
        _live(self.item, self.donor, donor_stock if live_donor is None else live_donor)
        return case_svc.evaluate_case(self.item.id, self.dest.id)['case']


# ── Internal transfer → draft TransferRequest ──────────────────────────────────

class ApproveTransferTests(_Base):
    def test_creates_draft_transfer_request_and_records_decision(self):
        from apps.audit.models import AuditLog
        from apps.transfers.models import TransferRequestMessage
        case = self._case_needing(gap=5)
        res = exe.approve_internal_transfer(case, idempotency_key='k1', staff=self.staff)
        self.assertFalse(res['replayed'])
        tr = res['transfer_requests'][0]
        self.assertEqual(tr.status, 'draft')                  # transfers team takes it from here
        self.assertEqual(tr.requesting_branch_id, self.dest.id)
        self.assertEqual(tr.supplying_branch_id, self.donor.id)
        self.assertEqual(float(tr.items.get().quantity), 5.0)
        self.assertTrue(TransferRequestMessage.objects.filter(request=tr).exists())
        d = res['decision']
        self.assertEqual(d.kind, SupplyDecision.KIND_INTERNAL_TRANSFER)
        self.assertEqual(float(d.recommended_qty), float(d.decided_qty))
        self.assertFalse(d.is_override)
        case.refresh_from_db()
        self.assertEqual(case.status, S.STATUS_TRANSFER_PENDING)
        self.assertIn(tr.pk, case.execution_refs['transfer_requests'])
        self.assertTrue(AuditLog.objects.filter(action='supply_transfer_drafted').exists())

    def test_same_idempotency_key_replays_without_a_second_draft(self):
        from apps.transfers.models import TransferRequest
        case = self._case_needing(gap=5)
        exe.approve_internal_transfer(case, idempotency_key='dup', staff=self.staff)
        res2 = exe.approve_internal_transfer(case, idempotency_key='dup', staff=self.staff)
        self.assertTrue(res2['replayed'])
        self.assertEqual(TransferRequest.objects.count(), 1)

    def test_approved_draft_reserves_the_donor_surplus(self):
        # Donor surplus 7; approving 5 for dest leaves only 2 for anyone else.
        case = self._case_needing(gap=5)
        exe.approve_internal_transfer(case, idempotency_key='k', staff=self.staff)
        src = {s['branch_id']: s for s in
               transferable_surplus(self.item.id, exclude_branch_id=self.other.id, live=True)}
        self.assertEqual(src[self.donor.id]['committed_outbound'], 5.0)
        self.assertEqual(src[self.donor.id]['surplus'], 2.0)

    def test_after_approval_the_need_is_not_proposed_again(self):
        case = self._case_needing(gap=5)
        exe.approve_internal_transfer(case, idempotency_key='k', staff=self.staff)
        rec = recommend(self.item.id, branch_id=self.dest.id)
        L = rec['quantity_ledger']
        self.assertEqual(L['pending_internal_in'], 5.0)
        self.assertEqual(L['required'], 0.0)                  # already in motion
        self.assertEqual(L['internally_allocated'], 0.0)

    def test_dispatched_transfer_no_longer_counts_as_committed(self):
        from django.utils import timezone
        from apps.transfers.models import TransferRequest
        case = self._case_needing(gap=5)
        exe.approve_internal_transfer(case, idempotency_key='k', staff=self.staff)
        TransferRequest.objects.update(status='sent_to_erp', dispatched_at=timezone.now())
        src = {s['branch_id']: s for s in
               transferable_surplus(self.item.id, exclude_branch_id=self.other.id, live=True)}
        self.assertEqual(src[self.donor.id]['committed_outbound'], 0.0)

    def test_live_revalidation_rejects_a_stale_plan(self):
        # Demand run said donor had 9, but live stock is now 3 (safety 2 → surplus 1).
        case = self._case_needing(gap=5, donor_stock=9, live_donor=3)
        with self.assertRaises(exe.ExecutionError):
            exe.approve_internal_transfer(
                case, idempotency_key='k', staff=self.staff,
                transfers=[{'from_branch_id': self.donor.id, 'qty': 5}])
        res = exe.approve_internal_transfer(case, idempotency_key='k2', staff=self.staff)
        self.assertEqual(float(res['decision'].decided_qty), 1.0)   # what is actually there

    def test_moving_more_than_recommended_needs_a_reason(self):
        case = self._case_needing(gap=3)                      # recommended 3, surplus 7
        with self.assertRaises(exe.ExecutionError):
            exe.approve_internal_transfer(
                case, idempotency_key='k', staff=self.staff,
                transfers=[{'from_branch_id': self.donor.id, 'qty': 6}])
        res = exe.approve_internal_transfer(
            case, idempotency_key='k2', staff=self.staff, reason='عرض ترويجي بالفرع',
            transfers=[{'from_branch_id': self.donor.id, 'qty': 6}])
        self.assertTrue(res['decision'].is_override)
        self.assertEqual(res['decision'].override_reason, 'عرض ترويجي بالفرع')

    def test_network_case_cannot_create_a_transfer(self):
        case = SupplyCase.objects.create(item=self.item, branch=None)
        with self.assertRaises(exe.ExecutionError):
            exe.approve_internal_transfer(case, idempotency_key='k', staff=self.staff)


# ── Order list (WhatsApp / Excel) ──────────────────────────────────────────────

class OrderListTests(_Base):
    def _need(self, gap=5):
        _metric(_run(), self.item, self.dest, stock=0, gap=gap)
        return case_svc.evaluate_case(self.item.id, self.dest.id)['case']

    def _offer(self, qty=10, price=500):
        b = AvailabilityBatch.objects.create(source='whatsapp', supplier_name='Ibn Sina')
        return AvailabilityLine.objects.create(batch=b, raw_text='recormon 4000 10',
                                               item=self.item, is_confirmed=True,
                                               supplier_qty=qty, price=price)

    def test_preview_builds_whatsapp_text_and_flags_excess(self):
        case = self._need(gap=5)
        p = exe.preview_order([{'item_id': self.item.id, 'qty': 8, 'case_id': case.id}])
        self.assertEqual(p['text'], 'مطلوب:\nRECORMON 4000 IU — 8')
        self.assertTrue(p['lines'][0]['exceeds_need'])          # 8 > need 5
        self.assertEqual(p['lines'][0]['recommended_qty'], 5.0)

    def test_commit_records_order_and_moves_case_and_batch(self):
        case = self._need(gap=5)
        offer = self._offer()
        res = exe.commit_order([{'availability_line_id': offer.id, 'qty': 5, 'case_id': case.id}],
                               idempotency_key='o1', staff=self.staff)
        d = res['decisions'][0]
        self.assertEqual(d.receipt_status, SupplyDecision.RECEIPT_OPEN)
        self.assertEqual(float(d.unit_price), 500.0)
        case.refresh_from_db()
        self.assertEqual(case.status, S.STATUS_ORDERED)
        offer.batch.refresh_from_db()
        self.assertEqual(offer.batch.status, AvailabilityBatch.STATUS_ACTIONED)
        self.assertIn('RECORMON 4000 IU — 5', res['text'])

    def test_commit_is_idempotent(self):
        case = self._need(gap=5)
        exe.commit_order([{'item_id': self.item.id, 'qty': 5, 'case_id': case.id}],
                         idempotency_key='same', staff=self.staff)
        res2 = exe.commit_order([{'item_id': self.item.id, 'qty': 5, 'case_id': case.id}],
                                idempotency_key='same', staff=self.staff)
        self.assertTrue(res2['replayed'])
        self.assertEqual(SupplyDecision.objects.filter(order_ref='same').count(), 1)

    def test_buying_more_than_need_requires_reason_and_is_all_or_nothing(self):
        from apps.catalog.models import Item
        other_item = Item.objects.create(softech_id='700002', name='KREON 25000', is_active=True)
        case = self._need(gap=5)
        with self.assertRaises(exe.ExecutionError):
            exe.commit_order([
                {'item_id': other_item.id, 'qty': 1, 'reason': 'طلب خاص'},   # valid
                {'item_id': self.item.id, 'qty': 9, 'case_id': case.id},     # exceeds, no reason
            ], idempotency_key='bad', staff=self.staff)
        self.assertFalse(SupplyDecision.objects.exists())                     # nothing recorded

    def test_open_order_nets_the_requirement_so_it_is_not_ordered_twice(self):
        case = self._need(gap=5)
        exe.commit_order([{'item_id': self.item.id, 'qty': 5, 'case_id': case.id}],
                         idempotency_key='o1', staff=self.staff)
        L = recommend(self.item.id, branch_id=self.dest.id)['quantity_ledger']
        self.assertEqual(L['pending_orders'], 5.0)
        self.assertEqual(L['required'], 0.0)
        with self.assertRaises(exe.ExecutionError):                           # second order
            exe.commit_order([{'item_id': self.item.id, 'qty': 5, 'case_id': case.id}],
                             idempotency_key='o2', staff=self.staff)

    def test_receiving_the_case_settles_the_open_order(self):
        case = self._need(gap=5)
        exe.commit_order([{'item_id': self.item.id, 'qty': 5, 'case_id': case.id}],
                         idempotency_key='o1', staff=self.staff)
        case.refresh_from_db()
        case_svc.transition(case, S.STATUS_RECEIVED, staff=self.staff)
        d = SupplyDecision.objects.get(order_ref='o1')
        self.assertEqual(d.receipt_status, SupplyDecision.RECEIPT_RECEIVED)
        L = recommend(self.item.id, branch_id=self.dest.id)['quantity_ledger']
        self.assertEqual(L['pending_orders'], 0.0)

    def test_excel_export_is_an_xlsx(self):
        self._need(gap=5)
        content = exe.export_order_excel([{'item_id': self.item.id, 'qty': 5}],
                                         supplier_name='Ibn Sina')
        self.assertTrue(content[:2] == b'PK')


# ── API + RBAC ─────────────────────────────────────────────────────────────────

class ExecutionApiTests(_Base):
    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def test_approve_transfer_endpoint_and_replay(self):
        case = self._case_needing(gap=5)
        c = self._client(self.user)
        url = f'/api/supply/cases/{case.id}/approve-transfer/'
        r1 = c.post(url, {'idempotency_key': 'api-1'}, format='json')
        self.assertEqual(r1.status_code, 201, r1.content)
        self.assertEqual(r1.json()['transfer_requests'][0]['status'], 'draft')
        r2 = c.post(url, {'idempotency_key': 'api-1'}, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()['replayed'])

    def test_order_list_endpoints(self):
        _metric(_run(), self.item, self.dest, stock=0, gap=5)
        case = case_svc.evaluate_case(self.item.id, self.dest.id)['case']
        c = self._client(self.user)
        lines = [{'item_id': self.item.id, 'qty': 5, 'case_id': case.id}]
        r = c.post('/api/supply/order-list/preview/', {'lines': lines}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = c.post('/api/supply/order-list/commit/',
                   {'lines': lines, 'idempotency_key': 'api-o1'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        r = c.get('/api/supply/decisions/?order_ref=api-o1')
        self.assertEqual(r.status_code, 200)
        r = c.post('/api/supply/order-list/excel/', {'lines': lines}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_missing_idempotency_key_is_rejected(self):
        case = self._case_needing(gap=5)
        r = self._client(self.user).post(f'/api/supply/cases/{case.id}/approve-transfer/',
                                         {}, format='json')
        self.assertEqual(r.status_code, 409)

    def test_salesperson_cannot_execute(self):
        case = self._case_needing(gap=5)
        seller, _, _ = make_user('exec_seller', role='salesperson')
        c = self._client(seller)
        self.assertEqual(c.post(f'/api/supply/cases/{case.id}/approve-transfer/',
                                {'idempotency_key': 'x'}, format='json').status_code, 403)
        self.assertEqual(c.post('/api/supply/order-list/commit/',
                                {'lines': [], 'idempotency_key': 'x'},
                                format='json').status_code, 403)


# ── Real concurrency: two approvals racing for the same donor surplus (§31/§38) ─

from django.test import TransactionTestCase, skipUnlessDBFeature  # noqa: E402


class ConcurrentAllocationTests(TransactionTestCase):
    """Two branches each need 5; the donor has only 7 spare. Fired at the same instant,
    the per-item advisory lock must serialize them so the donor is never over-drawn
    (without it both would read "7 free" and draft 5 + 5 = 10)."""

    def test_same_surplus_is_never_allocated_twice(self):
        import threading
        from django.db import connection
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        from apps.transfers.models import TransferRequestItem

        item = Item.objects.create(softech_id='790001', name='SCARCE', is_active=True)
        a = Branch.objects.create(softech_branch_id='131', name='A')
        b = Branch.objects.create(softech_branch_id='132', name='B')
        donor = Branch.objects.create(softech_branch_id='133', name='D')
        _, staff, _ = make_user('race_buyer', role='purchasing')
        run = _run()
        _metric(run, item, a, stock=0, gap=5)
        _metric(run, item, b, stock=0, gap=5)
        _metric(run, item, donor, stock=9, safety=2)          # surplus 7
        _live(item, donor, 9)
        case_a = case_svc.evaluate_case(item.id, a.id)['case']
        case_b = case_svc.evaluate_case(item.id, b.id)['case']

        barrier = threading.Barrier(2)
        errors = []

        def approve(case, key):
            try:
                barrier.wait()
                exe.approve_internal_transfer(case, idempotency_key=key, staff=staff)
            except exe.ExecutionError as exc:
                errors.append(str(exc))                        # acceptable: nothing left
            finally:
                connection.close()

        t1 = threading.Thread(target=approve, args=(case_a, 'race-a'))
        t2 = threading.Thread(target=approve, args=(case_b, 'race-b'))
        t1.start(); t2.start(); t1.join(); t2.join()

        drawn = sum(float(t.quantity) for t in
                    TransferRequestItem.objects.filter(item=item, request__supplying_branch=donor))
        self.assertLessEqual(drawn, 7.0 + 1e-6)                # never beyond the real surplus
        self.assertAlmostEqual(drawn, 7.0)                     # 5 + 2 — surplus fully used
