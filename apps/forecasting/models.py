"""
Forecasting models
==================
SeasonalityIndex  — per-item (or category) per-month seasonal multiplier
ForecastRun       — audit log of each full forecast execution
ForecastAccuracy  — back-test accuracy tracking (forecast vs actual)
"""
from decimal import Decimal

from django.db import models


class SeasonalityIndex(models.Model):
    """
    Seasonal index (α) for a given month.
    Can be scoped to a specific item OR a catalog category (or global if both null).
    index_value = 1.0 means no seasonality; >1 means above-average demand.
    """
    item     = models.ForeignKey(
        'catalog.Item', null=True, blank=True,
        on_delete=models.CASCADE, related_name='seasonality_indices',
        verbose_name='الصنف',
    )
    category = models.ForeignKey(
        'catalog.Category', null=True, blank=True,
        on_delete=models.CASCADE, related_name='seasonality_indices',
        verbose_name='الفئة',
    )
    month        = models.PositiveSmallIntegerField(verbose_name='الشهر (1–12)')
    index_value  = models.DecimalField(max_digits=6, decimal_places=4, verbose_name='قيمة المؤشر')
    computed_from_years = models.PositiveSmallIntegerField(default=1, verbose_name='عدد السنوات المستخدمة')
    computed_at  = models.DateTimeField(auto_now=True, verbose_name='آخر تحديث')

    class Meta:
        unique_together = [('item', 'category', 'month')]
        ordering = ['item', 'category', 'month']
        verbose_name = 'مؤشر موسمي'
        verbose_name_plural = 'مؤشرات موسمية'

    def __str__(self):
        scope = self.item or self.category or 'عام'
        return f'{scope} — شهر {self.month}: {self.index_value}'


class ForecastRun(models.Model):
    """Audit record for each forecast engine execution."""
    STATUS_CHOICES = [
        ('running',   'جارٍ'),
        ('completed', 'مكتمل'),
        ('failed',    'فشل'),
    ]
    started_at      = models.DateTimeField(auto_now_add=True, verbose_name='وقت البدء')
    completed_at    = models.DateTimeField(null=True, blank=True, verbose_name='وقت الإكمال')
    status          = models.CharField(max_length=15, choices=STATUS_CHOICES, default='running', db_index=True)
    items_processed = models.PositiveIntegerField(default=0, verbose_name='أصناف معالَجة')
    triggered_by    = models.ForeignKey(
        'users.StaffProfile', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='forecast_runs',
        verbose_name='أطلقه',
    )
    parameters  = models.JSONField(default=dict, verbose_name='معاملات التشغيل')
    error       = models.TextField(blank=True, verbose_name='رسالة الخطأ')

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'تشغيل التنبؤ'
        verbose_name_plural = 'تشغيلات التنبؤ'

    def __str__(self):
        return f'ForecastRun #{self.pk} [{self.status}] @ {self.started_at:%Y-%m-%d %H:%M}'


class ForecastAccuracy(models.Model):
    """Back-test: compare the forecast made on forecast_date to what actually happened."""
    item          = models.ForeignKey('catalog.Item',    on_delete=models.CASCADE, related_name='forecast_accuracy')
    branch        = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='forecast_accuracy')
    forecast_date = models.DateField(db_index=True, verbose_name='تاريخ التنبؤ')
    forecast_30d  = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='تنبؤ 30 يوم')
    actual_30d    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='فعلي 30 يوم')
    mape          = models.DecimalField(max_digits=7, decimal_places=4, null=True, blank=True, verbose_name='MAPE')
    mae           = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='MAE')

    class Meta:
        unique_together = [('item', 'branch', 'forecast_date')]
        ordering = ['-forecast_date']
        verbose_name = 'دقة التنبؤ'
        verbose_name_plural = 'دقة التنبؤات'
        indexes = [
            models.Index(fields=['forecast_date', 'branch'], name='fcast_acc_date_branch_idx'),
        ]

    def __str__(self):
        return f'{self.item_id}@{self.branch_id} {self.forecast_date} MAPE={self.mape}'


