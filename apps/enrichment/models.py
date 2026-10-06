"""
apps/enrichment/models.py

AI-Assisted Catalog Enrichment Layer.

Design rules:
  - NEVER overwrites SOFTECH-synced fields on catalog.Item
  - SOFTECH remains source of truth; this module is an extension layer
  - Every suggestion tracks: source, confidence, status, reviewer
  - Self-learning: approved/rejected decisions feed EnrichmentApprovalLog
"""
from django.db import models
from django.conf import settings


# ── Enrichable field registry ─────────────────────────────────────────────────

ENRICHABLE_FIELDS = [
    'name_ar', 'brand_name',
    'manufacturer_ar', 'manufacturer_en',
    'country_ar', 'country_en',
    'dosage_form_ar', 'dosage_form_en',
    'atc_code', 'strength', 'volume', 'pack_size_label',
    'indication_ar', 'indication_en',
    'contraindication_ar', 'warning_ar',
    'pregnancy_category', 'age_range',
    'storage_condition', 'administration_route_ar',
    'dosage_ar', 'frequency_ar', 'duration_ar',
    'side_effects_ar', 'side_effects_en', 'drug_interactions_ar',
    'rx_otc', 'image_url', 'image_secondary_url',
    'seo_desc_ar', 'seo_desc_en',
    'medical_keywords_ar', 'medical_keywords_en',
]

FIELD_LABELS_AR = {
    'name_ar':                'الاسم العربي',
    'brand_name':             'الاسم التجاري',
    'manufacturer_ar':        'الشركة المصنعة (عربي)',
    'manufacturer_en':        'الشركة المصنعة (إنجليزي)',
    'country_ar':             'بلد المنشأ (عربي)',
    'country_en':             'بلد المنشأ (إنجليزي)',
    'dosage_form_ar':         'الشكل الدوائي (عربي)',
    'dosage_form_en':         'الشكل الدوائي (إنجليزي)',
    'atc_code':               'كود ATC',
    'strength':               'التركيز / القوة',
    'volume':                 'الحجم',
    'pack_size_label':        'حجم العبوة',
    'indication_ar':          'الاستخدامات (عربي)',
    'indication_en':          'الاستخدامات (إنجليزي)',
    'contraindication_ar':    'موانع الاستخدام',
    'warning_ar':             'التحذيرات',
    'pregnancy_category':     'فئة الحمل',
    'age_range':              'الفئة العمرية',
    'storage_condition':      'شروط التخزين',
    'administration_route_ar': 'طريقة الاستخدام',
    'dosage_ar':              'الجرعة',
    'frequency_ar':           'التكرار',
    'duration_ar':            'مدة العلاج',
    'side_effects_ar':        'الآثار الجانبية (عربي)',
    'side_effects_en':        'الآثار الجانبية (إنجليزي)',
    'drug_interactions_ar':   'التفاعلات الدوائية',
    'rx_otc':                 'وصفة طبية / بدون وصفة',
    'image_url':              'صورة المنتج',
    'image_secondary_url':    'صورة ثانوية',
    'seo_desc_ar':            'وصف SEO (عربي)',
    'seo_desc_en':            'وصف SEO (إنجليزي)',
    'medical_keywords_ar':    'الكلمات الطبية (عربي)',
    'medical_keywords_en':    'الكلمات الطبية (إنجليزي)',
}

SOURCE_CHOICES = [
    ('softech',           'بيانات SOFTECH'),
    ('chronic_module',    'وحدة الأدوية المزمنة'),
    ('supplier_catalog',  'كتالوج المورد'),
    ('manual',            'إدخال يدوي'),
    ('ai_extract',        'استخراج ذكاء اصطناعي'),
    ('ocr',               'استخراج OCR'),
    ('previous_approval', 'موافقة سابقة'),
    ('rule_engine',       'محرك القواعد'),
]

