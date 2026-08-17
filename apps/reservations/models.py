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
        ('high',    'مهم'),
    ]
    # ── POS-type channel (mirrors Softech ERP POS screen selection) ─────────────
    # Ctrl+F2 = Cash Sales  →  cash_sales
    # Ctrl+F3 = Home Delivery →  home_delivery
    # Ctrl+F4 = Contract Sales → contract_sales  (sub-channel stored in contract_subtype)
    CHANNEL_CHOICES = [
        ('cash_sales',     'بيع نقدي / كاش (F2)'),
        ('home_delivery',  'توصيل للمنزل (F3)'),
        ('contract_sales', 'بيع بالكنتراكت (F4)'),
    ]

    # ── Contract sub-channel (نوع العميل in Softech, only when channel=contract_sales) ──
    CONTRACT_SUBTYPE_CHOICES = [
        ('taakodat',         'تعاقدات / آجل'),
        ('loyal_customer',   'عميل دائم'),
        ('health_insurance', 'تأمين صحي'),
        ('compensation',     'تعويضات الشركات'),
        ('electronic',       'إيصال إلكتروني بالبطاقة الشخصية'),
        ('vip',              'Vip'),
        ('camac',            'تعاقد - سداد أجل - خصم يدوى'),
        ('clearing',         'مقاصات'),
        ('donation',         'تبرعات'),
        ('internal',         'موظفين شركة الرزيقى'),
    ]

    customer = models.ForeignKey(
        'customers.Customer', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='reservations',
    )
    item = models.ForeignKey(
        'catalog.Item', on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='reservations',
    )
    # Used when the item is not yet in the system (no softech_id / not synced).
    # Staff types the name manually; item FK is null until the item is added.
    manual_item_name = models.CharField(
        max_length=500, blank=True,
        help_text='اسم صنف غير مكوَّد — يُستخدم عند عدم وجود الصنف في قاعدة البيانات',
    )
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT)
    assigned_to = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_reservations'
    )
    quantity_requested = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal', db_index=True)
    contact_phone = models.CharField(max_length=50)
    contact_name = models.CharField(max_length=255)
    notes = models.TextField(blank=True)
    channel = models.CharField(
        max_length=20, choices=CHANNEL_CHOICES, default='cash_sales',
        verbose_name='قناة الطلب (نوع POS)',
    )
    contract_subtype = models.CharField(
        max_length=30, choices=CONTRACT_SUBTYPE_CHOICES, blank=True,
        verbose_name='نوع العميل / قناة الكنتراكت',
        help_text='يُملأ فقط عند اختيار بيع بالكنتراكت',
    )
    expected_arrival_date = models.DateField(null=True, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    softech_reserve_id = models.CharField(max_length=50, blank=True)
    image = models.ImageField(upload_to='reservations/%Y/%m/', null=True, blank=True)

    # Built once from STATUS_CHOICES — used in status_label_ar property
    _STATUS_LABELS: dict = {}   # populated below after class body completes

    ORDER_SOURCE_CHOICES = [
        ('cc_whatsapp',     'كول سنتر — واتساب'),
        ('cc_call',         'كول سنتر — مكالمة'),
        ('branch_whatsapp', 'الفرع — واتساب'),
        ('branch_call',     'الفرع — مكالمة'),
        ('online',          'طلب إلكتروني'),
        ('walk_in',         'زيارة مباشرة'),
    ]
    FULFILLMENT_CHOICES = [
        ('pickup',   'استلام من الفرع'),
        ('delivery', 'توصيل'),
    ]
    order_source = models.CharField(
        max_length=20, choices=ORDER_SOURCE_CHOICES, blank=True,
        verbose_name='مصدر الطلب',
    )
    fulfillment_method = models.CharField(
        max_length=10, choices=FULFILLMENT_CHOICES, blank=True,
        verbose_name='طريقة التسليم',
    )

    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, related_name='created_reservations'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── ERP Match Verification (post-fulfillment) ─────────────────────────────
    # After تم التسليم (fulfilled), admin/pharmacist can verify that the
    # reservation was actually processed in SOFTECH as a sales document
    # (doccode 115 — مبيعات نقدية).
    erp_reference         = models.CharField(
        max_length=50, blank=True,
        verbose_name='رقم مستند ERP (مبيعات)',
    )
    erp_match_status      = models.CharField(
        max_length=20, blank=True, db_index=True,
        choices=[
            ('pending',   'قيد الانتظار'),
            ('matched',   'متطابق'),
            ('partial',   'تطابق جزئي'),
            ('not_found', 'غير موجود'),
        ],
        verbose_name='حالة مطابقة ERP',
    )
    erp_match_detail      = models.TextField(blank=True, verbose_name='تفاصيل المطابقة')
    erp_last_checked      = models.DateTimeField(null=True, blank=True, verbose_name='آخر فحص')
    erp_check_attempts    = models.PositiveSmallIntegerField(default=0, verbose_name='عدد المحاولات')
    erp_matched_at        = models.DateTimeField(null=True, blank=True, verbose_name='وقت المطابقة')
    erp_match_doc_code    = models.CharField(max_length=10, blank=True, verbose_name='كود نوع المستند')
    erp_match_doc_date    = models.DateField(null=True, blank=True, verbose_name='تاريخ المستند')
    erp_match_doc_value   = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        verbose_name='قيمة المستند',
    )
    erp_match_user_code   = models.CharField(max_length=20, blank=True, verbose_name='كود المستخدم (ERP)')
    erp_match_user_id     = models.CharField(max_length=100, blank=True, verbose_name='اسم مستخدم ERP')
    erp_match_user_name   = models.CharField(max_length=200, blank=True, verbose_name='الاسم الكامل (ERP)')
    erp_match_trans_time  = models.DateTimeField(null=True, blank=True, verbose_name='وقت تنفيذ المعاملة (ERP)')
    erp_match_store_code  = models.CharField(max_length=20, blank=True, verbose_name='كود المخزن (ERP)')
    erp_matched_items     = models.JSONField(default=list, blank=True, verbose_name='أصناف المطابقة')
    # Full document lines from SOFTECH (all items on the matched receipt)
    erp_receipt_lines     = models.JSONField(default=list, blank=True, verbose_name='أصناف الإيصال الكاملة')
    # Customer info from SOFTECH localcustomers (PIC code, name, phone)
    erp_customer_info     = models.JSONField(default=dict, blank=True, verbose_name='بيانات العميل (ERP)')

    # ── Class-level lookup maps (built once, not per property call) ──────────────
    _STATUS_COLORS = {
        'pending': 'gray', 'available': 'orange', 'contacted': 'blue',
        'confirmed': 'indigo', 'fulfilled': 'green', 'cancelled': 'red', 'expired': 'red',
    }
    _PRIORITY_COLORS = {'normal': 'gray', 'urgent': 'red', 'chronic': 'purple', 'high': 'yellow'}

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['status', '-created_at']),   # list filtered by status
            models.Index(fields=['follow_up_date']),
            models.Index(fields=['branch', '-created_at']),   # branch-scoped list
        ]

    @property
    def item_label(self):
        """Display name whether item is a catalog FK or a manual entry."""
        if self.item_id:
            return self.item.name
        return self.manual_item_name or '(صنف غير مكوَّد)'

    def __str__(self):
        customer_label = self.customer.name if self.customer_id else self.contact_name or 'زبون مباشر'
        return f"#{self.id} {self.item_label} — {customer_label} [{self.status}]"

    @property
    def is_active(self):
        return self.status not in ('fulfilled', 'cancelled', 'expired')

    @property
    def priority_color(self):
        return self._PRIORITY_COLORS.get(self.priority, 'gray')

    @property
    def status_color(self):
        return self._STATUS_COLORS.get(self.status, 'gray')

    @property
    def status_label_ar(self):
        # dict() called once at class definition — reuse as class attribute
        return self._STATUS_LABELS.get(self.status, self.status)


