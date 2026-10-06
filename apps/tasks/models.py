"""
apps/tasks/models.py

Pharmacy Operations Task Management System.
Covers operational tasks, scheduling, assignments, chatter, attachments and audit.
"""
from django.db import models
from django.conf import settings
from django.utils import timezone


def _next_task_number():
    last = OperationalTask.objects.order_by('-id').first()
    nxt = (last.id + 1) if last else 1
    return f'TK-{nxt:06d}'


# ── Choices ────────────────────────────────────────────────────────────────────

TASK_TYPE_CHOICES = [
    ('stock_count',   'جرد المخزون'),
    ('receiving',     'استلام بضاعة'),
    ('transfer',      'طلب تحويل'),
    ('delivery',      'توصيل'),
    ('shortage',      'قائمة نقص'),
    ('purchasing',    'مشتريات'),
    ('maintenance',   'صيانة'),
    ('meeting',       'اجتماع'),
    ('training',      'تدريب'),
    ('audit',         'تدقيق'),
    ('customer',      'خدمة عملاء'),
    ('other',         'أخرى'),
]

CATEGORY_CHOICES = [
    ('operations',  'عمليات'),
    ('logistics',   'لوجستيات'),
    ('purchasing',  'مشتريات'),
    ('sales',       'مبيعات'),
    ('hr',          'موارد بشرية'),
    ('admin',       'إدارة'),
]

PRIORITY_CHOICES = [
    ('low',      'منخفضة'),
    ('normal',   'عادية'),
    ('high',     'عالية'),
    ('urgent',   'عاجلة'),
    ('critical', 'حرجة'),
]

STATUS_CHOICES = [
    ('open',        'مفتوحة'),
    ('in_progress', 'قيد التنفيذ'),
    ('on_hold',     'متوقفة'),
    ('completed',   'مكتملة'),
    ('cancelled',   'ملغاة'),
]

RECURRENCE_CHOICES = [
    ('none',    'لا تتكرر'),
    ('daily',   'يومياً'),
    ('weekly',  'أسبوعياً'),
    ('monthly', 'شهرياً'),
]

ASSIGNMENT_ROLE_CHOICES = [
    ('lead',        'مسؤول رئيسي'),
    ('contributor', 'مساهم'),
    ('reviewer',    'مراجع'),
    ('observer',    'مراقب'),
]

MESSAGE_TYPE_CHOICES = [
    ('comment',        'تعليق'),
    ('status_change',  'تغيير الحالة'),
    ('assignment',     'تعيين'),
    ('system',         'نظام'),
]

AUDIT_ACTION_CHOICES = [
    ('created',         'إنشاء'),
    ('status_changed',  'تغيير الحالة'),
    ('assigned',        'تعيين'),
    ('unassigned',      'إلغاء تعيين'),
    ('priority_changed','تغيير الأولوية'),
    ('due_date_changed','تغيير الموعد'),
    ('completed',       'اكتمال'),
    ('comment_added',   'إضافة تعليق'),
    ('attachment_added','إضافة مرفق'),
    ('field_changed',   'تغيير حقل'),
]


# ── Models ─────────────────────────────────────────────────────────────────────

