"""
apps/replacement/models.py — Replacement / buy-back case orchestration (doc 25).

Phase 0 = read-only historical reconstruction. The native truth (doc 25 §0):

  entitlement  = a doccode-10 purchase from a virtual "contract supplier" (4469–4472) or a
                 general buy-back account (3068 / 4069)   → ledger credit
  redemption   = a supplier payment voucher (سداد, cheques) allocated to that purchase,
                 whose cash then pays for POS sales (products) or leaves with the patient
                 (cash)                                    → ledger debit(s)

The case ledger is a per-patient PROJECTION of that native A/P sub-ledger — never an
independent balance. Invariant I-1: Σ ledger == native outstanding of the anchor purchase.
"""
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class ReplacementCase(models.Model):
    # ── source (doc 25 §16.1 rule matrix) ────────────────────────────────────
    SOURCE_INSURANCE_RX       = 'insurance_rx'        # A  — our own insurance prescription
    SOURCE_INSURANCE_EXTERNAL = 'insurance_external'  # B1 — insurance meds not dispensed by us
    SOURCE_CLIENT_BUYBACK     = 'client_buyback'      # B2 — non-insurance client selling meds
    SOURCE_CHOICES = [
        (SOURCE_INSURANCE_RX,       'روشتة تأمين من صرفنا'),
        (SOURCE_INSURANCE_EXTERNAL, 'أدوية تأمين من خارج صرفنا'),
        (SOURCE_CLIENT_BUYBACK,     'شراء أدوية من عميل (غير تأمين)'),
    ]

    MODE_PRODUCTS = 'products'
    MODE_CASH     = 'cash'
    MODE_MIXED    = 'mixed'
    MODE_PENDING  = 'pending'      # nothing redeemed yet
    MODE_CHOICES = [(MODE_PRODUCTS, 'منتجات'), (MODE_CASH, 'نقدي'), (MODE_MIXED, 'مختلط'),
                    (MODE_PENDING, 'لم يُصرف بعد')]

    # ── lifecycle (doc 25 §5). Phase 0 only produces the three post-execution states. ──
    STATUS_DRAFT              = 'draft'
    STATUS_CALCULATED         = 'calculated'
    STATUS_AWAITING_APPROVAL  = 'awaiting_approval'
    STATUS_APPROVED           = 'approved'
    STATUS_EXECUTING          = 'executing'
    STATUS_ENTITLEMENT_ACTIVE = 'entitlement_active'
    STATUS_SETTLED            = 'settled'
    STATUS_RECONCILED         = 'reconciled'
    STATUS_CLOSED             = 'closed'
    STATUS_CANCELLED          = 'cancelled'
    STATUS_REVERSING          = 'reversing'
    STATUS_REVERSED           = 'reversed'
    STATUS_CHOICES = [
        (STATUS_DRAFT,              'مسودة'),
        (STATUS_CALCULATED,         'محسوبة'),
        (STATUS_AWAITING_APPROVAL,  'بانتظار الموافقة'),
        (STATUS_APPROVED,           'معتمدة'),
        (STATUS_EXECUTING,          'جارٍ التنفيذ'),
        (STATUS_ENTITLEMENT_ACTIVE, 'رصيد قائم'),
        (STATUS_SETTLED,            'مستهلكة بالكامل'),
        (STATUS_RECONCILED,         'مطابقة'),
        (STATUS_CLOSED,             'مغلقة'),
        (STATUS_CANCELLED,          'ملغاة'),
        (STATUS_REVERSING,          'جارٍ العكس'),
        (STATUS_REVERSED,           'معكوسة'),
    ]

    ORIGIN_RECONSTRUCTED = 'reconstructed'
    ORIGIN_LIVE          = 'live'
    ORIGIN_CHOICES = [(ORIGIN_RECONSTRUCTED, 'مُعاد بناؤها من التاريخ'), (ORIGIN_LIVE, 'حالة تشغيلية')]

    CONF_HIGH, CONF_MEDIUM, CONF_LOW = 'high', 'medium', 'low'
    CONF_CHOICES = [(CONF_HIGH, 'عالية'), (CONF_MEDIUM, 'متوسطة'), (CONF_LOW, 'منخفضة')]

    number        = models.CharField(max_length=24, unique=True, null=True, blank=True)
    source_type   = models.CharField(max_length=20, choices=SOURCE_CHOICES, db_index=True)
    settlement_mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_PENDING)
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True,
                                     default=STATUS_DRAFT)
    origin        = models.CharField(max_length=14, choices=ORIGIN_CHOICES, default=ORIGIN_LIVE,
                                     db_index=True)
    correlation_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # ── where / who ──────────────────────────────────────────────────────────
    branch      = models.ForeignKey('branches.Branch', null=True, blank=True,
                                    on_delete=models.PROTECT, related_name='replacement_cases')
    branchcode  = models.CharField(max_length=5, db_index=True)
    # Patient identity comes from the SOFTECH phcode on the contract sale / redemption
    # receipts — NOT from customers.PurchaseHistory.customer (known mis-resolution).
    customer     = models.ForeignKey('customers.Customer', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='replacement_cases')
    softech_pic  = models.CharField(max_length=20, blank=True, db_index=True)
    patient_name = models.CharField(max_length=255, blank=True)
    contract_personcode = models.CharField(max_length=12, blank=True, db_index=True)  # e.g. 4479

    # ── anchor: the entitlement-creating purchase (one case per purchase) ───────
    supplier_personcode = models.CharField(max_length=12, db_index=True)
    supplier_name       = models.CharField(max_length=300, blank=True)
    # Reconstructed cases always have it; a LIVE case gets it when its purchase is posted.
    purchase_ref     = models.OneToOneField('lineage.DocumentRef', null=True, blank=True,
                                            on_delete=models.PROTECT, related_name='replacement_case')
    purchase_invoice = models.OneToOneField('finance.APInvoice', null=True, blank=True,
                                            on_delete=models.SET_NULL, related_name='replacement_case')
    purchase_date    = models.DateField(db_index=True)

    # ── money (DERIVED snapshots — recomputable from items/ledger/documents) ───
    public_value       = models.DecimalField(max_digits=14, decimal_places=2, default=0)   # Σ public × qty of replaced items
    contract_value     = models.DecimalField(max_digits=14, decimal_places=2, default=0)   # Σ contract line value of replaced items
    entitlement        = models.DecimalField(max_digits=14, decimal_places=2, default=0)   # purchase doc value
    applied_deduction_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    supplier_tier_pct  = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    redeemed_products  = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    redeemed_cash      = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    redeemed_unclassified = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    reversed_by_return = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    absorbed           = models.DecimalField(max_digits=14, decimal_places=2, default=0)   # receipts > voucher (small)
    customer_topup     = models.DecimalField(max_digits=14, decimal_places=2, default=0)   # receipts > voucher (paid by patient)
    outstanding        = models.DecimalField(max_digits=14, decimal_places=2, default=0)   # Σ ledger
    native_outstanding = models.DecimalField(max_digits=14, decimal_places=2, default=0)   # from the A/P mirror (I-1)

    # ── live workflow (Phase 1) ──────────────────────────────────────────────
    is_shortage_item = models.BooleanField(default=False)   # A: item we cannot supply → 25 % tier
    prescription_no  = models.CharField(max_length=40, blank=True)
    approval_no      = models.CharField(max_length=40, blank=True)
    notes            = models.TextField(blank=True)
    created_by   = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='replacement_cases_created')
    current_calc = models.ForeignKey('ReplacementCalculation', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    approval_request = models.ForeignKey('approvals.ApprovalRequest', null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name='+')
    approved_by  = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='+')
    approved_at  = models.DateTimeField(null=True, blank=True)
    locked_at    = models.DateTimeField(null=True, blank=True)   # set on submit; edits refused while set
    version      = models.PositiveIntegerField(default=1)        # optimistic concurrency token

    link_confidence = models.CharField(max_length=8, choices=CONF_CHOICES, blank=True)
    open_exceptions = models.PositiveIntegerField(default=0)
    max_severity    = models.CharField(max_length=10, blank=True)
    rules_version   = models.CharField(max_length=20, blank=True)
    reconstructed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-purchase_date', '-id']
        verbose_name = 'حالة بدل'
        verbose_name_plural = 'حالات البدل'
        indexes = [
            models.Index(fields=['status', 'branchcode']),
            models.Index(fields=['supplier_personcode', 'purchase_date']),
        ]

    def __str__(self):
        return f'{self.number or f"case#{self.pk}"} {self.softech_pic or "—"} {self.entitlement}'

    @property
    def number_prefix(self) -> str:
        return 'IRC' if self.source_type == self.SOURCE_INSURANCE_RX else 'BBC'

    def assign_number(self):
        if not self.number and self.pk:
            self.number = f'{self.number_prefix}-{self.purchase_date.year}-{self.pk:06d}'
            type(self).objects.filter(pk=self.pk).update(number=self.number)


