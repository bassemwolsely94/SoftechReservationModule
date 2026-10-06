from django.db import models
from django.contrib.postgres.indexes import GinIndex

# Stores that hold expired / quarantine stock at HQ branch (code 100).
# These must NEVER appear in any stock balance queries or displays.
EXCLUDED_STORE_CODES = frozenset({'102', '103', '105'})


class Category(models.Model):
    softech_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    name_ar = models.CharField(max_length=255, blank=True)
    # Subcategory hierarchy — platform-native (SOFTECH categories are flat). Admin-
    # managed; NOT synced, so it survives category syncs (update_fields allowlist).
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='subcategories', verbose_name='التصنيف الأب',
    )

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name_ar or self.name


class ItemTag(models.Model):
    """
    Curated, admin-managed free tag for merchandising / POS filtering (e.g.
    'عرض', 'الأكثر مبيعًا', 'موسمي'). Platform-native — NOT from SOFTECH. Kept
    separate from SOFTECH's own classifications (family/medicine_type/store_classif)
    which stay authoritative for pricing/clinical grouping.
    """
    slug = models.SlugField(max_length=50, unique=True, verbose_name='المعرّف')
    name = models.CharField(max_length=60, verbose_name='الاسم')
    name_ar = models.CharField(max_length=60, blank=True, verbose_name='الاسم بالعربية')
    color = models.CharField(max_length=7, blank=True, default='', help_text='#RRGGBB')
    is_active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        'users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='created_item_tags',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'وسم صنف'
        verbose_name_plural = 'وسوم الأصناف'

    def __str__(self):
        return self.name_ar or self.name