class OperationalTask(models.Model):
    """Core task record."""

    task_number = models.CharField(
        max_length=20, unique=True, null=True, blank=True,
        verbose_name='رقم المهمة',
    )
    title = models.CharField(max_length=255, verbose_name='عنوان المهمة')
    description = models.TextField(blank=True, verbose_name='الوصف')

    task_type = models.CharField(
        max_length=30, choices=TASK_TYPE_CHOICES,
        default='other', db_index=True, verbose_name='نوع المهمة',
    )
    category = models.CharField(
        max_length=30, choices=CATEGORY_CHOICES,
        default='operations', db_index=True, verbose_name='التصنيف',
    )
    priority = models.CharField(
        max_length=20, choices=PRIORITY_CHOICES,
        default='normal', db_index=True, verbose_name='الأولوية',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='open', db_index=True, verbose_name='الحالة',
    )

    # ── Relations ──────────────────────────────────────────────────────────────
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='tasks', verbose_name='الفرع',
    )
    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_tasks', verbose_name='أنشئ بواسطة',
    )
    assigned_to = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='primary_tasks', verbose_name='مُعيَّن إلى',
    )
    completed_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='completed_tasks', verbose_name='أُكمل بواسطة',
    )

    # ── Hierarchy (subtasks) ───────────────────────────────────────────────────
    parent_task = models.ForeignKey(
        'self', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='subtasks', verbose_name='المهمة الأم',
    )

    # ── Generic link to any record ─────────────────────────────────────────────
    related_model = models.CharField(
        max_length=50, blank=True,
        help_text='e.g. transfer, reservation, stockcount',
        verbose_name='النموذج المرتبط',
    )
    related_id = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='معرّف السجل المرتبط',
    )

    # ── Scheduling ─────────────────────────────────────────────────────────────
    due_date = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name='الموعد النهائي')
    start_date = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ البدء')
    estimated_hours = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name='الساعات المقدَّرة',
    )
    actual_hours = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name='الساعات الفعلية',
    )

    # ── Completion ─────────────────────────────────────────────────────────────
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت الاكتمال')
    completion_notes = models.TextField(blank=True, verbose_name='ملاحظات الإغلاق')

    # ── Recurrence ─────────────────────────────────────────────────────────────
    recurrence = models.CharField(
        max_length=10, choices=RECURRENCE_CHOICES,
        default='none', verbose_name='التكرار',
    )
    schedule = models.ForeignKey(
        'TaskSchedule', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='generated_tasks', verbose_name='الجدولة المصدر',
    )

    # ── Tags (comma-separated) ─────────────────────────────────────────────────
    tags = models.CharField(max_length=500, blank=True, verbose_name='الوسوم')

    # ── Timestamps ─────────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت الإنشاء')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='آخر تحديث')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'مهمة تشغيلية'
        verbose_name_plural = 'المهام التشغيلية'
        indexes = [
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['branch', 'status']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['due_date']),
        ]

    def __str__(self):
        return f'{self.task_number or self.pk} — {self.title}'

    def save(self, *args, **kwargs):
        if not self.task_number:
            self.task_number = _next_task_number()
        super().save(*args, **kwargs)

    @property
    def is_overdue(self):
        return (
            self.due_date
            and self.status not in ('completed', 'cancelled')
            and timezone.now() > self.due_date
        )

    @property
    def tags_list(self):
        return [t.strip() for t in self.tags.split(',') if t.strip()]


class TaskAssignment(models.Model):
    """Additional assignees beyond the primary assigned_to."""

    task = models.ForeignKey(
        OperationalTask, on_delete=models.CASCADE,
        related_name='assignments', verbose_name='المهمة',
    )
    staff = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='task_assignments', verbose_name='الموظف',
    )
    role = models.CharField(
        max_length=20, choices=ASSIGNMENT_ROLE_CHOICES,
        default='contributor', verbose_name='الدور',
    )
    assigned_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assignments_made', verbose_name='عُيِّن بواسطة',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    is_completed = models.BooleanField(default=False, verbose_name='أنهى')
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('task', 'staff')
        verbose_name = 'تعيين مهمة'
        verbose_name_plural = 'تعيينات المهام'

    def __str__(self):
        return f'{self.staff} → {self.task}'


class TaskItem(models.Model):
    """Checklist item or tracked item within a task (e.g., items to count/receive)."""

    task = models.ForeignKey(
        OperationalTask, on_delete=models.CASCADE,
        related_name='items', verbose_name='المهمة',
    )
    item = models.ForeignKey(
        'catalog.Item', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='task_items', verbose_name='الصنف',
    )
    item_name = models.CharField(max_length=255, blank=True, verbose_name='اسم الصنف')
    item_code = models.CharField(max_length=50, blank=True, verbose_name='كود الصنف')
    quantity_expected = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True,
        verbose_name='الكمية المتوقعة',
    )
    quantity_actual = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True,
        verbose_name='الكمية الفعلية',
    )
    unit = models.CharField(max_length=30, blank=True, verbose_name='الوحدة')
    notes = models.CharField(max_length=500, blank=True, verbose_name='ملاحظات')
    is_checked = models.BooleanField(default=False, verbose_name='تم التحقق')
    checked_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    checked_at = models.DateTimeField(null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        verbose_name = 'عنصر مهمة'
        verbose_name_plural = 'عناصر المهام'

    def save(self, *args, **kwargs):
        if self.item and not self.item_name:
            self.item_name = self.item.name or ''
        if self.item and not self.item_code:
            self.item_code = getattr(self.item, 'softech_id', '') or ''
        super().save(*args, **kwargs)


class TaskMessage(models.Model):
    """Chatter messages and system events for a task."""

    task = models.ForeignKey(
        OperationalTask, on_delete=models.CASCADE,
        related_name='messages', verbose_name='المهمة',
    )
    author = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='task_messages', verbose_name='الكاتب',
    )
    message_type = models.CharField(
        max_length=20, choices=MESSAGE_TYPE_CHOICES,
        default='comment', verbose_name='نوع الرسالة',
    )
    body = models.TextField(verbose_name='النص')
    is_deleted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'رسالة مهمة'
        verbose_name_plural = 'رسائل المهام'

    def __str__(self):
        return f'[{self.message_type}] {self.task_id} — {self.created_at:%Y-%m-%d %H:%M}'


