"""
apps/purchasing/engine.py

Demand & Purchasing Optimization Engine — DemandEngine

Reproduces the Excel Power Query model exactly:
  "اولوية النواقص لكل فرع ب 3 معدلات سنوى - ربع سنوى - شهرى"

Excel rates (matched exactly):
  rate_30d  = qty_30d            (raw 30-day qty = monthly rate, Excel passes it straight through)
  rate_90d  = qty_90d  / 3      (quarterly qty ÷ 3 months, Excel: [90d QTY] / 3)
  rate_365d = qty_365d / 12     (annual qty ÷ 12 months, Excel: [365d QTY] / 12)

Weighted average (MonthlyAvg3Rates in Excel):
  weights = {30d: 0.5, 90d: 0.3, 365d: 0.2}
  • Only windows with rate > 0 participate (null-safe: excludes windows with no sales)
  • Participating weights are scaled so they sum to 1.0

Safety stock (MinRequired in Excel):
  monthly_avg < 0         → monthly_avg     (net returns, overstock signal)
  monthly_avg ≥ 2         → ceil(monthly_avg)
  monthly_avg ≥ 0.5       → 2
  monthly_avg ≥ 0.16      → 1
  monthly_avg ≥ 0.016     → 0.5
  else                    → 0

Gap (Excel: max(MinRequired, MonthlyAvg) − nowqty):
  Can be negative when item is overstocked.

Priority = (1 − coverage) × gap
  Not clamped — negative priority = overstocked item (no purchase needed).

TRNs count (MonthlyAvg3RatesofTRNsCount in Excel):
  Simple average of {trns_30d, trns_90d/3, trns_365d/12}, null-safe.

% stock of total = branch_stock / total_network_stock_for_item

────────────────────────────────────────────────────────────────────────────────
PERFORMANCE ARCHITECTURE
────────────────────────────────────────────────────────────────────────────────

MODULE 2 — SOFTECH sync (optimised):
  • fetchmany(5 000) streaming  — avoids loading the entire Sybase result set
    into memory before processing. Sybase can return 100k–5M rows for a full
    365-day backfill; fetchall() would allocate all of it at once.
  • ORDER BY removed            — unnecessary sort removed from QUERY_SALES_INCREMENTAL
    (saves significant Sybase CPU on large result sets).
  • COPY staging pattern        — raw Sybase rows are buffered to an io.BytesIO
    object in tab-separated text format and flushed to a temporary PG staging
    table using cursor.copy_expert().  A single INSERT … SELECT … ON CONFLICT
    then resolves FKs in SQL (JOIN catalog_item / branches_branch) and upserts
    into the main table.  This replaces the Python dict FK resolution loop +
    ORM bulk_create(update_conflicts=True), giving 3-10× throughput improvement
    for large batches.
  • Smart lookback              — before connecting to Sybase, the engine checks
    MAX(doc_date) in SalesTransactionLine.  If PG is already up-to-date, the
    lookback window is shrunk automatically (+ 2-day safety overlap).

MODULE 3 — PG aggregation (optimised):
  • Single raw SQL query        — replaces ORM annotate() with CASE WHEN per
    column.  Django's ORM generates multiple conditional passes; raw SQL does it
    in a single table scan.  ~3-5× faster on tables > 500k rows.

MODULE 9 — Network aggregation:
  • Already single-pass — no changes needed.

Incremental architecture:
  1. Smart-lookback SOFTECH sync → COPY → SQL upsert into SalesTransactionLine
  2. Purge SalesTransactionLine rows older than 365 days
  3. Single-pass raw SQL aggregation (3 windows) from PG
  4. Calculate metrics (modules 3–8)
  5. Aggregate network totals + pct_stock (module 9)
  6. ABC Pareto (module 10)
  7. Bulk upsert persist (module 11)
"""

import io
import math
import logging
import datetime
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone
from django.db import connection, transaction

logger = logging.getLogger('elrezeiky.purchasing')

# ── Default constants (used when DB config is unavailable) ────────────────────

WEIGHTS = {30: 0.5, 90: 0.3, 365: 0.2}   # MonthlyAvg3Rates weights (default)

ABC_A_THRESHOLD = 70.0   # cumulative % for A (default)
ABC_B_THRESHOLD = 90.0   # cumulative % for B (default)

# Default lookback for incremental sync (used when PG is empty or gap is larger)
DEFAULT_INCREMENTAL_DAYS = 10
ROLLING_WINDOW_DAYS      = 365   # rows older than this are purged

# COPY / fetch batch sizes
SYBASE_FETCH_BATCH = 5_000    # rows per Sybase fetchmany() round-trip
PG_COPY_CHUNK      = 100_000  # rows per COPY → staging flush

_D = lambda v: Decimal(str(v)) if v is not None else Decimal('0')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CALCULATION HELPERS (pure functions — easily unit-testable)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def calc_monthly_rate(qty: float, window_days: int) -> float:
    """
    MODULE 3 — Convert raw window qty to monthly equivalent.
    Matches Excel Power Query exactly:
      30d  → qty / 1  = qty           (raw qty IS the monthly rate)
      90d  → qty / 3                  ([90d QTY] / 3)
      365d → qty / 12                 ([365d QTY] / 12)
    """
    if qty is None or qty == 0:
        return 0.0
    qty = float(qty)
    if window_days == 30:
        return qty           # Excel: raw 30d = 1 month
    elif window_days == 90:
        return qty / 3.0     # Excel: [90 Days Sales QTY] / 3
    elif window_days == 365:
        return qty / 12.0    # Excel: [365 Days Sales QTY] / 12
    else:
        # Fallback for non-standard windows: proportional scaling
        return (qty / window_days) * 30.0


def calc_weighted_avg(rate_30d: float, rate_90d: float, rate_365d: float,
                      weights: dict | None = None) -> float:
    """
    MODULE 4 — Weighted blend with null-safe weight redistribution.
    Excel logic (MonthlyAvg3Rates):
      values  = {30d, 90d_monthly, 365d_monthly}
      weights = {0.5, 0.3, 0.2}  (or custom from EngineConfig)
      valid   = pairs where value != null (we treat 0 as null — no sales that period)
      result  = weightedSum / weightSum   (weights rescaled to sum to 1.0)

    weights dict: {30: w30, 90: w90, 365: w365}  defaults to WEIGHTS constant.
    """
    w = weights or WEIGHTS
    pairs = [
        (rate_30d,  w[30]),
        (rate_90d,  w[90]),
        (rate_365d, w[365]),
    ]
    # Only include windows with actual sales (treat 0 as "no data")
    active = [(r, wt) for r, wt in pairs if r > 0]
    if not active:
        return 0.0

    total_weight = sum(wt for _, wt in active)
    if total_weight == 0:
        return 0.0
    return sum(r * wt for r, wt in active) / total_weight


