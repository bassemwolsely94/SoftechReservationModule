"""General Ledger models (finance-gl). Registered under the `finance` app label."""
from django.db import models
from django.db.models import Q


class GLAccountGroup(models.Model):
    SECTION_CHOICES = [('balance_sheet', 'الميزانية'), ('trading', 'المتاجرة'), ('pl', 'الأرباح والخسائر')]
    name    = models.CharField(max_length=120, unique=True, verbose_name='الاسم')
    section = models.CharField(max_length=20, choices=SECTION_CHOICES, verbose_name='القسم')
    order   = models.IntegerField(default=0, verbose_name='الترتيب')

    class Meta:
        app_label = 'finance'
        ordering = ['order', 'id']
        verbose_name = 'مجموعة حسابات'
        verbose_name_plural = 'مجموعات الحسابات'

    def __str__(self):
        return self.name


class GLAccount(models.Model):
    NATURE_CHOICES = [('debit', 'مدين'), ('credit', 'دائن')]
    TYPE_CHOICES = [
        ('asset', 'أصل'), ('contra_asset', 'مقابل أصل'), ('liability', 'التزام'),
        ('equity', 'حقوق ملكية'), ('revenue', 'إيراد'), ('contra_revenue', 'مقابل إيراد'),
        ('expense', 'مصروف'), ('cogs', 'تكلفة بضاعة'),
    ]
    PARTY_CHOICES = [('none', 'بدون'), ('supplier', 'مورد'), ('customer', 'عميل'),
                     ('employee', 'موظف'), ('partner', 'شريك')]
    code            = models.CharField(max_length=10, unique=True, verbose_name='الكود')
    name            = models.CharField(max_length=200, verbose_name='الاسم')
    group           = models.ForeignKey(GLAccountGroup, on_delete=models.PROTECT,
                                        related_name='accounts', verbose_name='المجموعة')
    nature          = models.CharField(max_length=6, choices=NATURE_CHOICES, verbose_name='الطبيعة')
    account_type    = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name='النوع')
    statement_line  = models.CharField(max_length=40, blank=True, verbose_name='بند القائمة')
    is_posting      = models.BooleanField(default=True, verbose_name='يقبل الترحيل')
    is_active       = models.BooleanField(default=True, verbose_name='نشط')
    is_system       = models.BooleanField(default=False, verbose_name='حساب نظام')
    requires_branch = models.BooleanField(default=False, verbose_name='يتطلب فرعاً')
    party_type      = models.CharField(max_length=10, choices=PARTY_CHOICES, default='none',
                                       verbose_name='نوع الطرف')
    requires_party  = models.BooleanField(default=False, verbose_name='يتطلب طرفاً')

    class Meta:
        app_label = 'finance'
        ordering = ['code']
        verbose_name = 'حساب دفتر الأستاذ'
        verbose_name_plural = 'حسابات دفتر الأستاذ'

    def __str__(self):
        return f'{self.code} {self.name}'


class LedgerEntry(models.Model):
    BOOK_CHOICES = [('cash', 'نقدية'), ('credit', 'آجل'), ('general', 'عامة'),
                    ('opening', 'افتتاحية'), ('closing', 'إقفال')]
    STATUS_CHOICES = [('draft', 'مسودة'), ('approved', 'معتمد'), ('reversed', 'معكوس')]
    number      = models.CharField(max_length=30, null=True, blank=True, unique=True, verbose_name='الرقم')
    entry_date  = models.DateField(verbose_name='التاريخ')
    period      = models.ForeignKey('finance.FinancialPeriod', on_delete=models.PROTECT,
                                    related_name='ledger_entries', verbose_name='الفترة')
    book        = models.CharField(max_length=10, choices=BOOK_CHOICES, verbose_name='الدفتر')
    branch      = models.ForeignKey('branches.Branch', null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='+', verbose_name='الفرع')
    description = models.CharField(max_length=500, blank=True, verbose_name='البيان')
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft', verbose_name='الحالة')
    # free text: 'reversal' is used for reversal mirrors (source_key='')
    source_type = models.CharField(max_length=30, blank=True, verbose_name='نوع المصدر')
    source_key  = models.CharField(max_length=120, blank=True, verbose_name='مفتاح المصدر')
    created_by  = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT,
                                    related_name='+', verbose_name='أنشأه')
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name='وقت الإنشاء')
    approved_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='+', verbose_name='اعتمده')
    approved_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت الاعتماد')
    reverses    = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='reversals', verbose_name='يعكس')
    notes       = models.TextField(blank=True, verbose_name='ملاحظات')

    class Meta:
        app_label = 'finance'
        ordering = ['-entry_date', '-id']
        verbose_name = 'قيد يومية'
        verbose_name_plural = 'قيود اليومية'
        indexes = [models.Index(fields=['entry_date', 'status'], name='gl_entry_date_status_idx')]
        constraints = [
            models.UniqueConstraint(
                fields=['source_key'],
                condition=Q(status__in=['draft', 'approved']) & ~Q(source_key=''),
                name='gl_live_source_key_unique'),
        ]

    def __str__(self):
        return self.number or f'draft #{self.pk}'


class LedgerLine(models.Model):
    entry       = models.ForeignKey(LedgerEntry, on_delete=models.CASCADE, related_name='lines',
                                    verbose_name='القيد')
    line_no     = models.PositiveIntegerField(verbose_name='رقم السطر')
    account     = models.ForeignKey(GLAccount, on_delete=models.PROTECT, related_name='lines',
                                    verbose_name='الحساب')
    branch      = models.ForeignKey('branches.Branch', null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='+', verbose_name='الفرع')
    party_code  = models.CharField(max_length=40, blank=True, verbose_name='كود الطرف')
    debit       = models.DecimalField(max_digits=18, decimal_places=2, default=0, verbose_name='مدين')
    credit      = models.DecimalField(max_digits=18, decimal_places=2, default=0, verbose_name='دائن')
    description = models.CharField(max_length=500, blank=True, verbose_name='البيان')
    cheque_no   = models.CharField(max_length=40, blank=True, verbose_name='رقم الشيك')
    due_date    = models.DateField(null=True, blank=True, verbose_name='تاريخ الاستحقاق')

    class Meta:
        app_label = 'finance'
        ordering = ['entry_id', 'line_no']
        verbose_name = 'سطر قيد'
        verbose_name_plural = 'أسطر القيود'
        indexes = [models.Index(fields=['account', 'entry'], name='gl_line_account_entry_idx')]
        constraints = [
            models.CheckConstraint(
                check=Q(debit__gte=0) & Q(credit__gte=0) & ~(Q(debit__gt=0) & Q(credit__gt=0)),
                name='gl_line_amounts_valid'),
        ]


class GLSequence(models.Model):
    year = models.IntegerField(unique=True, verbose_name='السنة')
    last = models.IntegerField(default=0, verbose_name='آخر رقم')

    class Meta:
        app_label = 'finance'
        verbose_name = 'تسلسل القيود'
        verbose_name_plural = 'تسلسلات القيود'
