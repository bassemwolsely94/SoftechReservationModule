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
    # auto = derived from the posting rules / source map; the others are finance's override
    FEED_CHOICES = [('auto', 'تلقائي'), ('softech', 'من SOFTECH'), ('manual', 'يدوي'),
                    ('both', 'الاثنان')]
    feed            = models.CharField(max_length=8, choices=FEED_CHOICES, default='auto',
                                       verbose_name='مصدر التغذية')

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
    # a late-correction entry points at the closed-month entry it corrects
    corrects    = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT,
                                    related_name='corrections', verbose_name='يصحح')
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


# ── Plan 2: drafting engine ───────────────────────────────────────────────────

class GLParty(models.Model):
    TYPE_CHOICES = [('supplier', 'مورد'), ('customer', 'عميل'), ('employee', 'موظف'),
                    ('partner', 'شريك'), ('other', 'أخرى')]
    STATUS_CHOICES = [('unmapped', 'غير مربوط'), ('proposed', 'مقترح'),
                      ('confirmed', 'مؤكد'), ('rejected', 'مرفوض')]
    BASIS_CHOICES = [('exact', 'تطابق تام'), ('tokens', 'تطابق كلمات'), ('manual', 'يدوي'), ('', '')]
    party_type          = models.CharField(max_length=10, choices=TYPE_CHOICES, verbose_name='نوع الطرف')
    code                = models.CharField(max_length=20, verbose_name='الكود')
    name                = models.CharField(max_length=200, verbose_name='الاسم')
    softech_personcode  = models.CharField(max_length=12, blank=True, verbose_name='كود SOFTECH')
    recon_party         = models.ForeignKey('finance.ReconParty', null=True, blank=True,
                                            on_delete=models.SET_NULL, related_name='+',
                                            verbose_name='طرف التسوية')
    status              = models.CharField(max_length=10, choices=STATUS_CHOICES, default='unmapped',
                                           verbose_name='الحالة')
    proposal_basis      = models.CharField(max_length=10, choices=BASIS_CHOICES, blank=True,
                                           verbose_name='أساس الاقتراح')
    confirmed_by        = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                            on_delete=models.PROTECT, related_name='+',
                                            verbose_name='أكده')
    confirmed_at        = models.DateTimeField(null=True, blank=True, verbose_name='وقت التأكيد')
    is_active           = models.BooleanField(default=True, verbose_name='نشط')

    class Meta:
        app_label = 'finance'
        ordering = ['party_type', 'code']
        verbose_name = 'طرف دفتر الأستاذ'
        verbose_name_plural = 'أطراف دفتر الأستاذ'
        constraints = [
            models.UniqueConstraint(fields=['party_type', 'code'], name='gl_party_code_unique'),
            models.UniqueConstraint(
                fields=['party_type', 'softech_personcode'],
                condition=Q(status='confirmed') & ~Q(softech_personcode=''),
                name='gl_party_personcode_confirmed_unique'),
        ]

    @property
    def is_confirmed(self):
        return self.status == 'confirmed'

    def __str__(self):
        return f'{self.code} {self.name}'


class GLSourceMap(models.Model):
    KIND_CHOICES = [('bank', 'خزينة/بنك'), ('expense', 'مصروف'), ('card_clearing', 'تسوية بطاقات'),
                    ('intercompany', 'شركة شقيقة')]   # Ruling P24: SOFTECH branch code -> sister-company account
    kind         = models.CharField(max_length=15, choices=KIND_CHOICES, verbose_name='النوع')
    source_value = models.CharField(max_length=20, verbose_name='قيمة المصدر')
    account      = models.ForeignKey(GLAccount, on_delete=models.PROTECT, related_name='+',
                                     verbose_name='الحساب')
    branch       = models.ForeignKey('branches.Branch', null=True, blank=True,
                                     on_delete=models.PROTECT, related_name='+', verbose_name='الفرع')
    note         = models.CharField(max_length=200, blank=True, verbose_name='ملاحظة')
    updated_by   = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                     on_delete=models.PROTECT, related_name='+', verbose_name='عدّله')
    updated_at   = models.DateTimeField(auto_now=True, verbose_name='وقت التعديل')

    class Meta:
        app_label = 'finance'
        ordering = ['kind', 'source_value']
        verbose_name = 'ربط مصدر بحساب'
        verbose_name_plural = 'ربط المصادر بالحسابات'
        constraints = [
            models.UniqueConstraint(fields=['kind', 'source_value'], name='gl_sourcemap_unique'),
        ]


