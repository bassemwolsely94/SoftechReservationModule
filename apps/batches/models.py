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
