from django.db import models
from django.conf import settings


PRICEABLE_FIELDS = [
    # (django_field, arabic_label, softech_column, is_auto_derived)
    # is_auto_derived=True → always recomputed from pack_price; user cannot set independently
    ('pack_price',       'سعر العبوة (بدون ضريبة)',    'itemsaleprice',     False),
    ('pack_price_tax',   'سعر العبوة (شامل الضريبة)',  'itemsaleprice_tax', True),   # auto from pack_price * (1 + tax%)
    ('unit_price',       'سعر الوحدة',                  'unitsaleprice',     True),   # auto from pack_price / packqty
    ('pharmacy_discp',   'خصم الصيدلية %',              'pharmacydiscp',     False),
    ('additional_discp', 'خصم إضافي %',                 'additionaldiscp',   False),
    ('special_discp',    'خصم خاص %',                   'specialdiscp',      False),
    ('pos_discp',        'خصم POS %',                   'posdiscp',          False),
]

# Only user-editable fields appear in the create form
USER_EDITABLE_FIELDS = [(f[0], f[1], f[2]) for f in PRICEABLE_FIELDS if not f[3]]

FIELD_TO_SOFTECH = {f[0]: f[2] for f in PRICEABLE_FIELDS}
FIELD_LABELS     = {f[0]: f[1] for f in PRICEABLE_FIELDS}
AUTO_DERIVED     = {f[0] for f in PRICEABLE_FIELDS if f[3]}


class SupplierDiscountPolicy(models.Model):
    """
    Master expected discount for a supplier or origin group — the "big supplier's
    current discount". The discount-alignment audit compares each item's actual
    basic discount (pharmacy_discp) against the applicable policy and flags drift.
    """
    SCOPE_SUPPLIER = 'supplier'
    SCOPE_ORIGIN   = 'origin'
    SCOPE_CHOICES  = [
        (SCOPE_SUPPLIER, 'المورد'),
        (SCOPE_ORIGIN,   'المنشأ'),
    ]

    scope = models.CharField(
        max_length=10, choices=SCOPE_CHOICES, default=SCOPE_SUPPLIER,
        db_index=True, verbose_name='نطاق السياسة',
    )
    code  = models.CharField(
        max_length=20, db_index=True,
        verbose_name='الكود (مورد/منشأ)',
        help_text='supplier_code (للمورد) أو origin_code (للمنشأ)',
    )
    label = models.CharField(max_length=150, blank=True, verbose_name='الاسم')

    # The current master BASIC discount (خصم أساسى / pharmacydiscp) and, optionally,
    # the expected max-sales cap (حد أقصى خصم مبيعات / posdiscp).
    expected_discount     = models.DecimalField(
        max_digits=6, decimal_places=2,
        verbose_name='الخصم الأساسى المتوقع %',
    )
    expected_pos_discount = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        verbose_name='أقصى خصم مبيعات متوقع %',
    )

    is_active  = models.BooleanField(default=True, db_index=True, verbose_name='مفعّلة')
    note       = models.TextField(blank=True, verbose_name='ملاحظات')
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='discount_policy_updates',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'سياسة خصم المورد/المنشأ'
        verbose_name_plural = 'سياسات خصم الموردين/المناشئ'
        unique_together     = [('scope', 'code')]
        ordering            = ['scope', 'code']

    def __str__(self):
        return f'[{self.get_scope_display()}] {self.code} → {self.expected_discount}%'