class PostingRule(models.Model):
    ACTION_CHOICES = [('post', 'ترحيل'), ('skip', 'تجاهل')]
    GRANULARITY_CHOICES = [('document', 'مستند'), ('branch_day', 'فرع/يوم'), ('party_day', 'طرف/يوم')]
    BOOK_CHOICES = [('cash', 'نقدية'), ('credit', 'آجل'), ('general', 'عامة')]
    code           = models.SlugField(max_length=60, verbose_name='الكود')
    version        = models.PositiveIntegerField(default=1, verbose_name='الإصدار')
    source_type    = models.CharField(max_length=30, verbose_name='نوع المصدر')
    description    = models.CharField(max_length=300, blank=True, verbose_name='الوصف')
    conditions     = models.JSONField(default=dict, blank=True, verbose_name='الشروط')
    action         = models.CharField(max_length=5, choices=ACTION_CHOICES, default='post',
                                      verbose_name='الإجراء')
    granularity    = models.CharField(max_length=10, choices=GRANULARITY_CHOICES, default='document',
                                      verbose_name='التجميع')
    lines          = models.JSONField(default=list, blank=True, verbose_name='الأسطر')
    book           = models.CharField(max_length=10, choices=BOOK_CHOICES, default='general',
                                      verbose_name='الدفتر')
    priority       = models.SmallIntegerField(default=100, verbose_name='الأولوية')
    effective_from = models.DateField(verbose_name='ساري من')
    effective_to   = models.DateField(null=True, blank=True, verbose_name='ساري حتى')
    is_active      = models.BooleanField(default=True, verbose_name='نشط')
    created_by     = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                       on_delete=models.PROTECT, related_name='+', verbose_name='أنشأه')
    created_at     = models.DateTimeField(auto_now_add=True, verbose_name='وقت الإنشاء')

    class Meta:
        app_label = 'finance'
        ordering = ['source_type', 'code', '-version']
        verbose_name = 'قاعدة ترحيل'
        verbose_name_plural = 'قواعد الترحيل'
        constraints = [
            models.UniqueConstraint(fields=['code', 'version'], name='gl_rule_code_version_unique'),
        ]

    def delete(self, *args, **kwargs):
        raise models.ProtectedError('Posting rules are versioned and never deleted.', {self})

    def __str__(self):
        return f'{self.code} v{self.version}'


class GLDraftRun(models.Model):
    STATUS_CHOICES = [('running', 'قيد التشغيل'), ('success', 'نجح'),
                      ('partial', 'جزئي'), ('failed', 'فشل')]
    started_at   = models.DateTimeField(auto_now_add=True, verbose_name='بدأ')
    finished_at  = models.DateTimeField(null=True, blank=True, verbose_name='انتهى')
    heartbeat_at = models.DateTimeField(null=True, blank=True, verbose_name='آخر نبضة')
    status       = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running',
                                    verbose_name='الحالة')
    date_from    = models.DateField(verbose_name='من')
    date_to      = models.DateField(verbose_name='إلى')
    source_types = models.JSONField(default=list, blank=True, verbose_name='أنواع المصادر')
    triggered_by = models.CharField(max_length=60, blank=True, verbose_name='شغّله')
    counts       = models.JSONField(default=dict, blank=True, verbose_name='الأعداد')
    detail       = models.JSONField(default=dict, blank=True, verbose_name='تفاصيل')

    class Meta:
        app_label = 'finance'
        ordering = ['-started_at', '-id']
        verbose_name = 'تشغيل ترحيل مسودات'
        verbose_name_plural = 'تشغيلات ترحيل المسودات'
        constraints = [
            models.UniqueConstraint(fields=['status'], condition=Q(status='running'),
                                    name='gl_one_running_draft'),
        ]


