"""
apps/followups/models.py

Phase 5: Follow-up Engine

Two models:
  ChronicMedicationProfile  — tracks chronic medications with refill timing
  FollowUpTask              — scheduled tasks to contact patients for refills

Logic:
  - Get last sale from ERPTransaction (doccode=115, Phase 1 required)
  - Calculate expected refill date = last_sale_date + expected_duration_days
  - Create FollowUpTask due on refill date
  - Auto-close task if a new ERP sale is found after the follow-up was created

HARD RULES:
  ❌ No stock mutations
  ❌ No ERP writes
  ✅ ERP READ ONLY
"""
from django.db import models
from django.utils import timezone
from datetime import timedelta


class ChronicMedicationProfile(models.Model):
    """
    Profile for a chronic medication — defines expected usage duration
    so the system can predict when a patient needs a refill.

    Can be populated manually by pharmacists or inferred from ERP history.
    """

    SOURCE_CHOICES = [
        ('manual',    '✍️ إدخال يدوي'),
        ('erp_infer', '🤖 استنتاج من الـ ERP'),
    ]

    # ── Item link ─────────────────────────────────────────────────────────────
    item = models.OneToOneField(
        'catalog.Item',
        on_delete=models.CASCADE,
        related_name='chronic_profile',
        verbose_name='الصنف',
    )

    # ── Chronic classification ────────────────────────────────────────────────
    is_chronic = models.BooleanField(
        default=True,
        verbose_name='دواء مزمن',
        db_index=True,
    )

    # ── Usage parameters ──────────────────────────────────────────────────────
    avg_daily_usage = models.DecimalField(
        max_digits=8, decimal_places=3,
        default=1,
        verbose_name='متوسط الاستخدام اليومي (وحدة/يوم)',
        help_text='مثال: 1 قرص/يوم = 1.0, نصف قرص/يوم = 0.5',
    )
    pack_size = models.DecimalField(
        max_digits=8, decimal_places=3,
        default=30,
        verbose_name='حجم العبوة (وحدة)',
        help_text='عدد الأقراص/الكبسولات/الجرعات في العبوة الواحدة',
    )
    expected_duration_days = models.PositiveIntegerField(
        default=30,
        verbose_name='مدة العبوة المتوقعة (يوم)',
        help_text='يُحسب تلقائياً: حجم_العبوة ÷ الاستخدام_اليومي',
    )

    # ── Follow-up timing ──────────────────────────────────────────────────────
    followup_before_days = models.PositiveIntegerField(
        default=5,
        verbose_name='أيام التذكير قبل النفاد',
        help_text='يُنشأ التذكير قبل نفاد الدواء بهذا العدد من الأيام',
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = models.TextField(blank=True, verbose_name='ملاحظات')
    source = models.CharField(
        max_length=12,
        choices=SOURCE_CHOICES,
        default='manual',
        verbose_name='مصدر البيانات',
    )

    # ── Audit ──────────────────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['item__name']
        verbose_name = 'بروفايل دواء مزمن'
        verbose_name_plural = 'بروفايلات الأدوية المزمنة'

    def __str__(self):
        return f'{self.item.name} — {self.expected_duration_days} يوم'

    def save(self, *args, **kwargs):
        # Auto-calculate duration from pack_size / avg_daily_usage
        if self.avg_daily_usage and self.avg_daily_usage > 0:
            self.expected_duration_days = max(
                1,
                int(float(self.pack_size) / float(self.avg_daily_usage))
            )
        super().save(*args, **kwargs)

    @property
    def followup_trigger_day(self):
        """
        Day offset from last sale date when a follow-up should be created.
        e.g. duration=30, before=5 → trigger on day 25
        """
        return max(1, self.expected_duration_days - self.followup_before_days)


class FollowUpTask(models.Model):
    """
    A scheduled follow-up task for a chronic patient.

    Lifecycle:
      pending  → assigned to call center / branch staff
      called   → staff attempted contact
      done     → patient confirmed / purchased
      missed   → no response after multiple attempts
      auto_closed → ERP confirmed a new sale automatically
      cancelled
    """

    STATUS_CHOICES = [
        ('pending',     'معلق — لم يُتواصل بعد'),
        ('called',      'تم الاتصال — لا رد'),
        ('done',        'مكتمل — تم الشراء'),
        ('missed',      'فائت — لا استجابة'),
        ('auto_closed', 'أُغلق تلقائياً — الـ ERP أكّد البيع'),
        ('cancelled',   'ملغي'),
    ]

    TYPE_CHOICES = [
        ('refill',    '💊 تذكير إعادة صرف'),
        ('chronic',   '🏥 متابعة مريض مزمن'),
        ('demand',    '📋 متابعة طلب عميل'),
        ('custom',    '📝 مخصص'),
    ]

    # ── Links ─────────────────────────────────────────────────────────────────
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='followup_tasks',
        verbose_name='العميل',
    )
    item = models.ForeignKey(
        'catalog.Item',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='followup_tasks',
        verbose_name='الصنف',
    )
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='chronic_followup_tasks',
        verbose_name='الفرع',
    )
    chronic_profile = models.ForeignKey(
        ChronicMedicationProfile,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='followup_tasks',
        verbose_name='بروفايل الدواء المزمن',
    )
    assigned_to = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='chronic_followup_tasks',
        verbose_name='مُعيَّن لـ',
    )

    # ── Task type & dates ─────────────────────────────────────────────────────
    task_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default='refill',
        verbose_name='نوع المهمة',
        db_index=True,
    )
    due_date = models.DateField(
        db_index=True,
        verbose_name='تاريخ الاستحقاق',
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        verbose_name='الحالة',
    )

    # ── ERP anchor ────────────────────────────────────────────────────────────
    # The sale that triggered this follow-up (stored as ERP doc reference string)
    source_erp_transaction = models.CharField(
        max_length=50, blank=True,
        verbose_name='رقم معاملة ERP المصدر',
        help_text='docnumber من stktransm',
    )
    source_sale_date = models.DateField(
        null=True, blank=True,
        verbose_name='تاريخ آخر بيع في الـ ERP',
    )

    # Auto-close anchor — the sale that closed this task
    closing_erp_transaction = models.CharField(
        max_length=50, blank=True,
        verbose_name='رقم معاملة ERP الإغلاق',
    )

    # ── Notes & result ────────────────────────────────────────────────────────
    notes       = models.TextField(blank=True, verbose_name='ملاحظات')
    result_note = models.TextField(blank=True, verbose_name='ملاحظة النتيجة')
    attempts    = models.PositiveIntegerField(default=0, verbose_name='عدد محاولات الاتصال')

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_by   = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_followup_tasks',
        verbose_name='أنشئ بواسطة',
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='completed_followup_tasks',
        verbose_name='أُنجز بواسطة',
    )

    class Meta:
        ordering = ['due_date', '-created_at']
        verbose_name = 'مهمة متابعة'
        verbose_name_plural = 'مهام المتابعة'
        indexes = [
            models.Index(fields=['status', 'due_date']),
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['item', 'status']),
            models.Index(fields=['branch', 'status', 'due_date']),
        ]

    def __str__(self):
        return (
            f'[{self.get_task_type_display()}] '
            f'{self.customer.name} — '
            f'{self.item.name if self.item else "—"} '
            f'@ {self.due_date}'
        )

    @property
    def is_overdue(self):
        from datetime import date
        return self.status == 'pending' and self.due_date < date.today()

    @property
    def is_active(self):
        return self.status in ('pending', 'called')

    @property
    def customer_phone(self):
        return self.customer.phone or ''

    @property
    def whatsapp_url(self):
        phone = self.customer.phone
        if not phone:
            return None
        clean = phone.strip().replace(' ', '').replace('-', '')
        if clean.startswith('0'):
            clean = '20' + clean[1:]
        return f'https://wa.me/{clean}'
