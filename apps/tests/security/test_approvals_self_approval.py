"""
Separation of duties — nobody approves their own request (Batch 4, Z-11j; overblock review,
owner sign-off: the engine serves HR, batch quarantine, near-expiry markdowns, POS offer approvals,
gamification rewards and replacement).

Before: the shared approvals engine checked only that the decider was eligible for the step, so a
supervisor who filed a request on a supervisor step (or an admin on an admin step) approved it
themselves. Replacement enforced maker ≠ checker in its own code; nothing else did.

Now: ApprovalService.decide refuses an *approval* by the request's requester. Rejecting (or
returning / delegating) one's own request stays possible — that is withdrawing it.
"""
from apps.approvals.models import ApprovalDecision, ApprovalRequest
from apps.approvals.service import ApprovalError, ApprovalService
from apps.tests.factories import make_user
from apps.tests.test_hr import HrBase


LEAVE = {'leave_type_code': 'annual', 'start_date': '2026-08-01', 'end_date': '2026-08-03',
         'return_to_work_date': '2026-08-05', 'days_requested': '3', 'reason': 'ظرف'}


class SelfApprovalTests(HrBase):

    def setUp(self):
        super().setUp()
        self.sup.hr_code = 'HR7001'
        self.sup.save(update_fields=['hr_code'])
        r = self.sup_c.post('/api/hr/leave-requests/submit/', LEAVE, format='json')     # the supervisor's own leave
        self.assertEqual(r.status_code, 201, r.content)
        self.ar = ApprovalRequest.objects.get(pk=r.data['approval_request'])

    def test_a_requester_cannot_approve_their_own_request(self):
        with self.assertRaises(ApprovalError):
            ApprovalService.decide(request=self.ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.sup)
        r = self.sup_c.post(f'/api/approvals/requests/{self.ar.pk}/decide/', {'decision': 'approved'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.ar.refresh_from_db()
        self.assertFalse(self.ar.decisions.filter(decision=ApprovalDecision.DECISION_APPROVED).exists())

    def test_another_eligible_approver_still_approves(self):
        _, sup2, _ = make_user('hr_sup2', role='supervisor', branch=self.branch)
        ApprovalService.decide(request=self.ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=sup2)
        self.ar.refresh_from_db()
        self.assertTrue(self.ar.decisions.filter(decided_by=sup2, decision=ApprovalDecision.DECISION_APPROVED).exists())

    def test_a_requester_can_still_reject_their_own_request(self):
        ApprovalService.decide(request=self.ar, decision=ApprovalDecision.DECISION_REJECTED, decided_by=self.sup)
        self.ar.refresh_from_db()
        self.assertEqual(self.ar.status, ApprovalRequest.STATUS_REJECTED)
