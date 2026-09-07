from django.db import models


class Customer(models.Model):
    # softech_id = branchcustcode (e.g. "28"). NOT globally unique — the same
    # number exists for different customers in different branches. Kept for
    # backward-compat and as a fallback search field only.
    softech_id = models.CharField(max_length=13, null=True, blank=True, db_index=True)
    # softech_pic = phcode from SOFTECH (e.g. "12HD28", "130HD9969"). This IS
    # globally unique — it encodes both branch prefix and customer serial.
    softech_pic = models.CharField(
        max_length=30, null=True, blank=True, unique=True, db_index=True,
        verbose_name='كود العميل (PIC)',
        help_text='الكود المركب: {كودالفرع}HD{رقمالعميل} — مثال: 01HD14 أو 130HD9969',
    )
    # ── SOFTECH person-type tree ─────────────────────────────────────────────
    # sourced from personsdata (authoritative) via LEFT JOIN on phcode = personcode.
    softech_ptcode = models.CharField(
        max_length=10, blank=True, db_index=True,
        verbose_name='كود نوع الشخص',
        help_text='personsdata.ptcode → persontypes.ptcode (e.g. "01" = عميل)',
    )
    softech_ptclassifcode = models.CharField(
        max_length=10, blank=True, db_index=True,
        verbose_name='كود تصنيف الشخص',
        help_text='personsdata.ptclassifcode — authoritative channel code '
                  '(e.g. "90"=توصيل "91"=كاش "15"=تأمين). '
                  'Falls back to localcustomers.branchcustclassif if personsdata row absent.',
    )
    person_type_label = models.CharField(
        max_length=150, blank=True,
        verbose_name='وصف نوع الشخص',
        help_text='persontypes.ptdescr — Arabic label for ptcode',
    )
    person_classif_label = models.CharField(
        max_length=150, blank=True,
        verbose_name='وصف تصنيف الشخص',
        help_text='persontypesclassif.ptclassifdescr — Arabic label for ptclassifcode '
                  '(= sales channel label: توصيل / كاش / تأمين صحي …)',
    )
    softech_global_code = models.CharField(
        max_length=50, blank=True,
        verbose_name='الكود المركزي (personglobalcode)',
        help_text='personsdata.personglobalcode — cross-branch global person code',
    )
    order_branch_code = models.CharField(
        max_length=10, blank=True,
        verbose_name='كود فرع الطلبات الافتراضي',
        help_text='localcustomers.orderbranchcode — default branch for delivery orders',
    )
    name = models.CharField(max_length=255, db_index=True)
    phone = models.CharField(max_length=50, db_index=True, blank=True)
    phone_alt = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    chronic_conditions = models.TextField(blank=True)      # staff-entered
    notes_softech = models.TextField(blank=True)            # personnote from SOFTECH
    discount_percent = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    preferred_branch = models.ForeignKey(
        'branches.Branch', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='customers'
    )
    # Walk-in / pre-ERP flag.
    # True  → entered by staff before the customer is registered in SOFTECH.
    #         No softech_id yet. Auto-merged when SOFTECH sync finds same phone.
    # False → synced from SOFTECH (normal customer).
    is_guest = models.BooleanField(
        default=False,
        help_text='زبون مؤقت — سيتم دمجه تلقائياً عند مزامنة رقم هاتفه من SOFTECH',
    )
    created_by = models.ForeignKey(
        'users.StaffProfile', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='created_customers'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── CRM Segmentation fields (populated by segment_customers command) ──────
    SEGMENT_CHOICES = [
        ('vip',      'VIP 👑'),
        ('loyal',    'مخلص'),
        ('regular',  'عادي'),
        ('at_risk',  'في خطر ⚠️'),
        ('dormant',  'نائم 💤'),
        ('new',      'جديد 🌱'),
        ('churned',  'مفقود ❌'),
    ]
    segment = models.CharField(
        max_length=15, blank=True, db_index=True,
        choices=SEGMENT_CHOICES,
        verbose_name='شريحة العميل',
        help_text='Computed daily by segment_customers management command',
    )
    # Lifetime value — sum of net sales from PurchaseHistory (sales - returns)
    ltv = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='القيمة الكلية للعميل (LTV)',
    )
    last_visit_date = models.DateField(
        null=True, blank=True, db_index=True,
        verbose_name='آخر زيارة',
    )
    # Cached delta from today — refreshed nightly (avoids runtime subtraction in queries)
    days_since_last_visit = models.PositiveIntegerField(
        null=True, blank=True, db_index=True,
        verbose_name='الأيام منذ آخر زيارة',
    )
    purchase_count_90d = models.PositiveIntegerField(
        default=0,
        verbose_name='عدد المشتريات (90 يوم)',
    )
    # 0-100 risk score: higher = more likely to complain / escalate
    complaint_risk_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name='مخاطر الشكوى',
        help_text='0–100: computed from complaint history, call frequency, unfulfilled requests',
    )
    segment_updated_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='آخر تحديث للتصنيف',
    )

    # ── Churn intelligence (computed by segment_customers nightly) ────────────
    CHURN_SEGMENT_CHOICES = [
        ('low',      'منخفض — عميل مستقر'),
        ('medium',   'متوسط — مراقبة'),
        ('high',     'مرتفع — تدخل مطلوب'),
        ('critical', 'حرج — على وشك الانقطاع'),
    ]
    churn_score = models.FloatField(
        default=0.0, db_index=True,
        verbose_name='درجة خطر الانقطاع',
        help_text='0-1: كلما ارتفعت زادت احتمالية انقطاع العميل. تُحسب يومياً.',
    )
    churn_segment = models.CharField(
        max_length=10, blank=True, choices=CHURN_SEGMENT_CHOICES, db_index=True,
        verbose_name='شريحة الانقطاع',
    )
    churn_updated_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='آخر تحديث لدرجة الانقطاع',
    )

    # ── WhatsApp contact (may differ from primary phone) ──────────────────────
    whatsapp_phone = models.CharField(
        max_length=50, blank=True, db_index=True,
        verbose_name='واتساب',
        help_text='رقم الواتساب إن اختلف عن الهاتف الأساسي',
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.phone})"

    @property
    def customer_type_label(self):
        labels = {
            '90': 'توصيل',      # Delivery
            '91': 'كاش',         # Cash
            '15': 'تأمين صحي',   # Insurance
        }
        return labels.get(self.softech_ptclassifcode, 'عميل')

    @property
    def customer_type_color(self):
        colors = {
            '90': 'blue',
            '91': 'gray',
            '15': 'green',
        }
        return colors.get(self.softech_ptclassifcode, 'gray')

    @property
    def total_purchases(self):
        return self.purchases.count()

    @property
    def lifetime_value(self):
        from django.db.models import Sum
        result = self.purchases.aggregate(total=Sum('total_amount'))
        return result['total'] or 0


