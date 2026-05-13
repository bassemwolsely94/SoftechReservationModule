"""
apps.chronic — Chronic Medication Classifier
=============================================
5-layer model system:
  1. MedicationTag     — project-wide reusable labels (diagnosis, disease, ICD-10, etc.)
  2. ActiveIngredient  — drug substance master (the level above brand/SKU)
  3. IngredientTag     — through model linking tags to ingredients
  4. ItemIngredientMap — maps catalog.Item → ActiveIngredient (many-to-many, supports combos)
  5. FollowUpProtocol  — when/how to follow up per ingredient (multiple per ingredient)

NOTE: stktransm.phcode = customer personcode (e.g. 04HD1006) — NOT a drug code.
Item classification is done manually per item by linking to an ActiveIngredient.
"""

from django.db import models


# ─────────────────────────────────────────────────────────────────────────────
# Shared choice lists
# ─────────────────────────────────────────────────────────────────────────────

CHRONIC_CLASS_CHOICES = [
    ('diabetes',          'السكري'),
    ('hypertension',      'ضغط الدم'),
    ('cardiovascular',    'أمراض القلب والأوعية'),
    ('thyroid',           'الغدة الدرقية'),
    ('asthma',            'الربو وأمراض الجهاز التنفسي'),
    ('anticoagulant',     'مضادات التخثر'),
    ('epilepsy',          'الصرع'),
    ('parkinson',         'باركنسون'),
    ('depression',        'الاكتئاب والأمراض النفسية'),
    ('immunosuppressant', 'مثبطات المناعة'),
    ('osteoporosis',      'هشاشة العظام'),
    ('renal',             'أمراض الكلى المزمنة'),
    ('oncology',          'الأورام'),
    ('cholesterol',       'ارتفاع الكوليسترول'),
    ('gerd',              'ارتجاع المريء المزمن'),
    ('anemia',            'فقر الدم المزمن'),
    ('other_chronic',     'مزمن - أخرى'),
]

PRIORITY_CHOICES = [
    ('low',     'منخفض'),
    ('normal',  'عادي'),
    ('high',    'مرتفع'),
    ('urgent',  'عاجل'),
    ('chronic', 'مزمن'),
]

TASK_TYPE_CHOICES = [
    ('call',     '📞 اتصال هاتفي'),
    ('whatsapp', '💬 واتساب'),
    ('sms',      '📱 رسالة نصية'),
    ('visit',    '🏥 زيارة'),
]


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — Tag System (project-wide)
# ─────────────────────────────────────────────────────────────────────────────

class MedicationTag(models.Model):
    TAG_TYPES = [
        ('diagnosis',  '🏥 تشخيص'),
        ('disease',    '🩺 مرض مزمن'),
        ('drug_class', '💊 تصنيف دوائي'),
        ('icd10',      '📋 كود ICD-10'),
        ('atc_class',  '🔬 تصنيف ATC'),
        ('custom',     '🏷️ مخصص'),
    ]

    name        = models.CharField(max_length=100, unique=True, verbose_name='الاسم')
    name_ar     = models.CharField(max_length=100, blank=True, verbose_name='الاسم بالعربية')
    tag_type    = models.CharField(max_length=20, choices=TAG_TYPES, verbose_name='نوع التصنيف')
    color       = models.CharField(max_length=7, default='#6B7280', verbose_name='لون الشارة')
    description = models.TextField(blank=True, verbose_name='وصف')
    is_active   = models.BooleanField(default=True, verbose_name='نشط')
    created_by  = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_medication_tags',
        verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'وسم دوائي'
        verbose_name_plural = 'الوسوم الدوائية'
        ordering            = ['tag_type', 'name']

    def __str__(self):
        return f'{self.name} ({self.get_tag_type_display()})'


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — Active Ingredient Master
# ─────────────────────────────────────────────────────────────────────────────

