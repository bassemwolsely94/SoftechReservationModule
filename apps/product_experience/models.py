"""
apps/product_experience/models.py

Commerce Catalog + Product Experience Platform
Single Source of Truth for: ERP, Reservations, Call Center,
Customer Experience, E-Commerce, WhatsApp Commerce, Adherence.

ERP (SOFTECH) owns: transactions, stock, pricing, financial.
This app owns: images, descriptions, attributes, tags, search,
               relationships, recommendations, content, SEO.

NEVER overwrite ERP data. NEVER expose internal stock quantities.
"""
import os
from django.conf import settings
from django.db import models
from django.utils.text import slugify


# ── Upload path helpers ───────────────────────────────────────────────────────

def _media_path(instance, filename):
    return f'products/{instance.item.softech_id}/media/{filename}'

def _thumb_path(instance, filename):
    return f'products/{instance.item.softech_id}/thumbs/{filename}'

def _og_path(instance, filename):
    return f'products/{instance.item.softech_id}/og/{filename}'


# ── Constants ─────────────────────────────────────────────────────────────────

MEDIA_TYPES = [
    ('image',  'صورة'),
    ('video',  'فيديو'),
    ('pdf',    'ملف PDF'),
    ('manual', 'نشرة / دليل'),
]

MEDIA_SOURCES = [
    ('manual_upload', 'رفع يدوي'),
    ('erp_sync',      'مزامنة ERP'),
    ('ai_generated',  'توليد آلي'),
]

SYNC_STATUS = [
    ('synced',  'متزامن'),
    ('pending', 'في الانتظار'),
    ('error',   'خطأ'),
]

RELATION_TYPES = [
    ('frequently_bought', 'غالباً ما يشترى معه'),
    ('recommended',       'موصى به'),
    ('substitute',        'بديل'),
    ('refill',            'إعادة طلب'),
    ('companion',         'مكمل'),
    ('starter_pack',      'حزمة البداية'),
]

AVAILABILITY_STATUS = [
    ('available',   'متاح'),
    ('limited',     'كميات محدودة'),
    ('unavailable', 'غير متاح'),
]

TEMPERATURE_CHOICES = [
    ('room',         'حفظ بدرجة حرارة الغرفة (أقل من 25°م)'),
    ('cool',         'حفظ في مكان بارد (8-15°م)'),
    ('refrigerated', 'حفظ في الثلاجة (2-8°م)'),
    ('frozen',       'حفظ مجمداً (أقل من -18°م)'),
]


# ── ProductMapping ────────────────────────────────────────────────────────────

class ProductMapping(models.Model):
    """
    Tracks ERP ↔ Catalog mapping and external code lookups.
    softech_id is the primary ERP key (also on Item.softech_id).
    external_code supports future GS1/NDC/ICD codes.
    """
    item          = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='mappings',
    )
    softech_id    = models.CharField(max_length=6, db_index=True)   # denormalized
    external_code = models.CharField(max_length=50, blank=True)     # GS1, NDC, etc.
    barcode       = models.CharField(max_length=30, blank=True, db_index=True)
    is_primary    = models.BooleanField(default=True)
    sync_status   = models.CharField(max_length=10, choices=SYNC_STATUS, default='synced')
    last_synced   = models.DateTimeField(null=True, blank=True)
    notes         = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ('item', 'external_code')
        indexes = [models.Index(fields=['barcode'])]
        verbose_name = 'خريطة منتج'
        verbose_name_plural = 'خرائط المنتجات'
        ordering = ['-is_primary']

    def __str__(self):
        return f'{self.item.softech_id} → {self.external_code or "primary"}'


# ── ProductMedia ──────────────────────────────────────────────────────────────