class CustomerNote(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='notes')
    note = models.TextField()
    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note for {self.customer.name} at {self.created_at:%Y-%m-%d}"


class CustomerHealthProfile(models.Model):
    """
    Structured clinical summary for a customer — auto-maintained by the
    disease detection engine (segment_customers or a dedicated command).

    Design rules:
      - OneToOne to Customer — one profile per real person
      - NEVER synced from SOFTECH — derived from purchase history via chronic module
      - Pharmacist can override any field manually (source field tracks this)
      - is_* flags are computed from ItemIngredientMap + PurchaseHistory
      - condition_confidence stores per-condition confidence score (0-1)

    This replaces the free-text Customer.chronic_conditions field for automation.
    """
    CHRONIC_CONDITIONS = [
        ('diabetes',       'السكري'),
        ('hypertension',   'ضغط الدم'),
        ('cardiovascular', 'أمراض القلب'),
        ('thyroid',        'الغدة الدرقية'),
        ('cholesterol',    'ارتفاع الكوليسترول'),
        ('asthma',         'الربو'),
        ('psychiatric',    'الأمراض النفسية'),
        ('epilepsy',       'الصرع'),
        ('osteoporosis',   'هشاشة العظام'),
        ('renal',          'أمراض الكلى المزمنة'),
        ('oncology',       'الأورام'),
        ('gerd',           'ارتجاع المريء المزمن'),
        ('anemia',         'فقر الدم المزمن'),
        ('anticoagulant',  'مضادات التخثر'),
        ('immunosuppressant', 'مثبطات المناعة'),
        ('other_chronic',  'مزمن - أخرى'),
    ]

    customer = models.OneToOneField(
        Customer, on_delete=models.CASCADE,
        related_name='health_profile',
        verbose_name='العميل',
    )

    # ── Detected chronic conditions (auto-computed from purchases) ─────────────
    has_diabetes         = models.BooleanField(default=False, db_index=True)
    has_hypertension     = models.BooleanField(default=False, db_index=True)
    has_cardiovascular   = models.BooleanField(default=False, db_index=True)
    has_thyroid          = models.BooleanField(default=False, db_index=True)
    has_cholesterol      = models.BooleanField(default=False, db_index=True)
    has_asthma           = models.BooleanField(default=False)
    has_psychiatric      = models.BooleanField(default=False)
    has_epilepsy         = models.BooleanField(default=False)
    has_osteoporosis     = models.BooleanField(default=False)
    has_renal            = models.BooleanField(default=False)
    has_oncology         = models.BooleanField(default=False)
    has_gerd             = models.BooleanField(default=False)
    has_anemia           = models.BooleanField(default=False)
    has_anticoagulant    = models.BooleanField(default=False)
    has_immunosuppressant= models.BooleanField(default=False)
    has_other_chronic    = models.BooleanField(default=False)

    # ── Confidence scores per condition {condition_key: 0.0-1.0} ──────────────
    condition_confidence = models.JSONField(
        default=dict, blank=True,
        verbose_name='درجة الثقة لكل حالة',
        help_text='مثال: {"diabetes": 0.95, "hypertension": 0.80}',
    )

    # ── Active medications (auto-built from PurchaseHistory via chronic tags) ──
    # [{item_id, item_name, ingredient, chronic_class, last_purchase_date, purchase_count}]
    active_medications = models.JSONField(
        default=list, blank=True,
        verbose_name='الأدوية النشطة',
        help_text='قائمة الأدوية المزمنة النشطة — تُجمَع من سجل المشتريات',
    )

    # ── Special flags ──────────────────────────────────────────────────────────
    pregnancy_flag    = models.BooleanField(
        default=False,
        verbose_name='حامل',
        help_text='يُحدَّد يدوياً بواسطة الصيدلاني',
    )
    lactation_flag    = models.BooleanField(
        default=False,
        verbose_name='مرضعة',
    )
    pediatric_patient = models.BooleanField(
        default=False,
        verbose_name='يشتري لطفل',
        help_text='العميل يشتري لمريض طفل (لا لنفسه)',
    )
    polypharmacy_flag = models.BooleanField(
        default=False,
        verbose_name='أدوية متعددة (>5)',
        help_text='يأخذ أكثر من 5 أدوية متزامنة',
    )

    # ── Known allergies ────────────────────────────────────────────────────────
    # [{"ingredient": "penicillin", "severity": "severe", "source": "declared"}]
    known_allergies = models.JSONField(
        default=list, blank=True,
        verbose_name='الحساسيات المعروفة',
    )
    declared_allergies_text = models.TextField(
        blank=True,
        verbose_name='تفاصيل الحساسية (نص حر)',
        help_text='نص حر أدخله الصيدلاني أو العميل',
    )

    # ── Audit ──────────────────────────────────────────────────────────────────
    last_computed_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='آخر حساب تلقائي',
    )
    manually_overridden = models.BooleanField(
        default=False,
        verbose_name='تم التعديل يدوياً',
        help_text='إذا True: لن يُعيد الحساب التلقائي تجاوز الحقول اليدوية',
    )
    updated_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='updated_health_profiles',
        verbose_name='آخر تعديل بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'ملف صحي للعميل'
        verbose_name_plural = 'الملفات الصحية للعملاء'
        indexes = [
            models.Index(fields=['has_diabetes', 'has_hypertension']),
            models.Index(fields=['has_cardiovascular']),
        ]

    def __str__(self):
        conditions = [
            c[1] for c, flag in zip(self.CHRONIC_CONDITIONS, [
                self.has_diabetes, self.has_hypertension, self.has_cardiovascular,
                self.has_thyroid, self.has_cholesterol, self.has_asthma,
                self.has_psychiatric, self.has_epilepsy, self.has_osteoporosis,
                self.has_renal, self.has_oncology, self.has_gerd,
                self.has_anemia, self.has_anticoagulant, self.has_immunosuppressant,
                self.has_other_chronic,
            ]) if flag
        ]
        return f'{self.customer.name} — {", ".join(conditions) or "لا حالات مسجلة"}'

    @property
    def detected_conditions(self) -> list[str]:
        """Return list of condition keys that are True."""
        mapping = [
            ('diabetes',        self.has_diabetes),
            ('hypertension',    self.has_hypertension),
            ('cardiovascular',  self.has_cardiovascular),
            ('thyroid',         self.has_thyroid),
            ('cholesterol',     self.has_cholesterol),
            ('asthma',          self.has_asthma),
            ('psychiatric',     self.has_psychiatric),
            ('epilepsy',        self.has_epilepsy),
            ('osteoporosis',    self.has_osteoporosis),
            ('renal',           self.has_renal),
            ('oncology',        self.has_oncology),
            ('gerd',            self.has_gerd),
            ('anemia',          self.has_anemia),
            ('anticoagulant',   self.has_anticoagulant),
            ('immunosuppressant', self.has_immunosuppressant),
            ('other_chronic',   self.has_other_chronic),
        ]
        return [k for k, v in mapping if v]

    @property
    def is_chronic(self) -> bool:
        return bool(self.detected_conditions)

    @property
    def active_ingredient_names(self) -> list[str]:
        """Quick list of all active ingredient names from active_medications."""
        return [m.get('ingredient', '') for m in (self.active_medications or []) if m.get('ingredient')]


