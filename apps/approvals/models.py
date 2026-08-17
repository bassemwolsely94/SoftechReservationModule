"""
apps/approvals/models.py

Generic multi-step approval engine.

Usage by any module:

    from apps.approvals.service import ApprovalService

    # Submit a new request
    req = ApprovalService.submit(
        workflow_code='leave_request',
        subject_object=leave_instance,
        title='إجازة سنوية — أحمد محمود',
        requested_by=staff_profile,
        context_data={'days': 5, 'start': '2026-07-01'},
    )

    # Record a decision (approver's view)
    ApprovalService.decide(
        request=req,
        decision='approved',
        decided_by=manager_profile,
        notes='موافق',
    )

Models:
  ApprovalWorkflowDefinition  — reusable template (seeded per module)
  ApprovalStepDefinition      — ordered steps inside a template
  ApprovalRequest             — one live instance tied to any domain object
  ApprovalDecision            — immutable record of each step decision
  ApprovalEscalationLog       — audit trail of escalation events
"""
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from apps.users.models import ROLE_CHOICES


# ─────────────────────────────────────────────────────────────────────────────
# Workflow template (seeded once, rarely changed)
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalWorkflowDefinition(models.Model):
    """
    Reusable approval blueprint.  One row per approval type in the platform.
    Seeded by seed_approval_workflows; edited by admins via Django admin.
    """
    CATEGORY_CHOICES = [
        ('operational', 'تشغيلي'),
        ('hr',          'موارد بشرية'),
        ('finance',     'مالي'),
    ]

    code        = models.CharField(
        max_length=60, unique=True, db_index=True,
        verbose_name='الكود',
        help_text='مثال: leave_request | salary_advance | expense_claim | supplier_claim',
    )
    # Buckets the workflow for routing/filtering (e.g. the operational approvals
    # inbox shows category='operational' and excludes HR). Admin-editable.
    category    = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default='operational',
        db_index=True, verbose_name='التصنيف',
    )
    name        = models.CharField(max_length=120, verbose_name='الاسم')
    name_ar     = models.CharField(max_length=120, verbose_name='الاسم بالعربي')
    description = models.TextField(blank=True, verbose_name='الوصف')
    is_active   = models.BooleanField(default=True, db_index=True, verbose_name='مفعّل')

    # When True, any single rejection terminates the whole request (fail-fast).
    # When False, the requester is notified but remaining steps continue.
    reject_terminates = models.BooleanField(
        default=True,
        verbose_name='الرفض ينهي الطلب فوراً',
    )

    # Optional SLA: requests not completed within this many hours are flagged overdue.
    sla_hours = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name='SLA بالساعات',
        help_text='اترك فارغاً إذا لم يكن هناك SLA',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']
        verbose_name        = 'مسار موافقة'
        verbose_name_plural = 'مسارات الموافقة'

    def __str__(self):
        return f'[{self.code}] {self.name_ar}'

    @classmethod
    def get(cls, code: str) -> 'ApprovalWorkflowDefinition':
        return cls.objects.get(code=code, is_active=True)


