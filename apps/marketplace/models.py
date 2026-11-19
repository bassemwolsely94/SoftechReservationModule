"""
apps/marketplace/models.py — platform-agnostic selling through delivery / e-commerce platforms (doc 38).

A MarketplaceChannel is one platform (Talabat, InstaShop, ...); ChannelStore ties it to a branch;
ChannelListing is the approved-items list; ExternalOrder(+Line/Event) is an order that came in from
the platform and is handed to the existing indirect POS (SoftechSalesOrder). Nothing here is ever
written to SOFTECH directly; pushes to a platform are logged in PushLog and gated by flags.
"""
from django.db import models


class MarketplaceChannel(models.Model):
    ADAPTER_MANUAL, ADAPTER_FAKE = 'manual', 'fake'
    ADAPTER_CHOICES = [(ADAPTER_MANUAL, 'يدوي'), (ADAPTER_FAKE, 'تجريبي')]
    SCOPE_PER_BRANCH, SCOPE_NATIONAL = 'per_branch', 'national'
    SCOPE_CHOICES = [(SCOPE_PER_BRANCH, 'لكل فرع'), (SCOPE_NATIONAL, 'على مستوى الشركة')]
    PRICE_SHELF, PRICE_SHELF_PLUS_PCT = 'shelf', 'shelf_plus_pct'
    PRICE_CHOICES = [(PRICE_SHELF, 'سعر الرف'), (PRICE_SHELF_PLUS_PCT, 'سعر الرف + نسبة')]

    code = models.SlugField(unique=True, verbose_name='الكود')
    name = models.CharField(max_length=120, verbose_name='الاسم')
    adapter = models.CharField(max_length=20, choices=ADAPTER_CHOICES, default=ADAPTER_MANUAL, verbose_name='المحوّل')
    scope = models.CharField(max_length=12, choices=SCOPE_CHOICES, default=SCOPE_PER_BRANCH, verbose_name='النطاق')
    softech_personcode = models.CharField(max_length=8, blank=True, verbose_name='كود العميل في SOFTECH')
    price_rule = models.CharField(max_length=16, choices=PRICE_CHOICES, default=PRICE_SHELF, verbose_name='قاعدة السعر')
    price_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name='نسبة السعر %')
    stock_buffer = models.DecimalField(max_digits=12, decimal_places=3, default=1, verbose_name='احتياطي المخزون')
    max_qty_per_item = models.PositiveIntegerField(null=True, blank=True, verbose_name='أقصى كمية للصنف')
    is_active = models.BooleanField(default=False, verbose_name='مفعّل')
    credentials = models.JSONField(default=dict, blank=True, verbose_name='بيانات الاعتماد')  # never serialized
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'منصة'
        verbose_name_plural = 'المنصات'
        ordering = ['name']

    def __str__(self):
        return self.name


class ChannelStore(models.Model):
    MODE_PLATFORM, MODE_OWN = 'platform_rider', 'own_rider'
    MODE_CHOICES = [(MODE_PLATFORM, 'مندوب المنصة'), (MODE_OWN, 'مندوبنا')]

    channel = models.ForeignKey(MarketplaceChannel, on_delete=models.CASCADE, related_name='stores', verbose_name='المنصة')
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='marketplace_stores', verbose_name='الفرع')
    external_store_id = models.CharField(max_length=100, blank=True, verbose_name='كود المتجر عند المنصة')
    delivery_mode = models.CharField(max_length=16, choices=MODE_CHOICES, default=MODE_PLATFORM, verbose_name='طريقة التوصيل')
    is_active = models.BooleanField(default=False, verbose_name='مفعّل')

    class Meta:
        verbose_name = 'متجر منصة'
        verbose_name_plural = 'متاجر المنصات'
        constraints = [models.UniqueConstraint(fields=['channel', 'branch'], name='uniq_channelstore_channel_branch')]

    def __str__(self):
        return f'{self.channel} / {self.branch}'


class ChannelListing(models.Model):
    channel = models.ForeignKey(MarketplaceChannel, on_delete=models.CASCADE, related_name='listings', verbose_name='المنصة')
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, related_name='marketplace_listings', verbose_name='الصنف')
    external_sku = models.CharField(max_length=100, blank=True, verbose_name='كود الصنف عند المنصة')
    approved = models.BooleanField(default=False, verbose_name='معتمد')
    approved_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+', verbose_name='اعتمده')
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت الاعتماد')
    allow_fridge = models.BooleanField(default=False, verbose_name='يسمح بالثلاجة')
    note = models.TextField(blank=True, verbose_name='ملاحظة')

    class Meta:
        verbose_name = 'صنف على منصة'
        verbose_name_plural = 'أصناف المنصات'
        constraints = [models.UniqueConstraint(fields=['channel', 'item'], name='uniq_channellisting_channel_item')]

    def __str__(self):
        return f'{self.channel} / {self.item_id}'


