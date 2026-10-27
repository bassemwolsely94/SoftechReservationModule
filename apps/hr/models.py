"""
apps/hr/models.py

HR workflow layer built on top of the existing StaffProfile.

Design rules:
  - NEVER duplicate StaffProfile.  All HR records link to it via FK.
  - Approvals always go through apps.approvals.ApprovalRequest.
  - Finance integration: approved ExpenseClaim / SalaryAdvance creates a row in
    apps.finance.ExpenseRecord (written by HrService, not the model itself).
  - All state machines follow the same pattern: draft → submitted → approved/rejected.

Models:
  LeaveType           — configurable leave categories (seeded by seed_hr_config)
  LeaveBalance        — one row per (staff × leave_type × year); updated on approval
  LeaveRequest        — a staff member's leave application
  ShiftTemplate       — named shift definition (name, start/end time, days)
  ShiftAssignment     — assigns a shift to a staff member for a date range
  OvertimeRequest     — employee overtime authorization
  SalaryAdvance       — advance against next salary
  ExpenseClaim        — reimbursable business expense (receipts + trips / مأمورية)
"""
from django.db import models
from django.utils import timezone
import datetime


class HrRequestIdentity(models.Model):
    """
    Shared subject/submitter identity for every HR request.

    An HR request is *about* an employee (the subject) and *filed by* a logged-in
    user (submitted_by) — the two differ when a permit is filed on someone else's
    behalf, e.g. an office boy with no system login submitting from another user's
    session. `employee_hr_code` (كود الموارد البشرية) is the mandatory anchor;
    the subject may optionally link to a StaffProfile (concrete `staff` FK) and/or
    carry a SOFTECH code.
    """
    submitted_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='%(class)s_submitted', verbose_name='مُقدَّم بواسطة',
    )
    employee_hr_code = models.CharField(max_length=30, blank=True, default='', db_index=True, verbose_name='كود الموارد البشرية')
    employee_name    = models.CharField(max_length=150, blank=True, default='', verbose_name='اسم الموظف')
    softech_code     = models.CharField(max_length=50, blank=True, default='', verbose_name='كود سوفتك')

    class Meta:
        abstract = True


# ─────────────────────────────────────────────────────────────────────────────
# Leave
# ─────────────────────────────────────────────────────────────────────────────

class LeaveType(models.Model):
    code    = models.CharField(max_length=30, unique=True, verbose_name='الكود')
    name    = models.CharField(max_length=100, verbose_name='الاسم')
    name_ar = models.CharField(max_length=100, verbose_name='الاسم بالعربي')

    is_paid           = models.BooleanField(default=True, verbose_name='مدفوعة')
    accrues_balance   = models.BooleanField(
        default=True, verbose_name='ترصيد سنوي',
        help_text='إذا كانت True يُخصم من الرصيد السنوي عند الاعتماد',
    )
    max_days_per_year = models.PositiveSmallIntegerField(
        default=21, verbose_name='الحد الأقصى (أيام/سنة)',
    )
    max_days_per_request = models.PositiveSmallIntegerField(
        default=14, verbose_name='الحد الأقصى للطلب الواحد',
    )
    # Which approval workflow to use (must exist in apps.approvals)
    approval_workflow_code = models.CharField(
        max_length=60, default='leave_request',
        verbose_name='كود مسار الموافقة',
    )
    is_active = models.BooleanField(default=True, verbose_name='مفعّل')

    class Meta:
        ordering            = ['code']
        verbose_name        = 'نوع إجازة'
        verbose_name_plural = 'أنواع الإجازات'

    def __str__(self):
        return self.name_ar


