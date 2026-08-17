"""
apps/incentives/models.py  —  v4

Item-based sales incentive engine — data models.

Flow:
  IncentiveProgram      → campaign (date range, period type)
  IncentiveRule         → per-item / per-category rules inside a program
  IncentiveRuleItem     → items belonging to a multi-item rule (CSV or manual)
  IncentiveTransaction  → one ERP line that matched a rule (immutable audit trail)
  IncentiveSettlement   → aggregated settled amount per user per period
  AdjustmentEntry       → manual +/- corrections to a settlement
  IncentiveCalculationLog → audit log of every calculate() / simulate() run
"""
from django.db import models
from decimal import Decimal


# ─────────────────────────────────────────────────────────────────────────────
# Incentive Program
# ─────────────────────────────────────────────────────────────────────────────

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

    # ── Supplier / sponsor ────────────────────────────────────────────────────
    sponsor_name = models.CharField(
        max_length=200, blank=True,
        verbose_name='اسم الجهة الراعية',
        help_text='اسم المورد أو الشركة التي تموّل البرنامج جزئياً أو كلياً',
    )
    sponsor_contribution_pct = models.DecimalField(
        max_digits=6, decimal_places=3,
        null=True, blank=True,
        verbose_name='نسبة مساهمة الراعي %',
        help_text='0–100. مثال: 60 = الراعي يتحمّل 60%، الصيدلية تتحمّل 40%',
    )

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