class ReservationLine(models.Model):
    """
    One item line in a multi-item reservation basket.
    When a reservation has lines, they are the authoritative item list.
    When it has no lines, the header item/qty fields apply (single-item, backward compat).
    """
    reservation = models.ForeignKey(
        Reservation, on_delete=models.CASCADE, related_name='lines',
    )
    item = models.ForeignKey(
        'catalog.Item', on_delete=models.PROTECT,
        null=True, blank=True,
    )
    manual_item_name = models.CharField(max_length=500, blank=True)
    quantity_requested = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'صنف في الحجز'
        verbose_name_plural = 'أصناف الحجز'

    @property
    def item_label(self):
        if self.item_id:
            return self.item.name
        return self.manual_item_name or '(صنف غير مكوَّد)'

    def __str__(self):
        return f'{self.item_label} × {self.quantity_requested} — حجز #{self.reservation_id}'


class ReservationDownpayment(models.Model):
    """Track downpayments received against a reservation."""

    PAYMENT_METHODS = [
        ('cash',     'نقدي'),
        ('card',     'بطاقة'),
        ('transfer', 'تحويل بنكي'),
        ('other',    'أخرى'),
    ]

    reservation = models.ForeignKey(
        Reservation, on_delete=models.CASCADE, related_name='downpayments'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_METHODS, default='cash')
    reference_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    received_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True
    )
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at']
        verbose_name = 'دفعة مقدمة'
        verbose_name_plural = 'الدفعات المقدمة'

    def __str__(self):
        return f'حجز #{self.reservation_id} — {self.amount} جنيه ({self.get_payment_method_display()})'


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


