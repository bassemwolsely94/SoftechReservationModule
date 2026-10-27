"""
apps/invoices/models.py

VendorProfile     — supplier master with discount ranges & aliases.
VendorItemMapping — learning table: (vendor, raw_name_normalized) → Item.
SupplierInvoice   — a scanned / manually entered supplier invoice.
InvoiceLine       — one item line on that invoice.

OCR workflow:
  1. Upload image → SupplierInvoice created with status='pending'
  2. Background thread runs pytesseract/easyocr
  3. Lines extracted → InvoiceLine rows created with raw_text
  4. Fuzzy matcher (reuses shortage.matching) + VendorItemMapping lookup
  5. User reviews & confirms matches, adjusts discount rates
  6. Invoice finalized → Excel/CSV export
"""
import uuid

from django.db import models


# ── Vendor master ──────────────────────────────────────────────────────────────

class VendorProfile(models.Model):
    name                 = models.CharField(max_length=200, unique=True, verbose_name='اسم المورد')
    # SOFTECH personsdata.personcode (ptcode='20'). Required before this vendor's
    # invoices can be written back to SOFTECH (= stktransm.cust_branch_code / line suppliercode).
    softech_personcode   = models.CharField(max_length=8, blank=True, db_index=True,
                                             verbose_name='كود المورد في SOFTECH')
    # Only "main"/official distributors (those that issue official invoices) are
    # processed for sourcing, code injection/recall, and the supplier exports.
    # Dynamically toggled — unofficial suppliers are skipped (wasteful to process).
    is_main              = models.BooleanField(default=False, db_index=True,
                                               verbose_name='مورد رئيسي (رسمي)')
    aliases              = models.TextField(blank=True,
                                             help_text='أسماء بديلة مفصولة بفاصلة',
                                             verbose_name='أسماء بديلة')
    typical_discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                                verbose_name='خصم نموذجي %')
    # Per-distributor OCR extraction hints, tuned per main distributor and learned over
    # time (code format, FOC/bonus style, tax handling, free-text). Injected into the
    # extraction prompt when this vendor is known at upload time. See ocr.vendor_prompt_hints.
    #   { "code_format": "alphanumeric|numeric", "foc_style": "same_line|separate_line|none",
    #     "tax_note": "...", "notes": "free text" }
    ocr_profile          = models.JSONField(default=dict, blank=True,
                                            verbose_name='ملف قراءة الفاتورة (OCR)')
    notes                = models.TextField(blank=True, verbose_name='ملاحظات')
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'مورد'
        verbose_name_plural = 'الموردون'
        ordering            = ['name']

    def __str__(self):
        return self.name


# ── Vendor-item learning table ─────────────────────────────────────────────────

class VendorItemMapping(models.Model):
    """
    Remembers confirmed raw vendor product name → ERP Item mappings.
    When a user confirms an invoice line the mapping is stored/incremented
    so future invoices from the same vendor skip fuzzy matching for that name.
    """
    vendor               = models.ForeignKey(VendorProfile, on_delete=models.SET_NULL,
                                              null=True, blank=True,
                                              related_name='item_mappings',
                                              verbose_name='المورد')
    raw_name_normalized  = models.CharField(max_length=300, db_index=True,
                                             verbose_name='الاسم المُعيَّر')
    # Supplier's own printed product code (when present it is a far stronger key than
    # the fuzzy name — matched first). Learned alongside the name on confirm.
    vendor_item_code     = models.CharField(max_length=100, blank=True, db_index=True,
                                             verbose_name='كود الصنف (المورد)')
    item                 = models.ForeignKey('catalog.Item', on_delete=models.CASCADE,
                                             related_name='+', verbose_name='الصنف')
    use_count            = models.PositiveIntegerField(default=1,
                                                        verbose_name='عدد الاستخدامات')
    created_by           = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                              on_delete=models.SET_NULL, related_name='+',
                                              verbose_name='أُنشئ بواسطة')
    created_at           = models.DateTimeField(auto_now_add=True)
    updated_at           = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'ربط صنف بمورد'
        verbose_name_plural = 'ربط الأصناف بالموردين'
        unique_together     = [['vendor', 'raw_name_normalized']]

    def __str__(self):
        return f'{self.raw_name_normalized} → {self.item}'