class LeaveBalance(models.Model):
    """One row per staff × leave_type × year.  Updated atomically on approval."""
    staff      = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='leave_balances', verbose_name='الموظف',
    )
    leave_type = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT,
        related_name='balances', verbose_name='نوع الإجازة',
    )
    year            = models.PositiveSmallIntegerField(verbose_name='السنة')
    entitled_days   = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name='الأيام المستحقة')
    consumed_days   = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name='الأيام المستهلكة')
    carried_forward = models.DecimalField(max_digits=6, decimal_places=2, default=0, verbose_name='مُرحَّل من السنة السابقة')
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together     = ('staff', 'leave_type', 'year')
        verbose_name        = 'رصيد إجازة'
        verbose_name_plural = 'أرصدة الإجازات'

    @property
    def remaining_days(self):
        return self.entitled_days + self.carried_forward - self.consumed_days

    def __str__(self):
        return f'{self.staff} | {self.leave_type} | {self.year} | متبقي: {self.remaining_days}'


class LeaveRequest(HrRequestIdentity):
    STATUS_DRAFT     = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_APPROVED  = 'approved'
    STATUS_REJECTED  = 'rejected'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_DRAFT,     'مسودة'),
        (STATUS_SUBMITTED, 'مُقدَّم'),
        (STATUS_APPROVED,  'معتمد'),
        (STATUS_REJECTED,  'مرفوض'),
        (STATUS_CANCELLED, 'ملغي'),
    ]

    staff      = models.ForeignKey(
        'users.StaffProfile', on_delete=models.PROTECT, null=True, blank=True,
        related_name='leave_requests', verbose_name='الموظف',
    )
    leave_type = models.ForeignKey(
        LeaveType, on_delete=models.PROTECT,
        related_name='requests', verbose_name='نوع الإجازة',
    )
    start_date      = models.DateField(verbose_name='من')
    end_date        = models.DateField(verbose_name='إلى')
    # على أن أعود للعمل يوم … — explicit return-to-work day from the paper form.
    # May differ from end_date+1 (e.g. a weekly rest day falls in between).
    return_to_work_date = models.DateField(
        null=True, blank=True, verbose_name='العودة للعمل يوم',
    )
    days_requested  = models.DecimalField(max_digits=5, decimal_places=2, verbose_name='عدد الأيام')
    reason          = models.TextField(blank=True, verbose_name='السبب')
    status          = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default=STATUS_DRAFT,
        db_index=True, verbose_name='الحالة',
    )
    # Link to the live ApprovalRequest driving this leave
    approval_request = models.OneToOneField(
        'approvals.ApprovalRequest', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='leave_request',
        verbose_name='طلب الموافقة',
    )
    rejection_reason = models.TextField(blank=True, verbose_name='سبب الرفض')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'طلب إجازة'
        verbose_name_plural = 'طلبات الإجازات'
        indexes = [
            models.Index(fields=['staff', 'status']),
            models.Index(fields=['start_date', 'end_date']),
        ]

    def __str__(self):
        return f'{self.staff} | {self.leave_type} | {self.start_date} → {self.end_date} [{self.get_status_display()}]'


# ─────────────────────────────────────────────────────────────────────────────
# Shift management
# ─────────────────────────────────────────────────────────────────────────────

class ShiftTemplate(models.Model):
    DAYS = ['saturday', 'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday']
    DAY_CHOICES = [(d, d.capitalize()) for d in DAYS]

    name       = models.CharField(max_length=100, verbose_name='اسم الشيفت')
    name_ar    = models.CharField(max_length=100, verbose_name='الاسم بالعربي')
    branch     = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE,
        null=True, blank=True, related_name='shift_templates',
        verbose_name='الفرع',
    )
    start_time = models.TimeField(verbose_name='وقت البدء')
    end_time   = models.TimeField(verbose_name='وقت الانتهاء')
    # Comma-separated day names: "saturday,sunday,monday"
    days_of_week = models.CharField(max_length=120, verbose_name='أيام العمل',
                                     help_text='مفصولة بفاصلة: saturday,sunday,monday')
    is_active  = models.BooleanField(default=True, verbose_name='مفعّل')

    class Meta:
        verbose_name        = 'نموذج شيفت'
        verbose_name_plural = 'نماذج الشيفتات'

    def __str__(self):
        return f'{self.name_ar} ({self.start_time}–{self.end_time})'