class ReplacementItem(models.Model):
    """One prescription / purchase line. `disposition` distinguishes the replaced item
    (bought back by the entitlement purchase) from items dispensed as prescribed."""
    DISP_DISPENSED = 'dispensed_as_prescribed'
    DISP_REPLACED  = 'selected_for_replacement'
    DISP_PARTIAL   = 'partially_replaced'
    DISP_CHOICES = [(DISP_DISPENSED, 'صُرف كما هو'), (DISP_REPLACED, 'مُستبدل'),
                    (DISP_PARTIAL, 'مُستبدل جزئياً')]

    case = models.ForeignKey(ReplacementCase, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey('catalog.Item', null=True, blank=True, on_delete=models.SET_NULL)
    itemcode    = models.CharField(max_length=6, db_index=True)
    item_name   = models.CharField(max_length=255, blank=True)
    disposition = models.CharField(max_length=24, choices=DISP_CHOICES)
    qty_prescribed = models.DecimalField(max_digits=12, decimal_places=5, null=True, blank=True)
    qty_replaced   = models.DecimalField(max_digits=12, decimal_places=5, default=0)
    public_unit_price   = models.DecimalField(max_digits=12, decimal_places=3, default=0)   # سعر الجمهور
    contract_unit_price = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    purchase_unit_price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    applied_deduction_pct = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['disposition', 'itemcode']
        verbose_name = 'صنف حالة بدل'
        verbose_name_plural = 'أصناف حالات البدل'

    @property
    def eligible_public_value(self) -> Decimal:
        return (self.public_unit_price or 0) * (self.qty_replaced or 0)


class CaseDocument(models.Model):
    """Membership of a native document in a case, with its role and how sure we are."""
    ROLE_PURCHASE         = 'purchase'
    ROLE_SUPPLIER_RETURN  = 'supplier_return'
    ROLE_CONTRACT_SALE    = 'contract_sale'
    ROLE_CONTRACT_RETURN  = 'contract_return'     # partial return of the standing sale
    ROLE_CONTRACT_VOID    = 'contract_void'       # a sale + its full return (cancelled pair)
    ROLE_VOUCHER          = 'voucher'
    ROLE_RETURN_SETTLEMENT = 'return_settlement'  # voucher that closes a supplier return
    ROLE_PRODUCT_SALE     = 'product_sale'
    ROLE_CHOICES = [
        (ROLE_PURCHASE,        'فاتورة الشراء (إنشاء الرصيد)'),
        (ROLE_SUPPLIER_RETURN, 'مرتجع للمورد'),
        (ROLE_CONTRACT_SALE,   'بيع التعاقد'),
        (ROLE_CONTRACT_RETURN, 'مرتجع جزئي للتعاقد'),
        (ROLE_CONTRACT_VOID,   'بيع تعاقد ملغى بمرتجع'),
        (ROLE_VOUCHER,         'سند صرف'),
        (ROLE_RETURN_SETTLEMENT, 'سند تسوية مرتجع'),
        (ROLE_PRODUCT_SALE,    'فاتورة منتجات البدل'),
    ]

    STATUS_PROPOSED  = 'proposed'
    STATUS_CONFIRMED = 'confirmed'
    STATUS_REJECTED  = 'rejected'
    STATUS_CHOICES = [(STATUS_PROPOSED, 'مقترح'), (STATUS_CONFIRMED, 'مؤكد'), (STATUS_REJECTED, 'مرفوض')]

    case     = models.ForeignKey(ReplacementCase, on_delete=models.CASCADE, related_name='documents')
    document = models.ForeignKey('lineage.DocumentRef', on_delete=models.PROTECT, related_name='case_links')
    role     = models.CharField(max_length=20, choices=ROLE_CHOICES, db_index=True)
    status   = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PROPOSED, db_index=True)
    origin   = models.CharField(max_length=8, default='matched')    # native | matched | manual
    confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    evidence   = models.JSONField(default=list, blank=True)
    parent     = models.ForeignKey('self', null=True, blank=True, on_delete=models.CASCADE,
                                   related_name='children')          # product_sale → its voucher
    amount     = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']
        verbose_name = 'مستند حالة'
        verbose_name_plural = 'مستندات الحالات'
        constraints = [
            models.UniqueConstraint(fields=['case', 'document', 'role'], name='uq_replacement_casedoc'),
        ]


class LedgerEntryQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError('دفتر الرصيد للإضافة فقط — لا يُسمح بالتعديل.')

    def delete(self):
        raise ValidationError('دفتر الرصيد للإضافة فقط — لا يُسمح بالحذف.')


class EntitlementLedgerEntry(models.Model):
    """APPEND-ONLY. Balance = Σ amount. Corrections are compensating entries pointing at the
    entry they undo via `reverses` (UNIQUE → an entry can be reversed at most once)."""
    TYPE_CREATED       = 'entitlement_created'
    TYPE_PRODUCT       = 'product_redemption'
    TYPE_CASH          = 'cash_settlement'
    TYPE_UNCLASSIFIED  = 'redemption_unclassified'   # voucher paid out, use not yet proven
    TYPE_SUPPLIER_RET  = 'supplier_return_reversal'
    TYPE_POS_RETURN    = 'pos_return_credit'
    TYPE_RETURN_SETTLED = 'return_settled'           # supplier return closed by a voucher (cash back / netting)
    TYPE_REVERSAL      = 'reversal'                  # compensates the entry in `reverses`
    TYPE_CHOICES = [
        (TYPE_CREATED,      'إنشاء رصيد'),
        (TYPE_PRODUCT,      'صرف منتجات'),
        (TYPE_CASH,         'صرف نقدي'),
        (TYPE_UNCLASSIFIED, 'صرف غير مصنّف'),
        (TYPE_SUPPLIER_RET, 'عكس بمرتجع مورد'),
        (TYPE_RETURN_SETTLED, 'تسوية مرتجع (استرداد / مقاصة)'),
        (TYPE_POS_RETURN,   'رد رصيد بمرتجع منتجات'),
        (TYPE_REVERSAL,     'قيد عكسي'),
    ]
    CREDIT_TYPES = {TYPE_CREATED, TYPE_POS_RETURN, TYPE_RETURN_SETTLED}
    DEBIT_TYPES  = {TYPE_PRODUCT, TYPE_CASH, TYPE_UNCLASSIFIED, TYPE_SUPPLIER_RET}

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case       = models.ForeignKey(ReplacementCase, on_delete=models.PROTECT, related_name='ledger')
    entry_type = models.CharField(max_length=24, choices=TYPE_CHOICES, db_index=True)
    amount     = models.DecimalField(max_digits=14, decimal_places=2)
    document   = models.ForeignKey('lineage.DocumentRef', null=True, blank=True,
                                   on_delete=models.PROTECT, related_name='ledger_entries')
    reverses   = models.OneToOneField('self', null=True, blank=True, on_delete=models.PROTECT,
                                      related_name='reversed_by')
    origin     = models.CharField(max_length=14, default=ReplacementCase.ORIGIN_RECONSTRUCTED)
    created_by = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    note       = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = LedgerEntryQuerySet.as_manager()

    class Meta:
        ordering = ['created_at']
        verbose_name = 'قيد رصيد بدل'
        verbose_name_plural = 'قيود رصيد البدل'
        constraints = [
            models.CheckConstraint(check=~models.Q(amount=0), name='ck_replacement_ledger_nonzero'),
            # one entry of a given type per (case, native document) → reconstruction is idempotent
            models.UniqueConstraint(fields=['case', 'entry_type', 'document'],
                                    condition=models.Q(document__isnull=False, reverses__isnull=True),
                                    name='uq_replacement_ledger_doc'),
        ]

    def clean(self):
        if self.entry_type in self.CREDIT_TYPES and self.amount <= 0:
            raise ValidationError('قيد الإضافة يجب أن يكون موجباً.')
        if self.entry_type in self.DEBIT_TYPES and self.amount >= 0:
            raise ValidationError('قيد الصرف يجب أن يكون سالباً.')
        if self.entry_type == self.TYPE_REVERSAL:
            if not self.reverses_id:
                raise ValidationError('القيد العكسي يجب أن يشير إلى القيد الأصلي.')
            if self.amount != -self.reverses.amount:
                raise ValidationError('القيد العكسي يجب أن يساوي سالب القيد الأصلي.')

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('دفتر الرصيد للإضافة فقط — لا يُسمح بالتعديل.')
        self.full_clean(exclude=['case', 'document', 'reverses', 'created_by'])
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('دفتر الرصيد للإضافة فقط — لا يُسمح بالحذف.')