# ── Extra images ──────────────────────────────────────────────────────────────

class ReservationImage(models.Model):
    reservation = models.ForeignKey(
        Reservation, on_delete=models.CASCADE, related_name='images',
    )
    image = models.ImageField(upload_to='reservations/%Y/%m/')
    uploaded_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='uploaded_reservation_images',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['uploaded_at']


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
    # Voice note — recorded in browser via WebRTC or uploaded as audio file
    voice_note = models.FileField(
        upload_to='reservation_voices/%Y/%m/',
        null=True, blank=True,
        help_text='ملاحظة صوتية (WebRTC أو ملف صوتي)',
    )

    # Soft-delete — message body/attachments are redacted but the tombstone stays visible
    is_deleted = models.BooleanField(default=False, db_index=True, verbose_name='محذوف')
    deleted_at  = models.DateTimeField(null=True, blank=True, verbose_name='وقت الحذف')
    deleted_by  = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='deleted_reservation_activities',
        verbose_name='حُذف بواسطة',
    )

    class Meta:
        ordering = ['created_at']  # Oldest first — chatter reads top to bottom
        verbose_name = 'نشاط الحجز'
        verbose_name_plural = 'أنشطة الحجز'

    def __str__(self):
        return f"[{self.get_activity_type_display()}] حجز #{self.reservation_id} — {self.created_at:%Y-%m-%d %H:%M}"

    # Class-level lookup maps — built once, reused on every property call
    _ACTIVITY_TYPES_MAP: dict = {}   # populated below

    @property
    def activity_icon(self):
        label = self._ACTIVITY_TYPES_MAP.get(self.activity_type, '')
        return label.split(' ')[0] if label else '•'

    @property
    def activity_label(self):
        label = self._ACTIVITY_TYPES_MAP.get(self.activity_type, self.activity_type)
        parts = label.split(' ', 1)
        return parts[1] if len(parts) > 1 else label


# ── Populate class-level lookup maps (after class body is complete) ────────────
Reservation._STATUS_LABELS       = dict(Reservation.STATUS_CHOICES)
ReservationActivity._ACTIVITY_TYPES_MAP = dict(ReservationActivity.ACTIVITY_TYPES)