def calc_trns_avg(trns_30d: int, trns_90d: int, trns_365d: int) -> float:
    """
    MonthlyAvg3RatesofTRNsCount in Excel = List.Average({30d, 90d/3, 365d/12}).
    Simple average of available (non-zero) values.
    """
    rates = []
    if trns_30d  > 0: rates.append(float(trns_30d))
    if trns_90d  > 0: rates.append(float(trns_90d) / 3.0)
    if trns_365d > 0: rates.append(float(trns_365d) / 12.0)
    return sum(rates) / len(rates) if rates else 0.0


def calc_safety_stock(
    monthly_avg: float,
    ss_multiplier: float = 1.0,
    ss_high_threshold: float = 2.0,
    ss_tier_mid: float = 2.0,
    ss_tier_low: float = 1.0,
    ss_tier_vlow: float = 0.5,
) -> float:
    """
    MODULE 5 — Safety stock rules matching Excel MinRequired exactly,
    extended with configurable tier outputs.

    Tier logic (applied to effective = monthly_avg × ss_multiplier):
      effective >= ss_high_threshold → ceil(effective)   [formula — scales with demand]
      effective >= 0.5               → ss_tier_mid       [fixed, default 2]
      effective >= 0.16              → ss_tier_low       [fixed, default 1]
      effective >= 0.016             → ss_tier_vlow      [fixed, default 0.5]
      else                           → 0

    All threshold boundaries (0.5, 0.16, 0.016) are hardcoded — they are the
    natural pharmacy dispensing-frequency breakpoints.  Only the OUTPUT values
    for the fixed tiers and the high-demand threshold are configurable.

    Note: negative monthly_avg (net returns > sales) returns monthly_avg itself
    so the gap column reflects the overstock condition. The multiplier is NOT
    applied to the overstock signal.
    """
    if monthly_avg < 0:
        return monthly_avg          # overstock/net-return signal — skip multiplier
    effective = monthly_avg * ss_multiplier
    if effective >= ss_high_threshold:
        return float(math.ceil(effective))
    if effective >= 0.5:
        return float(ss_tier_mid)
    if effective >= 0.16:
        return float(ss_tier_low)
    if effective >= 0.016:
        return float(ss_tier_vlow)
    return 0.0


def calc_coverage(current_stock: float, monthly_avg: float):
    """
    MODULE 6 — Coverage in months.
    Returns None when monthly_avg <= 0 (zero demand → coverage undefined).
    """
    if monthly_avg <= 0:
        return None
    return current_stock / monthly_avg


def calc_gap(current_stock: float, safety_stock: float, monthly_avg: float,
             coverage_months: float = 1.0) -> float:
    """
    MODULE 7 — Gap = max(MinRequired, MonthlyAvg × coverage_months) − nowqty.

    coverage_months (default 1.0) = how many months of consumption to hold.
    Option ① — "scale throughput, keep floor":
      • The safety-stock FLOOR stays 1-month calibrated (never scaled), so
        slow / expensive movers whose floor already covers many months are
        NOT inflated when coverage rises.
      • Only the genuine throughput term (monthly_avg × coverage) scales, and
        it overtakes the floor only when real demand over the window exceeds it.

    coverage_months = 1.0 reproduces the historical Excel behaviour exactly:
        max(MinRequired, MonthlyAvg) − nowqty.

    Negative monthly_avg (net returns → safety_stock carries the negative signal):
    scaling makes monthly_avg×coverage even more negative, so max() keeps the
    unscaled overstock signal — coverage never distorts overstock. NOT clamped.
    """
    scaled_demand = monthly_avg * coverage_months
    target = safety_stock if safety_stock > scaled_demand else scaled_demand
    return target - current_stock


def calc_priority(coverage, gap: float) -> float:
    """
    MODULE 8 — Priority = (1 − coverage) × gap.
    Excel: (1 - Coverage) * Gap
    Not clamped — negative means overstocked (no purchase needed).
    Items with gap ≤ 0 get priority ≤ 0 naturally.
    """
    if coverage is None:
        return 0.0
    return (1.0 - float(coverage)) * gap


