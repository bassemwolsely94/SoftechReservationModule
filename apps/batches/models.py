"""
apps/batches/models.py

FEFO (First-Expired, First-Out) batch tracking layer.

Design:
  StockBatch      — master record per (item × branch × batch_number).
                    Created from SupplierInvoice confirmation; updated by
                    BatchMovement aggregation.  Never deleted — zero-qty batches
                    are retained for full audit history.

  BatchMovement   — immutable ledger.  Every qty change is a new row.
                    Callers must NEVER update qty on StockBatch directly;
                    use BatchService.record_movement() instead.

  NearExpiryAlert — one row per (batch × threshold) to prevent duplicate alerts.

FEFO recommendation:
  BatchService.fefo_batches(item_id, branch_id) returns active batches ordered
  by expiry_date ASC so callers always consume the oldest-expiry stock first.

Integration points:
  • Created from:  apps/invoices (confirmed InvoiceLine)
  • Consumed by:   apps/transfers, apps/delivery, apps/stockcount (future)
  • Alerts sent via: apps/notifications (existing Notification model)
  • Claims via:    apps/approvals (supplier_claim workflow)
"""
from django.db import models
from django.utils import timezone


class StockBatch(models.Model):
    """
    One physical batch (lot) of an item held at a branch.

    Lifecycle:
      receive (invoice confirmed) → [transfers] → [sales/issues] → zero qty
      May be quarantined at any point (quality hold or near expiry).
      Expired batches are flagged automatically by the near-expiry job.
    """
    STORAGE_AMBIENT  = 'ambient'
    STORAGE_FRIDGE   = 'fridge'
    STORAGE_FREEZER  = 'freezer'
    STORAGE_CHOICES  = [
        (STORAGE_AMBIENT, 'درجة حرارة الغرفة'),
        (STORAGE_FRIDGE,  'مبرّد (2–8°C)'),
        (STORAGE_FREEZER, 'مجمّد'),
    ]

    item         = models.ForeignKey(
        'catalog.Item', on_delete=models.PROTECT,
        related_name='batches', verbose_name='الصنف',
    )
    branch       = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT,
        related_name='batches', verbose_name='الفرع',
    )
    batch_number = models.CharField(max_length=100, verbose_name='رقم التشغيلة')
    expiry_date  = models.DateField(db_index=True, verbose_name='تاريخ الصلاحية')

    # Supplier traceability
    vendor       = models.ForeignKey(
        'invoices.VendorProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='batches',
        verbose_name='المورد',
    )
    invoice      = models.ForeignKey(
        'invoices.SupplierInvoice', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='batches',
        verbose_name='فاتورة الاستلام',
    )
    invoice_number = models.CharField(max_length=50, blank=True, verbose_name='رقم الفاتورة')
    manufacturer   = models.CharField(max_length=200, blank=True, verbose_name='المصنّع')

    # Purchase economics (unit = smallest dispensable unit)
    purchase_price = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        verbose_name='سعر الشراء (للوحدة)',
    )

    # Quantities — always updated via BatchMovement, never direct writes
    original_qty = models.DecimalField(
        max_digits=12, decimal_places=3, default=0,
        verbose_name='الكمية الأصلية',
    )
    current_qty  = models.DecimalField(
        max_digits=12, decimal_places=3, default=0,
        db_index=True, verbose_name='الكمية الحالية',
    )

    storage_condition = models.CharField(
        max_length=10, choices=STORAGE_CHOICES, default=STORAGE_AMBIENT,
        verbose_name='شرط التخزين',
    )
    is_quarantined = models.BooleanField(
        default=False, db_index=True, verbose_name='معزولة',
    )
    quarantine_reason = models.TextField(blank=True, verbose_name='سبب العزل')
    is_expired     = models.BooleanField(
        default=False, db_index=True, verbose_name='منتهية الصلاحية',
    )

    # Who received this batch
    received_by  = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='received_batches',
        verbose_name='استلم بواسطة',
    )
    received_at  = models.DateTimeField(default=timezone.now, verbose_name='تاريخ الاستلام')

    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'دفعة مخزون'
        verbose_name_plural = 'دفعات المخزون'
        # A batch_number is unique per (item, branch) — two branches may hold the same lot
        unique_together     = ('item', 'branch', 'batch_number')
        indexes = [
            models.Index(fields=['item', 'branch', 'expiry_date'], name='batch_fefo_idx'),
            models.Index(fields=['expiry_date', 'is_quarantined', 'is_expired'], name='batch_expiry_filter_idx'),
            models.Index(fields=['vendor', 'expiry_date'], name='batch_vendor_expiry_idx'),
        ]
        ordering = ['expiry_date', 'id']

    def __str__(self):
        return f'{self.item.name} | {self.batch_number} | exp {self.expiry_date} | {self.branch}'

    @property
    def days_to_expiry(self):
        return (self.expiry_date - timezone.now().date()).days

    @property
    def expiry_value(self):
        """Current stock value at purchase price — potential loss if expired."""
        return float(self.current_qty) * float(self.purchase_price)

    @property
    def is_active(self):
        return self.current_qty > 0 and not self.is_expired and not self.is_quarantined

    def flag_expired(self):
        if not self.is_expired and self.expiry_date < timezone.now().date():
            self.is_expired = True
            self.save(update_fields=['is_expired', 'updated_at'])


