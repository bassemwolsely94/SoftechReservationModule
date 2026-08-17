"""
apps/audit/models.py

Phase 7: Audit + Anti-abuse System

AuditLog   — records every create/update/delete across all domain models
AbuseFlag  — flags suspicious patterns (frequent edits, cancellations, overrides)

Design principles:
  - Lightweight: no signal overhead on every request
  - Selective: only meaningful domain events, not every DB write
  - Non-blocking: failures never propagate to the caller
  - Queryable: indexed for fast reporting
"""
from django.db import models
import json


class AuditLog(models.Model):
    """
    Immutable audit trail. One row per meaningful domain event.
    Written by services and views — never auto-generated via signals
    (signals fire too broadly and add latency to every request).
    """

    ACTION_CHOICES = [
        # Reservation
        ('reservation_created',        'حجز — إنشاء'),
        ('reservation_updated',        'حجز — تعديل'),
        ('reservation_status_changed', 'حجز — تغيير حالة'),
        ('reservation_cancelled',      'حجز — إلغاء'),
        ('reservation_erp_validated',  'حجز — تحقق ERP'),

        # Transfer
        ('transfer_created',           'تحويل — إنشاء'),
        ('transfer_submitted',         'تحويل — تقديم'),
        ('transfer_approved',          'تحويل — اعتماد'),
        ('transfer_rejected',          'تحويل — رفض'),
        ('transfer_sent_to_erp',       'تحويل — إرسال للـ ERP'),
        ('transfer_erp_validated',     'تحويل — تحقق ERP'),

        # Customer
        ('customer_created',           'عميل — إنشاء'),
        ('customer_updated',           'عميل — تعديل'),
        ('customer_tag_added',         'عميل — إضافة تاج'),
        ('customer_location_added',    'عميل — إضافة عنوان'),

        # Demand
        ('demand_created',             'طلب — إنشاء'),
        ('demand_status_changed',      'طلب — تغيير حالة'),
        ('demand_lost',                'طلب — بيع ضائع'),

        # Follow-up
        ('followup_created',           'متابعة — إنشاء'),
        ('followup_done',              'متابعة — اكتمال'),
        ('followup_auto_closed',       'متابعة — إغلاق تلقائي'),

        # Auth
        ('user_login',                 'مستخدم — دخول'),
        ('user_login_failed',          'مستخدم — محاولة دخول فاشلة'),

        # System
        ('sync_completed',             'مزامنة — اكتمال'),
        ('sync_failed',                'مزامنة — فشل'),
    ]

    # ── Who ───────────────────────────────────────────────────────────────────
    user = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='audit_logs',
        verbose_name='المستخدم',
    )
    user_name = models.CharField(
        max_length=150, blank=True,
        verbose_name='اسم المستخدم',
        help_text='Snapshot at time of action — preserved even if user is deleted',
    )
    user_role = models.CharField(max_length=20, blank=True, verbose_name='دور المستخدم')
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name='عنوان IP')

    # ── What ──────────────────────────────────────────────────────────────────
    action = models.CharField(
        max_length=40,
        choices=ACTION_CHOICES,
        db_index=True,
        verbose_name='الإجراء',
    )
    model_name = models.CharField(
        max_length=50, blank=True, db_index=True,
        verbose_name='النموذج',
        help_text='e.g. Reservation, TransferRequest',
    )
    object_id = models.CharField(
        max_length=50, blank=True, db_index=True,
        verbose_name='معرف الكيان',
    )
    object_repr = models.CharField(
        max_length=200, blank=True,
        verbose_name='وصف الكيان',
        help_text='Human-readable str(obj) at time of action',
    )

    # ── Before/after ──────────────────────────────────────────────────────────
    old_data = models.JSONField(
        null=True, blank=True,
        verbose_name='البيانات قبل التعديل',
    )
    new_data = models.JSONField(
        null=True, blank=True,
        verbose_name='البيانات بعد التعديل',
    )
    changes = models.JSONField(
        null=True, blank=True,
        verbose_name='التغييرات فقط',
        help_text='Dict of {field: [old, new]} for updates',
    )

    # ── Extra context ─────────────────────────────────────────────────────────
    extra = models.JSONField(
        null=True, blank=True,
        verbose_name='بيانات إضافية',
    )
    note = models.CharField(max_length=255, blank=True, verbose_name='ملاحظة')

    # ── When ──────────────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'سجل مراجعة'
        verbose_name_plural = 'سجلات المراجعة'
        indexes = [
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['model_name', 'object_id']),
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return (
            f'[{self.get_action_display()}] '
            f'{self.user_name or "system"} → '
            f'{self.model_name}#{self.object_id}'
        )

    @classmethod
    def log(cls, action, user=None, obj=None,
            old_data=None, new_data=None, changes=None,
            extra=None, note='', request=None):
        """
        Non-fatal audit log factory. Call from anywhere.

        Usage:
            AuditLog.log(
                'reservation_status_changed',
                user=staff_profile,
                obj=reservation,
                changes={'status': ['pending', 'available']},
                note='Auto-flagged after sync',
            )
        """
        try:
            entry = cls(
                action=action,
                note=note,
            )

            if user:
                entry.user      = user
                entry.user_name = user.full_name
                entry.user_role = user.role

            if obj:
                entry.model_name  = type(obj).__name__
                entry.object_id   = str(obj.pk)
                entry.object_repr = str(obj)[:200]

            if old_data:
                entry.old_data = old_data if isinstance(old_data, dict) else {'value': str(old_data)}
            if new_data:
                entry.new_data = new_data if isinstance(new_data, dict) else {'value': str(new_data)}
            if changes:
                entry.changes = changes
            if extra:
                entry.extra = extra

            if request:
                entry.ip_address = _get_ip(request)

            entry.save()
            return entry
        except Exception:
            # Never propagate audit failures
            return None