class CaseException(models.Model):
    SEV_INFO, SEV_WARNING, SEV_HIGH, SEV_CRITICAL = 'info', 'warning', 'high', 'critical'
    SEVERITY_CHOICES = [(SEV_INFO, 'معلومة'), (SEV_WARNING, 'تحذير'), (SEV_HIGH, 'مرتفع'),
                        (SEV_CRITICAL, 'حرج')]
    SEVERITY_RANK = {SEV_INFO: 0, SEV_WARNING: 1, SEV_HIGH: 2, SEV_CRITICAL: 3}

    TYPE_CHOICES = [
        ('purchase_lines_missing',  'أصناف فاتورة الشراء غير متاحة في المرآة'),
        ('no_contract_sale',        'لا توجد فاتورة تعاقد مطابقة'),
        ('ambiguous_patient',       'أكثر من مريض محتمل لنفس الشراء'),
        ('sale_outside_window',     'فاتورة التعاقد خارج النافذة الزمنية'),
        ('multi_patient_purchase',  'فاتورة شراء لأكثر من مريض'),
        ('duplicate_purchase',      'شراء مكرر لنفس صنف الروشتة'),
        ('qty_exceeds_sale',        'الكمية المشتراة أكبر من كمية فاتورة التعاقد (قد تغطي أكثر من روشتة)'),
        ('aged_outstanding',        'رصيد قائم قديم'),
        ('unlinked_voucher_likely', 'رصيد قائم مع سند صرف غير مربوط محتمل'),
        ('voucher_without_receipt', 'سند صرف بدون فاتورة منتجات'),
        ('cash_on_product_tier',    'صرف نقدي من رصيد بسعر المنتجات'),
        ('cash_remainder_high',     'باقي نقدي كبير من رصيد المنتجات'),
        ('receipts_exceed_voucher', 'فواتير المنتجات أكبر من السند'),
        ('anonymous_receipt',       'فاتورة منتجات بدون كود مريض — تحتاج تأكيد'),
        ('rate_deviation',          'نسبة الخصم المطبقة تختلف عن فئة المورد'),
        ('cross_branch_voucher',    'سند صرف من فرع مختلف'),
        ('voucher_reversed',        'سند صرف مُلغى'),
        ('supplier_return',         'مرتجع للمورد على الفاتورة'),
        ('ledger_native_mismatch',  'رصيد الدفتر لا يطابق رصيد SOFTECH'),
        ('negative_entitlement',    'رصيد سالب'),
        ('self_approval',           'اعتماد من منشئ الحالة (فصل المهام)'),
        ('stale_approval',          'اعتماد على حساب تغيّر بعد الإرسال'),
        ('posting_failed',          'فشل الترحيل إلى SOFTECH'),
        ('purchase_value_mismatch', 'قيمة فاتورة الشراء في SOFTECH تختلف عن الرصيد المعتمد'),
    ]

    STATUS_OPEN, STATUS_ACK, STATUS_RESOLVED, STATUS_CLEARED = 'open', 'acknowledged', 'resolved', 'auto_cleared'
    STATUS_CHOICES = [(STATUS_OPEN, 'مفتوح'), (STATUS_ACK, 'قيد المتابعة'),
                      (STATUS_RESOLVED, 'محلول'), (STATUS_CLEARED, 'زال تلقائياً')]
    BLOCKING = {SEV_HIGH, SEV_CRITICAL}

    case     = models.ForeignKey(ReplacementCase, on_delete=models.CASCADE, related_name='exceptions')
    exception_type = models.CharField(max_length=28, choices=TYPE_CHOICES, db_index=True)
    key      = models.CharField(max_length=60, blank=True, default='')   # e.g. the voucher id
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, db_index=True)
    status   = models.CharField(max_length=14, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    amount   = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    detail   = models.TextField(blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    owner    = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name='+')
    resolved_by = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='+')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution  = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'استثناء حالة بدل'
        verbose_name_plural = 'استثناءات حالات البدل'
        constraints = [
            models.UniqueConstraint(fields=['case', 'exception_type', 'key'],
                                    name='uq_replacement_exception'),
        ]
        indexes = [models.Index(fields=['status', 'severity'])]


