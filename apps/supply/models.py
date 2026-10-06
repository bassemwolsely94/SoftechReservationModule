"""
apps/supply/models.py — the orchestration spine's persistent state (doc 24).

Phase 1 introduces ONE model: DemandSignal — the provenance + dedup ledger.

WHY THIS EXISTS (prompt §22 / §23):
  The same underlying requirement reaches us through several channels — a customer
  reservation, a structured demand record, a branch shortage list pasted from
  WhatsApp, the market-shortage detector. Summing them blindly double-counts demand.
  DemandSignal records EACH expression with full provenance (who/where/when/how much,
  from which source row), and the reconcile engine (apps/supply/reconcile.py) collapses
  same-class echoes at read time WITHOUT destroying any provenance.

DemandSignal NEVER recomputes demand quantities — it only stores what a source already
asked for, tagged with a provenance class that tells the reconciler how to combine it:

  • customer_commitment — a real, independent customer ask (reservation / demand record).
    Multiple are ADDITIVE (3 reservations = 3 waiting customers).
  • branch_replenishment — a branch expressing a stock need (shortage list). Repeated
    expressions of the same item at the same branch are ECHOES → deduped (max), not summed.
  • statistical — the market-shortage detector's network baseline for an item (indicator,
    not added to the above).
"""
from django.conf import settings
from django.db import models