class Item(models.Model):
    softech_id = models.CharField(max_length=6, unique=True)          # itemcode varchar(6)
    name = models.CharField(max_length=100, db_index=True)             # itemname
    name_scientific = models.CharField(max_length=100, blank=True)    # itemname_scientific
    barcode = models.CharField(max_length=15, blank=True, db_index=True)  # itembarcode
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    supplier_code = models.CharField(max_length=8, blank=True)          # suppcode → itemssuppliers (main_supp='1')
    supplier_name = models.CharField(max_length=150, blank=True)        # personsdata.personname via supplier_code
    producer_code = models.CharField(max_length=8, blank=True)          # producercode → itemsproducers (main_producer='1')
    producer_name = models.CharField(max_length=150, blank=True)        # personsdata.personname via producer_code
    family_code = models.CharField(max_length=5, blank=True)            # familycode
    family_name = models.CharField(max_length=150, blank=True)          # itemsfamily.familyname
    family_name_ar = models.CharField(max_length=150, blank=True)       # itemsfamily.familynamearabic
    pack_price = models.DecimalField(              # SOFTECH itemsaleprice  — full box/pack retail price
        max_digits=10, decimal_places=3, default=0,
        verbose_name='سعر العبوة',
    )
    unit_price = models.DecimalField(              # SOFTECH unitsaleprice  — price per individual unit/strip
        max_digits=10, decimal_places=3, default=0,
        verbose_name='سعر الوحدة',
    )
    cost_price = models.DecimalField(              # SOFTECH itembuyprice   — purchase/cost price
        max_digits=10, decimal_places=3, default=0,
        verbose_name='سعر الشراء',
    )
    medicine_type = models.CharField(max_length=2, blank=True)         # itemmedicine → itemstree.cdlcode
    medicine_type_name = models.CharField(max_length=100, blank=True)    # itemstree.cdldescr
    medicine_type_name_ar = models.CharField(max_length=100, blank=True) # itemstree.cdldescrar
    # Dosage form — itemshape lookup (e.g. tablet, capsule, syrup, injection)
    shape_code = models.CharField(max_length=5, blank=True)             # items.itemshapecode → itemshape.itemshapecode
    shape_name = models.CharField(max_length=100, blank=True)           # itemshape.itemshapename
    shape_name_ar = models.CharField(max_length=100, blank=True)        # itemshape.shapenamearabic
    # Country of origin — itemsorigin lookup
    origin_code = models.CharField(max_length=5, blank=True)            # items.itemorigincode → itemsorigin.itemorigincode
    origin_name = models.CharField(max_length=100, blank=True)          # itemsorigin.itemoriginname
    origin_name_ar = models.CharField(max_length=100, blank=True)       # itemsorigin.originnamearabic
    is_imported = models.BooleanField(default=False)                    # itemsorigin.importedorigin='1'
    # Primary therapeutic indication / disease — itemseffect lookup
    effect_code = models.CharField(max_length=5, blank=True)            # items.itemeffectcode → itemseffect
    effect_name = models.CharField(max_length=100, blank=True)          # itemseffect.itemeffectname
    effect_name_ar = models.CharField(max_length=100, blank=True)       # itemseffect.effectnamearabic
    # Secondary therapeutic indication — itemseffect2 lookup
    effect_code2 = models.CharField(max_length=5, blank=True)           # items.itemeffectcode2 → itemseffect2
    effect_name2 = models.CharField(max_length=100, blank=True)         # itemseffect2.itemeffectname2
    effect_name2_ar = models.CharField(max_length=100, blank=True)      # itemseffect2.effectnamearabic2
    # Pack sub-unit type — itemsunits lookup (e.g. strip, vial, ampoule, sachet)
    unit_code = models.CharField(max_length=3, blank=True)              # items.unitcode → itemsunits.unitcode
    unit_name = models.CharField(max_length=50, blank=True)             # itemsunits.unitname
    # Active ingredients — comma-separated ainame from activeingredients via itemsai junction
    active_ingredients = models.TextField(
        blank=True,
        verbose_name='المواد الفعالة',
        help_text='itemsai → activeingredients.ainame — comma-separated active ingredient names',
    )
    phcode = models.CharField(max_length=20, null=True, blank=True, db_index=True)  # ATC/phcode (legacy)
    requires_fridge = models.BooleanField(default=False)               # fridgeitem='1'
    comment = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    # SOFTECH items.itemnomoreuse = '1' → discontinued ("امر التوريد" in the
    # manual pivot). Such items are synced with is_active=False but kept for
    # purchasing visibility (shown flagged). See sync filter in sybase_queries.
    no_more_use = models.BooleanField(
        default=False, db_index=True,
        verbose_name='امر التوريد (موقوف/غير مستخدم)',
        help_text="SOFTECH items.itemnomoreuse='1' — discontinued / order-only item.",
    )
    # SOFTECH items.itemarchive = 1 → archived. Distinct from no_more_use. Now
    # SYNCED (the itemarchive=0 filter was removed) and synced with is_active=False.
    item_archive = models.BooleanField(
        default=False, db_index=True,
        verbose_name='مؤرشف',
        help_text="SOFTECH items.itemarchive = 1 — archived item.",
    )
    # ── Market shortage flag (نواقص السوق) ────────────────────────────────────
    # Sticky, human-confirmed flag: this item is in a market/supply shortage — we
    # can't source it, or suppliers only give a limited quota below demand. Set by
    # confirming an auto-detected candidate OR by adding a known quota item manually.
    # It is NEVER auto-cleared (a quota item may briefly have stock); a human clears it.
    in_shortage = models.BooleanField(
        default=False, db_index=True,
        verbose_name='في نقص بالسوق',
        help_text='مؤكَّد يدويًا: صنف يصعب توريده من الموردين أو يأتي بكمية محدودة (كوتة).',
    )
    shortage_source = models.CharField(
        max_length=10, blank=True, default='',
        verbose_name='مصدر التحديد', help_text="'auto' (candidate confirmed) | 'manual' (added by hand).",
    )
    shortage_note = models.CharField(
        max_length=300, blank=True, default='', verbose_name='ملاحظة النقص',
        help_text='e.g. كوتة / لا يوجد بالموردين / بديل مطلوب.',
    )
    shortage_flagged_at = models.DateTimeField(
        null=True, blank=True, verbose_name='تاريخ التحديد',
    )
    # ── SOFTECH writeback state (items.itemmodified = صنف نواقص, itemcode_alt2 = تحذير) ──
    # in_shortage is the DESIRED state; these track whether SOFTECH reflects it yet.
    # False → local change not pushed (SOFTECH offline / error) → retry job picks it up.
    shortage_softech_synced = models.BooleanField(
        default=True, db_index=True, verbose_name='مُتزامن مع سوفتك',
    )
    shortage_softech_synced_at = models.DateTimeField(null=True, blank=True,
                                                      verbose_name='آخر مزامنة سوفتك')
    shortage_softech_error = models.CharField(max_length=300, blank=True, default='',
                                              verbose_name='خطأ مزامنة سوفتك')
    # True when THIS module set أوامر التوريد = موقوف (items.itemnomoreuse='1') because
    # the item was dismissed as يُطلب عند الحاجة / obsolete — so retrieve can restore it.
    shortage_supply_suspended = models.BooleanField(
        default=False, verbose_name='أوقفنا التوريد (موقوف)',
    )
    shortage_confirmed_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='confirmed_market_shortages', verbose_name='أكَّده',
    )
    # ── Dismissal (move an item OUT of the candidate list, with a reason) ──────
    # So the same non-shortage item doesn't resurface every run. Dismissed items are
    # hidden from candidates but fully retrievable, and re-surface automatically only
    # if they later show a strong new shortage signal (re-entered).
    DISMISS_REASONS = [
        ('variant',        'مقاس/شكل بديل لمنتج متاح'),   # size/variant of an available product
        ('on_request',     'يُطلب عند الحاجة'),            # brought only upon request
        ('obsolete',       'غير متوفر بالسوق المصري'),      # obsolete in the Egyptian market
        ('not_shortage',   'ليس ناقصًا (موقوف/موسمي)'),    # stopped/seasonal — not a genuine shortage
        ('false_positive', 'اكتشاف خاطئ — ليس ناقصًا'),    # detector error → carries NO state in the export
        ('other',          'أخرى'),
    ]
    shortage_dismissed = models.BooleanField(
        default=False, db_index=True, verbose_name='مُستبعد من النواقص',
        help_text='مُستبعد من قائمة المرشحين مع حفظ السبب — قابل للاسترجاع.',
    )
    shortage_dismiss_reason = models.CharField(
        max_length=15, blank=True, default='', choices=DISMISS_REASONS,
        verbose_name='سبب الاستبعاد',
    )
    shortage_dismiss_note = models.CharField(max_length=300, blank=True, default='',
                                             verbose_name='ملاحظة الاستبعاد')
    shortage_dismissed_at = models.DateTimeField(null=True, blank=True,
                                                 verbose_name='تاريخ الاستبعاد')
    shortage_dismissed_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='dismissed_market_shortages', verbose_name='استبعده',
    )
    # For reason='variant': the available product(s) that cover this item's demand.
    # Many-to-many: a variant may map to one or two matching products, and a single
    # available product may be the match for many variant items.
    shortage_matching_items = models.ManyToManyField(
        'self', symmetrical=False, blank=True,
        related_name='covers_shortage_variants', verbose_name='المنتجات البديلة المتاحة',
    )

    # ── Phantom substitution (مبيعات وهمية) ───────────────────────────────────
    # Contract patients sell their prescribed drug back; SOFTECH records it as a
    # purchase (doccode 10) from an internal buy-back "supplier" account + an
    # immediate contract-channel sale — the unit is never sourced from a real
    # distributor. Such "sales" are NOT genuine demand, so the demand sheet must
    # not order (or must heavily reduce) them. Auto-detected each engine run:
    # phantom_ratio = buyback_qty / sold_qty over a rolling window; flagged at a
    # configurable threshold (default 0.50). Human-reviewable (phantom_override).
    PHANTOM_OVERRIDE_CHOICES = [
        ('',         'تلقائي (بدون مراجعة)'),   # auto only
        ('confirmed', 'مؤكَّد يدويًا'),           # human confirmed it IS phantom (sticky)
        ('excluded',  'ليست مبيعات وهمية'),       # human says NOT phantom → suppress flag
    ]
    is_phantom_substitution = models.BooleanField(
        default=False, db_index=True, verbose_name='مبيعات وهمية',
        help_text='معظم مبيعاته يُعاد شراؤها من العميل/المريض (تعاقد) لا من الموردين — لا يُطلب أو تُقلَّل كميته.',
    )
    phantom_ratio = models.FloatField(
        default=0.0, verbose_name='نسبة الوهمية',
        help_text='buyback_qty / sold_qty على مدى نافذة التحديد (12 شهر) — أساس التحديد.',
    )
    phantom_contract_ratio = models.FloatField(
        default=0.0, verbose_name='نسبة قناة التعاقد',
        help_text='حصة مبيعات قناة التعاقد/التأمين — سياقية فقط، ليست شرط التحديد.',
    )
    phantom_order_pct = models.FloatField(
        default=1.0, verbose_name='النسبة الموصى بطلبها',
        help_text='1 − النسبة الوهمية (مرجَّحة زمنيًا) — الجزء الحقيقي المطلوب توريده من الموردين.',
    )
    phantom_buyback_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0,
                                              verbose_name='كمية إعادة الشراء (نافذة)')
    phantom_sold_qty = models.DecimalField(max_digits=12, decimal_places=3, default=0,
                                           verbose_name='كمية المبيعات (نافذة)')
    phantom_genuine_need = models.DecimalField(max_digits=12, decimal_places=3, default=0,
                                               verbose_name='الطلب الحقيقي (مبيعات − إعادة شراء)')
    phantom_detected_at = models.DateTimeField(null=True, blank=True,
                                               verbose_name='آخر فحص وهمية')
    phantom_source = models.CharField(max_length=10, blank=True, default='',
                                      verbose_name='مصدر التحديد',
                                      help_text="'auto' | 'manual'.")
    phantom_override = models.CharField(
        max_length=10, blank=True, default='', choices=PHANTOM_OVERRIDE_CHOICES,
        verbose_name='قرار المراجعة',
    )
    phantom_override_note = models.CharField(max_length=300, blank=True, default='',
                                             verbose_name='ملاحظة المراجعة')
    phantom_reviewed_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_phantom_items', verbose_name='راجعه',
    )
    phantom_reviewed_at = models.DateTimeField(null=True, blank=True,
                                               verbose_name='تاريخ المراجعة')

    # ── Cash & inventory optimization (docs/architecture/22) ──────────────────
    # Strategic hold: a manual flag we set on items deliberately kept despite ~no
    # sales (oncology / fridge biologics for a known contract patient). Excludes
    # the item from dead-stock flagging so it never nags.
    strategic_hold = models.BooleanField(
        default=False, db_index=True, verbose_name='احتفاظ استراتيجي',
        help_text='مُحتفَظ به عمدًا رغم قلة البيع (مريض تعاقد/أورام) — يُستثنى من رصد الركود.',
    )
    # ── Demand-spike over-purchase (📈) — behavioral "doctor-target" burst ──────
    # recent = qty_90d/3 ; prior = (qty_365d−qty_90d)/9. STRONG = new-burst (prior<0.15)
    # OR recent/prior ≥ 10× → cap-eligible; WATCH = 6–10× → monitor only. Computed
    # each engine run from the run's metrics. The order cap is REVIEW-GATED
    # (spike_confirmed) + opt-in, so genuine new-product ramps aren't starved.
    SPIKE_TIER_CHOICES = [('', '—'), ('strong', 'ذروة قوية'), ('watch', 'ذروة للمراقبة')]
    is_spike = models.BooleanField(
        default=False, db_index=True, verbose_name='ذروة طلب غير مؤكدة',
        help_text='قفزة طلب حديثة قد لا تدوم (نمط الوصفة المستهدفة) — راجِع قبل الشراء بكمية كبيرة.',
    )
    spike_tier = models.CharField(max_length=8, blank=True, default='',
                                  choices=SPIKE_TIER_CHOICES, verbose_name='درجة الذروة')
    spike_ratio = models.FloatField(default=0.0, verbose_name='مضاعف الذروة',
                                    help_text='الطلب الربع أخير ÷ طلب الأشهر التسعة السابقة.')
    spike_recent = models.FloatField(default=0.0, verbose_name='المعدل الحديث (شهري)')
    spike_prior = models.FloatField(default=0.0, verbose_name='المعدل السابق (شهري)')
    spike_confirmed = models.BooleanField(
        default=False, verbose_name='مؤكَّدة (طبّق التقليل)',
        help_text='مراجعة بشرية: ذروة غير مستدامة فعلاً — يُسمح بتقليل الكمية عند التفعيل.',
    )
    spike_detected_at = models.DateTimeField(null=True, blank=True,
                                             verbose_name='آخر رصد ذروة')
    spike_reviewed_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_spike_items', verbose_name='راجع الذروة',
    )
    spike_reviewed_at = models.DateTimeField(null=True, blank=True)

    is_stockable = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name='قابل للتخزين (Stockable)',
        help_text=(
            'Synced from SOFTECH items.itemtrans. '
            '1 = stockable (included in demand calculations). '
            '0 = non-stockable (excluded from all demand, purchasing, and inventory calculations). '
            'Only 38 items are non-stockable out of ~37,500.'
        ),
    )
    batch_required = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name='اختيار الباتش إلزامي (Batch required)',
        help_text=(
            'Synced from SOFTECH items.itempartno («رقم القطعة أو الباتش»). '
            '1 = batch/expiry selection is MANDATORY at POS before dispensing (not merely "batches exist"). '
            '0 = optional. Sparse: only ~9 items master-wide carry it.'
        ),
    )

    # ── Channel & operational flags (synced from SOFTECH items) ───────────────
    is_fast_moving = models.BooleanField(
        default=False, db_index=True,
        verbose_name='سريع التداول (FMI)',
        help_text='SOFTECH items.fmi. Fast Moving Item flag — high sales velocity.',
    )
    insurance_type = models.CharField(
        max_length=1, blank=True, db_index=True,
        verbose_name='نوع التأمين الصحي',
        help_text=(
            'SOFTECH items.hi_typecode. '
            '0=غير خاضع للتأمين (not covered), 1=طلبية (Talbia), '
            '2=TPA, 3=تكافل (Takaful), 4=Other.'
        ),
    )
    item_level = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='مستوى الصنف',
        help_text=(
            'SOFTECH items.itemslevel. '
            'Distribution: 0=standard (50,338 items), 1=special (1,014 items). '
            'Exact business meaning needs user confirmation — sample items with level=1 '
            'include CENTRUM SILVER, ADVIL, ROGAINE, ASHWAGANDHA, BIO SOFT (mostly imported '
            'brand-name items). NOT narcotics. Possible meaning: imported/branded/special tier. '
            'NOTE: تصنيف جدول مخدرات (Narcotics Schedule) shown in the SOFTECH UI maps to a '
            'DIFFERENT column not yet identified. TODO: confirm with business team.'
        ),
    )
    has_points = models.BooleanField(
        default=False,
        verbose_name='مؤهل لنظام النقاط',
        help_text='SOFTECH items.itempointsys. 1 = eligible for points program.',
    )
    pack_qty = models.PositiveSmallIntegerField(
        default=1,
        verbose_name='كمية العبوة',
        help_text='SOFTECH items.packqty — units (strips/vials/ampoules) per pack.',
    )
    # Branch / supplier / customer transaction permissions
    # Values: 0=full ops, 1=dispatch-sell-buy only, 2=return only, 3=full stop
    branch_trans = models.CharField(
        max_length=1, blank=True,
        verbose_name='صلاحية — الفروع',
        help_text=(
            'SOFTECH items.itemtrans1. Branch transfer permissions. '
            '0=صرف+ارتجاع, 1=صرف فقط, 2=ارتجاع فقط, 3=إيقاف كامل.'
        ),
    )
    supplier_trans = models.CharField(
        max_length=1, blank=True,
        verbose_name='صلاحية — الموردين',
        help_text=(
            'SOFTECH items.itemtrans2. Supplier purchase permissions. '
            '0=شراء+ارتجاع, 1=شراء فقط, 2=ارتجاع فقط, 3=إيقاف كامل.'
        ),
    )
    customer_trans = models.CharField(
        max_length=1, blank=True,
        verbose_name='صلاحية — العملاء',
        help_text=(
            'SOFTECH items.itemtrans3. Customer sale permissions. '
            '0=بيع+ارتجاع, 1=بيع فقط, 2=ارتجاع فقط, 3=إيقاف كامل.'
        ),
    )
    nosale_classif = models.CharField(
        max_length=5, blank=True,
        verbose_name='تصنيف منع الصرف',
        help_text=(
            'SOFTECH items.itemnosaleclassif. Contract/dispensing restriction. '
            '10=normal (no restriction), 20=#2, 30=#3, 31=#4.'
        ),
    )
    # Contract discount classification — SOFTECH items.itemstoreclassif
    # FK → custdiscpclassif.custdiscpcode  (see docs/softech_items_reference.md)
    # Used by SOFTECH to group items into discount tiers for contract pricing.
    # Examples: '10'=Med Local, '13'=Med Imported/Egydrug 12%, '15'=Med Imported 18%,
    #   '84'=SERVICES, '87'=Children Supplies, '88'=Baby formula, '90'=Imported Devices.
    store_classif = models.CharField(
        max_length=5, blank=True, db_index=True,
        verbose_name='تصنيف خصم التعاقدات',
        help_text=(
            'SOFTECH items.itemstoreclassif → custdiscpclassif.custdiscpcode. '
            'Contract discount classification tier. Used to determine which discount '
            'rate applies to this item under contract pricing. '
            'Common values: 10=Med Local, 11=Med Local Under License 20%, '
            '12=Med Local 25%, 13=Med Imported/Egydrug 12%, 14=Med Imported/Agent 15%, '
            '15=Med Imported 18%, 25=Med Local 25% Shortage, 84=SERVICES, '
            '87=Children Supplies, 88=Baby Formula, 89=Baby Care, 90=Imported Devices. '
            'NULL/empty = not classified.'
        ),
    )
    store_classif_name = models.CharField(
        max_length=60, blank=True,
        verbose_name='اسم تصنيف التعاقدات',
        help_text='Resolved name from custdiscpclassif.custdiscpdescr.',
    )

    # ── Extended price fields (synced from SOFTECH items) ────────────────────
    pack_price_tax = models.DecimalField(  # itemsaleprice_tax — retail price incl. tax
        max_digits=10, decimal_places=3, default=0,
        verbose_name='سعر العبوة شامل الضريبة',
        help_text='SOFTECH items.itemsaleprice_tax. Must be updated whenever pack_price changes.',
    )
    sale_tax_pct = models.DecimalField(    # itemsalestaxp — tax rate % on this item
        max_digits=5, decimal_places=2, default=0,
        verbose_name='نسبة الضريبة %',
        help_text='SOFTECH items.itemsalestaxp. Used to auto-compute pack_price_tax on approval.',
    )

    # ── Discount fields (synced from SOFTECH items) ───────────────────────────
    pharmacy_discp = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name='خصم الصيدلية %',
        help_text='SOFTECH items.pharmacydiscp — wholesale/pharmacy customer discount %.',
    )
    additional_discp = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name='خصم إضافي %',
        help_text='SOFTECH items.additionaldiscp — secondary discount tier %.',
    )
    special_discp = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name='خصم خاص %',
        help_text='SOFTECH items.specialdiscp — special event discount %.',
    )
    pos_discp = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name='خصم POS %',
        help_text='SOFTECH items.posdiscp — retail POS discount %. Currently 10% on 87.5% of items.',
    )

    # ── Product-intelligence overlay (PG-only, derived — NOT synced from SOFTECH) ──
    # Normalized, Arabic-folded haystack (code + barcode + AR/EN + scientific name)
    # for fast universal search via a pg_trgm GIN index. Rebuilt at item sync and by
    # the `backfill_search_name` command. NOT in the sync update_fields allowlist as
    # a SOFTECH column — it's computed from the synced fields, never written back.
    search_name = models.TextField(
        blank=True, default='',
        verbose_name='اسم البحث (منسّق)',
        help_text='Derived normalized search haystack — powers universal search. Do not edit by hand.',
    )
    # Curated merchandising tags (platform-native, admin-managed). Not from SOFTECH.
    tags = models.ManyToManyField(
        'ItemTag', blank=True, related_name='items', verbose_name='الوسوم',
    )

    last_synced = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            GinIndex(
                name='catalog_item_searchname_trgm',
                fields=['search_name'],
                opclasses=['gin_trgm_ops'],
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        if self.name_scientific:
            return f"{self.name} ({self.name_scientific})"
        return self.name


class ItemStock(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='stock_levels')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE)
    softech_store_code = models.CharField(max_length=3, blank=True)   # storecode
    quantity_on_hand = models.DecimalField(max_digits=10, decimal_places=3, default=0)  # nowqty
    monthly_qty = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    on_order_qty = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    last_synced = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('item', 'branch', 'softech_store_code')

    def __str__(self):
        return f"{self.item.name} @ {self.branch.name}: {self.quantity_on_hand}"

    @property
    def stock_status(self):
        if self.quantity_on_hand <= 0:
            return 'out_of_stock'
        if self.quantity_on_hand < 5:
            return 'low_stock'
        return 'in_stock'

    @property
    def stock_status_label(self):
        return {
            'out_of_stock': 'نفد من المخزن',
            'low_stock': 'مخزون منخفض',
            'in_stock': 'متاح',
        }.get(self.stock_status, 'غير معروف')


