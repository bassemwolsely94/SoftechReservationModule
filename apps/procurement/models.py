"""
apps/procurement/models.py

Procurement Intelligence Platform — persistent store.

Tables:
  PurchaseLine           — cached raw purchase lines from SOFTECH stktrans (doccode 10/120)
  SupplierProfile        — supplier master + computed performance metrics
  SupplierItemMapping    — learning table: supplier × item purchase history
  ProcurementEngineRun   — audit trail for each engine computation
  ProcurementSnapshot    — daily pre-computed network-level KPIs
  BuyerPerformance       — per-buyer computed metrics (Module 10)
  ProcurementAlert       — generated alerts & recommendations

DOCCODE RULES (enforced everywhere):
  doccode '10'  → purchase  → net_qty = +transqty,  net_value = +line_value
  doccode '120' → return    → net_qty = -transqty,  net_value = -line_value
"""
from decimal import Decimal
from django.db import models
from django.utils import timezone


# ── PurchaseLine ──────────────────────────────────────────────────────────────

class PurchaseLine(models.Model):
    """
    Cached purchase transaction line from SOFTECH stktrans.
    One row per (branch, supplier, doc_number, doc_date, item_code) after
    collapsing expiry-batch splits (dblitemflag aggregation).

    net_qty and net_value are pre-computed at insert time:
      doccode 10  → net = +transqty / +line_value
      doccode 120 → net = -transqty / -line_value
    """
    # ── Identity ──────────────────────────────────────────────────────────────
    branch_code    = models.CharField(max_length=10, db_index=True)
    supplier_code  = models.CharField(max_length=10, db_index=True)
    doc_number     = models.CharField(max_length=20)
    doc_date       = models.DateField(db_index=True)
    item_code      = models.CharField(max_length=6, db_index=True)
    store_code     = models.CharField(max_length=5, blank=True)
    doccode        = models.CharField(max_length=5)   # '10' or '120'
    is_return      = models.BooleanField(default=False, db_index=True)

    # ── Quantities & Values (raw from Sybase — always positive) ───────────────
    raw_qty    = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    raw_value  = models.DecimalField(max_digits=16, decimal_places=3, default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    cost_price = models.DecimalField(max_digits=12, decimal_places=4, default=0)

    # ── Net (sign-corrected: negative for returns) ────────────────────────────
    net_qty   = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    net_value = models.DecimalField(max_digits=16, decimal_places=3, default=0)

    # ── Public price at sync time (from Item.pack_price) ──────────────────────
    public_price = models.DecimalField(max_digits=12, decimal_places=3, default=0)

    # ── Margin (computed at insert: (public - cost) / public × 100) ───────────
    margin_pct = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    # ── Buyer & Invoice ───────────────────────────────────────────────────────
    buyer_code = models.CharField(max_length=20, blank=True)
    doc_value  = models.DecimalField(max_digits=16, decimal_places=3, default=0)

    # ── FOC Intelligence (v2) ─────────────────────────────────────────────────
    # is_foc: True when the (invoice × item) group received free goods.
    # foc_type: 'bonus' → free units present (بونص) | '' → normal paid line
    # bonus_qty: free (بونص) units received IN ADDITION to the paid net_qty.
    #            SOFTECH books free goods as a SEPARATE line for the same item with
    #            a 100% pharmacy discount (pharmacydiscp>=100) or zero price; the
    #            engine sums those free lines here so they survive the GROUP BY
    #            that used to average the zero price away.  This is the
    #            authoritative FOC signal — NOT stktrans.bonusqty (which holds a
    #            notional value, not the free quantity).
    is_foc     = models.BooleanField(default=False, db_index=True)
    foc_type   = models.CharField(max_length=15, blank=True, default='')
    bonus_qty  = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    # ── Tax-Aware Cost (v2) ───────────────────────────────────────────────────
    # vat_value:     SUM(stktrans.itemsalestax) for the grouped line — absolute
    #                tax amount in local currency charged on this purchase line.
    # tax_rate_pct:  AVG(stktrans.origintaxp) — tax rate % (e.g. 14.00 = 14%).
    #                Stored for reference / analysis; effective_cost uses vat_value.
    # effective_cost: (net_value + vat_value) / net_qty — true per-unit cost
    #                 after tax.  For FOC lines (net_value=0) stays 0.
    vat_value      = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    tax_rate_pct   = models.DecimalField(max_digits=7,  decimal_places=2, default=0)
    effective_cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)

    # ── Expiry Return Intelligence (v2) ──────────────────────────────────────
    # 'expiry' if store_code IN ('102','103','105'), else 'normal', else ''
    return_type = models.CharField(max_length=10, blank=True, default='')

    # ── Supplier Segmentation back-fill (v2) ─────────────────────────────────
    # Denormalized from SupplierSegmentation for fast filtering in history views
    supplier_category = models.CharField(max_length=25, blank=True, default='')

    # ── FK to Item (nullable — item may not be in PG catalog yet) ─────────────
    item = models.ForeignKey(
        'catalog.Item', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='purchase_lines',
    )

    # ── FK to Branch ──────────────────────────────────────────────────────────
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='purchase_lines',
    )

    synced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('branch_code', 'supplier_code', 'doc_number', 'doc_date', 'item_code', 'doccode')
        indexes = [
            models.Index(fields=['doc_date', 'supplier_code']),
            models.Index(fields=['doc_date', 'item_code']),
            models.Index(fields=['supplier_code', 'item_code']),
            models.Index(fields=['buyer_code', 'doc_date']),
            models.Index(fields=['is_return', 'doc_date']),
            models.Index(fields=['is_foc', 'doc_date']),
            models.Index(fields=['return_type', 'doc_date']),
            models.Index(fields=['supplier_category', 'doc_date']),
        ]
        ordering = ['-doc_date']
        verbose_name = 'سطر شراء'
        verbose_name_plural = 'سطور الشراء'

    def __str__(self):
        direction = 'مرتجع' if self.is_return else 'شراء'
        return f'{direction} {self.doc_number} — {self.item_code} — {self.doc_date}'

    @staticmethod
    def compute_net(raw_qty, raw_value, is_return):
        sign = Decimal('-1') if is_return else Decimal('1')
        return sign * Decimal(str(raw_qty)), sign * Decimal(str(raw_value))