class DemandSignal(models.Model):
    # ── Source channel ────────────────────────────────────────────────────────
    SOURCE_RESERVATION = 'reservation'
    SOURCE_DEMAND_ITEM = 'demand_item'
    SOURCE_SHORTAGE    = 'shortage_item'
    SOURCE_MARKET      = 'market_shortage'
    SOURCE_MANUAL      = 'manual'
    SOURCE_CHOICES = [
        (SOURCE_RESERVATION, 'حجز عميل'),
        (SOURCE_DEMAND_ITEM, 'طلب طلب (Demand)'),
        (SOURCE_SHORTAGE,    'قائمة نواقص فرع'),
        (SOURCE_MARKET,      'كاشف نواقص السوق'),
        (SOURCE_MANUAL,      'يدوي'),
    ]

    # ── Provenance class — tells the reconciler HOW to combine this signal ─────
    CLASS_CUSTOMER    = 'customer_commitment'
    CLASS_BRANCH      = 'branch_replenishment'
    CLASS_STATISTICAL = 'statistical'
    CLASS_CHOICES = [
        (CLASS_CUSTOMER,    'التزام عميل (تُجمَع)'),
        (CLASS_BRANCH,      'طلب فرع (تُدمَج المكرَّرات)'),
        (CLASS_STATISTICAL, 'مؤشر سوق (إرشادي)'),
    ]

    # ── Lifecycle ──────────────────────────────────────────────────────────────
    STATUS_OPEN       = 'open'
    STATUS_FULFILLED  = 'fulfilled'
    STATUS_CANCELLED  = 'cancelled'
    STATUS_SUPERSEDED = 'superseded'   # the source is no longer an active demand
    STATUS_CHOICES = [
        (STATUS_OPEN,       'مفتوح'),
        (STATUS_FULFILLED,  'مُلبّى'),
        (STATUS_CANCELLED,  'ملغى'),
        (STATUS_SUPERSEDED, 'متجاوَز'),
    ]

    # ── What / where / who ─────────────────────────────────────────────────────
    item     = models.ForeignKey('catalog.Item', on_delete=models.CASCADE,
                                 null=True, blank=True, related_name='demand_signals',
                                 verbose_name='الصنف')
    raw_name = models.CharField(max_length=300, blank=True,
                                verbose_name='الاسم الخام',
                                help_text='يُستخدم عندما لا يكون الصنف مطابَقاً بعد')
    branch   = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                 null=True, blank=True, related_name='demand_signals',
                                 verbose_name='الفرع',
                                 help_text='فارغ = طلب على مستوى الشبكة')
    customer = models.ForeignKey('customers.Customer', on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='demand_signals',
                                 verbose_name='العميل')
    qty      = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                   verbose_name='الكمية المطلوبة')

    # ── Provenance (idempotency key) ───────────────────────────────────────────
    source_type      = models.CharField(max_length=20, choices=SOURCE_CHOICES, db_index=True,
                                        verbose_name='نوع المصدر')
    source_ref       = models.CharField(max_length=64, verbose_name='مرجع المصدر',
                                        help_text='معرّف السطر المصدري (idempotency)')
    provenance_class = models.CharField(max_length=24, choices=CLASS_CHOICES, db_index=True,
                                        verbose_name='فئة المصدر')

    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_OPEN, db_index=True, verbose_name='الحالة')

    # When the underlying demand was actually expressed (not when we ingested it).
    source_created_at = models.DateTimeField(null=True, blank=True,
                                             verbose_name='تاريخ نشوء الطلب')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'إشارة طلب'
        verbose_name_plural = 'إشارات الطلب'
        constraints = [
            models.UniqueConstraint(fields=['source_type', 'source_ref'],
                                    name='unique_demand_signal_source'),
        ]
        indexes = [
            models.Index(fields=['item', 'status'],   name='ds_item_status_idx'),
            models.Index(fields=['branch', 'status'], name='ds_branch_status_idx'),
            models.Index(fields=['provenance_class', 'status'], name='ds_class_status_idx'),
            models.Index(fields=['item', 'branch', 'status'], name='ds_item_branch_status_idx'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        label = self.item_id and (self.item.name if self.item else '') or self.raw_name
        return f'{self.get_source_type_display()} · {label} × {self.qty} [{self.status}]'


# ═══════════════════════════════════════════════════════════════════════════════
# AVAILABILITY INBOX (supplier PUSH) — the sibling of shortage.ShortageList.
#
# A branch shortage list is a branch PULL ("we need these"). An availability batch is
# a supplier PUSH ("these are available"). They share the SAME ingestion pipeline
# (apps/supply/ingest.py — parse → match → learn) and OCR (apps/vision), but supplier
# availability carries economics a shortage line never should (price / FOC / expiry /
# supplier item code), so it lives in its own models rather than overloading ShortageItem.
# ═══════════════════════════════════════════════════════════════════════════════

class AvailabilityBatch(models.Model):
    """One supplier availability announcement — a WhatsApp paste, a screenshot, an Excel
    file, etc. Preserves the ORIGINAL content alongside the parsed lines for audit (§3),
    and a content fingerprint for duplicate-import detection (§32)."""

    SOURCE_WHATSAPP = 'whatsapp'
    SOURCE_IMAGE    = 'image'
    SOURCE_EXCEL    = 'excel'
    SOURCE_CSV      = 'csv'
    SOURCE_TEXT     = 'text'
    SOURCE_EMAIL    = 'email'
    SOURCE_MANUAL   = 'manual'
    SOURCE_CHOICES = [
        (SOURCE_WHATSAPP, 'واتساب'),
        (SOURCE_IMAGE,    'صورة / لقطة'),
        (SOURCE_EXCEL,    'إكسل'),
        (SOURCE_CSV,      'CSV'),
        (SOURCE_TEXT,     'نص'),
        (SOURCE_EMAIL,    'بريد'),
        (SOURCE_MANUAL,   'يدوي'),
    ]

    STATUS_OPEN     = 'open'        # imported, under review
    STATUS_REVIEWED = 'reviewed'    # matches confirmed
    STATUS_ACTIONED = 'actioned'    # fed into sourcing / an order was generated
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = [
        (STATUS_OPEN,     'قيد المراجعة'),
        (STATUS_REVIEWED, 'تمت المراجعة'),
        (STATUS_ACTIONED, 'تم التنفيذ'),
        (STATUS_ARCHIVED, 'مؤرشف'),
    ]

    # ── Supplier (may be unresolved — resolution is best-effort) ────────────────
    supplier      = models.ForeignKey('invoices.VendorProfile', on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='availability_batches',
                                      verbose_name='المورد')
    supplier_name = models.CharField(max_length=255, blank=True,
                                     verbose_name='اسم المورد كما ورد')

    source        = models.CharField(max_length=12, choices=SOURCE_CHOICES,
                                     default=SOURCE_WHATSAPP, verbose_name='المصدر')
    status        = models.CharField(max_length=12, choices=STATUS_CHOICES,
                                     default=STATUS_OPEN, db_index=True, verbose_name='الحالة')

    # Original content preserved for auditability (§3).
    raw_content   = models.TextField(blank=True, verbose_name='المحتوى الأصلي')
    source_image  = models.ImageField(upload_to='supply/availability/%Y/%m/',
                                      null=True, blank=True, verbose_name='صورة المصدر')
    # Normalized-content hash → duplicate-import detection (§32). Not unique: a real
    # repeated announcement is legitimate; we WARN, never silently drop.
    raw_fingerprint = models.CharField(max_length=64, blank=True, db_index=True,
                                       verbose_name='بصمة المحتوى')

    operator   = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='availability_batches',
                                   verbose_name='المُدخِل')
    notes      = models.TextField(blank=True)

    # Which branches this offer can serve (a medical warehouse near some branches only).
    # [] = every branch — the company-level total need (the default).
    branch_scope = models.JSONField(default=list, blank=True, verbose_name='الفروع المستهدفة')

    # Finalized: matches / lines / scope can't be edited until someone unlocks it (with a
    # reason). Every lock, unlock and edit is in the audit log (AuditLog, model
    # AvailabilityBatch) — who / what / when / why / before → after.
    locked_at  = models.DateTimeField(null=True, blank=True, verbose_name='أُقفلت في')
    locked_by  = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+', verbose_name='أقفلها')
    lock_note  = models.CharField(max_length=255, blank=True, verbose_name='ملاحظة الإقفال')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_locked(self) -> bool:
        return self.locked_at is not None

    class Meta:
        verbose_name        = 'دفعة إتاحة مورد'
        verbose_name_plural = 'دفعات إتاحة الموردين'
        ordering            = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at'], name='ab_status_created_idx'),
            models.Index(fields=['supplier', '-created_at'], name='ab_supplier_created_idx'),
        ]

    def __str__(self):
        return f'إتاحة {self.supplier_name or self.supplier_id or "?"} — {self.created_at:%Y-%m-%d}'


