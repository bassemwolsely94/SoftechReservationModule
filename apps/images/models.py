"""
apps/images/models.py

Image Acquisition Pipeline — schema.

Flow:
  Item  →  ProductNormalization  (cached name parse)
        →  ImageSearchJob        (one job per item, retried per stage)
        →  ImageCandidate        (raw results, one per URL found)
        →  [human review]
        →  ProductMedia          (approved image, owned by product_experience)

Nothing here writes to SOFTECH.  All reads are PostgreSQL + public internet.
"""
from django.conf import settings
from django.db import models


# ── Choices ───────────────────────────────────────────────────────────────────

JOB_STATUS = [
    ('pending',   'في الانتظار'),
    ('running',   'جارٍ التشغيل'),
    ('done',      'مكتمل'),
    ('failed',    'فشل'),
    ('skipped',   'تخطي — صورة موجودة'),
    ('cancelled', 'ملغي'),
]

PIPELINE_STAGE = [
    (1, 'المرحلة 1 — الكاش الداخلي'),
    (2, 'المرحلة 2 — الباركود / قواعد البيانات'),
    (3, 'المرحلة 3 — مواقع الموردين'),
    (4, 'المرحلة 4 — مواقع الصيدليات'),
    (5, 'المرحلة 5 — محركات البحث'),
    (6, 'المرحلة 6 — مراجعة بشرية'),
]

SOURCE_TYPE = [
    ('cache',        'كاش داخلي'),
    ('openfoodfacts','Open Food Facts'),
    ('openbeauty',   'Open Beauty Facts'),
    ('drugs_com',    'drugs.com'),
    ('rxlist',       'RxList'),
    ('manufacturer', 'موقع المورد'),
    ('pharmacy_site','موقع صيدلية'),
    ('duckduckgo',   'DuckDuckGo Images'),
    ('google',       'Google Images'),
    ('bing',         'Bing Images'),
    ('manual',       'رفع يدوي'),
    ('ai_generated', 'توليد AI'),
]

CANDIDATE_STATUS = [
    ('new',          'جديد'),
    ('scored',       'تم التقييم'),
    ('auto_approved','موافقة تلقائية'),
    ('pending_review','قيد المراجعة'),
    ('approved',     'موافق عليها'),
    ('rejected',     'مرفوضة'),
    ('error',        'خطأ في التنزيل'),
]

PRIORITY = [
    (1, 'منخفضة'),
    (2, 'عادية'),
    (3, 'عالية'),
    (4, 'عاجلة'),
]


# ── ProductNormalization ───────────────────────────────────────────────────────

class ProductNormalization(models.Model):
    """
    Cached parse of an item's name into structured fields used for search.
    Re-computed automatically when the item name changes (via pipeline).
    """
    item = models.OneToOneField(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='normalization',
    )

    # Cleaned forms
    canonical_name      = models.CharField(max_length=400, blank=True)
    normalized_name     = models.CharField(max_length=400, blank=True)
    # Search queries sent to external sources
    search_query_en     = models.CharField(max_length=300, blank=True)
    search_query_ar     = models.CharField(max_length=300, blank=True)
    # Extracted components
    brand               = models.CharField(max_length=100, blank=True)
    strength            = models.CharField(max_length=50,  blank=True)   # e.g. "500mg"
    dosage_form         = models.CharField(max_length=60,  blank=True)   # tablet/syrup…
    pack_size           = models.CharField(max_length=50,  blank=True)   # "30 tab"
    # Known aliases (barcode, OCR variants, supplier names)
    aliases             = models.JSONField(default=list, blank=True)
    # Confidence in the parse
    parse_confidence    = models.FloatField(default=0.0)

    updated_at          = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'تطبيع اسم المنتج'
        verbose_name_plural = 'تطبيع أسماء المنتجات'

    def __str__(self):
        return f'{self.item.softech_id} → {self.canonical_name}'