# ════════════════════════════════════════════════════════════════════════════
# BRANCH-KPI FORECASTING LAYER  (doc 16)
# Config-driven monthly branch KPIs (cash / credit / delivery / beauty / profit /
# customers). Actuals derived from customers.PurchaseHistory(+Line). Separate from
# the item-demand forecaster above.
# ════════════════════════════════════════════════════════════════════════════


class ChannelBucketMap(models.Model):
    """
    Maps a SOFTECH sales channel — the pair (person_type=ptcode, channel=ptclassifcode)
    stamped on every invoice — to a KPI bucket. Owner-editable: every code is assigned
    explicitly (unmapped codes default to `exclude`).

    Validated 2026-07-29 against تحقيق مايو 2026 (person_type '10' = customers):
      cash     = {91 نقدى, 11 موظفيين, 12 بطاقة}   (+ delivery 90 + regular 30 → cash bucket)
      delivery = subtype of cash: {90 عميل Delivery}
      regular  = subtype of cash: {30 عميل دائم}
      credit   = {10 تعاقدات/آجل, 33 تعاقد سداد آجل}
      insurance= {15 تأمين صحي}
    """
    BUCKET_CASH = 'cash'; BUCKET_CREDIT = 'credit'
    BUCKET_INSURANCE = 'insurance'; BUCKET_EXCLUDE = 'exclude'
    BUCKET_CHOICES = [
        (BUCKET_CASH, 'نقدى'), (BUCKET_CREDIT, 'آجل'),
        (BUCKET_INSURANCE, 'تأمين'), (BUCKET_EXCLUDE, 'مستبعد'),
    ]
    SUB_NONE = ''; SUB_DELIVERY = 'delivery'; SUB_REGULAR = 'regular'
    SUBTYPE_CHOICES = [
        (SUB_NONE, '—'), (SUB_DELIVERY, 'توصيل'), (SUB_REGULAR, 'عميل دائم'),
    ]

    person_type = models.CharField(
        max_length=10, db_index=True, verbose_name='نوع الشخص (ptcode)',
        help_text='persontypes.ptcode — e.g. 10 = عملاء',
    )
    channel = models.CharField(
        max_length=10, db_index=True, verbose_name='كود القناة (ptclassifcode)',
        help_text='persontypesclassif.ptclassifcode — stamped on the invoice as sales_channel',
    )
    label   = models.CharField(max_length=150, blank=True, verbose_name='الوصف')
    bucket  = models.CharField(
        max_length=12, choices=BUCKET_CHOICES, default=BUCKET_EXCLUDE,
        db_index=True, verbose_name='التصنيف',
    )
    subtype = models.CharField(
        max_length=12, choices=SUBTYPE_CHOICES, default=SUB_NONE, blank=True,
        verbose_name='التصنيف الفرعي',
    )
    counts_customer   = models.BooleanField(
        default=False, verbose_name='يُحسب ضمن عدد العملاء',
        help_text='Include this channel in the distinct-customer count (عدد العملاء).',
    )
    include_in_profit = models.BooleanField(
        default=False, verbose_name='يُحسب ضمن الربحية',
        help_text='Include this channel in the gross-profit metric (معامل الربحية).',
    )
    active  = models.BooleanField(default=True, db_index=True, verbose_name='نشط')

    class Meta:
        unique_together = [('person_type', 'channel')]
        ordering = ['person_type', 'channel']
        verbose_name = 'ربط قناة البيع'
        verbose_name_plural = 'ربط قنوات البيع'

    def __str__(self):
        return f'{self.person_type}/{self.channel} → {self.bucket} — {self.label}'