SUGGESTION_STATUS_CHOICES = [
    ('pending',  'في الانتظار'),
    ('approved', 'موافق عليه'),
    ('rejected', 'مرفوض'),
    ('edited',   'تم التعديل'),
]


# ── Core enrichment record (one per item) ─────────────────────────────────────

class ItemEnrichment(models.Model):
    """
    Enrichment data layer for catalog.Item.
    One record per item. Never touches SOFTECH-synced fields.
    """
    item = models.OneToOneField(
        'catalog.Item',
        on_delete=models.CASCADE,
        related_name='enrichment',
        verbose_name='الصنف',
    )

    # ── Bilingual names ────────────────────────────────────────────────────────
    name_ar    = models.CharField(max_length=255, blank=True, verbose_name='الاسم العربي')
    brand_name = models.CharField(max_length=255, blank=True, verbose_name='الاسم التجاري')

    # ── Manufacturer / country ─────────────────────────────────────────────────
    manufacturer_ar = models.CharField(max_length=255, blank=True, verbose_name='الشركة المصنعة (عربي)')
    manufacturer_en = models.CharField(max_length=255, blank=True, verbose_name='الشركة المصنعة (إنجليزي)')
    country_ar      = models.CharField(max_length=100, blank=True, verbose_name='بلد المنشأ (عربي)')
    country_en      = models.CharField(max_length=100, blank=True, verbose_name='بلد المنشأ (إنجليزي)')

    # ── Dosage form ────────────────────────────────────────────────────────────
    dosage_form_ar = models.CharField(max_length=100, blank=True, verbose_name='الشكل الدوائي (عربي)')
    dosage_form_en = models.CharField(max_length=100, blank=True, verbose_name='الشكل الدوائي (إنجليزي)')

    # ── Drug details ───────────────────────────────────────────────────────────
    atc_code        = models.CharField(max_length=20,  blank=True, verbose_name='كود ATC')
    strength        = models.CharField(max_length=100, blank=True, verbose_name='التركيز / القوة')
    volume          = models.CharField(max_length=50,  blank=True, verbose_name='الحجم')
    pack_size_label = models.CharField(max_length=100, blank=True, verbose_name='حجم العبوة')

    # ── Clinical info ──────────────────────────────────────────────────────────
    indication_ar       = models.TextField(blank=True, verbose_name='الاستخدامات (عربي)')
    indication_en       = models.TextField(blank=True, verbose_name='الاستخدامات (إنجليزي)')
    contraindication_ar = models.TextField(blank=True, verbose_name='موانع الاستخدام')
    warning_ar          = models.TextField(blank=True, verbose_name='التحذيرات')
    pregnancy_category  = models.CharField(max_length=10, blank=True, verbose_name='فئة الحمل')
    age_range           = models.TextField(blank=True, verbose_name='الفئة العمرية')

    # ── Storage / administration ───────────────────────────────────────────────
    storage_condition       = models.TextField(blank=True, verbose_name='شروط التخزين')
    administration_route_ar = models.TextField(blank=True, verbose_name='طريقة الاستخدام')

    # ── Dosage regimen ─────────────────────────────────────────────────────────
    dosage_ar    = models.TextField(blank=True, verbose_name='الجرعة')
    frequency_ar = models.TextField(blank=True, verbose_name='التكرار')
    duration_ar  = models.TextField(blank=True, verbose_name='مدة العلاج')

    # ── Safety ─────────────────────────────────────────────────────────────────
    side_effects_ar      = models.TextField(blank=True, verbose_name='الآثار الجانبية (عربي)')
    side_effects_en      = models.TextField(blank=True, verbose_name='الآثار الجانبية (إنجليزي)')
    drug_interactions_ar = models.TextField(blank=True, verbose_name='التفاعلات الدوائية')

    # ── Classification ─────────────────────────────────────────────────────────
    rx_otc = models.CharField(
        max_length=10, blank=True,
        choices=[
            ('rx',  'يحتاج وصفة طبية (Rx)'),
            ('otc', 'بدون وصفة (OTC)'),
            ('cd',  'مخدرات/تحكم (CD)'),
        ],
        verbose_name='وصفة طبية',
    )

    # ── Media ──────────────────────────────────────────────────────────────────
    # image_url is a CACHE of the primary ProductMedia URL, synced by the
    # image pipeline (images/pipeline.py → _sync_enrichment_url).
    # SOURCE OF TRUTH is product_experience.ProductMedia (is_primary=True).
    # Never set image_url directly — use ProductMedia + let the pipeline sync it.
    # Use the property `primary_image_url` for reads to always get the fresh value.
    image_url           = models.URLField(max_length=500, blank=True, verbose_name='صورة المنتج (كاش)')
    image_secondary_url = models.URLField(max_length=500, blank=True, verbose_name='صورة ثانوية')

    # ── SEO / search ───────────────────────────────────────────────────────────
    seo_desc_ar         = models.TextField(blank=True, verbose_name='وصف SEO (عربي)')
    seo_desc_en         = models.TextField(blank=True, verbose_name='وصف SEO (إنجليزي)')
    medical_keywords_ar = models.TextField(blank=True, verbose_name='الكلمات الطبية (عربي)')
    medical_keywords_en = models.TextField(blank=True, verbose_name='الكلمات الطبية (إنجليزي)')

    # ── Quality tracking ───────────────────────────────────────────────────────
    completeness_score = models.FloatField(default=0.0, db_index=True, verbose_name='نسبة الاكتمال %')
    is_published       = models.BooleanField(default=False, db_index=True, verbose_name='منشور')
    last_enriched_at   = models.DateTimeField(null=True, blank=True)
    enriched_by        = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='enriched_items',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'إثراء صنف'
        verbose_name_plural = 'إثراء الأصناف'
        ordering            = ['completeness_score']

    def __str__(self):
        return f'Enrichment: {self.item.name} [{self.completeness_score:.0f}%]'

    def compute_score(self) -> float:
        """
        Recompute completeness_score from ENRICHABLE_FIELDS.
        Updates self in memory only — call save() after.
        """
        filled = sum(1 for f in ENRICHABLE_FIELDS if getattr(self, f, ''))
        self.completeness_score = round(filled / len(ENRICHABLE_FIELDS) * 100, 1)
        return self.completeness_score

    @property
    def primary_image_url(self) -> str:
        """
        Always reads the PRIMARY image from ProductMedia (source of truth).
        Falls back to the cached image_url field if no ProductMedia record exists.

        Use this property everywhere instead of accessing image_url directly.
        """
        try:
            from apps.product_experience.models import ProductMedia
            media = ProductMedia.objects.filter(
                item=self.item, media_type='image', is_primary=True, approved=True,
            ).first()
            if media and media.file:
                return media.file.url
        except Exception:
            pass
        return self.image_url

    def sync_image_url(self) -> bool:
        """
        Re-sync image_url cache from the primary ProductMedia record.
        Call this after any ProductMedia change to keep the cache fresh.
        Returns True if the cache was updated.
        """
        fresh = self.primary_image_url
        if fresh and fresh != self.image_url:
            self.image_url = fresh
            self.save(update_fields=['image_url'])
            return True
        return False


