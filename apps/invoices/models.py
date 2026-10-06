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

    match_score     = models.FloatField(null=True, blank=True, verbose_name='نسبة التطابق')
    ocr_confidence  = models.FloatField(null=True, blank=True, verbose_name='ثقة الاستخراج (OCR)')
    # Set at ingest when the Arabic name and the English generic guess resolve to
    # DIFFERENT catalog items — an "uncertain match, please verify" signal.
    match_review    = models.BooleanField(default=False, verbose_name='مطابقة تحتاج مراجعة')
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