class BatchMovement(models.Model):
    """
    Immutable ledger entry.  Every quantity change produces a new row.
    Never update; never delete.
    """
    TYPE_RECEIVE     = 'receive'
    TYPE_TRANSFER_OUT = 'transfer_out'
    TYPE_TRANSFER_IN  = 'transfer_in'
    TYPE_SALE        = 'sale'
    TYPE_RETURN_IN   = 'return_in'     # customer return (back to stock)
    TYPE_RETURN_OUT  = 'return_out'    # supplier return (batch claim)
    TYPE_ADJUSTMENT  = 'adjustment'    # manual stock adjustment
    TYPE_STOCKCOUNT  = 'stockcount'    # stock count correction
    TYPE_QUARANTINE  = 'quarantine'    # moved to quarantine store
    TYPE_DESTROY     = 'destroy'       # condemned stock disposal

    TYPE_CHOICES = [
        (TYPE_RECEIVE,      'استلام من مورد'),
        (TYPE_TRANSFER_OUT, 'تحويل صادر'),
        (TYPE_TRANSFER_IN,  'تحويل وارد'),
        (TYPE_SALE,         'بيع'),
        (TYPE_RETURN_IN,    'مرتجع من عميل'),
        (TYPE_RETURN_OUT,   'مرتجع لمورد'),
        (TYPE_ADJUSTMENT,   'تسوية يدوية'),
        (TYPE_STOCKCOUNT,   'تصحيح جرد'),
        (TYPE_QUARANTINE,   'تحويل لعزل'),
        (TYPE_DESTROY,      'إتلاف'),
    ]

    batch          = models.ForeignKey(
        StockBatch, on_delete=models.PROTECT,
        related_name='movements', verbose_name='الدفعة',
    )
    movement_type  = models.CharField(
        max_length=15, choices=TYPE_CHOICES, db_index=True,
        verbose_name='نوع الحركة',
    )
    # Positive = stock increase; Negative = stock decrease
    qty_change     = models.DecimalField(
        max_digits=12, decimal_places=3,
        verbose_name='تغيير الكمية',
    )
    qty_after      = models.DecimalField(
        max_digits=12, decimal_places=3,
        verbose_name='الكمية بعد الحركة',
    )

    branch         = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT,
        related_name='batch_movements', verbose_name='الفرع',
    )
    performed_by   = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='batch_movements',
        verbose_name='بواسطة',
    )

    # Generic reference to the triggering record (Transfer, DeliveryOrder, StockCountSession…)
    reference_type = models.CharField(max_length=50, blank=True, verbose_name='نوع المرجع')
    reference_id   = models.PositiveIntegerField(null=True, blank=True, verbose_name='رقم المرجع')

    notes          = models.TextField(blank=True, verbose_name='ملاحظات')
    created_at     = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='وقت الحركة')

    class Meta:
        verbose_name        = 'حركة دفعة'
        verbose_name_plural = 'حركات الدفعات'
        ordering            = ['-created_at']
        indexes = [
            models.Index(fields=['batch', 'created_at'], name='batchmov_batch_time_idx'),
            models.Index(fields=['movement_type', 'created_at'], name='batchmov_type_time_idx'),
            models.Index(fields=['reference_type', 'reference_id'], name='batchmov_ref_idx'),
        ]

    def __str__(self):
        sign = '+' if self.qty_change >= 0 else ''
        return f'{self.batch.batch_number} | {self.get_movement_type_display()} | {sign}{self.qty_change}'