# ── SupplierProfile ───────────────────────────────────────────────────────────

class SupplierProfile(models.Model):
    """
    Supplier master synced from SOFTECH personsdata + pre-computed performance.
    Updated on every engine run.
    """
    supplier_code = models.CharField(max_length=10, unique=True)
    supplier_name = models.CharField(max_length=255, blank=True)
    classif_code  = models.CharField(max_length=10, blank=True)  # WH/MF/etc.

    # ── Computed performance (last 365 days) ──────────────────────────────────
    net_purchase_value  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_purchase_qty    = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_return_value    = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    return_pct          = models.DecimalField(max_digits=7,  decimal_places=2, default=0)
    distinct_items      = models.PositiveIntegerField(default=0)
    invoice_count       = models.PositiveIntegerField(default=0)
    avg_margin_pct      = models.DecimalField(max_digits=7,  decimal_places=2, default=0)
    branches_supplied   = models.PositiveSmallIntegerField(default=0)
    purchase_frequency  = models.DecimalField(max_digits=6,  decimal_places=2, default=0)  # avg days between orders

    # ── Performance windows ───────────────────────────────────────────────────
    value_30d  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    value_90d  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    value_365d = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── Scoring (0-100) ───────────────────────────────────────────────────────
    score_margin          = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    score_availability    = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    score_returns         = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    score_price_stability = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    total_score           = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # ── Enhanced Scoring (v2) — 30% Margin + 20% Effective Cost + 15% FOC
    #                             + 15% Tax + 10% Returns + 10% Availability ──
    score_effective_cost  = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    score_foc_benefit     = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    score_tax_efficiency  = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    enhanced_total_score  = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # ── FOC & Tax Statistics (v2) ─────────────────────────────────────────────
    foc_rate_pct         = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    avg_tax_burden_pct   = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    # ── Segmentation category (denormalized from SupplierSegmentation) ────────
    supplier_category    = models.CharField(max_length=25, blank=True, default='')

    # ── MODULE 13 — Lost Sales Attribution (added by 0005_supplier_lost_sales) ─
    # avoidable_loss_value: sum of lost_revenue_30d for items where this supplier
    # is the primary supplier AND root_cause='supplier'
    avoidable_loss_value = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
        verbose_name='الإيراد الضائع المنسوب للمورد (30 يوم) ج.م',
        help_text='Lost revenue where root_cause=supplier AND this supplier is primary',
    )
    # service_level_pct: % of expected demand actually delivered
    # = (expected_demand - lost_qty) / expected_demand × 100
    service_level_pct = models.DecimalField(
        max_digits=6, decimal_places=2, default=100.0,
        verbose_name='مستوى الخدمة % (30 يوم)',
        help_text='(expected - lost_qty) / expected × 100 for items supplied by this vendor',
    )

    # ── Dates ─────────────────────────────────────────────────────────────────
    first_purchase_date = models.DateField(null=True, blank=True)
    last_purchase_date  = models.DateField(null=True, blank=True)
    last_updated        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-total_score', '-net_purchase_value']
        verbose_name = 'ملف مورد'
        verbose_name_plural = 'ملفات الموردين'
        indexes = [
            models.Index(fields=['total_score']),
            models.Index(fields=['avg_margin_pct']),
        ]

    def __str__(self):
        return f'{self.supplier_name or self.supplier_code} ({self.total_score:.0f})'