class ReplacementRule(models.Model):
    """Versioned deduction rule (doc 25 §9). Never edited once used: a change is a NEW version
    (same rule_key, version+1) and every calculation snapshot points at the exact version."""
    ROUND_NONE, ROUND_1, ROUND_5, ROUND_10, ROUND_50 = 'none', 'floor_1', 'floor_5', 'floor_10', 'floor_50'
    ROUND_CHOICES = [(ROUND_NONE, 'بدون تقريب'), (ROUND_1, 'تقريب لأسفل لأقرب 1'),
                     (ROUND_5, 'تقريب لأسفل لأقرب 5'), (ROUND_10, 'تقريب لأسفل لأقرب 10'),
                     (ROUND_50, 'تقريب لأسفل لأقرب 50')]

    rule_key   = models.CharField(max_length=40, db_index=True)
    version    = models.PositiveIntegerField(default=1)
    name       = models.CharField(max_length=120)
    source_type = models.CharField(max_length=20, choices=ReplacementCase.SOURCE_CHOICES)
    settlement_mode = models.CharField(max_length=10, choices=[('products', 'منتجات'), ('cash', 'نقدي')])
    shortage_only = models.BooleanField(default=False)          # applies only to is_shortage_item cases
    contract_personcode = models.CharField(max_length=12, blank=True)   # '' = any contract
    branchcode = models.CharField(max_length=5, blank=True)              # '' = any branch
    deduction_pct = models.DecimalField(max_digits=5, decimal_places=2)
    supplier_personcode = models.CharField(max_length=12)       # virtual supplier the purchase goes to
    rounding   = models.CharField(max_length=10, choices=ROUND_CHOICES, default=ROUND_NONE)
    priority   = models.PositiveSmallIntegerField(default=100)  # lower = more specific / wins
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    is_active  = models.BooleanField(default=True)
    created_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['priority', 'rule_key', '-version']
        verbose_name = 'قاعدة خصم بدل'
        verbose_name_plural = 'قواعد خصم البدل'
        constraints = [models.UniqueConstraint(fields=['rule_key', 'version'], name='uq_replacement_rule_version')]

    def __str__(self):
        return f'{self.name} v{self.version} — {self.deduction_pct}% → {self.supplier_personcode}'


