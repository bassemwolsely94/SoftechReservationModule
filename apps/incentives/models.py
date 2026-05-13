"""
apps/incentives/models.py

Item-based sales incentive engine — data models.

Flow:
  IncentiveProgram  → defines a campaign (date range, period type)
  IncentiveRule     → per-item / per-category rules inside a program
  IncentiveTransaction → one ERP line that matched a rule (audit trail)
  IncentiveSettlement  → aggregated settled amount per user per period
"""
from django.db import models
from decimal import Decimal


class IncentiveProgram(models.Model):
    PERIOD_CHOICES = [
        ('weekly',  'أسبوعي'),
        ('monthly', 'شهري'),
        ('custom',  'مخصص'),
    ]

    name               = models.CharField(max_length=200, verbose_name='اسم البرنامج')
    description        = models.TextField(blank=True, verbose_name='الوصف')
    start_date         = models.DateField(verbose_name='تاريخ البداية')
    end_date           = models.DateField(verbose_name='تاريخ النهاية')
    calculation_period = models.CharField(
        max_length=10, choices=PERIOD_CHOICES, default='monthly',
        verbose_name='دورة الاحتساب',
    )
    is_active  = models.BooleanField(default=True, verbose_name='نشط')
    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='incentive_programs',
        verbose_name='أُنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'برنامج حوافز'
        verbose_name_plural = 'برامج الحوافز'
        ordering            = ['-created_at']

    def __str__(self):
        return self.name


class IncentiveRule(models.Model):
    TYPE_CHOICES = [
        ('percent', 'نسبة مئوية %'),
        ('fixed',   'مبلغ ثابت / وحدة'),
    ]

    program   = models.ForeignKey(
        IncentiveProgram, on_delete=models.CASCADE,
        related_name='rules', verbose_name='البرنامج',
    )
    rule_name = models.CharField(max_length=200, blank=True, verbose_name='اسم القاعدة')

    # Item / category targeting — at least one must be set
    item_code     = models.CharField(
        max_length=50, blank=True, verbose_name='كود الصنف',
        help_text='اتركه فارغاً للتطبيق على فئة كاملة',
    )
    item_name     = models.CharField(
        max_length=300, blank=True, verbose_name='اسم الصنف (للعرض)',
    )
    category_code = models.CharField(
        max_length=50, blank=True, verbose_name='كود الفئة (groupcode)',
        help_text='يُطبَّق على كل أصناف هذه الفئة إن لم يُحدَّد كود صنف بعينه',
    )

    # Incentive calculation
    incentive_type  = models.CharField(
        max_length=10, choices=TYPE_CHOICES, default='percent',
        verbose_name='نوع الحافز',
    )
    incentive_value = models.DecimalField(
        max_digits=10, decimal_places=4, verbose_name='قيمة الحافز',
        help_text='نسبة (0–100) للنوع المئوي، أو مبلغ ثابت لكل وحدة للنوع الثابت',
    )
    min_qty = models.DecimalField(
        max_digits=10, decimal_places=3, default=Decimal('0'),
        verbose_name='الحد الأدنى للكمية',
    )

    # Optional filters
    person_code_filter = models.CharField(
        max_length=50, blank=True, verbose_name='فلتر كود المندوب (phcode)',
        help_text='اتركه فارغاً لتطبيقه على جميع المندوبين',
    )
    expiry_within_days = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='أيام الصلاحية',
        help_text='تنطبق فقط على وحدات تنتهي صلاحيتها خلال N يوم',
    )
    priority  = models.PositiveIntegerField(
        default=0, verbose_name='الأولوية',
        help_text='الرقم الأعلى = الأولوية الأعلى عند تعارض القواعد',
    )
    is_active = models.BooleanField(default=True, verbose_name='نشطة')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'قاعدة حوافز'
        verbose_name_plural = 'قواعد الحوافز'
        ordering            = ['-priority', 'item_code']

    def __str__(self):
        target = self.item_name or self.item_code or f'فئة {self.category_code}'
        return f'{self.program.name} — {target}'


