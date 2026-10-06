"""
apps/hr/service.py

HrService — single entry point for all HR state transitions.

Approval integration:
  Every submitted request creates an ApprovalRequest via ApprovalService.submit().
  When the ApprovalRequest closes (approved/rejected), the calling view
  or a signal handler calls HrService.on_approval_outcome() to sync the
  HR record's status and trigger downstream finance entries.

Finance integration:
  On expense_claim approval → creates apps.finance.ExpenseRecord.
  On salary_advance approval → creates apps.finance.ExpenseRecord (category='payroll').
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    LeaveType, LeaveBalance, LeaveRequest,
    ShiftTemplate, ShiftAssignment,
    OvertimeRequest, SalaryAdvance, ExpenseClaim,
    Permit,
)

logger = logging.getLogger('elrezeiky.hr')


class HrError(Exception):
    pass


class HrService:

    # ── Subject / submitter identity helper ────────────────────────────────────

    @staticmethod
    def _identity(*, submitted_by, subject_staff=None, employee_hr_code='',
                  employee_name='', softech_code=''):
        """Build the shared identity kwargs + a display name for titles.

        The subject may be a StaffProfile (self or another user) or a non-login
        employee (office boy) identified only by HR code + typed name.
        """
        name = (employee_name or (subject_staff.full_name if subject_staff else '')).strip()
        code = (softech_code or (subject_staff.softech_user_id if subject_staff else '')).strip()
        hr_code = (employee_hr_code or (subject_staff.hr_code if subject_staff else '')).strip()
        if not hr_code:
            raise HrError('كود الموارد البشرية مطلوب.')
        kwargs = {
            'staff':            subject_staff,
            'submitted_by':     submitted_by,
            'employee_hr_code': hr_code,
            'employee_name':    name,
            'softech_code':     code,
        }
        return kwargs, (name or hr_code)

    # ── Leave ─────────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def submit_leave(cls, *, submitted_by, leave_type_code: str, start_date, end_date,
                     days: Decimal, reason: str = '', return_to_work_date=None,
                     subject_staff=None, employee_hr_code='', employee_name='',
                     softech_code='', nominated_approvers=None) -> LeaveRequest:
        leave_type = LeaveType.objects.get(code=leave_type_code, is_active=True)
        identity, who = cls._identity(
            submitted_by=submitted_by, subject_staff=subject_staff,
            employee_hr_code=employee_hr_code, employee_name=employee_name, softech_code=softech_code,
        )

        # Balance is only tracked for employees with a system profile.
        if subject_staff and leave_type.accrues_balance:
            balance = cls._get_or_create_balance(subject_staff, leave_type)
            if balance.remaining_days < days:
                raise HrError(
                    f'الرصيد المتبقي ({balance.remaining_days} يوم) أقل من الأيام المطلوبة ({days} يوم).'
                )

        if days > leave_type.max_days_per_request:
            raise HrError(f'الحد الأقصى للطلب الواحد هو {leave_type.max_days_per_request} أيام.')

        leave = LeaveRequest.objects.create(
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            return_to_work_date=return_to_work_date,
            days_requested=days,
            reason=reason,
            status=LeaveRequest.STATUS_SUBMITTED,
            **identity,
        )

        from apps.approvals.service import ApprovalService
        approval = ApprovalService.submit(
            workflow_code=leave_type.approval_workflow_code,
            subject_object=leave,
            title=f'طلب إجازة {leave_type.name_ar} — {who}',
            requested_by=submitted_by,
            nominated_approvers=nominated_approvers,
            context_data={
                'leave_type': leave_type.code,
                'start_date': str(start_date),
                'end_date':   str(end_date),
                'days':       str(days),
            },
        )
        leave.approval_request = approval
        leave.save(update_fields=['approval_request'])

        cls._audit(leave, 'leave_submitted', submitted_by)
        return leave

    @classmethod
    @transaction.atomic
    def cancel_leave(cls, *, leave: LeaveRequest, cancelled_by) -> None:
        if leave.status not in (LeaveRequest.STATUS_DRAFT, LeaveRequest.STATUS_SUBMITTED):
            raise HrError('يمكن إلغاء الطلب فقط في حالة المسودة أو المُقدَّم.')
        leave.status = LeaveRequest.STATUS_CANCELLED
        leave.save(update_fields=['status'])

        if leave.approval_request:
            from apps.approvals.service import ApprovalService
            try:
                ApprovalService.cancel(request=leave.approval_request, cancelled_by=cancelled_by)
            except Exception:
                pass  # approval may already be terminal

    @classmethod
    @transaction.atomic
    def cancel_request(cls, *, obj, cancelled_by) -> None:
        """
        Cancel a still-open overtime / salary-advance / expense-claim request.
        Mirrors cancel_leave: only draft/submitted may be cancelled, and the
        linked ApprovalRequest (if any) is cancelled too.
        """
        if obj.status not in ('draft', 'submitted'):
            raise HrError('يمكن إلغاء الطلب فقط في حالة المسودة أو المُقدَّم.')
        obj.status = 'cancelled'
        obj.save(update_fields=['status'])

        approval = getattr(obj, 'approval_request', None)
        if approval:
            from apps.approvals.service import ApprovalService
            try:
                ApprovalService.cancel(request=approval, cancelled_by=cancelled_by)
            except Exception:
                pass  # approval may already be terminal

    # ── Overtime ─────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def submit_overtime(cls, *, submitted_by, branch, date, hours: Decimal, reason: str,
                        subject_staff=None, employee_hr_code='', employee_name='',
                        softech_code='', nominated_approvers=None) -> OvertimeRequest:
        identity, who = cls._identity(
            submitted_by=submitted_by, subject_staff=subject_staff,
            employee_hr_code=employee_hr_code, employee_name=employee_name, softech_code=softech_code,
        )
        ot = OvertimeRequest.objects.create(
            branch=branch, date=date, hours=hours, reason=reason, status='submitted',
            **identity,
        )
        from apps.approvals.service import ApprovalService
        approval = ApprovalService.submit(
            workflow_code='overtime',
            subject_object=ot,
            title=f'طلب عمل إضافي — {who} | {date}',
            requested_by=submitted_by,
            nominated_approvers=nominated_approvers,
            context_data={'date': str(date), 'hours': str(hours), 'reason': reason},
        )
        ot.approval_request = approval
        ot.save(update_fields=['approval_request'])
        return ot

    # ── Salary advance ────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def submit_salary_advance(cls, *, submitted_by, amount: Decimal, repayment_date, reason: str,
                              subject_staff=None, employee_hr_code='', employee_name='',
                              softech_code='', nominated_approvers=None) -> SalaryAdvance:
        identity, who = cls._identity(
            submitted_by=submitted_by, subject_staff=subject_staff,
            employee_hr_code=employee_hr_code, employee_name=employee_name, softech_code=softech_code,
        )
        advance = SalaryAdvance.objects.create(
            amount=amount, repayment_date=repayment_date, reason=reason,
            status='submitted', **identity,
        )
        from apps.approvals.service import ApprovalService
        approval = ApprovalService.submit(
            workflow_code='salary_advance',
            subject_object=advance,
            title=f'سلفة راتب — {who} | {amount:,.2f} ج.م',
            requested_by=submitted_by,
            nominated_approvers=nominated_approvers,
            context_data={'amount': str(amount), 'repayment_date': str(repayment_date)},
        )
        advance.approval_request = approval
        advance.save(update_fields=['approval_request'])
        return advance

    # ── Expense claim ─────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def submit_expense_claim(cls, *, submitted_by, branch, category: str, expense_date,
                              amount: Decimal, description: str, receipt=None, trip_data: dict = None,
                              subject_staff=None, employee_hr_code='', employee_name='',
                              softech_code='', nominated_approvers=None) -> ExpenseClaim:
        identity, who = cls._identity(
            submitted_by=submitted_by, subject_staff=subject_staff,
            employee_hr_code=employee_hr_code, employee_name=employee_name, softech_code=softech_code,
        )
        claim = ExpenseClaim.objects.create(
            branch=branch, category=category, expense_date=expense_date,
            amount=amount, description=description, receipt=receipt,
            status='submitted', **identity, **(trip_data or {}),
        )
        wf_code = 'mamoriya' if category == ExpenseClaim.CATEGORY_MAMORIYA else 'expense_claim'
        from apps.approvals.service import ApprovalService
        approval = ApprovalService.submit(
            workflow_code=wf_code,
            subject_object=claim,
            title=f'مطالبة مصروفات — {who} | {claim.get_category_display()} | {amount:,.2f} ج.م',
            requested_by=submitted_by,
            nominated_approvers=nominated_approvers,
            context_data={
                'category': category,
                'amount':   str(amount),
                'date':     str(expense_date),
            },
        )
        claim.approval_request = approval
        claim.save(update_fields=['approval_request'])
        return claim

    # ── Permits (اذن مأمورية / اذن تعديل شيفت) ─────────────────────────────────

    @classmethod
    @transaction.atomic
    def submit_permit(cls, *, submitted_by, branch, permit_type: str, date, time_from,
                      time_to=None, destination: str = '', reason: str = '',
                      subject_staff=None, employee_hr_code='', employee_name='',
                      softech_code='', nominated_approvers=None) -> Permit:
        identity, who = cls._identity(
            submitted_by=submitted_by, subject_staff=subject_staff,
            employee_hr_code=employee_hr_code, employee_name=employee_name, softech_code=softech_code,
        )
        permit = Permit.objects.create(
            branch=branch, permit_type=permit_type,
            date=date, time_from=time_from, time_to=time_to,
            destination=destination, reason=reason, status='submitted',
            **identity,
        )
        from apps.approvals.service import ApprovalService
        approval = ApprovalService.submit(
            workflow_code=permit.workflow_code,
            subject_object=permit,
            title=f'{permit.get_permit_type_display()} — {who} | {date}',
            requested_by=submitted_by,
            nominated_approvers=nominated_approvers,
            context_data={
                'permit_type': permit_type,
                'date':        str(date),
                'time_from':   str(time_from),
                'time_to':     str(time_to) if time_to else '',
                'destination': destination,
            },
        )
        permit.approval_request = approval
        permit.save(update_fields=['approval_request'])
        return permit

    # ── Approval outcome handler (called when ApprovalRequest closes) ─────────

    @classmethod
    @transaction.atomic
    def on_approval_outcome(cls, approval_request, outcome: str) -> None:
        """
        Called by views or a signal after ApprovalService.decide() closes a request.
        outcome: 'approved' | 'rejected'
        """
        # Leave
        if hasattr(approval_request, 'leave_request'):
            leave = approval_request.leave_request
            if outcome == 'approved':
                leave.status = LeaveRequest.STATUS_APPROVED
                leave.save(update_fields=['status'])
                cls._deduct_leave_balance(leave)
            else:
                leave.status = LeaveRequest.STATUS_REJECTED
                leave.save(update_fields=['status'])

        # Overtime
        elif hasattr(approval_request, 'overtime_request'):
            ot = approval_request.overtime_request
            ot.status = 'approved' if outcome == 'approved' else 'rejected'
            ot.save(update_fields=['status'])

        # Salary advance
        elif hasattr(approval_request, 'salary_advance'):
            adv = approval_request.salary_advance
            if outcome == 'approved':
                adv.status = 'approved'
                adv.save(update_fields=['status'])
                cls._create_finance_entry_for_advance(adv)
            else:
                adv.status = 'rejected'
                adv.save(update_fields=['status'])

        # Expense claim
        elif hasattr(approval_request, 'expense_claim'):
            claim = approval_request.expense_claim
            if outcome == 'approved':
                claim.status = 'approved'
                claim.save(update_fields=['status'])
                cls._create_finance_entry_for_claim(claim)
            else:
                claim.status = 'rejected'
                claim.save(update_fields=['status'])

        # Permit (mamoriya / shift change)
        elif hasattr(approval_request, 'permit'):
            permit = approval_request.permit
            permit.status = 'approved' if outcome == 'approved' else 'rejected'
            permit.save(update_fields=['status'])

    # ── Balance helpers ───────────────────────────────────────────────────────

    @classmethod
    def _get_or_create_balance(cls, staff, leave_type: LeaveType) -> LeaveBalance:
        year = timezone.now().year
        balance, created = LeaveBalance.objects.get_or_create(
            staff=staff, leave_type=leave_type, year=year,
            defaults={
                'entitled_days':   leave_type.max_days_per_year,
                'consumed_days':   Decimal('0'),
                'carried_forward': Decimal('0'),
            },
        )
        return balance

    @classmethod
    def _deduct_leave_balance(cls, leave: LeaveRequest) -> None:
        if not leave.staff or not leave.leave_type.accrues_balance:
            return  # non-login subjects (office boys) have no tracked balance
        balance = cls._get_or_create_balance(leave.staff, leave.leave_type)
        balance.consumed_days += leave.days_requested
        balance.save(update_fields=['consumed_days', 'updated_at'])

    # ── Finance entry creation ────────────────────────────────────────────────

    @classmethod
    def _create_finance_entry_for_advance(cls, advance: SalaryAdvance) -> None:
        try:
            from apps.finance.models import ExpenseRecord
            record = ExpenseRecord.objects.create(
                expense_date=timezone.now().date(),
                category='payroll',
                sub_category='salary_advance',
                branch=advance.staff.branch,
                amount=advance.amount,
                description=f'سلفة راتب — {advance.staff.full_name}',
                reference=f'HR-ADV-{advance.pk}',
            )
            advance.finance_record_id = record.pk
            advance.save(update_fields=['finance_record_id'])
        except Exception:
            logger.exception('Failed to create finance entry for salary advance %s', advance.pk)

    @classmethod
    def _create_finance_entry_for_claim(cls, claim: ExpenseClaim) -> None:
        try:
            from apps.finance.models import ExpenseRecord
            record = ExpenseRecord.objects.create(
                expense_date=claim.expense_date,
                category='other',
                sub_category=claim.category,
                branch=claim.branch,
                amount=claim.total_amount,
                description=claim.description or claim.get_category_display(),
                reference=f'HR-EXP-{claim.pk}',
            )
            claim.finance_record_id = record.pk
            claim.save(update_fields=['finance_record_id'])
        except Exception:
            logger.exception('Failed to create finance entry for expense claim %s', claim.pk)

    # ── Audit ─────────────────────────────────────────────────────────────────

    @classmethod
    def _audit(cls, obj, action: str, actor) -> None:
        try:
            from apps.audit.models import AuditLog
            AuditLog.objects.create(
                user=actor,                       # actor is a StaffProfile (AuditLog.user FK target)
                action=action,
                model_name=obj.__class__.__name__,
                object_id=str(obj.pk),
                new_data={'status': getattr(obj, 'status', '')},
            )
        except Exception:
            logger.exception('Failed to write HR audit log for %s %s', obj.__class__.__name__, obj.pk)
