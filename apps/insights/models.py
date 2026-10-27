"""
Narrative Insights  (doc 18 — narrative analytics / automated audit reporting)
=============================================================================
Rule-based, bilingual (AR/EN) narrative reporting. A scheduled engine scans the
mirror for a period (day/week/month), checks each owner-tuned rule, emits
auditable findings, and renders a deterministic narrative delivered to WhatsApp
recipients + an in-app report page. Analytics-side; reuses forecasting.KpiResolver
so every number agrees with the KPI board/targets. No SOFTECH writes.
"""
from decimal import Decimal

from django.db import models


class InsightRule(models.Model):
    """Owner-editable rule config. `code` maps to a evaluator in rules.RULES."""
    CAT_COVERAGE = 'coverage'; CAT_VOLUME = 'volume'; CAT_MIX = 'mix'
    CAT_DISCOUNT = 'discount'; CAT_COMPARISON = 'comparison'; CAT_HIGHLIGHT = 'highlight'
    CATEGORY_CHOICES = [
        (CAT_COVERAGE, 'تغطية/سلامة البيانات'), (CAT_VOLUME, 'حجم المبيعات'),
        (CAT_MIX, 'مزيج المنتجات'), (CAT_DISCOUNT, 'الخصومات'),
        (CAT_COMPARISON, 'مقارنات'), (CAT_HIGHLIGHT, 'إنجازات'),
    ]
    SEV_INFO = 'info'; SEV_WARNING = 'warning'; SEV_CRITICAL = 'critical'
    SEVERITY_CHOICES = [(SEV_INFO, 'معلومة'), (SEV_WARNING, 'تنبيه'), (SEV_CRITICAL, 'حرج')]

    code      = models.CharField(max_length=50, unique=True, verbose_name='كود القاعدة')
    name_ar   = models.CharField(max_length=150, verbose_name='الاسم (عربي)')
    name_en   = models.CharField(max_length=150, verbose_name='الاسم (إنجليزي)')
    category  = models.CharField(max_length=12, choices=CATEGORY_CHOICES, default=CAT_VOLUME)
    severity  = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default=SEV_WARNING)
    # threshold meaning is rule-specific (%, EGP, or ratio) — documented per rule.
    threshold = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True,
                                    verbose_name='الحد')
    enabled   = models.BooleanField(default=True, db_index=True, verbose_name='مُفعّلة')
    # which period types this rule runs for: comma list of day,week,month
    periods   = models.CharField(max_length=30, default='day,week,month',
                                 verbose_name='الفترات')

    class Meta:
        ordering = ['category', 'code']
        verbose_name = 'قاعدة تحليل سردي'
        verbose_name_plural = 'قواعد التحليل السردي'

    def __str__(self):
        return f'{self.code} [{self.severity}] thr={self.threshold}'

    def runs_for(self, period_type):
        return self.enabled and period_type in (self.periods or '').split(',')


class InsightRun(models.Model):
    """One narrative report for a period — stores the assembled bilingual text (audit)."""
    PERIOD_DAY = 'day'; PERIOD_WEEK = 'week'; PERIOD_MONTH = 'month'
    PERIOD_CHOICES = [(PERIOD_DAY, 'يوم'), (PERIOD_WEEK, 'أسبوع'), (PERIOD_MONTH, 'شهر')]
    DOMAIN_CHOICES = [('sales', 'المبيعات'), ('purchasing', 'المشتريات والتموين')]

    domain       = models.CharField(max_length=12, choices=DOMAIN_CHOICES, default='sales', db_index=True,
                                    verbose_name='نوع التقرير')
    period_type  = models.CharField(max_length=6, choices=PERIOD_CHOICES, db_index=True)
    period_start = models.DateField(db_index=True)
    period_end   = models.DateField()
    findings_count = models.PositiveIntegerField(default=0)
    narrative_ar = models.TextField(blank=True)
    narrative_en = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at      = models.DateTimeField(null=True, blank=True)
    sent_to      = models.PositiveIntegerField(default=0, verbose_name='عدد المستلمين')

    class Meta:
        ordering = ['-period_start', '-created_at']
        verbose_name = 'تقرير سردي'
        verbose_name_plural = 'التقارير السردية'

    def __str__(self):
        return f'{self.get_period_type_display()} {self.period_start} ({self.findings_count} findings)'


class InsightFinding(models.Model):
    """A single auditable detected fact within a run."""
    run        = models.ForeignKey(InsightRun, on_delete=models.CASCADE, related_name='findings')
    rule_code  = models.CharField(max_length=50, db_index=True)
    category   = models.CharField(max_length=12)
    severity   = models.CharField(max_length=10, db_index=True)
    scope_type = models.CharField(max_length=15, blank=True)   # branch/salesperson/chain/product
    scope_key  = models.CharField(max_length=40, blank=True)
    scope_label= models.CharField(max_length=150, blank=True)
    value      = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    baseline   = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    threshold  = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    message_ar = models.TextField()
    message_en = models.TextField()

    class Meta:
        ordering = ['run', 'severity', 'category']
        verbose_name = 'ملاحظة سردية'
        verbose_name_plural = 'الملاحظات السردية'

    def __str__(self):
        return f'{self.rule_code}:{self.scope_label} = {self.value}'


class InsightRecipient(models.Model):
    """WhatsApp recipients for narrative reports (per-branch or all-branches)."""
    name      = models.CharField(max_length=120, verbose_name='الاسم')
    wa_number = models.CharField(max_length=20, verbose_name='رقم واتساب',
                                 help_text='E.164 without + (e.g. 2010…)')
    # Report scope precedence: salesperson_usercode > branch > chain.
    #  • salesperson_usercode set → gets ONLY that rep's report (render_for_salesperson)
    #  • branch set → gets ONLY that branch's report (render_for_branch)
    #  • both blank → gets the whole-chain board report
    branch    = models.ForeignKey('branches.Branch', null=True, blank=True,
                                  on_delete=models.CASCADE, related_name='insight_recipients')
    salesperson_usercode = models.CharField(max_length=20, blank=True, db_index=True,
                                            verbose_name='كود مسئول البيع',
                                            help_text='لإرسال تقرير مسئول بيع بعينه (يتقدّم على الفرع)')
    period_types = models.CharField(max_length=30, default='day,week,month',
                                    verbose_name='الفترات المُرسلة')
    active    = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ['branch', 'name']
        verbose_name = 'مستلم تقرير'
        verbose_name_plural = 'مستلمو التقارير'

    def __str__(self):
        return f'{self.name} ({self.wa_number})'
