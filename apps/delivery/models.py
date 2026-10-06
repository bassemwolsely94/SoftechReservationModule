"""
apps/delivery/models.py

Delivery Management System — v2 (complete overhaul)

Models:
  DeliveryDriver        — driver profile (separate entity, may link to StaffProfile)
  CustomerLocation      — customer address / GPS (multiple per customer)
  DeliveryOrder         — core delivery order entity
  DeliveryOrderItem     — line items per delivery order
  DeliveryAssignment    — assignment history (ForeignKey, not OneToOne)
  DeliveryStatusLog     — immutable status-change audit trail
  CashCollection        — cash collected per order

SOFTECH Integration:
  Delivery orders identified by: stktransm.doccode='115' AND ptclassifcode='90'
  Customer PIC from stktransm.phcode → Customer.softech_pic
  Order source distinguised by:
    - source_type='call_center'  → created by رئيسى call-center staff
    - source_type='branch_pos'   → created by branch POS user
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DeliveryDriver
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeliveryDriver(models.Model):
    """
    Driver profile entity.

    A driver may or may not be a StaffProfile user.
    staff_profile is optional — some drivers are external contractors.
    """

    STATUS_ACTIVE    = 'active'
    STATUS_INACTIVE  = 'inactive'
    STATUS_SUSPENDED = 'suspended'

    STATUS_CHOICES = [
        (STATUS_ACTIVE,    'نشط ✅'),
        (STATUS_INACTIVE,  'غير نشط'),
        (STATUS_SUSPENDED, 'موقوف 🔴'),
    ]

    VEHICLE_CHOICES = [
        ('motorcycle', 'دراجة نارية 🏍️'),
        ('car',        'سيارة 🚗'),
        ('bicycle',    'دراجة هوائية 🚲'),
        ('on_foot',    'سير 🚶'),
        ('van',        'ميكروباص 🚐'),
    ]

    # ── Identity ──────────────────────────────────────────────────────────────
    full_name   = models.CharField(max_length=255, verbose_name='الاسم الكامل')
    mobile      = models.CharField(max_length=50,  db_index=True, verbose_name='الجوال')
    national_id = models.CharField(max_length=30,  blank=True, verbose_name='رقم الهوية')

    # Optional link to a StaffProfile (for internal drivers)
    staff_profile = models.OneToOneField(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='driver_profile',
        verbose_name='ملف الموظف',
    )

    # ── Branch & vehicle ──────────────────────────────────────────────────────
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='drivers',
        verbose_name='الفرع',
    )
    vehicle_type  = models.CharField(
        max_length=15,
        choices=VEHICLE_CHOICES,
        default='motorcycle',
        verbose_name='نوع المركبة',
    )
    vehicle_plate = models.CharField(max_length=30, blank=True, verbose_name='لوحة المركبة')

    # ── Operational ───────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
        db_index=True,
        verbose_name='الحالة',
    )
    max_daily_orders = models.PositiveSmallIntegerField(
        default=20,
        verbose_name='الحد اليومي للطلبات',
    )
    notes = models.TextField(blank=True, verbose_name='ملاحظات')

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['full_name']
        verbose_name = 'سائق توصيل'
        verbose_name_plural = 'سائقو التوصيل'
        indexes = [
            models.Index(fields=['status', 'branch']),
        ]

    def __str__(self):
        return f'{self.full_name} ({self.get_vehicle_type_display()})'

    @property
    def today_order_count(self):
        return self.assignments.filter(
            assigned_at__date=timezone.localdate(),
            is_current=True,
        ).count()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CustomerLocation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CustomerLocation(models.Model):
    """
    Customer address / GPS — multiple per customer.

    Changed from OneToOneField to ForeignKey in v2.
    A customer can have: home, work, relative, hospital, etc.
    """

    LABEL_CHOICES = [
        ('home',      'المنزل 🏠'),
        ('work',      'العمل 🏢'),
        ('relative',  'قريب 👨‍👩‍👧'),
        ('temporary', 'مؤقت ⏳'),
        ('hospital',  'مستشفى 🏥'),
        ('other',     'أخرى'),
    ]

    ACCURACY_CHOICES = [
        ('exact',       'دقيق — GPS مؤكد'),
        ('approximate', 'تقريبي — عنوان نصي'),
        ('unverified',  'غير مؤكد'),
    ]

    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='locations',
        verbose_name='العميل',
    )

    # ── Label / type ─────────────────────────────────────────────────────────
    label        = models.CharField(
        max_length=15,
        choices=LABEL_CHOICES,
        default='home',
        verbose_name='نوع العنوان',
    )
    label_custom = models.CharField(max_length=50, blank=True, verbose_name='تسمية مخصصة')
    is_default   = models.BooleanField(default=False, db_index=True, verbose_name='العنوان الافتراضي')

    # ── Address fields ────────────────────────────────────────────────────────
    address_line  = models.TextField(blank=True, verbose_name='العنوان التفصيلي')
    building      = models.CharField(max_length=50,  blank=True, verbose_name='رقم / اسم المبنى')
    floor         = models.CharField(max_length=10,  blank=True, verbose_name='الدور')
    apartment     = models.CharField(max_length=20,  blank=True, verbose_name='رقم الشقة')
    landmark      = models.CharField(max_length=200, blank=True, verbose_name='علامة مميزة')
    area          = models.CharField(max_length=100, blank=True, verbose_name='المنطقة')
    district      = models.CharField(max_length=100, blank=True, verbose_name='الحي')
    governorate   = models.CharField(max_length=100, blank=True, verbose_name='المحافظة')

    # ── GPS ───────────────────────────────────────────────────────────────────
    latitude  = models.DecimalField(
        max_digits=10, decimal_places=7,
        null=True, blank=True,
        verbose_name='خط العرض',
    )
    longitude = models.DecimalField(
        max_digits=10, decimal_places=7,
        null=True, blank=True,
        verbose_name='خط الطول',
    )
    google_maps_url = models.CharField(
        max_length=500, blank=True,
        verbose_name='رابط خرائط جوجل',
    )
    location_accuracy = models.CharField(
        max_length=15,
        choices=ACCURACY_CHOICES,
        default='unverified',
        verbose_name='دقة الموقع',
    )

    # ── Delivery notes ────────────────────────────────────────────────────────
    delivery_phone = models.CharField(max_length=50, blank=True, verbose_name='هاتف التوصيل')
    notes          = models.TextField(blank=True, verbose_name='ملاحظات التوصيل')

    # ── Audit ─────────────────────────────────────────────────────────────────
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='آخر تعديل بواسطة',
    )
    updated_at = models.DateTimeField(auto_now=True,     verbose_name='آخر تعديل')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')

    class Meta:
        ordering = ['-is_default', 'label']
        verbose_name = 'موقع العميل'
        verbose_name_plural = 'مواقع العملاء'
        indexes = [
            models.Index(fields=['customer', 'is_default']),
        ]

    def __str__(self):
        label = self.get_label_display() if not self.label_custom else self.label_custom
        return f'{self.customer.name} — {label}'

    def save(self, *args, **kwargs):
        # Enforce only one default per customer
        if self.is_default:
            CustomerLocation.objects.filter(
                customer=self.customer, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    @property
    def full_address(self):
        parts = filter(None, [
            self.governorate, self.area, self.district,
            self.address_line, self.building, self.floor, self.apartment,
            self.landmark,
        ])
        return ' — '.join(parts)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DeliveryOrder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeliveryOrder(models.Model):
    """
    Core delivery order entity — single source of truth for one delivery.

    Source types:
      call_center  → created by رئيسى call-center staff for branch رئيسى
      branch_pos   → created by branch POS user from the pharmacy branch

    SOFTECH link:
      softech_doc_ref → stktransm.docnumber (doccode='115', ptclassifcode='90')
    """

    # ── Status constants ──────────────────────────────────────────────────────
    STATUS_CREATED             = 'created'
    STATUS_PENDING_REVIEW      = 'pending_review'
    STATUS_PREPARING           = 'preparing'
    STATUS_READY               = 'ready'
    STATUS_ASSIGNED            = 'assigned'
    STATUS_DRIVER_ACCEPTED     = 'driver_accepted'
    STATUS_OUT                 = 'out_for_delivery'
    STATUS_DELIVERED           = 'delivered'
    STATUS_PARTIAL             = 'partial_delivery'
    STATUS_CUSTOMER_UNAVAILABLE = 'customer_unavailable'
    STATUS_FAILED              = 'failed'
    STATUS_RETURNED            = 'returned'
    STATUS_CANCELLED           = 'cancelled'
    STATUS_CLOSED              = 'closed'

    STATUS_CHOICES = [
        (STATUS_CREATED,              'جديد 🆕'),
        (STATUS_PENDING_REVIEW,       'بانتظار المراجعة ⏳'),
        (STATUS_PREPARING,            'جاري التحضير 🔧'),
        (STATUS_READY,                'جاهز للتسليم 📦'),
        (STATUS_ASSIGNED,             'تم التكليف 👤'),
        (STATUS_DRIVER_ACCEPTED,      'السائق قبل الطلب ✅'),
        (STATUS_OUT,                  'في الطريق 🚚'),
        (STATUS_DELIVERED,            'تم التسليم ✅'),
        (STATUS_PARTIAL,              'تسليم جزئي ⚠️'),
        (STATUS_CUSTOMER_UNAVAILABLE, 'العميل غير متاح 📵'),
        (STATUS_FAILED,               'فشل التسليم ❌'),
        (STATUS_RETURNED,             'مُعاد 🔄'),
        (STATUS_CANCELLED,            'ملغى 🚫'),
        (STATUS_CLOSED,               'مغلق 🔒'),
    ]

    # Terminal statuses — no further transitions allowed
    TERMINAL_STATUSES = {
        STATUS_DELIVERED, STATUS_CANCELLED, STATUS_CLOSED
    }

    # ── Source type ───────────────────────────────────────────────────────────
    SOURCE_CC    = 'call_center'
    SOURCE_POS   = 'branch_pos'

    SOURCE_CHOICES = [
        (SOURCE_CC,  'كول سنتر 📞'),
        (SOURCE_POS, 'POS الفرع 🏪'),
    ]

    # ── Payment method ────────────────────────────────────────────────────────
    PAY_CASH     = 'cash'
    PAY_VISA     = 'visa'
    PAY_INSURANCE = 'insurance'
    PAY_MIXED    = 'mixed'
    PAY_WALLET   = 'wallet'
    PAY_PENDING  = 'pending'

    PAYMENT_CHOICES = [
        (PAY_CASH,      'كاش 💵'),
        (PAY_VISA,      'فيزا 💳'),
        (PAY_INSURANCE, 'تأمين 🏥'),
        (PAY_MIXED,     'مختلط'),
        (PAY_WALLET,    'محفظة إلكترونية'),
        (PAY_PENDING,   'لم يُحدد بعد'),
    ]

    # ── Order number & references ─────────────────────────────────────────────
    # null=True so that multiple unsaved rows can coexist without blank collision.
    # The DEL-XXXXXX number is generated in save() after the pk is assigned.
    order_number   = models.CharField(
        max_length=20, unique=True, blank=True, null=True, db_index=True,
        verbose_name='رقم الطلب',
    )
    # piccrmorders.crmorderno — the CRM queue order number from SOFTECH.
    # NOTE: crmorderno is NOT globally unique — it is only unique within a
    # (crmbranchcode, crmorderno) pair. Branch 130's crmorderno=166399 can
    # collide with HQ's crmorderno=166399 (different branches, same number).
    # The composite uniqueness is enforced by the UniqueConstraint in Meta.
    softech_crm_order_no = models.IntegerField(
        null=True, blank=True, db_index=True,
        verbose_name='رقم طلب CRM (SOFTECH)',
        help_text='piccrmorders.crmorderno — فريد فقط بالتركيب مع softech_crm_branch',
    )
    # piccrmorders.crmbranchcode — always '100' for call center
    softech_crm_branch = models.CharField(
        max_length=10, blank=True,
        verbose_name='فرع CRM (SOFTECH)',
        help_text='piccrmorders.crmbranchcode — دائماً 100 للكول سنتر',
    )
    # ─────────────────────────────────────────────────────────────────────────
    # piccrmorders.docnumber5 — the PRE-INVOICE staging document in SOFTECH.
    #
    # This is the PRIMARY SOFTECH reference while the order is PENDING.
    # For CC orders (crmbranchcode='100'): docnumber5 ≠ crmorderno
    #   e.g. crmorderno=166415, docnumber5=712505
    # For branch POS orders: docnumber5 = crmorderno (same value)
    #
    # piccrmorders.docdate5 — the staging document date (typically the business
    # day that started the pre-order, SOFTECHDB date).
    #
    # Use this to look up the order in SOFTECH: branch + docnumber5 + docdate5
    # ─────────────────────────────────────────────────────────────────────────
    softech_doc_number5 = models.IntegerField(
        null=True, blank=True, db_index=True,
        verbose_name='رقم مستند التجهيز (SOFTECH)',
        help_text='piccrmorders.docnumber5 — المرجع الأساسي في SOFTECH للطلب المعلَّق',
    )
    softech_doc_date5 = models.DateField(
        null=True, blank=True,
        verbose_name='تاريخ مستند التجهيز',
        help_text='piccrmorders.docdate5 — تاريخ مستند SOFTECH',
    )
    # piccrmorders.docnumber — the FINAL INVOICE number (filled after delivery).
    # = 0 while order is pending. Populated when order status reaches 90 (delivered).
    softech_doc_ref = models.CharField(
        max_length=100, blank=True, db_index=True,
        verbose_name='رقم الفاتورة النهائية (SOFTECH)',
        help_text='piccrmorders.docnumber — رقم الفاتورة بعد الصرف (0 = معلَّق)',
    )
    softech_branch_code = models.CharField(
        max_length=10, blank=True,
        verbose_name='كود فرع التنفيذ (SOFTECH)',
        help_text='piccrmorders.branchcode — الفرع المُنفِّذ للطلب',
    )
    # piccrmorders.orderusercode — CC agent who placed the order
    softech_order_usercode = models.CharField(
        max_length=10, blank=True,
        verbose_name='كود موظف CRM',
        help_text='piccrmorders.orderusercode — موظف الكول سنتر',
    )
    # Raw SOFTECH status code (10/20/30/44/50/90/100) for diagnostics
    softech_order_status = models.SmallIntegerField(
        null=True, blank=True,
        verbose_name='حالة SOFTECH الخام',
        help_text='piccrmorders.orderstatus — الحالة المصدر في SOFTECH',
    )

    # ── Source & branch ───────────────────────────────────────────────────────
    source_type = models.CharField(
        max_length=15,
        choices=SOURCE_CHOICES,
        default=SOURCE_CC,
        db_index=True,
        verbose_name='مصدر الطلب',
    )
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.PROTECT,
        related_name='delivery_orders',
        verbose_name='الفرع',
    )

    # ── Customer ──────────────────────────────────────────────────────────────
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='delivery_orders',
        verbose_name='العميل',
    )
    customer_name  = models.CharField(max_length=255, verbose_name='اسم العميل')
    customer_phone = models.CharField(max_length=50, blank=True, verbose_name='هاتف العميل')
    customer_phone_alt = models.CharField(max_length=50, blank=True, verbose_name='هاتف بديل')

    # ── Delivery address ──────────────────────────────────────────────────────
    location = models.ForeignKey(
        CustomerLocation,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='orders',
        verbose_name='موقع التوصيل',
    )
    # Snapshot of address at time of order (location record may change later)
    delivery_address   = models.TextField(blank=True, verbose_name='عنوان التوصيل')
    delivery_area      = models.CharField(max_length=100, blank=True, verbose_name='المنطقة')
    delivery_district  = models.CharField(max_length=100, blank=True, verbose_name='الحي')
    delivery_governorate = models.CharField(max_length=100, blank=True, verbose_name='المحافظة')
    delivery_landmark  = models.CharField(max_length=200, blank=True, verbose_name='علامة مميزة')
    delivery_lat = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
        verbose_name='خط العرض',
    )
    delivery_lng = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True,
        verbose_name='خط الطول',
    )
    google_maps_url = models.CharField(
        max_length=500, blank=True,
        verbose_name='رابط خرائط جوجل',
    )

    # ── Financials ────────────────────────────────────────────────────────────
    items_count    = models.IntegerField(default=0, verbose_name='عدد الأصناف')
    total_value    = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name='إجمالي قيمة الأصناف',
    )
    delivery_fees  = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        verbose_name='رسوم التوصيل',
    )
    payment_method = models.CharField(
        max_length=15,
        choices=PAYMENT_CHOICES,
        default=PAY_PENDING,
        verbose_name='طريقة الدفع',
    )
    collected_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='المبلغ المحصَّل',
    )

    # ── Status & workflow ─────────────────────────────────────────────────────
    status = models.CharField(
        max_length=25,
        choices=STATUS_CHOICES,
        default=STATUS_CREATED,
        db_index=True,
        verbose_name='الحالة',
    )
    cancel_reason = models.TextField(blank=True, verbose_name='سبب الإلغاء')
    failure_reason = models.CharField(max_length=500, blank=True, verbose_name='سبب الفشل')

    # ── Assigned driver ───────────────────────────────────────────────────────
    assigned_driver = models.ForeignKey(
        DeliveryDriver,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='current_orders',
        verbose_name='السائق المكلف',
    )

    # ── SLA & timing ──────────────────────────────────────────────────────────
    sla_due_at       = models.DateTimeField(null=True, blank=True, verbose_name='موعد SLA')
    ordered_at       = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='وقت الطلب')
    assigned_at      = models.DateTimeField(null=True, blank=True, verbose_name='وقت التكليف')
    driver_accepted_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت قبول السائق')
    dispatched_at    = models.DateTimeField(null=True, blank=True, verbose_name='وقت الخروج')
    delivered_at     = models.DateTimeField(null=True, blank=True, verbose_name='وقت التسليم')
    failed_at        = models.DateTimeField(null=True, blank=True, verbose_name='وقت الفشل')
    closed_at        = models.DateTimeField(null=True, blank=True, verbose_name='وقت الإغلاق')

    # ── Proof of delivery (captured at completion) ────────────────────────────
    pod_recipient_name = models.CharField(max_length=120, blank=True, verbose_name='المستلِم')
    pod_note           = models.CharField(max_length=500, blank=True, verbose_name='ملاحظة التسليم')
    pod_photo          = models.ImageField(upload_to='delivery_pod/%Y/%m/', null=True, blank=True,
                                           verbose_name='صورة إثبات التسليم')
    pod_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    pod_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # Straight-line distance branch → confirmed delivery point, logged at completion.
    delivery_distance_km = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True,
                                               verbose_name='مسافة التوصيل (كم)')
    # True when pickup/delivery was entered manually by a branch user (rider didn't
    # log it) — the location is an estimate, not a live GPS capture.
    pod_backfilled = models.BooleanField(default=False, verbose_name='إدخال يدوي (تقديري)')

    # ── Route batching ────────────────────────────────────────────────────────
    route = models.ForeignKey(
        'delivery.DeliveryRoute', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='orders', verbose_name='المسار',
    )
    route_sequence = models.PositiveIntegerField(null=True, blank=True, verbose_name='ترتيب التسليم')

    # ── Meta ──────────────────────────────────────────────────────────────────
    notes      = models.TextField(blank=True, verbose_name='ملاحظات')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_deliveries',
        verbose_name='أنشأ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at = models.DateTimeField(auto_now=True,     verbose_name='آخر تعديل')

    class Meta:
        ordering = ['-ordered_at']
        verbose_name = 'طلب توصيل'
        verbose_name_plural = 'طلبات التوصيل'
        indexes = [
            models.Index(fields=['status', 'branch'],      name='del_order_status_branch_v2'),
            models.Index(fields=['ordered_at'],            name='del_order_ordered_at_v2'),
            models.Index(fields=['customer', 'status'],    name='del_order_customer_status'),
            models.Index(fields=['assigned_driver'],       name='del_order_driver'),
            models.Index(fields=['source_type', 'status'], name='del_order_source_status'),
        ]
        constraints = [
            # crmorderno is unique only within a (crmbranchcode, crmorderno) pair.
            # Branch 130 orderno=166399 and HQ orderno=166399 are different orders.
            models.UniqueConstraint(
                fields=['softech_crm_branch', 'softech_crm_order_no'],
                condition=models.Q(softech_crm_order_no__isnull=False),
                name='del_order_crm_branch_orderno_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.order_number or f"DEL-{self.pk}"} — {self.customer_name} ({self.get_status_display()})'

    def save(self, *args, **kwargs):
        if not self.order_number:
            # First save to get the pk, then assign the order number.
            # order_number is nullable so the initial NULL doesn't conflict.
            super().save(*args, **kwargs)
            self.order_number = f'DEL-{self.pk:06d}'
            kwargs['force_insert'] = False
        super().save(*args, **kwargs)

    # ── Computed properties ───────────────────────────────────────────────────

    @property
    def total_with_fees(self):
        return self.total_value + self.delivery_fees

    @property
    def suggested_driver_fee(self):
        """Distance-based driver payout estimate (config base + per-km). None if no distance."""
        if self.delivery_distance_km is None:
            return None
        from apps.config.services import get_setting
        try:
            base   = float(get_setting('delivery_driver_fee_base', default='10'))
            per_km = float(get_setting('delivery_driver_fee_per_km', default='3'))
        except (ValueError, TypeError):
            base, per_km = 10.0, 3.0
        return round(base + per_km * float(self.delivery_distance_km), 2)

    @property
    def delivery_minutes(self):
        if self.dispatched_at and self.delivered_at:
            return int((self.delivered_at - self.dispatched_at).total_seconds() // 60)
        return None

    @property
    def is_late(self):
        if self.sla_due_at and self.status not in self.TERMINAL_STATUSES:
            return timezone.now() > self.sla_due_at
        # Fallback: 60+ min since dispatch without delivery
        if self.dispatched_at and not self.delivered_at:
            return (timezone.now() - self.dispatched_at).total_seconds() > 3600
        return False

    @property
    def is_terminal(self):
        return self.status in self.TERMINAL_STATUSES

    @property
    def age_minutes(self):
        return int((timezone.now() - self.ordered_at).total_seconds() // 60)

    @property
    def cash_variance(self):
        if self.collected_amount is not None:
            return self.collected_amount - self.total_with_fees
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DeliveryOrderItem
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeliveryOrderItem(models.Model):
    """Line items for a delivery order."""

    order = models.ForeignKey(
        DeliveryOrder,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='طلب التوصيل',
    )
    item = models.ForeignKey(
        'catalog.Item',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='delivery_items',
        verbose_name='الصنف',
    )
    item_name  = models.CharField(max_length=500, verbose_name='اسم الصنف')
    item_code  = models.CharField(max_length=20,  blank=True, verbose_name='كود الصنف')
    quantity   = models.DecimalField(max_digits=10, decimal_places=2, default=1, verbose_name='الكمية')
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name='السعر')
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الإجمالي')

    # Partial delivery tracking
    delivered_quantity = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='الكمية المسلَّمة',
    )

    notes = models.TextField(blank=True, verbose_name='ملاحظات')

    class Meta:
        ordering = ['id']
        verbose_name = 'صنف في طلب التوصيل'
        verbose_name_plural = 'أصناف طلبات التوصيل'

    def __str__(self):
        return f'{self.item_name} × {self.quantity} — طلب {self.order_id}'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DeliveryAssignment  (v2 — ForeignKey, immutable history)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeliveryAssignment(models.Model):
    """
    Assignment record.

    Changed from OneToOneField → ForeignKey in v2.
    is_current=True marks the active assignment; previous ones are kept for history.
    Never deleted — only superseded.
    """

    order    = models.ForeignKey(
        DeliveryOrder,
        on_delete=models.CASCADE,
        related_name='assignments',
        verbose_name='طلب التوصيل',
    )
    driver   = models.ForeignKey(
        DeliveryDriver,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assignments',
        verbose_name='السائق',
    )
    # Fallback name when no DeliveryDriver FK exists
    driver_name = models.CharField(max_length=255, blank=True, verbose_name='اسم السائق')
    vehicle     = models.CharField(max_length=100, blank=True, verbose_name='المركبة')

    is_current  = models.BooleanField(default=True, db_index=True, verbose_name='تكليف حالي')

    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_deliveries',
        verbose_name='كُلِّف بواسطة',
    )
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت التكليف')
    notes       = models.TextField(blank=True, verbose_name='ملاحظات')

    class Meta:
        ordering = ['-assigned_at']
        verbose_name = 'تكليف توصيل'
        verbose_name_plural = 'تكليفات التوصيل'

    def __str__(self):
        name = (self.driver.full_name if self.driver else self.driver_name) or '—'
        current = ' ✅' if self.is_current else ''
        return f'تكليف #{self.pk}{current} — {name} → طلب #{self.order_id}'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DeliveryStatusLog  (immutable)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeliveryStatusLog(models.Model):
    """
    Immutable status-change audit trail.
    Every status transition records: timestamp, user, old status, new status, source, comment.
    """

    SOURCE_CHOICES = [
        ('manual',  '👤 يدوي'),
        ('system',  '⚙️ نظام'),
        ('api',     '🔌 API'),
        ('import',  '📥 استيراد'),
        ('mobile',  '📱 موبايل'),
    ]

    order       = models.ForeignKey(
        DeliveryOrder,
        on_delete=models.CASCADE,
        related_name='status_logs',
        verbose_name='طلب التوصيل',
    )
    from_status = models.CharField(max_length=25, verbose_name='من')
    to_status   = models.CharField(max_length=25, verbose_name='إلى')
    source      = models.CharField(
        max_length=10,
        choices=SOURCE_CHOICES,
        default='manual',
        verbose_name='مصدر التغيير',
    )
    notes       = models.TextField(blank=True, verbose_name='ملاحظات')
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='سُجِّل بواسطة',
    )
    recorded_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت التسجيل')

    class Meta:
        ordering = ['recorded_at']
        verbose_name = 'سجل حالة التوصيل'
        verbose_name_plural = 'سجلات حالات التوصيل'

    def __str__(self):
        return f'طلب #{self.order_id}: {self.from_status} → {self.to_status}'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CashCollection
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DeliveryAreaFee  (F9 — Fee Calculator)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeliveryAreaFee(models.Model):
    """
    Configurable delivery fee per area / governorate per branch.
    Used by the Delivery Fee Calculator (F9) and free-delivery threshold (F4).
    """
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.CASCADE,
        related_name='delivery_fees',
        verbose_name='الفرع',
    )
    governorate  = models.CharField(max_length=100, blank=True, db_index=True, verbose_name='المحافظة')
    area         = models.CharField(max_length=100, blank=True, db_index=True, verbose_name='المنطقة / الحي')
    fee_amount   = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name='رسوم التوصيل (ج.م)')
    # Free delivery if order value exceeds this amount (0 = always charged)
    free_above   = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='توصيل مجاني فوق (ج.م)',
        help_text='0 = لا يوجد حد للتوصيل المجاني',
    )
    is_active    = models.BooleanField(default=True, verbose_name='مفعَّل')
    notes        = models.TextField(blank=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('branch', 'governorate', 'area')
        ordering = ['branch', 'governorate', 'area']
        verbose_name = 'رسوم توصيل منطقة'
        verbose_name_plural = 'رسوم توصيل المناطق'

    def __str__(self):
        zone = ' — '.join(filter(None, [self.governorate, self.area])) or 'افتراضي'
        return f'{self.branch} | {zone} | {self.fee_amount} ج.م'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DeliveryCSAT  (F14 — Customer Satisfaction)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DeliveryCSAT(models.Model):
    """Customer satisfaction rating collected after delivery (F14)."""

    SCORE_CHOICES = [(i, '⭐' * i) for i in range(1, 6)]

    CHANNEL_CHOICES = [
        ('whatsapp', '💬 واتساب'),
        ('manual',   '👤 يدوي'),
        ('app',      '📱 تطبيق'),
    ]

    order     = models.OneToOneField(
        DeliveryOrder,
        on_delete=models.CASCADE,
        related_name='csat',
        verbose_name='الطلب',
    )
    score     = models.PositiveSmallIntegerField(
        choices=SCORE_CHOICES,
        null=True, blank=True,
        verbose_name='التقييم (1-5)',
    )
    feedback  = models.TextField(blank=True, verbose_name='تعليق العميل')
    channel   = models.CharField(
        max_length=10, choices=CHANNEL_CHOICES,
        default='whatsapp', verbose_name='قناة التقييم',
    )
    # WhatsApp message sent flag
    wa_sent_at   = models.DateTimeField(null=True, blank=True, verbose_name='وقت إرسال واتساب')
    wa_sent      = models.BooleanField(default=False, verbose_name='أُرسل واتساب')
    responded_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت الرد')
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'تقييم عميل (توصيل)'
        verbose_name_plural = 'تقييمات العملاء (توصيل)'

    def __str__(self):
        return f'CSAT #{self.order.order_number}: {self.score or "—"}/5'


class CashCollection(models.Model):
    """
    Cash collection record per delivery order.
    Tracks expected vs collected cash with audit.
    """

    STATUS_CHOICES = [
        ('pending',   'بانتظار التحصيل ⏳'),
        ('collected', 'تم التحصيل ✅'),
        ('shortage',  'عجز نقدي ⚠️'),
        ('overage',   'زيادة نقدية'),
        ('waived',    'تم الإعفاء'),
        ('disputed',  'خلاف 🔴'),
    ]

    order = models.OneToOneField(
        DeliveryOrder,
        on_delete=models.CASCADE,
        related_name='cash_collection',
        verbose_name='طلب التوصيل',
    )

    expected_amount  = models.DecimalField(
        max_digits=12, decimal_places=2,
        verbose_name='المبلغ المتوقع',
    )
    collected_amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        verbose_name='المبلغ المحصَّل',
    )
    shortage_amount  = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=0,
        verbose_name='مبلغ العجز',
    )
    overage_amount   = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=0,
        verbose_name='مبلغ الزيادة',
    )

    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        verbose_name='حالة التحصيل',
    )

    collection_time = models.DateTimeField(null=True, blank=True, verbose_name='وقت التحصيل')
    collected_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cash_collections',
        verbose_name='حُصِّل بواسطة',
    )
    notes = models.TextField(blank=True, verbose_name='ملاحظات')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تحصيل نقدي'
        verbose_name_plural = 'التحصيلات النقدية'

    def __str__(self):
        return f'تحصيل طلب #{self.order_id}: {self.status}'

    def save(self, *args, **kwargs):
        if self.collected_amount is not None:
            variance = self.collected_amount - self.expected_amount
            if variance < 0:
                self.shortage_amount = abs(variance)
                self.overage_amount  = 0
            elif variance > 0:
                self.overage_amount  = variance
                self.shortage_amount = 0
            else:
                self.shortage_amount = 0
                self.overage_amount  = 0
        super().save(*args, **kwargs)


# ════════════════════════════════════════════════════════════════════════════
# DeliveryRoute — a batch (run) of orders assigned to one driver, dispatched
# together in sequence. The read-only route-plan suggests the grouping; this
# persists a chosen run so it can be assigned, sequenced, and dispatched as one.
# ════════════════════════════════════════════════════════════════════════════

class DeliveryRoute(models.Model):
    STATUS_PLANNED    = 'planned'
    STATUS_DISPATCHED = 'dispatched'
    STATUS_COMPLETED  = 'completed'
    STATUS_CANCELLED  = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PLANNED,    'مُخطّط 📝'),
        (STATUS_DISPATCHED, 'في الطريق 🚚'),
        (STATUS_COMPLETED,  'مكتمل ✅'),
        (STATUS_CANCELLED,  'ملغى 🚫'),
    ]

    branch     = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                   related_name='delivery_routes', null=True, blank=True)
    driver     = models.ForeignKey(DeliveryDriver, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='routes', verbose_name='السائق')
    route_date = models.DateField(default=timezone.localdate, db_index=True, verbose_name='التاريخ')
    status     = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PLANNED,
                                  db_index=True, verbose_name='الحالة')
    notes      = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='created_delivery_routes')
    created_at   = models.DateTimeField(auto_now_add=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-route_date', '-created_at']
        verbose_name        = 'مسار توصيل'
        verbose_name_plural = 'مسارات التوصيل'

    def __str__(self):
        return f'ROUTE-{self.pk} — {self.driver.full_name if self.driver else "?"} ({self.route_date})'

    @property
    def stop_count(self):
        return self.orders.count()

    @property
    def delivered_count(self):
        return self.orders.filter(status=DeliveryOrder.STATUS_DELIVERED).count()

    @property
    def expected_cash(self):
        total = 0
        for o in self.orders.filter(payment_method__in=[DeliveryOrder.PAY_CASH, DeliveryOrder.PAY_MIXED]):
            total += float(o.total_with_fees)
        return round(total, 2)