class ItemBarcode(models.Model):
    """
    Additional / international barcodes for an item.
    Synced from SOFTECHDB9.dbo.itembarcodes — one item can have many barcodes.
    The primary barcode lives on Item.barcode (synced from items.itembarcode).
    This table holds all secondary / EAN-13 / GS1 barcodes used by barcode scanners.
    """
    item      = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='barcodes')
    barcode   = models.CharField(max_length=50, db_index=True)
    is_active = models.BooleanField(default=True)   # False when obsolete='1' in SOFTECH

    class Meta:
        unique_together     = [('item', 'barcode')]
        verbose_name        = 'باركود إضافي'
        verbose_name_plural = 'باركودات الأصناف'

    def __str__(self):
        flag = '✓' if self.is_active else '✗'
        return f'{self.item.softech_id} | {self.barcode} {flag}'


class ChronicMedication(models.Model):
    """
    Persisted tagging of catalog items as chronic medications.
    Populated by: python manage.py tag_chronic_items
    Detection logic lives in apps/catalog/chronic.py.
    """
    item = models.OneToOneField(
        Item, on_delete=models.CASCADE,
        related_name='chronic_tag',
        verbose_name='الصنف',
    )
    category_label = models.CharField(
        max_length=100, blank=True,
        verbose_name='تصنيف المرض المزمن',
        help_text='مثل: ضغط الدم، السكر، الغدة الدرقية ...',
    )
    is_active = models.BooleanField(default=True)
    tagged_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'دواء مزمن'
        verbose_name_plural = 'الأدوية المزمنة'
        ordering = ['item__name']

    def __str__(self):
        return f'{self.item.name} [{self.category_label}]'