class MetricGuardrail(models.Model):
    """
    Reward + guardrail pairing (doc 16 metric-catalog Phase 3). A KPI reward (a
    SalesTarget on `reward_metric`) is only incentive-eligible when the guardrail
    metric stays within bounds — e.g. reward net_revenue growth ONLY IF
    discount_pct ≤ 10 and return-rate ≤ 3. Prevents gaming (buying volume with
    discounts). Owner-editable; evaluated by apps/forecasting/guardrails.py.
    """
    OP_LTE = 'lte'; OP_GTE = 'gte'; OP_LT = 'lt'; OP_GT = 'gt'
    OP_CHOICES = [(OP_LTE, '≤'), (OP_GTE, '≥'), (OP_LT, '<'), (OP_GT, '>')]
    SCOPE_CHOICES = [
        ('branch', 'فرع'), ('salesperson', 'مندوب'),
        ('category', 'فئة'), ('chain', 'الشبكة'),
    ]

    label = models.CharField(max_length=120, blank=True, verbose_name='الاسم')
    scope_type = models.CharField(max_length=12, choices=SCOPE_CHOICES, default='branch',
                                  verbose_name='النطاق')
    # Reward this guardrail protects; blank = applies to every reward at this scope.
    reward_metric = models.CharField(max_length=20, blank=True, verbose_name='مؤشر المكافأة')
    guardrail_metric = models.CharField(max_length=20, verbose_name='مؤشر الحارس')
    operator  = models.CharField(max_length=3, choices=OP_CHOICES, default=OP_LTE, verbose_name='المُقارن')
    threshold = models.DecimalField(max_digits=14, decimal_places=2, verbose_name='الحد')
    active    = models.BooleanField(default=True, db_index=True, verbose_name='نشط')
    note      = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['scope_type', 'reward_metric', 'guardrail_metric']
        verbose_name = 'حارس مؤشر'
        verbose_name_plural = 'حراس المؤشرات'

    def __str__(self):
        r = self.reward_metric or 'any'
        return f'[{self.scope_type}] {r} ⇐ {self.guardrail_metric} {self.operator} {self.threshold}'

    def passes(self, value) -> bool:
        from decimal import Decimal as _D
        v, t = _D(str(value)), self.threshold
        return {'lte': v <= t, 'gte': v >= t, 'lt': v < t, 'gt': v > t}[self.operator]


class UnitCountExclusion(models.Model):
    """
    Items excluded from UNIT-count metrics (doc 16 metric-catalog) — e.g. syringes,
    delivery fees, alcohol swabs: high-qty add-ons that inflate 'units sold' without
    reflecting real product volume. Owner-managed list; does NOT affect revenue/profit.
    """
    item = models.OneToOneField('catalog.Item', on_delete=models.CASCADE,
                                related_name='unit_count_exclusion', verbose_name='الصنف')
    note = models.CharField(max_length=200, blank=True, verbose_name='السبب')
    active = models.BooleanField(default=True, db_index=True, verbose_name='نشط')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['item']
        verbose_name = 'استثناء من عدّ الوحدات'
        verbose_name_plural = 'استثناءات عدّ الوحدات'

    def __str__(self):
        return f'exclude {self.item_id} — {self.note}'


class BeautyClassRule(models.Model):
    """
    Which catalog `medicine_type` (itemmedicine) codes count as beauty/التجميل.
    Validated set: {50 Cosmetics, 20 Others}. Excludes 10 Medicine, 70 Services,
    40 Veterinary, 60 gifts. Owner-editable.
    """
    medicine_type = models.CharField(
        max_length=2, unique=True, verbose_name='كود itemmedicine',
        help_text='catalog.Item.medicine_type — e.g. 50 = Cosmetics, 20 = Others',
    )
    label  = models.CharField(max_length=100, blank=True, verbose_name='الوصف')
    active = models.BooleanField(default=True, db_index=True, verbose_name='نشط')

    class Meta:
        ordering = ['medicine_type']
        verbose_name = 'قاعدة تصنيف التجميل'
        verbose_name_plural = 'قواعد تصنيف التجميل'

    def __str__(self):
        return f'{self.medicine_type} — {self.label} ({"on" if self.active else "off"})'