# ─────────────────────────────────────────────────────────────────────────────
# Incentive Rule
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveRule(models.Model):
    TYPE_CHOICES = [
        ('percent',            'نسبة مئوية % من صافي البيع'),
        ('fixed',              'مبلغ ثابت / وحدة (قديم)'),     # backward-compat alias
        ('fixed_per_unit',     'مبلغ ثابت / وحدة'),
        ('fixed_per_transaction', 'مبلغ ثابت / فاتورة'),
        ('tiered',             'متدرج (سلاب)'),
        ('target_based',       'قائم على الهدف (شرائح إنجاز)'),
    ]

    program   = models.ForeignKey(
        IncentiveProgram, on_delete=models.CASCADE,
        related_name='rules', verbose_name='البرنامج',
    )
    rule_name = models.CharField(max_length=200, blank=True, verbose_name='اسم القاعدة')

    # ── Item / category targeting ─────────────────────────────────────────────
    item_code     = models.CharField(
        max_length=50, blank=True, verbose_name='كود الصنف (صنف وحيد)',
        help_text='اتركه فارغاً عند استخدام قائمة الأصناف (IncentiveRuleItem)',
    )
    item_name     = models.CharField(
        max_length=300, blank=True, verbose_name='اسم الصنف (للعرض)',
    )
    category_code = models.CharField(
        max_length=50, blank=True, verbose_name='كود الفئة (groupcode)',
        help_text='معلوماتي فقط — لا يُطبَّق في المحرك',
    )

    # ── Incentive calculation ─────────────────────────────────────────────────
    incentive_type  = models.CharField(
        max_length=25, choices=TYPE_CHOICES, default='percent',
        verbose_name='نوع الحافز',
    )
    incentive_value = models.DecimalField(
        max_digits=10, decimal_places=4, verbose_name='قيمة الحافز',
        help_text=(
            'نسبة (0–100) لـ percent | مبلغ لكل وحدة لـ fixed* | '
            'مبلغ ثابت للفاتورة لـ fixed_per_transaction | '
            'غير مستخدم عند tiered (استخدم slab_config)'
        ),
    )

    # ── Tiered / slab config ──────────────────────────────────────────────────
    # JSON format:
    # {
    #   "type": "percent" | "fixed_per_unit",
    #   "slabs": [
    #     {"min_qty": 0,   "max_qty": 49,  "rate": 2.0},
    #     {"min_qty": 50,  "max_qty": 199, "rate": 5.0},
    #     {"min_qty": 200, "max_qty": null, "rate": 10.0}
    #   ]
    # }
    # Applied to TOTAL period qty per (user, item).  The matching slab rate
    # is applied to ALL units (not incrementally).
    slab_config = models.JSONField(
        null=True, blank=True,
        verbose_name='إعداد السلاب (للنوع المتدرج)',
    )

    # ── Standard conditions ───────────────────────────────────────────────────
    min_qty = models.DecimalField(
        max_digits=10, decimal_places=3, default=Decimal('0'),
        verbose_name='الحد الأدنى للكمية (لكل حركة)',
    )
    min_total_qty_in_period = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True,
        verbose_name='الحد الأدنى لإجمالي الكمية في الفترة',
        help_text='القاعدة لا تُطبَّق إلا إذا بلغت الكمية الإجمالية للصنف هذا الحد',
    )

    # ── Person / branch / time filters ───────────────────────────────────────
    person_code_filter = models.CharField(
        max_length=50, blank=True, verbose_name='فلتر كود المندوب (phcode)',
        help_text='فارغ = يُطبَّق على جميع المندوبين',
    )
    branch_filter = models.CharField(
        max_length=50, blank=True, verbose_name='فلتر الفرع (branchcode)',
        help_text='فارغ = جميع الفروع',
    )
    # Transactions must fall within this time window (server time)
    time_window_start = models.TimeField(
        null=True, blank=True, verbose_name='بداية النافذة الزمنية',
    )
    time_window_end = models.TimeField(
        null=True, blank=True, verbose_name='نهاية النافذة الزمنية',
    )
    expiry_within_days = models.PositiveIntegerField(
        null=True, blank=True, verbose_name='أيام الصلاحية',
        help_text='تنطبق فقط على وحدات تنتهي صلاحيتها خلال N يوم',
    )

    # ── Near-expiry: origin filter ────────────────────────────────────────────
    IMPORTED_FILTER_CHOICES = [
        ('any',      'الكل (محلي + مستورد)'),
        ('local',    'محلي فقط'),
        ('imported', 'مستورد فقط'),
    ]
    is_imported_filter = models.CharField(
        max_length=10,
        choices=IMPORTED_FILTER_CHOICES,
        default='any',
        verbose_name='فلتر المصدر',
        help_text='any = لا فلترة | local = محلي فقط | imported = مستورد فقط',
    )
    origin_codes = models.JSONField(
        null=True, blank=True,
        verbose_name='كودات المصدر',
        help_text=(
            'قائمة كودات الدولة (itemorigincode) المسموح بها. '
            'فارغ = جميع المصادر.'
        ),
    )

    # ── Near-expiry: margin filter ────────────────────────────────────────────
    margin_min = models.DecimalField(
        max_digits=7, decimal_places=3,
        null=True, blank=True,
        verbose_name='الحد الأدنى لهامش الربح %',
        help_text='مثال: 15 — تُطبَّق فقط على أصناف هامش ربحها >= 15%',
    )
    margin_max = models.DecimalField(
        max_digits=7, decimal_places=3,
        null=True, blank=True,
        verbose_name='الحد الأقصى لهامش الربح %',
        help_text='مثال: 40 — تُطبَّق فقط على أصناف هامش ربحها <= 40%',
    )

    # ── Near-expiry: pack price filter ────────────────────────────────────────
    pack_price_min = models.DecimalField(
        max_digits=10, decimal_places=3,
        null=True, blank=True,
        verbose_name='الحد الأدنى لسعر العبوة',
        help_text='مثال: 50 — تُطبَّق فقط على أصناف سعرها >= 50',
    )
    pack_price_max = models.DecimalField(
        max_digits=10, decimal_places=3,
        null=True, blank=True,
        verbose_name='الحد الأقصى لسعر العبوة',
        help_text='مثال: 500 — تُطبَّق فقط على أصناف سعرها <= 500',
    )

    # ── Target-based incentive ────────────────────────────────────────────────
    target_qty = models.DecimalField(
        max_digits=12, decimal_places=3,
        null=True, blank=True,
        verbose_name='الهدف الكمي (وحدات/فترة)',
        help_text='الكمية الكاملة المستهدفة (100%) لكل مندوب. مطلوب عند نوع target_based.',
    )
    # JSON: {"tiers": [{"min_pct": 80, "max_pct": 99, "rate": 5.0, "type": "fixed_per_unit"}, ...]}
    target_tiers = models.JSONField(
        null=True, blank=True,
        verbose_name='شرائح الإنجاز (target_based)',
        help_text='شرائح نسب الإنجاز والمكافآت المقابلة لها',
    )

    # ── Priority / active ─────────────────────────────────────────────────────
    priority  = models.PositiveIntegerField(
        default=0, verbose_name='الأولوية',
        help_text='الرقم الأقل = أولوية أعلى عند التعارض (0 = الأعلى أولوية)',
    )
    is_active = models.BooleanField(default=True, verbose_name='نشطة')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'قاعدة حوافز'
        verbose_name_plural = 'قواعد الحوافز'
        ordering            = ['priority', 'item_code']

    def __str__(self):
        target = self.rule_name or self.item_name or self.item_code or f'فئة {self.category_code}'
        return f'{self.program.name} — {target}'