# ── ImageSearchJob ─────────────────────────────────────────────────────────────

class ImageSearchJob(models.Model):
    """
    One job per (item, trigger).  Background worker advances through stages.
    If an earlier stage succeeds (confidence ≥ auto_approve_threshold)
    the job completes without reaching later (expensive) stages.
    """
    item              = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='image_jobs',
    )
    status            = models.CharField(max_length=12, choices=JOB_STATUS,
                                         default='pending', db_index=True)
    current_stage     = models.PositiveSmallIntegerField(default=1,
                                                         choices=PIPELINE_STAGE)
    priority          = models.PositiveSmallIntegerField(default=2, choices=PRIORITY,
                                                         db_index=True)
    attempt_count     = models.PositiveSmallIntegerField(default=0)
    max_attempts      = models.PositiveSmallIntegerField(default=3)

    # Thresholds
    auto_approve_threshold = models.FloatField(default=0.85)
    review_threshold       = models.FloatField(default=0.50)

    # Progress
    candidates_found  = models.PositiveIntegerField(default=0)
    candidates_scored = models.PositiveIntegerField(default=0)
    best_score        = models.FloatField(default=0.0)

    # Audit
    triggered_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='triggered_image_jobs',
    )
    last_error        = models.TextField(blank=True)
    started_at        = models.DateTimeField(null=True, blank=True)
    finished_at       = models.DateTimeField(null=True, blank=True)
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering        = ['-priority', 'created_at']
        indexes         = [
            models.Index(fields=['status', 'priority']),
            models.Index(fields=['item', 'status']),
        ]
        verbose_name        = 'مهمة بحث عن صورة'
        verbose_name_plural = 'مهام البحث عن صور'

    def __str__(self):
        return f'Job#{self.pk} {self.item.softech_id} [{self.get_status_display()}]'


# ── ImageCandidate ─────────────────────────────────────────────────────────────

class ImageCandidate(models.Model):
    """
    Raw image found during search, before human approval.
    Scored by scorer.py; approved candidates are promoted to ProductMedia.
    """
    job              = models.ForeignKey(
        ImageSearchJob, on_delete=models.CASCADE,
        related_name='candidates',
    )
    item             = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='image_candidates',
    )

    # Source
    source_url       = models.URLField(max_length=2000)
    source_type      = models.CharField(max_length=20, choices=SOURCE_TYPE,
                                        default='duckduckgo')
    source_page_url  = models.URLField(max_length=2000, blank=True)
    query_used       = models.CharField(max_length=300, blank=True)

    # Local storage (downloaded by downloader.py)
    local_file       = models.ImageField(
        upload_to='image_candidates/%Y/%m/',
        null=True, blank=True,
    )

    # Image dimensions / file info
    width            = models.PositiveIntegerField(null=True, blank=True)
    height           = models.PositiveIntegerField(null=True, blank=True)
    file_size_bytes  = models.PositiveIntegerField(null=True, blank=True)
    format           = models.CharField(max_length=10, blank=True)   # JPEG/PNG/WEBP

    # Deduplication fingerprint (perceptual hash)
    phash            = models.CharField(max_length=64, blank=True, db_index=True)

    # Scoring
    quality_score    = models.FloatField(default=0.0)    # 0-1 image quality
    confidence_score = models.FloatField(default=0.0)   # 0-1 product match
    total_score      = models.FloatField(default=0.0)   # weighted composite

    # Score breakdown (for transparency/debugging)
    score_breakdown  = models.JSONField(default=dict, blank=True)

    # Status
    status           = models.CharField(max_length=16, choices=CANDIDATE_STATUS,
                                        default='new', db_index=True)
    reviewed_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='reviewed_candidates',
    )
    reviewed_at      = models.DateTimeField(null=True, blank=True)
    review_note      = models.CharField(max_length=300, blank=True)

    # Metadata from scraper
    scraper_metadata = models.JSONField(default=dict, blank=True)

    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-total_score', '-quality_score']
        indexes  = [
            models.Index(fields=['item', 'status']),
            models.Index(fields=['job', 'total_score']),
            models.Index(fields=['phash']),
        ]
        verbose_name        = 'صورة مرشحة'
        verbose_name_plural = 'صور مرشحة'

    def __str__(self):
        return f'Candidate#{self.pk} [{self.source_type}] score={self.total_score:.2f}'

    @property
    def image_url(self):
        if self.local_file:
            return self.local_file.url
        return self.source_url

    @property
    def dimensions(self):
        if self.width and self.height:
            return f'{self.width}×{self.height}'
        return ''