# ── Catalog Variant System ─────────────────────────────────────────────────────
#
# Virtual binding layer on top of SOFTECH.
# SOFTECH itemcode is VARCHAR(6) and IMMUTABLE — we NEVER touch it.
# All grouping is PostgreSQL-side only.

class CatalogVariantGroup(models.Model):
    """
    Groups items that are variants of the same product
    (different strengths, forms, pack sizes) without touching SOFTECH.
    Example: "Panadol 500mg", "Panadol 1000mg", "Panadol Syrup" → one group.
    """
    name    = models.CharField(max_length=255, verbose_name='الاسم (إنجليزي)')
    name_ar = models.CharField(max_length=255, blank=True, verbose_name='الاسم (عربي)')
    description = models.TextField(blank=True, verbose_name='وصف')

    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='variant_groups_created',
        verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'مجموعة متغيرات'
        verbose_name_plural = 'مجموعات المتغيرات'

    def __str__(self):
        return self.name_ar or self.name

    @property
    def member_count(self):
        return self.members.count()


class VariantMember(models.Model):
    """
    Maps one catalog Item to a CatalogVariantGroup.
    Each item can belong to at most one group (OneToOne on item).
    """
    group = models.ForeignKey(
        CatalogVariantGroup,
        on_delete=models.CASCADE,
        related_name='members',
        verbose_name='المجموعة',
    )
    item = models.OneToOneField(
        Item,
        on_delete=models.CASCADE,
        related_name='variant_membership',
        verbose_name='الصنف',
    )
    variant_label = models.CharField(
        max_length=100, blank=True,
        verbose_name='تسمية المتغير',
        help_text='مثل: 500mg، شراب، 10 أقراص',
    )
    sort_order = models.PositiveSmallIntegerField(default=0, verbose_name='الترتيب')

    class Meta:
        ordering = ['sort_order', 'variant_label']
        verbose_name = 'متغير'
        verbose_name_plural = 'المتغيرات'

    def __str__(self):
        return f'{self.item.name} [{self.variant_label}] → {self.group}'