class ProductMedia(models.Model):
    """
    Multi-media assets for a product.
    Supports: multiple images, 360°, video, PDF, manual.
    Thumbnails auto-generated on save via signal (services.py).
    """
    item        = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='media',
    )
    media_type  = models.CharField(max_length=10, choices=MEDIA_TYPES, default='image')
    file        = models.FileField(upload_to=_media_path)
    thumbnail   = models.ImageField(upload_to=_thumb_path, blank=True)
    alt_text    = models.CharField(max_length=255, blank=True)
    order       = models.PositiveSmallIntegerField(default=0, db_index=True)
    is_primary  = models.BooleanField(default=False, db_index=True)
    source      = models.CharField(max_length=20, choices=MEDIA_SOURCES, default='manual_upload')
    approved    = models.BooleanField(default=False, db_index=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='uploaded_media',
    )
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['order', '-is_primary', '-created_at']
        indexes = [
            models.Index(fields=['item', 'is_primary']),
            models.Index(fields=['item', 'approved', 'order']),
        ]
        verbose_name = 'وسائط منتج'
        verbose_name_plural = 'وسائط المنتجات'

    def __str__(self):
        return f'{self.item.softech_id} [{self.media_type}] #{self.order}'

    @property
    def url(self):
        return self.file.url if self.file else ''

    @property
    def thumb_url(self):
        return self.thumbnail.url if self.thumbnail else self.url


# ── ProductContent ────────────────────────────────────────────────────────────

class ProductContent(models.Model):
    """
    Editorial and marketing content for a product.
    Supports multiple output views: ERP, Customer, E-Commerce.

    MEDICAL DISCLAIMER: Instructions and descriptions are for informational
    purposes only. They do not constitute medical diagnosis or treatment advice.
    """
    item = models.OneToOneField(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='content',
    )

    # ── Display names ─────────────────────────────────────────────────────────
    display_name_ar = models.CharField(max_length=300, blank=True,
                                       verbose_name='الاسم التجاري (عربي)')
    display_name_en = models.CharField(max_length=300, blank=True,
                                       verbose_name='الاسم التجاري (إنجليزي)')

    # ── Descriptions (for customer/e-commerce) ────────────────────────────────
    short_description = models.TextField(
        blank=True,
        verbose_name='وصف مختصر',
        help_text='2-3 جمل — تُستخدم في بطاقات المنتج',
    )
    long_description  = models.TextField(
        blank=True,
        verbose_name='وصف تفصيلي',
        help_text='محتوى كامل — يظهر في صفحة المنتج',
    )

    # ── Adherence / Clinical ──────────────────────────────────────────────────
    instructions = models.TextField(
        blank=True,
        verbose_name='تعليمات الاستخدام',
        help_text='للإرشاد فقط — ليست وصفة طبية',
    )
    storage       = models.TextField(blank=True, verbose_name='شروط التخزين')
    usage         = models.TextField(blank=True, verbose_name='طريقة الاستخدام')
    contraindications = models.TextField(blank=True, verbose_name='موانع الاستخدام')
    benefits      = models.TextField(blank=True, verbose_name='الفوائد والاستخدامات')

    # ── Marketing ─────────────────────────────────────────────────────────────
    marketing_text = models.TextField(blank=True, verbose_name='النص التسويقي')

    # ── Search & Discovery ────────────────────────────────────────────────────
    keywords = models.TextField(
        blank=True,
        verbose_name='الكلمات المفتاحية',
        help_text='مفصولة بفاصلة: بنادول, panadol, باراسيتامول',
    )

    # ── FAQ ───────────────────────────────────────────────────────────────────
    faq = models.JSONField(
        default=list, blank=True,
        verbose_name='الأسئلة الشائعة',
        help_text='[{"q": "السؤال", "a": "الإجابة"}, ...]',
    )

    # ── Adherence icons ───────────────────────────────────────────────────────
    adherence_icons = models.JSONField(
        default=list, blank=True,
        verbose_name='أيقونات الالتزام',
        help_text='[{"icon": "☀️", "label": "صباحاً", "note": "بعد الأكل"}, ...]',
    )

    # ── WhatsApp preview ──────────────────────────────────────────────────────
    whatsapp_preview = models.TextField(
        blank=True,
        verbose_name='معاينة واتساب',
        help_text='نص قصير للمشاركة عبر واتساب',
    )

    last_updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='updated_contents',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'محتوى منتج'
        verbose_name_plural = 'محتويات المنتجات'

    def __str__(self):
        return f'محتوى: {self.item.softech_id} — {self.display_name_ar or self.item.name}'


# ── ProductAttribute ──────────────────────────────────────────────────────────