class KpiActualRollup(models.Model):
    """
    Materialised monthly branch KPI actuals (branch × year × month × metric → value).
    Long format so new metrics (call-center, etc.) need no migration. Net of returns.
    Rebuilt by `build_kpi_rollups`; the fast source for pace + backtest over the
    ~3–4M-rows/month PurchaseHistory.
    """
    # Metric keys — kept as constants so the resolver, rollup and targets agree.
    M_CASH_DELIVERY = 'cash_delivery'   # cash bucket total (the «cash+delivery» target)
    M_CASH          = 'cash'            # plain cash (subtype none)
    M_DELIVERY      = 'delivery'        # subtype delivery
    M_REGULAR       = 'regular'         # subtype عميل دائم
    M_CREDIT        = 'credit'
    M_INSURANCE     = 'insurance'
    M_NET_REVENUE   = 'net_revenue'     # all non-exclude buckets
    M_GROSS_PROFIT  = 'gross_profit'    # معامل الربحية (include_in_profit channels)
    M_CUSTOMERS     = 'customer_count'  # distinct phcode on counts_customer channels
    M_ORDERS        = 'order_count'
    M_BEAUTY        = 'beauty'          # التجميل (beauty medicine_type items)
    M_CALL_COUNT    = 'call_count'      # عدد المكالمات (CC only — from Issabel CDR)
    # Extended volume/mix metrics (doc 16 — extension set). Header scopes
    # (branch/salesperson/chain); category variants TBD.
    M_PIC_COUNT       = 'pic_count'            # distinct PICs handled (all channels)
    M_BULK_TXN        = 'bulk_txn_count'       # transactions ≥ bulk threshold
    M_MULTI_ITEM_TXN  = 'multi_item_txn_count' # transactions with >1 line
    M_BASKET_VALUE    = 'basket_value'         # avg net value per transaction
    M_BASKET_UNITS    = 'basket_units'         # avg units per transaction
    # Discounting family (needs stktrans discount fields — sync + re-backfill)
    M_GROSS_SALES     = 'gross_sales'          # pre-discount (Σ list_price·qty)
    M_DISCOUNT_VALUE  = 'discount_value'       # EGP discounted (gross − net)
    M_DISCOUNT_PCT    = 'discount_pct'         # discount ÷ gross
    M_DISCOUNT_FREQ   = 'discount_freq'        # % of lines discounted
    M_DISC_TO_MARGIN  = 'discount_to_margin'   # discount ÷ gross profit
    # Derivable metrics (mirror-only, doc 16 metric-catalog Phase 2)
    M_UNITS_SOLD        = 'units_sold'          # Σ qty (minus UnitCountExclusion items)
    M_GROSS_MARGIN_PCT  = 'gross_margin_pct'    # profit ÷ net revenue
    M_REVENUE_PER_CUST  = 'revenue_per_customer' # net revenue ÷ distinct PIC
    M_CROSS_CATEGORY_RATE = 'cross_category_rate' # % invoices spanning ≥2 categories
    M_NEW_CUSTOMERS     = 'new_customers'       # PICs whose first-ever purchase is in period
    METRIC_LABELS = {
        M_CASH_DELIVERY: 'نقدى + توصيل', M_CASH: 'نقدى', M_DELIVERY: 'توصيل',
        M_REGULAR: 'عميل دائم', M_CREDIT: 'آجل', M_INSURANCE: 'تأمين',
        M_NET_REVENUE: 'إجمالى المبيعات', M_GROSS_PROFIT: 'معامل الربحية',
        M_CUSTOMERS: 'عدد العملاء', M_ORDERS: 'عدد الفواتير', M_BEAUTY: 'التجميل',
        M_CALL_COUNT: 'عدد المكالمات',
        M_PIC_COUNT: 'عدد الأكواد (PIC)', M_BULK_TXN: 'فواتير الجملة',
        M_MULTI_ITEM_TXN: 'فواتير متعددة الأصناف', M_BASKET_VALUE: 'متوسط قيمة الفاتورة',
        M_BASKET_UNITS: 'متوسط أصناف الفاتورة',
        M_GROSS_SALES: 'المبيعات قبل الخصم', M_DISCOUNT_VALUE: 'قيمة الخصم',
        M_DISCOUNT_PCT: 'نسبة الخصم %', M_DISCOUNT_FREQ: 'تكرار الخصم %',
        M_DISC_TO_MARGIN: 'الخصم ÷ الربح %',
        M_UNITS_SOLD: 'الوحدات المباعة', M_GROSS_MARGIN_PCT: 'هامش الربح %',
        M_REVENUE_PER_CUST: 'الإيراد لكل عميل', M_CROSS_CATEGORY_RATE: 'نسبة تعدد الفئات %',
        M_NEW_CUSTOMERS: 'عملاء جدد',
    }
    # Metrics that are averages/ratios (not additive) — don't sum across members.
    RATIO_METRICS = {M_BASKET_VALUE, M_BASKET_UNITS,
                     M_DISCOUNT_PCT, M_DISCOUNT_FREQ, M_DISC_TO_MARGIN,
                     M_GROSS_MARGIN_PCT, M_REVENUE_PER_CUST, M_CROSS_CATEGORY_RATE}
    # Extended metrics currently supported on header scopes only (not category).
    EXTENDED_HEADER_METRICS = {M_PIC_COUNT, M_BULK_TXN, M_MULTI_ITEM_TXN,
                               M_BASKET_VALUE, M_BASKET_UNITS}
    # Discounting metrics — line-based, all scopes (incl. category).
    DISCOUNT_METRICS = {M_GROSS_SALES, M_DISCOUNT_VALUE, M_DISCOUNT_PCT,
                        M_DISCOUNT_FREQ, M_DISC_TO_MARGIN}

    branch      = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                    related_name='kpi_rollups', verbose_name='الفرع')
    year        = models.PositiveSmallIntegerField(db_index=True, verbose_name='السنة')
    month       = models.PositiveSmallIntegerField(verbose_name='الشهر (1–12)')
    metric      = models.CharField(max_length=20, db_index=True, verbose_name='المؤشر')
    value       = models.DecimalField(max_digits=16, decimal_places=2, default=0,
                                      verbose_name='القيمة')
    computed_at = models.DateTimeField(auto_now=True, verbose_name='آخر حساب')

    class Meta:
        unique_together = [('branch', 'year', 'month', 'metric')]
        ordering = ['-year', '-month', 'branch', 'metric']
        verbose_name = 'مؤشر شهري فعلى'
        verbose_name_plural = 'المؤشرات الشهرية الفعلية'
        indexes = [
            models.Index(fields=['year', 'month', 'metric'], name='kpi_rollup_ym_metric_idx'),
        ]

    def __str__(self):
        return f'{self.branch_id} {self.year}-{self.month:02d} {self.metric}={self.value}'