class ShiftAssignment(models.Model):
    staff      = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='shift_assignments', verbose_name='الموظف',
    )
    shift      = models.ForeignKey(
        ShiftTemplate, on_delete=models.PROTECT,
        related_name='assignments', verbose_name='الشيفت',
    )
    valid_from  = models.DateField(verbose_name='من تاريخ')
    valid_until = models.DateField(null=True, blank=True, verbose_name='حتى تاريخ')
    assigned_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='shift_assignments_given',
        verbose_name='عُيِّن بواسطة',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering            = ['-valid_from']
        verbose_name        = 'تعيين شيفت'
        verbose_name_plural = 'تعيينات الشيفت'

    def __str__(self):
        return f'{self.staff} → {self.shift} من {self.valid_from}'


# ─────────────────────────────────────────────────────────────────────────────
# Overtime
# ─────────────────────────────────────────────────────────────────────────────

class OvertimeRequest(HrRequestIdentity):
    STATUS_CHOICES = [
        ('draft',     'مسودة'),
        ('submitted', 'مُقدَّم'),
        ('approved',  'معتمد'),
        ('rejected',  'مرفوض'),
        ('cancelled', 'ملغي'),
    ]

    staff    = models.ForeignKey(
        'users.StaffProfile', on_delete=models.PROTECT, null=True, blank=True,
        related_name='overtime_requests', verbose_name='الموظف',
    )
    branch   = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT,
        related_name='overtime_requests', verbose_name='الفرع',
    )
    date     = models.DateField(verbose_name='التاريخ')
    hours    = models.DecimalField(max_digits=4, decimal_places=2, verbose_name='الساعات')
    reason   = models.TextField(verbose_name='السبب')
    status   = models.CharField(max_length=15, choices=STATUS_CHOICES, default='draft', db_index=True)
    approval_request = models.OneToOneField(
        'approvals.ApprovalRequest', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='overtime_request',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering            = ['-date', '-created_at']
        verbose_name        = 'طلب عمل إضافي'
        verbose_name_plural = 'طلبات العمل الإضافي'

    def __str__(self):
        return f'{self.staff} | {self.date} | {self.hours}h [{self.get_status_display()}]'


# ─────────────────────────────────────────────────────────────────────────────
# Salary advance
# ─────────────────────────────────────────────────────────────────────────────

class SalaryAdvance(HrRequestIdentity):
    STATUS_CHOICES = [
        ('draft',     'مسودة'),
        ('submitted', 'مُقدَّم'),
        ('approved',  'معتمد'),
        ('rejected',  'مرفوض'),
        ('settled',   'تمت التسوية'),
        ('cancelled', 'ملغي'),
    ]

    staff           = models.ForeignKey(
        'users.StaffProfile', on_delete=models.PROTECT, null=True, blank=True,
        related_name='salary_advances', verbose_name='الموظف',
    )
    amount          = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='المبلغ')
    repayment_date  = models.DateField(verbose_name='تاريخ السداد المتوقع')
    reason          = models.TextField(verbose_name='السبب')
    status          = models.CharField(max_length=15, choices=STATUS_CHOICES, default='draft', db_index=True)
    approval_request = models.OneToOneField(
        'approvals.ApprovalRequest', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='salary_advance',
    )
    # Set when finance settles the advance via ExpenseRecord
    finance_record_id = models.PositiveIntegerField(null=True, blank=True, verbose_name='رقم سجل المالية')
    settled_at        = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ التسوية')
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'سلفة راتب'
        verbose_name_plural = 'سلف الرواتب'

    def __str__(self):
        return f'{self.staff} | {self.amount:,.2f} | {self.get_status_display()}'


# ─────────────────────────────────────────────────────────────────────────────
# Expense claim (includes مأمورية / business trip)
# ─────────────────────────────────────────────────────────────────────────────