class PurchaseHistory(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='purchases')
    softech_invoice_id = models.CharField(max_length=150, unique=True)
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE)
    doc_code = models.CharField(max_length=3, blank=True)  # '115' = sale, '30' = return
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    invoice_date = models.DateTimeField(null=True, blank=True)
    # ERP document number — return invoices reference this to link back to the original sale
    docnumber = models.CharField(max_length=30, blank=True, db_index=True)
    # Cashier / salesperson usercode from stktransm
    softech_user = models.CharField(max_length=20, blank=True, db_index=True)
    # Denormalized from customer at sync time — avoids FK joins in analytics.
    # sales_channel     = customer.softech_ptclassifcode  (e.g. '90','91','15')
    # sales_person_type = customer.softech_ptcode          (e.g. '01' = عميل)
    sales_channel = models.CharField(
        max_length=10, blank=True, db_index=True,
        verbose_name='قناة البيع',
        help_text='personsdata.ptclassifcode — e.g. 90=توصيل 91=كاش 15=تأمين',
    )
    sales_person_type = models.CharField(
        max_length=10, blank=True, db_index=True,
        verbose_name='نوع شخص العميل',
        help_text='personsdata.ptcode — person type of the linked customer',
    )
    # stktrans.storecode — the warehouse/store within the branch that fulfilled the order.
    # Useful for multi-store branches (e.g. store '01' = main, '02' = pharmacy 2).
    store_code = models.CharField(
        max_length=20, blank=True, db_index=True,
        verbose_name='كود المخزن',
        help_text='stktrans.storecode — warehouse / store code within the branch',
    )
    # stktransm.cust_branch_code — the customer ordering/delivery branch code.
    # Distinct from the transaction branch: this is the branch "responsible" for
    # the customer (e.g. their home-delivery branch).
    cust_branch_code = models.CharField(
        max_length=10, blank=True, db_index=True,
        verbose_name='كود فرع العميل',
        help_text='stktransm.cust_branch_code — ordering/delivery branch code for this customer',
    )
    # stktransm.phcode — the customer PIC (Personal Identification Code) stamped
    # on every invoice header by SOFTECH. Same format as localcustomers.phcode
    # (e.g. "01HD14", "08HD1296"). Stored here so we can count distinct PICs
    # directly from invoice data instead of traversing customer.softech_pic —
    # which under-counts because anonymous walk-in invoices (personcode 1500/1510)
    # all map to the same two Customer records even though each had a unique PIC.
    softech_phcode = models.CharField(
        max_length=20, blank=True, db_index=True,
        verbose_name='كود PIC العميل',
        help_text='stktransm.phcode — customer PIC stamped on this invoice header',
    )
    # stktrans.transtime — the actual transaction clock time (distinct from stktransm.docdate
    # which stores only the date, always at midnight). Used for hour-of-day filtering in
    # analytics dashboards. Nullable because old records synced before this field was added
    # won't have it; they fall back to invoice_date for hour filtering.
    trans_time = models.DateTimeField(
        null=True, blank=True, db_index=True,
        verbose_name='وقت المعاملة',
        help_text='stktrans.transtime — actual transaction clock time (used for hour filters)',
    )
    last_synced = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-invoice_date']

    @property
    def is_return(self):
        return self.doc_code == '30'


