"""
apps/tests/test_hr.py

End-to-end tests for the HR + approvals modules (leave, permits, overtime,
salary advance, expense claims) and the generic approval engine that drives them.

Covers the integration seams that were previously broken/added:
  - submit goes through the `…/submit/` action (bare collection POST is 405)
  - full multi-step approval loop deducts leave balance via the outcome signal
  - cancel actions on every request type; cancel gated to draft/submitted
  - Permit (اذن مأمورية single-step / اذن تعديل شيفت two-step) approval + validation
  - staff_code + return_to_work_date serialization
  - approvals inbox `pending/`, comma-status history filter, and RBAC gating
  - audit rows written with user = StaffProfile
"""
import datetime
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.approvals.models import ApprovalDecision, ApprovalRequest
from apps.approvals.service import ApprovalService
from apps.audit.models import AuditLog
from apps.hr.models import LeaveBalance, LeaveRequest, OvertimeRequest, Permit
from apps.tests.factories import make_user, make_branch, make_branch2


def _seed():
    out = StringIO()
    call_command('seed_hr_config', stdout=out)
    call_command('seed_approval_workflows', stdout=out)


class HrBase(TestCase):
    def setUp(self):
        _seed()
        self.branch = make_branch()
        # employee, supervisor (same branch), admin (any branch)
        _, self.emp, self.emp_c = make_user('hr_emp', role='salesperson', branch=self.branch)
        _, self.sup, self.sup_c = make_user('hr_sup', role='supervisor', branch=self.branch)
        _, self.adm, self.adm_c = make_user('hr_adm', role='admin', branch=self.branch)
        self.emp.softech_user_id = '5049'
        self.emp.hr_code = 'HR5049'
        self.emp.save(update_fields=['softech_user_id', 'hr_code'])


# ── Leave ─────────────────────────────────────────────────────────────────────

class LeaveFlowTests(HrBase):
    def _submit(self, **over):
        payload = {
            'leave_type_code': 'annual',
            'start_date': '2026-08-01', 'end_date': '2026-08-03',
            'return_to_work_date': '2026-08-05',
            'days_requested': '3', 'reason': 'ظرف',
        }
        payload.update(over)
        return self.emp_c.post('/api/hr/leave-requests/submit/', payload, format='json')

    def test_bare_collection_post_is_405(self):
        # Regression: creation must go through /submit/, not the list endpoint.
        r = self.emp_c.post('/api/hr/leave-requests/', {'leave_type_code': 'annual'}, format='json')
        self.assertEqual(r.status_code, 405)

    def test_submit_creates_pending_approval_with_enriched_fields(self):
        r = self._submit()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['status'], 'submitted')
        self.assertEqual(r.data['staff_code'], '5049')
        self.assertEqual(r.data['return_to_work_date'], '2026-08-05')
        ar = ApprovalRequest.objects.get(pk=r.data['approval_request'])
        self.assertEqual(ar.status, 'pending')
        self.assertEqual(ar.current_step_order, 1)

    def test_full_approval_loop_deducts_balance(self):
        r = self._submit()
        ar = ApprovalRequest.objects.get(pk=r.data['approval_request'])
        # Step 1 — branch supervisor
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.sup)
        ar.refresh_from_db()
        self.assertEqual(ar.status, 'in_review')
        self.assertEqual(ar.current_step_order, 2)
        # Step 2 — admin
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.adm)
        ar.refresh_from_db()
        leave = LeaveRequest.objects.get(pk=r.data['id'])
        self.assertEqual(ar.status, 'approved')
        self.assertEqual(leave.status, 'approved')
        bal = LeaveBalance.objects.get(staff=self.emp, leave_type=leave.leave_type, year=leave.start_date.year)
        self.assertEqual(float(bal.consumed_days), 3.0)

    def test_reject_marks_leave_rejected(self):
        r = self._submit()
        ar = ApprovalRequest.objects.get(pk=r.data['approval_request'])
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_REJECTED, decided_by=self.sup)
        self.assertEqual(LeaveRequest.objects.get(pk=r.data['id']).status, 'rejected')

    def test_cancel_then_cannot_cancel_again(self):
        r = self._submit()
        leave_id = r.data['id']
        ok = self.emp_c.post(f'/api/hr/leave-requests/{leave_id}/cancel/')
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(LeaveRequest.objects.get(pk=leave_id).status, 'cancelled')
        again = self.emp_c.post(f'/api/hr/leave-requests/{leave_id}/cancel/')
        self.assertEqual(again.status_code, 400)

    def test_end_before_start_rejected(self):
        r = self._submit(start_date='2026-08-10', end_date='2026-08-01')
        self.assertEqual(r.status_code, 400)


# ── Permits (اذن مأمورية / اذن تعديل شيفت) ───────────────────────────────────────