def abc_class_from_pct(cumulative_pct: float,
                       a_threshold: float = ABC_A_THRESHOLD,
                       b_threshold: float = ABC_B_THRESHOLD) -> str:
    """MODULE 10 — Map cumulative % of revenue to ABC label."""
    if cumulative_pct <= a_threshold:
        return 'A'
    elif cumulative_pct <= b_threshold:
        return 'B'
    return 'C'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DemandEngine:
    """
    Orchestrates the full demand calculation pipeline.
    Designed for daily batch execution.

    Usage:
        engine = DemandEngine()
        run = engine.run()                       # incremental (smart lookback)
        run = engine.run(full_backfill=True)     # full 365-day resync
        run = engine.run(sync_only=True)         # sync SOFTECH → PG, skip calc
        run = engine.run(calc_only=True)         # skip sync, recalc from PG
    """

    def __init__(self, lookback_days: int = DEFAULT_INCREMENTAL_DAYS,
                 param_overrides: dict | None = None):
        """
        param_overrides — optional dict that overrides individual EngineConfig
        fields for this run only, e.g.:
          {'weight_30d': 0.6, 'weight_90d': 0.25, 'weight_365d': 0.15}
        Values not in the dict are read from the DB EngineConfig.
        """
        self.lookback_days     = lookback_days
        self.param_overrides   = param_overrides or {}
        self.run_obj           = None
        self.calc_date         = timezone.localdate()
        self._branch_map       = {}   # softech_branch_id → Branch.id
        self._item_map         = {}   # softech_id → (item_id, pack_price)
        self._item_id_to_price = {}   # item_id → pack_price  (O(1) reverse)
        self._stock_map        = {}   # (item_id, branch_id) → float (stkbal or ItemStock)
        self._intransit_map    = {}   # (item_id, branch_id) → float (in-transit qty inbound)
        self._softech_ok       = False
        # Active params (resolved in _load_config)
        self._weights          = WEIGHTS.copy()
        self._abc_a            = ABC_A_THRESHOLD
        self._abc_b            = ABC_B_THRESHOLD

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self, *, full_backfill: bool = False, sync_only: bool = False,
            calc_only: bool = False, existing_run=None):
        """
        Execute the pipeline. Returns the DemandCalculationRun object.

        existing_run: reuse an already-created run (e.g. the catch-up flow creates
        the run up front and drives the backfill progress on it, then hands it here
        so the whole operation is ONE continuous run for the dashboard banner).
        """
        from apps.purchasing.models import DemandCalculationRun
        import time

        # Determine effective lookback window
        if full_backfill:
            effective_lookback = ROLLING_WINDOW_DAYS
        elif calc_only:
            effective_lookback = 0
        else:
            # Smart incremental: shrink window if PG already has recent data
            effective_lookback = self._determine_lookback(self.lookback_days)

        t0 = time.monotonic()
        if existing_run is not None:
            self.run_obj = existing_run
            self.run_obj.sync_lookback_days = 0 if calc_only else effective_lookback
            self.run_obj.save(update_fields=['sync_lookback_days'])
        else:
            self.run_obj = DemandCalculationRun.objects.create(
                status='running',
                calc_date=self.calc_date,
                sync_lookback_days=0 if calc_only else effective_lookback,
            )
        logger.info(
            '[DemandEngine] Run %d | full=%s sync_only=%s calc_only=%s lookback=%dd',
            self.run_obj.pk, full_backfill, sync_only, calc_only, effective_lookback,
        )

        try:
            # MODULE 0 — Load tunable params from DB config
            effective_params = self._load_config()
            self.run_obj.params_snapshot = effective_params
            self.run_obj.save(update_fields=['params_snapshot'])

            # MODULE 1 — Load PG lookup maps
            self._load_lookups()

            rows_synced = rows_purged = 0

            if not calc_only:
                # MODULE 2 — Incremental SOFTECH sync + rolling window purge
                rows_synced, rows_purged = self._sync_from_softech(effective_lookback)
                self.run_obj.rows_synced       = rows_synced
                self.run_obj.rows_purged       = rows_purged
                self.run_obj.softech_available = self._softech_ok
                self.run_obj.save(update_fields=['rows_synced', 'rows_purged', 'softech_available'])

            if sync_only:
                self.run_obj.status           = 'success'
                self.run_obj.finished_at      = timezone.now()
                self.run_obj.duration_seconds = round(time.monotonic() - t0, 2)
                self.run_obj.save()
                return self.run_obj

            # MODULE 3 — Single-pass raw SQL aggregation from PG SalesTransactionLine
            pg_rows = self._aggregate_from_pg()

            # MODULES 4–8 — Per-branch metrics calculation
            metrics = self._calculate_per_branch(pg_rows)

            # MODULE 9 — Network aggregation + pct_stock_of_total
            aggregated = self._aggregate_network(metrics)

            # MODULE 10 — ABC Pareto classification
            self._classify_abc(aggregated)

            # MODULE 10.5 — Apply per-ABC coverage horizon to gap + priority.
            # (Runs after ABC is known; recomputes per-branch gap and re-sums
            #  the network total so both reflect the configured coverage.)
            self._apply_coverage(metrics, aggregated)

            # MODULE 11 — Persist to DB
            rows_written = self._persist(metrics, aggregated)

            # MODULE 12 — Inter-branch transfer recommendations
            try:
                from .transfer_engine import TransferEngine
                TransferEngine(self.run_obj).run()
                logger.info('[DemandEngine] MODULE 12 — transfer recommendations generated')
            except Exception as exc:
                # Non-fatal: demand engine result is still valid even if
                # transfer rec generation fails (e.g. no surplus anywhere).
                logger.warning('[DemandEngine] MODULE 12 skipped: %s', exc)

            # MODULE 13 — Lost Sales Intelligence
            try:
                from .lost_sales_engine import LostSalesEngine
                LostSalesEngine(self.run_obj).run()
                logger.info('[DemandEngine] MODULE 13 — lost sales intelligence computed')
            except Exception as exc:
                # Non-fatal: lost sales calculation should not block the main run.
                logger.warning('[DemandEngine] MODULE 13 skipped: %s', exc)

            elapsed = time.monotonic() - t0
            self.run_obj.status             = 'success'
            self.run_obj.finished_at        = timezone.now()
            self.run_obj.softech_available  = self._softech_ok
            self.run_obj.branches_processed = len(self._branch_map)
            self.run_obj.items_processed    = len({item_id for (item_id, _) in metrics})
            self.run_obj.rows_written       = rows_written
            self.run_obj.duration_seconds   = round(elapsed, 2)
            # True data horizon: latest sale the engine saw (may lag if sync behind)
            try:
                from apps.purchasing.models import SalesTransactionLine
                from django.db.models import Max
                self.run_obj.data_through_date = (
                    SalesTransactionLine.objects.aggregate(mx=Max('doc_date'))['mx']
                )
            except Exception as exc:
                logger.warning('[DemandEngine] data_through_date capture failed: %s', exc)
            self.run_obj.save()

            logger.info(
                '[DemandEngine] Run %d OK | items=%d rows=%d synced=%d purged=%d %.1fs',
                self.run_obj.pk, self.run_obj.items_processed,
                rows_written, rows_synced, rows_purged, elapsed,
            )

        except Exception as exc:
            elapsed = time.monotonic() - t0
            self.run_obj.status           = 'failed'
            self.run_obj.finished_at      = timezone.now()
            self.run_obj.error_message    = str(exc)
            self.run_obj.duration_seconds = round(elapsed, 2)
            self.run_obj.save()
            logger.exception('[DemandEngine] Run %d FAILED: %s', self.run_obj.pk, exc)
            raise

        return self.run_obj

    # ── Config loader ─────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        """
        Load EngineConfig from DB, apply any param_overrides, and populate
        self._weights / self._abc_a / self._abc_b.

        Returns the effective params dict (saved to run.params_snapshot).
        """
        from apps.purchasing.models import EngineConfig
        try:
            cfg = EngineConfig.get()
            base = cfg.as_dict()
        except Exception:
            logger.warning('[DemandEngine] EngineConfig unavailable — using hardcoded defaults')
            base = {
                'weight_30d': WEIGHTS[30], 'weight_90d': WEIGHTS[90],
                'weight_365d': WEIGHTS[365],
                'ss_multiplier':     1.0,
                'ss_high_threshold': 2.0,
                'ss_tier_mid':       2.0,
                'ss_tier_low':       1.0,
                'ss_tier_vlow':      0.5,
                'abc_a_threshold': ABC_A_THRESHOLD,
                'abc_b_threshold': ABC_B_THRESHOLD,
                'coverage_months_a': 1.0,
                'coverage_months_b': 1.0,
                'coverage_months_c': 1.0,
                'in_transit_max_age_days': 14,
            }

        # Apply per-run overrides (frontend can pass these)
        effective = {**base, **self.param_overrides}

        self._weights = {
            30:  effective['weight_30d'],
            90:  effective['weight_90d'],
            365: effective['weight_365d'],
        }
        self._ss_multiplier      = float(effective.get('ss_multiplier',     1.0))
        self._ss_high_threshold  = float(effective.get('ss_high_threshold', 2.0))
        self._ss_tier_mid        = float(effective.get('ss_tier_mid',       2.0))
        self._ss_tier_low        = float(effective.get('ss_tier_low',       1.0))
        self._ss_tier_vlow       = float(effective.get('ss_tier_vlow',      0.5))
        self._abc_a = effective['abc_a_threshold']
        self._abc_b = effective['abc_b_threshold']

        # In-transit freshness cutoff (days). Transfers older than this are stale
        # documents, not live pipeline — excluded from in-transit. 0 = no limit.
        self._intransit_max_age = int(effective.get('in_transit_max_age_days', 14))

        # Per-ABC coverage horizon (months of consumption to stock). 1.0 = legacy.
        self._coverage = {
            'A': float(effective.get('coverage_months_a', 1.0)),
            'B': float(effective.get('coverage_months_b', 1.0)),
            'C': float(effective.get('coverage_months_c', 1.0)),
            'X': 1.0,   # no annual sales → no throughput to scale
        }

        logger.info(
            '[DemandEngine] Config: w30=%.2f w90=%.2f w365=%.2f '
            '| ss×%.2f high≥%.2f mid=%.1f low=%.1f vlow=%.1f '
            '| A<%.0f%% B<%.0f%% | coverage A=%.2f B=%.2f C=%.2f',
            self._weights[30], self._weights[90], self._weights[365],
            self._ss_multiplier, self._ss_high_threshold,
            self._ss_tier_mid, self._ss_tier_low, self._ss_tier_vlow,
            self._abc_a, self._abc_b,
            self._coverage['A'], self._coverage['B'], self._coverage['C'],
        )
        return effective

    # ── Smart lookback determination ──────────────────────────────────────────

    def _determine_lookback(self, requested_days: int) -> int:
        """
        Determine how many days to fetch from SOFTECH based on the last
        upserted row in SalesTransactionLine.

        Strategy: always sync from the last upserted date up to today,
        with a 2-day safety overlap so weekend/late-arriving transactions
        are never missed.  `requested_days` is only used when the caller
        explicitly overrides (e.g. --lookback 30); it no longer caps the
        gap-based window.

        Rules:
          • PG empty                  → full ROLLING_WINDOW_DAYS backfill
          • gap ≤ requested_days      → use gap + 2-day overlap (shrink)
          • gap > requested_days      → use gap + 2-day overlap (EXTEND —
                                        new behaviour: never miss data)
          • Hard ceiling: ROLLING_WINDOW_DAYS (365) — no point fetching
            beyond the purge horizon
          • Floor: 3 days (weekend safety)
        """
        from apps.purchasing.models import SalesTransactionLine
        from django.db.models import Max

        result = SalesTransactionLine.objects.aggregate(latest=Max('doc_date'))
        latest = result.get('latest')

        if latest is None:
            logger.info('[DemandEngine] PG is empty — escalating to full %d-day backfill',
                        ROLLING_WINDOW_DAYS)
            return ROLLING_WINDOW_DAYS

        gap_days  = (self.calc_date - latest).days
        effective = max(gap_days + 2, 3)          # gap-driven; floor 3, +2 overlap
        effective = min(effective, ROLLING_WINDOW_DAYS)  # ceiling: purge horizon

        logger.info(
            '[DemandEngine] Gap-based sync: PG latest=%s  gap=%dd  fetching=%dd',
            latest, gap_days, effective,
        )
        return effective

    # ── MODULE 1 — Load PG lookups ────────────────────────────────────────────

    def _load_lookups(self):
        from apps.branches.models import Branch
        from apps.catalog.models import Item, ItemStock

        logger.info('[DemandEngine] MODULE 1 — loading PG lookups')

        self._branch_map = {
            b['softech_branch_id']: b['id']
            for b in Branch.objects.filter(is_active=True)
                                   .values('id', 'softech_branch_id')
            if b['softech_branch_id']
        }

        # Include active items PLUS discontinued ("امر التوريد" / no_more_use)
        # ones — the latter are is_active=False but still need purchasing
        # visibility when they have sales. Purchasing keys off sales rows, so
        # dead discontinued items (no sales) never appear regardless.
        from django.db.models import Q
        self._item_map = {
            row['softech_id']: (row['id'], float(row['pack_price'] or 0))
            for row in Item.objects.filter(is_stockable=True, softech_id__isnull=False)
                                   .filter(Q(is_active=True) | Q(no_more_use=True))
                                   .exclude(softech_id='')
                                   .values('id', 'softech_id', 'pack_price')
        }
        # O(1) reverse lookup: item_id → pack_price
        self._item_id_to_price = {iid: pp for _, (iid, pp) in self._item_map.items()}

        # ── Current stock: prefer live SOFTECH stkbal, fall back to PG ItemStock ──
        # PG ItemStock is loaded first as the fallback baseline.
        # ItemStock has one row per (item, branch, store_code); SUM them per branch.
        from collections import defaultdict
        pg_stock = defaultdict(float)
        excluded_stores = {'102', '103', '105'}
        for s in ItemStock.objects.values('item_id', 'branch_id',
                                          'softech_store_code', 'quantity_on_hand'):
            if s['softech_store_code'] not in excluded_stores:
                pg_stock[(s['item_id'], s['branch_id'])] += float(s['quantity_on_hand'] or 0)
        self._stock_map = dict(pg_stock)

        # Try to override with live stkbal from SOFTECH
        stkbal_map = self._fetch_stkbal()
        if stkbal_map:
            self._stock_map = stkbal_map
            logger.info(
                '[DemandEngine] current_stock → stkbal (%d pairs; PG fallback had %d)',
                len(stkbal_map), len(pg_stock),
            )
        else:
            logger.info(
                '[DemandEngine] current_stock → PG ItemStock fallback (%d pairs)',
                len(self._stock_map),
            )

        # In-transit (البضاعة بالطريق) — inbound pipeline inventory per branch.
        self._intransit_map = self._load_in_transit()

        logger.info(
            '[DemandEngine] Lookups: %d branches, %d items, %d stock pairs, %d in-transit pairs',
            len(self._branch_map), len(self._item_map),
            len(self._stock_map), len(self._intransit_map),
        )

    def _load_in_transit(self) -> dict:
        """
        Inbound in-transit quantity per (item_id, receiving_branch_id).

        Source: apps.transits.InTransitTransfer rows with transit_status
        'in_transit' (SOFTECH doccode 125 dispatched, not yet received). Sums
        each transfer's items_snapshot qty by destination branch, from ANY
        supplying branch (network-wide pipeline inventory). itemcode joins to
        catalog Item.softech_id; unresolved receiving branches are skipped.

        Returns dict: (item_id, branch_id) → float qty. Empty on any failure
        (in-transit is an enrichment — never block the run over it).
        """
        from collections import defaultdict
        try:
            from apps.transits.models import InTransitTransfer
        except Exception as exc:
            logger.warning('[DemandEngine] transits app unavailable (%s) — in-transit skipped', exc)
            return {}

        # softech_id → item_id  (reuse the already-built item map)
        code_to_id = {code: iid for code, (iid, _price) in self._item_map.items()}

        qs = InTransitTransfer.objects.filter(
            transit_status='in_transit', receiving_branch__isnull=False,
        )
        # Freshness cutoff: SOFTECH transfers received in ~3 days (p90); older
        # "in_transit" rows are stale/unreconciled documents (received-but-unlinked
        # or abandoned) — NOT live pipeline. Excluding them stops phantom qty from
        # shrinking the gap. 0 = disable the filter.
        max_age = getattr(self, '_intransit_max_age', 14)
        excluded = 0
        if max_age and max_age > 0:
            cutoff = timezone.localdate() - datetime.timedelta(days=max_age)
            excluded = qs.filter(issue_date__lt=cutoff).count()
            qs = qs.filter(issue_date__gte=cutoff)

        result = defaultdict(float)
        rows = qs.values_list('receiving_branch_id', 'items_snapshot')
        n_rows = 0
        for branch_id, snapshot in rows.iterator():
            n_rows += 1
            for line in (snapshot or []):
                code = str(line.get('itemcode') or '').strip()
                iid = code_to_id.get(code)
                if iid is None:
                    continue
                try:
                    result[(iid, branch_id)] += float(line.get('qty') or 0)
                except (TypeError, ValueError):
                    pass
        logger.info('[DemandEngine] in-transit: %d live transfers → %d (item,branch) '
                    'pairs (%d stale >%dd excluded)',
                    n_rows, len(result), excluded, max_age)
        return dict(result)

    def _fetch_stkbal(self) -> dict:
        """
        Fetch live current-stock from SOFTECH stkbal.
        Aggregates across storecodes per (itemcode, branchcode), excluding
        quarantine/expiry stores (102, 103, 105).

        Returns dict: (item_id, branch_id) → nowqty
        Returns empty dict if SOFTECH is unavailable (caller uses PG fallback).
        """
        from apps.purchasing.queries import QUERY_STKBAL
        try:
            from config.sybase import get_sybase_connection
            conn   = get_sybase_connection()
            cur    = conn.cursor()
            cur.execute(QUERY_STKBAL)
            rows   = cur.fetchall()
            conn.close()
        except Exception as exc:
            logger.info('[DemandEngine] stkbal fetch skipped (%s) — will use PG ItemStock', exc)
            return {}

        stock_map = {}
        skipped   = 0
        for row in rows:
            itemcode   = str(row[0] or '').strip()
            branchcode = str(row[1] or '').strip()
            nowqty     = float(row[2] or 0)

            entry     = self._item_map.get(itemcode)
            branch_id = self._branch_map.get(branchcode)
            if not entry or not branch_id:
                skipped += 1
                continue

            item_id = entry[0]
            key     = (item_id, branch_id)
            stock_map[key] = stock_map.get(key, 0.0) + nowqty

        logger.info(
            '[DemandEngine] stkbal: %d rows → %d mapped pairs (%d skipped/unmatched)',
            len(rows), len(stock_map), skipped,
        )
        return stock_map

    # ── MODULE 2 — SOFTECH incremental sync (streaming + COPY staging) ────────

    def _sync_from_softech(self, lookback_days: int):
        """
        Fetch the last `lookback_days` of stktrans from SOFTECH and upsert
        into SalesTransactionLine.  Then purge rows older than ROLLING_WINDOW_DAYS.

        Optimisations vs the previous implementation:
          1. fetchmany(5 000)    — streams Sybase rows in chunks, avoids fetchall()
             memory spike on large result sets (100k-5M rows for full backfill).
          2. COPY staging        — buffers rows in io.BytesIO (tab-separated text),
             flushes to a temp staging table using cursor.copy_expert() then
             upserts via a single INSERT … SELECT … ON CONFLICT statement.
          3. SQL FK resolution   — item_id / branch_id are resolved inside the
             INSERT … SELECT via LEFT JOIN catalog_item / branches_branch, removing
             the Python dict lookup loop entirely and eliminating silent data loss
             when new items appear in SOFTECH before the PG catalog is updated.

        Returns: (rows_synced, rows_purged)
        """
        from apps.purchasing.queries import QUERY_SALES_INCREMENTAL

        from datetime import date, timedelta
        sync_from = date.today() - timedelta(days=lookback_days)
        logger.info(
            '[DemandEngine] MODULE 2 — SOFTECH sync (last %dd, from %s to today)',
            lookback_days, sync_from,
        )

        # ── 1. Connect to Sybase and start streaming ──────────────────────────
        try:
            from config.sybase import get_sybase_connection
            syb_conn   = get_sybase_connection()
            syb_cursor = syb_conn.cursor()
            syb_cursor.execute(QUERY_SALES_INCREMENTAL, (lookback_days,))
            self._softech_ok = True
            logger.info('[DemandEngine] SOFTECH connected — streaming from %s', sync_from)
        except Exception as exc:
            logger.warning('[DemandEngine] SOFTECH unavailable: %s — skipping sync', exc)
            self._softech_ok = False
            rows_purged = self._purge_old_rows()
            return 0, rows_purged

        # ── 2. Create PG staging table ────────────────────────────────────────
        with connection.cursor() as pg:
            pg.execute("""
                CREATE TEMP TABLE IF NOT EXISTS _stl_staging (
                    softech_branchcode VARCHAR(20),
                    softech_itemcode   VARCHAR(50),
                    doccode            VARCHAR(10),
                    docnumber          VARCHAR(50),
                    doc_date           DATE,
                    transqty           NUMERIC(14,3),
                    net_qty            NUMERIC(14,3),
                    net_revenue        NUMERIC(18,3)
                )
            """)
            pg.execute("TRUNCATE _stl_staging")   # clear any leftovers from a previous run

        # ── 3. Stream Sybase rows → BytesIO buffer → COPY → upsert ───────────
        rows_synced   = 0
        total_fetched = 0
        buf      = io.BytesIO()
        buf_rows = 0

        def _flush_buffer(buf: io.BytesIO, buf_rows: int) -> int:
            """
            COPY buf into _stl_staging, then INSERT…ON CONFLICT into the main table.
            Returns the number of rows upserted (pg.rowcount after INSERT).
            """
            if buf_rows == 0:
                return 0
            buf.seek(0)
            with connection.cursor() as pg:
                pg.execute("TRUNCATE _stl_staging")
                pg.copy_expert(
                    "COPY _stl_staging "
                    "(softech_branchcode, softech_itemcode, doccode, docnumber, "
                    "doc_date, transqty, net_qty, net_revenue) "
                    "FROM STDIN WITH (FORMAT text)",   # text = tab-delimited
                    buf
                )
                # Safety-net dedup: aggregate staging rows with GROUP BY + SUM before
                # inserting into the main table.
                #
                # Primary dedup happens at Sybase source (QUERY_SALES_INCREMENTAL now
                # uses GROUP BY + SUM(transqty) to collapse expiry-batch split lines
                # into one pre-totalled row per item per document).  This CTE is a
                # defensive second pass that handles any edge-case duplicates that
                # could still arrive (e.g. a Sybase driver quirk re-sending a row).
                #
                # Using SUM — not DISTINCT ON / MAX — is critical: if two staging rows
                # genuinely represent different batch lines that were not aggregated at
                # source, SUM gives the correct total quantity; MAX would silently
                # discard real sales.
                pg.execute("""
                    WITH dedup AS (
                        SELECT
                            softech_branchcode,
                            softech_itemcode,
                            doccode,
                            docnumber,
                            doc_date,
                            SUM(transqty)    AS transqty,
                            SUM(net_qty)     AS net_qty,
                            SUM(net_revenue) AS net_revenue
                        FROM _stl_staging
                        GROUP BY
                            softech_branchcode, softech_itemcode,
                            doccode, docnumber, doc_date
                    )
                    INSERT INTO purchasing_salestransactionline
                        (softech_branchcode, softech_itemcode, doccode, docnumber,
                         doc_date, item_id, branch_id, transqty, net_qty, net_revenue, synced_at)
                    SELECT
                        d.softech_branchcode,
                        d.softech_itemcode,
                        d.doccode,
                        d.docnumber,
                        d.doc_date,
                        ci.id   AS item_id,
                        br.id   AS branch_id,
                        d.transqty,
                        d.net_qty,
                        d.net_revenue,
                        NOW()
                    FROM dedup d
                    LEFT JOIN catalog_item ci
                        ON  ci.softech_id = d.softech_itemcode
                        -- include discontinued (no_more_use) items so their sales
                        -- resolve to an item_id and appear in purchasing
                        AND (ci.is_active = TRUE OR ci.no_more_use = TRUE)
                    LEFT JOIN branches_branch br
                        ON  br.softech_branch_id = d.softech_branchcode
                        AND br.is_active         = TRUE
                    ON CONFLICT ON CONSTRAINT unique_stktrans_line
                    DO UPDATE SET
                        transqty    = EXCLUDED.transqty,
                        net_qty     = EXCLUDED.net_qty,
                        net_revenue = EXCLUDED.net_revenue,
                        -- Prefer resolved FK; keep existing value if new row has no match
                        item_id   = COALESCE(EXCLUDED.item_id,
                                             purchasing_salestransactionline.item_id),
                        branch_id = COALESCE(EXCLUDED.branch_id,
                                             purchasing_salestransactionline.branch_id),
                        synced_at = NOW()
                """)
                return pg.rowcount

        # Stream Sybase in chunks of SYBASE_FETCH_BATCH rows
        while True:
            chunk = syb_cursor.fetchmany(SYBASE_FETCH_BATCH)
            if not chunk:
                break

            for row in chunk:
                branchcode = str(row[0] or '').strip()
                itemcode   = str(row[1] or '').strip()
                doccode    = str(row[2] or '').strip()
                docnumber  = str(row[3] or '').strip()
                docdate          = row[4]
                transqty         = float(row[5] or 0)
                transprice_total = float(row[6] or 0) if len(row) > 6 else 0.0

                if not branchcode or not itemcode or transqty <= 0:
                    continue

                # Normalise datetime → date
                if hasattr(docdate, 'date'):
                    doc_date = docdate.date()
                elif isinstance(docdate, datetime.date):
                    doc_date = docdate
                else:
                    continue

                is_sale = doccode == '115'
                net_qty     =  transqty         if is_sale else -transqty
                net_revenue =  transprice_total  if is_sale else -transprice_total

                # Tab-separated text format; replace any embedded tabs to be safe
                line = (
                    f"{branchcode.replace(chr(9), ' ')}\t"
                    f"{itemcode.replace(chr(9), ' ')}\t"
                    f"{doccode}\t"
                    f"{docnumber.replace(chr(9), ' ')}\t"
                    f"{doc_date}\t"
                    f"{transqty:.3f}\t"
                    f"{net_qty:.3f}\t"
                    f"{net_revenue:.3f}\n"
                )
                buf.write(line.encode('utf-8'))
                buf_rows += 1

            total_fetched += len(chunk)

            # Flush to PG when buffer reaches the chunk threshold
            if buf_rows >= PG_COPY_CHUNK:
                rows_synced += _flush_buffer(buf, buf_rows)
                buf      = io.BytesIO()
                buf_rows = 0
                logger.debug('[DemandEngine] Streamed %d Sybase rows, upserted %d so far',
                             total_fetched, rows_synced)

        try:
            syb_conn.close()
        except Exception:
            pass  # non-critical

        # Flush remaining rows
        rows_synced += _flush_buffer(buf, buf_rows)

        # Cleanup staging table (also auto-dropped at session end)
        try:
            with connection.cursor() as pg:
                pg.execute("DROP TABLE IF EXISTS _stl_staging")
        except Exception:
            pass

        logger.info(
            '[DemandEngine] Sync complete: %d Sybase rows fetched, %d PG rows upserted',
            total_fetched, rows_synced,
        )

        # ── 4. Purge rolling window ───────────────────────────────────────────
        rows_purged = self._purge_old_rows()
        return rows_synced, rows_purged

    def _purge_old_rows(self) -> int:
        """Delete SalesTransactionLine rows older than ROLLING_WINDOW_DAYS."""
        from apps.purchasing.models import SalesTransactionLine
        cutoff = self.calc_date - datetime.timedelta(days=ROLLING_WINDOW_DAYS)
        rows_purged, _ = SalesTransactionLine.objects.filter(doc_date__lt=cutoff).delete()
        if rows_purged:
            logger.info('[DemandEngine] Purged %d rows older than %s', rows_purged, cutoff)
        return rows_purged

    # ── MODULE 3 — Single-pass raw SQL aggregation from PG ───────────────────

    def _aggregate_from_pg(self) -> list:
        """
        Compute 30/90/365-day aggregates from PG SalesTransactionLine using a
        single raw SQL query with CASE WHEN per column.

        Replaces the ORM annotate() approach which Django compiled into multiple
        conditional passes.  This version does exactly one sequential scan of
        purchasing_salestransactionline (aided by partial index stl_agg_sales_idx).

        Returns a list of dicts with keys:
          item_id, branch_id,
          qty_365d, qty_90d, qty_30d,
          inv_365d, inv_90d, inv_30d,
          trns_365d, trns_90d, trns_30d,
          last_sale_date, net_sales_revenue_365d
        """
        from apps.purchasing.queries import PG_AGGREGATE_SQL

        logger.info('[DemandEngine] MODULE 3 — single-pass raw SQL aggregation')

        today = self.calc_date
        d30   = today - datetime.timedelta(days=30)
        d90   = today - datetime.timedelta(days=90)
        d365  = today - datetime.timedelta(days=ROLLING_WINDOW_DAYS)

        with connection.cursor() as cur:
            cur.execute(PG_AGGREGATE_SQL, {'d30': d30, 'd90': d90, 'd365': d365})
            col_names = [col[0] for col in cur.description]
            rows = [dict(zip(col_names, row)) for row in cur.fetchall()]

        logger.info('[DemandEngine] PG aggregation: %d item-branch pairs', len(rows))
        return rows

    # ── MODULES 4–8 — Per-branch metric calculation ───────────────────────────

    def _calculate_per_branch(self, pg_rows: list) -> dict:
        """
        Process each PG aggregation row through Excel-exact formulas.
        Returns dict: (item_id, branch_id) → metrics dict.
        """
        logger.info('[DemandEngine] MODULES 4-8 — calculating %d rows', len(pg_rows))

        results = {}

        for row in pg_rows:
            item_id   = row['item_id']
            branch_id = row['branch_id']

            pack_price = self._item_id_to_price.get(item_id, 0.0)

            qty_30d  = float(row['qty_30d']  or 0)
            qty_90d  = float(row['qty_90d']  or 0)
            qty_365d = float(row['qty_365d'] or 0)

            inv_30d  = int(row['inv_30d']  or 0)
            inv_90d  = int(row['inv_90d']  or 0)
            inv_365d = int(row['inv_365d'] or 0)

            trns_30d  = int(row['trns_30d']  or 0)
            trns_90d  = int(row['trns_90d']  or 0)
            trns_365d = int(row['trns_365d'] or 0)

            # MODULE 3 — monthly rates (Excel-exact)
            rate_30d  = calc_monthly_rate(qty_30d,  30)
            rate_90d  = calc_monthly_rate(qty_90d,  90)
            rate_365d = calc_monthly_rate(qty_365d, 365)

            # MODULE 4 — weighted average (uses runtime config weights)
            monthly_avg = calc_weighted_avg(rate_30d, rate_90d, rate_365d,
                                            weights=self._weights)

            # TRNs simple average
            monthly_avg_trns = calc_trns_avg(trns_30d, trns_90d, trns_365d)

            # MODULE 5 — safety stock (configurable tiers)
            ss = calc_safety_stock(
                monthly_avg,
                self._ss_multiplier,
                self._ss_high_threshold,
                self._ss_tier_mid,
                self._ss_tier_low,
                self._ss_tier_vlow,
            )

            # Current stock from PG snapshot
            current_stock = self._stock_map.get((item_id, branch_id), 0.0)

            # In-transit (البضاعة بالطريق) — inbound qty dispatched but not received.
            in_transit = self._intransit_map.get((item_id, branch_id), 0.0)

            # MODULE 6 — coverage (on-hand only; in-transit is not yet on the shelf)
            cov = calc_coverage(current_stock, monthly_avg)

            # MODULE 7 — gap (can be negative = overstock). In-transit is pipeline
            # inventory → netted out like on-hand: gap = target − stock − in_transit.
            gap = calc_gap(current_stock + in_transit, ss, monthly_avg)

            # MODULE 8 — priority
            pri = calc_priority(cov, gap)

            # Monthly value (for ABC Pareto)
            monthly_value = monthly_avg * pack_price

            # Actual revenue captured from stktrans (365-day window)
            net_sales_revenue = float(row.get('net_sales_revenue_365d') or 0)

            results[(item_id, branch_id)] = {
                'item_id':            item_id,
                'branch_id':          branch_id,
                'pack_price':         pack_price,
                'qty_30d':            qty_30d,
                'qty_90d':            qty_90d,
                'qty_365d':           qty_365d,
                'invoices_30d':       inv_30d,
                'invoices_90d':       inv_90d,
                'invoices_365d':      inv_365d,
                'trns_30d':           trns_30d,
                'trns_90d':           trns_90d,
                'trns_365d':          trns_365d,
                'rate_30d':           rate_30d,
                'rate_90d':           rate_90d,
                'rate_365d':          rate_365d,
                'monthly_avg':        monthly_avg,
                'monthly_avg_trns':   monthly_avg_trns,
                'safety_stock':       ss,
                'current_stock':      current_stock,
                'in_transit_qty':     in_transit,
                'coverage_months':    cov,
                'gap':                gap,
                'priority':           pri,
                'monthly_value':      monthly_value,
                'net_sales_revenue':  net_sales_revenue,
                'last_sale_date':     row.get('last_sale_date'),
                'pct_stock_of_total': None,  # filled in MODULE 9
                'abc_class':          'X',   # filled in MODULE 10
            }

        logger.info('[DemandEngine] Calculated %d item-branch pairs', len(results))
        return results

    # ── MODULE 9 — Network aggregation + pct_stock_of_total ──────────────────

    def _aggregate_network(self, metrics: dict) -> dict:
        """
        Collapse per-branch metrics into per-item network totals.
        Also computes pct_stock_of_total for each branch metric (mutates in-place).

        Single pass: accumulate network totals while iterating, then compute pct
        in a second pass (O(n) total; unavoidable since we need the denominator first).

        Returns: item_id → aggregated dict.
        """
        logger.info('[DemandEngine] MODULE 9 — aggregating network totals')

        agg = defaultdict(lambda: {
            'item_id':                  None,
            'pack_price':               0.0,
            'total_qty_30d':            0.0,
            'total_qty_90d':            0.0,
            'total_qty_365d':           0.0,
            'total_monthly_avg':        0.0,
            'total_current_stock':      0.0,
            'total_in_transit':         0.0,
            'total_monthly_value':      0.0,
            'total_gap':                0.0,
            'total_net_sales_revenue':  0.0,
            'branches_with_sales':      0,
            'branches_with_gap':        0,
            'abc_class':                'X',
            'cumulative_pct':           0.0,
        })

        for (item_id, branch_id), m in metrics.items():
            a = agg[item_id]
            a['item_id']                 = item_id
            a['pack_price']              = m['pack_price']
            a['total_qty_30d']          += m['qty_30d']
            a['total_qty_90d']          += m['qty_90d']
            a['total_qty_365d']         += m['qty_365d']
            a['total_monthly_avg']      += m['monthly_avg']
            a['total_current_stock']    += m['current_stock']
            a['total_in_transit']       += m.get('in_transit_qty', 0.0)
            a['total_monthly_value']    += m['monthly_value']
            a['total_net_sales_revenue'] += m['net_sales_revenue']
            if m['gap'] > 0:
                a['total_gap']           += m['gap']
                a['branches_with_gap']   += 1
            a['branches_with_sales'] += 1

        # Compute pct_stock_of_total per branch (second pass — denominator now known)
        for (item_id, branch_id), m in metrics.items():
            total_stock = agg[item_id]['total_current_stock']
            if total_stock and total_stock > 0:
                m['pct_stock_of_total'] = m['current_stock'] / total_stock
            else:
                m['pct_stock_of_total'] = 0.0

        return dict(agg)

    # ── MODULE 10 — ABC Pareto ────────────────────────────────────────────────

    def _classify_abc(self, aggregated: dict):
        """Pareto ABC on network monthly value. Mutates aggregated in-place."""
        logger.info('[DemandEngine] MODULE 10 — ABC Pareto')

        items_with_value = [
            (iid, d) for iid, d in aggregated.items()
            if d['total_monthly_value'] > 0
        ]
        if not items_with_value:
            return

        items_with_value.sort(key=lambda x: x[1]['total_monthly_value'], reverse=True)
        total_value = sum(d['total_monthly_value'] for _, d in items_with_value)
        cumulative  = 0.0

        for item_id, d in items_with_value:
            cumulative        += d['total_monthly_value']
            pct                = (cumulative / total_value) * 100.0
            d['cumulative_pct'] = round(pct, 3)
            d['abc_class']      = abc_class_from_pct(pct, self._abc_a, self._abc_b)

    # ── MODULE 10.5 — Per-ABC coverage horizon ────────────────────────────────

    def _apply_coverage(self, metrics: dict, aggregated: dict):
        """
        Re-derive gap + priority using each item's ABC-specific coverage horizon,
        then re-sum the network totals. Mutates both dicts in-place.

        Must run AFTER _classify_abc (needs abc_class) and BEFORE _persist.
        When every coverage_months is 1.0 this is a no-op (values are unchanged),
        so default config exactly reproduces the legacy 1-month output.

        Coverage is an item-level attribute (from ABC), so all branches of an
        item share the same horizon — re-summing per-branch gaps yields the
        correct network total_gap.
        """
        if all(c == 1.0 for c in self._coverage.values()):
            return   # nothing to do — legacy behaviour

        logger.info('[DemandEngine] MODULE 10.5 — applying per-ABC coverage %s',
                    {k: v for k, v in self._coverage.items() if k in ('A', 'B', 'C')})

        # 1. Recompute per-branch gap + priority with the item's coverage.
        for (item_id, branch_id), m in metrics.items():
            agg = aggregated.get(item_id)
            abc = agg['abc_class'] if agg else 'X'
            m['abc_class'] = abc
            cov_months = self._coverage.get(abc, 1.0)

            gap = calc_gap(m['current_stock'] + m.get('in_transit_qty', 0.0),
                           m['safety_stock'], m['monthly_avg'], cov_months)
            m['gap']      = gap
            # priority uses stock-on-hand coverage (m['coverage_months']), not the
            # target horizon — recompute against the new gap only.
            m['priority'] = calc_priority(m['coverage_months'], gap)

        # 2. Re-sum network total_gap / branches_with_gap from the new gaps.
        for a in aggregated.values():
            a['total_gap']         = 0.0
            a['branches_with_gap'] = 0
        for (item_id, branch_id), m in metrics.items():
            a = aggregated.get(item_id)
            if a is None:
                continue
            if m['gap'] > 0:
                a['total_gap']         += m['gap']
                a['branches_with_gap'] += 1

    # ── MODULE 11 — Persist ───────────────────────────────────────────────────

    def _persist(self, metrics: dict, aggregated: dict) -> int:
        """Bulk upsert metrics + aggregated. Returns total rows written."""
        from apps.purchasing.models import ItemDemandMetrics, ItemDemandAggregated

        logger.info('[DemandEngine] MODULE 11 — persisting %d rows', len(metrics))

        # Propagate ABC class from aggregated → per-branch
        for (item_id, branch_id), m in metrics.items():
            agg = aggregated.get(item_id)
            if agg:
                m['abc_class'] = agg['abc_class']

        BATCH = 500
        rows_written = 0

        # ── Per-branch ItemDemandMetrics ──────────────────────────────────────
        metric_objs = []
        for (item_id, branch_id), m in metrics.items():
            cov = m['coverage_months']
            pct = m['pct_stock_of_total']
            metric_objs.append(ItemDemandMetrics(
                run_id             = self.run_obj.pk,
                item_id            = item_id,
                branch_id          = branch_id,
                calc_date          = self.calc_date,
                qty_30d            = _D(m['qty_30d']),
                qty_90d            = _D(m['qty_90d']),
                qty_365d           = _D(m['qty_365d']),
                invoices_30d       = m['invoices_30d'],
                invoices_90d       = m['invoices_90d'],
                invoices_365d      = m['invoices_365d'],
                trns_30d           = m['trns_30d'],
                trns_90d           = m['trns_90d'],
                trns_365d          = m['trns_365d'],
                rate_30d           = _D(m['rate_30d']),
                rate_90d           = _D(m['rate_90d']),
                rate_365d          = _D(m['rate_365d']),
                monthly_avg        = _D(m['monthly_avg']),
                monthly_avg_trns   = _D(m['monthly_avg_trns']),
                safety_stock       = _D(m['safety_stock']),
                current_stock      = _D(m['current_stock']),
                in_transit_qty     = _D(m.get('in_transit_qty', 0.0)),
                coverage_months    = _D(cov) if cov is not None else None,
                pct_stock_of_total = _D(pct) if pct is not None else None,
                gap                = _D(m['gap']),
                priority           = _D(m['priority']),
                abc_class          = m['abc_class'],
                pack_price         = _D(m['pack_price']),
                monthly_value      = _D(m['monthly_value']),
                net_sales_revenue  = _D(m['net_sales_revenue']),
                last_sale_date     = m['last_sale_date'],
            ))

        with transaction.atomic():
            for i in range(0, len(metric_objs), BATCH):
                chunk = metric_objs[i:i + BATCH]
                ItemDemandMetrics.objects.bulk_create(
                    chunk,
                    update_conflicts=True,
                    unique_fields=['run_id', 'item_id', 'branch_id'],
                    update_fields=[
                        'calc_date', 'qty_30d', 'qty_90d', 'qty_365d',
                        'invoices_30d', 'invoices_90d', 'invoices_365d',
                        'trns_30d', 'trns_90d', 'trns_365d',
                        'rate_30d', 'rate_90d', 'rate_365d',
                        'monthly_avg', 'monthly_avg_trns', 'safety_stock',
                        'current_stock', 'in_transit_qty', 'coverage_months',
                        'pct_stock_of_total',
                        'gap', 'priority', 'abc_class', 'pack_price',
                        'monthly_value', 'net_sales_revenue', 'last_sale_date',
                    ],
                )
                rows_written += len(chunk)

        # ── Aggregated (network) ItemDemandAggregated ─────────────────────────
        agg_objs = []
        for item_id, a in aggregated.items():
            agg_objs.append(ItemDemandAggregated(
                run_id              = self.run_obj.pk,
                item_id             = item_id,
                calc_date           = self.calc_date,
                total_qty_30d       = _D(a['total_qty_30d']),
                total_qty_90d       = _D(a['total_qty_90d']),
                total_qty_365d      = _D(a['total_qty_365d']),
                total_monthly_avg   = _D(a['total_monthly_avg']),
                total_current_stock = _D(a['total_current_stock']),
                total_in_transit    = _D(a['total_in_transit']),
                total_monthly_value = _D(a['total_monthly_value']),
                total_gap                = _D(a['total_gap']),
                abc_class                = a['abc_class'],
                cumulative_pct           = _D(a['cumulative_pct']),
                branches_with_sales      = a['branches_with_sales'],
                branches_with_gap        = a['branches_with_gap'],
                pack_price               = _D(a['pack_price']),
                total_net_sales_revenue  = _D(a['total_net_sales_revenue']),
            ))

        with transaction.atomic():
            for i in range(0, len(agg_objs), BATCH):
                chunk = agg_objs[i:i + BATCH]
                ItemDemandAggregated.objects.bulk_create(
                    chunk,
                    update_conflicts=True,
                    unique_fields=['run_id', 'item_id'],
                    update_fields=[
                        'calc_date', 'total_qty_30d', 'total_qty_90d', 'total_qty_365d',
                        'total_monthly_avg', 'total_current_stock', 'total_in_transit',
                        'total_monthly_value',
                        'total_gap', 'abc_class', 'cumulative_pct',
                        'branches_with_sales', 'branches_with_gap', 'pack_price',
                        'total_net_sales_revenue',
                    ],
                )
                rows_written += len(chunk)

        logger.info('[DemandEngine] Persisted %d total rows', rows_written)
        return rows_written