# ─────────────────────────────────────────────────────────────────────────────
# Rule Items (multi-item targeting)
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveRuleItem(models.Model):
    """
    One item belonging to a multi-item rule.
    A rule can target either IncentiveRule.item_code (single legacy field)
    OR any number of IncentiveRuleItem records.  Engine evaluates both.

    incentive_override — overrides the rule's global incentive_value for this SKU.
    """
    rule = models.ForeignKey(
        IncentiveRule, on_delete=models.CASCADE,
        related_name='rule_items', verbose_name='القاعدة',
    )
    item_code = models.CharField(max_length=50, db_index=True, verbose_name='كود الصنف')
    item_name = models.CharField(max_length=300, blank=True, verbose_name='اسم الصنف')
    incentive_override = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True,
        verbose_name='قيمة حافز خاصة (override)',
        help_text='فارغ → يُستخدم incentive_value من القاعدة الأصلية',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'صنف القاعدة'
        verbose_name_plural = 'أصناف القاعدة'
        unique_together     = [('rule', 'item_code')]
        ordering            = ['item_code']

    def __str__(self):
        return f'{self.item_code} — {self.item_name}'


# ─────────────────────────────────────────────────────────────────────────────
# Incentive Transaction  (immutable audit trail — written only by engine)
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveTransaction(models.Model):
    DOC_TYPE_CHOICES = [
        ('sale',   'بيع'),
        ('return', 'مرتجع'),
    ]

    program = models.ForeignKey(
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
        help_text='للمرتجعات: رقم فاتورة البيع الأصلية',
    )
    quantity         = models.DecimalField(max_digits=12, decimal_places=3, verbose_name='الكمية')
    unit_price       = models.DecimalField(max_digits=12, decimal_places=4, verbose_name='سعر الوحدة')
    incentive_amount = models.DecimalField(
        max_digits=12, decimal_places=4, default=Decimal('0'),
        verbose_name='مبلغ الحافز',
        help_text='سالب للمرتجعات',
    )
    is_reversed = models.BooleanField(
        default=False, db_index=True, verbose_name='مُعكوس (مُسترجَع)',
        help_text='True إذا تمت إعادة هذا البيع لاحقاً',
    )

    # ── Near-expiry batch audit ───────────────────────────────────────────────
    expiry_date = models.DateField(
        null=True, blank=True, db_index=True,
        verbose_name='تاريخ انتهاء الصلاحية',
        help_text='من stktrans.itemexpirydate — تاريخ انتهاء صلاحية الدُفعة المُباعة',
    )
    expiry_days_remaining = models.IntegerField(
        null=True, blank=True,
        verbose_name='أيام الصلاحية المتبقية',
        help_text='عدد الأيام المتبقية في تاريخ البيع (سالب = انتهت الصلاحية)',
    )

    # Period & ERP metadata
    period_start  = models.DateField(verbose_name='بداية الفترة')
    period_end    = models.DateField(verbose_name='نهاية الفترة')
    erp_date      = models.DateField(null=True, blank=True, verbose_name='تاريخ الحركة')
    branch_code   = models.CharField(max_length=20, blank=True, verbose_name='كود الفرع')
    is_cross_period_return = models.BooleanField(
        default=False,
        verbose_name='مرتجع من فترة مختلفة',
        help_text='True إذا كانت حركة المرتجع تقع خارج نافذة الفترة الحالية',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'حركة حافز'
        verbose_name_plural = 'حركات الحوافز'
        ordering            = ['-erp_date', 'doc_no']
        indexes = [
            models.Index(fields=['program', 'period_start', 'period_end'],
                         name='incentive_prog_period_idx'),
            models.Index(fields=['user', 'period_start'],
                         name='incentive_user_period_idx'),
            models.Index(fields=['doc_no', 'item_code'],
                         name='incentive_doc_item_idx'),
            models.Index(fields=['program', 'expiry_date'],
                         name='incentive_prog_expiry_idx'),
        ]

    def __str__(self):
        return f'{self.doc_no}/{self.item_code} → {self.incentive_amount}'


# ─────────────────────────────────────────────────────────────────────────────
# Incentive Settlement  (finalized per-user totals)
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveSettlement(models.Model):
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
    # Raw incentive total from transactions (before adjustments)
    total_incentive   = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal('0'),
        verbose_name='إجمالي الحوافز (من الحركات)',
    )
    # Adjustment total (sum of AdjustmentEntry.amount)
    total_adjustments = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal('0'),
        verbose_name='إجمالي التسويات اليدوية',
    )
    # Final payout = total_incentive + total_adjustments
    final_payout      = models.DecimalField(
        max_digits=14, decimal_places=4, default=Decimal('0'),
        verbose_name='الصافي النهائي للصرف',
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
        return (f'{self.program} / {self.user.full_name} '
                f'{self.period_start}→{self.period_end}')


# ─────────────────────────────────────────────────────────────────────────────
# Adjustment Entry  (manual +/- corrections)
# ─────────────────────────────────────────────────────────────────────────────

class AdjustmentEntry(models.Model):
    """
    Manual adjustment to a user's incentive for a period.
    Can be positive (bonus) or negative (deduction).
    Created/edited only by admins; locked once settlement is finalized.
    """
    program      = models.ForeignKey(
        IncentiveProgram, on_delete=models.CASCADE,
        related_name='adjustments', verbose_name='البرنامج',
    )
    user = models.ForeignKey(
        'users.StaffProfile', on_delete=models.CASCADE,
        related_name='incentive_adjustments', verbose_name='المندوب',
    )
    period_start = models.DateField(verbose_name='بداية الفترة')
    period_end   = models.DateField(verbose_name='نهاية الفترة')

    # Positive = bonus, Negative = deduction
    amount       = models.DecimalField(
        max_digits=12, decimal_places=4,
        verbose_name='المبلغ (+ مكافأة / - خصم)',
    )
    reason       = models.TextField(verbose_name='سبب التسوية')

    created_by   = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_adjustments',
        verbose_name='أُنشئ بواسطة',
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'تسوية يدوية'
        verbose_name_plural = 'التسويات اليدوية'
        ordering            = ['-created_at']
        indexes = [
            models.Index(fields=['program', 'user', 'period_start'],
                         name='adj_prog_user_period_idx'),
        ]

    def __str__(self):
        sign = '+' if self.amount >= 0 else ''
        return f'{self.user.full_name} {sign}{self.amount} ({self.period_start}→{self.period_end})'


# ─────────────────────────────────────────────────────────────────────────────
# Incentive Calculation Log  (audit trail of every engine run)
# ─────────────────────────────────────────────────────────────────────────────

class IncentiveCalculationLog(models.Model):
    MODE_CHOICES   = [('calculate', 'احتساب فعلي'), ('simulate', 'محاكاة')]
    STATUS_CHOICES = [('done', 'مكتمل'), ('failed', 'فشل')]

    program      = models.ForeignKey(
        IncentiveProgram, on_delete=models.CASCADE,
        related_name='calculation_logs', verbose_name='البرنامج',
    )
    triggered_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='triggered_calculations',
        verbose_name='شُغِّل بواسطة',
    )
    period_start = models.DateField(verbose_name='بداية الفترة')
    period_end   = models.DateField(verbose_name='نهاية الفترة')
    mode         = models.CharField(
        max_length=12, choices=MODE_CHOICES, default='calculate',
        verbose_name='النوع',
    )
    status       = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='done',
        verbose_name='الحالة',
    )
    transactions_created  = models.IntegerField(default=0, verbose_name='حركات أُنشئت')
    skipped_person_codes  = models.JSONField(default=list, verbose_name='كودات غير مربوطة')
    # {str(user_id): {"name": "...", "person_code": "...", "total": 0.0}}
    user_summaries        = models.JSONField(default=dict, verbose_name='ملخص المستخدمين')
    error_detail          = models.TextField(blank=True, verbose_name='تفاصيل الخطأ')
    started_at            = models.DateTimeField(auto_now_add=True, verbose_name='وقت البدء')
    finished_at           = models.DateTimeField(null=True, blank=True, verbose_name='وقت الانتهاء')
    duration_seconds      = models.FloatField(null=True, blank=True, verbose_name='المدة (ثانية)')

    class Meta:
        verbose_name        = 'سجل احتساب'
        verbose_name_plural = 'سجلات الاحتساب'
        ordering            = ['-started_at']
        indexes = [
            models.Index(fields=['program', 'period_start'],
                         name='calclog_prog_period_idx'),
        ]

    def __str__(self):
        return (f'[{self.get_mode_display()}] {self.program.name} '
                f'{self.period_start}→{self.period_end} '
                f'({self.get_status_display()})')