class PurchaseExpiryEntry(models.Model):
    """
    3-year local mirror of SOFTECH purchase-invoice lines (doccode '10') that
    carry an entered expiry date (`stktrans.itemexpirydate`), from suppliers we
    designate as "main" (trusted-expiry distributors / manufacturers).

    WHY THIS EXISTS (physical near-expiry audit engine)
    ---------------------------------------------------
    SOFTECH's current per-batch on-hand table (`stkbalexpiry`) is not reliable —
    expiry data-entry from non-main suppliers is arbitrary, and the current
    on-hand batch↔expiry linkage drifts. Instead of trusting it, we trust the
    ORIGINAL data-entry signal: "we keyed a purchase, from a trusted supplier,
    with an expiry, during a window." Any item that (a) has such a purchase
    entry inside a chosen period AND (b) is on-hand right now becomes a
    candidate to physically pull off the shelf and re-verify its real expiry.

    IMPORTANT: this is a HISTORY trigger, not a current-batch match. The
    current stock does NOT have to carry the entered expiry — the entry is only
    the reason to go and physically check.

    Grain & idempotency
    -------------------
    One row per purchase line, batch-splits preserved via `dblitemflag`
    (each split = its own entered expiry). The unique key makes the backfill
    fully re-runnable: re-runs only INSERT rows that are missing (e.g. after a
    supplier is newly re-classified as "main"), never duplicating existing ones.
    Rows are immutable historical facts — never updated after insert.

    Source: `apps/batches/queries.py` QUERY_PURCHASE_EXPIRY_WINDOW
    Written by: `sync_purchase_expiry` management command / expiry_audit.run_backfill
    Read by:    expiry_audit.audit_candidates → near-expiry physical audit report
    """
    # ── Identity (SOFTECH-native codes) ───────────────────────────────────────
    branch_code    = models.CharField(max_length=10, db_index=True, verbose_name='كود الفرع')
    supplier_code  = models.CharField(max_length=10, db_index=True, verbose_name='كود المورد')
    supplier_name  = models.CharField(max_length=255, blank=True, verbose_name='اسم المورد')
    # Denormalized from procurement.SupplierSegmentation at sync time so the
    # report can filter by "main" category without a live join.
    supplier_category = models.CharField(max_length=25, blank=True, db_index=True,
                                         verbose_name='تصنيف المورد')
    doc_number     = models.CharField(max_length=20, verbose_name='رقم الفاتورة')
    doc_date       = models.DateField(db_index=True, verbose_name='تاريخ إدخال الفاتورة')
    item_code      = models.CharField(max_length=6, db_index=True, verbose_name='كود الصنف')
    item_name      = models.CharField(max_length=255, blank=True, verbose_name='اسم الصنف')
    # dblitemflag differentiates expiry-batch splits within one (doc × item).
    dblitemflag    = models.IntegerField(default=1, verbose_name='رقم الدفعة داخل الفاتورة')

    # ── The signal ────────────────────────────────────────────────────────────
    entered_expiry = models.DateField(db_index=True,
                                      verbose_name='تاريخ الصلاحية المُدخَل')
    qty            = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                        verbose_name='الكمية المشتراة')
    store_code     = models.CharField(max_length=5, blank=True, verbose_name='كود المخزن')

    # ── Optional PG links (item/branch may not be mirrored yet) ───────────────
    item   = models.ForeignKey(
        'catalog.Item', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_expiry_entries', verbose_name='الصنف',
    )
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='purchase_expiry_entries', verbose_name='الفرع',
    )

    synced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'إدخال صلاحية شراء'
        verbose_name_plural = 'إدخالات صلاحية الشراء'
        unique_together = ('branch_code', 'supplier_code', 'doc_number',
                           'doc_date', 'item_code', 'dblitemflag')
        indexes = [
            models.Index(fields=['item_code', 'entered_expiry'], name='pxe_item_expiry_idx'),
            models.Index(fields=['doc_date', 'supplier_code'],   name='pxe_date_supplier_idx'),
            models.Index(fields=['supplier_category', 'doc_date'], name='pxe_cat_date_idx'),
            models.Index(fields=['branch_code', 'doc_date'],      name='pxe_branch_date_idx'),
        ]
        ordering = ['-doc_date', 'item_code']

    def __str__(self):
        return (f'{self.item_code} exp {self.entered_expiry} '
                f'← {self.supplier_code} doc {self.doc_number} ({self.doc_date})')