# ── SupplierItemMapping ───────────────────────────────────────────────────────

class SupplierItemMapping(models.Model):
    """
    Permanent learning table: supplier × item purchase history.
    Used by OCR invoice module for auto-matching and by procurement for
    supplier selection recommendations.
    Updated after each engine run.
    """
    supplier_code   = models.CharField(max_length=10, db_index=True)
    supplier_name   = models.CharField(max_length=255, blank=True)
    item_code       = models.CharField(max_length=6, db_index=True)
    item            = models.ForeignKey(
        'catalog.Item', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='supplier_mappings',
    )
    item_name       = models.CharField(max_length=255, blank=True)

    # ── Purchase history ──────────────────────────────────────────────────────
    purchase_count      = models.PositiveIntegerField(default=0)
    last_purchase_date  = models.DateField(null=True, blank=True)
    first_purchase_date = models.DateField(null=True, blank=True)
    net_qty_total       = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    net_value_total     = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── Price statistics ──────────────────────────────────────────────────────
    min_price    = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    max_price    = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    avg_price    = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    last_price   = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    price_drift_pct = models.DecimalField(max_digits=7, decimal_places=2, default=0)  # (last/avg-1)*100

    # ── Learning confidence (0-100) ───────────────────────────────────────────
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, default=50)
    is_primary       = models.BooleanField(default=False)  # this supplier is item's primary

    # ── OCR mapping corrections ───────────────────────────────────────────────
    ocr_match_count      = models.PositiveIntegerField(default=0)
    ocr_correction_count = models.PositiveIntegerField(default=0)

    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('supplier_code', 'item_code')
        indexes = [
            models.Index(fields=['supplier_code', 'is_primary']),
            models.Index(fields=['item_code', 'confidence_score']),
            models.Index(fields=['last_purchase_date']),
        ]
        ordering = ['-purchase_count']
        verbose_name = 'خريطة مورد-صنف'
        verbose_name_plural = 'خرائط الموردين والأصناف'

    def __str__(self):
        return f'{self.supplier_code} → {self.item_code} (×{self.purchase_count})'

    def boost_confidence(self, amount=5):
        self.confidence_score = min(Decimal('100'), self.confidence_score + Decimal(str(amount)))

    def penalize_confidence(self, amount=10):
        self.confidence_score = max(Decimal('0'), self.confidence_score - Decimal(str(amount)))


# ── ProcurementEngineRun ──────────────────────────────────────────────────────

class ProcurementEngineRun(models.Model):
    STATUS_CHOICES = [
        ('running', 'يعمل'),
        ('success', 'ناجح'),
        ('failed',  'فشل'),
    ]

    started_at     = models.DateTimeField(auto_now_add=True)
    finished_at    = models.DateTimeField(null=True, blank=True)
    status         = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')
    period_days    = models.PositiveIntegerField(default=365)  # lookback window
    lines_synced   = models.PositiveIntegerField(default=0)
    lines_upserted = models.PositiveIntegerField(default=0)
    suppliers_updated = models.PositiveIntegerField(default=0)
    mappings_updated  = models.PositiveIntegerField(default=0)
    alerts_generated  = models.PositiveIntegerField(default=0)
    error_message  = models.TextField(blank=True)
    triggered_by   = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'تشغيل محرك المشتريات'

    def __str__(self):
        return f'ProcurementRun #{self.pk} — {self.status} — {self.started_at:%Y-%m-%d %H:%M}'

    def finish(self, status='success', error=''):
        self.status = status
        self.finished_at = timezone.now()
        self.error_message = error
        self.save(update_fields=['status', 'finished_at', 'error_message'])