class IncentiveTransaction(models.Model):
    """
    Immutable audit record: one ERP sale/return line that earned/reversed an incentive.
    Records are deleted and recreated on every calculate() call for idempotency.
    """
    DOC_TYPE_CHOICES = [
        ('sale',   'بيع'),
        ('return', 'مرتجع'),
    ]

    program    = models.ForeignKey(
        IncentiveProgram, on_delete=models.CASCADE,
        related_name='transactions', verbose_name='البرنامج',
    )
    rule = models.ForeignKey(
        IncentiveRule, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='transactions',
        verbose_name='القاعدة المطبقة',
    )
    user = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='incentive_transactions', verbose_name='المندوب',
    )

    # ERP mirror fields
    item_code  = models.CharField(max_length=50, db_index=True, verbose_name='كود الصنف')
    item_name  = models.CharField(max_length=300, blank=True, verbose_name='اسم الصنف')
    doc_no     = models.CharField(max_length=50, db_index=True, verbose_name='رقم الفاتورة')
    doc_type   = models.CharField(
        max_length=10, choices=DOC_TYPE_CHOICES, default='sale',
        verbose_name='نوع الحركة',
    )
    ref_doc_no = models.CharField(
        max_length=50, blank=True, db_index=True,
        verbose_name='الفاتورة المرجعية',
        help_text='للمرتجعات: رقم فاتورة البيع الأصلية (r_docnumber)',
    )
    quantity        = models.DecimalField(max_digits=12, decimal_places=3, verbose_name='الكمية')
    unit_price      = models.DecimalField(max_digits=12, decimal_places=4, verbose_name='سعر الوحدة')
    incentive_amount = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal('0'),
        verbose_name='مبلغ الحافز',
        help_text='سالب للمرتجعات',
    )
    is_reversed = models.BooleanField(
        default=False, db_index=True, verbose_name='مُعكوس',
        help_text='True إذا تمت إعادة هذا البيع لاحقاً في نفس الفترة',
    )

    # Period & ERP metadata
    period_start = models.DateField(verbose_name='بداية الفترة')
    period_end   = models.DateField(verbose_name='نهاية الفترة')
    erp_date     = models.DateField(null=True, blank=True, verbose_name='تاريخ الحركة')
    branch_code  = models.CharField(max_length=20, blank=True, verbose_name='كود الفرع')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'حركة حافز'
        verbose_name_plural = 'حركات الحوافز'
        ordering            = ['-erp_date', 'doc_no']
        indexes = [
            models.Index(fields=['program', 'period_start', 'period_end']),
            models.Index(fields=['user', 'period_start']),
            models.Index(fields=['doc_no', 'item_code']),
        ]

    def __str__(self):
        return f'{self.doc_no}/{self.item_code} → {self.incentive_amount}'


class IncentiveSettlement(models.Model):
    """
    Finalized per-user totals for a period.
    Created by POST /incentives/finalize/ — cannot be edited after finalization.
    """
    program      = models.ForeignKey(
        IncentiveProgram, on_delete=models.CASCADE,
        related_name='settlements', verbose_name='البرنامج',
    )
    user = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='incentive_settlements', verbose_name='المندوب',
    )
    period_start      = models.DateField(verbose_name='بداية الفترة')
    period_end        = models.DateField(verbose_name='نهاية الفترة')
    total_incentive   = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal('0'),
        verbose_name='إجمالي الحوافز',
    )
    transaction_count = models.PositiveIntegerField(default=0, verbose_name='عدد الحركات')
    is_finalized      = models.BooleanField(default=False, db_index=True, verbose_name='مُعتمد')
    finalized_at      = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الاعتماد')
    finalized_by      = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='finalized_settlements',
        verbose_name='اعتمد بواسطة',
    )
    notes      = models.TextField(blank=True, verbose_name='ملاحظات')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'تسوية حوافز'
        verbose_name_plural = 'تسويات الحوافز'
        ordering            = ['-period_end', 'user']
        unique_together     = [('program', 'user', 'period_start', 'period_end')]

    def __str__(self):
        return f'{self.program} / {self.user.full_name} {self.period_start}→{self.period_end}'