# ── ImageSource ────────────────────────────────────────────────────────────────

class ImageSource(models.Model):
    """
    Configured external sources.  Tracks reliability + rate limits.
    Seeds via management command seed_image_sources.
    """
    name              = models.CharField(max_length=60, unique=True)
    source_type       = models.CharField(max_length=20, choices=SOURCE_TYPE)
    base_url          = models.URLField(max_length=500, blank=True)
    priority          = models.PositiveSmallIntegerField(default=5)   # lower = tried first
    rate_limit_rpm    = models.PositiveSmallIntegerField(default=20)
    requires_js       = models.BooleanField(default=False)            # needs Playwright
    is_active         = models.BooleanField(default=True, db_index=True)

    # Rolling stats (updated by pipeline)
    total_requests    = models.PositiveIntegerField(default=0)
    successful_hits   = models.PositiveIntegerField(default=0)
    avg_quality_score = models.FloatField(default=0.0)
    last_used_at      = models.DateTimeField(null=True, blank=True)

    headers           = models.JSONField(default=dict, blank=True)  # extra HTTP headers

    class Meta:
        ordering        = ['priority']
        verbose_name        = 'مصدر صور'
        verbose_name_plural = 'مصادر الصور'

    def __str__(self):
        return f'{self.name} (priority={self.priority})'

    @property
    def success_rate(self):
        if self.total_requests == 0:
            return 0.0
        return self.successful_hits / self.total_requests


# ── ImageApprovalInsight ───────────────────────────────────────────────────────

class ImageApprovalInsight(models.Model):
    """
    Learns from every approval: which source_type produces accepted images
    for each brand.  Updated automatically on approve_candidate().
    Used by the pipeline to boost known-good sources on future searches.

    Example: ARCOXIA → drugs_com approved 12/15 times → weight 1.3 (boost)
             ARCOXIA → duckduckgo approved 2/10 times → weight 0.7 (reduce)
    """
    brand             = models.CharField(max_length=100, db_index=True)
    source_type       = models.CharField(max_length=20)
    approved          = models.PositiveIntegerField(default=0)
    considered        = models.PositiveIntegerField(default=0)   # total candidates from this source
    avg_quality_score = models.FloatField(default=0.0)           # rolling avg of approved image quality
    last_updated      = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together     = ('brand', 'source_type')
        ordering            = ['-approved']
        verbose_name        = 'تعلم مصادر الصور'
        verbose_name_plural = 'تعلم مصادر الصور'

    def __str__(self):
        return f'{self.brand} / {self.source_type}: {self.approved}/{self.considered}'

    @property
    def approval_rate(self) -> float:
        return self.approved / self.considered if self.considered else 0.0

    @property
    def weight(self) -> float:
        """
        Search boost multiplier: 0.5 (penalise) to 1.5 (boost).
        Blends approval_rate with avg_quality_score of approved images.
        """
        if self.considered < 3:
            return 1.0   # not enough data yet
        base = 0.5 + self.approval_rate      # 0.5–1.5 from approval rate
        if self.avg_quality_score > 0:
            # Quality adjustment: ±0.1 based on image quality of approved images
            quality_adj = (self.avg_quality_score - 0.5) * 0.2
            base = min(1.5, max(0.5, base + quality_adj))
        return round(base, 2)
