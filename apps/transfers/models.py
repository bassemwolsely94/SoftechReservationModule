"""
apps/transfers/models.py

Transfer Request Module — Communication + Approval Workflow ONLY.
This module does NOT execute stock movements or touch ERP inventory.
Actual stock transfers are handled in Sybase / SOFTECH ERP externally.
"""
from django.db import models
from django.utils import timezone


def generate_request_number():
    """Auto-generate TR-XXXXXX sequential number."""
    last = TransferRequest.objects.order_by('-id').first()
    next_id = (last.id + 1) if last else 1
    return f'TR-{next_id:06d}'


class TransferRequest(models.Model):

    STATUS_CHOICES = [
        ('draft',          'مسودة'),
        ('pending',        'بانتظار الموافقة'),
        ('approved',       'معتمد'),
        ('rejected',       'مرفوض'),
        ('needs_revision', 'يحتاج تعديل'),
        ('sent_to_erp',    'تم الإرسال للـ ERP'),
        ('completed',      'مكتمل'),
        ('cancelled',      'ملغي'),
    ]

    # ── Identity ─────────────────────────────────────────────────────────────
    request_number = models.CharField(
        max_length=50, null=True, blank=True,
        verbose_name='رقم الطلب',
    )

    # ── Branches ──────────────────────────────────────────────────────────────
    requesting_branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.PROTECT,
        related_name='outgoing_requests',
        verbose_name='الفرع الطالب',
    )
    supplying_branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='incoming_requests',
        verbose_name='الفرع المصدر',
    )

    # ── Status & workflow ─────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='draft',
        db_index=True,
        verbose_name='حالة الطلب',
    )

    # ── People ────────────────────────────────────────────────────────────────
    created_by = models.ForeignKey(
    'users.StaffProfile',
    on_delete=models.PROTECT,
    null=True,
    blank=True,
    related_name='created_transfer_requests',
    verbose_name='أنشئ بواسطة',
)
    reviewed_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_transfer_requests',
        verbose_name='راجع بواسطة',
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = models.TextField(blank=True, verbose_name='ملاحظات')
    rejection_reason = models.TextField(blank=True, verbose_name='سبب الرفض')
    revision_notes = models.TextField(blank=True, verbose_name='ملاحظات التعديل')

    # ── ERP handoff ───────────────────────────────────────────────────────────
    erp_reference = models.CharField(
        max_length=100, blank=True,
        verbose_name='مرجع الـ ERP',
    )
    sent_to_erp_at = models.DateTimeField(null=True, blank=True)
    sent_to_erp_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='erp_sent_requests',
        verbose_name='أُرسل للـ ERP بواسطة',
    )

    # ── Delivery tracking ─────────────────────────────────────────────────────
    delivery_person_name = models.CharField(
        max_length=255, blank=True,
        verbose_name='اسم مندوب التوصيل',
    )
    dispatched_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='وقت الإرسال',
    )
    dispatched_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='dispatched_transfers',
        verbose_name='أُرسل بواسطة',
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    submitted_at  = models.DateTimeField(null=True, blank=True)
    reviewed_at   = models.DateTimeField(null=True, blank=True)
    completed_at  = models.DateTimeField(null=True, blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'طلب تحويل'
        verbose_name_plural = 'طلبات التحويل'
        indexes = [
            models.Index(fields=['status', 'requesting_branch']),
            models.Index(fields=['status', 'supplying_branch']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f'{self.request_number} | {self.requesting_branch} → {self.supplying_branch} | {self.get_status_display()}'

    def save(self, *args, **kwargs):
        if not self.request_number:
            # Pre-fetch the next PK from the DB sequence so we can populate
            # request_number BEFORE the INSERT — avoids a two-phase save and
            # works even when the column has a NOT NULL constraint.
            if not self.pk:
                from django.db import connection
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT nextval('transfers_transferrequest_id_seq')"
                    )
                    next_id = cursor.fetchone()[0]
                self.pk = next_id
            self.request_number = f'TR-{self.pk:06d}'
        super().save(*args, **kwargs)

    # ── State machine helpers ─────────────────────────────────────────────────

    @property
    def is_editable(self):
        """Items can only be edited in draft or needs_revision."""
        return self.status in ('draft', 'needs_revision')

    @property
    def can_submit(self):
        return self.status in ('draft', 'needs_revision') and self.items.exists()

    @property
    def can_approve(self):
        return self.status == 'pending'

    @property
    def can_reject(self):
        return self.status == 'pending'

    @property
    def can_request_revision(self):
        return self.status == 'pending'

    @property
    def can_send_to_erp(self):
        return self.status == 'approved'

    @property
    def can_dispatch(self):
        return self.status == 'sent_to_erp' and not self.dispatched_at

    @property
    def can_cancel(self):
        return self.status in ('draft', 'pending', 'needs_revision')

    @property
    def status_color(self):
        return {
            'draft':          'gray',
            'pending':        'orange',
            'approved':       'blue',
            'rejected':       'red',
            'needs_revision': 'yellow',
            'sent_to_erp':    'purple',
            'completed':      'green',
            'cancelled':      'gray',
        }.get(self.status, 'gray')

    @property
    def status_label_ar(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)

    def total_items(self):
        return self.items.count()


class TransferRequestItem(models.Model):
    """One line in a transfer request — one item with requested quantity."""

    request = models.ForeignKey(
        TransferRequest,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='الطلب',
        null=True,
        blank=True
    )
    item = models.ForeignKey(
        'catalog.Item',
        on_delete=models.PROTECT,
        related_name='transfer_request_items',
        verbose_name='الصنف',
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=3,
        verbose_name='الكمية المطلوبة',
    )
    notes = models.CharField(
        max_length=255, blank=True,
        verbose_name='ملاحظة',
    )

    class Meta:
        verbose_name = 'صنف في الطلب'
        verbose_name_plural = 'أصناف الطلب'
        unique_together = ('request', 'item')

    def __str__(self):
        return f'{self.item.name} × {self.quantity}'

    @property
    def available_stock_at_destination(self):
        """Live stock at the destination branch for this item."""
        from apps.catalog.models import ItemStock
        stock = ItemStock.objects.filter(
            item=self.item,
            branch=self.request.supplying_branch,
        ).first()
        return float(stock.quantity_on_hand) if stock else 0.0


class TransferRequestMessage(models.Model):
    """
    Odoo-style chatter message on a transfer request.
    Covers both human messages and system log entries.
    """

    MESSAGE_TYPES = [
        ('message', '💬 رسالة'),
        ('system',  '⚙️ نظام'),
        ('note',    '📝 ملاحظة داخلية'),
    ]

    request = models.ForeignKey(
        TransferRequest,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='الطلب',
    )
    message_type = models.CharField(
        max_length=10,
        choices=MESSAGE_TYPES,
        default='message',
    )
    message = models.TextField(verbose_name='الرسالة', blank=True)
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='transfer_messages',
        verbose_name='بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Attachments
    attachment = models.ImageField(
        upload_to='transfer_attachments/%Y/%m/',
        null=True, blank=True,
        verbose_name='مرفق صورة',
    )
    voice_note = models.FileField(
        upload_to='transfer_voices/%Y/%m/',
        null=True, blank=True,
        verbose_name='ملاحظة صوتية',
    )

    # Soft-delete — tombstone stays; body/attachments are redacted
    is_deleted = models.BooleanField(default=False, verbose_name='محذوف')
    deleted_at  = models.DateTimeField(null=True, blank=True, verbose_name='وقت الحذف')
    deleted_by  = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='deleted_transfer_messages',
        verbose_name='حُذف بواسطة',
    )

    class Meta:
        ordering = ['created_at']
        verbose_name = 'رسالة'
        verbose_name_plural = 'رسائل الطلب'

    def __str__(self):
        return f'[{self.get_message_type_display()}] {self.request_id}: {self.message[:50]}'

    @classmethod
    def log_system(cls, request, message):
        """Create a system log entry (auto-generated on status changes)."""
        return cls.objects.create(
            request=request,
            message_type='system',
            message=message,
            created_by=None,
        )