class ReplacementGrant(models.Model):
    """Per-employee authorization on top of the role matrix (owner D12: mostly per role, per user
    for certain channels). No row = role defaults; an active row narrows/extends the limits."""
    staff = models.OneToOneField('users.StaffProfile', on_delete=models.CASCADE, related_name='replacement_grant')
    is_active = models.BooleanField(default=True)
    can_create = models.BooleanField(default=True)
    can_approve = models.BooleanField(default=False)
    can_post = models.BooleanField(default=False)          # may execute legs (purchase / sales)
    allowed_sources = models.JSONField(default=list, blank=True)   # [] = all source types
    allowed_modes   = models.JSONField(default=list, blank=True)   # [] = all settlement modes
    max_case_entitlement = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    approve_limit   = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_override_pp = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # may LOWER deduction by ≤ N pp
    notes      = models.CharField(max_length=300, blank=True)
    granted_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'صلاحية موظف على البدل'
        verbose_name_plural = 'صلاحيات الموظفين على البدل'


class ReplacementCalculation(models.Model):
    """Immutable server-side calculation snapshot. A case may have several; current_calc is the
    one submitted/approved. Approval is bound to `fingerprint` — any later change invalidates it."""
    case = models.ForeignKey(ReplacementCase, on_delete=models.CASCADE, related_name='calculations')
    seq  = models.PositiveIntegerField()
    rule = models.ForeignKey(ReplacementRule, on_delete=models.PROTECT, related_name='calculations')
    rule_deduction_pct    = models.DecimalField(max_digits=5, decimal_places=2)
    applied_deduction_pct = models.DecimalField(max_digits=5, decimal_places=2)
    override_reason = models.CharField(max_length=300, blank=True)
    lines = models.JSONField(default=list)        # [{itemcode, name, qty, public_price, eligible, entitlement}]
    public_value   = models.DecimalField(max_digits=14, decimal_places=2)
    entitlement_raw = models.DecimalField(max_digits=14, decimal_places=2)
    rounding_adj   = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    entitlement    = models.DecimalField(max_digits=14, decimal_places=2)
    fingerprint    = models.CharField(max_length=64)
    created_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-seq']
        constraints = [models.UniqueConstraint(fields=['case', 'seq'], name='uq_replacement_calc_seq')]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError('لقطة الحساب غير قابلة للتعديل — أنشئ حساباً جديداً.')
        super().save(*args, **kwargs)