class PurchaseHistoryLine(models.Model):
    purchase = models.ForeignKey(PurchaseHistory, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey('catalog.Item', on_delete=models.SET_NULL, null=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)
    # stktrans.itemcostprice — cost recorded at time of sale/return by SOFTECH.
    # This is the AUTHORITATIVE value for COGS and profit calculations.
    # Item.cost_price is the CURRENT catalog cost (updated every sync) and
    # diverges from historic transaction costs, causing COGS discrepancies.
    cost_at_sale = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        verbose_name='سعر التكلفة عند البيع',
        help_text='stktrans.newcostprice — weighted-average cost per unit at time of transaction',
    )
    # ── Discount / promo fields (doc 16 metric-catalog Phase 1) ──────────────────
    # From stktrans; populated by the sales sync. Enable discounting/upsell metrics.
    list_price = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        verbose_name='سعر البيع قبل الخصم',
        help_text='stktrans.itemsaleprice — catalog/list unit price before discount',
    )
    disc_pharmacy_pct   = models.DecimalField(max_digits=6, decimal_places=3, default=0,
                                              verbose_name='خصم الصيدلية %')   # pharmacydiscp
    disc_additional_pct = models.DecimalField(max_digits=6, decimal_places=3, default=0,
                                              verbose_name='خصم إضافي %')       # additionaldiscp
    disc_customer_pct   = models.DecimalField(max_digits=6, decimal_places=3, default=0,
                                              verbose_name='خصم العميل %')       # custdiscp
    disc_special_pct    = models.DecimalField(max_digits=6, decimal_places=3, default=0,
                                              verbose_name='خصم خاص %')          # specialdiscp
    # NOTE: list_price (itemsaleprice) is TAX-INCLUSIVE; customer discount is derived as
    # list_price·qty − line_total (discount applies to the full tax-inclusive price).
    # pharmacydiscp/additionaldiscp are NOT customer discounts (don't reduce the paid price).
    # bonusqty was removed — it is a PURCHASING column, never set on sales (115) / returns (30).