class GLSourceDoc(models.Model):
    STATUS_CHOICES = [('new', 'جديد'), ('drafted', 'مسودة'), ('skipped', 'متجاهل'),
                      ('exception', 'استثناء'), ('vanished', 'اختفى')]
    source_type  = models.CharField(max_length=30, verbose_name='نوع المصدر')
    source_key   = models.CharField(max_length=120, unique=True, verbose_name='مفتاح المصدر')
    doc_date     = models.DateField(verbose_name='التاريخ')
    branch_code  = models.CharField(max_length=5, blank=True, verbose_name='كود الفرع')
    kind         = models.CharField(max_length=30, blank=True, verbose_name='النوع')
    personcode   = models.CharField(max_length=12, blank=True, verbose_name='كود الطرف')
    amounts      = models.JSONField(default=dict, verbose_name='المبالغ')
    attrs        = models.JSONField(default=dict, verbose_name='الخصائص')
    content_hash = models.CharField(max_length=64, verbose_name='بصمة المحتوى')
    version      = models.PositiveIntegerField(default=1, verbose_name='الإصدار')
    status       = models.CharField(max_length=10, choices=STATUS_CHOICES, default='new',
                                    verbose_name='الحالة')
    rule         = models.ForeignKey(PostingRule, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name='+', verbose_name='القاعدة')
    group_key    = models.CharField(max_length=160, blank=True, verbose_name='مفتاح التجميع')
    entry        = models.ForeignKey(LedgerEntry, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='source_docs', verbose_name='القيد')
    first_seen   = models.DateTimeField(auto_now_add=True, verbose_name='أول ظهور')
    last_seen    = models.DateTimeField(auto_now=True, verbose_name='آخر ظهور')
    last_run     = models.ForeignKey(GLDraftRun, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+', verbose_name='آخر تشغيل')

    class Meta:
        app_label = 'finance'
        ordering = ['-doc_date', 'id']
        verbose_name = 'مستند مصدر'
        verbose_name_plural = 'مستندات المصدر'
        indexes = [
            models.Index(fields=['source_type', 'doc_date'], name='gl_srcdoc_type_date_idx'),
            models.Index(fields=['group_key'], name='gl_srcdoc_group_idx'),
        ]


class SourceException(models.Model):
    KIND_CHOICES = [
        ('unmapped_party', 'طرف غير مربوط'), ('unmapped_account', 'حساب غير مربوط'),
        ('no_rule', 'لا توجد قاعدة'), ('ambiguous_rule', 'قاعدتان متعارضتان'),
        ('unbalanced_rule', 'قاعدة غير متوازنة'), ('closed_period_change', 'تغيير في فترة مغلقة'),
        ('duplicate_source_key', 'مفتاح مصدر مكرر'), ('ledger_error', 'خطأ في الدفتر'),
    ]
    STATUS_CHOICES = [('open', 'مفتوح'), ('resolved', 'تم الحل'), ('ignored', 'متجاهل')]
    source_doc     = models.ForeignKey(GLSourceDoc, on_delete=models.CASCADE, related_name='exceptions',
                                       verbose_name='مستند المصدر')
    kind           = models.CharField(max_length=25, choices=KIND_CHOICES, verbose_name='النوع')
    source_date    = models.DateField(verbose_name='تاريخ المستند')
    message        = models.CharField(max_length=500, blank=True, verbose_name='الرسالة')
    detail         = models.JSONField(default=dict, blank=True, verbose_name='تفاصيل')
    original_entry = models.ForeignKey(LedgerEntry, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name='+', verbose_name='القيد الأصلي')
    proposed_lines = models.JSONField(null=True, blank=True, verbose_name='الأسطر المقترحة')
    status         = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open',
                                      verbose_name='الحالة')
    created_at     = models.DateTimeField(auto_now_add=True, verbose_name='وقت الإنشاء')
    resolved_by    = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                       on_delete=models.PROTECT, related_name='+', verbose_name='حلّه')
    resolved_at    = models.DateTimeField(null=True, blank=True, verbose_name='وقت الحل')
    resolution_note = models.TextField(blank=True, verbose_name='ملاحظة الحل')

    class Meta:
        app_label = 'finance'
        ordering = ['-created_at', '-id']
        verbose_name = 'استثناء مصدر'
        verbose_name_plural = 'استثناءات المصدر'
        constraints = [
            models.UniqueConstraint(fields=['source_doc', 'kind'], condition=Q(status='open'),
                                    name='gl_one_open_exception_per_kind'),
        ]