# ── Batch run ─────────────────────────────────────────────────────────────────

class EnrichmentBatch(models.Model):
    SCOPE_CHOICES = [
        ('all',       'كل الكتالوج'),
        ('category',  'تصنيف محدد'),
        ('supplier',  'مورد محدد'),
        ('selected',  'أصناف محددة'),
        ('low_score', 'أقل من حد الاكتمال'),
    ]
    STATUS_CHOICES = [
        ('pending',   'في الانتظار'),
        ('running',   'جارٍ التشغيل'),
        ('success',   'اكتمل'),
        ('failed',    'فشل'),
        ('cancelled', 'ملغي'),
    ]

    name       = models.CharField(max_length=200, blank=True, verbose_name='اسم الدفعة')
    status     = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending', db_index=True)
    scope_type = models.CharField(max_length=15, choices=SCOPE_CHOICES, default='all')
    scope_params = models.JSONField(
        default=dict, blank=True,
        help_text='e.g. {"category_id": 5, "threshold": 30}',
    )
    auto_publish_threshold = models.FloatField(
        default=0.90,
        help_text='Suggestions with confidence ≥ this are auto-approved',
    )

    total_items           = models.PositiveIntegerField(default=0)
    processed_items       = models.PositiveIntegerField(default=0)
    suggestions_generated = models.PositiveIntegerField(default=0)
    auto_published        = models.PositiveIntegerField(default=0)
    error_count           = models.PositiveIntegerField(default=0)
    error_log             = models.TextField(blank=True)

    created_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='enrichment_batches',
    )
    started_at  = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'دفعة إثراء'
        verbose_name_plural = 'دفعات الإثراء'
        ordering            = ['-created_at']

    def __str__(self):
        return f'Batch #{self.pk} [{self.get_status_display()}] — {self.processed_items}/{self.total_items}'

    @property
    def progress_pct(self):
        if not self.total_items:
            return 0
        return round(self.processed_items / self.total_items * 100, 1)