# ════════════════════════════════════════════════════════════════════════════
# Sales Targets & Goals — set a number per scope/period, track live attainment.
# Actuals are computed from customers.PurchaseHistory (mirrored SOFTECH sales):
#   net_revenue = Σ(total_amount where doc_code='115') − Σ(doc_code='30')
# ════════════════════════════════════════════════════════════════════════════

class SalesTarget(models.Model):
    SCOPE_CHAIN = 'chain'; SCOPE_BRANCH = 'branch'
    SCOPE_SALESPERSON = 'salesperson'; SCOPE_CATEGORY = 'category'
    SCOPE_CHOICES = [
        (SCOPE_CHAIN, 'الشبكة كاملة'), (SCOPE_BRANCH, 'فرع'),
        (SCOPE_SALESPERSON, 'مندوب'), (SCOPE_CATEGORY, 'فئة'),
    ]
    METRIC_REVENUE = 'net_revenue'; METRIC_ORDERS = 'orders'
    # Branch-KPI metrics (doc 16) — actuals resolved via forecasting.KpiResolver.
    METRIC_CHOICES = [
        (METRIC_REVENUE, 'صافي المبيعات (ج.م)'),
        (METRIC_ORDERS,  'عدد الفواتير'),
        ('cash_delivery', 'نقدى + توصيل (ج.م)'),
        ('cash',          'نقدى (ج.م)'),
        ('delivery',      'توصيل (ج.م)'),
        ('credit',        'آجل (ج.م)'),
        ('gross_profit',  'معامل الربحية (ج.م)'),
        ('beauty',        'التجميل (ج.م)'),
        ('customer_count', 'عدد العملاء'),
    ]
    # Metrics whose actuals come from the KPI channel-bucket resolver (doc 16).
    KPI_RESOLVER_METRICS = {
        'cash_delivery', 'cash', 'delivery', 'regular', 'credit',
        'insurance', 'gross_profit', 'customer_count', 'beauty',
    }

    label        = models.CharField(max_length=120, blank=True, verbose_name='الاسم')
    scope_type   = models.CharField(max_length=12, choices=SCOPE_CHOICES, default=SCOPE_BRANCH)
    branch       = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, null=True, blank=True)
    softech_user = models.CharField(max_length=20, blank=True, db_index=True,
                                    verbose_name='كود المندوب (SOFTECH)')
    category     = models.ForeignKey('catalog.Category', on_delete=models.CASCADE, null=True, blank=True)
    metric       = models.CharField(max_length=20, choices=METRIC_CHOICES, default=METRIC_REVENUE)
    period_start = models.DateField(verbose_name='من')
    period_end   = models.DateField(verbose_name='إلى')
    target_value = models.DecimalField(max_digits=14, decimal_places=2, verbose_name='القيمة المستهدفة')
    created_by   = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-period_end', 'scope_type']
        verbose_name        = 'هدف بيعي'
        verbose_name_plural = 'الأهداف البيعية'

    def __str__(self):
        return f'{self.get_scope_type_display()} | {self.label or self.metric} | {self.period_start}→{self.period_end}'

    def _actuals_qs(self):
        from apps.customers.models import PurchaseHistory
        qs = PurchaseHistory.objects.filter(
            invoice_date__date__gte=self.period_start,
            invoice_date__date__lte=self.period_end,
        )
        if self.scope_type == self.SCOPE_BRANCH and self.branch_id:
            qs = qs.filter(branch_id=self.branch_id)
        elif self.scope_type == self.SCOPE_SALESPERSON and self.softech_user:
            qs = qs.filter(softech_user=self.softech_user)
        return qs

    def actual_value(self):
        from django.db.models import Sum
        from apps.customers.models import PurchaseHistoryLine

        # Branch-KPI metrics (doc 16) resolve via the channel-bucket engine.
        # Scopes: branch (branch_ids), salesperson (softech_user), category (category_id).
        if self.metric in self.KPI_RESOLVER_METRICS:
            from apps.forecasting.kpi import KpiResolver
            branch_ids = [self.branch_id] if (self.scope_type == self.SCOPE_BRANCH and self.branch_id) else None
            softech_user = self.softech_user if (self.scope_type == self.SCOPE_SALESPERSON and self.softech_user) else None
            category_id = self.category_id if (self.scope_type == self.SCOPE_CATEGORY and self.category_id) else None
            return float(KpiResolver().resolve(
                self.metric, branch_ids=branch_ids,
                start=self.period_start, end=self.period_end,
                softech_user=softech_user, category_id=category_id,
            ))

        ph = self._actuals_qs()
        if self.metric == self.METRIC_ORDERS:
            return ph.filter(doc_code='115').count()
        if self.scope_type == self.SCOPE_CATEGORY and self.category_id:
            lines = PurchaseHistoryLine.objects.filter(purchase__in=ph, item__category_id=self.category_id)
            sales = lines.filter(purchase__doc_code='115').aggregate(s=Sum('line_total'))['s'] or 0
            rets  = lines.filter(purchase__doc_code='30').aggregate(s=Sum('line_total'))['s'] or 0
            return float(sales) - float(rets)
        sales = ph.filter(doc_code='115').aggregate(s=Sum('total_amount'))['s'] or 0
        rets  = ph.filter(doc_code='30').aggregate(s=Sum('total_amount'))['s'] or 0
        return float(sales) - float(rets)

    def attainment(self):
        """Returns {actual, target, pct, expected_to_date, pace, days_total, days_left}."""
        from datetime import date
        actual = self.actual_value()
        target = float(self.target_value or 0)
        today  = date.today()
        days_total = max((self.period_end - self.period_start).days + 1, 1)
        elapsed    = min(max((today - self.period_start).days + 1, 0), days_total)
        frac       = elapsed / days_total
        expected   = target * frac
        pct        = (actual / target * 100) if target else 0
        if today > self.period_end:
            pace = 'met' if actual >= target else 'missed'
        elif actual >= expected:
            pace = 'ahead'
        else:
            pace = 'behind'
        return {
            'actual': round(actual, 2), 'target': round(target, 2),
            'pct': round(pct, 1), 'expected_to_date': round(expected, 2),
            'pace': pace, 'days_total': days_total, 'days_left': max(days_total - elapsed, 0),
        }