class ApprovalStepDefinition(models.Model):
    """
    One step in a workflow.  Steps are evaluated in ascending `order`.

    Approver resolution (in priority order):
      1. approver_user  — a specific named person
      2. approver_role  — any active StaffProfile with that role
         (further narrowed to the requester's branch when restrict_to_branch=True)
    """
    DECISION_ON_REJECT = [
        ('terminate',    'إنهاء الطلب فوراً'),
        ('next_step',    'الانتقال للخطوة التالية'),
        ('return_prev',  'الإعادة للخطوة السابقة'),
    ]

    workflow = models.ForeignKey(
        ApprovalWorkflowDefinition, on_delete=models.CASCADE,
        related_name='steps', verbose_name='المسار',
    )
    order   = models.PositiveSmallIntegerField(verbose_name='الترتيب', db_index=True)
    name    = models.CharField(max_length=120, verbose_name='اسم الخطوة')
    name_ar = models.CharField(max_length=120, verbose_name='اسم الخطوة بالعربي')

    # Approver: role (any matching user) OR specific user (overrides role)
    approver_role = models.CharField(
        max_length=20, choices=ROLE_CHOICES,
        null=True, blank=True, db_index=True,
        verbose_name='دور المعتمِد',
    )
    approver_user = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_approval_steps',
        verbose_name='معتمِد محدد',
    )

    # When True, eligible approvers are only those in the requester's branch.
    restrict_to_branch = models.BooleanField(
        default=False,
        verbose_name='تقييد بفرع مقدم الطلب',
    )

    # When True, this step's approvers are NOT resolved from role/user above —
    # they come from the individual request's `nominated_approvers` (the requester
    # picks who signs). If the request nominated nobody, the step is auto-skipped.
    use_nominated_approvers = models.BooleanField(
        default=False,
        verbose_name='معتمِدون يختارهم مقدّم الطلب',
    )

    is_optional = models.BooleanField(
        default=False,
        verbose_name='اختيارية',
        help_text='إذا لم يستجب المعتمِد خلال مهلة التصعيد، تُعتمَد الخطوة تلقائياً',
    )

    # Escalation: re-notify approvers if no decision within N hours (0 = disabled)
    escalation_hours = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='ساعات التصعيد',
        help_text='0 = بدون تصعيد',
    )

    # What happens when this step is rejected
    on_reject = models.CharField(
        max_length=15, choices=DECISION_ON_REJECT, default='terminate',
        verbose_name='عند الرفض',
    )

    class Meta:
        ordering            = ['workflow', 'order']
        unique_together     = ('workflow', 'order')
        verbose_name        = 'خطوة موافقة'
        verbose_name_plural = 'خطوات الموافقة'

    def __str__(self):
        return f'{self.workflow.code} › Step {self.order}: {self.name_ar}'

    def eligible_approvers(self, requester_branch_id=None):
        """Return queryset of StaffProfile rows that may act on this step.

        For nominated steps, approvers live on the individual request, not the
        step definition — callers must resolve those via the request. Return an
        empty queryset here so a stray direct call never leaks all staff.
        """
        from apps.users.models import StaffProfile
        if self.use_nominated_approvers:
            return StaffProfile.objects.none()
        qs = StaffProfile.objects.filter(is_active=True)
        if self.approver_user_id:
            return qs.filter(pk=self.approver_user_id)
        if self.approver_role:
            qs = qs.filter(role=self.approver_role)
        if self.restrict_to_branch and requester_branch_id:
            qs = qs.filter(branch_id=requester_branch_id)
        return qs


# ─────────────────────────────────────────────────────────────────────────────
# Live request instance
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalRequest(models.Model):
    """
    One running approval instance tied to any domain object via GenericForeignKey.

    State machine:
      draft → pending → in_review → approved
                                  ↘ rejected
                      ↘ cancelled
                      ↘ expired    (SLA breached, flagged by scheduled job)
    """
    STATUS_DRAFT     = 'draft'
    STATUS_PENDING   = 'pending'
    STATUS_IN_REVIEW = 'in_review'
    STATUS_APPROVED  = 'approved'
    STATUS_REJECTED  = 'rejected'
    STATUS_CANCELLED = 'cancelled'
    STATUS_EXPIRED   = 'expired'

    STATUS_CHOICES = [
        (STATUS_DRAFT,     'مسودة'),
        (STATUS_PENDING,   'في الانتظار'),
        (STATUS_IN_REVIEW, 'قيد المراجعة'),
        (STATUS_APPROVED,  'معتمد'),
        (STATUS_REJECTED,  'مرفوض'),
        (STATUS_CANCELLED, 'ملغي'),
        (STATUS_EXPIRED,   'منتهي الصلاحية'),
    ]

    TERMINAL_STATUSES = {STATUS_APPROVED, STATUS_REJECTED, STATUS_CANCELLED, STATUS_EXPIRED}

    workflow     = models.ForeignKey(
        ApprovalWorkflowDefinition, on_delete=models.PROTECT,
        related_name='requests', verbose_name='المسار',
    )
    requested_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.PROTECT,
        related_name='approval_requests_submitted',
        verbose_name='مقدم الطلب',
    )
    requested_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='تاريخ الطلب')

    title        = models.CharField(max_length=255, verbose_name='العنوان')
    body         = models.TextField(blank=True, verbose_name='التفاصيل')

    # Generic link to the subject object (LeaveRequest, ExpenseClaim, SalaryAdvance…)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL,
        null=True, blank=True, verbose_name='نوع الكائن',
    )
    object_id    = models.PositiveIntegerField(null=True, blank=True, verbose_name='رقم الكائن')
    subject      = GenericForeignKey('content_type', 'object_id')

    # Snapshot of domain object at submission time (for audit)
    context_data = models.JSONField(default=dict, verbose_name='بيانات السياق')

    # Approvers picked by the requester, used by steps flagged
    # use_nominated_approvers. Any one of them approving satisfies that step.
    nominated_approvers = models.ManyToManyField(
        'users.StaffProfile', blank=True,
        related_name='nominated_approval_requests',
        verbose_name='المعتمِدون المختارون',
    )

    status       = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default=STATUS_DRAFT,
        db_index=True, verbose_name='الحالة',
    )
    current_step_order = models.PositiveSmallIntegerField(
        default=1, verbose_name='الخطوة الحالية',
    )

    # Computed SLA deadline (set on submission)
    due_at       = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name='الموعد النهائي')
    is_overdue   = models.BooleanField(default=False, db_index=True, verbose_name='متأخر')

    completed_at    = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الإنهاء')
    completion_note = models.TextField(blank=True, verbose_name='ملاحظة الإنهاء')

    class Meta:
        ordering            = ['-requested_at']
        verbose_name        = 'طلب موافقة'
        verbose_name_plural = 'طلبات الموافقة'
        indexes = [
            models.Index(fields=['status', 'current_step_order']),
            models.Index(fields=['workflow', 'status']),
            models.Index(fields=['requested_by', 'status']),
            models.Index(fields=['content_type', 'object_id']),
        ]

    def __str__(self):
        return f'[{self.get_status_display()}] {self.title}'

    @property
    def is_terminal(self):
        return self.status in self.TERMINAL_STATUSES

    @property
    def current_step(self):
        return self.workflow.steps.filter(order=self.current_step_order).first()

    def mark_overdue(self):
        if not self.is_overdue and self.due_at and timezone.now() > self.due_at:
            self.is_overdue = True
            self.save(update_fields=['is_overdue'])