class ItemPriceChangeRequest(models.Model):
    STATUS_PENDING  = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_EXECUTED = 'executed'
    STATUS_FAILED   = 'failed'

    STATUS_CHOICES = [
        (STATUS_PENDING,  'في الانتظار'),
        (STATUS_APPROVED, 'معتمد'),
        (STATUS_REJECTED, 'مرفوض'),
        (STATUS_EXECUTED, 'منفذ في Softech'),
        (STATUS_FAILED,   'فشل في التنفيذ'),
    ]

    item         = models.ForeignKey(
        'catalog.Item', on_delete=models.PROTECT,
        related_name='price_change_requests',
        verbose_name='الصنف',
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='price_change_requests',
        verbose_name='طلب بواسطة',
    )
    requested_at = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الطلب')

    # old_values: snapshot of ALL priceable fields at request time
    # new_values: only the user-editable fields the requester wants to change
    # executed_values: what actually got written to Softech (includes auto-derived fields)
    old_values      = models.JSONField(verbose_name='القيم الحالية')
    new_values      = models.JSONField(verbose_name='القيم المقترحة')
    executed_values = models.JSONField(default=dict, verbose_name='القيم المنفذة فعلياً')
    reason          = models.TextField(verbose_name='سبب التعديل')

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default=STATUS_PENDING, db_index=True,
        verbose_name='الحالة',
    )

    reviewed_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='reviewed_price_changes',
        verbose_name='اعتمد/رفض بواسطة',
    )
    reviewed_at  = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ المراجعة')
    review_notes = models.TextField(blank=True, verbose_name='ملاحظات المراجعة')

    # ERP execution — uses the approver's own Softech usercode
    erp_executed_at    = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ التنفيذ في Softech')
    erp_usercode       = models.CharField(max_length=10, blank=True, verbose_name='كود Softech للمعتمِد')
    erp_username       = models.CharField(max_length=50, blank=True, verbose_name='اسم Softech للمعتمِد')
    erp_error          = models.TextField(blank=True, verbose_name='خطأ التنفيذ')

    class Meta:
        ordering = ['-requested_at']
        verbose_name = 'طلب تعديل سعر / خصم'
        verbose_name_plural = 'طلبات تعديل الأسعار والخصومات'

    # Rollback: when this request was created by reverting another request
    rolled_back_from = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='rollbacks', verbose_name='تراجع عن الطلب',
    )
    # Source channel — distinguishes module requests from imported batches
    source = models.CharField(
        max_length=20,
        choices=[('manual', 'يدوي'), ('import', 'استيراد ملف'), ('rollback', 'تراجع')],
        default='manual', db_index=True, verbose_name='مصدر الطلب',
    )

    def __str__(self):
        fields_str = ', '.join(
            f"{FIELD_LABELS.get(k, k)}: {v}"
            for k, v in self.new_values.items()
        )
        return f"[{self.get_status_display()}] {self.item.name} — {fields_str}"


# ════════════════════════════════════════════════════════════════════════════
# Replication audit — tracks whether HQ item changes reached every branch.
# Covers BOTH module-driven changes and direct SOFTECH (Items Master) edits.
# ════════════════════════════════════════════════════════════════════════════

class ReplicationScan(models.Model):
    """One run of the HQ↔branch replication audit over a time window."""
    STATUS_RUNNING = 'running'
    STATUS_DONE    = 'done'
    STATUS_FAILED  = 'failed'
    STATUS_CHOICES = [
        (STATUS_RUNNING, 'قيد التنفيذ'),
        (STATUS_DONE,    'مكتمل'),
        (STATUS_FAILED,  'فشل'),
    ]

    started_at      = models.DateTimeField(auto_now_add=True, verbose_name='بدأ في')
    finished_at     = models.DateTimeField(null=True, blank=True, verbose_name='انتهى في')
    days_window     = models.PositiveIntegerField(default=30, verbose_name='نافذة الأيام')
    status          = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_RUNNING)
    triggered_by    = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='replication_scans', verbose_name='شُغّل بواسطة',
    )
    is_scheduled    = models.BooleanField(default=False, verbose_name='مجدول')

    items_checked   = models.PositiveIntegerField(default=0, verbose_name='أصناف مفحوصة')
    items_ok        = models.PositiveIntegerField(default=0, verbose_name='متطابقة')
    items_with_gaps = models.PositiveIntegerField(default=0, verbose_name='بها فجوات')
    branches_down   = models.JSONField(default=list, verbose_name='فروع غير متاحة')
    error           = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'فحص النسخ المتماثل'
        verbose_name_plural = 'فحوصات النسخ المتماثل'

    def __str__(self):
        return f'Scan #{self.pk} ({self.days_window}d) — {self.items_with_gaps} gaps'