class TaskAttachment(models.Model):
    """File attachments on a task."""

    task = models.ForeignKey(
        OperationalTask, on_delete=models.CASCADE,
        related_name='attachments', verbose_name='المهمة',
    )
    uploaded_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    file = models.FileField(upload_to='tasks/attachments/%Y/%m/', verbose_name='الملف')
    file_name = models.CharField(max_length=255, blank=True)
    file_type = models.CharField(max_length=50, blank=True)  # image, pdf, excel, other
    file_size = models.PositiveIntegerField(null=True, blank=True)  # bytes
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'مرفق مهمة'
        verbose_name_plural = 'مرفقات المهام'

    def save(self, *args, **kwargs):
        if self.file and not self.file_name:
            self.file_name = self.file.name.split('/')[-1]
        super().save(*args, **kwargs)


class TaskSchedule(models.Model):
    """Recurring schedule that auto-generates tasks."""

    name = models.CharField(max_length=200, verbose_name='اسم الجدول')
    task_type = models.CharField(
        max_length=30, choices=TASK_TYPE_CHOICES,
        default='other', verbose_name='نوع المهمة',
    )
    category = models.CharField(
        max_length=30, choices=CATEGORY_CHOICES,
        default='operations', verbose_name='التصنيف',
    )
    priority = models.CharField(
        max_length=20, choices=PRIORITY_CHOICES,
        default='normal', verbose_name='الأولوية',
    )
    title_template = models.CharField(
        max_length=255, verbose_name='قالب العنوان',
        help_text='Use {date} for today, {branch} for branch name',
    )
    description_template = models.TextField(
        blank=True, verbose_name='قالب الوصف',
    )

    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='task_schedules', verbose_name='الفرع',
    )
    assign_to = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='scheduled_tasks', verbose_name='يُعيَّن إلى',
    )
    assign_to_role = models.CharField(
        max_length=30, blank=True,
        verbose_name='يُعيَّن إلى الدور',
        help_text='pharmacist, admin, etc.',
    )

    frequency = models.CharField(
        max_length=10, choices=RECURRENCE_CHOICES,
        default='daily', verbose_name='التكرار',
    )
    day_of_week = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='0=Monday … 6=Sunday (for weekly)',
        verbose_name='يوم الأسبوع',
    )
    day_of_month = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='1-31 (for monthly)',
        verbose_name='يوم الشهر',
    )
    time_of_day = models.TimeField(
        null=True, blank=True, verbose_name='وقت التنفيذ',
    )
    advance_days = models.PositiveSmallIntegerField(
        default=1,
        help_text='Create task N days before due date',
        verbose_name='أيام مسبقة',
    )

    is_active = models.BooleanField(default=True, verbose_name='نشط')
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    estimated_hours = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'جدول مهام'
        verbose_name_plural = 'جداول المهام'

    def __str__(self):
        return self.name


class TaskAuditLog(models.Model):
    """Immutable audit trail for all task changes."""

    task = models.ForeignKey(
        OperationalTask, on_delete=models.CASCADE,
        related_name='audit_logs', verbose_name='المهمة',
    )
    action = models.CharField(
        max_length=30, choices=AUDIT_ACTION_CHOICES, verbose_name='الإجراء',
    )
    actor = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='task_audit_logs', verbose_name='المنفِّذ',
    )
    field_name = models.CharField(max_length=50, blank=True, verbose_name='الحقل')
    old_value = models.TextField(blank=True, verbose_name='القيمة القديمة')
    new_value = models.TextField(blank=True, verbose_name='القيمة الجديدة')
    extra = models.JSONField(default=dict, blank=True, verbose_name='بيانات إضافية')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'سجل تدقيق المهام'
        verbose_name_plural = 'سجلات تدقيق المهام'

    def __str__(self):
        return f'{self.task_id} — {self.action} by {self.actor}'
