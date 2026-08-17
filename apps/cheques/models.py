"""
apps/cheques/models.py

Post-dated cheque planning with Egyptian holiday-aware banking day calculation.

  EgyptianHoliday  — lookup table for non-banking days (official + Islamic)
  ChequePlan       — a multi-cheque payment plan (linked to supplier or free-text payee)
  ChequeInstalment — one physical cheque within a plan
"""
from decimal import Decimal
from django.db import models
from django.utils import timezone


class EgyptianHoliday(models.Model):
    """
    A single non-banking day in Egypt.
    Banking week: Sunday–Thursday. Fridays & Saturdays are always skipped
    in the engine without needing a DB record. This table covers:
      - Official national holidays (fixed date, e.g. Jan 25)
      - Islamic holidays (variable — must be seeded per year)
      - Ad-hoc closures (Central Bank circulars)
    """
    HOLIDAY_TYPE_CHOICES = [
        ('national',  'عيد وطني'),
        ('islamic',   'عيد إسلامي'),
        ('adhoc',     'إغلاق استثنائي'),
    ]

    date          = models.DateField(unique=True, db_index=True, verbose_name='التاريخ')
    name_ar       = models.CharField(max_length=200, verbose_name='الاسم')
    name_en       = models.CharField(max_length=200, blank=True, verbose_name='Name')
    holiday_type  = models.CharField(
        max_length=10, choices=HOLIDAY_TYPE_CHOICES,
        default='national', verbose_name='النوع',
    )
    # For recurring national holidays we store the month+day so they can be
    # regenerated for future years automatically.
    is_annual     = models.BooleanField(
        default=False,
        verbose_name='سنوي',
        help_text='إذا كان True، يتكرر كل عام في نفس الشهر واليوم',
    )

    class Meta:
        ordering = ['date']
        verbose_name = 'إجازة مصرية'
        verbose_name_plural = 'الإجازات المصرية'

    def __str__(self):
        return f'{self.date} — {self.name_ar}'


class ChequePlan(models.Model):
    """
    A schedule of post-dated cheques issued to a payee.
    Typical use: pay a supplier in 6 monthly instalments.
    """
    STATUS_CHOICES = [
        ('draft',     'مسودة'),
        ('active',    'نشطة'),
        ('completed', 'مكتملة'),
        ('cancelled', 'ملغاة'),
    ]

    INTERVAL_CHOICES = [
        ('days',   'أيام'),
        ('weeks',  'أسابيع'),
        ('months', 'أشهر'),
    ]

    # ── Identity ──────────────────────────────────────────────────────────────
    title         = models.CharField(max_length=255, verbose_name='عنوان الخطة')
    notes         = models.TextField(blank=True, verbose_name='ملاحظات')
    status        = models.CharField(
        max_length=10, choices=STATUS_CHOICES,
        default='draft', db_index=True, verbose_name='الحالة',
    )

    # ── Payee ─────────────────────────────────────────────────────────────────
    payee_name    = models.CharField(max_length=255, verbose_name='اسم المستفيد')
    bank_name     = models.CharField(max_length=100, blank=True, verbose_name='البنك')
    account_number = models.CharField(max_length=50, blank=True, verbose_name='رقم الحساب')

    # ── Amounts ───────────────────────────────────────────────────────────────
    total_amount  = models.DecimalField(
        max_digits=14, decimal_places=2,
        verbose_name='إجمالي المبلغ',
    )
    # Optional: link to an invoice / purchase order
    reference_doc = models.CharField(
        max_length=100, blank=True,
        verbose_name='رقم المستند المرجعي',
        help_text='رقم الفاتورة أو أمر الشراء',
    )

    # ── Schedule parameters ───────────────────────────────────────────────────
    cheque_count    = models.PositiveSmallIntegerField(
        default=1, verbose_name='عدد الشيكات',
    )
    first_due_date  = models.DateField(verbose_name='تاريخ الشيك الأول')
    interval_value  = models.PositiveSmallIntegerField(
        default=1, verbose_name='فترة التكرار',
    )
    interval_unit   = models.CharField(
        max_length=6, choices=INTERVAL_CHOICES,
        default='months', verbose_name='وحدة التكرار',
    )

    # ── People ────────────────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cheque_plans_created',
        verbose_name='أنشئ بواسطة',
    )
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cheque_plans',
        verbose_name='الفرع',
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'خطة شيكات'
        verbose_name_plural = 'خطط الشيكات'

    def __str__(self):
        return f'{self.title} — {self.payee_name} ({self.total_amount})'

    @property
    def cleared_count(self):
        return self.instalments.filter(status='cleared').count()

    @property
    def pending_count(self):
        return self.instalments.filter(status__in=['pending', 'issued']).count()

    @property
    def total_cleared(self):
        return self.instalments.filter(status='cleared').aggregate(
            t=models.Sum('amount')
        )['t'] or Decimal('0')


class ChequeInstalment(models.Model):
    """
    One physical cheque within a ChequePlan.
    due_date is the banking-day-adjusted date;
    nominal_date is the raw computed date before holiday adjustment.
    """
    STATUS_CHOICES = [
        ('pending',   'لم يُصدَر'),
        ('issued',    'صادر'),
        ('presented', 'مُقدَّم للبنك'),
        ('cleared',   'تمّ الصرف'),
        ('bounced',   'ارتدّ / رُفض'),
        ('cancelled', 'ملغي'),
    ]

    plan           = models.ForeignKey(
        ChequePlan,
        on_delete=models.CASCADE,
        related_name='instalments',
        verbose_name='الخطة',
    )
    instalment_no  = models.PositiveSmallIntegerField(verbose_name='رقم الشيك')
    amount         = models.DecimalField(
        max_digits=14, decimal_places=2,
        verbose_name='المبلغ',
    )
    nominal_date   = models.DateField(
        verbose_name='التاريخ الاسمي',
        help_text='التاريخ قبل تعديل الإجازات',
    )
    due_date       = models.DateField(
        db_index=True,
        verbose_name='تاريخ الاستحقاق',
        help_text='أول يوم عمل مصرفي ≥ التاريخ الاسمي',
    )
    cheque_number  = models.CharField(
        max_length=50, blank=True,
        verbose_name='رقم الشيك',
    )
    status         = models.CharField(
        max_length=10, choices=STATUS_CHOICES,
        default='pending', db_index=True,
        verbose_name='الحالة',
    )
    issued_at      = models.DateField(null=True, blank=True, verbose_name='تاريخ الإصدار')
    cleared_at     = models.DateField(null=True, blank=True, verbose_name='تاريخ الصرف')
    notes          = models.CharField(max_length=500, blank=True, verbose_name='ملاحظات')

    class Meta:
        ordering = ['instalment_no']
        verbose_name = 'شيك'
        verbose_name_plural = 'شيكات'
        unique_together = [('plan', 'instalment_no')]

    def __str__(self):
        return f'{self.plan.title} #{self.instalment_no} — {self.due_date} ({self.amount})'