class AvailabilityLine(models.Model):
    """One offered product in an AvailabilityBatch. The item match reuses the shared
    ingest/matching pipeline; supplier economics are all OPTIONAL (missing is allowed —
    "Recormon 4000 available" is a valid signal with no qty/price, §4)."""

    SOURCE_CHOICES = [
        ('manual', 'يدوي'), ('bulk', 'استيراد نصي'),
        ('ocr', 'OCR'), ('file', 'ملف'),
    ]

    batch    = models.ForeignKey(AvailabilityBatch, on_delete=models.CASCADE,
                                 related_name='lines', verbose_name='الدفعة')

    # ── Item resolution (shared pipeline) ──────────────────────────────────────
    raw_text = models.CharField(max_length=300, verbose_name='النص كما ورد')
    item     = models.ForeignKey('catalog.Item', on_delete=models.SET_NULL,
                                 null=True, blank=True, related_name='+', verbose_name='الصنف المطابق')
    match_score  = models.FloatField(null=True, blank=True, verbose_name='نسبة التطابق')
    match_reason = models.JSONField(default=dict, blank=True, verbose_name='سبب المطابقة')
    is_confirmed = models.BooleanField(default=False, verbose_name='مُؤكَّد')
    is_unmatched = models.BooleanField(default=False, verbose_name='غير مطابق')

    # ── Supplier economics (all optional — missing allowed) ─────────────────────
    supplier_qty      = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True,
                                            verbose_name='الكمية المتاحة لدى المورد')
    price             = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True,
                                            verbose_name='السعر المعروض')
    discount_pct      = models.DecimalField(max_digits=7, decimal_places=3, null=True, blank=True,
                                            verbose_name='الخصم %')
    foc_qty           = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True,
                                            verbose_name='البونص / الكمية المجانية')
    expiry            = models.CharField(max_length=20, blank=True, verbose_name='الصلاحية (كما وردت)')
    supplier_item_code = models.CharField(max_length=40, blank=True, verbose_name='كود المورد للصنف')

    source   = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='bulk',
                                verbose_name='مصدر الإدخال')
    notes    = models.CharField(max_length=300, blank=True)
    # One supplier line can offer several products ("بيبيلاك 1....2....3"). Matching it to
    # several items SPLITS it: the original keeps the first item, each further item is a
    # sibling line (same raw text + economics) pointing here — so every consumer (cases,
    # sourcing, order lists, KPIs) still sees exactly one item per line.
    split_from = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True,
                                   related_name='siblings', verbose_name='مقسوم من سطر')

    confirmed_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='confirmed_availability_lines')
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'صنف إتاحة'
        verbose_name_plural = 'أصناف الإتاحة'
        ordering            = ['id']
        indexes = [
            models.Index(fields=['batch', 'is_confirmed'], name='al_batch_confirmed_idx'),
            models.Index(fields=['item'], name='al_item_idx'),
        ]

    def __str__(self):
        return f'{self.raw_text} (متاح {self.supplier_qty if self.supplier_qty is not None else "?"})'


