"""
apps/usage_print/models.py — usage-instruction slips printed on receipt paper (Project 5).

One UsageSheet per SOFTECH sale invoice (branch + doccode 115 + docnumber + docdate — never the
docnumber alone). Its lines are a snapshot of the invoice lines plus the instruction a pharmacist
or salesman confirmed. Nothing here is ever written to SOFTECH; every suggestion is deterministic
(earlier confirmations or pharmacist-approved curated content) and nothing prints unconfirmed.
"""
from django.db import models


class UsagePreset(models.Model):
    """Quick-pick text: chips that build a sentence (amount × frequency × timing) or whole phrases."""
    KIND_AMOUNT, KIND_FREQUENCY, KIND_TIMING, KIND_PHRASE = 'amount', 'frequency', 'timing', 'phrase'
    KIND_CHOICES = [
        (KIND_AMOUNT,    'الكمية'),
        (KIND_FREQUENCY, 'عدد المرات'),
        (KIND_TIMING,    'التوقيت'),
        (KIND_PHRASE,    'جملة كاملة'),
    ]
    kind       = models.CharField(max_length=10, choices=KIND_CHOICES, verbose_name='النوع')
    text       = models.CharField(max_length=200, verbose_name='النص')
    sort_order = models.PositiveIntegerField(default=0, verbose_name='الترتيب')
    is_active  = models.BooleanField(default=True, verbose_name='مفعّل')

    class Meta:
        verbose_name = 'قالب طريقة استخدام'
        verbose_name_plural = 'قوالب طريقة الاستخدام'
        ordering = ['kind', 'sort_order', 'id']

    def __str__(self):
        return f'{self.get_kind_display()}: {self.text}'


class UsageSheet(models.Model):
    SOURCE_MIRROR, SOURCE_LIVE = 'mirror', 'live'
    SOURCE_CHOICES = [(SOURCE_MIRROR, 'نسخة المبيعات'), (SOURCE_LIVE, 'قراءة مباشرة من SOFTECH')]
    LAYOUT_SINGLE, LAYOUT_PER_ITEM = 'single', 'per_item'
    LAYOUT_CHOICES = [(LAYOUT_SINGLE, 'ورقة واحدة'), (LAYOUT_PER_ITEM, 'قطعة لكل صنف')]

    branch             = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='+')
    doccode            = models.CharField(max_length=3, default='115')
    docnumber          = models.CharField(max_length=30, verbose_name='رقم الفاتورة')
    docdate            = models.DateField(verbose_name='تاريخ الفاتورة')
    softech_invoice_id = models.CharField(max_length=150, unique=True)   # same key as PurchaseHistory
    source             = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_MIRROR)
    purchase           = models.ForeignKey('customers.PurchaseHistory', null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name='+')
    customer           = models.ForeignKey('customers.Customer', null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name='+')
    patient_name       = models.CharField(max_length=200, blank=True)   # only a real named customer
    pos_order          = models.ForeignKey('pos_orders.SoftechSalesOrder', null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name='+')
    prescription_image = models.ImageField(upload_to='usage_print/prescriptions/%Y/%m/', null=True,
                                           blank=True, verbose_name='صورة الروشتة')
    invoice_changed    = models.BooleanField(default=False)   # lines differed on the last reopen
    print_count        = models.PositiveIntegerField(default=0)
    last_printed_at    = models.DateTimeField(null=True, blank=True)
    last_printed_by    = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name='+')
    last_layout        = models.CharField(max_length=10, choices=LAYOUT_CHOICES, blank=True)
    created_by         = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                           on_delete=models.SET_NULL, related_name='+')
    created_at         = models.DateTimeField(auto_now_add=True)
    updated_at         = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ورقة طريقة استخدام'
        verbose_name_plural = 'أوراق طريقة الاستخدام'
        ordering = ['-created_at']

    def __str__(self):
        return self.softech_invoice_id


class UsageSheetLine(models.Model):
    STATUS_PENDING, STATUS_CONFIRMED, STATUS_EXCLUDED = 'pending', 'confirmed', 'excluded'
    STATUS_CHOICES = [
        (STATUS_PENDING,   'بانتظار التأكيد'),
        (STATUS_CONFIRMED, 'مؤكد'),
        (STATUS_EXCLUDED,  'لا يطبع'),
    ]
    SRC_PATIENT, SRC_COMMON, SRC_CURATED, SRC_NONE = 'patient_last', 'item_common', 'curated', 'none'
    SOURCE_CHOICES = [
        (SRC_PATIENT, 'آخر مرة لنفس المريض'),
        (SRC_COMMON,  'الأكثر استخداما'),
        (SRC_CURATED, 'محتوى معتمد'),
        (SRC_NONE,    'بدون اقتراح'),
    ]

    sheet             = models.ForeignKey(UsageSheet, on_delete=models.CASCADE, related_name='lines')
    item              = models.ForeignKey('catalog.Item', null=True, blank=True, on_delete=models.SET_NULL,
                                          related_name='+')
    itemcode          = models.CharField(max_length=30)
    item_name         = models.CharField(max_length=300, blank=True)
    quantity          = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    suggested_text    = models.CharField(max_length=300, blank=True)
    suggestion_source = models.CharField(max_length=15, choices=SOURCE_CHOICES, default=SRC_NONE)
    text              = models.CharField(max_length=300, blank=True, verbose_name='التعليمات')
    status            = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING,
                                         db_index=True)
    confirmed_by      = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                          on_delete=models.SET_NULL, related_name='+')
    confirmed_at      = models.DateTimeField(null=True, blank=True)
    sort_order        = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = 'سطر طريقة استخدام'
        verbose_name_plural = 'سطور طريقة الاستخدام'
        ordering = ['sort_order', 'id']
        constraints = [models.UniqueConstraint(fields=['sheet', 'itemcode'], name='usage_line_unique_item')]
        indexes = [models.Index(fields=['item', 'status'])]

    def __str__(self):
        return f'{self.item_name}: {self.text}'