class ExpenseClaim(HrRequestIdentity):
    CATEGORY_TRANSPORT  = 'transport'
    CATEGORY_MEAL       = 'meal'
    CATEGORY_ACCOMM     = 'accommodation'
    CATEGORY_STATIONARY = 'stationery'
    CATEGORY_EQUIPMENT  = 'equipment'
    CATEGORY_MAMORIYA   = 'mamoriya'
    CATEGORY_OTHER      = 'other'

    CATEGORY_CHOICES = [
        (CATEGORY_TRANSPORT,  'مواصلات'),
        (CATEGORY_MEAL,       'وجبات'),
        (CATEGORY_ACCOMM,     'إقامة'),
        (CATEGORY_STATIONARY, 'قرطاسية'),
        (CATEGORY_EQUIPMENT,  'معدات'),
        (CATEGORY_MAMORIYA,   'مأمورية'),
        (CATEGORY_OTHER,      'أخرى'),
    ]

    STATUS_CHOICES = [
        ('draft',     'مسودة'),
        ('submitted', 'مُقدَّم'),
        ('approved',  'معتمد'),
        ('rejected',  'مرفوض'),
        ('paid',      'تم الصرف'),
        ('cancelled', 'ملغي'),
    ]

    staff    = models.ForeignKey(
        'users.StaffProfile', on_delete=models.PROTECT, null=True, blank=True,
        related_name='expense_claims', verbose_name='الموظف',
    )
    branch   = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT,
        related_name='expense_claims', verbose_name='الفرع',
    )
    category       = models.CharField(max_length=20, choices=CATEGORY_CHOICES, db_index=True, verbose_name='الفئة')
    expense_date   = models.DateField(verbose_name='تاريخ المصروف')
    amount         = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='المبلغ')
    description    = models.TextField(verbose_name='الوصف')
    receipt        = models.FileField(
        upload_to='hr/receipts/%Y/%m/', null=True, blank=True,
        verbose_name='صورة الإيصال',
    )

    # مأمورية-specific fields
    trip_destination = models.CharField(max_length=200, blank=True, verbose_name='وجهة المأمورية')
    trip_purpose     = models.TextField(blank=True, verbose_name='غرض المأمورية')
    trip_start       = models.DateField(null=True, blank=True, verbose_name='تاريخ المغادرة')
    trip_end         = models.DateField(null=True, blank=True, verbose_name='تاريخ العودة')
    distance_km      = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True, verbose_name='المسافة (كم)')
    transport_type   = models.CharField(max_length=50, blank=True, verbose_name='وسيلة النقل')
    allowance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='بدل المأمورية')

    status           = models.CharField(max_length=15, choices=STATUS_CHOICES, default='draft', db_index=True)
    approval_request = models.OneToOneField(
        'approvals.ApprovalRequest', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='expense_claim',
    )
    # Set after finance processes the payment
    finance_record_id = models.PositiveIntegerField(null=True, blank=True, verbose_name='رقم سجل المالية')
    paid_at           = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الصرف')

    rejection_reason = models.TextField(blank=True, verbose_name='سبب الرفض')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'مطالبة مصروفات'
        verbose_name_plural = 'مطالبات المصروفات'
        indexes = [
            models.Index(fields=['staff', 'status']),
            models.Index(fields=['expense_date', 'branch']),
        ]

    @property
    def total_amount(self):
        return self.amount + self.allowance_amount

    def __str__(self):
        return f'{self.staff} | {self.get_category_display()} | {self.amount:,.2f} | {self.get_status_display()}'


