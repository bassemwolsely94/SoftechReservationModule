"""
apps/tests/test_reconciliation_grid.py

Owner request 2026-09-28: sortable grid, multi-select actions, and the GROUPED review
view (all vouchers proposed for one invoice together, flagging when they exceed it).
Also pins that human decisions survive the nightly re-matching: a rejected pair is
never re-proposed and a manual «send to review» hold is never auto-approved.
"""
from datetime import date
from decimal import Decimal as D

from django.test import TestCase

from apps.finance import recon_actions as A, recon_engine as E
from apps.finance.models import Allocation, MatchCandidate
from .factories import make_admin
from .test_reconciliation_actions import BASE, _inv, _party, _pay


def _cand(party, inv, pay, amount, score='90', cls='high', note=''):
    return MatchCandidate.objects.create(
        party=party, invoice=inv, payment=pay, proposed_amount=D(amount),
        confidence_score=D(score), confidence_class=cls, decision_note=note)


class GridAndGroupsTests(TestCase):

    def setUp(self):
        _, _, self.client = make_admin('grid_admin')
        self.party = _party()
        self.inv = _inv(self.party, docnumber='500', value='1000')
        self.p1 = _pay(self.party, cheqsno=1, amount='700', note='x')
        self.p2 = _pay(self.party, cheqsno=2, amount='600', note='y')
        self.c1 = _cand(self.party, self.inv, self.p1, '700')
        self.c2 = _cand(self.party, self.inv, self.p2, '600', score='85')
        other = _inv(self.party, docnumber='501', value='50')
        self.p3 = _pay(self.party, cheqsno=3, amount='50', note='z')
        self.c3 = _cand(self.party, other, self.p3, '50', score='99')

    def test_grid_sorts_by_invoice_value_both_ways(self):
        up = self.client.get(f'{BASE}/candidates/', {'ordering': 'invoice__doc_value'}).json()['results']
        down = self.client.get(f'{BASE}/candidates/', {'ordering': '-invoice__doc_value'}).json()['results']
        self.assertEqual(up[0]['id'], self.c3.id)
        self.assertEqual(down[-1]['id'], self.c3.id)

    def test_group_by_invoice_shows_all_vouchers_and_flags_excess(self):
        r = self.client.get(f'{BASE}/candidates/groups/', {'by': 'invoice', 'only': 'over'}).json()
        self.assertEqual(r['count'], 1)
        g = r['results'][0]
        self.assertEqual(g['id'], self.inv.id)
        self.assertEqual({c['id'] for c in g['candidates']}, {self.c1.id, self.c2.id})
        self.assertEqual(D(g['pending']), D('1300'))
        self.assertEqual(D(g['excess']), D('300'))           # 700+600 vs 1000 still owed

    def test_single_candidate_groups_hidden_by_default(self):
        r = self.client.get(f'{BASE}/candidates/groups/', {'by': 'invoice'}).json()
        self.assertEqual([g['id'] for g in r['results']], [self.inv.id])

    def test_approve_one_and_dismiss_the_rest_of_the_group(self):
        r = self.client.post(f'{BASE}/candidates/selection-action/',
                             {'action': 'approve', 'ids': [self.c1.id], 'reject_ids': [self.c2.id]},
                             format='json').json()
        self.assertEqual((r['done'], r['rejected']), (1, 1))
        self.c1.refresh_from_db(); self.c2.refresh_from_db()
        self.assertEqual(self.c1.status, MatchCandidate.STATUS_APPROVED)
        self.assertEqual(self.c2.status, MatchCandidate.STATUS_REJECTED)

    def test_selection_approve_over_capacity_is_refused_per_row(self):
        r = self.client.post(f'{BASE}/candidates/selection-action/',
                             {'action': 'approve', 'ids': [self.c1.id, self.c2.id]}, format='json').json()
        self.assertEqual((r['done'], r['failed']), (1, 1))  # 2nd would overpay the invoice

    def test_send_approved_back_to_review_undoes_mirror_allocation(self):
        A.approve_candidate(self.c1)
        A.send_to_review(self.c1, note='تحقق من المورد')
        self.c1.refresh_from_db()
        self.assertEqual(self.c1.status, MatchCandidate.STATUS_PROPOSED)
        self.assertTrue(self.c1.decision_note.startswith(E.MANUAL_HOLD_PREFIX))
        self.assertFalse(Allocation.objects.filter(candidate=self.c1).exists())


class DecisionsSurviveRerunTests(TestCase):

    def setUp(self):
        self.party = _party()
        self.inv = _inv(self.party)                    # 12207 / 743.40
        self.pay = _pay(self.party)                    # note names 12207, same amount

    def _only(self):
        return MatchCandidate.objects.get(invoice=self.inv, payment=self.pay, status='proposed')

    def test_rejected_pair_is_not_proposed_again(self):
        E.run_matching(party_type='supplier')
        A.reject_candidate(self._only(), note='خطأ')
        E.run_matching(party_type='supplier')
        self.assertFalse(MatchCandidate.objects.filter(
            invoice=self.inv, payment=self.pay, status='proposed').exists())

    def test_manual_hold_survives_rerun_and_is_never_auto_approved(self):
        E.run_matching(party_type='supplier')
        A.send_to_review(self._only(), note='راجع')
        E.run_matching(party_type='supplier')
        c = self._only()
        self.assertTrue(c.decision_note.startswith(E.MANUAL_HOLD_PREFIX))
        with self.settings(AP_RECONCILE_AUTO_APPROVE=True):
            A.auto_approve(party_type='supplier')
        c.refresh_from_db()
        self.assertEqual(c.status, MatchCandidate.STATUS_PROPOSED)
        self.assertFalse(Allocation.objects.filter(invoice=self.inv, origin='approved').exists())