# ── Multi-invoice bundle (document stack) ──────────────────────────────────────

class InvoiceBatch(models.Model):
    """
    A single uploaded PDF (or image) that may contain MANY separate invoices —
    the normal case for the main distributors, whose daily PDF is a stack of
    one-page invoices (a 50-page Ramco PDF observed = ~50 distinct invoices).

    This is purely an INGESTION container upstream of the existing pipeline: it
    is rendered, probed and split, then fanned out into ordinary SupplierInvoice
    rows (``invoices`` below) that run the normal OCR/match/review/post flow.
    It never touches SOFTECH itself — only its child invoices do, through the
    existing writer. Not a parallel invoice app.
    """
    STATUS = [
        ('pending',    'في الانتظار'),
        ('processing', 'جاري التقسيم والمعالجة'),
        ('ready',      'تم التقسيم — قيد المراجعة'),
        ('failed',     'فشل التقسيم'),
    ]

    branch       = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                      related_name='invoice_batches', verbose_name='الفرع')
    vendor       = models.ForeignKey(VendorProfile, on_delete=models.SET_NULL,
                                      null=True, blank=True, related_name='invoice_batches',
                                      verbose_name='المورد (افتراضي للحزمة)')
    doc_kind     = models.CharField(max_length=10, default='purchase',
                                    choices=[('purchase', 'شراء'), ('return', 'مرتجع')],
                                    verbose_name='نوع المستند')
    # OCR engine for extracting the lines of each detected invoice: '' = auto
    # (Gemini when a key is set, else the free easyOCR engine). See engines.py.
    OCR_ENGINE = [('', 'تلقائي'), ('gemini', 'Gemini (مدفوع)'),
                  ('tesseract', 'Tesseract (مجاني)'), ('easyocr', 'easyOCR (مجاني)')]
    ocr_engine   = models.CharField(max_length=12, blank=True, default='', choices=OCR_ENGINE,
                                    verbose_name='محرك القراءة')
    created_by   = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                      null=True, related_name='invoice_batches',
                                      verbose_name='رُفعت بواسطة')
    status       = models.CharField(max_length=20, choices=STATUS, default='pending',
                                    db_index=True, verbose_name='الحالة')
    source_file  = models.FileField(upload_to='invoice_bundles/', null=True, blank=True,
                                    verbose_name='ملف الحزمة (PDF)')
    page_count      = models.PositiveIntegerField(default=0, verbose_name='عدد الصفحات')
    detected_count  = models.PositiveIntegerField(default=0, verbose_name='عدد الفواتير المكتشفة')
    processed_count = models.PositiveIntegerField(default=0, verbose_name='تمت معالجتها')
    # splitter.summarize() output: one entry per detected invoice (pages, doc no.,
    # type, date, confidence) — the audit trail for how the bundle was divided.
    split_summary   = models.JSONField(default=list, blank=True, verbose_name='تفاصيل التقسيم')
    # document-robustness flags for the whole bundle (blank_pages, rotated_pages…)
    flags           = models.JSONField(default=list, blank=True, verbose_name='ملاحظات المعالجة')
    error           = models.TextField(blank=True)
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'حزمة فواتير'
        verbose_name_plural = 'حزم الفواتير'
        ordering            = ['-created_at']

    def __str__(self):
        return f'حزمة #{self.id} — {self.detected_count} فاتورة / {self.page_count} صفحة'


# ── Purchase Order / GRN (separate, advisory workflow) ──────────────────────────

class PurchaseOrder(models.Model):
    """A purchase order the pharmacy placed with a supplier. Used ONLY for an
    optional, advisory goods-received check against the supplier's invoice — it is
    deliberately decoupled from the SOFTECH posting flow (never gates a post).
    Low-traffic: most invoices are posted without a PO."""
    STATUS = [('open', 'مفتوح'), ('received', 'تم الاستلام'),
              ('closed', 'مغلق'), ('cancelled', 'ملغي')]
    branch     = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                   related_name='purchase_orders', verbose_name='الفرع')
    vendor     = models.ForeignKey(VendorProfile, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='purchase_orders', verbose_name='المورد')
    po_number  = models.CharField(max_length=50, verbose_name='رقم أمر الشراء')
    status     = models.CharField(max_length=12, choices=STATUS, default='open', db_index=True,
                                  verbose_name='الحالة')
    notes      = models.TextField(blank=True, verbose_name='ملاحظات')
    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True,
                                   related_name='purchase_orders', verbose_name='أُنشئ بواسطة')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'أمر شراء'
        verbose_name_plural = 'أوامر الشراء'
        ordering = ['-created_at']

    def __str__(self):
        return f'PO {self.po_number} — {self.vendor.name if self.vendor else "?"}'