class ProductAttribute(models.Model):
    """
    Enhanced product attributes — complements the base Item fields.
    Item already has: shape_code (dosage form), origin_code (country),
    supplier_code (manufacturer), barcode, requires_fridge.
    This model adds: strength, flavor, pack_size, color, Rx flag, etc.
    """
    item = models.OneToOneField(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='attributes',
    )

    # ── Clinical / Pharmaceutical ─────────────────────────────────────────────
    strength             = models.CharField(max_length=100, blank=True,
                                             verbose_name='التركيز / القوة',
                                             help_text='مثال: 500mg, 250mg/5ml')
    concentration        = models.CharField(max_length=100, blank=True,
                                             verbose_name='التركيز للسوائل')
    prescription_required = models.BooleanField(
        null=True, blank=True, default=None,
        verbose_name='يحتاج وصفة طبية',
        help_text='True=يحتاج, False=دون وصفة, None=غير محدد',
    )
    special_warnings     = models.TextField(blank=True, verbose_name='تحذيرات خاصة')

    # ── Physical attributes ───────────────────────────────────────────────────
    flavor               = models.CharField(max_length=100, blank=True, verbose_name='النكهة')
    color                = models.CharField(max_length=100, blank=True, verbose_name='اللون')
    size                 = models.CharField(max_length=50, blank=True, verbose_name='الحجم / الوزن')

    # ── Packaging ─────────────────────────────────────────────────────────────
    pack_size_label      = models.CharField(max_length=100, blank=True,
                                             verbose_name='مواصفات العبوة',
                                             help_text='مثال: 30 قرص, 100ml')
    count_per_pack       = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='العدد في العبوة',
    )

    # ── Storage ───────────────────────────────────────────────────────────────
    temperature_storage  = models.CharField(
        max_length=20, choices=TEMPERATURE_CHOICES, blank=True,
        verbose_name='درجة حرارة التخزين',
    )
    shelf_life_months    = models.PositiveSmallIntegerField(
        null=True, blank=True, verbose_name='مدة الصلاحية (شهور)',
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'خصائص منتج'
        verbose_name_plural = 'خصائص المنتجات'

    def __str__(self):
        parts = [self.item.softech_id]
        if self.strength:
            parts.append(self.strength)
        return ' · '.join(parts)


# ── ProductSEO ────────────────────────────────────────────────────────────────

class ProductSEO(models.Model):
    """
    SEO and digital sharing metadata.
    Slug auto-generated from item name + softech_id (see services.py).
    Never expose medical claims in SEO fields.
    """
    item = models.OneToOneField(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='seo',
    )
    slug        = models.SlugField(max_length=250, unique=True, allow_unicode=True)
    title_ar    = models.CharField(max_length=200, blank=True, verbose_name='عنوان الصفحة (عربي)')
    title_en    = models.CharField(max_length=200, blank=True, verbose_name='عنوان الصفحة (إنجليزي)')
    description_ar = models.TextField(blank=True, max_length=320, verbose_name='وصف الصفحة (عربي)')
    description_en = models.TextField(blank=True, max_length=320, verbose_name='وصف الصفحة (إنجليزي)')
    keywords    = models.TextField(blank=True, verbose_name='كلمات مفتاحية')
    canonical   = models.URLField(blank=True, verbose_name='الرابط الأصلي')
    og_image    = models.ImageField(upload_to=_og_path, blank=True, verbose_name='صورة المشاركة')
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SEO المنتج'
        verbose_name_plural = 'SEO المنتجات'

    def __str__(self):
        return f'SEO: {self.slug}'


# ── ProductExperience ─────────────────────────────────────────────────────────

class ProductExperience(models.Model):
    """
    Product usage and engagement analytics.
    Only tracks actual available data (real interactions).
    No conversion rates, no cart abandonment, no visitor traffic.
    Popularity score is computed from weighted interactions.
    """
    item = models.OneToOneField(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='experience',
    )

    # ── Interaction counters ──────────────────────────────────────────────────
    views         = models.PositiveIntegerField(default=0)
    shares        = models.PositiveIntegerField(default=0)
    wishlist_adds = models.PositiveIntegerField(default=0)
    reservations  = models.PositiveIntegerField(default=0)
    refills       = models.PositiveIntegerField(default=0)
    call_requests = models.PositiveIntegerField(default=0)

    # ── Computed score ────────────────────────────────────────────────────────
    popularity_score = models.FloatField(default=0.0, db_index=True)

    last_interaction = models.DateTimeField(null=True, blank=True, db_index=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'تجربة منتج'
        verbose_name_plural = 'تجارب المنتجات'
        ordering = ['-popularity_score']

    def __str__(self):
        return f'تجربة: {self.item.softech_id} (نقاط={self.popularity_score:.1f})'

    def recompute_popularity(self):
        """
        Weighted popularity score from real interactions only.
        reservations × 3 + refills × 2.5 + call_requests × 2
        + wishlist_adds × 1.5 + shares × 1 + views × 0.05
        """
        self.popularity_score = round(
            self.reservations  * 3.0 +
            self.refills       * 2.5 +
            self.call_requests * 2.0 +
            self.wishlist_adds * 1.5 +
            self.shares        * 1.0 +
            self.views         * 0.05,
            4,
        )

    def increment(self, field: str):
        from django.utils import timezone
        if hasattr(self, field):
            setattr(self, field, getattr(self, field) + 1)
            self.last_interaction = timezone.now()
            self.recompute_popularity()
            self.save(update_fields=[field, 'popularity_score', 'last_interaction', 'updated_at'])


# ── ProductRelation ───────────────────────────────────────────────────────────

class ProductRelation(models.Model):
    """
    Curated relationships between items.
    Drives: frequently_bought, substitutes, refills, companion products, starter packs.
    Example: Brilique → Aspirin (companion), Insulin → Needles (companion).
    """
    from_item     = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='relations_from',
    )
    to_item       = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='relations_to',
    )
    relation_type = models.CharField(max_length=20, choices=RELATION_TYPES, db_index=True)
    order         = models.PositiveSmallIntegerField(default=0)
    is_active     = models.BooleanField(default=True, db_index=True)
    added_by      = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('from_item', 'to_item', 'relation_type')
        ordering = ['relation_type', 'order']
        verbose_name = 'علاقة منتج'
        verbose_name_plural = 'علاقات المنتجات'

    def __str__(self):
        return f'{self.from_item.softech_id} →[{self.relation_type}]→ {self.to_item.softech_id}'