class PurchaseExpiryAuditRun(models.Model):
    """
    Audit trail for one `sync_purchase_expiry` backfill run.

    Supports the re-run story: the owner reclassifies more suppliers as "main"
    over time, then re-runs the backfill so the newly-included suppliers' history
    is pulled in. Each run records exactly which window / branches / categories /
    supplier-set it covered and how many rows it added.
    """
    STATUS_CHOICES = [
        ('running', 'يعمل'),
        ('success', 'ناجح'),
        ('failed',  'فشل'),
    ]

    started_at   = models.DateTimeField(auto_now_add=True)
    finished_at  = models.DateTimeField(null=True, blank=True)
    status       = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')

    window_from  = models.DateField(verbose_name='من تاريخ')
    window_to    = models.DateField(verbose_name='إلى تاريخ')
    branch_scope = models.CharField(max_length=10, blank=True, default='',
                                    verbose_name='الفرع (فارغ = كل الفروع)')
    categories   = models.JSONField(default=list, verbose_name='فئات الموردين المشمولة')

    suppliers_count = models.PositiveIntegerField(default=0, verbose_name='عدد الموردين')
    lines_fetched   = models.PositiveIntegerField(default=0, verbose_name='الأسطر المقروءة')
    lines_upserted  = models.PositiveIntegerField(default=0, verbose_name='الأسطر المضافة')
    error_message   = models.TextField(blank=True)
    triggered_by    = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name        = 'تشغيل مزامنة صلاحيات الشراء'
        verbose_name_plural = 'تشغيلات مزامنة صلاحيات الشراء'
        ordering = ['-started_at']

    def __str__(self):
        return f'PurchaseExpiryRun #{self.pk} — {self.status} — {self.started_at:%Y-%m-%d %H:%M}'

    def finish(self, status='success', error=''):
        from django.utils import timezone as _tz
        self.status = status
        self.finished_at = _tz.now()
        self.error_message = error
        self.save(update_fields=['status', 'finished_at', 'error_message',
                                 'suppliers_count', 'lines_fetched', 'lines_upserted'])


class StockExpiryBalance(models.Model):
    """
    Local mirror of SOFTECH `stkbalexpiry` (current on-hand per-batch expiry)
    swept across ALL operational nodes — HQ/central (store-level) AND each sales
    branch's own Sybase node — so the FEFO tabs show live near-expiry / expired
    stock chain-wide, fast, without hitting 6 flaky nodes on every page load.

    `branch_code` = the operational branch whose node this row came from (HQ='100').
    `store_code`  = the raw storecode within that node (stkbalexpiry.branchcode is
                    always 0 in SOFTECH, so location lives in storecode).
    Refreshed by `sync_stock_expiry` (replace-per-branch snapshot). Unlike
    PurchaseExpiryEntry (a 3-yr additive purchase-entry mirror), this is a current
    balance — each sync REPLACES the synced branch's rows.
    """
    branch_code = models.CharField(max_length=10, db_index=True, verbose_name='الفرع')
    store_code  = models.CharField(max_length=10, blank=True, verbose_name='المخزن')
    item_code   = models.CharField(max_length=6, db_index=True, verbose_name='كود الصنف')
    item_name   = models.CharField(max_length=255, blank=True, verbose_name='اسم الصنف')
    batch_no    = models.CharField(max_length=50, blank=True, verbose_name='رقم التشغيلة')
    expiry_date = models.DateField(db_index=True, verbose_name='تاريخ الصلاحية')
    qty         = models.DecimalField(max_digits=14, decimal_places=5, default=0,
                                      verbose_name='الكمية')
    is_quarantine = models.BooleanField(default=False, verbose_name='مخزن عزل/تالف')

    synced_at   = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name        = 'رصيد صلاحية مخزون'
        verbose_name_plural = 'أرصدة صلاحية المخزون'
        indexes = [
            models.Index(fields=['expiry_date', 'qty'],       name='sxb_expiry_qty_idx'),
            models.Index(fields=['branch_code', 'expiry_date'], name='sxb_branch_expiry_idx'),
            models.Index(fields=['item_code'],                 name='sxb_item_idx'),
        ]
        ordering = ['expiry_date', 'item_code']

    def __str__(self):
        return f'{self.item_code} exp {self.expiry_date} qty {self.qty} @ {self.branch_code}/{self.store_code}'