class SupplierFileLayout(models.Model):
    """How one supplier's Excel / CSV availability file is laid out — which column is the
    name, code, barcode, quantity, price, bonus, discount, expiry. Confirmed once by a
    person; every later file with the same header row imports straight away
    (apps/supply/file_layouts.py)."""
    ROLES = ['name', 'code', 'barcode', 'qty', 'price', 'foc', 'discount', 'expiry', 'ignore']

    supplier_key = models.CharField(max_length=120, db_index=True,
                                    verbose_name='المورد (كود SOFTECH أو الاسم)')
    vendor       = models.ForeignKey('invoices.VendorProfile', on_delete=models.CASCADE,
                                     null=True, blank=True, related_name='file_layouts')
    signature    = models.CharField(max_length=500, verbose_name='بصمة صف العناوين')
    headers      = models.JSONField(default=list, blank=True)
    header_row   = models.PositiveSmallIntegerField(default=0, verbose_name='رقم صف العناوين')
    mapping      = models.JSONField(default=dict, verbose_name='الأعمدة')   # {"0": "name", …}
    use_count    = models.PositiveIntegerField(default=1)
    updated_by   = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='+')
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'ترتيب أعمدة ملف مورد'
        verbose_name_plural = 'ترتيبات أعمدة ملفات الموردين'
        unique_together     = ('supplier_key', 'signature')

    def __str__(self):
        return f'{self.supplier_key}: {self.mapping}'


# ═══════════════════════════════════════════════════════════════════════════════
# SUPPLY CASE — the durable operational case for one unresolved need (§16).
#
# One OPEN case per (item, branch) [branch NULL = network-level, e.g. a market-shortage
# item]. A case survives across days: processing today's WhatsApp list never makes it
# disappear — it closes only when the need is actually resolved (net requirement 0 on a
# real demand run) or a human closes it with a reason. The case stores a SNAPSHOT of the
# last recommendation (apps/supply/engine) for the queue + audit; it never recomputes.
# ═══════════════════════════════════════════════════════════════════════════════