# ── Product Bundles ────────────────────────────────────────────────────────────

class ProductBundle(models.Model):
    """
    A curated bundle of items sold or promoted together.
    Discount applies to the bundle total.
    """
    DISCOUNT_TYPE_CHOICES = [
        ('pct',   'خصم نسبة مئوية'),
        ('fixed', 'خصم ثابت'),
        ('none',  'بدون خصم'),
    ]

    name        = models.CharField(max_length=255, verbose_name='اسم الباقة (إنجليزي)')
    name_ar     = models.CharField(max_length=255, blank=True, verbose_name='اسم الباقة (عربي)')
    description = models.TextField(blank=True, verbose_name='وصف')
    is_active   = models.BooleanField(default=True, db_index=True, verbose_name='نشط')

    discount_type  = models.CharField(
        max_length=10, choices=DISCOUNT_TYPE_CHOICES, default='none',
        verbose_name='نوع الخصم',
    )
    discount_value = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        verbose_name='قيمة الخصم',
        help_text='نسبة مئوية (0-100) أو مبلغ ثابت حسب نوع الخصم',
    )

    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='bundles_created',
        verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'باقة منتجات'
        verbose_name_plural = 'باقات المنتجات'

    def __str__(self):
        return self.name_ar or self.name


class BundleItem(models.Model):
    """One item line within a ProductBundle."""
    bundle   = models.ForeignKey(
        ProductBundle,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='الباقة',
    )
    item     = models.ForeignKey(
        Item,
        on_delete=models.CASCADE,
        related_name='bundle_memberships',
        verbose_name='الصنف',
    )
    quantity = models.DecimalField(
        max_digits=8, decimal_places=2, default=1,
        verbose_name='الكمية',
    )

    class Meta:
        unique_together = ('bundle', 'item')
        verbose_name = 'صنف في الباقة'
        verbose_name_plural = 'أصناف الباقة'

    def __str__(self):
        return f'{self.item.name} × {self.quantity}'