# ════════════════════════════════════════════════════════════════════════════
# CALL CENTER  (doc 16, Phase 5)
# CC is a cross-branch overlay (not a branch): sales/profit/beauty/orders come from
# invoices placed by CC sales agents (SOFTECH usercodes); call-count comes from the
# Issabel CDR (outgoing answered calls from CC phone extensions). Owner-editable.
# ════════════════════════════════════════════════════════════════════════════

class CallCenterConfig(models.Model):
    """Singleton (pk=1). Decoded from the owner's Call-Center-KPIs workbook (2026-07-29)."""
    # SOFTECH usercodes stamped on CC invoices (sales/profit/beauty attribution).
    sales_agent_usercodes = models.JSONField(
        default=list, verbose_name='أكواد مندوبي الكول سنتر (SOFTECH)',
        help_text="e.g. ['62','63','64']")
    # Issabel/Asterisk phone extensions the CC agents dial FROM (outgoing calls).
    call_agent_extensions = models.JSONField(
        default=list, verbose_name='امتدادات هاتف الكول سنتر (CDR)',
        help_text="e.g. ['10','12','15']")
    # Call-count rule (validated): ANSWERED, src in extensions, dst→11-digit mobile,
    # per-day distinct summed. GoIP prefixes are stripped by taking the last 11 digits.
    cdr_enabled = models.BooleanField(default=False, verbose_name='ربط CDR مباشر مُفعّل')
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إعداد الكول سنتر'
        verbose_name_plural = 'إعداد الكول سنتر'

    def __str__(self):
        return f'CallCenterConfig agents={self.sales_agent_usercodes} ext={self.call_agent_extensions}'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1, defaults={'sales_agent_usercodes': ['62', '63', '64'],
                            'call_agent_extensions': ['10', '12', '15']})
        return obj


# ════════════════════════════════════════════════════════════════════════════
# FORECAST ENGINE  (doc 16, Phase 3)
# Factor-driven monthly target generation. Two models + average:
#   Model A (goal):  target = base×(1+growth_goal) ÷ incentive_threshold
#   Model B (blend): target = [w_lm·LM + w_pm·PM + w_yoy·(base×(1+benchmark))]
#                             × seasonality × (1+inflation+promotion) ÷ threshold
# where base = same-month-last-year actual, LM/PM = the 1–2 months before target.
# generate → review ForecastResult → commit → incentives.SalesTarget rows.
# ════════════════════════════════════════════════════════════════════════════

