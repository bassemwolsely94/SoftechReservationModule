"""
apps/purchasing/models.py

Purchasing Optimization Engine — persistent store for demand metrics.

Four tables:
  SalesTransactionLine  — PG cache of raw SOFTECH stktrans rows (rolling 365d).
  DemandCalculationRun  — audit trail for each engine run.
  ItemDemandMetrics     — per-item × per-branch calculated metrics.
  ItemDemandAggregated  — cross-branch network rollup + ABC classification.

DATA FLOW:
  SOFTECH (incremental, last N days)
      ↓ upsert
  SalesTransactionLine  (rolling 365-day window, purge old rows automatically)
      ↓ aggregate from PG
  ItemDemandMetrics  +  ItemDemandAggregated  (recalculated on each run)
"""
from django.db import models


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENGINE CONFIGURATION — singleton model (pk=1 always)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class EngineConfig(models.Model):
    """
    Singleton model (always pk=1).
    Stores all tunable calculation parameters for the Demand Engine.
    Changes take effect on the NEXT run — previously-written runs keep their
    own snapshot in DemandCalculationRun.params_snapshot.

    Weighted average (MonthlyAvg3Rates):
        monthly_avg = (rate_30d × w30 + rate_90d × w90 + rate_365d × w365)
                      ─────────────────────────────────────────────────────
                           sum of weights for windows with sales > 0
        Weights must sum to 1.0 (validation enforced at API level).

    ABC thresholds (cumulative % of network monthly value):
        ≤ abc_a_threshold → A
        ≤ abc_b_threshold → B
        else              → C

    Safety stock tiers (applied to monthly_avg):
        Each tier: (monthly_avg >= threshold) → output value
        Listed from highest to lowest threshold.
    """

    # ── Weighted-average weights ──────────────────────────────────────────────
    weight_30d  = models.FloatField(
        default=0.5,
        verbose_name='وزن معدل 30 يوم',
        help_text='Weight for the 30-day window in the weighted monthly average (default 0.5)',
    )
    weight_90d  = models.FloatField(
        default=0.3,
        verbose_name='وزن معدل 90 يوم',
        help_text='Weight for the 90-day window in the weighted monthly average (default 0.3)',
    )
    weight_365d = models.FloatField(
        default=0.2,
        verbose_name='وزن معدل 365 يوم',
        help_text='Weight for the 365-day window in the weighted monthly average (default 0.2)',
    )

    # ── Safety stock parameters ───────────────────────────────────────────────
    ss_multiplier = models.FloatField(
        default=1.0,
        verbose_name='معامل كمية الأمان (مبيعات > حد عالي)',
        help_text=(
            'Multiplier applied to monthly_avg before the tier lookup for high-demand items. '
            'Default 1.0 = ceil(monthly_avg). 1.5 = ceil(monthly_avg × 1.5). Range [0.5, 3.0].'
        ),
    )
    # Tier threshold — above this, formula is ceil(avg × multiplier)
    ss_high_threshold = models.FloatField(
        default=2.0,
        verbose_name='حد الطلب العالي (وحدة/شهر)',
        help_text='monthly_avg >= this → safety = ceil(avg × multiplier). Default 2.0.',
    )
    # Fixed output values for the three lower tiers
    ss_tier_mid  = models.FloatField(
        default=2.0,
        verbose_name='كمية أمان فئة متوسطة (0.5 – حد عالي)',
        help_text='Fixed safety stock for items with monthly_avg in [0.5, high_threshold). Default 2.',
    )
    ss_tier_low  = models.FloatField(
        default=1.0,
        verbose_name='كمية أمان فئة منخفضة (0.16 – 0.5)',
        help_text='Fixed safety stock for items with monthly_avg in [0.16, 0.5). Default 1.',
    )
    ss_tier_vlow = models.FloatField(
        default=0.5,
        verbose_name='كمية أمان فئة نادرة (0.016 – 0.16)',
        help_text='Fixed safety stock for items with monthly_avg in [0.016, 0.16). Default 0.5.',
    )

    # ── ABC thresholds ────────────────────────────────────────────────────────
    abc_a_threshold = models.FloatField(
        default=70.0,
        verbose_name='حد فئة A (%)',
        help_text='Cumulative % of network value at which A ends and B begins (default 70)',
    )
    abc_b_threshold = models.FloatField(
        default=90.0,
        verbose_name='حد فئة B (%)',
        help_text='Cumulative % of network value at which B ends and C begins (default 90)',
    )

    # ── Coverage horizon (per ABC class) ──────────────────────────────────────
    # How many months of weighted-average consumption the gap target should fill,
    # PER ABC class. Formula (Option ① — scale throughput, keep floor):
    #     target = max(safety_stock_floor, monthly_avg × coverage_months)
    # The safety-stock floor stays 1-month calibrated, so slow/expensive movers
    # are NOT inflated — coverage only scales the genuine throughput term.
    # Default 1.0 for every class → identical to the historical 1-month behaviour.
    coverage_months_a = models.FloatField(
        default=1.0,
        verbose_name='أشهر التغطية — فئة A',
        help_text='Months of consumption to stock for A-class items. Default 1.0.',
    )
    coverage_months_b = models.FloatField(
        default=1.0,
        verbose_name='أشهر التغطية — فئة B',
        help_text='Months of consumption to stock for B-class items. Default 1.0.',
    )
    coverage_months_c = models.FloatField(
        default=1.0,
        verbose_name='أشهر التغطية — فئة C',
        help_text='Months of consumption to stock for C-class items. Default 1.0.',
    )

    # ── In-transit (البضاعة بالطريق) freshness cutoff ─────────────────────────
    # SOFTECH inter-branch transfers (doccode 125) are considered live pipeline
    # inventory only if issued within this many days. Older "in_transit" rows are
    # stale/unreconciled documents (received but receipt un-linked, or abandoned)
    # — real transfers here are received within ~3 days (p90). Counting zombies
    # wrongly shrinks the gap, so they are excluded. 0 = disable the age filter.
    in_transit_max_age_days = models.PositiveSmallIntegerField(
        default=14,
        verbose_name='أقصى عمر للبضاعة بالطريق (أيام)',
        help_text='Only transfers issued within N days count as in-transit. '
                  'Older = stale/unreconciled → excluded. Default 14. 0 = no limit.',
    )

    # ── MODULE 13 — Lost Sales Intelligence parameters ────────────────────────

    ls_min_daily_demand = models.FloatField(
        default=0.03,
        verbose_name='الحد الأدنى للطلب اليومي (مبيعات ضائعة)',
        help_text=(
            'Items whose daily_demand (monthly_avg / 30) is below this value are '
            'excluded from stockout counting — too slow-moving to detect gaps reliably. '
            'Default 0.03 ≈ 1 sale per ~33 days. Range [0.01, 0.5].'
        ),
    )

    ls_bulk_sale_coverage_pct = models.FloatField(
        default=0.85,
        verbose_name='نسبة تغطية المبيعات الكبيرة (bulk sale)',
        help_text=(
            'If actual qty sold in 30d ≥ monthly_avg × this value, the item is '
            'treated as "demand fulfilled in bulk" and stockout_days = 0. '
            'Prevents false stockouts for items sold in large one-off transactions '
            '(e.g. hospitals, institutional orders). Default 0.85 = 85%. Range [0.5, 1.5].'
        ),
    )

    ls_forecast_spike_ratio = models.FloatField(
        default=1.35,
        verbose_name='معامل ارتفاع الطلب (توقعات)',
        help_text=(
            'If rate_30d > rate_365d × this value, root cause is classified as '
            '"forecast" (unexpected demand spike). Default 1.35 = 35%% above annual '
            'rate. Range [1.1, 3.0].'
        ),
    )

    ls_bottleneck_days = models.FloatField(
        default=7.0,
        verbose_name='أيام تغطية حد الاختناق',
        help_text=(
            'Items with coverage_days (current_stock / daily_demand) below this '
            'threshold while still in stock are flagged as "bottleneck" days. '
            'Default 7 days (1 week lead-time proxy). Range [1, 30].'
        ),
    )

    # ── Audit ─────────────────────────────────────────────────────────────────
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إعدادات محرك الطلب'
        verbose_name_plural = 'إعدادات محرك الطلب'

    def save(self, *args, **kwargs):
        """Force singleton: always pk=1."""
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        """Return the singleton config, creating it with defaults if absent."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def as_dict(self):
        """Return params as a plain dict (for snapshot / API serialisation)."""
        return {
            # Demand engine weights
            'weight_30d':                self.weight_30d,
            'weight_90d':                self.weight_90d,
            'weight_365d':               self.weight_365d,
            # Safety stock
            'ss_multiplier':             self.ss_multiplier,
            'ss_high_threshold':         self.ss_high_threshold,
            'ss_tier_mid':               self.ss_tier_mid,
            'ss_tier_low':               self.ss_tier_low,
            'ss_tier_vlow':              self.ss_tier_vlow,
            # ABC
            'abc_a_threshold':           self.abc_a_threshold,
            'abc_b_threshold':           self.abc_b_threshold,
            # Coverage horizon (per ABC class)
            'coverage_months_a':         self.coverage_months_a,
            'coverage_months_b':         self.coverage_months_b,
            'coverage_months_c':         self.coverage_months_c,
            # In-transit freshness
            'in_transit_max_age_days':   self.in_transit_max_age_days,
            # MODULE 13 — Lost Sales
            'ls_min_daily_demand':       self.ls_min_daily_demand,
            'ls_bulk_sale_coverage_pct': self.ls_bulk_sale_coverage_pct,
            'ls_forecast_spike_ratio':   self.ls_forecast_spike_ratio,
            'ls_bottleneck_days':        self.ls_bottleneck_days,
        }

    def __str__(self):
        return (
            f'Engine config (w30={self.weight_30d} w90={self.weight_90d} '
            f'w365={self.weight_365d} | A<{self.abc_a_threshold}% B<{self.abc_b_threshold}%)'
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RAW TRANSACTION CACHE — rolling 365-day SOFTECH mirror
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SupplierLeadTime(models.Model):
    """
    Per-supplier replenishment lead time (days), used by the advanced engine's
    reorder-point / JIT math instead of the flat per-ABC default. Populated by
    the lead-time estimator (from SOFTECH purchase receipts) or set manually.
    """
    METHOD_CHOICES = [
        ('order_to_receive', 'أمر → استلام'),   # true lead time (PO date → receipt)
        ('receipt_interval', 'فترة بين التوريدات'),  # cadence proxy
        ('manual',           'يدوى'),
    ]
    supplier_code = models.CharField(max_length=20, unique=True, db_index=True,
                                     verbose_name='كود المورد')
    supplier_name = models.CharField(max_length=150, blank=True)
    lead_time_days = models.FloatField(verbose_name='مهلة التوريد (أيام)')
    sample_count   = models.PositiveIntegerField(default=0, verbose_name='عدد العينات')
    method         = models.CharField(max_length=20, choices=METHOD_CHOICES, default='manual')
    note           = models.CharField(max_length=200, blank=True)
    computed_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'مهلة توريد المورد'
        verbose_name_plural = 'مهل توريد الموردين'
        ordering            = ['supplier_code']

    def __str__(self):
        return f'{self.supplier_code} → {self.lead_time_days:.0f}d ({self.method})'


class SalesTransactionLine(models.Model):
    """
    One row per stktrans line item (one item per SOFTECH transaction document).

    Natural key from SOFTECH: (branchcode, itemcode, doccode, docnumber, docdate).

    Quantities:
      transqty — raw qty from SOFTECH (always positive, direction determined by doccode)
      net_qty  — +transqty for sales (115), -transqty for returns (30)

    The rolling window is maintained by:
      • Incrementally syncing the last N days from SOFTECH on every run
      • Purging rows where doc_date < today − 365 after each sync
    """

    # ── SOFTECH composite key (kept as chars for upsert performance) ──────────
    softech_branchcode = models.CharField(max_length=20, db_index=True)
    softech_itemcode   = models.CharField(max_length=50,  db_index=True)
    doccode            = models.CharField(max_length=10,
                                          help_text="'115' = sale | '30' = return")
    docnumber          = models.CharField(max_length=50)
    doc_date           = models.DateField(db_index=True)

    # ── Resolved FKs (nullable: rows with unmapped items/branches stay but are
    #    skipped during calculation) ───────────────────────────────────────────
    item   = models.ForeignKey(
        'catalog.Item', on_delete=models.SET_NULL,
        null=True, blank=True, db_index=True,
        related_name='sales_lines',
    )
    branch = models.ForeignKey(
        'branches.Branch', on_delete=models.SET_NULL,
        null=True, blank=True, db_index=True,
        related_name='sales_lines',
    )

    # ── Quantities ────────────────────────────────────────────────────────────
    transqty    = models.DecimalField(max_digits=14, decimal_places=3,
                                      help_text='Raw qty from SOFTECH (always ≥ 0)')
    net_qty     = models.DecimalField(max_digits=14, decimal_places=3,
                                      help_text='+transqty for sales, -transqty for returns')
    net_revenue = models.DecimalField(max_digits=18, decimal_places=3, default=0,
                                      help_text='Actual line revenue: +transprice_total for sales, -transprice_total for returns')

    # ── Sync metadata ─────────────────────────────────────────────────────────
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Natural PK from SOFTECH — enables ON CONFLICT upsert
        constraints = [
            models.UniqueConstraint(
                fields=['softech_branchcode', 'softech_itemcode',
                        'doccode', 'docnumber', 'doc_date'],
                name='unique_stktrans_line',
            )
        ]
        indexes = [
            # Purge query: WHERE doc_date < cutoff
            models.Index(fields=['doc_date'], name='stl_doc_date'),
            # Aggregation query: GROUP BY item_id, branch_id
            models.Index(fields=['item', 'branch', 'doc_date'], name='stl_item_branch_date'),
            # Sync dedup: look up existing rows by SOFTECH key
            models.Index(
                fields=['softech_branchcode', 'softech_itemcode', 'doc_date'],
                name='stl_soft_key_date',
            ),
        ]
        verbose_name        = 'حركة مبيعات'
        verbose_name_plural = 'حركات المبيعات'

    def __str__(self):
        return (
            f'{self.softech_itemcode} @ {self.softech_branchcode} '
            f'| {self.doccode}/{self.docnumber} | {self.doc_date} | {self.net_qty}'
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RUN LOG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DemandCalculationRun(models.Model):

    STATUS_CHOICES = [
        ('running',  'جارٍ'),
        ('success',  'نجح'),
        ('partial',  'جزئي'),
        ('failed',   'فشل'),
    ]

    started_at  = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')

    calc_date          = models.DateField(null=True, blank=True, db_index=True)
    softech_available  = models.BooleanField(default=False)

    # What was synced this run
    sync_lookback_days = models.PositiveSmallIntegerField(default=0,
                                                          help_text='Days fetched from SOFTECH (0 = calc-only)')
    rows_synced        = models.PositiveIntegerField(default=0,
                                                     help_text='Rows upserted into SalesTransactionLine')
    rows_purged        = models.PositiveIntegerField(default=0,
                                                     help_text='Old rows deleted (>365 days)')

    # What was calculated
    branches_processed = models.PositiveIntegerField(default=0)
    items_processed    = models.PositiveIntegerField(default=0)
    rows_written       = models.PositiveIntegerField(default=0)

    error_message     = models.TextField(blank=True)
    duration_seconds  = models.FloatField(null=True, blank=True)

    # Latest sale doc_date the engine actually saw (max SalesTransactionLine.doc_date).
    # The TRUE data horizon of this run's recommendations — may lag calc_date/run
    # time badly if the sales sync is behind. Surfaced in the dashboard header.
    data_through_date = models.DateField(null=True, blank=True, db_index=True,
                                         verbose_name='المبيعات حتى تاريخ')

    # Snapshot of EngineConfig params actually used for this run (for auditability)
    params_snapshot   = models.JSONField(default=dict, blank=True)

    # Live progress for the dashboard banner, esp. the catch-up backfill phase
    # which happens before the engine's own sync/calc phases:
    #   {"phase": "backfill"|"sync"|"calc", "pct": 0-100, "message": "..."}
    progress          = models.JSONField(default=dict, blank=True)

    # Bumped on every save (incl. progress updates). Used for ACTIVITY-based
    # stale-run expiry so a long-but-progressing run is never wrongly expired.
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        ordering        = ['-started_at']
        verbose_name    = 'تشغيل محرك الطلب'
        verbose_name_plural = 'تشغيلات محرك الطلب'

    def __str__(self):
        return f'Run {self.pk} | {self.get_status_display()} | {self.started_at:%Y-%m-%d %H:%M}'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PER-ITEM × PER-BRANCH METRICS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ItemDemandMetrics(models.Model):
    """
    One row per (item, branch) for each engine run.
    Fully replaced on each successful run (run FK cascades delete).

    Rate conventions — matching Excel Power Query logic exactly:
      rate_30d  = qty_30d            (raw 30-day qty IS the monthly rate)
      rate_90d  = qty_90d  / 3       (quarterly qty ÷ 3 months)
      rate_365d = qty_365d / 12      (annual qty ÷ 12 months)
      monthly_avg = weighted blend (50% × 30d + 30% × 90d + 20% × 365d)
                    weights redistributed when a window has zero sales
    """

    ABC_CHOICES = [
        ('A', 'A — الأكثر قيمةً (أعلى 70% من الإيرادات)'),
        ('B', 'B — متوسط القيمة (70–90%)'),
        ('C', 'C — أقل قيمةً (90–100%)'),
        ('X', 'X — لا مبيعات خلال السنة'),
    ]

    run    = models.ForeignKey(DemandCalculationRun, on_delete=models.CASCADE,
                               related_name='metrics', db_index=True)
    item   = models.ForeignKey('catalog.Item',   on_delete=models.CASCADE,
                               related_name='demand_metrics')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                               related_name='demand_metrics')

    calc_date = models.DateField(db_index=True)

    # ── Raw net quantities (sales − returns) per window ───────────────────────
    qty_30d  = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    qty_90d  = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    qty_365d = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    # ── Sale invoice counts (distinct sale docnumber per window) ──────────────
    invoices_30d  = models.PositiveIntegerField(default=0)
    invoices_90d  = models.PositiveIntegerField(default=0)
    invoices_365d = models.PositiveIntegerField(default=0)

    # ── Sale transaction row counts (for TRNs rate) ───────────────────────────
    trns_30d  = models.PositiveIntegerField(default=0,
                                            verbose_name='عدد حركات البيع (30 يوم)')
    trns_90d  = models.PositiveIntegerField(default=0,
                                            verbose_name='عدد حركات البيع (90 يوم)')
    trns_365d = models.PositiveIntegerField(default=0,
                                            verbose_name='عدد حركات البيع (365 يوم)')

    # ── Monthly rates (Excel-exact formula) ───────────────────────────────────
    rate_30d  = models.DecimalField(max_digits=14, decimal_places=4, default=0,
                                    verbose_name='معدل البيع الشهري (30 يوم) = qty_30d')
    rate_90d  = models.DecimalField(max_digits=14, decimal_places=4, default=0,
                                    verbose_name='معدل البيع الشهري (90 يوم) = qty_90d / 3')
    rate_365d = models.DecimalField(max_digits=14, decimal_places=4, default=0,
                                    verbose_name='معدل البيع الشهري (365 يوم) = qty_365d / 12')

    # ── Weighted monthly average (MonthlyAvg3Rates in Excel) ─────────────────
    monthly_avg = models.DecimalField(max_digits=14, decimal_places=4, default=0,
                                      verbose_name='المتوسط الشهري الموزون (3 معدلات)')

    # ── Transaction count monthly average (MonthlyAvg3RatesofTRNsCount) ──────
    monthly_avg_trns = models.DecimalField(max_digits=10, decimal_places=4, default=0,
                                           verbose_name='معدل عدد حركات البيع الشهري')

    # ── Safety stock (MinRequired in Excel) ───────────────────────────────────
    safety_stock  = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                        verbose_name='كمية الأمان (MinRequired)')

    # ── Stock & coverage ──────────────────────────────────────────────────────
    current_stock   = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='الرصيد الحالي')
    # Qty already dispatched to this branch by inter-branch transfer (SOFTECH
    # doccode 125) but not yet received — SOFTECH "البضاعة بالطريق". Pipeline
    # inventory: netted out of the gap (gap = target − current_stock − in_transit).
    in_transit_qty  = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='بضاعة في الطريق (لم تُستلم)')
    coverage_months = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True,
                                          verbose_name='معامل التغطية بالشهور')

    # ── Stock share of network total ──────────────────────────────────────────
    pct_stock_of_total = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True,
        verbose_name='نسبة الرصيد لإجمالي المخزون',
        help_text='branch_stock / total_network_stock for this item',
    )

    # ── Gap & priority (both can be negative = overstock) ─────────────────────
    gap      = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                   verbose_name='الفرق مطلوب/راكد (يمكن أن يكون سالباً)')
    priority = models.DecimalField(max_digits=14, decimal_places=4, default=0,
                                   verbose_name='معامل أولوية الطلب = (1 − تغطية) × فجوة')

    # ── ABC classification ────────────────────────────────────────────────────
    abc_class = models.CharField(max_length=1, choices=ABC_CHOICES, default='X',
                                 db_index=True)

    # ── Price & value snapshot ────────────────────────────────────────────────
    pack_price    = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    monthly_value = models.DecimalField(max_digits=16, decimal_places=2, default=0,
                                        verbose_name='القيمة الشهرية = معدل × سعر')

    # ── Actual revenue (365-day window, sign-corrected: sales − returns) ─────
    net_sales_revenue = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
        verbose_name='الإيرادات الفعلية (365 يوم)',
        help_text='SUM of net_revenue from SalesTransactionLine over rolling 365-day window',
    )

    # ── Last sale date at this branch ─────────────────────────────────────────
    last_sale_date = models.DateField(null=True, blank=True)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # MODULE 13 — LOST SALES INTELLIGENCE (added by 0012_lost_sales_fields)
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    ROOT_CAUSE_CHOICES = [
        ('purchasing',  'شراء — لم يُطلَب بما يكفي'),
        ('supplier',    'مورد — تأخر التوريد'),
        ('transfer',    'تحويل — متاح في فرع آخر'),
        ('expiry',      'انتهاء صلاحية — مردودات منتهية'),
        ('forecast',    'توقع — ارتفاع مفاجئ في الطلب'),
        ('unknown',     'غير محدد'),
    ]

    # Coverage expressed in DAYS (current_stock / daily_demand)
    coverage_days = models.FloatField(
        null=True, blank=True,
        verbose_name='أيام التغطية (من اليوم)',
        help_text='current_stock ÷ (monthly_avg / 30) — None when monthly_avg = 0',
    )

    # Estimated OOS days in the last 30 days
    stockout_days_30d = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='أيام النفاد (30 يوم)',
        help_text='Estimated days with zero stock in the last 30-day window',
    )

    # Days where stock > 0 but below 1-day demand (bottleneck)
    bottleneck_days_30d = models.PositiveSmallIntegerField(
        default=0,
        verbose_name='أيام الاختناق (30 يوم)',
        help_text='Days where stock > 0 but coverage_days < lead_time threshold (7d default)',
    )

    # Estimated lost units / revenue / margin for last 30 days
    lost_qty_30d = models.DecimalField(
        max_digits=14, decimal_places=3, default=0,
        verbose_name='الكمية الضائعة (30 يوم)',
        help_text='stockout_days × daily_demand_rate',
    )
    lost_revenue_30d = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
        verbose_name='الإيراد الضائع (30 يوم) ج.م',
        help_text='lost_qty × pack_price',
    )
    lost_margin_30d = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
        verbose_name='هامش الربح الضائع (30 يوم) ج.م',
        help_text='lost_revenue × std_gross_margin_pct',
    )

    # Availability = fraction of 30 days the item was in stock (%)
    availability_rate_30d = models.FloatField(
        default=100.0,
        verbose_name='معدل التوفر (30 يوم) %',
        help_text='(30 - stockout_days) / 30 × 100',
    )

    # Root cause classification (determined at engine run time)
    root_cause = models.CharField(
        max_length=15, choices=ROOT_CAUSE_CHOICES, default='unknown', blank=True,
        db_index=True,
        verbose_name='السبب الجذري',
    )

    # ── Forecast fields (written by ForecastService) ──────────────────────────
    DEMAND_PATTERN_CHOICES = [
        ('trend_up',   'اتجاه تصاعدي'),
        ('trend_down', 'اتجاه تنازلي'),
        ('stable',     'مستقر'),
        ('cyclical',   'دوري'),
        ('spike',      'طفرة'),
        ('anomaly',    'شاذ'),
    ]

    seasonal_index             = models.DecimalField(max_digits=6,  decimal_places=4, null=True, blank=True, verbose_name='المؤشر الموسمي')
    yoy_growth_rate            = models.DecimalField(max_digits=7,  decimal_places=4, null=True, blank=True, verbose_name='معدل النمو السنوي')
    forecast_next_30d          = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='توقع 30 يوم')
    forecast_next_90d          = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='توقع 90 يوم')
    forecast_confidence        = models.DecimalField(max_digits=5,  decimal_places=4, null=True, blank=True, verbose_name='درجة ثقة التوقع (0–1)')
    demand_pattern             = models.CharField(max_length=15, choices=DEMAND_PATTERN_CHOICES, null=True, blank=True, db_index=True, verbose_name='نمط الطلب')
    expected_stockout_date     = models.DateField(null=True, blank=True, verbose_name='تاريخ النفاد المتوقع')
    expected_expiry_risk_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='قيمة خطر الانتهاء المتوقع')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['run', 'item', 'branch'],
                                    name='unique_run_item_branch')
        ]
        ordering = ['-priority']
        verbose_name        = 'مقاييس الطلب'
        verbose_name_plural = 'مقاييس الطلب'
        indexes = [
            models.Index(fields=['calc_date', 'branch'],   name='purch_metrics_date_branch'),
            models.Index(fields=['calc_date', 'abc_class'], name='purch_metrics_date_abc'),
            models.Index(fields=['calc_date', 'priority'],  name='purch_metrics_date_priority'),
            models.Index(fields=['item', 'branch', 'calc_date'],
                         name='purch_metrics_item_branch_date'),
        ]

    def __str__(self):
        return (
            f'{self.item.name} @ {self.branch.display_name} '
            f'| avg={self.monthly_avg} | gap={self.gap} | {self.abc_class}'
        )

    @property
    def needs_purchase(self):
        return float(self.gap) > 0

    @property
    def stock_status(self):
        cov = float(self.coverage_months or 0)
        if cov == 0 and float(self.current_stock) == 0:
            return 'نفد'
        elif cov < 0.5:
            return 'حرج'
        elif cov < 1:
            return 'منخفض'
        elif cov < 2:
            return 'مقبول'
        return 'جيد'

    @property
    def stock_status_color(self):
        return {
            'نفد': 'red', 'حرج': 'orange', 'منخفض': 'yellow',
            'مقبول': 'blue', 'جيد': 'green',
        }.get(self.stock_status, 'gray')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CROSS-BRANCH AGGREGATED VIEW
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ItemDemandAggregated(models.Model):

    ABC_CHOICES = ItemDemandMetrics.ABC_CHOICES

    run       = models.ForeignKey(DemandCalculationRun, on_delete=models.CASCADE,
                                  related_name='aggregated', db_index=True)
    item      = models.ForeignKey('catalog.Item', on_delete=models.CASCADE,
                                  related_name='demand_aggregated')
    calc_date = models.DateField(db_index=True)

    total_qty_30d  = models.DecimalField(max_digits=16, decimal_places=3, default=0)
    total_qty_90d  = models.DecimalField(max_digits=16, decimal_places=3, default=0)
    total_qty_365d = models.DecimalField(max_digits=16, decimal_places=3, default=0)

    total_monthly_avg   = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    total_current_stock = models.DecimalField(max_digits=16, decimal_places=3, default=0)
    total_in_transit    = models.DecimalField(max_digits=16, decimal_places=3, default=0,
                                              verbose_name='إجمالي البضاعة بالطريق')
    total_monthly_value = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_gap           = models.DecimalField(max_digits=16, decimal_places=3, default=0)

    abc_class      = models.CharField(max_length=1, choices=ABC_CHOICES,
                                      default='X', db_index=True)
    cumulative_pct = models.DecimalField(max_digits=6, decimal_places=3, default=0)

    branches_with_sales = models.PositiveSmallIntegerField(default=0)
    branches_with_gap   = models.PositiveSmallIntegerField(default=0)

    pack_price = models.DecimalField(max_digits=10, decimal_places=3, default=0)

    # ── Actual network revenue (365-day, all branches summed) ─────────────────
    total_net_sales_revenue = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
        verbose_name='إجمالي الإيرادات الفعلية (شبكة)',
    )

    # ── MODULE 13 — Lost Sales (network rollup, added by 0012_lost_sales_fields) ─
    total_lost_qty_30d = models.DecimalField(
        max_digits=16, decimal_places=3, default=0,
        verbose_name='إجمالي الكمية الضائعة (30 يوم)',
    )
    total_lost_revenue_30d = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
        verbose_name='إجمالي الإيراد الضائع (30 يوم) ج.م',
    )
    total_lost_margin_30d = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
        verbose_name='إجمالي الهامش الضائع (30 يوم) ج.م',
    )
    # Average availability across branches that have demand (monthly_avg > 0)
    network_availability_rate_30d = models.FloatField(
        default=100.0,
        verbose_name='متوسط معدل توفر الشبكة (30 يوم) %',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['run', 'item'], name='unique_run_item_agg')
        ]
        ordering = ['-total_monthly_value']
        verbose_name        = 'إجماليات الطلب (شبكة)'
        verbose_name_plural = 'إجماليات الطلب (شبكة)'
        indexes = [
            models.Index(fields=['calc_date', 'abc_class'],          name='purch_agg_date_abc'),
            models.Index(fields=['calc_date', 'total_monthly_value'], name='purch_agg_date_value'),
        ]

    def __str__(self):
        return (
            f'{self.item.name} | net_avg={self.total_monthly_avg} '
            f'| stock={self.total_current_stock} | {self.abc_class}'
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MODULE 2 — INTER-BRANCH TRANSFER RECOMMENDATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from django.conf import settings   # noqa: E402  (imported here to keep models.py self-contained)


class TransferRecommendationRun(models.Model):
    """
    One record per TransferEngine execution, linked 1-to-1 with a
    DemandCalculationRun.  Generated automatically at the end of MODULE 12.
    """
    STATUS_CHOICES = [
        ('pending',  'انتظار'),
        ('running',  'جارٍ'),
        ('success',  'نجح'),
        ('failed',   'فشل'),
    ]

    demand_run  = models.OneToOneField(
        DemandCalculationRun,
        on_delete=models.CASCADE,
        related_name='transfer_rec_run',
        verbose_name='تشغيل محرك الطلب',
    )
    started_at  = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)

    # Summary counters (filled when status='success')
    total_recommendations = models.PositiveIntegerField(default=0)
    total_items_covered   = models.PositiveIntegerField(default=0)
    total_transfer_value  = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        ordering            = ['-started_at']
        verbose_name        = 'تشغيل محرك التحويلات'
        verbose_name_plural = 'تشغيلات محرك التحويلات'

    def __str__(self):
        return (
            f'TransferRun {self.pk} → DemandRun {self.demand_run_id} '
            f'| {self.get_status_display()} | {self.total_recommendations} توصية'
        )


class TransferRecommendation(models.Model):
    """
    One row per (item, from_branch → to_branch) transfer suggestion generated
    by the TransferEngine for a given run.

    Lifecycle:
        pending  → approved  → (physical transfer executed in transfers app)
                 → rejected
        pending  → executed  (shortcut: approved + executed in one step)

    All stock/gap figures are snapshots at the time the engine ran —
    they do NOT change if live stock changes later.
    """

    STATUS_CHOICES = [
        ('pending',  'انتظار مراجعة'),
        ('approved', 'موافق عليه'),
        ('rejected', 'مرفوض'),
        ('executed', 'منفّذ'),
    ]

    ABC_CHOICES = ItemDemandMetrics.ABC_CHOICES

    run  = models.ForeignKey(
        TransferRecommendationRun,
        on_delete=models.CASCADE,
        related_name='recommendations',
        db_index=True,
    )
    item        = models.ForeignKey('catalog.Item',   on_delete=models.CASCADE,
                                    related_name='transfer_recs')
    from_branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                    related_name='transfer_recs_out')
    to_branch   = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                    related_name='transfer_recs_in')

    # ── Transfer quantity & value ─────────────────────────────────────────────
    quantity        = models.DecimalField(max_digits=14, decimal_places=3,
                                          verbose_name='الكمية المقترحة للتحويل')
    pack_price      = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                          verbose_name='سعر الوحدة (ج.م)')
    estimated_value = models.DecimalField(max_digits=18, decimal_places=2, default=0,
                                          verbose_name='القيمة التقديرية = الكمية × السعر')

    # ── Priority signal (from the receiving branch's demand metrics) ──────────
    priority_score = models.FloatField(default=0,
                                       verbose_name='درجة الأولوية (من فرع الاستلام)')

    # ── Source-branch snapshot at engine run time ─────────────────────────────
    from_stock       = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                            verbose_name='رصيد الفرع المُرسِل')
    from_safety      = models.DecimalField(max_digits=10, decimal_places=2, default=0,
                                            verbose_name='كمية الأمان (فرع المُرسِل)')
    from_surplus     = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                            verbose_name='الفائض المتاح = رصيد − أمان')
    from_monthly_avg = models.DecimalField(max_digits=14, decimal_places=4, default=0,
                                            verbose_name='متوسط مبيعات فرع المُرسِل (شهري)')

    # ── Destination-branch snapshot at engine run time ────────────────────────
    to_stock       = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='رصيد الفرع المستلِم')
    to_gap         = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          verbose_name='الفجوة في فرع الاستلام')
    to_monthly_avg = models.DecimalField(max_digits=14, decimal_places=4, default=0,
                                          verbose_name='متوسط مبيعات فرع المستلِم (شهري)')
    to_priority    = models.FloatField(default=0,
                                        verbose_name='أولوية فرع الاستلام')

    # ── Classification ────────────────────────────────────────────────────────
    abc_class = models.CharField(max_length=1, choices=ABC_CHOICES, default='X',
                                  db_index=True)

    # ── Review ────────────────────────────────────────────────────────────────
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES,
                                    default='pending', db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='transfer_rec_reviews',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    notes       = models.TextField(blank=True)

    # ── Audit ─────────────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['run', 'item', 'from_branch', 'to_branch'],
                name='unique_transfer_rec_per_run',
            )
        ]
        ordering = ['-priority_score', '-estimated_value']
        verbose_name        = 'توصية تحويل'
        verbose_name_plural = 'توصيات التحويل'
        indexes = [
            models.Index(fields=['run', 'status'],      name='trec_run_status'),
            models.Index(fields=['run', 'abc_class'],   name='trec_run_abc'),
            models.Index(fields=['run', 'from_branch'], name='trec_run_from'),
            models.Index(fields=['run', 'to_branch'],   name='trec_run_to'),
            models.Index(fields=['run', 'item'],        name='trec_run_item'),
        ]

    def __str__(self):
        return (
            f'{self.item.name} | {self.from_branch.name_ar or self.from_branch.name}'
            f' → {self.to_branch.name_ar or self.to_branch.name}'
            f' | qty={self.quantity} | {self.get_status_display()}'
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MODULE 13 — LOST SALES ENGINE AUDIT LOG
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LostSalesRun(models.Model):
    """
    Audit log for one MODULE 13 (Lost Sales Engine) execution.
    Linked 1-to-1 with a DemandCalculationRun.
    Generated automatically at the end of MODULE 13.

    All figures are for the 30-day window ending on calc_date.
    """
    STATUS_CHOICES = [
        ('pending',  'انتظار'),
        ('running',  'جارٍ'),
        ('success',  'نجح'),
        ('failed',   'فشل'),
    ]

    demand_run = models.OneToOneField(
        DemandCalculationRun,
        on_delete=models.CASCADE,
        related_name='lost_sales_run',
        verbose_name='تشغيل محرك الطلب',
    )
    started_at    = models.DateTimeField(auto_now_add=True)
    finished_at   = models.DateTimeField(null=True, blank=True)
    status        = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(blank=True)

    # Summary counters (filled when status='success')
    items_affected        = models.PositiveIntegerField(default=0,
                              help_text='Items with stockout_days_30d > 0')
    branch_item_pairs     = models.PositiveIntegerField(default=0,
                              help_text='Total (item, branch) rows processed')
    total_lost_revenue    = models.DecimalField(max_digits=20, decimal_places=2, default=0,
                              verbose_name='إجمالي الإيراد الضائع (30 يوم) ج.م')
    total_lost_margin     = models.DecimalField(max_digits=20, decimal_places=2, default=0,
                              verbose_name='إجمالي الهامش الضائع (30 يوم) ج.م')

    # Root-cause distribution (JSON dict: {root_cause: count})
    root_cause_breakdown  = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering            = ['-started_at']
        verbose_name        = 'تشغيل محرك المبيعات الضائعة'
        verbose_name_plural = 'تشغيلات محرك المبيعات الضائعة'

    def __str__(self):
        return (
            f'LostSalesRun {self.pk} → DemandRun {self.demand_run_id} '
            f'| {self.get_status_display()} | {self.items_affected} صنف'
        )


# ═══════════════════════════════════════════════════════════════════════════
# MARKET SHORTAGE — run snapshots (enables delta view + recovery tracking)
# ═══════════════════════════════════════════════════════════════════════════
class ShortageSnapshot(models.Model):
    """
    One row per demand run — a point-in-time capture of the shortage picture, so
    the review screen can diff runs (new / recovering / re-entered) instead of
    re-scanning the whole candidate list every cycle.
    """
    run        = models.OneToOneField(DemandCalculationRun, on_delete=models.CASCADE,
                                      related_name='shortage_snapshot')
    created_at = models.DateTimeField(auto_now_add=True)
    n_candidates = models.IntegerField(default=0)
    n_confirmed  = models.IntegerField(default=0)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'ShortageSnapshot run={self.run_id} ({self.n_candidates} cand)'


class ShortageObservation(models.Model):
    """
    Per (snapshot, item): the item's shortage signals at that run. Records every
    detected candidate PLUS every currently-confirmed item (even if healthy), so a
    confirmed item's recovery can be tracked across runs.
    """
    snapshot     = models.ForeignKey(ShortageSnapshot, on_delete=models.CASCADE,
                                     related_name='observations')
    item         = models.ForeignKey('catalog.Item', on_delete=models.CASCADE,
                                     related_name='shortage_observations')
    tier         = models.CharField(max_length=20, blank=True, default='')
    coverage     = models.FloatField(default=0.0)
    suppression  = models.FloatField(default=0.0)
    annual_qty   = models.FloatField(default=0.0)
    is_candidate = models.BooleanField(default=False)   # met the detection threshold
    is_confirmed = models.BooleanField(default=False)   # in_shortage at snapshot time
    healthy      = models.BooleanField(default=False)   # recovery signal (stock+sales back)

    class Meta:
        indexes = [
            models.Index(fields=['snapshot', 'item']),
            models.Index(fields=['item', 'id']),
        ]

    def __str__(self):
        return f'{self.item_id} @ snap{self.snapshot_id} ({self.tier})'
