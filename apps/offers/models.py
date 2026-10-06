"""
apps/offers/models.py — customer-facing offers & promotions.

This is the ONE genuinely-new, money-critical domain in Commerce OS (Phase 3).
Definitions live here; the DETERMINISTIC evaluation lives in engine.py. Execution
(posting a resulting discount to SOFTECH) is a SEPARATE, gated batch that must
reuse the established discount methodology — NOT this app writing to Sybase.

Design rules honored:
  • Financial math is deterministic + testable (rule 2/10) — no fuzzy logic.
  • Every application is auditable (rule 8) → OfferApplication.
  • Targeting reuses catalog (Item/Category/ItemTag) — no parallel product data.
"""
from django.db import models


class Offer(models.Model):
    OFFER_TYPES = [
        ('percent',  'خصم نسبة مئوية'),      # value = % off qualifying subtotal
        ('fixed',    'خصم مبلغ ثابت'),        # value = EGP off qualifying subtotal
        ('bxgy',     'اشترِ X واحصل على Y'),   # buy_qty / get_qty / get_discount_percent
        ('qty_tier', 'خصم متدرّج بالكمية'),   # tiers: [{min_qty, percent}]
        ('gift',     'صنف هدية عند الشراء'),   # buy buy_qty of target → gift_item at get%
        ('spend_threshold', 'مكافأة عند تجاوز مبلغ'),  # basket ≥ min_basket_amount → gift/percent
        ('bundle',   'باقة بسعر ثابت'),        # items[] together = bundle_price
        ('mix_match', 'اختر أي N من مجموعة'),  # any min_qty from target → value% (cheapest N)
    ]
    STATUS = [
        ('draft',  'مسودة'),
        ('active', 'فعّال'),
        ('paused', 'موقوف'),
        ('expired', 'منتهي'),
    ]

    # ── identity ──
    name        = models.CharField(max_length=150, verbose_name='اسم العرض')
    name_ar     = models.CharField(max_length=150, blank=True, verbose_name='الاسم بالعربية')
    description = models.TextField(blank=True, verbose_name='الوصف')
    offer_type  = models.CharField(max_length=16, choices=OFFER_TYPES, db_index=True)
    status      = models.CharField(max_length=10, choices=STATUS, default='draft', db_index=True)

    # Where the discount MAGNITUDE comes from (owner decision, Phase-3 exec design):
    #   item_card → the item's own posdiscp IS the discount (a genuine 1+1 = an item
    #               with posdiscp=100). The offer defines only the STRUCTURE. No
    #               approval — it's already the SOFTECH-authorized POS discount.
    #   offer     → the Offer's own value/get% is the magnitude (may exceed posdiscp);
    #               REQUIRES supervisor approval before the order reaches the cashier.
    AUTH_SOURCES = [('item_card', 'من كارت الصنف (posdiscp)'), ('offer', 'من العرض (يتطلب موافقة)')]
    authorization_source = models.CharField(
        max_length=10, choices=AUTH_SOURCES, default='item_card', db_index=True,
        verbose_name='مصدر قيمة الخصم',
    )
    # BXGY pairing scope:
    #   group_cheapest → buy across the qualifying group; the LESSER-priced unit(s)
    #                    are the promo units (the dominant 1+1 / 1+½ mechanic).
    #   same_item      → buy N of the SAME item, get some of that same item.
    BXGY_SCOPES = [('group_cheapest', 'الأقل سعرًا في المجموعة'), ('same_item', 'نفس الصنف')]
    bxgy_scope = models.CharField(
        max_length=15, choices=BXGY_SCOPES, default='group_cheapest',
        verbose_name='نطاق اشترِ واحصل',
    )

    # ── discount value ──
    value = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        verbose_name='القيمة', help_text='نسبة % (لخصم النسبة) أو مبلغ ثابت',
    )
    max_discount_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        verbose_name='حد أقصى للخصم', help_text='سقف اختياري لخصم النسبة المئوية',
    )
    # BXGY params
    buy_qty = models.PositiveSmallIntegerField(default=0, verbose_name='اشترِ (كمية)')
    get_qty = models.PositiveSmallIntegerField(default=0, verbose_name='احصل على (كمية)')
    get_discount_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=100,
        verbose_name='نسبة خصم المجاني %', help_text='100 = مجاناً',
    )
    # qty-tier: [{"min_qty": 3, "percent": 5}, {"min_qty": 6, "percent": 10}]
    qty_tiers = models.JSONField(default=list, blank=True, verbose_name='شرائح الكمية')

    # gift / spend_threshold: the reward item Z (buy X of target → get gift_item at get%).
    gift_item = models.ForeignKey('catalog.Item', null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='offer_gifts', verbose_name='صنف الهدية')
    # bundle: the target `items` (each qty 1) sold together for this fixed total.
    bundle_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                       verbose_name='سعر الباقة')

    # ── targeting (which lines qualify) — reuses catalog ──
    target_all = models.BooleanField(default=False, verbose_name='كل الأصناف')
    items      = models.ManyToManyField('catalog.Item', blank=True, related_name='offers',
                                        verbose_name='أصناف مضمّنة (يدوي)')
    categories = models.ManyToManyField('catalog.Category', blank=True, related_name='offers')
    tags       = models.ManyToManyField('catalog.ItemTag', blank=True, related_name='offers')
    # SOFTECH classification filters, e.g. {"family_code": ["12"], "store_classif": ["13"]}
    classification_filters = models.JSONField(default=dict, blank=True)

    # ── flexible Odoo-style selector (targeting.py) ──────────────────────────────
    # Compose predicates over ANY whitelisted items-master field (producer/supplier/
    # internal classif/category/origin/shape/effect), booleans (fridge/fast-moving/
    # imported), and price ranges. Example:
    #   {"match": "all", "rules": [
    #      {"field": "producer_code", "op": "in",    "value": ["123"]},
    #      {"field": "pack_price",    "op": "range", "value": [10, 100]},
    #      {"field": "requires_fridge","op": "is_true"}]}
    target_spec = models.JSONField(default=dict, blank=True, verbose_name='محدِّد الأصناف المرن')
    # Manual exclusions — "keep some, leave out some" (removed AFTER the spec resolves).
    excluded_items = models.ManyToManyField('catalog.Item', blank=True,
                                            related_name='offers_excluded',
                                            verbose_name='أصناف مستبعَدة (يدوي)')
    # Stock gate: an item only qualifies when it has available branch stock. The owner
    # can override per-offer (some promos apply even to out-of-stock / reserved items).
    require_stock = models.BooleanField(
        default=True, verbose_name='يشترط توفر رصيد',
        help_text='الافتراضي: لا يُطبَّق العرض على صنف بلا رصيد بالفرع. أوقفه للتجاوز.',
    )

    # ── eligibility (offer-level gates) ──
    segments = models.JSONField(default=list, blank=True, verbose_name='شرائح العملاء',
                                help_text="قائمة مفاتيح الشرائح، مثال: [\"vip\",\"loyal\"] — فارغ = الكل")
    branches = models.ManyToManyField('branches.Branch', blank=True, related_name='offers')
    channels = models.JSONField(default=list, blank=True,
                                help_text='قنوات البيع، مثال: ["cash","home_delivery"] — فارغ = الكل')
    min_basket_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                            verbose_name='أقل إجمالي للسلة')
    min_qty = models.PositiveSmallIntegerField(default=0, verbose_name='أقل كمية مؤهِّلة')

    # ── window ──
    starts_at = models.DateTimeField(null=True, blank=True, verbose_name='يبدأ')
    ends_at   = models.DateTimeField(null=True, blank=True, verbose_name='ينتهي')

    # ── controls ──
    stackable = models.BooleanField(
        default=False, verbose_name='قابل للدمج',
        help_text='إن كان قابلاً للدمج يُجمع مع عروض أخرى قابلة للدمج؛ وإلا فهو حصري.',
    )
    priority = models.IntegerField(default=0, db_index=True, verbose_name='الأولوية',
                                   help_text='الأعلى يفوز عند تعارض العروض الحصرية')
    is_clearance = models.BooleanField(default=False, verbose_name='تصفية (قرب انتهاء صلاحية)')
    requires_approval = models.BooleanField(
        default=False, verbose_name='يتطلب موافقة',
        help_text='يتجاوز حد الهامش — يحتاج اعتماد مشرف قبل التنفيذ (مرحلة لاحقة).',
    )
    max_uses_total        = models.PositiveIntegerField(null=True, blank=True, verbose_name='حد الاستخدام الكلي')
    max_uses_per_customer = models.PositiveIntegerField(null=True, blank=True, verbose_name='حد الاستخدام لكل عميل')

    # ── audit ──
    created_by = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='offers_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-priority', 'name']
        verbose_name = 'عرض'
        verbose_name_plural = 'العروض'
        indexes = [models.Index(fields=['status', 'offer_type'])]

    def __str__(self):
        return self.name_ar or self.name


