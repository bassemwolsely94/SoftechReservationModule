from django.db import models


class Reservation(models.Model):
    STATUS_CHOICES = [
        ('pending',   'قيد الانتظار — انتظار مخزون'),
        ('available', 'المخزون متاح — اتصل بالعميل'),
        ('contacted', 'تم التواصل — العميل على علم'),
        ('confirmed', 'مؤكد — العميل قادم'),
        ('fulfilled', 'تم التسليم — الصنف صُرف'),
        ('cancelled', 'ملغي'),
        ('expired',   'منتهي — لا استجابة'),
    ]
    PRIORITY_CHOICES = [
        ('normal',  'عادي'),
        ('urgent',  'عاجل'),
        ('chronic', 'مريض مزمن'),
    ]

    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.PROTECT, related_name='reservations'
    )
    item = models.ForeignKey(
        'catalog.Item', on_delete=models.PROTECT, related_name='reservations'
    )
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    assigned_to = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_reservations'
    )
    quantity_requested = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    contact_phone = models.CharField(max_length=50)
    contact_name = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    expected_arrival_date = models.DateField(null=True, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    softech_reserve_id = models.CharField(max_length=50, blank=True)
    image = models.ImageField(upload_to='reservations/%Y/%m/', null=True, blank=True)
    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, related_name='created_reservations'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['follow_up_date']),
        ]

    def __str__(self):
        return f"#{self.id} {self.item.name} — {self.customer.name} [{self.status}]"

    @property
    def is_active(self):
        return self.status not in ('fulfilled', 'cancelled', 'expired')

    @property
    def priority_color(self):
        return {
            'normal': 'gray',
            'urgent': 'red',
            'chronic': 'purple',
        }.get(self.priority, 'gray')

    @property
    def status_color(self):
        return {
            'pending': 'gray',
            'available': 'orange',
            'contacted': 'blue',
            'confirmed': 'indigo',
            'fulfilled': 'green',
            'cancelled': 'red',
            'expired': 'red',
        }.get(self.status, 'gray')

    @property
    def status_label_ar(self):
        return dict(self.STATUS_CHOICES).get(self.status, self.status)


class ReservationStatusLog(models.Model):
    reservation = models.ForeignKey(
        Reservation, on_delete=models.CASCADE, related_name='status_logs'
    )
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True
    )
    note = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f"Reservation #{self.reservation_id}: {self.old_status} → {self.new_status}"


# ── Chatter / Activity Log ─────────────────────────────────────────────────────

class ReservationActivity(models.Model):
    """
    Odoo-style chatter for reservations.
    Every action — status change, call made, note, image, transfer — is logged here.
    This is the single source of truth for what happened on a reservation.
    """

    ACTIVITY_TYPES = [
        ('note',               '📝 ملاحظة'),
        ('call_made',          '📞 مكالمة أُجريت'),
        ('customer_replied',   '💬 رد العميل'),
        ('stock_checked',      '🔍 تم فحص المخزون'),
        ('status_changed',     '🔄 تغيير الحالة'),
        ('transfer_requested', '🔀 طلب تحويل مخزون'),
        ('transfer_replied',   '↩️ رد على طلب تحويل'),
        ('item_dispensed',     '✅ تم صرف الصنف'),
        ('reminder_sent',      '🔔 تم إرسال تذكير'),
        ('image_attached',     '🖼️ تم إرفاق صورة'),
        ('assigned',           '👤 تم التعيين'),
        ('mention',            '@ذِكر'),
    ]

    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name='activities',
    )
    activity_type = models.CharField(
        max_length=30,
        choices=ACTIVITY_TYPES,
        default='note',
    )
    message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True,
        related_name='reservation_activities',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    attachment = models.ImageField(
        upload_to='reservation_activities/%Y/%m/',
        null=True, blank=True,
    )
    mentioned_users = models.ManyToManyField(
        'users.StaffProfile',
        blank=True,
        related_name='mentioned_in_activities',
    )

    # Optional FK to transfer request (for transfer_requested / transfer_replied types)
    transfer_request_id_ref = models.IntegerField(
        null=True, blank=True,
        help_text='ID of related TransferRequest (loose reference to avoid circular import)',
    )

    class Meta:
        ordering = ['created_at']  # Oldest first — chatter reads top to bottom
        verbose_name = 'نشاط الحجز'
        verbose_name_plural = 'أنشطة الحجز'

    def __str__(self):
        return f"[{self.get_activity_type_display()}] حجز #{self.reservation_id} — {self.created_at:%Y-%m-%d %H:%M}"

    @property
    def activity_icon(self):
        label = dict(self.ACTIVITY_TYPES).get(self.activity_type, '')
        # Extract just the emoji
        return label.split(' ')[0] if label else '•'

    @property
    def activity_label(self):
        label = dict(self.ACTIVITY_TYPES).get(self.activity_type, self.activity_type)
        # Strip emoji
        parts = label.split(' ', 1)
        return parts[1] if len(parts) > 1 else label