class PermitFlowTests(HrBase):
    def _submit(self, **over):
        payload = {
            'permit_type': 'mamoriya', 'date': '2026-07-10',
            'time_from': '10:00', 'time_to': '13:00',
            'destination': 'المخزن الرئيسي', 'reason': 'توصيل',
        }
        payload.update(over)
        return self.emp_c.post('/api/hr/permits/submit/', payload, format='json')

    def test_mamoriya_single_step_supervisor_approval(self):
        r = self._submit()
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['permit_type_display'], 'اذن مأمورية')
        self.assertEqual(r.data['staff_code'], '5049')
        ar = ApprovalRequest.objects.get(pk=r.data['approval_request'])
        self.assertEqual(ar.workflow.code, 'mission_permit')
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.sup)
        self.assertEqual(Permit.objects.get(pk=r.data['id']).status, 'approved')

    def test_mamoriya_requires_destination(self):
        r = self._submit(destination='')
        self.assertEqual(r.status_code, 400)

    def test_shift_change_two_step_supervisor_then_admin(self):
        r = self._submit(permit_type='shift_change', destination='', time_from='14:00', time_to='22:00')
        self.assertEqual(r.status_code, 201, r.content)
        ar = ApprovalRequest.objects.get(pk=r.data['approval_request'])
        self.assertEqual(ar.workflow.code, 'shift_change')
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.sup)
        ar.refresh_from_db()
        self.assertEqual(ar.current_step_order, 2)
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.adm)
        self.assertEqual(Permit.objects.get(pk=r.data['id']).status, 'approved')

    def test_time_to_before_from_rejected(self):
        r = self._submit(time_from='13:00', time_to='10:00')
        self.assertEqual(r.status_code, 400)

    def test_cancel_permit(self):
        r = self._submit()
        pid = r.data['id']
        ok = self.emp_c.post(f'/api/hr/permits/{pid}/cancel/')
        self.assertEqual(ok.status_code, 200, ok.content)
        self.assertEqual(Permit.objects.get(pk=pid).status, 'cancelled')


# ── Nominated approvers + on-behalf-of + HR code ────────────────────────────────

class NominatedApproverTests(HrBase):
    def _submit_permit(self, approver_ids):
        return self.emp_c.post('/api/hr/permits/submit/', {
            'permit_type': 'mamoriya', 'date': '2026-07-10',
            'time_from': '10:00', 'time_to': '13:00',
            'destination': 'المخزن', 'reason': 'توصيل',
            'approver_ids': approver_ids,
        }, format='json')

    def test_nominated_step_runs_after_mandatory_manager(self):
        _, nom, nom_c = make_user('hr_nom', role='pharmacist', branch=self.branch)
        r = self._submit_permit([nom.pk])
        self.assertEqual(r.status_code, 201, r.content)
        ar = ApprovalRequest.objects.get(pk=r.data['approval_request'])
        # Mandatory supervisor step first
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.sup)
        ar.refresh_from_db()
        self.assertEqual(ar.status, 'in_review')  # now on the nominated step
        # The nominee is eligible; any one of them approving closes it
        self.assertIn(ar.pk, [x['id'] for x in nom_c.get('/api/approvals/requests/pending/').data])
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=nom)
        self.assertEqual(Permit.objects.get(pk=r.data['id']).status, 'approved')

    def test_non_nominee_cannot_decide_nominated_step(self):
        _, nom, _ = make_user('hr_nom2', role='pharmacist', branch=self.branch)
        _, outsider, _ = make_user('hr_out', role='pharmacist', branch=self.branch)
        r = self._submit_permit([nom.pk])
        ar = ApprovalRequest.objects.get(pk=r.data['approval_request'])
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.sup)
        from apps.approvals.service import ApprovalError
        with self.assertRaises(ApprovalError):
            ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=outsider)

    def test_no_nominees_autoskips_to_approved_after_manager(self):
        # No approver_ids → the trailing nominated step auto-skips.
        r = self.emp_c.post('/api/hr/permits/submit/', {
            'permit_type': 'mamoriya', 'date': '2026-07-10',
            'time_from': '10:00', 'time_to': '13:00', 'destination': 'x', 'reason': 'y',
        }, format='json')
        ar = ApprovalRequest.objects.get(pk=r.data['approval_request'])
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.sup)
        self.assertEqual(Permit.objects.get(pk=r.data['id']).status, 'approved')