class MarginConfig(models.Model):
    """
    Singleton (pk=1) margin-protection floor for the offers engine. If applying an
    offer pushes a line's margin below `min_margin_percent`, the plan is flagged
    `requires_approval` (supervisor sign-off at execution) — the discount is never
    silently applied below the floor. `enforce=False` computes margin for display
    but never gates. Deterministic; cost is read from catalog.Item.cost_price.
    """
    min_margin_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=10,
        verbose_name='أقل هامش ربح مسموح %',
        help_text='هامش على صافي البيع = (الصافي − التكلفة) ÷ الصافي × 100',
    )
    enforce = models.BooleanField(
        default=True, verbose_name='تفعيل الحماية',
        help_text='عند الإيقاف يُحسب الهامش للعرض فقط دون اشتراط موافقة.',
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'إعدادات حماية الهامش'
        verbose_name_plural = 'إعدادات حماية الهامش'

    def __str__(self):
        return f'حد الهامش {self.min_margin_percent}%'

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ManualOfferMatch(models.Model):
    """
    Detection/annotation of a HISTORICAL manual promo already in the sales mirror
    (a customer discount cashiers hand-keyed before/outside this module). READ-ONLY
    provenance: it never writes to SOFTECH and never mutates the invoice — it only
    records that a `customers_purchasehistoryline` looks like a promo, so reporting
    is complete and module-vs-manual can be reconciled.

    One row per (purchase, item). Re-running detection updates in place (idempotent).
    """
    PATTERNS = [
        ('exact_offer',       'مطابقة عرض معرّف'),      # matches a defined Offer's magnitude + targeting
        ('bxgy_cheapest',     'نمط 1+1 / 1+½ (الأقل سعرًا)'),  # cheapest-unit fingerprint
        ('unmapped_discount', 'خصم غير مرتبط بعرض'),    # a customer discount with no matching offer
    ]
    CONFIDENCE = [('high', 'عالية'), ('medium', 'متوسطة'), ('low', 'منخفضة')]

    purchase = models.ForeignKey('customers.PurchaseHistory', on_delete=models.CASCADE,
                                 related_name='manual_offer_matches')
    item     = models.ForeignKey('catalog.Item', null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name='manual_offer_matches')
    matched_offer = models.ForeignKey(Offer, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='manual_matches')
    pattern    = models.CharField(max_length=20, choices=PATTERNS, db_index=True)
    confidence = models.CharField(max_length=6, choices=CONFIDENCE, default='low', db_index=True)
    disc_pct        = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # denormalized for fast filtering / reporting
    branch      = models.ForeignKey('branches.Branch', null=True, blank=True, on_delete=models.SET_NULL)
    invoice_date = models.DateTimeField(null=True, blank=True, db_index=True)
    detail      = models.JSONField(default=dict, blank=True)
    detected_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-invoice_date']
        verbose_name = 'كشف عرض يدوي'
        verbose_name_plural = 'كشف العروض اليدوية'
        constraints = [
            models.UniqueConstraint(fields=['purchase', 'item'], name='uniq_manual_match_per_line'),
        ]
        indexes = [models.Index(fields=['pattern', 'confidence'])]

    def __str__(self):
        return f'{self.get_pattern_display()} · {self.disc_pct}% · inv {self.purchase_id}'


class OfferApplication(models.Model):
    """
    Immutable audit of an offer evaluation/application: what discount an offer
    produced, whether it was selected or rejected by conflict resolution, and WHY
    (rule 8). Written at execution time (gated batch); pure evaluation is
    side-effect free and only returns this shape in-memory.
    """
    offer      = models.ForeignKey(Offer, on_delete=models.PROTECT, related_name='applications')
    customer   = models.ForeignKey('customers.Customer', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='offer_applications')
    branch     = models.ForeignKey('branches.Branch', null=True, blank=True, on_delete=models.SET_NULL)
    # Link to the POS order once executed (nullable during pure evaluation).
    pos_order  = models.ForeignKey('pos_orders.SoftechSalesOrder', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='offer_applications')
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    was_applied = models.BooleanField(default=False, db_index=True)
    reason      = models.CharField(max_length=255, blank=True)
    detail      = models.JSONField(default=dict, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'تطبيق عرض'
        verbose_name_plural = 'تطبيقات العروض'

    def __str__(self):
        state = '✓' if self.was_applied else '✗'
        return f'{state} {self.offer} → {self.discount_amount}'