class SupplyCase(models.Model):
    STATUS_DETECTED            = 'detected'
    STATUS_SEARCHING           = 'searching'
    STATUS_AVAILABILITY_FOUND  = 'availability_found'
    STATUS_AWAITING_DECISION   = 'awaiting_decision'
    STATUS_TRANSFER_PENDING    = 'transfer_pending'
    STATUS_ORDERED             = 'ordered'
    STATUS_PARTIALLY_FULFILLED = 'partially_fulfilled'
    STATUS_RECEIVED            = 'received'
    STATUS_FULFILLED           = 'fulfilled'
    STATUS_CANCELLED           = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DETECTED,            'مُكتشَف'),
        (STATUS_SEARCHING,           'جارٍ البحث'),
        (STATUS_AVAILABILITY_FOUND,  'وُجد توفّر لدى مورد'),
        (STATUS_AWAITING_DECISION,   'بانتظار قرار'),
        (STATUS_TRANSFER_PENDING,    'تحويل داخلي قيد التنفيذ'),
        (STATUS_ORDERED,             'تم الطلب من مورد'),
        (STATUS_PARTIALLY_FULFILLED, 'مُلبّى جزئياً'),
        (STATUS_RECEIVED,            'تم الاستلام'),
        (STATUS_FULFILLED,           'مُلبّى ✅'),
        (STATUS_CANCELLED,           'ملغى'),
    ]
    # The engine may move a case only among these; human statuses are never overwritten.
    AUTO_STATUSES = frozenset({STATUS_DETECTED, STATUS_SEARCHING,
                               STATUS_AVAILABILITY_FOUND, STATUS_AWAITING_DECISION})
    TERMINAL_STATUSES = frozenset({STATUS_FULFILLED, STATUS_CANCELLED})
    OPEN_STATUSES = frozenset(s for s, _ in STATUS_CHOICES) - TERMINAL_STATUSES

    item   = models.ForeignKey('catalog.Item', on_delete=models.CASCADE,
                               related_name='supply_cases', verbose_name='الصنف')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                               null=True, blank=True, related_name='supply_cases',
                               verbose_name='الفرع', help_text='فارغ = حالة على مستوى الشبكة')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES,
                              default=STATUS_DETECTED, db_index=True, verbose_name='الحالة')

    # ── Denormalized from the last recommendation (queue sorting / filtering) ────
    required_qty    = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='الاحتياج الصافي')
    residual_gap    = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='فجوة الشراء الخارجي')
    internal_cover  = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='تغطية داخلية مقترحة')
    customer_demand = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='طلب عملاء منتظرين')
    current_stock   = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='الرصيد الحالي')
    scarcity_score  = models.PositiveSmallIntegerField(default=0, db_index=True,
                                                       verbose_name='درجة الندرة')
    is_urgent       = models.BooleanField(default=False, db_index=True, verbose_name='عاجل')
    has_availability = models.BooleanField(default=False, db_index=True,
                                           verbose_name='يوجد توفّر لدى مورد')
    availability_lines = models.ManyToManyField('AvailabilityLine', blank=True,
                                                related_name='supply_cases',
                                                verbose_name='عروض الموردين المطابقة')

    last_ledger  = models.JSONField(default=dict, blank=True, verbose_name='آخر دفتر كميات')
    last_reasons = models.JSONField(default=list, blank=True, verbose_name='آخر أسباب التوصية')
    # Filled by execution (Phase 5): {'transfer_requests': [...], 'isr_pushes': [...]}.
    execution_refs = models.JSONField(default=dict, blank=True, verbose_name='مراجع التنفيذ')

    assigned_to = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='supply_cases',
                                    verbose_name='المسؤول')
    close_reason = models.CharField(max_length=255, blank=True, verbose_name='سبب الإغلاق')
    notes        = models.TextField(blank=True)

    first_detected_at = models.DateTimeField(auto_now_add=True, db_index=True,
                                             verbose_name='أول اكتشاف')
    last_evaluated_at = models.DateTimeField(null=True, blank=True, verbose_name='آخر تقييم')
    status_changed_at = models.DateTimeField(null=True, blank=True, verbose_name='آخر تغيير حالة')
    closed_at         = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الإغلاق')
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'حالة نقص / توريد'
        verbose_name_plural = 'حالات النقص والتوريد'
        ordering            = ['-is_urgent', '-scarcity_score', 'first_detected_at']
        constraints = [
            # One OPEN case per (item, branch). NULL branches are distinct in a unique
            # index, so network cases get their own partial constraint on item alone.
            models.UniqueConstraint(
                fields=['item', 'branch'],
                condition=models.Q(branch__isnull=False) & ~models.Q(status__in=['fulfilled', 'cancelled']),
                name='uniq_open_supply_case_branch'),
            models.UniqueConstraint(
                fields=['item'],
                condition=models.Q(branch__isnull=True) & ~models.Q(status__in=['fulfilled', 'cancelled']),
                name='uniq_open_supply_case_network'),
        ]
        indexes = [
            models.Index(fields=['status', 'is_urgent', 'scarcity_score'], name='sc_queue_idx'),
            models.Index(fields=['item', 'branch'], name='sc_item_branch_idx'),
        ]

    def __str__(self):
        where = self.branch.name if self.branch_id else 'الشبكة'
        return f'{self.item} @ {where} [{self.get_status_display()}]'

    @property
    def is_open(self) -> bool:
        return self.status not in self.TERMINAL_STATUSES

    @property
    def days_open(self) -> int:
        from django.utils import timezone
        end = self.closed_at or timezone.now()
        return max(0, (end - self.first_detected_at).days) if self.first_detected_at else 0


