"""
apps/counselling/models.py — Project 4 (doc 34).

Pharmacist-approved counselling sheets ("how to use" text) shared by the items a pharmacist links,
with an immutable snapshot per approval. Customer-facing readers (the WhatsApp card, Project 5's
printed label) only ever read the latest APPROVED snapshot — never the editable fields.
"""
from django.db import models

TEXT_FIELDS = ('what_for', 'how_to_use', 'dose', 'frequency', 'duration', 'warnings', 'storage', 'missed_dose')
CONTENT_FIELDS = tuple(f'{f}_{lang}' for lang in ('ar', 'en') for f in TEXT_FIELDS) + ('frequency_code', 'with_food')

WITH_FOOD_LABELS = {'before': 'قبل الأكل', 'after': 'بعد الأكل', 'any': 'مع الأكل أو بدونه', '': ''}


class CounsellingContent(models.Model):
    STATUS_CHOICES = [
        ('draft',          'مسودة'),
        ('pending_review', 'بانتظار الاعتماد'),
        ('approved',       'معتمد'),
        ('retired',        'مسحوب'),
    ]
    SOURCE_CHOICES = [('manual', 'كتابة صيدلي'), ('ai_draft', 'مسودة آلية')]
    WITH_FOOD_CHOICES = [('', '—'), ('before', 'قبل الأكل'), ('after', 'بعد الأكل'), ('any', 'مع الأكل أو بدونه')]

    title = models.CharField(max_length=200, blank=True, verbose_name='العنوان')

    what_for_ar = models.TextField(blank=True, verbose_name='يستخدم في')
    how_to_use_ar = models.TextField(blank=True, verbose_name='طريقة الاستخدام')
    dose_ar = models.TextField(blank=True, verbose_name='الجرعة')
    frequency_ar = models.TextField(blank=True, verbose_name='عدد المرات')
    duration_ar = models.TextField(blank=True, verbose_name='المدة')
    warnings_ar = models.TextField(blank=True, verbose_name='تحذيرات')
    storage_ar = models.TextField(blank=True, verbose_name='الحفظ')
    missed_dose_ar = models.TextField(blank=True, verbose_name='عند نسيان جرعة')
    what_for_en = models.TextField(blank=True)
    how_to_use_en = models.TextField(blank=True)
    dose_en = models.TextField(blank=True)
    frequency_en = models.TextField(blank=True)
    duration_en = models.TextField(blank=True)
    warnings_en = models.TextField(blank=True)
    storage_en = models.TextField(blank=True)
    missed_dose_en = models.TextField(blank=True)
    frequency_code = models.CharField(max_length=10, blank=True, verbose_name='رمز التكرار')   # 1x1, 1x2, 1x3, prn
    with_food = models.CharField(max_length=10, blank=True, choices=WITH_FOOD_CHOICES, verbose_name='مع الأكل')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft', db_index=True,
                              verbose_name='الحالة')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='manual', verbose_name='المصدر')
    ai_model = models.CharField(max_length=80, blank=True, verbose_name='نموذج المسودة الآلية')
    version = models.PositiveIntegerField(default=0, verbose_name='آخر إصدار معتمد')
    approved_version = models.ForeignKey('CounsellingContentVersion', null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name='+',
                                         verbose_name='الإصدار المعتمد الحالي')
    retired_reason = models.CharField(max_length=255, blank=True, verbose_name='سبب السحب')

    created_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    updated_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    approved_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+')
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إرشاد استخدام'
        verbose_name_plural = 'إرشادات الاستخدام'
        ordering = ['-updated_at', '-id']

    def __str__(self):
        return self.title or f'إرشاد #{self.pk}'

    def snapshot(self) -> dict:
        return {f: getattr(self, f) for f in CONTENT_FIELDS}


class CounsellingContentItem(models.Model):
    """An item shares exactly one sheet; the pharmacist picks which items (never auto-linked)."""
    content = models.ForeignKey(CounsellingContent, on_delete=models.CASCADE, related_name='links')
    item = models.OneToOneField('catalog.Item', on_delete=models.CASCADE, related_name='counselling_link')
    linked_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='+')
    linked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'صنف مرتبط بإرشاد'
        verbose_name_plural = 'أصناف مرتبطة بإرشادات'


class CounsellingContentVersion(models.Model):
    """Immutable snapshot written at each approval — what customers actually received."""
    content = models.ForeignKey(CounsellingContent, on_delete=models.CASCADE, related_name='versions')
    version = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    approved_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+')
    approved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('content', 'version')]
        ordering = ['-version']
        verbose_name = 'إصدار إرشاد معتمد'
        verbose_name_plural = 'إصدارات الإرشادات المعتمدة'

    @staticmethod
    def snapshot_fields():
        return CONTENT_FIELDS

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('approved counselling versions are immutable')
        super().save(*args, **kwargs)


class CounselCardSend(models.Model):
    """One WhatsApp counselling card a staff member sent — the audit row (who/what/when/to whom)."""
    STATUS_CHOICES = [
        ('queued',          'قيد الإرسال'),
        ('sent',            'أُرسلت'),
        ('failed',          'فشل الإرسال'),
        ('blocked_optout',  'العميل أوقف الرسائل'),
    ]
    SOURCE_CHOICES = [('pos', 'نقطة البيع'), ('customer360', 'ملف العميل'), ('assistant', 'معلومات الصنف')]

    customer = models.ForeignKey('customers.Customer', null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='counsel_cards')
    first_name = models.CharField(max_length=80, blank=True)
    phone_masked = models.CharField(max_length=20, blank=True)
    phone_hash = models.CharField(max_length=64, db_index=True)
    branch = models.ForeignKey('branches.Branch', null=True, blank=True, on_delete=models.SET_NULL,
                               related_name='+')
    sent_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='+')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='pos')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued', db_index=True)
    fail_reason = models.CharField(max_length=255, blank=True)
    channel = models.CharField(max_length=20, blank=True)        # template | text
    wamid = models.CharField(max_length=128, blank=True)         # links the WAMessage the sender logged
    idempotency_key = models.CharField(max_length=64, unique=True)
    resend = models.BooleanField(default=False)
    first_opened_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'إرسال إرشادات لعميل'
        verbose_name_plural = 'إرسالات الإرشادات للعملاء'
        indexes = [models.Index(fields=['branch', 'created_at'])]

    def __str__(self):
        return f'إرشادات #{self.pk} → {self.phone_masked}'


class CounselCardItem(models.Model):
    send = models.ForeignKey(CounselCardSend, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, related_name='+')
    content = models.ForeignKey(CounsellingContent, on_delete=models.PROTECT, related_name='+')
    version = models.ForeignKey(CounsellingContentVersion, on_delete=models.PROTECT, related_name='+')


class CounselCardOptOut(models.Model):
    """The customer asked to stop counselling messages (by customer and/or phone)."""
    customer = models.ForeignKey('customers.Customer', null=True, blank=True, on_delete=models.CASCADE,
                                 related_name='+')
    phone_hash = models.CharField(max_length=64, db_index=True)
    source = models.CharField(max_length=20, default='link')     # link | staff
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'إيقاف رسائل الإرشادات'
        verbose_name_plural = 'إيقاف رسائل الإرشادات'