class AttendanceRecord(models.Model):
    """Geofenced clock in/out. Distance to the branch is computed at check-in/out;
    `*_ok` is True/False when verifiable, or null when the branch has no coordinates."""
    staff = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='attendance_records', verbose_name='الموظف',
    )
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='attendance_records', verbose_name='الفرع',
    )
    work_date = models.DateField(db_index=True, verbose_name='التاريخ')

    check_in_at        = models.DateTimeField(auto_now_add=True, verbose_name='وقت الحضور')
    check_in_lat       = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_lng       = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_distance_m = models.PositiveIntegerField(null=True, blank=True, verbose_name='مسافة الحضور (م)')
    check_in_ok        = models.BooleanField(null=True, verbose_name='ضمن النطاق عند الحضور')

    check_out_at        = models.DateTimeField(null=True, blank=True, verbose_name='وقت الانصراف')
    check_out_lat       = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_lng       = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_out_distance_m = models.PositiveIntegerField(null=True, blank=True)
    check_out_ok        = models.BooleanField(null=True)

    class Meta:
        ordering = ['-check_in_at']
        verbose_name        = 'سجل حضور'
        verbose_name_plural = 'سجلات الحضور'
        indexes = [models.Index(fields=['staff', 'work_date'])]

    def __str__(self):
        return f'{self.staff} @ {self.work_date} ({"خرج" if self.check_out_at else "حاضر"})'


# ─────────────────────────────────────────────────────────────────────────────
# Permits (أذونات) — time/schedule permissions, distinct from ExpenseClaim (money)
#   TYPE_MAMORIYA    → اذن مأمورية: leave the branch for a work errand for a
#                      time window on a given day (destination + reason).
#   TYPE_SHIFT_CHANGE→ اذن تعديل شيفت / تعديل فترة العمل: work a modified period
#                      (new from→to time) on a given day. Its approved print is
#                      the "تعديل فترة العمل" notice.
# ─────────────────────────────────────────────────────────────────────────────

class Permit(HrRequestIdentity):
    TYPE_MAMORIYA     = 'mamoriya'
    TYPE_SHIFT_CHANGE = 'shift_change'
    TYPE_CHOICES = [
        (TYPE_MAMORIYA,     'اذن مأمورية'),
        (TYPE_SHIFT_CHANGE, 'اذن تعديل شيفت'),
    ]

    # Which approval workflow each permit type routes through (apps.approvals)
    WORKFLOW_BY_TYPE = {
        TYPE_MAMORIYA:     'mission_permit',
        TYPE_SHIFT_CHANGE: 'shift_change',
    }

    STATUS_CHOICES = [
        ('draft',     'مسودة'),
        ('submitted', 'مُقدَّم'),
        ('approved',  'معتمد'),
        ('rejected',  'مرفوض'),
        ('cancelled', 'ملغي'),
    ]

    staff       = models.ForeignKey(
        'users.StaffProfile', on_delete=models.PROTECT, null=True, blank=True,
        related_name='permits', verbose_name='الموظف',
    )
    branch      = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT,
        related_name='permits', verbose_name='الفرع',
    )
    permit_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, db_index=True, verbose_name='نوع الإذن',
    )
    date        = models.DateField(verbose_name='التاريخ')
    time_from   = models.TimeField(verbose_name='من الساعة')
    time_to     = models.TimeField(null=True, blank=True, verbose_name='حتى الساعة')

    # mamoriya only — جهة المأمورية
    destination = models.CharField(max_length=200, blank=True, verbose_name='جهة المأمورية')
    reason      = models.TextField(blank=True, verbose_name='السبب')

    status      = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default='draft', db_index=True,
        verbose_name='الحالة',
    )
    approval_request = models.OneToOneField(
        'approvals.ApprovalRequest', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='permit',
    )
    rejection_reason = models.TextField(blank=True, verbose_name='سبب الرفض')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering            = ['-date', '-created_at']
        verbose_name        = 'إذن'
        verbose_name_plural = 'الأذونات'
        indexes = [
            models.Index(fields=['staff', 'status']),
            models.Index(fields=['permit_type', 'date']),
        ]

    @property
    def workflow_code(self):
        return self.WORKFLOW_BY_TYPE[self.permit_type]

    def __str__(self):
        return f'{self.staff} | {self.get_permit_type_display()} | {self.date} [{self.get_status_display()}]'