# ═══════════════════════════════════════════════════════════════════════════════
# SUPPLY DECISION — one consequential human decision on a recommendation (§40 / Phase 5).
#
# Records "system recommended vs human decided vs actual outcome" for every internal
# transfer draft and every supplier order generated from this module, with the override
# reason when the human deviated. It is also:
#   • the IDEMPOTENCY guard — a unique key per submitted action, so a double-click / retry
#     never creates a second transfer draft or a second order (§31/§32)
#   • the PENDING-ORDER ledger — open purchase decisions count as confirmed incoming in
#     net_demand, so the same need is never ordered twice (§14)
# Nothing here writes SOFTECH: transfers become DRAFT TransferRequests for the transfers
# team's normal flow; purchases become a WhatsApp/Excel order list.
# ═══════════════════════════════════════════════════════════════════════════════

class SupplyDecision(models.Model):
    KIND_INTERNAL_TRANSFER = 'internal_transfer'
    KIND_PURCHASE          = 'purchase'
    KIND_CHOICES = [
        (KIND_INTERNAL_TRANSFER, 'تحويل داخلي (مسودة)'),
        (KIND_PURCHASE,          'طلب شراء من مورد'),
    ]

    # Receipt tracking for purchases (open = ordered, not yet received → pending incoming).
    RECEIPT_OPEN      = 'open'
    RECEIPT_RECEIVED  = 'received'
    RECEIPT_CANCELLED = 'cancelled'
    RECEIPT_CHOICES = [
        (RECEIPT_OPEN, 'بانتظار الاستلام'),
        (RECEIPT_RECEIVED, 'تم الاستلام'),
        (RECEIPT_CANCELLED, 'ملغى'),
    ]

    kind   = models.CharField(max_length=20, choices=KIND_CHOICES, db_index=True)
    case   = models.ForeignKey(SupplyCase, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='decisions', verbose_name='الحالة')
    item   = models.ForeignKey('catalog.Item', on_delete=models.CASCADE,
                               related_name='supply_decisions', verbose_name='الصنف')
    branch = models.ForeignKey('branches.Branch', on_delete=models.SET_NULL,
                               null=True, blank=True, related_name='supply_decisions',
                               verbose_name='الفرع المستفيد')

    # ── Recommended vs decided ──────────────────────────────────────────────────
    recommended_qty = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='الكمية الموصى بها')
    decided_qty     = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='الكمية المعتمدة')
    is_override     = models.BooleanField(default=False, db_index=True, verbose_name='تجاوز للتوصية')
    override_reason = models.CharField(max_length=255, blank=True, verbose_name='سبب التجاوز')

    # ── Purchase economics (kind=purchase) ──────────────────────────────────────
    supplier          = models.ForeignKey('invoices.VendorProfile', on_delete=models.SET_NULL,
                                          null=True, blank=True, related_name='supply_decisions')
    supplier_name     = models.CharField(max_length=255, blank=True)
    availability_line = models.ForeignKey(AvailabilityLine, on_delete=models.SET_NULL,
                                          null=True, blank=True, related_name='decisions')
    unit_price     = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    foc_qty        = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    effective_cost = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    receipt_status = models.CharField(max_length=10, choices=RECEIPT_CHOICES, blank=True,
                                      db_index=True, verbose_name='حالة الاستلام')
    received_qty   = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)

    # ── Provenance / execution ──────────────────────────────────────────────────
    recommendation_snapshot = models.JSONField(default=dict, blank=True,
                                               verbose_name='لقطة التوصية وقت القرار')
    revalidation = models.JSONField(default=dict, blank=True,
                                    verbose_name='نتيجة إعادة التحقق قبل التنفيذ')
    result_refs  = models.JSONField(default=dict, blank=True,
                                    verbose_name='مراجع التنفيذ (طلبات تحويل / طلب شراء)')
    order_ref    = models.CharField(max_length=64, blank=True, db_index=True,
                                    verbose_name='مرجع قائمة الطلب')
    idempotency_key = models.CharField(max_length=100, unique=True, null=True, blank=True,
                                       verbose_name='مفتاح منع التكرار')

    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='supply_decisions')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'قرار توريد'
        verbose_name_plural = 'قرارات التوريد'
        ordering            = ['-created_at']
        indexes = [
            models.Index(fields=['kind', 'receipt_status', 'item'], name='sd_pending_idx'),
            models.Index(fields=['case', '-created_at'], name='sd_case_idx'),
        ]

    def __str__(self):
        return f'{self.get_kind_display()} · {self.item_id} × {self.decided_qty}'