class ReplicationGap(models.Model):
    """A single (item × branch) where the branch did not receive the HQ change."""
    STATUS_STALE       = 'stale'        # branch row older than HQ → missed the change
    STATUS_UNREACHABLE = 'unreachable'  # branch server was down during the check
    STATUS_REPAIRED    = 'repaired'     # re-replication forced and confirmed
    STATUS_CHOICES = [
        (STATUS_STALE,       'متأخر'),
        (STATUS_UNREACHABLE, 'فرع غير متاح'),
        (STATUS_REPAIRED,    'تم الإصلاح'),
    ]

    SOURCE_MODULE = 'module'
    SOURCE_DIRECT = 'direct'
    SOURCE_CHOICES = [
        (SOURCE_MODULE, 'وحدة الموافقات'),
        (SOURCE_DIRECT, 'تعديل مباشر في Softech'),
    ]

    scan              = models.ForeignKey(ReplicationScan, on_delete=models.CASCADE, related_name='gaps')
    item_softech_id   = models.CharField(max_length=6, db_index=True, verbose_name='كود الصنف')
    item_name         = models.CharField(max_length=120, blank=True, verbose_name='اسم الصنف')
    branch_code       = models.CharField(max_length=5, db_index=True, verbose_name='كود الفرع')
    branch_name       = models.CharField(max_length=120, blank=True, verbose_name='اسم الفرع')

    hq_itemlastupdate     = models.DateTimeField(null=True, verbose_name='آخر تحديث HQ')
    branch_itemlastupdate = models.DateTimeField(null=True, verbose_name='آخر تحديث الفرع')
    hq_usercode       = models.CharField(max_length=10, blank=True, verbose_name='كود مستخدم HQ')
    source_user       = models.CharField(max_length=120, blank=True, verbose_name='مصدر التعديل')
    source_channel    = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_DIRECT)
    diff_summary      = models.JSONField(default=dict, verbose_name='فروق القيم')

    status            = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_STALE, db_index=True)
    repaired_at       = models.DateTimeField(null=True, blank=True)
    repaired_by       = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='replication_repairs',
    )
    repair_note       = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-scan__started_at', 'item_softech_id', 'branch_code']
        verbose_name = 'فجوة نسخ متماثل'
        verbose_name_plural = 'فجوات النسخ المتماثل'
        indexes = [models.Index(fields=['status', 'branch_code'])]

    def __str__(self):
        return f'{self.item_softech_id} → BR{self.branch_code} [{self.status}]'


class ReplicationPolicy(models.Model):
    """Singleton (pk=1) — controls the scheduled replication audit/repair job."""
    auto_repair_enabled = models.BooleanField(
        default=False, verbose_name='إصلاح تلقائي',
        help_text='عند التفعيل: تُعاد جدولة الفجوات تلقائياً بعد كل فحص يومي. عند الإيقاف: تنبيه فقط.',
    )
    max_items_per_run = models.PositiveIntegerField(
        default=200, verbose_name='حد أقصى للأصناف في المرة',
        help_text='حد أمان لعدد الأصناف التي يُعاد جدولتها تلقائياً في الفحص الواحد.',
    )
    daily_window_days = models.PositiveIntegerField(
        default=30, verbose_name='نافذة الفحص اليومي (أيام)',
    )
    weekly_full_audit = models.BooleanField(
        default=True, verbose_name='فحص أسبوعي شامل',
        help_text='فحص عميق أسبوعي لكل الأصناف (وليس المعدّلة حديثاً فقط) لاكتشاف الانحراف الصامت.',
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='replication_policy_updates',
    )

    class Meta:
        verbose_name = 'سياسة النسخ المتماثل'
        verbose_name_plural = 'سياسة النسخ المتماثل'

    def __str__(self):
        return f'ReplicationPolicy(auto_repair={self.auto_repair_enabled}, max={self.max_items_per_run})'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