class PostingOperation(models.Model):
    """One intended SOFTECH write (doc 25 §11) — the idempotency unit. A retry finds the same
    operation (unique key) and the underlying writer's own idempotency (docnumber2 dup-guard /
    client_token + vf2) makes a second physical write impossible."""
    KIND_PURCHASE, KIND_CONTRACT_SALE, KIND_PRODUCT_SALE = 'purchase', 'contract_sale', 'product_sale'
    KIND_CHOICES = [(KIND_PURCHASE, 'فاتورة شراء (إنشاء الرصيد)'), (KIND_CONTRACT_SALE, 'بيع تعاقد'),
                    (KIND_PRODUCT_SALE, 'بيع منتجات البدل')]
    ST_PLANNED, ST_DRY_RUN, ST_POSTING, ST_POSTED, ST_VERIFIED, ST_FAILED, ST_CANCELLED = (
        'planned', 'dry_run', 'posting', 'posted', 'posted_verified', 'failed', 'cancelled')
    STATUS_CHOICES = [(ST_PLANNED, 'مُعد'), (ST_DRY_RUN, 'تجربة بدون ترحيل'), (ST_POSTING, 'جارٍ الترحيل'),
                      (ST_POSTED, 'مُرحّل — بانتظار الكاشير'), (ST_VERIFIED, 'مُرحّل ومُتحقق'),
                      (ST_FAILED, 'فشل'), (ST_CANCELLED, 'ملغى')]

    op_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    case  = models.ForeignKey(ReplacementCase, on_delete=models.PROTECT, related_name='operations')
    kind  = models.CharField(max_length=16, choices=KIND_CHOICES)
    idempotency_key = models.CharField(max_length=80, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=ST_PLANNED, db_index=True)
    supplier_invoice = models.ForeignKey('invoices.SupplierInvoice', null=True, blank=True,
                                         on_delete=models.PROTECT, related_name='+')
    sales_order = models.ForeignKey('pos_orders.SoftechSalesOrder', null=True, blank=True,
                                    on_delete=models.PROTECT, related_name='+')
    expected_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    result_docnumber = models.CharField(max_length=20, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error  = models.TextField(blank=True)
    requested_by = models.ForeignKey('users.StaffProfile', null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'عملية ترحيل'
        verbose_name_plural = 'عمليات الترحيل'


class ReconstructionRun(models.Model):
    started_at   = models.DateTimeField(auto_now_add=True)
    finished_at  = models.DateTimeField(null=True, blank=True)
    status       = models.CharField(max_length=10, default='running')   # running | success | partial | failed
    params       = models.JSONField(default=dict)
    counts       = models.JSONField(default=dict)
    rules_version = models.CharField(max_length=20, blank=True)
    triggered_by = models.CharField(max_length=100, blank=True)
    notes        = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'تشغيل إعادة بناء'
        verbose_name_plural = 'تشغيلات إعادة البناء'