# ═══════════════════════════════════════════════════════════════════════════════
# BRANCH REQUESTS (طلبات واتساب) — urgent needs branches post in WhatsApp GROUPS.
#
# The Meta Cloud API cannot read groups, so staff paste the chat (or a photo). The
# paste is split into messages → item fragments → catalog candidates
# (apps/supply/branch_requests.py) and reviewed line by line. Confirming creates the
# branch's shortage.ShortageList (which already feeds DemandSignal → supply cases); the
# availability analysis reuses the ISR fulfilment engine. Nothing here writes SOFTECH.
# ═══════════════════════════════════════════════════════════════════════════════

class BranchRequest(models.Model):
    SOURCE_WHATSAPP = 'whatsapp'
    SOURCE_CHOICES = [(SOURCE_WHATSAPP, 'واتساب')]

    STATUS_DRAFT     = 'draft'       # extracted, under review
    STATUS_CONFIRMED = 'confirmed'   # shortage list created
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [(STATUS_DRAFT, 'قيد المراجعة'), (STATUS_CONFIRMED, 'مؤكَّد'),
                      (STATUS_CANCELLED, 'ملغى')]

    branch     = models.ForeignKey('branches.Branch', on_delete=models.PROTECT,
                                   related_name='branch_requests', verbose_name='الفرع')
    source     = models.CharField(max_length=12, choices=SOURCE_CHOICES, default=SOURCE_WHATSAPP)
    group_name = models.CharField(max_length=200, blank=True, verbose_name='اسم المجموعة')
    raw_text   = models.TextField(blank=True, verbose_name='النص الملصوق')
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT,
                                  db_index=True)
    shortage_list = models.ForeignKey('shortage.ShortageList', on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='branch_requests')
    created_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='+')
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='+')
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = 'طلب فرع (واتساب)'
        verbose_name_plural = 'طلبات الفروع (واتساب)'
        ordering            = ['-created_at']

    def __str__(self):
        return f'BranchRequest {self.pk} · br{getattr(self.branch, "softech_branch_id", "")} · {self.status}'


class BranchRequestLine(models.Model):
    KIND_ITEM = 'item'
    KIND_NOTE = 'note'                # phone, name, reference, remark — kept for context
    KIND_CHOICES = [(KIND_ITEM, 'صنف'), (KIND_NOTE, 'ملاحظة')]

    UNIT_PACK  = 'pack'
    UNIT_STRIP = 'strip'
    UNIT_CHOICES = [(UNIT_PACK, 'علبة'), (UNIT_STRIP, 'شريط')]

    request    = models.ForeignKey(BranchRequest, on_delete=models.CASCADE, related_name='lines')
    position   = models.PositiveIntegerField(default=0)
    msg_index  = models.PositiveIntegerField(default=0)
    msg_sender = models.CharField(max_length=120, blank=True)
    msg_time   = models.CharField(max_length=40, blank=True)          # as written in the chat
    from_ocr   = models.BooleanField(default=False)

    raw_text   = models.CharField(max_length=500, verbose_name='كما كُتب')
    match_text = models.CharField(max_length=300, blank=True, verbose_name='النص المستخدم للمطابقة')
    kind       = models.CharField(max_length=6, choices=KIND_CHOICES, default=KIND_ITEM)

    qty        = models.DecimalField(max_digits=10, decimal_places=3, default=1)
    qty_unit   = models.CharField(max_length=6, choices=UNIT_CHOICES, default=UNIT_PACK)
    qty_source = models.CharField(max_length=10, default='default',
                                  help_text='unit | count | default | manual')
    all_variants = models.BooleanField(default=False, verbose_name='كل الأنواع')

    item       = models.ForeignKey('catalog.Item', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    # Several picks for one line ("Strepsils" → two chosen flavours): `item` is the first
    # pick, these are the others. Each gets the line's quantity. Ignored when all_variants.
    extra_items = models.ManyToManyField('catalog.Item', blank=True, related_name='+')
    score      = models.FloatField(null=True, blank=True)
    flags      = models.JSONField(default=list, blank=True)
    candidates = models.JSONField(default=list, blank=True)           # variant / alternative picks
    confirmed  = models.BooleanField(default=False)
    picked_by_user = models.BooleanField(default=False)

    class Meta:
        ordering = ['request', 'position']

    def __str__(self):
        return f'{self.request_id}#{self.position} {self.raw_text[:40]}'