# ── ProductAvailabilityCache ──────────────────────────────────────────────────

class ProductAvailabilityCache(models.Model):
    """
    Cached availability status per (item, branch).
    Status is abstracted — NEVER expose raw quantities to customers.
    Populated by sync tasks that read from catalog.ItemStock.
    available = qty > threshold
    limited   = 0 < qty <= threshold
    unavailable = qty <= 0
    """
    item    = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='availability_cache',
    )
    branch  = models.ForeignKey(
        'branches.Branch', on_delete=models.CASCADE,
        related_name='product_availability',
    )
    status  = models.CharField(
        max_length=15, choices=AVAILABILITY_STATUS, default='unavailable', db_index=True,
    )
    last_checked = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('item', 'branch')
        indexes = [
            models.Index(fields=['item', 'status']),
        ]
        verbose_name = 'توافر المنتج'
        verbose_name_plural = 'توافر المنتجات'

    def __str__(self):
        return f'{self.item.softech_id} @ {self.branch_id}: {self.status}'


# ── ProductReview ─────────────────────────────────────────────────────────────

class ProductReview(models.Model):
    """
    PREPARED BUT DISABLED — no endpoints until e-commerce launch.
    Schema is ready; all records have is_active=False by default.
    """
    item          = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='reviews',
    )
    customer_name = models.CharField(max_length=100, blank=True)
    rating        = models.PositiveSmallIntegerField(default=5)  # 1-5
    title         = models.CharField(max_length=200, blank=True)
    body          = models.TextField(blank=True)
    is_approved   = models.BooleanField(default=False)
    is_active     = models.BooleanField(default=False)  # disabled until e-commerce
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'مراجعة منتج (معطل)'
        verbose_name_plural = 'مراجعات المنتجات (معطلة)'
        ordering = ['-created_at']

    def __str__(self):
        return f'مراجعة {self.item.softech_id} — {self.rating}★ (معطل)'
