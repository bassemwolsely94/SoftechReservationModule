from django.db import models


class Notification(models.Model):
    """
    In-app notification for ElRezeiky platform staff.

    Every notification has a type, a recipient, a human-readable title/body,
    and optional FKs to the related domain object (reservation or transfer).

    Delivered via polling — the frontend bell queries /api/notifications/unread-count/
    every 60 seconds, and loads the full list when the bell is clicked.
    """

    NOTIFICATION_TYPES = [
        # ── Reservation types ─────────────────────────────────────────────────
        ('stock_available',          '📦 مخزون متاح'),
        ('reservation_assigned',     '👤 حجز مُعيَّن'),
        ('reservation_created',      '➕ حجز جديد'),
        ('reservation_status',       '🔄 تغيير حالة حجز'),
        ('follow_up_due',            '📅 متابعة مستحقة اليوم'),
        ('weekly_summary',           '📊 ملخص أسبوعي'),
        ('monthly_report',           '📈 تقرير شهري'),
        ('mention',                  '@ ذِكر'),

        # ── Transfer types ────────────────────────────────────────────────────
        ('transfer_request',         '🔀 طلب تحويل جديد'),
        ('transfer_response',        '↩️ رد على طلب تحويل'),
        ('unfulfilled_transfer_flag','⚠️ تحويل غير مُصرَّف'),

        # ── System types ──────────────────────────────────────────────────────
        ('system',                   '⚙️ نظام'),
    ]

    recipient = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name='المستلم',
    )
    notification_type = models.CharField(
        max_length=40,
        choices=NOTIFICATION_TYPES,
        default='system',
        db_index=True,
        verbose_name='نوع الإشعار',
    )
    title = models.CharField(max_length=255, verbose_name='العنوان')
    body = models.TextField(blank=True, verbose_name='نص الإشعار')
    is_read = models.BooleanField(default=False, db_index=True, verbose_name='مقروء')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # ── Optional domain object links ─────────────────────────────────────────
    # Using nullable FKs so this model stays independent of whether the
    # reservations / transfers apps have been migrated yet.
    reservation = models.ForeignKey(
        'reservations.Reservation',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='notifications',
        verbose_name='الحجز المرتبط',
    )
    # Transfer request stored as integer ID to avoid circular-import issues
    # when notifications is populated before the transfers app is migrated.
    transfer_request_id_ref = models.IntegerField(
        null=True, blank=True,
        verbose_name='معرّف طلب التحويل',
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'إشعار'
        verbose_name_plural = 'الإشعارات'
        indexes = [
            models.Index(fields=['recipient', 'is_read', '-created_at']),
            models.Index(fields=['notification_type', '-created_at']),
        ]

    def __str__(self):
        return f"[{self.get_notification_type_display()}] {self.title} → {self.recipient}"

    @property
    def type_icon(self):
        label = dict(self.NOTIFICATION_TYPES).get(self.notification_type, '')
        return label.split(' ')[0] if label else '🔔'

    # ── Class-level factory helpers ───────────────────────────────────────────

    @classmethod
    def send_to_user(cls, staff, notification_type, title, body='',
                     reservation=None, transfer_id=None):
        """Create a single notification for one staff member."""
        return cls.objects.create(
            recipient=staff,
            notification_type=notification_type,
            title=title,
            body=body,
            reservation=reservation,
            transfer_request_id_ref=transfer_id,
        )

    @classmethod
    def send_to_branch(cls, branch, notification_type, title, body='',
                       reservation=None, transfer_id=None,
                       exclude_roles=None):
        """Create notifications for ALL active staff at a branch."""
        from apps.users.models import StaffProfile
        qs = StaffProfile.objects.filter(branch=branch, is_active=True)
        if exclude_roles:
            qs = qs.exclude(role__in=exclude_roles)
        bulk = [
            cls(
                recipient=staff,
                notification_type=notification_type,
                title=title,
                body=body,
                reservation=reservation,
                transfer_request_id_ref=transfer_id,
            )
            for staff in qs
        ]
        if bulk:
            cls.objects.bulk_create(bulk)
        return len(bulk)

    @classmethod
    def send_to_roles(cls, roles, notification_type, title, body='',
                      reservation=None, transfer_id=None, branch=None):
        """Create notifications for all active staff with any of the given roles,
        optionally filtered by branch."""
        from apps.users.models import StaffProfile
        qs = StaffProfile.objects.filter(role__in=roles, is_active=True)
        if branch:
            qs = qs.filter(branch=branch)
        bulk = [
            cls(
                recipient=staff,
                notification_type=notification_type,
                title=title,
                body=body,
                reservation=reservation,
                transfer_request_id_ref=transfer_id,
            )
            for staff in qs
        ]
        if bulk:
            cls.objects.bulk_create(bulk)
        return len(bulk)

    @classmethod
    def send_to_admins(cls, notification_type, title, body='',
                       reservation=None, transfer_id=None):
        """Shortcut: notify all admins and purchasing staff."""
        return cls.send_to_roles(
            roles=['admin', 'purchasing'],
            notification_type=notification_type,
            title=title,
            body=body,
            reservation=reservation,
            transfer_id=transfer_id,
        )