class ActiveIngredient(models.Model):
    # ── Identity ──────────────────────────────────────────────────────────────
    name            = models.CharField(max_length=200, db_index=True, verbose_name='الاسم (إنجليزي)')
    name_ar         = models.CharField(max_length=200, blank=True, verbose_name='الاسم (عربي)')
    name_scientific = models.CharField(max_length=200, blank=True, verbose_name='الاسم العلمي / IUPAC')

    # ── ATC Hierarchy ─────────────────────────────────────────────────────────
    # Full ATC code, e.g. A10BA02
    atc_code        = models.CharField(max_length=20, blank=True, db_index=True, verbose_name='كود ATC')
    # Level 1: A
    atc_level1      = models.CharField(max_length=2,   blank=True, verbose_name='ATC المستوى 1 (كود)')
    atc_level1_name = models.CharField(max_length=150, blank=True, verbose_name='ATC المستوى 1 (اسم)')
    # Level 2: A10
    atc_level2      = models.CharField(max_length=4,   blank=True, verbose_name='ATC المستوى 2 (كود)')
    atc_level2_name = models.CharField(max_length=150, blank=True, verbose_name='ATC المستوى 2 (اسم)')
    # Level 3: A10B
    atc_level3      = models.CharField(max_length=5,   blank=True, verbose_name='ATC المستوى 3 (كود)')
    atc_level3_name = models.CharField(max_length=150, blank=True, verbose_name='ATC المستوى 3 (اسم)')
    # Level 4: A10BA
    atc_level4      = models.CharField(max_length=7,   blank=True, verbose_name='ATC المستوى 4 (كود)')
    atc_level4_name = models.CharField(max_length=150, blank=True, verbose_name='ATC المستوى 4 (اسم)')

    # ── Chronic Classification ─────────────────────────────────────────────────
    is_chronic    = models.BooleanField(default=False, db_index=True, verbose_name='دواء مزمن')
    chronic_class = models.CharField(
        max_length=30, blank=True,
        choices=CHRONIC_CLASS_CHOICES,
        verbose_name='تصنيف المرض المزمن',
    )

    # ── Tags (via through model) ──────────────────────────────────────────────
    tags = models.ManyToManyField(
        MedicationTag,
        through='IngredientTag',
        blank=True,
        verbose_name='الوسوم',
    )

    notes      = models.TextField(blank=True, verbose_name='ملاحظات')
    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_ingredients',
        verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'مادة فعّالة'
        verbose_name_plural = 'المواد الفعّالة'
        ordering            = ['name']

    def __str__(self):
        return self.name_ar or self.name

    @property
    def item_count(self):
        return self.item_maps.count()


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3 — Ingredient ↔ Tag (through model)
# ─────────────────────────────────────────────────────────────────────────────

class IngredientTag(models.Model):
    active_ingredient = models.ForeignKey(
        ActiveIngredient, on_delete=models.CASCADE,
        related_name='ingredient_tags',
        verbose_name='المادة الفعّالة',
    )
    tag = models.ForeignKey(
        MedicationTag, on_delete=models.CASCADE,
        related_name='ingredient_tags',
        verbose_name='الوسم',
    )
    added_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='أضيف بواسطة',
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('active_ingredient', 'tag')
        verbose_name        = 'وسم على مادة فعّالة'
        verbose_name_plural = 'وسوم المواد الفعّالة'


# ─────────────────────────────────────────────────────────────────────────────
# Layer 4 — Item ↔ Active Ingredient Mapping
# ─────────────────────────────────────────────────────────────────────────────

class ItemIngredientMap(models.Model):
    """
    Many-to-many bridge between catalog.Item and ActiveIngredient.
    Supports combination drugs (multiple ingredients per item).
    is_primary=True marks the main therapeutic ingredient.
    """
    item = models.ForeignKey(
        'catalog.Item', on_delete=models.CASCADE,
        related_name='ingredient_maps',
        verbose_name='الصنف',
    )
    active_ingredient = models.ForeignKey(
        ActiveIngredient, on_delete=models.CASCADE,
        related_name='item_maps',
        verbose_name='المادة الفعّالة',
    )
    concentration = models.CharField(max_length=50, blank=True,
                                     verbose_name='التركيز')   # "500mg", "10mg/5ml"
    is_primary    = models.BooleanField(default=True,
                                        verbose_name='مادة رئيسية')
    mapped_by     = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='رُبط بواسطة',
    )
    mapped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together     = ('item', 'active_ingredient')
        verbose_name        = 'ربط صنف بمادة فعّالة'
        verbose_name_plural = 'روابط الأصناف والمواد الفعّالة'

    def __str__(self):
        conc = f' {self.concentration}' if self.concentration else ''
        return f'{self.item}{conc} → {self.active_ingredient}'