class ItemAlias(models.Model):
    """
    Learned mapping: a raw (OCR / voice / typed) product name → a catalog Item.

    Grows every time a human confirms a match anywhere (shortage lists, supplier
    invoices, imports), so a name we've seen before resolves instantly with full
    confidence instead of being re-fuzzed from scratch. This is the cross-module
    "gets smarter every time" corpus that feeds ``matching.find_best_matches``.

    ``vendor_code`` (SOFTECH personcode, ptcode='20') optionally scopes a single
    supplier's private spelling of an item; blank = a global alias. It's a plain
    field (not an FK) so the catalog app stays dependency-free.
    """
    SOURCES = (
        ('shortage', 'قائمة نواقص'),
        ('invoice',  'فاتورة مورد'),
        ('import',   'استيراد'),
        ('manual',   'يدوي'),
        ('whatsapp', 'طلبات واتساب'),
        ('availability', 'إتاحة مورد'),
        ('pos_rx_ocr', 'روشتة POS'),
    )
    normalized  = models.CharField(max_length=300, db_index=True,
                                   verbose_name='الاسم المُعيَّر')
    item        = models.ForeignKey(Item, on_delete=models.CASCADE,
                                    related_name='aliases', verbose_name='الصنف')
    vendor_code = models.CharField(max_length=8, blank=True, db_index=True,
                                   verbose_name='كود المورد (اختياري)')
    source      = models.CharField(max_length=20, choices=SOURCES, default='manual',
                                   verbose_name='المصدر')
    use_count   = models.PositiveIntegerField(default=1, verbose_name='عدد التأكيدات')
    sample_raw  = models.CharField(max_length=300, blank=True,
                                   verbose_name='آخر نص خام')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'اسم مُتعلَّم للصنف'
        verbose_name_plural = 'الأسماء المُتعلَّمة'
        unique_together     = ('normalized', 'vendor_code', 'item')
        indexes = [
            models.Index(fields=['normalized', 'vendor_code'], name='itemalias_lookup_idx'),
            # close-spelling lookups (apps/shortage/learning — trigram similarity)
            GinIndex(fields=['normalized'], name='itemalias_norm_trgm', opclasses=['gin_trgm_ops']),
        ]
        ordering = ['-use_count']

    def __str__(self):
        scope = f'[{self.vendor_code}] ' if self.vendor_code else ''
        return f'{scope}{self.normalized} → {self.item.name} (×{self.use_count})'