class PurchaseOrderLine(models.Model):
    po         = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE,
                                   related_name='lines', verbose_name='أمر الشراء')
    item       = models.ForeignKey('catalog.Item', on_delete=models.CASCADE,
                                   related_name='+', verbose_name='الصنف')
    quantity   = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name='الكمية')
    unit_price = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name='سعر الوحدة')
    notes      = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name = 'سطر أمر شراء'
        verbose_name_plural = 'سطور أوامر الشراء'


# ── Invoice ────────────────────────────────────────────────────────────────────

class SupplierInvoice(models.Model):
    STATUS = [
        ('pending',    'في الانتظار'),
        ('processing', 'جاري المعالجة'),
        ('review',     'قيد المراجعة'),
        ('confirmed',  'مُأكَّدة'),
        ('rejected',   'مرفوضة'),
        # ── writeback lifecycle (Track B) ──
        ('queued',     'بانتظار الترحيل'),
        ('pushing',    'جارٍ الترحيل'),
        ('finalized',  'مُرحَّلة إلى ERP'),
        ('push_failed','فشل الترحيل'),
    ]

    DOC_KIND = [
        ('purchase', 'شراء (doccode 10)'),
        ('return',   'مرتجع مورد (doccode 120)'),
    ]

    branch          = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                         related_name='invoices', verbose_name='الفرع')
    # When this invoice was carved out of a multi-invoice PDF bundle, the parent
    # batch and the bundle page numbers it was built from (audit of the split).
    batch           = models.ForeignKey('InvoiceBatch', on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name='invoices',
                                         verbose_name='حزمة المصدر')
    source_pages    = models.JSONField(default=list, blank=True,
                                        verbose_name='صفحات الحزمة')
    # Optional link to a purchase order for the advisory goods-received check
    # (separate workflow; never affects posting).
    po              = models.ForeignKey('PurchaseOrder', on_delete=models.SET_NULL,
                                        null=True, blank=True, related_name='invoices',
                                        verbose_name='أمر الشراء')
    # OCR review flags for this detected invoice (few_lines, low_recall,
    # low_confidence, no_totals…) — see apps/invoices/preprocess.page_quality.
    ocr_flags       = models.JSONField(default=list, blank=True,
                                       verbose_name='تنبيهات القراءة')
    doc_kind        = models.CharField(max_length=10, choices=DOC_KIND, default='purchase',
                                        verbose_name='نوع المستند')
    vendor          = models.ForeignKey(VendorProfile, on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name='invoices',
                                         verbose_name='المورد (ملف)')
    created_by      = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                         null=True, related_name='invoices',
                                         verbose_name='أُنشئت بواسطة')
    status          = models.CharField(max_length=20, choices=STATUS, default='pending',
                                        verbose_name='الحالة')

    # Supplier info (manual or extracted)
    supplier_name   = models.CharField(max_length=200, blank=True, verbose_name='اسم المورد')
    invoice_number  = models.CharField(max_length=50, blank=True, verbose_name='رقم الفاتورة')
    invoice_date    = models.DateField(null=True, blank=True, verbose_name='تاريخ الفاتورة')
    currency        = models.CharField(max_length=10, default='EGP', verbose_name='العملة')

    # Discount at invoice level (applied to all lines unless overridden)
    global_discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                               verbose_name='خصم عام %')
    global_discount_amt = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                               verbose_name='خصم عام بمبلغ')

    # Source file (image or PDF, for OCR)
    source_image    = models.FileField(upload_to='invoice_images/', null=True, blank=True,
                                        verbose_name='ملف الفاتورة (صورة / PDF)')
    raw_ocr_text    = models.TextField(blank=True, verbose_name='نص OCR الخام')
    # Invoice grand-total as READ from the document by OCR — used only to reconcile
    # against the sum of captured lines (anomaly flag); never written to SOFTECH.
    declared_total  = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True,
                                          verbose_name='الإجمالي المقروء من الفاتورة')

    notes           = models.TextField(blank=True, verbose_name='ملاحظات')

    # ── SOFTECH writeback (Track B) ────────────────────────────────────────────
    # Target codes (default from branch at save). The final purchase doc is written
    # to stktransm/stktrans on the branch DB; docnumber from lastdocnumber{in,out}_supp.
    softech_branchcode = models.CharField(max_length=5, blank=True, verbose_name='كود الفرع (SOFTECH)')
    store_code         = models.CharField(max_length=5, blank=True, verbose_name='كود المخزن')
    softech_docnumber  = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True,
                                             verbose_name='رقم المستند في SOFTECH')
    softech_docdate    = models.DateField(null=True, blank=True)
    # For returns (doccode 120): the original purchase docnumber → r_docnumber/r_doccode.
    return_of_docnumber = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True,
                                              verbose_name='مرتجع للمستند رقم')
    # Idempotency marker (stashed in stktransm.vf2 = 'INV<pk>'); prevents a retry duplicating a doc.
    client_token       = models.UUIDField(null=True, blank=True, default=None, editable=False)

    # immutable execution audit (mirrors pos_orders / discount_approvals)
    erp_executed_at = models.DateTimeField(null=True, blank=True)
    erp_payload     = models.JSONField(default=dict, blank=True, verbose_name='الحمولة المُرسلة')
    erp_readback    = models.JSONField(default=dict, blank=True, verbose_name='قراءة التحقق')
    erp_error       = models.TextField(blank=True)

    # Cached thorough duplicate-check summary (writer.check_duplicates), run in the
    # background when the invoice enters review so the LIST can flag re-entries early.
    dup_check       = models.JSONField(default=dict, blank=True, verbose_name='فحص التكرار')
    dup_checked_at  = models.DateTimeField(null=True, blank=True)

    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'فاتورة مورد'
        verbose_name_plural = 'فواتير الموردين'
        ordering            = ['-created_at']

    def __str__(self):
        return f'فاتورة {self.supplier_name or "?"} — {self.invoice_number or self.id}'

    def save(self, *args, **kwargs):
        # Default the SOFTECH target codes from the branch (storecode == branchcode
        # for the main store, per the captured golden template). Never overwrite an
        # explicit value.
        if self.branch_id and not self.softech_branchcode:
            self.softech_branchcode = self.branch.softech_branch_id
        if not self.store_code:
            self.store_code = self.softech_branchcode
        super().save(*args, **kwargs)

    # ── SOFTECH-mapping helpers ────────────────────────────────────────────────
    @property
    def softech_doccode(self):
        return '10' if self.doc_kind == 'purchase' else '120'

    @property
    def softech_counter_column(self):
        # tr_stktransm5 routing (confirmed): purchase→in_supp, return→out_supp.
        return 'lastdocnumberin_supp' if self.doc_kind == 'purchase' else 'lastdocnumberout_supp'

    @property
    def is_locked(self):
        """Immutable once it is being/has been written to SOFTECH."""
        return self.status in ('pushing', 'finalized')

    @property
    def total_before_discount(self):
        return float(sum(l.line_total or 0 for l in self.lines.all()))

    @property
    def total_after_discount(self):
        sub = self.total_before_discount          # already float
        pct = float(self.global_discount_pct or 0)
        amt = float(self.global_discount_amt or 0)
        return sub * (1 - pct / 100) - amt