# ─────────────────────────────────────────────────────────────────────────────
# Immutable decision record
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalDecision(models.Model):
    """
    Immutable.  One row per step per request decision.
    Never updated after creation.
    """
    DECISION_APPROVED      = 'approved'
    DECISION_REJECTED      = 'rejected'
    DECISION_DELEGATED     = 'delegated'
    DECISION_RETURNED      = 'returned'    # sent back to requester for revision
    DECISION_AUTO_APPROVED = 'auto_approved'  # optional step timed out

    DECISION_CHOICES = [
        (DECISION_APPROVED,      'معتمد'),
        (DECISION_REJECTED,      'مرفوض'),
        (DECISION_DELEGATED,     'تفويض'),
        (DECISION_RETURNED,      'إعادة للمراجعة'),
        (DECISION_AUTO_APPROVED, 'اعتماد تلقائي'),
    ]

    request    = models.ForeignKey(
        ApprovalRequest, on_delete=models.CASCADE,
        related_name='decisions', verbose_name='الطلب',
    )
    step       = models.ForeignKey(
        ApprovalStepDefinition, on_delete=models.PROTECT,
        verbose_name='الخطوة',
    )
    # Denormalized so history survives step definition edits
    step_order = models.PositiveSmallIntegerField(verbose_name='ترتيب الخطوة')
    step_name  = models.CharField(max_length=120, verbose_name='اسم الخطوة')

    decision   = models.CharField(
        max_length=15, choices=DECISION_CHOICES, db_index=True,
        verbose_name='القرار',
    )
    decided_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.PROTECT,
        null=True, blank=True,                           # null when auto_approved
        related_name='approval_decisions',
        verbose_name='المعتمِد',
    )
    decided_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت القرار')
    notes      = models.TextField(blank=True, verbose_name='ملاحظات')

    # Populated when decision=delegated
    delegated_to = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='delegated_decisions',
        verbose_name='تفويض إلى',
    )

    class Meta:
        ordering            = ['request', 'step_order']
        verbose_name        = 'قرار موافقة'
        verbose_name_plural = 'قرارات الموافقة'

    def __str__(self):
        return f'{self.request} › Step {self.step_order} → {self.get_decision_display()}'


# ─────────────────────────────────────────────────────────────────────────────
# Escalation audit (written by the escalation scheduled job)
# ─────────────────────────────────────────────────────────────────────────────

class ApprovalEscalationLog(models.Model):
    """Audit trail for escalation events fired by the scheduled job."""
    request        = models.ForeignKey(
        ApprovalRequest, on_delete=models.CASCADE,
        related_name='escalations', verbose_name='الطلب',
    )
    step_order     = models.PositiveSmallIntegerField(verbose_name='الخطوة')
    escalated_at   = models.DateTimeField(auto_now_add=True, verbose_name='وقت التصعيد')
    notified_users = models.JSONField(default=list, verbose_name='المستخدمون المُبلَّغون')
    note           = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering            = ['-escalated_at']
        verbose_name        = 'تصعيد'
        verbose_name_plural = 'سجلات التصعيد'

    def __str__(self):
        return f'Escalation: {self.request} step {self.step_order} at {self.escalated_at:%Y-%m-%d %H:%M}'