# ── ProcurementSnapshot ───────────────────────────────────────────────────────

class ProcurementSnapshot(models.Model):
    """
    Daily pre-computed network-level procurement KPIs.
    Used by the dashboard overview (Module 1 + Module 15).
    """
    snapshot_date = models.DateField(unique=True, db_index=True)
    engine_run    = models.ForeignKey(ProcurementEngineRun, on_delete=models.SET_NULL, null=True, blank=True)

    # ── Module 1 KPIs ────────────────────────────────────────────────────────
    net_purchase_value_30d  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_purchase_value_90d  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_purchase_value_365d = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    net_purchase_qty_30d  = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_purchase_qty_90d  = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_purchase_qty_365d = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    distinct_items_30d  = models.PositiveIntegerField(default=0)
    distinct_items_90d  = models.PositiveIntegerField(default=0)
    distinct_items_365d = models.PositiveIntegerField(default=0)

    distinct_suppliers_30d  = models.PositiveSmallIntegerField(default=0)
    distinct_suppliers_90d  = models.PositiveSmallIntegerField(default=0)
    distinct_suppliers_365d = models.PositiveSmallIntegerField(default=0)

    invoice_count_30d  = models.PositiveIntegerField(default=0)
    invoice_count_90d  = models.PositiveIntegerField(default=0)
    invoice_count_365d = models.PositiveIntegerField(default=0)

    # ── Module 5 — Margin ─────────────────────────────────────────────────────
    avg_margin_pct_30d  = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    avg_margin_pct_90d  = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    avg_margin_pct_365d = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    # ── Module 6 — Returns ────────────────────────────────────────────────────
    return_value_30d  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    return_pct_30d    = models.DecimalField(max_digits=7,  decimal_places=2, default=0)

    # ── Supplier concentration (top 3 by value) ───────────────────────────────
    top3_supplier_pct_365d = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    # ── Growth ────────────────────────────────────────────────────────────────
    purchase_growth_pct_mom = models.DecimalField(max_digits=7, decimal_places=2, default=0)  # month-over-month
    purchase_growth_pct_yoy = models.DecimalField(max_digits=7, decimal_places=2, default=0)  # year-over-year

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-snapshot_date']
        verbose_name = 'لقطة مشتريات يومية'

    def __str__(self):
        return f'ProcurementSnapshot {self.snapshot_date}'


# ── BuyerPerformance ──────────────────────────────────────────────────────────