class ExternalOrder(models.Model):
    STATUS_RECEIVED, STATUS_ACCEPTED, STATUS_REJECTED, STATUS_PREPARING = 'received', 'accepted', 'rejected', 'preparing'
    STATUS_READY, STATUS_HANDED_OVER, STATUS_DELIVERED, STATUS_CANCELLED = 'ready', 'handed_over', 'delivered', 'cancelled'
    STATUS_CHOICES = [
        (STATUS_RECEIVED, 'جديد'),
        (STATUS_ACCEPTED, 'مقبول'),
        (STATUS_REJECTED, 'مرفوض'),
        (STATUS_PREPARING, 'جاري التحضير'),
        (STATUS_READY, 'جاهز للتسليم'),
        (STATUS_HANDED_OVER, 'سُلِّم للمندوب'),
        (STATUS_DELIVERED, 'تم التوصيل'),
        (STATUS_CANCELLED, 'ملغى'),
    ]
    SOURCE_API, SOURCE_MANUAL = 'api', 'manual'
    SOURCE_CHOICES = [(SOURCE_API, 'من المنصة'), (SOURCE_MANUAL, 'إدخال يدوي')]
    PAY_PLATFORM, PAY_COD = 'platform_paid', 'cash_on_delivery'
    PAY_CHOICES = [(PAY_PLATFORM, 'مدفوع للمنصة'), (PAY_COD, 'الدفع عند الاستلام')]

    channel = models.ForeignKey(MarketplaceChannel, on_delete=models.PROTECT, related_name='orders', verbose_name='المنصة')
    store = models.ForeignKey(ChannelStore, on_delete=models.PROTECT, related_name='orders', verbose_name='المتجر')
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='marketplace_orders', verbose_name='الفرع')
    external_id = models.CharField(max_length=100, verbose_name='رقم الطلب عند المنصة')
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_MANUAL, verbose_name='المصدر')
    status = models.CharField(max_length=14, choices=STATUS_CHOICES, default=STATUS_RECEIVED, db_index=True, verbose_name='الحالة')
    customer_name = models.CharField(max_length=200, blank=True, verbose_name='اسم العميل')
    customer_phone = models.CharField(max_length=30, blank=True, verbose_name='هاتف العميل')   # masked on output
    delivery_address = models.TextField(blank=True, verbose_name='عنوان التوصيل')
    payment_mode = models.CharField(max_length=16, choices=PAY_CHOICES, default=PAY_PLATFORM, verbose_name='طريقة الدفع')
    platform_total = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='إجمالي المنصة')
    raw_payload = models.JSONField(default=dict, blank=True, verbose_name='البيانات الخام')
    reject_reason = models.CharField(max_length=200, blank=True, verbose_name='سبب الرفض')
    pos_order = models.OneToOneField('pos_orders.SoftechSalesOrder', null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='marketplace_order', verbose_name='طلب نقطة البيع')
    needs_review = models.BooleanField(default=False, verbose_name='يحتاج مراجعة')
    created_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+', verbose_name='أنشأه')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'طلب منصة'
        verbose_name_plural = 'طلبات المنصات'
        ordering = ['-created_at', '-id']
        constraints = [models.UniqueConstraint(fields=['channel', 'external_id'], name='uniq_externalorder_channel_extid')]

    def __str__(self):
        return f'{self.channel_id}:{self.external_id}'


class ExternalOrderLine(models.Model):
    PROBLEM_NONE, PROBLEM_NOT_LISTED, PROBLEM_BLOCKED, PROBLEM_OOS = '', 'not_listed', 'blocked', 'out_of_stock'
    PROBLEM_CHOICES = [
        (PROBLEM_NONE, 'بدون مشكلة'),
        (PROBLEM_NOT_LISTED, 'غير معتمد على المنصة'),
        (PROBLEM_BLOCKED, 'ممنوع'),
        (PROBLEM_OOS, 'غير متوفر'),
    ]

    order = models.ForeignKey(ExternalOrder, on_delete=models.CASCADE, related_name='lines', verbose_name='الطلب')
    listing = models.ForeignKey(ChannelListing, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+', verbose_name='الصنف المعتمد')
    item = models.ForeignKey('catalog.Item', null=True, blank=True, on_delete=models.SET_NULL,
                             related_name='+', verbose_name='الصنف')
    external_sku = models.CharField(max_length=100, blank=True, verbose_name='كود الصنف عند المنصة')
    name = models.CharField(max_length=300, blank=True, verbose_name='الاسم')
    qty = models.DecimalField(max_digits=12, decimal_places=3, default=1, verbose_name='الكمية')
    platform_unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='سعر الوحدة عند المنصة')
    problem = models.CharField(max_length=12, blank=True, default='', choices=PROBLEM_CHOICES, verbose_name='المشكلة')

    class Meta:
        verbose_name = 'سطر طلب منصة'
        verbose_name_plural = 'سطور طلبات المنصات'
        ordering = ['id']