class ItemAliasRejection(models.Model):
    """Negative learning: a person REPLACED the machine's suggestion ``item`` for this
    spelling. Each rejection pushes that item down for the spelling (and close spellings)
    next time, and weakens any alias that pointed there; a later confirmation of the same
    item forgives one rejection. Fed by apps/shortage/learning.record_rejection."""
    normalized  = models.CharField(max_length=300, db_index=True)
    item        = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='alias_rejections')
    vendor_code = models.CharField(max_length=8, blank=True, db_index=True)
    count       = models.PositiveIntegerField(default=1)
    sample_raw  = models.CharField(max_length=300, blank=True)
    source      = models.CharField(max_length=20, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'مطابقة مرفوضة'
        verbose_name_plural = 'المطابقات المرفوضة'
        unique_together     = ('normalized', 'vendor_code', 'item')

    def __str__(self):
        return f'{self.normalized} ✗ {self.item_id} (×{self.count})'


class ItemAliasGroup(models.Model):
    """Learned ONE-TO-MANY mapping: a spelling that stands for several catalog items
    ("بيبيلاك 1....2....3" → BEBELAC (1), (2), (3)). Learned when a person confirms a line
    as several items; next time the same (or a close) spelling is split into those items
    as a suggestion. ``item_ids`` keeps the confirmed order; ``items_key`` = sorted ids."""
    normalized  = models.CharField(max_length=300, db_index=True)
    vendor_code = models.CharField(max_length=8, blank=True, db_index=True)
    item_ids    = models.JSONField(default=list)
    items_key   = models.CharField(max_length=300)
    use_count   = models.PositiveIntegerField(default=1)
    source      = models.CharField(max_length=20, blank=True)
    sample_raw  = models.CharField(max_length=300, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'اسم مُتعلَّم لعدة أصناف'
        verbose_name_plural = 'الأسماء المُتعلَّمة لعدة أصناف'
        unique_together     = ('normalized', 'vendor_code', 'items_key')
        ordering            = ['-use_count']

    def __str__(self):
        return f'{self.normalized} → {self.item_ids} (×{self.use_count})'


class ItemSupplierLink(models.Model):
    """Nightly mirror of SOFTECH ``itemssuppliers`` — which supplier carries which item,
    the supplier's OWN product code for it (``suppitemcode``, often blank) and the main
    supplier flag. Read-only copy (apps/catalog/supplier_links.py), so supplier codes and
    "this supplier carries it" work while SOFTECH is unreachable. SOFTECH stays the truth:
    writes still go through apps/invoices/supplier_items.inject_mapping only."""
    item_code      = models.CharField(max_length=10, db_index=True, verbose_name='كود الصنف')
    item           = models.ForeignKey(Item, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='supplier_links', verbose_name='الصنف')
    supp_code      = models.CharField(max_length=10, db_index=True, verbose_name='كود المورد')
    supp_item_code = models.CharField(max_length=60, blank=True, db_index=True,
                                      verbose_name='كود الصنف لدى المورد')
    is_main        = models.BooleanField(default=False, verbose_name='المورد الأساسي')
    synced_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'صنف لدى مورد (SOFTECH)'
        verbose_name_plural = 'أصناف الموردين (SOFTECH)'
        unique_together     = ('item_code', 'supp_code')
        indexes = [models.Index(fields=['supp_code', 'supp_item_code'], name='isl_supp_code_idx')]

    def __str__(self):
        return f'{self.supp_code}:{self.supp_item_code or "—"} → {self.item_code}'