class OnBehalfAndHrCodeTests(HrBase):
    def test_file_permit_for_non_login_employee(self):
        # Office boy: no StaffProfile, identified by HR code + typed name.
        r = self.emp_c.post('/api/hr/permits/submit/', {
            'permit_type': 'mamoriya', 'date': '2026-07-10',
            'time_from': '09:00', 'time_to': '10:00', 'destination': 'البنك',
            'reason': 'إيداع', 'employee_hr_code': 'OB-001', 'employee_name': 'عم محمود',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        p = Permit.objects.get(pk=r.data['id'])
        self.assertIsNone(p.staff_id)                 # no login subject
        self.assertEqual(p.employee_hr_code, 'OB-001')
        self.assertEqual(p.employee_name, 'عم محمود')
        self.assertEqual(p.submitted_by_id, self.emp.pk)  # filed from emp's session

    def test_hr_code_required_when_subject_has_none(self):
        # A submitter without hr_code, filing for themselves, must supply one.
        _, noc, noc_c = make_user('hr_noc', role='salesperson', branch=self.branch)
        r = noc_c.post('/api/hr/permits/submit/', {
            'permit_type': 'mamoriya', 'date': '2026-07-10',
            'time_from': '09:00', 'time_to': '10:00', 'destination': 'x', 'reason': 'y',
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_self_service_prefills_hr_code_from_profile(self):
        # emp has hr_code on profile → no need to type it.
        r = self.emp_c.post('/api/hr/permits/submit/', {
            'permit_type': 'mamoriya', 'date': '2026-07-10',
            'time_from': '09:00', 'time_to': '10:00', 'destination': 'x', 'reason': 'y',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(Permit.objects.get(pk=r.data['id']).employee_hr_code, 'HR5049')


# ── Overtime + expense validation/cancel ────────────────────────────────────────

class OtherRequestTests(HrBase):
    def test_overtime_submit_and_cancel(self):
        r = self.emp_c.post('/api/hr/overtime/submit/',
                            {'date': '2026-07-05', 'hours': '2', 'reason': 'x'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        oid = r.data['id']
        self.assertEqual(r.data['staff_code'], '5049')
        ok = self.emp_c.post(f'/api/hr/overtime/{oid}/cancel/')
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(OvertimeRequest.objects.get(pk=oid).status, 'cancelled')

    def test_expense_mamoriya_requires_trip_destination(self):
        r = self.emp_c.post('/api/hr/expense-claims/submit/', {
            'category': 'mamoriya', 'expense_date': '2026-07-01',
            'amount': '100', 'description': 'd',
        }, format='json')
        self.assertEqual(r.status_code, 400)

    def test_expense_transport_ok(self):
        r = self.emp_c.post('/api/hr/expense-claims/submit/', {
            'category': 'transport', 'expense_date': '2026-07-01',
            'amount': '100', 'description': 'مواصلات',
        }, format='json')
        self.assertEqual(r.status_code, 201, r.content)


# ── Approvals inbox + RBAC ───────────────────────────────────────────────────────

class ApprovalsInboxTests(HrBase):
    def _make_pending_leave(self):
        r = self.emp_c.post('/api/hr/leave-requests/submit/', {
            'leave_type_code': 'annual', 'start_date': '2026-08-01',
            'end_date': '2026-08-03', 'days_requested': '3', 'reason': 'r',
        }, format='json')
        return ApprovalRequest.objects.get(pk=r.data['approval_request'])

    def test_pending_returns_only_awaiting_my_action(self):
        ar = self._make_pending_leave()
        # Supervisor is the step-1 approver → sees it
        r = self.sup_c.get('/api/approvals/requests/pending/')
        self.assertEqual(r.status_code, 200)
        self.assertIn(ar.pk, [x['id'] for x in r.data])

    def test_history_accepts_comma_status_list(self):
        ar = self._make_pending_leave()
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.sup)
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.adm)
        r = self.adm_c.get('/api/approvals/requests/', {'status': 'approved,rejected'})
        self.assertEqual(r.status_code, 200)
        results = r.data.get('results', r.data)
        self.assertIn(ar.pk, [x['id'] for x in results])

    def test_salesperson_blocked_from_approvals_inbox(self):
        # emp is a salesperson → not an approver role
        r = self.emp_c.get('/api/approvals/requests/pending/')
        self.assertEqual(r.status_code, 403)

    def test_supervisor_allowed_in_approvals_inbox(self):
        r = self.sup_c.get('/api/approvals/requests/pending/')
        self.assertEqual(r.status_code, 200)

    def test_cross_branch_supervisor_not_eligible(self):
        ar = self._make_pending_leave()
        other = make_branch2()
        _, osup, _ = make_user('hr_sup2', role='supervisor', branch=other)
        # decide by a supervisor from another branch must raise (restrict_to_branch)
        from apps.approvals.service import ApprovalError
        with self.assertRaises(ApprovalError):
            ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=osup)


# ── Audit trail ─────────────────────────────────────────────────────────────────

class AuditTrailTests(HrBase):
    def test_audit_rows_written_with_staffprofile(self):
        r = self.emp_c.post('/api/hr/leave-requests/submit/', {
            'leave_type_code': 'annual', 'start_date': '2026-08-01',
            'end_date': '2026-08-03', 'days_requested': '3', 'reason': 'r',
        }, format='json')
        ar = ApprovalRequest.objects.get(pk=r.data['approval_request'])
        ApprovalService.decide(request=ar, decision=ApprovalDecision.DECISION_APPROVED, decided_by=self.sup)
        # HR submit + approval submit + decision all write audit rows tied to a StaffProfile
        self.assertTrue(AuditLog.objects.filter(user=self.emp, model_name='LeaveRequest').exists())
        self.assertTrue(AuditLog.objects.filter(model_name='ApprovalRequest', action='approval_submitted').exists())
        self.assertTrue(AuditLog.objects.filter(user=self.sup, action='approval_decision_approved').exists())