class ExternalOrderEvent(models.Model):
    order = models.ForeignKey(ExternalOrder, on_delete=models.CASCADE, related_name='events', verbose_name='الطلب')
    from_status = models.CharField(max_length=14, blank=True, verbose_name='من حالة')
    to_status = models.CharField(max_length=14, verbose_name='إلى حالة')
    by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                           related_name='+', verbose_name='بواسطة')
    note = models.CharField(max_length=300, blank=True, verbose_name='ملاحظة')
    at = models.DateTimeField(auto_now_add=True, verbose_name='الوقت')

    class Meta:
        verbose_name = 'حدث طلب منصة'
        verbose_name_plural = 'أحداث طلبات المنصات'
        ordering = ['at', 'id']


class PushLog(models.Model):
    KIND_STOCK, KIND_PRICE, KIND_STATUS = 'stock', 'price', 'status'
    KIND_CHOICES = [(KIND_STOCK, 'مخزون'), (KIND_PRICE, 'سعر'), (KIND_STATUS, 'حالة')]

    channel = models.ForeignKey(MarketplaceChannel, on_delete=models.CASCADE, related_name='push_logs', verbose_name='المنصة')
    store = models.ForeignKey(ChannelStore, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='+', verbose_name='المتجر')
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, verbose_name='النوع')
    dry_run = models.BooleanField(default=True, verbose_name='تجربة فقط')
    payload = models.JSONField(default=dict, blank=True, verbose_name='المرسل')
    response = models.JSONField(default=dict, blank=True, verbose_name='الرد')
    ok = models.BooleanField(default=False, verbose_name='نجح')
    at = models.DateTimeField(auto_now_add=True, verbose_name='الوقت')

    class Meta:
        verbose_name = 'سجل إرسال للمنصة'
        verbose_name_plural = 'سجلات الإرسال للمنصات'
        ordering = ['-at', '-id']


class SettlementBatch(models.Model):
    channel = models.ForeignKey(MarketplaceChannel, on_delete=models.PROTECT, related_name='settlements', verbose_name='المنصة')
    period_from = models.DateField(verbose_name='من')
    period_to = models.DateField(verbose_name='إلى')
    file_name = models.CharField(max_length=255, blank=True, verbose_name='اسم الملف')
    uploaded_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+', verbose_name='رفعه')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت الرفع')
    column_map = models.JSONField(default=dict, blank=True, verbose_name='خريطة الأعمدة')

    class Meta:
        verbose_name = 'تسوية منصة'
        verbose_name_plural = 'تسويات المنصات'
        ordering = ['-uploaded_at', '-id']


class SettlementLine(models.Model):
    MATCHED, UNMATCHED, AMOUNT_MISMATCH, NOT_IN_FILE = 'matched', 'unmatched', 'amount_mismatch', 'not_in_file'
    MATCH_CHOICES = [
        (MATCHED, 'مطابق'),
        (UNMATCHED, 'غير موجود'),
        (AMOUNT_MISMATCH, 'اختلاف مبلغ'),
        (NOT_IN_FILE, 'غير موجود بالملف'),
    ]

    batch = models.ForeignKey(SettlementBatch, on_delete=models.CASCADE, related_name='lines', verbose_name='التسوية')
    external_id = models.CharField(max_length=100, verbose_name='رقم الطلب عند المنصة')
    gross = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الإجمالي')
    commission = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='العمولة')
    delivery_fee = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='رسوم التوصيل')
    net = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الصافي')
    order = models.ForeignKey(ExternalOrder, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='+', verbose_name='الطلب')
    match_status = models.CharField(max_length=16, choices=MATCH_CHOICES, default=UNMATCHED, verbose_name='نتيجة المطابقة')
    note = models.TextField(blank=True, verbose_name='ملاحظة')

    class Meta:
        verbose_name = 'سطر تسوية'
        verbose_name_plural = 'سطور التسوية'
        ordering = ['id']