# ─────────────────────────────────────────────────────────────────────────────
# Layer 5 — Follow-up Protocols
# ─────────────────────────────────────────────────────────────────────────────

class FollowUpProtocol(models.Model):
    """
    Defines when and how to follow up after a purchase of this ingredient.
    Multiple protocols per ingredient fire independently.

    Example for Metformin 500mg (30-day pack):
      Protocol 1: call  25 days after purchase  (before_runout, days=5)
      Protocol 2: whatsapp 30 days after purchase (on_runout)
      Protocol 3: call  35 days after purchase  (days_after_purchase, days=35) [escalation]
    """
    FREQUENCY_TYPES = [
        ('days_after_purchase',  '📅 بعد الشراء بـ X يوم'),
        ('before_runout',        '⏳ قبل نفاد العبوة بـ X يوم'),
        ('on_runout',            '🔴 عند يوم النفاد المتوقع'),
        ('days_after_last_task', '🔁 بعد آخر متابعة بـ X يوم'),
        ('fixed_monthly',        '📆 شهري — نفس اليوم كل شهر'),
    ]

    TRIGGER_CONDITIONS = [
        ('any_purchase',     'أي عملية شراء'),
        ('first_purchase',   'أول مرة فقط لهذا العميل'),
        ('repeat_only',      'عملاء متكررون فقط'),
        ('no_refill_missed', 'لم يعد لإعادة الصرف بعد الموعد'),
    ]

    CUSTOMER_TYPE_FILTERS = [
        ('all',           'جميع العملاء'),
        ('home_delivery', 'توصيل منزلي فقط'),
        ('walkin',        'كاش / مشي فقط'),
        ('b2b',           'شركات / تأمين فقط'),
    ]

    active_ingredient    = models.ForeignKey(
        ActiveIngredient, on_delete=models.CASCADE,
        related_name='followup_protocols',
        verbose_name='المادة الفعّالة',
    )
    name                 = models.CharField(max_length=100, verbose_name='اسم البروتوكول')
    frequency_type       = models.CharField(max_length=30, choices=FREQUENCY_TYPES,
                                            verbose_name='نوع التكرار')
    days                 = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name='عدد الأيام',
        help_text='مطلوب لأنواع: بعد الشراء، قبل النفاد، بعد آخر متابعة',
    )
    trigger_condition    = models.CharField(
        max_length=30, choices=TRIGGER_CONDITIONS,
        default='any_purchase', verbose_name='شرط التفعيل',
    )
    customer_type_filter = models.CharField(
        max_length=20, choices=CUSTOMER_TYPE_FILTERS,
        default='all', verbose_name='نوع العميل',
    )
    task_type            = models.CharField(
        max_length=20, choices=TASK_TYPE_CHOICES,
        default='call', verbose_name='وسيلة التواصل',
    )
    priority             = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES,
        default='normal', verbose_name='الأولوية',
    )
    message_template     = models.TextField(
        blank=True, verbose_name='قالب الرسالة',
        help_text=(
            'المتغيرات المتاحة: {customer_name}, {item_name}, {ingredient_name}, '
            '{days_since_purchase}, {branch_name}, {phone}'
        ),
    )
    applies_to_branches  = models.ManyToManyField(
        'branches.Branch', blank=True,
        verbose_name='الفروع المطبقة',
        help_text='اتركه فارغاً للتطبيق على جميع الفروع',
    )
    is_active   = models.BooleanField(default=True, verbose_name='نشط')
    sort_order  = models.PositiveIntegerField(default=0, verbose_name='ترتيب التنفيذ')
    created_by  = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='أنشئ بواسطة',
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'بروتوكول متابعة'
        verbose_name_plural = 'بروتوكولات المتابعة'
        ordering            = ['active_ingredient', 'sort_order', 'created_at']

    def __str__(self):
        return f'{self.active_ingredient} — {self.name}'

    @property
    def description(self):
        """Human-readable summary of this protocol."""
        freq = self.get_frequency_type_display()
        cust = self.get_customer_type_filter_display()
        days_str = f' ({self.days} يوم)' if self.days else ''
        return f'{self.get_task_type_display()} | {freq}{days_str} | {cust}'
