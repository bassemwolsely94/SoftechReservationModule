"""Period close and SOFTECH comparison models (finance-gl Plan 3)."""
from decimal import Decimal

from django.db import models


class ClosingStockSnapshot(models.Model):
    """One per close attempt; the latest with `entry` set is the period's closing stock."""
    period         = models.ForeignKey('finance.FinancialPeriod', on_delete=models.PROTECT,
                                       related_name='stock_snapshots', verbose_name='الفترة')
    as_of          = models.DateField(verbose_name='بتاريخ')
    read_at        = models.DateTimeField(auto_now_add=True, verbose_name='وقت القراءة')
    read_by        = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='+',
                                       verbose_name='قرأه')
    total          = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                         verbose_name='الإجمالي')
    excluded_total = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                         verbose_name='المستبعد')
    missing_stores = models.JSONField(default=list, blank=True, verbose_name='مخازن ناقصة')
    entry          = models.ForeignKey('finance.LedgerEntry', null=True, blank=True,
                                       on_delete=models.PROTECT, related_name='+',
                                       verbose_name='القيد')
    reversal       = models.ForeignKey('finance.LedgerEntry', null=True, blank=True,
                                       on_delete=models.PROTECT, related_name='+',
                                       verbose_name='قيد العكس')

    class Meta:
        app_label = 'finance'
        ordering = ['-read_at', '-id']
        verbose_name = 'لقطة مخزون آخر المدة'
        verbose_name_plural = 'لقطات مخزون آخر المدة'


class ClosingStockStore(models.Model):
    snapshot      = models.ForeignKey(ClosingStockSnapshot, on_delete=models.CASCADE,
                                      related_name='stores', verbose_name='اللقطة')
    store_code    = models.CharField(max_length=10, verbose_name='كود المخزن')
    store_name    = models.CharField(max_length=200, blank=True, verbose_name='اسم المخزن')
    branch        = models.ForeignKey('branches.Branch', null=True, blank=True,
                                      on_delete=models.PROTECT, related_name='+',
                                      verbose_name='الفرع')
    included      = models.BooleanField(default=True, verbose_name='مشمول')
    rows          = models.IntegerField(default=0, verbose_name='عدد الصفوف')
    value         = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                        verbose_name='القيمة')
    snapshot_date = models.DateField(verbose_name='تاريخ اللقطة')
    # True when snapshot_date < the snapshot's as_of (carried forward)
    carried       = models.BooleanField(default=False, verbose_name='مرحّل من قبل')

    class Meta:
        app_label = 'finance'
        ordering = ['store_code']
        verbose_name = 'مخزون مخزن'
        verbose_name_plural = 'مخزون المخازن'


class GLSoftechCheck(models.Model):
    KIND_CHOICES = [('movement', 'حركة'), ('balance', 'رصيد')]
    SOURCE_CHOICES = [
        ('sales', 'المبيعات'), ('purchases', 'المشتريات'), ('stock_at_cost', 'المخزون بالتكلفة'),
        ('expenses', 'المصروفات'), ('supplier_balance', 'أرصدة الموردين'),
    ]
    SIGN_CHOICES = [('debit', 'مدين'), ('credit', 'دائن')]
    key           = models.CharField(max_length=40, unique=True, verbose_name='المفتاح')
    label         = models.CharField(max_length=200, verbose_name='الاسم')
    kind          = models.CharField(max_length=10, choices=KIND_CHOICES, verbose_name='النوع')
    account_codes = models.JSONField(default=list, blank=True, verbose_name='الحسابات')
    group_names   = models.JSONField(default=list, blank=True, verbose_name='المجموعات')
    source        = models.CharField(max_length=20, choices=SOURCE_CHOICES, verbose_name='المصدر')
    sign          = models.CharField(max_length=6, choices=SIGN_CHOICES, verbose_name='الإشارة')
    per_party     = models.BooleanField(default=False, verbose_name='لكل طرف')
    blocks_close  = models.BooleanField(default=True, verbose_name='يمنع الإقفال')
    tolerance     = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('1.00'),
                                        verbose_name='التسامح')
    is_active     = models.BooleanField(default=True, verbose_name='نشط')
    order         = models.IntegerField(default=0, verbose_name='الترتيب')

    class Meta:
        app_label = 'finance'
        ordering = ['order', 'key']
        verbose_name = 'فحص مقارنة SOFTECH'
        verbose_name_plural = 'فحوصات مقارنة SOFTECH'

    def __str__(self):
        return self.label


class GLComparisonLine(models.Model):
    period       = models.ForeignKey('finance.FinancialPeriod', on_delete=models.CASCADE,
                                     related_name='comparison_lines', verbose_name='الفترة')
    softech_check = models.ForeignKey(GLSoftechCheck, on_delete=models.PROTECT,
                                     related_name='lines', verbose_name='الفحص')
    branch       = models.ForeignKey('branches.Branch', null=True, blank=True,
                                     on_delete=models.PROTECT, related_name='+',
                                     verbose_name='الفرع')
    party_code   = models.CharField(max_length=20, blank=True, verbose_name='كود الطرف')
    ledger_amount  = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                         verbose_name='مبلغ الدفتر')
    softech_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                         verbose_name='مبلغ SOFTECH')
    difference   = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal('0'),
                                       verbose_name='الفرق')
    computed_at  = models.DateTimeField(auto_now=True, verbose_name='وقت الحساب')
    explanation  = models.TextField(blank=True, verbose_name='التفسير')
    explained_by = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+',
                                     verbose_name='فسّره')
    explained_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت التفسير')
    # the difference the explanation was written against; a later change re-opens it
    explained_difference = models.DecimalField(max_digits=18, decimal_places=2, null=True,
                                               blank=True, verbose_name='الفرق وقت التفسير')

    class Meta:
        app_label = 'finance'
        ordering = ['softech_check__order', 'branch_id', 'party_code']
        verbose_name = 'سطر مقارنة'
        verbose_name_plural = 'أسطر المقارنة'
        constraints = [
            models.UniqueConstraint(fields=['period', 'softech_check', 'branch', 'party_code'],
                                    name='gl_cmp_line_unique',
                                    nulls_distinct=False),
        ]

    @property
    def needs_explanation(self):
        if abs(self.difference) <= self.softech_check.tolerance:
            return False
        return self.explanation == '' or self.explained_difference != self.difference