class AbuseFlag(models.Model):
    """
    Flags a suspicious activity pattern for a staff member.
    Populated by the anti-abuse detector (run periodically).
    """

    FLAG_TYPE_CHOICES = [
        ('frequent_cancellations', '⚠️ إلغاءات متكررة'),
        ('frequent_status_changes', '⚠️ تغييرات حالة متكررة'),
        ('frequent_edits',          '⚠️ تعديلات متكررة'),
        ('erp_mismatch',            '⚠️ عدم تطابق ERP'),
        ('after_hours_activity',    '⚠️ نشاط خارج أوقات العمل'),
        ('bulk_deletions',          '⚠️ حذف جماعي'),
        ('override_pattern',        '⚠️ تجاوزات متكررة'),
    ]

    SEVERITY_CHOICES = [
        ('info',     'معلومة'),
        ('warning',  'تحذير'),
        ('critical', 'حرج'),
    ]

    STATUS_CHOICES = [
        ('open',        'مفتوح'),
        ('reviewed',    'تمت المراجعة'),
        ('dismissed',   'تم التجاهل'),
        ('escalated',   'تم التصعيد'),
    ]

    # ── Subject ───────────────────────────────────────────────────────────────
    staff = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.CASCADE,
        related_name='abuse_flags',
        verbose_name='الموظف',
    )

    # ── Flag details ──────────────────────────────────────────────────────────
    flag_type = models.CharField(
        max_length=30,
        choices=FLAG_TYPE_CHOICES,
        db_index=True,
        verbose_name='نوع المشكلة',
    )
    severity = models.CharField(
        max_length=10,
        choices=SEVERITY_CHOICES,
        default='warning',
        db_index=True,
        verbose_name='الخطورة',
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default='open',
        db_index=True,
        verbose_name='الحالة',
    )

    # ── Evidence ──────────────────────────────────────────────────────────────
    description = models.TextField(verbose_name='الوصف')
    evidence = models.JSONField(
        null=True, blank=True,
        verbose_name='الأدلة',
        help_text='Supporting AuditLog IDs or counts',
    )
    count = models.PositiveIntegerField(
        default=0,
        verbose_name='عدد الأحداث',
    )
    window_hours = models.PositiveIntegerField(
        default=24,
        verbose_name='النافذة الزمنية (ساعة)',
    )

    # ── Review ────────────────────────────────────────────────────────────────
    reviewed_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_abuse_flags',
        verbose_name='راجع بواسطة',
    )
    review_note = models.TextField(blank=True, verbose_name='ملاحظة المراجعة')

    # ── Timestamps ────────────────────────────────────────────────────────────
    detected_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-detected_at']
        verbose_name = 'إشارة مشكلة'
        verbose_name_plural = 'إشارات المشاكل'
        indexes = [
            models.Index(fields=['staff', 'flag_type', 'detected_at']),
            models.Index(fields=['status', 'severity']),
        ]

    def __str__(self):
        return (
            f'[{self.get_severity_display()}] '
            f'{self.staff.full_name} — '
            f'{self.get_flag_type_display()}'
        )


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_ip(request):
    """Extract client IP from Django request."""
    try:
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            return x_forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')
    except Exception:
        return None