class BuyerPerformance(models.Model):
    """
    Per-buyer performance metrics (Module 10).
    Aggregated from PurchaseLine by buyer_code.
    """
    buyer_code     = models.CharField(max_length=20, db_index=True)
    buyer_name     = models.CharField(max_length=100, blank=True)
    period_start   = models.DateField()
    period_end     = models.DateField()

    net_purchase_value = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    invoice_count      = models.PositiveIntegerField(default=0)
    distinct_items     = models.PositiveIntegerField(default=0)
    distinct_suppliers = models.PositiveSmallIntegerField(default=0)
    avg_margin_pct     = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    return_pct         = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    # ── Savings (avg_market_price - paid_price) × qty ─────────────────────────
    estimated_savings  = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── Score (weighted KPI) ──────────────────────────────────────────────────
    procurement_score  = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    engine_run = models.ForeignKey(ProcurementEngineRun, on_delete=models.CASCADE, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('buyer_code', 'period_start', 'period_end')
        ordering = ['-procurement_score']
        verbose_name = 'أداء المشتري'

    def __str__(self):
        return f'{self.buyer_code} — {self.period_start} / {self.period_end}'


# ── ProcurementAlert ──────────────────────────────────────────────────────────

ALERT_TYPES = [
    ('price_spike',             'ارتفاع مفاجئ في السعر'),
    ('price_drop',              'انخفاض مفاجئ في السعر'),
    ('high_return_rate',        'معدل مرتجعات عالٍ'),
    ('supplier_overpriced',     'مورد بسعر أعلى من السوق'),
    ('low_margin',              'هامش ربح منخفض'),
    ('preferred_supplier',      'مورد مفضل متاح'),
    ('missed_discount',         'خصم فائت'),
    ('price_drift',             'تذبذب في الأسعار'),
    ('high_concentration',      'تركز عالٍ على مورد واحد'),
    ('stockout_risk',           'خطر نفاد المخزون'),
    # v2 alert types
    ('foc_deterioration',       'تراجع في منح البضاعة المجانية'),
    ('tax_spike',               'ارتفاع حاد في الضرائب'),
    ('expiry_return_spike',     'ارتفاع في مرتجعات التالف'),
    ('demand_reorder',          'طلب شراء مدفوع بطلب العملاء'),
    ('patient_purchases_rising','ارتفاع المشتريات من المرضى'),
    ('warehouse_dependency',    'اعتماد مفرط على مستودعات صغيرة'),
]

ALERT_SEVERITY = [
    ('info',     'معلومة'),
    ('warning',  'تحذير'),
    ('critical', 'حرجة'),
]


class ProcurementAlert(models.Model):
    """
    Automated alerts generated by the procurement engine.
    """
    alert_type    = models.CharField(max_length=30, choices=ALERT_TYPES, db_index=True)
    severity      = models.CharField(max_length=10, choices=ALERT_SEVERITY, default='warning')
    entity_type   = models.CharField(max_length=20, blank=True)  # 'supplier', 'item', 'buyer', 'branch'
    entity_code   = models.CharField(max_length=20, blank=True, db_index=True)
    entity_name   = models.CharField(max_length=255, blank=True)

    title         = models.CharField(max_length=255)
    message       = models.TextField()
    metric_value  = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    threshold     = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    detected_at   = models.DateTimeField(auto_now_add=True, db_index=True)
    is_resolved   = models.BooleanField(default=False, db_index=True)
    resolved_at   = models.DateTimeField(null=True, blank=True)
    resolved_by   = models.CharField(max_length=100, blank=True)
    resolution_notes = models.TextField(blank=True)

    engine_run    = models.ForeignKey(ProcurementEngineRun, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-detected_at']
        indexes = [
            models.Index(fields=['is_resolved', 'severity']),
            models.Index(fields=['alert_type', 'detected_at']),
        ]
        verbose_name = 'تنبيه مشتريات'
        verbose_name_plural = 'تنبيهات المشتريات'

    def __str__(self):
        return f'[{self.severity}] {self.alert_type}: {self.title}'


# ── SupplierSegmentation (v2) ─────────────────────────────────────────────────

SUPPLIER_CATEGORY_CHOICES = [
    ('OFFICIAL_DISTRIBUTOR', 'موزع رسمي'),
    ('MANUFACTURER',         'مصنع / شركة أدوية'),
    ('SMALL_WAREHOUSE',      'مستودع صغير'),
    ('PATIENT_REPURCHASE',   'شراء من مريض / خاص'),
    ('INTERNAL_TRANSFER',    'تحويل داخلي بين الفروع'),
    ('SERVICE_VENDOR',       'مورد خدمات'),
    ('UNKNOWN',              'غير مصنف'),
]


class SupplierSegmentation(models.Model):
    """
    Semantic classification of each supplier / purchase-source.
    Auto-classified from personsdata (ptcode, ptclassifcode) on every engine run.
    Manual overrides are preserved (manual_override=True).

    Linked to SupplierProfile by supplier_code (not FK — supplier may not be in
    SupplierProfile if they only appear in non-20 ptcodes).
    """
    supplier_code    = models.CharField(max_length=10, unique=True, db_index=True)
    supplier_name    = models.CharField(max_length=255, blank=True)
    supplier_category = models.CharField(
        max_length=25, choices=SUPPLIER_CATEGORY_CHOICES, default='UNKNOWN', db_index=True,
    )

    # Raw personsdata fields — preserved for audit and re-classification
    persontype        = models.CharField(max_length=20, blank=True)
    persontypeclassif = models.CharField(max_length=20, blank=True)
    ptcode            = models.CharField(max_length=10, blank=True)
    ptclassifcode     = models.CharField(max_length=10, blank=True)

    # Classification metadata
    classified_at   = models.DateTimeField(auto_now=True)
    auto_classified = models.BooleanField(default=True)   # False = manually set
    manual_override = models.BooleanField(default=False)  # True = don't auto-reclassify
    notes           = models.TextField(blank=True)

    # Purchase statistics (populated by engine enrichment stage)
    purchase_value_365d  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    invoice_count_365d   = models.PositiveIntegerField(default=0)
    foc_rate_pct         = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    return_pct           = models.DecimalField(max_digits=7, decimal_places=2, default=0)

    class Meta:
        ordering = ['supplier_category', 'supplier_code']
        verbose_name = 'تصنيف مورد'
        verbose_name_plural = 'تصنيفات الموردين'
        indexes = [
            models.Index(fields=['supplier_category', 'purchase_value_365d']),
        ]

    def __str__(self):
        return f'{self.supplier_name or self.supplier_code} — {self.get_supplier_category_display()}'


# ── Admin-managed supplier categories (v3) ────────────────────────────────────

class SupplierCategory(models.Model):
    """
    Admin-managed supplier category master.

    Replaces the hard-coded SUPPLIER_CATEGORY_CHOICES with a DB-driven list so
    staff can add / rename / recolour categories without a code change.  The
    `code` is the stable key stored (denormalized) on SupplierSegmentation,
    SupplierProfile and PurchaseLine.supplier_category; `name_ar` / `color`
    drive all UI labels and badges.
    """
    code        = models.CharField(
        max_length=30, unique=True, db_index=True,
        help_text='Stable key stored on purchase lines / suppliers (e.g. OFFICIAL_DISTRIBUTOR)',
    )
    name_ar     = models.CharField(max_length=100, verbose_name='الاسم بالعربية')
    name_en     = models.CharField(max_length=100, blank=True, verbose_name='الاسم بالإنجليزية')
    color       = models.CharField(
        max_length=20, blank=True, default='',
        help_text='Tailwind badge tone key, e.g. "blue", "green", "amber" (UI hint)',
    )
    sort_order  = models.PositiveSmallIntegerField(default=100)
    is_active   = models.BooleanField(default=True)
    # Exactly one category should be the fallback for suppliers no rule matches.
    is_fallback = models.BooleanField(
        default=False,
        help_text='The catch-all category assigned when no rule matches (only one).',
    )
    notes       = models.TextField(blank=True)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'code']
        verbose_name = 'فئة مورد'
        verbose_name_plural = 'فئات الموردين'

    def __str__(self):
        return f'{self.name_ar} ({self.code})'


class SupplierClassificationRule(models.Model):
    """
    Admin-managed mapping from SOFTECH person codes → SupplierCategory.

    On every engine run, each supplier's (ptcode, ptclassifcode) — read from the
    synced apps.sync person tables — is matched against these rules and the
    winning category's `code` is written to SupplierSegmentation.supplier_category
    (unless the supplier has a manual_override).

    Matching precedence (most specific wins):
      1. exact  (ptcode set, ptclassifcode set)
      2. ptcode-only (ptclassifcode blank = any classif under this ptcode)
      3. lower `priority` number breaks ties
    A blank ptcode is NOT a wildcard — unmatched suppliers get the fallback
    category instead, so rules stay explicit and auditable.
    """
    ptcode        = models.CharField(max_length=10, db_index=True, verbose_name='كود نوع الشخص')
    ptclassifcode = models.CharField(
        max_length=10, blank=True, default='', db_index=True,
        verbose_name='كود التصنيف (فارغ = كل التصنيفات تحت النوع)',
    )
    category      = models.ForeignKey(
        SupplierCategory, on_delete=models.PROTECT, related_name='rules',
    )
    priority      = models.PositiveSmallIntegerField(
        default=100, help_text='Lower wins when multiple rules match.',
    )
    is_active     = models.BooleanField(default=True)
    notes         = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ('ptcode', 'ptclassifcode')
        ordering = ['ptcode', 'ptclassifcode']
        verbose_name = 'قاعدة تصنيف مورد'
        verbose_name_plural = 'قواعد تصنيف الموردين'
        indexes = [
            models.Index(fields=['ptcode', 'ptclassifcode', 'is_active']),
        ]

    def __str__(self):
        cl = self.ptclassifcode or '*'
        return f'pt{self.ptcode}/{cl} → {self.category.code}'
