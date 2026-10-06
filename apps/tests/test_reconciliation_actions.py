"""
apps/tests/test_reconciliation_actions.py

Phase-C batch E — human approval actions (apps/finance/recon_actions.py + the
action endpoints). Mirror mutations only; every action writes a ReconAuditEvent
and NOTHING touches SOFTECH. Covers capacity guards, party integrity, undo rules,
and the RBAC gate.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.finance import recon_actions as A, recon_engine as E
from apps.finance.models import (
    ReconParty, APInvoice, Payment, Allocation, MatchCandidate, ReconAuditEvent,
)
from .factories import make_admin, make_salesperson

BASE = '/api/finance/reconciliation'


def _party(pc='4471'):
    return ReconParty.objects.create(party_type='supplier', softech_personcode=pc, name='مورد')


def _inv(party, docnumber='12207', value='743.40'):
    return APInvoice.objects.create(
        party=party, branchcode='130', doccode='10', docnumber=docnumber,
        docdate=date(2026, 8, 15), docnumber2='5213', doc_value=Decimal(value),
        doc_value_pay=Decimal('0'), party_type='supplier',
    )


def _pay(party, cheqsno=51703, amount='743.40', note='مورد 12207'):
    return Payment.objects.create(
        party=party, branchcode='130', cheqsno=cheqsno, direction='out',
        party_type='supplier', voucher_date=date(2026, 9, 18),
        amount=Decimal(amount), note=note, is_unallocated=True,
    )


def _proposed(party, inv, pay):
    E.run_matching(party_type='supplier')
    return MatchCandidate.objects.get(invoice=inv, payment=pay)


class ApproveTests(TestCase):

    def setUp(self):
        self.party = _party()
        self.inv = _inv(self.party)
        self.pay = _pay(self.party)
        self.cand = _proposed(self.party, self.inv, self.pay)

    def test_approve_full(self):
        alloc = A.approve_candidate(self.cand)
        self.assertEqual(alloc.origin, Allocation.ORIGIN_APPROVED)
        self.assertEqual(alloc.amount, Decimal('743.40'))
        self.cand.refresh_from_db()
        self.pay.refresh_from_db()
        self.assertEqual(self.cand.status, MatchCandidate.STATUS_APPROVED)
        self.assertFalse(self.pay.is_unallocated)
        self.assertEqual(self.inv.unlinked_amount, Decimal('0.00'))
        self.assertTrue(ReconAuditEvent.objects.filter(action='candidate_approved').exists())

    def test_approve_partial(self):
        alloc = A.approve_candidate(self.cand, amount='300')
        self.assertEqual(alloc.amount, Decimal('300'))
        self.assertEqual(self.inv.unlinked_amount, Decimal('443.40'))
        self.assertEqual(self.pay.unallocated_amount, Decimal('443.40'))

    def test_over_allocation_blocked(self):
        with self.assertRaises(A.ReconActionError):
            A.approve_candidate(self.cand, amount='800')

    def test_double_approve_blocked(self):
        A.approve_candidate(self.cand)
        self.cand.refresh_from_db()
        with self.assertRaises(A.ReconActionError):
            A.approve_candidate(self.cand)   # already approved

    def _written_partial(self, ours=True):
        alloc = Allocation.objects.create(payment=self.pay, invoice=self.inv, amount=Decimal('300'),
                                          origin=Allocation.ORIGIN_WRITTEN if ours else Allocation.ORIGIN_SOFTECH)
        if ours:
            ReconAuditEvent.objects.create(action='allocation_written', allocation=alloc)
        self.cand.proposed_amount = Decimal('443.40')
        self.cand.save(update_fields=['proposed_amount'])
        return alloc

    def test_approve_on_our_partial_link_tops_it_up(self):
        alloc = self._written_partial()
        got = A.approve_candidate(self.cand)
        self.assertEqual(got.pk, alloc.pk)                           # the same link, not a second
        alloc.refresh_from_db()
        self.assertEqual((alloc.amount, alloc.origin), (Decimal('743.40'), Allocation.ORIGIN_APPROVED))
        with self.assertRaises(A.ReconActionError):                 # already in SOFTECH → reverse, not undo
            A.undo_allocation(alloc)

    def test_approve_on_native_partial_link_is_refused(self):
        self._written_partial(ours=False)
        with self.assertRaises(A.ReconActionError):
            A.approve_candidate(self.cand)

    def test_reject(self):
        c = A.reject_candidate(self.cand, note='ليست الفاتورة الصحيحة')
        self.assertEqual(c.status, MatchCandidate.STATUS_REJECTED)
        self.assertEqual(c.decision_note, 'ليست الفاتورة الصحيحة')


class UndoAndManualTests(TestCase):

    def setUp(self):
        self.party = _party()
        self.inv = _inv(self.party)
        self.pay = _pay(self.party)

    def test_manual_allocate_and_undo(self):
        alloc = A.manual_allocate(self.pay, self.inv, '743.40')
        self.assertEqual(alloc.origin, Allocation.ORIGIN_APPROVED)
        self.pay.refresh_from_db()
        self.assertFalse(self.pay.is_unallocated)
        A.undo_allocation(alloc)
        self.assertFalse(Allocation.objects.filter(pk=alloc.pk).exists())
        self.pay.refresh_from_db()
        self.assertTrue(self.pay.is_unallocated)

    def test_manual_party_mismatch_blocked(self):
        other = ReconParty.objects.create(party_type='supplier', softech_personcode='9999')
        foreign_inv = _inv(other, docnumber='888')
        with self.assertRaises(A.ReconActionError):
            A.manual_allocate(self.pay, foreign_inv, '100')

    def test_undo_softech_allocation_blocked(self):
        soft = Allocation.objects.create(
            payment=self.pay, invoice=self.inv, amount=Decimal('743.40'),
            origin=Allocation.ORIGIN_SOFTECH,
        )
        with self.assertRaises(A.ReconActionError):
            A.undo_allocation(soft)

    def test_undo_reverts_candidate_to_proposed(self):
        cand = _proposed(self.party, self.inv, self.pay)
        alloc = A.approve_candidate(cand)
        cand.refresh_from_db()
        self.assertEqual(cand.status, MatchCandidate.STATUS_APPROVED)
        A.undo_allocation(alloc)
        cand.refresh_from_db()
        self.assertEqual(cand.status, MatchCandidate.STATUS_PROPOSED)


class BulkApproveTests(TestCase):

    def _high_candidates(self, n):
        """n parties each with one clean amount+reference match; force class=high."""
        for i in range(n):
            p = _party(pc=str(4000 + i))
            inv = _inv(p, docnumber=str(10000 + i), value='500')
            _pay(p, cheqsno=20000 + i, amount='500', note=f'مورد {10000 + i}')
        E.run_matching(party_type='supplier')
        MatchCandidate.objects.filter(status=MatchCandidate.STATUS_PROPOSED).update(
            confidence_class='high')

    def test_bulk_approves_all_high(self):
        self._high_candidates(3)
        res = A.bulk_approve(party_type='supplier', confidence_class='high')
        self.assertEqual(res['approved'], 3)
        self.assertEqual(res['remaining'], 0)
        self.assertEqual(Allocation.objects.filter(origin=Allocation.ORIGIN_APPROVED).count(), 3)
        self.assertFalse(MatchCandidate.objects.filter(
            status=MatchCandidate.STATUS_PROPOSED, confidence_class='high').exists())

    def test_bulk_only_touches_requested_class(self):
        self._high_candidates(2)
        # add a medium candidate that must be left alone
        p = _party(pc='7777')
        inv = _inv(p, docnumber='777', value='500')
        _pay(p, cheqsno=777, amount='500', note='x')
        E.run_matching(party_type='supplier')
        MatchCandidate.objects.filter(party=p).update(confidence_class='medium')
        res = A.bulk_approve(party_type='supplier', confidence_class='high')
        self.assertEqual(res['approved'], 2)
        self.assertTrue(MatchCandidate.objects.filter(
            party=p, status=MatchCandidate.STATUS_PROPOSED).exists())

    def test_bulk_limit_reports_remaining(self):
        self._high_candidates(3)
        res = A.bulk_approve(party_type='supplier', confidence_class='high', limit=1)
        self.assertEqual(res['approved'], 1)
        self.assertEqual(res['remaining'], 2)

    def test_mass_approve_skips_matches_held_for_review(self):
        self._high_candidates(3)
        held = MatchCandidate.objects.filter(status=MatchCandidate.STATUS_PROPOSED).first()
        held.decision_note = A.HOLD_PREFIX + 'السند أكبر من الفاتورة'
        held.group_key = 'g-review'
        held.save(update_fields=['decision_note', 'group_key'])
        res = A.bulk_approve(party_type='supplier', confidence_class='high')
        self.assertEqual(res['approved'], 2)
        self.assertEqual(res['held_for_review'], 1)
        self.assertEqual(res['remaining'], 0)
        held.refresh_from_db()
        self.assertEqual(held.status, MatchCandidate.STATUS_PROPOSED)
        # a deliberate, reviewed GROUP approve still can approve it
        res = A.bulk_approve(group_key='g-review', confidence_class=None)
        self.assertEqual(res['approved'], 1)

    def test_bulk_endpoint_rbac_and_drain(self):
        _, _, client = make_admin('bulk_admin')
        self._high_candidates(2)
        resp = client.post(f'{BASE}/candidates/bulk-approve/',
                           {'party_type': 'supplier', 'confidence_class': 'high'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['approved'], 2)
        # salesperson is blocked
        _, _, sales = make_salesperson('bulk_sales')
        resp2 = sales.post(f'{BASE}/candidates/bulk-approve/',
                          {'confidence_class': 'high'}, format='json')
        self.assertEqual(resp2.status_code, 403)


class ActionApiTests(TestCase):

    def setUp(self):
        _, self.profile, self.client = make_admin('recon_admin')
        self.party = _party()
        self.inv = _inv(self.party)
        self.pay = _pay(self.party)
        self.cand = _proposed(self.party, self.inv, self.pay)

    def test_approve_endpoint(self):
        resp = self.client.post(f'{BASE}/candidates/{self.cand.id}/approve/', {}, format='json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['candidate']['status'], 'approved')
        self.assertTrue(Allocation.objects.filter(invoice=self.inv, payment=self.pay).exists())

    def test_approve_capacity_error_maps_400(self):
        resp = self.client.post(f'{BASE}/candidates/{self.cand.id}/approve/',
                                {'amount': '9999'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_reject_endpoint(self):
        resp = self.client.post(f'{BASE}/candidates/{self.cand.id}/reject/',
                                {'note': 'خطأ'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], 'rejected')

    def test_manual_and_undo_endpoints(self):
        inv2 = _inv(self.party, docnumber='30000', value='100')
        pay2 = _pay(self.party, cheqsno=2, amount='100', note='x')
        resp = self.client.post(f'{BASE}/allocations/manual/',
                                {'payment': pay2.id, 'invoice': inv2.id, 'amount': '100'},
                                format='json')
        self.assertEqual(resp.status_code, 201)
        alloc_id = resp.json()['id']
        resp2 = self.client.post(f'{BASE}/allocations/{alloc_id}/undo/', {}, format='json')
        self.assertEqual(resp2.status_code, 204)

    def test_permission_gate(self):
        _, _, sales_client = make_salesperson('sales_recon')
        resp = sales_client.post(f'{BASE}/candidates/{self.cand.id}/approve/', {}, format='json')
        self.assertEqual(resp.status_code, 403)
        self.cand.refresh_from_db()
        self.assertEqual(self.cand.status, MatchCandidate.STATUS_PROPOSED)   # untouched

    def test_write_softech_is_dry_run_when_flag_off(self):
        # approve → get the allocation → write-softech returns a dry-run plan (flag off)
        appr = self.client.post(f'{BASE}/candidates/{self.cand.id}/approve/', {}, format='json')
        alloc_id = appr.json()['allocation']['id']
        resp = self.client.post(f'{BASE}/allocations/{alloc_id}/write-softech/', {}, format='json')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['dry_run'])
        self.assertFalse(body['written'])
        self.assertFalse(body['enabled'])            # AP_RECONCILE_WRITER_ENABLED off
        self.assertIn('plan', body)
        # the plan never writes a cheques row
        sqls = ' '.join(s['sql'].lower() for s in body['plan']['statements']).replace('chequestrans', '')
        self.assertNotIn(' cheques', sqls)

    def test_write_softech_admin_only(self):
        appr = self.client.post(f'{BASE}/candidates/{self.cand.id}/approve/', {}, format='json')
        alloc_id = appr.json()['allocation']['id']
        _, _, sales_client = make_salesperson('sales_write')
        resp = sales_client.post(f'{BASE}/allocations/{alloc_id}/write-softech/', {}, format='json')
        self.assertEqual(resp.status_code, 403)