class StockExpirySyncRun(models.Model):
    """Audit trail for one `sync_stock_expiry` multi-node sweep."""
    STATUS_CHOICES = [('running', 'يعمل'), ('success', 'ناجح'),
                      ('partial', 'جزئي'), ('failed', 'فشل')]

    started_at  = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')
    nodes_total    = models.PositiveIntegerField(default=0)
    nodes_ok       = models.PositiveIntegerField(default=0)
    nodes_failed   = models.PositiveIntegerField(default=0)
    rows_synced    = models.PositiveIntegerField(default=0)
    detail         = models.JSONField(default=dict)   # {branch_code: {ok/rows/error}}
    triggered_by   = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name        = 'تشغيل مزامنة صلاحية المخزون'
        verbose_name_plural = 'تشغيلات مزامنة صلاحية المخزون'
        ordering = ['-started_at']

    def __str__(self):
        return f'StockExpirySync #{self.pk} — {self.status} — {self.started_at:%Y-%m-%d %H:%M}'

    def finish(self, status='success'):
        from django.utils import timezone as _tz
        self.status = status
        self.finished_at = _tz.now()
        self.save(update_fields=['status', 'finished_at', 'nodes_total', 'nodes_ok',
                                 'nodes_failed', 'rows_synced', 'detail'])


class NearExpiryAlert(models.Model):
    """
    One row per (batch × threshold_days) — prevents duplicate alerts.
    Created by the near_expiry_scan management command.
    """
    THRESHOLD_30  = 30
    THRESHOLD_60  = 60
    THRESHOLD_90  = 90
    THRESHOLD_180 = 180

    THRESHOLD_CHOICES = [
        (THRESHOLD_30,  '< 30 يوماً — خطر'),
        (THRESHOLD_60,  '30–60 يوماً — تحذير'),
        (THRESHOLD_90,  '60–90 يوماً — تنبيه'),
        (THRESHOLD_180, '90–180 يوماً — مراقبة'),
    ]

    batch          = models.ForeignKey(
        StockBatch, on_delete=models.CASCADE,
        related_name='expiry_alerts', verbose_name='الدفعة',
    )
    threshold_days = models.PositiveSmallIntegerField(
        choices=THRESHOLD_CHOICES, db_index=True, verbose_name='عتبة التنبيه (أيام)',
    )
    alerted_at     = models.DateTimeField(auto_now_add=True, verbose_name='وقت التنبيه')
    resolved_at    = models.DateTimeField(null=True, blank=True, verbose_name='وقت الحل')
    # How it was resolved: transferred / returned_to_supplier / destroyed / sold / expired
    resolution     = models.CharField(max_length=30, blank=True, verbose_name='طريقة الحل')

    class Meta:
        verbose_name        = 'تنبيه انتهاء صلاحية'
        verbose_name_plural = 'تنبيهات انتهاء الصلاحية'
        unique_together     = ('batch', 'threshold_days')
        ordering            = ['batch__expiry_date']

    def __str__(self):
        return f'{self.batch} | {self.threshold_days}d alert'