class ForecastScenario(models.Model):
    MODEL_A = 'a'; MODEL_B = 'b'; MODEL_AVG = 'avg'
    MODEL_CHOICES = [
        (MODEL_A, 'Model A — نمو الهدف'),
        (MODEL_B, 'Model B — مزيج مرجّح'),
        (MODEL_AVG, 'المتوسط (A+B)/2'),
    ]
    STATUS_DRAFT = 'draft'; STATUS_GENERATED = 'generated'; STATUS_COMMITTED = 'committed'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'مسودة'), (STATUS_GENERATED, 'محسوب'), (STATUS_COMMITTED, 'معتمد'),
    ]

    SCOPE_BRANCH = 'branch'; SCOPE_SALESPERSON = 'salesperson'; SCOPE_CATEGORY = 'category'
    SCOPE_CHOICES = [
        (SCOPE_BRANCH, 'فرع'), (SCOPE_SALESPERSON, 'مندوب'), (SCOPE_CATEGORY, 'فئة'),
    ]

    name  = models.CharField(max_length=120, verbose_name='اسم السيناريو')
    year  = models.PositiveSmallIntegerField(verbose_name='سنة الهدف')
    month = models.PositiveSmallIntegerField(verbose_name='شهر الهدف (1–12)')
    scope_type = models.CharField(max_length=12, choices=SCOPE_CHOICES, default=SCOPE_BRANCH,
                                  verbose_name='مستوى التنبؤ')
    model = models.CharField(max_length=4, choices=MODEL_CHOICES, default=MODEL_A,
                             verbose_name='النموذج')
    # Global factors (owner-editable)
    incentive_threshold = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.9000'),
                                              verbose_name='حد الحافز (÷)')
    benchmark_growth = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0.3000'),
                                          verbose_name='نمو مرجعي (YoY)')
    inflation = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0'),
                                    verbose_name='التضخم')
    promotion_lift = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0'),
                                         verbose_name='رفع العروض')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT,
                              db_index=True, verbose_name='الحالة')
    notes  = models.TextField(blank=True, verbose_name='ملاحظات')
    created_by   = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='forecast_scenarios')
    created_at   = models.DateTimeField(auto_now_add=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-year', '-month', '-created_at']
        verbose_name = 'سيناريو تنبؤ'
        verbose_name_plural = 'سيناريوهات التنبؤ'

    def __str__(self):
        return f'{self.name} [{self.year}-{self.month:02d}] {self.get_model_display()}'


class ForecastFactor(models.Model):
    """Per-metric knobs for a scenario: Model-A growth goal + Model-B blend weights."""
    scenario = models.ForeignKey(ForecastScenario, on_delete=models.CASCADE, related_name='factors')
    metric   = models.CharField(max_length=20, verbose_name='المؤشر')
    growth_goal = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0.2000'),
                                      verbose_name='هدف النمو (Model A)')
    w_lm  = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.5000'),
                                verbose_name='وزن الشهر السابق')
    w_pm  = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.3000'),
                                verbose_name='وزن الشهر قبل السابق')
    w_yoy = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.2000'),
                                verbose_name='وزن العام السابق')
    seasonality_index = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('1.0000'),
                                            verbose_name='مؤشر موسمي')

    class Meta:
        unique_together = [('scenario', 'metric')]
        ordering = ['scenario', 'metric']
        verbose_name = 'عامل تنبؤ'
        verbose_name_plural = 'عوامل التنبؤ'

    def __str__(self):
        return f'{self.scenario_id}/{self.metric} g={self.growth_goal}'