class InvoiceLine(models.Model):
    invoice         = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE,
                                         related_name='lines', verbose_name='الفاتورة')
    item            = models.ForeignKey('catalog.Item', on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name='+',
                                         verbose_name='الصنف المطابق')
    raw_text        = models.CharField(max_length=500, blank=True, verbose_name='النص الخام')
    manual_name     = models.CharField(max_length=300, blank=True, verbose_name='اسم الصنف')

    # ── Supplier / lot info ────────────────────────────────────────────────────
    manufacturer    = models.CharField(max_length=200, blank=True, verbose_name='اسم المورد/المصنع')
    vendor_item_code= models.CharField(max_length=100, blank=True, verbose_name='كود الصنف (المورد)')
    batch_number    = models.CharField(max_length=100, blank=True, verbose_name='رقم التشغيلة')
    expiry_date     = models.CharField(max_length=50,  blank=True, verbose_name='تاريخ الصلاحية')

    # ── Pricing ────────────────────────────────────────────────────────────────
    quantity             = models.DecimalField(max_digits=10, decimal_places=3, default=1,
                                               verbose_name='الكمية')
    public_price         = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                               verbose_name='سعر الجمهور')
    discount_pct         = models.DecimalField(max_digits=6, decimal_places=3, default=0,
                                               verbose_name='خصم مطابقة %')
    extra_discount_pct   = models.DecimalField(max_digits=6, decimal_places=3, default=0,
                                               verbose_name='خصم إضافي % (خ.ص.د)')
    # خصم خاص (d3) — a third purchase discount applied AFTER the basic + extra ones
    # (compound). The SofTech cost = base × (1−d1)(1−d2)(1−d3).
    special_discount_pct = models.DecimalField(max_digits=6, decimal_places=3, default=0,
                                               verbose_name='خصم خاص %')
    # الضريبة من التكلفة — VAT base is the purchase cost (True) or the base price (False)
    tax_from_cost        = models.BooleanField(default=True, verbose_name='الضريبة من التكلفة')
    unit_price           = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                               verbose_name='سعر الصيدلي')
    discount_amt         = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                               verbose_name='خصم بمبلغ')
    vat_pct                = models.DecimalField(max_digits=5,  decimal_places=2, default=0,
                                                 verbose_name='ضريبة القيمة المضافة %')
    distributor_margin_amt = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                                 verbose_name='هامش الموزع (مبلغ)')
    pharmacist_margin_amt  = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                                 verbose_name='هامش ربح الصيدلي')
    line_total           = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True,
                                               verbose_name='إجمالي صيدلي')
    # FOC / free-bonus packs on this line (printed "10+1" or on a separate bonus line).
    # On push this expands to a 2nd stktrans line at zero cost (see softech_columns.expand_foc).
    bonus_qty            = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                               verbose_name='كمية البونص (هدية)')

    match_score     = models.FloatField(null=True, blank=True, verbose_name='نسبة التطابق')
    ocr_confidence  = models.FloatField(null=True, blank=True, verbose_name='ثقة الاستخراج (OCR)')
    # Set at ingest when the Arabic name and the English generic guess resolve to
    # DIFFERENT catalog items — an "uncertain match, please verify" signal.
    match_review    = models.BooleanField(default=False, verbose_name='مطابقة تحتاج مراجعة')
    # Set when the OCR name matched SEVERAL catalog products — operator must pick one.
    needs_pick      = models.BooleanField(default=False, verbose_name='يحتاج اختيار صنف')
    # Per-line retail-price decision when the invoice public price differs from the
    # item's current catalog price. 'use_new' only flags intent — the master-price
    # write is a separate, approval-gated SOFTECH step (never automatic here).
    PRICE_ACTION = [('keep_old', 'إبقاء سعر البيع الحالي'), ('use_new', 'تحديث سعر البيع')]
    price_action    = models.CharField(max_length=10, choices=PRICE_ACTION, default='keep_old',
                                       verbose_name='قرار سعر البيع')
    is_confirmed    = models.BooleanField(default=False, verbose_name='مُأكَّد')
    notes           = models.CharField(max_length=300, blank=True, verbose_name='ملاحظات')
    order           = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name        = 'سطر فاتورة'
        verbose_name_plural = 'سطور الفواتير'
        ordering            = ['order', 'id']

    def compute_total(self):
        qty       = float(self.quantity or 0)
        net       = float(self.unit_price or 0)
        pub       = float(self.public_price or 0)
        disc_p    = float(self.discount_pct or 0)
        extra_d   = float(self.extra_discount_pct or 0)
        disc_a    = float(self.discount_amt or 0)

        # Derive pharmacist (net) price from public price + discounts if not explicitly set
        if net == 0 and pub > 0:
            net = pub * (1 - disc_p / 100) * (1 - extra_d / 100)

        subtotal = qty * net - disc_a

        # Add VAT on top of the pharmacist subtotal when applicable
        vat = float(self.vat_pct or 0)
        if vat:
            subtotal = subtotal * (1 + vat / 100)

        return round(subtotal, 3)

    def save(self, *args, **kwargs):
        self.line_total = self.compute_total()
        super().save(*args, **kwargs)
