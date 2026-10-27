"""
apps/approvals/service.py

ApprovalService — the only entry point other modules should call.

All state transitions live here.  Views and management commands call
these methods; they never touch model fields directly.

Notification integration:
  Uses apps.notifications.models.Notification (existing system).
  Never creates its own notification channel.

Audit integration:
  Writes to apps.audit.models.AuditLog on submit / decide / cancel.
"""
import logging
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from .models import (
    ApprovalWorkflowDefinition,
    ApprovalRequest,
    ApprovalDecision,
    ApprovalEscalationLog,
)

logger = logging.getLogger('elrezeiky.approvals')


class ApprovalError(Exception):
    """Raised for illegal state transitions or missing configuration."""


class ApprovalService:

    # ── Submit ────────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def submit(
        cls,
        *,
        workflow_code: str,
        subject_object,               # any Django model instance
        title: str,
        requested_by,                 # StaffProfile
        body: str = '',
        context_data: dict = None,
        nominated_approvers=None,     # iterable[StaffProfile] for nominated steps
    ) -> ApprovalRequest:
        """
        Create and submit a new approval request.

        Returns the ApprovalRequest (status=pending, current_step_order=first
        actionable step). Raises ApprovalError if the workflow has no active steps.
        """
        workflow = ApprovalWorkflowDefinition.get(workflow_code)
        first_step = workflow.steps.order_by('order').first()
        if not first_step:
            raise ApprovalError(f"Workflow '{workflow_code}' has no steps defined.")

        ct = ContentType.objects.get_for_model(subject_object)
        due_at = None
        if workflow.sla_hours:
            due_at = timezone.now() + timezone.timedelta(hours=workflow.sla_hours)

        req = ApprovalRequest.objects.create(
            workflow=workflow,
            requested_by=requested_by,
            title=title,
            body=body,
            content_type=ct,
            object_id=subject_object.pk,
            context_data=context_data or {},
            status=ApprovalRequest.STATUS_PENDING,
            current_step_order=first_step.order,
            due_at=due_at,
        )
        if nominated_approvers:
            req.nominated_approvers.set(list(nominated_approvers))

        # Skip a leading nominated step the requester left empty, then notify
        # whoever the current (landing) step routes to.
        cls._autoskip_empty_nominated(req)
        req.refresh_from_db()
        if req.is_terminal:
            cls._notify_requester(req, 'approved')
        else:
            cls._notify_step_approvers(req, req.current_step)

        cls._audit(req, 'approval_submitted', requested_by)
        logger.info('ApprovalRequest %s submitted for workflow %s', req.pk, workflow_code)
        return req

    # ── Decide ────────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def decide(
        cls,
        *,
        request: ApprovalRequest,
        decision: str,                 # ApprovalDecision.DECISION_* constant
        decided_by,                    # StaffProfile
        notes: str = '',
        delegated_to=None,             # StaffProfile, only when decision=delegated
    ) -> ApprovalDecision:
        """
        Record a decision on the current step of an ApprovalRequest.

        Advances the workflow:
          - approved + more steps  → moves to next step, notifies next approvers
          - approved + last step   → closes request as STATUS_APPROVED
          - rejected               → closes request as STATUS_REJECTED (if reject_terminates)
                                     OR advances to next step (if step.on_reject='next_step')
          - delegated              → re-notifies delegated_to user, does not advance step
          - returned               → re-notifies requester for revision (stays in_review)
        """
        if request.is_terminal:
            raise ApprovalError(f"Request {request.pk} is already in terminal state '{request.status}'.")

        step = request.current_step
        if step is None:
            raise ApprovalError(f"Request {request.pk} has no step at order {request.current_step_order}.")

        cls._assert_eligible(request, step, decided_by)

        dec = ApprovalDecision.objects.create(
            request=request,
            step=step,
            step_order=step.order,
            step_name=step.name_ar,
            decision=decision,
            decided_by=decided_by,
            notes=notes,
            delegated_to=delegated_to,
        )

        if decision == ApprovalDecision.DECISION_APPROVED:
            cls._handle_approval(request, step)
        elif decision == ApprovalDecision.DECISION_REJECTED:
            cls._handle_rejection(request, step)
        elif decision == ApprovalDecision.DECISION_DELEGATED:
            cls._handle_delegation(request, step, delegated_to)
        elif decision == ApprovalDecision.DECISION_RETURNED:
            cls._handle_return(request)

        cls._audit(request, f'approval_decision_{decision}', decided_by)
        return dec

    # ── Cancel ────────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def cancel(cls, *, request: ApprovalRequest, cancelled_by, reason: str = '') -> None:
        """
        Cancel an in-flight request.  Only the requester or an admin may cancel.
        """
        if request.is_terminal:
            raise ApprovalError(f"Request {request.pk} is already terminal.")

        is_requester = request.requested_by_id == cancelled_by.pk
        is_admin = cancelled_by.role == 'admin'
        if not (is_requester or is_admin):
            raise ApprovalError("Only the requester or an admin can cancel an approval request.")

        request.status         = ApprovalRequest.STATUS_CANCELLED
        request.completed_at   = timezone.now()
        request.completion_note = reason
        request.save(update_fields=['status', 'completed_at', 'completion_note'])

        cls._notify_requester(request, 'cancelled', body=reason)
        cls._audit(request, 'approval_cancelled', cancelled_by)

    # ── Query helpers ─────────────────────────────────────────────────────────

    @classmethod
    def pending_for(cls, staff_profile):
        """
        Return all ApprovalRequests currently awaiting action from this user.

        A request awaits this user if:
          - The current step's approver_user matches, OR
          - The current step's approver_role matches this user's role
            (and restrict_to_branch is satisfied)
        """
        from apps.approvals.models import ApprovalRequest, ApprovalStepDefinition
        active = ApprovalRequest.objects.filter(
            status__in=[ApprovalRequest.STATUS_PENDING, ApprovalRequest.STATUS_IN_REVIEW]
        ).select_related('workflow', 'requested_by', 'requested_by__branch')

        result = []
        for req in active:
            step = req.current_step
            if step is None:
                continue
            eligible = cls._eligible_for(req, step)
            if eligible.filter(pk=staff_profile.pk).exists():
                result.append(req)
        return result

    @classmethod
    def for_subject(cls, subject_object):
        """Return all ApprovalRequests linked to a specific domain object."""
        ct = ContentType.objects.get_for_model(subject_object)
        return ApprovalRequest.objects.filter(
            content_type=ct, object_id=subject_object.pk
        ).order_by('-requested_at')

    # ── Escalation (called by scheduled job) ──────────────────────────────────

    @classmethod
    def escalate_overdue_steps(cls):
        """
        Re-notify approvers on steps that have exceeded escalation_hours.
        Called by APScheduler (configured in apps/approvals/scheduler.py).
        """
        from django.db.models import F
        now = timezone.now()
        active = ApprovalRequest.objects.filter(
            status__in=[ApprovalRequest.STATUS_PENDING, ApprovalRequest.STATUS_IN_REVIEW]
        ).select_related('workflow', 'requested_by')

        count = 0
        for req in active:
            step = req.current_step
            if step is None or step.escalation_hours == 0:
                continue

            # Find the last escalation or submission time
            last_escalation = req.escalations.filter(step_order=step.order).order_by('-escalated_at').first()
            reference_time = last_escalation.escalated_at if last_escalation else req.requested_at
            hours_elapsed = (now - reference_time).total_seconds() / 3600

            if hours_elapsed < step.escalation_hours:
                continue

            if step.is_optional and hours_elapsed >= step.escalation_hours * 2:
                # Auto-approve optional step that has been waiting twice the escalation window
                cls._auto_approve_step(req, step)
            else:
                notified = cls._notify_step_approvers(req, step, is_escalation=True)
                ApprovalEscalationLog.objects.create(
                    request=req,
                    step_order=step.order,
                    notified_users=[u.pk for u in notified],
                    note=f'تصعيد تلقائي بعد {hours_elapsed:.1f} ساعة',
                )
                count += 1

        logger.info('Escalation job: %d requests escalated', count)
        return count

    # ── Internal helpers ──────────────────────────────────────────────────────

    @classmethod
    def _handle_approval(cls, request: ApprovalRequest, step) -> None:
        next_step = request.workflow.steps.filter(order__gt=step.order).order_by('order').first()
        if next_step:
            request.status = ApprovalRequest.STATUS_IN_REVIEW
            request.current_step_order = next_step.order
            request.save(update_fields=['status', 'current_step_order'])
            # A nominated next step with no nominees is auto-skipped.
            cls._autoskip_empty_nominated(request)
            request.refresh_from_db()
            if request.is_terminal:
                cls._notify_requester(request, 'approved')
            else:
                cls._notify_step_approvers(request, request.current_step)
        else:
            request.status       = ApprovalRequest.STATUS_APPROVED
            request.completed_at = timezone.now()
            request.save(update_fields=['status', 'completed_at'])
            cls._notify_requester(request, 'approved')

    @classmethod
    def _autoskip_empty_nominated(cls, request: ApprovalRequest) -> None:
        """Advance past any leading nominated step the requester left empty,
        recording an auto-approve decision for each so the audit trail is intact.
        Closes the request as approved only if no further steps remain (a
        nominated-only workflow) — HR workflows always keep a role step after."""
        while True:
            step = request.current_step
            if step is None or not step.use_nominated_approvers:
                return
            if request.nominated_approvers.exists():
                return
            ApprovalDecision.objects.create(
                request=request, step=step, step_order=step.order, step_name=step.name_ar,
                decision=ApprovalDecision.DECISION_AUTO_APPROVED, decided_by=None,
                notes='تخطٍّ تلقائي — لم يحدد مقدّم الطلب معتمِدين',
            )
            next_step = request.workflow.steps.filter(order__gt=step.order).order_by('order').first()
            if next_step:
                request.status = ApprovalRequest.STATUS_IN_REVIEW
                request.current_step_order = next_step.order
                request.save(update_fields=['status', 'current_step_order'])
            else:
                request.status = ApprovalRequest.STATUS_APPROVED
                request.completed_at = timezone.now()
                request.save(update_fields=['status', 'completed_at'])
                return

    @classmethod
    def _eligible_for(cls, request: ApprovalRequest, step):
        """Approvers who may act on `step` of `request` — the requester's
        nominees for a nominated step, else the step's role/user rule."""
        if step.use_nominated_approvers:
            return request.nominated_approvers.filter(is_active=True)
        return step.eligible_approvers(requester_branch_id=request.requested_by.branch_id)

    @classmethod
    def _handle_rejection(cls, request: ApprovalRequest, step) -> None:
        if step.on_reject == 'terminate' or request.workflow.reject_terminates:
            request.status       = ApprovalRequest.STATUS_REJECTED
            request.completed_at = timezone.now()
            request.save(update_fields=['status', 'completed_at'])
            cls._notify_requester(request, 'rejected')
        elif step.on_reject == 'next_step':
            cls._handle_approval(request, step)   # advance despite rejection
        elif step.on_reject == 'return_prev':
            cls._handle_return(request)

    @classmethod
    def _handle_delegation(cls, request: ApprovalRequest, step, delegated_to) -> None:
        if delegated_to is None:
            raise ApprovalError('delegated_to is required for delegation decisions.')
        cls._send_notification(
            recipients=[delegated_to],
            title=f'تفويض موافقة: {request.title}',
            body=f'تم تفويض طلب موافقة إليك في الخطوة: {step.name_ar}',
            approval_request=request,
        )

    @classmethod
    def _handle_return(cls, request: ApprovalRequest) -> None:
        request.status = ApprovalRequest.STATUS_IN_REVIEW
        request.save(update_fields=['status'])
        cls._notify_requester(request, 'returned')

    @classmethod
    def _auto_approve_step(cls, request: ApprovalRequest, step) -> None:
        ApprovalDecision.objects.create(
            request=request,
            step=step,
            step_order=step.order,
            step_name=step.name_ar,
            decision=ApprovalDecision.DECISION_AUTO_APPROVED,
            decided_by=None,
            notes='اعتماد تلقائي بعد انتهاء مهلة الاستجابة (خطوة اختيارية)',
        )
        cls._handle_approval(request, step)

    @classmethod
    def _assert_eligible(cls, request, step, decided_by) -> None:
        eligible = cls._eligible_for(request, step)
        if not eligible.filter(pk=decided_by.pk).exists():
            raise ApprovalError(
                f"User '{decided_by.full_name}' is not eligible to decide step '{step.name_ar}'."
            )

    @classmethod
    def _notify_step_approvers(cls, request: ApprovalRequest, step, is_escalation=False) -> list:
        approvers = list(cls._eligible_for(request, step))
        prefix = '🔔 تصعيد — ' if is_escalation else ''
        cls._send_notification(
            recipients=approvers,
            title=f'{prefix}طلب موافقة: {request.title}',
            body=f'مطلوب موافقتك على: {step.name_ar}\nمقدم الطلب: {request.requested_by.full_name}',
            approval_request=request,
        )
        return approvers

    @classmethod
    def _notify_requester(cls, request: ApprovalRequest, outcome: str, body: str = '') -> None:
        LABELS = {
            'approved':  ('✅ تمت الموافقة', 'تمت الموافقة على طلبك'),
            'rejected':  ('❌ تم الرفض',     'تم رفض طلبك'),
            'cancelled': ('🚫 تم الإلغاء',   'تم إلغاء طلبك'),
            'returned':  ('↩️ إعادة للمراجعة', 'تم إعادة طلبك للمراجعة'),
        }
        title_prefix, default_body = LABELS.get(outcome, ('🔔 تحديث', ''))
        cls._send_notification(
            recipients=[request.requested_by],
            title=f'{title_prefix}: {request.title}',
            body=body or default_body,
            approval_request=request,
        )

    @classmethod
    def _send_notification(cls, *, recipients, title, body, approval_request) -> None:
        try:
            from apps.notifications.models import Notification
            for recipient in recipients:
                Notification.objects.create(
                    recipient=recipient,
                    notification_type='system',
                    title=title,
                    body=body,
                    dedup_key=f'approval_{approval_request.pk}_{approval_request.status}_{recipient.pk}',
                )
        except Exception:
            logger.exception('Failed to send approval notification for request %s', approval_request.pk)

    @classmethod
    def _audit(cls, request: ApprovalRequest, action: str, actor) -> None:
        try:
            from apps.audit.models import AuditLog
            AuditLog.objects.create(
                user=actor,                       # actor is a StaffProfile (AuditLog.user FK target)
                action=action,
                model_name='ApprovalRequest',
                object_id=str(request.pk),
                new_data={
                    'workflow': request.workflow.code,
                    'status':   request.status,
                    'step':     request.current_step_order,
                    'title':    request.title,
                },
            )
        except Exception:
            logger.exception('Failed to write audit log for ApprovalRequest %s', request.pk)