class ForecastResult(models.Model):
    """Generated forecast per scenario × branch × metric (branch NULL = chain aggregate)."""
    scenario = models.ForeignKey(ForecastScenario, on_delete=models.CASCADE, related_name='results')
    branch   = models.ForeignKey('branches.Branch', null=True, blank=True,
                                 on_delete=models.CASCADE, related_name='forecast_results')
    # Generic scope member (branch code / salesperson usercode / category id / 'chain').
    scope_key   = models.CharField(max_length=40, blank=True, db_index=True, verbose_name='مفتاح النطاق')
    scope_label = models.CharField(max_length=150, blank=True, verbose_name='اسم النطاق')
    metric   = models.CharField(max_length=20, verbose_name='المؤشر')
    base_value   = models.DecimalField(max_digits=16, decimal_places=2, default=0,
                                       verbose_name='الأساس (نفس الشهر العام السابق)')
    lm_value     = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    pm_value     = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    model_a      = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    model_b      = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    forecast_value = models.DecimalField(max_digits=16, decimal_places=2, default=0,
                                         verbose_name='التنبؤ')
    target_value = models.DecimalField(max_digits=16, decimal_places=2, default=0,
                                       verbose_name='الهدف (تنبؤ ÷ حد الحافز)')
    branch_share = models.DecimalField(max_digits=6, decimal_places=4, default=0,
                                       verbose_name='حصة الفرع')
    computed_at  = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('scenario', 'scope_key', 'metric')]
        ordering = ['scenario', 'metric', 'scope_key']
        verbose_name = 'نتيجة تنبؤ'
        verbose_name_plural = 'نتائج التنبؤ'

    def __str__(self):
        return f'{self.scenario_id} {self.branch_id or "chain"} {self.metric} → {self.target_value}'


# ════════════════════════════════════════════════════════════════════════════
# BACKTEST  (doc 16, Phase 4)
# Replays Model A vs Model B across historical months (base=M-12, LM=M-1, PM=M-2,
# actual=M) and scores accuracy per metric → picks the winning model. Chain-level
# (all operational branches summed) — models are linear so chain == Σ branches.
# ════════════════════════════════════════════════════════════════════════════

class BacktestRun(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='backtest_runs')
    window_start_year  = models.PositiveSmallIntegerField()
    window_start_month = models.PositiveSmallIntegerField()
    window_end_year    = models.PositiveSmallIntegerField()
    window_end_month   = models.PositiveSmallIntegerField()
    n_months = models.PositiveSmallIntegerField(default=0, verbose_name='عدد الشهور المختبرة')
    # Global knobs used (factors are per-metric — snapshotted on each result)
    benchmark_growth    = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0.3000'))
    incentive_threshold = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.9000'))
    inflation           = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0'))
    promotion_lift      = models.DecimalField(max_digits=6, decimal_places=4, default=Decimal('0'))
    scenario = models.ForeignKey(ForecastScenario, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name='backtests',
                                 verbose_name='مصدر العوامل')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'تشغيل اختبار رجعي'
        verbose_name_plural = 'تشغيلات الاختبار الرجعي'

    def __str__(self):
        return (f'Backtest #{self.pk} '
                f'{self.window_start_year}-{self.window_start_month:02d}→'
                f'{self.window_end_year}-{self.window_end_month:02d} ({self.n_months}m)')


class BacktestResult(models.Model):
    MODEL_A = 'a'; MODEL_B = 'b'
    MODEL_CHOICES = [(MODEL_A, 'Model A'), (MODEL_B, 'Model B')]

    run    = models.ForeignKey(BacktestRun, on_delete=models.CASCADE, related_name='results')
    metric = models.CharField(max_length=20, verbose_name='المؤشر')
    model  = models.CharField(max_length=4, choices=MODEL_CHOICES, verbose_name='النموذج')
    n_points = models.PositiveSmallIntegerField(default=0)
    mape = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name='MAPE %')
    wape = models.DecimalField(max_digits=8, decimal_places=2, default=0, verbose_name='WAPE %')
    bias = models.DecimalField(max_digits=8, decimal_places=2, default=0,
                               verbose_name='الانحياز %')  # +ve = over-forecast
    rmse = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    is_winner = models.BooleanField(default=False, verbose_name='الأفضل')
    # {growth_goal, w_lm, w_pm, w_yoy, seasonality_index} used for this metric
    factor_snapshot = models.JSONField(default=dict)

    class Meta:
        unique_together = [('run', 'metric', 'model')]
        ordering = ['run', 'metric', 'model']
        verbose_name = 'نتيجة اختبار رجعي'
        verbose_name_plural = 'نتائج الاختبار الرجعي'

    def __str__(self):
        return f'{self.run_id} {self.metric}/{self.model} WAPE={self.wape}%'