# ── Per-field suggestion ──────────────────────────────────────────────────────

class EnrichmentSuggestion(models.Model):
    """One per field per item. Stores source suggestion + human review state."""

    item       = models.ForeignKey(
        'catalog.Item',
        on_delete=models.CASCADE,
        related_name='enrichment_suggestions',
    )
    enrichment = models.ForeignKey(
        ItemEnrichment,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='suggestions',
    )
    batch = models.ForeignKey(
        EnrichmentBatch,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='suggestions',
    )

    field_name      = models.CharField(max_length=60, db_index=True)
    suggested_value = models.TextField()
    current_value   = models.TextField(blank=True)
    source          = models.CharField(max_length=30, choices=SOURCE_CHOICES)
    confidence      = models.FloatField(default=0.5)

    status         = models.CharField(max_length=15, choices=SUGGESTION_STATUS_CHOICES, default='pending', db_index=True)
    approved_value = models.TextField(blank=True)
    notes          = models.TextField(blank=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_suggestions',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'اقتراح إثراء'
        verbose_name_plural = 'اقتراحات الإثراء'
        ordering            = ['-confidence', 'field_name']
        indexes = [
            models.Index(fields=['item', 'status']),
            models.Index(fields=['item', 'field_name', 'status']),
            models.Index(fields=['batch', 'status']),
        ]

    def __str__(self):
        return f'{self.item.softech_id} | {self.field_name} | {self.status}'

    @property
    def field_label_ar(self):
        return FIELD_LABELS_AR.get(self.field_name, self.field_name)


# ── Approval audit log ────────────────────────────────────────────────────────

class EnrichmentApprovalLog(models.Model):
    """
    Immutable audit trail. Every approve/reject decision is logged here.
    Powers the self-learning confidence engine.
    """
    item       = models.ForeignKey(
        'catalog.Item',
        on_delete=models.CASCADE,
        related_name='enrichment_approvals',
    )
    field_name           = models.CharField(max_length=60)
    source               = models.CharField(max_length=30, choices=SOURCE_CHOICES)
    confidence_at_review = models.FloatField()
    outcome              = models.CharField(
        max_length=10,
        choices=[
            ('approved', 'موافق'),
            ('rejected', 'مرفوض'),
            ('edited',   'تم التعديل'),
        ],
    )
    accepted_value = models.TextField(blank=True)
    reviewer       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'سجل موافقة إثراء'
        verbose_name_plural = 'سجلات موافقات الإثراء'
        ordering            = ['-reviewed_at']
        indexes             = [
            models.Index(fields=['field_name', 'source', 'outcome']),
        ]

    def __str__(self):
        return f'{self.item.softech_id} | {self.field_name} | {self.outcome}'
