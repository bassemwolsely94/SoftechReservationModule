"""
apps/purchasing/lost_sales_engine.py  —  v3 (configurable + bulk-sale fix)

MODULE 13 — Lost Sales + Replenishment Intelligence Engine

Runs after MODULE 11 (persist) and MODULE 12 (transfer recs) as part of
the DemandEngine pipeline.

─────────────────────────────────────────────────────────────────────────────
HOW STOCKOUT DETECTION WORKS
─────────────────────────────────────────────────────────────────────────────

The engine never has a day-by-day stock history.  It estimates stockout days
from the gap between expected and actual sales activity:

  expected_sale_days  = ROUND(monthly_avg)           ← how many days we'd
                                                         expect ≥1 sale
  actual_sale_days    = COUNT(DISTINCT doc_date)      ← days that had a sale
  actual_qty_sold     = SUM(net_qty)                  ← total qty sold in window

  BULK-SALE CHECK (NEW — v3):
    If actual_qty_sold ≥ monthly_avg × ls_bulk_sale_coverage_pct
    → stockout_days = 0
    This handles institutional / hospital sales where a customer buys the full
    month's stock in 1–3 large transactions.  Without this check those items
    would show 25+ false stockout days.

  STANDARD CASE:
    stockout_days = MAX(0, MIN(expected_sale_days − actual_sale_days, 30))
    Only applied when daily_demand ≥ ls_min_daily_demand (skip near-zero movers).

─────────────────────────────────────────────────────────────────────────────
ROOT CAUSE WATERFALL  (evaluated only when stockout_days > 0)
─────────────────────────────────────────────────────────────────────────────

  1. expiry    — PurchaseLine.return_type='expiry' for this (item, branch) in 90d
  2. transfer  — pending TransferRecommendation to this branch in current run
  3. forecast  — rate_30d > rate_365d × ls_forecast_spike_ratio  (demand spike)
  4. purchasing — gap > 0 AND no purchase order placed in last 30 days
  5. supplier  — gap > 0 AND purchase order WAS placed (ordered but not delivered)
  6. unknown   — default / item has no meaningful demand

─────────────────────────────────────────────────────────────────────────────
TUNABLE PARAMETERS  (all stored in EngineConfig, editable via Django admin)
─────────────────────────────────────────────────────────────────────────────

  ls_min_daily_demand       (default 0.03)
      Minimum daily_demand = monthly_avg/30 for an item to be included in
      stockout detection.  Items below this are very slow movers; zero-sale
      days are noise, not signals.

  ls_bulk_sale_coverage_pct  (default 0.85)
      KEY PARAMETER.  If actual_qty_sold / monthly_avg ≥ this, the engine
      concludes demand was fulfilled in bulk and sets stockout_days = 0.
      Raise to 1.0 if you only want to suppress when qty equals OR exceeds
      demand.  Lower to 0.7 to be more aggressive at suppressing bulk patterns.

  ls_forecast_spike_ratio    (default 1.35)
      Root cause 'forecast' fires when rate_30d > rate_365d × this factor.
      Raise (e.g. 1.5) to only flag large spikes.  Lower (e.g. 1.2) to be
      more sensitive to demand increases.

  ls_bottleneck_days         (default 7.0)
      Items with coverage_days < this while still in stock are flagged as
      'bottleneck' (near-OOS risk).  Equals typical lead-time; raise for
      slower supply chains, lower for faster ones.

─────────────────────────────────────────────────────────────────────────────
PERFORMANCE
─────────────────────────────────────────────────────────────────────────────
  All computation runs in 3 SQL statements (one CTE UPDATE + two rollups).
  Zero Python loops over rows.  Expected: ~6 s for 30 K pairs.
"""

import logging
import datetime
from decimal import Decimal

from django.db import connection, transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky.purchasing.lost_sales')


class LostSalesEngine:
    """
    MODULE 13 — Lost Sales Intelligence.

    Usage:
        LostSalesEngine(demand_calculation_run).run()
    """

    # ─────────────────────────────────────────────────────────────────────────
    # CORE SQL — single CTE UPDATE that computes + writes all 8 MODULE 13 fields
    # ─────────────────────────────────────────────────────────────────────────
    #
    # Named parameters (%(name)s) are injected from the EngineConfig singleton
    # so every threshold is tunable without code changes.
    #
    # Parameter reference:
    #   %(run_pk)s                  — current DemandCalculationRun PK
    #   %(d30)s / %(d90)s           — date boundaries
    #   %(calc_date)s               — engine calc date
    #   %(ls_min_daily_demand)s     — skip items below this daily demand
    #   %(ls_bulk_sale_coverage_pct)s — bulk-sale suppression threshold
    #   %(ls_forecast_spike_ratio)s — rate_30d / rate_365d spike multiplier
    #   %(ls_bottleneck_days)s      — coverage_days threshold for bottleneck flag

    _UPDATE_METRICS_SQL = """
    WITH

    -- ── 1. Sale stats per (item, branch) in the last 30 days ─────────────────
    --    sale_day_cnt : COUNT(DISTINCT doc_date)  — number of days with a sale
    --    total_qty_sold : SUM(net_qty)             — total units actually sold
    --    Both used together to detect bulk-sale patterns (v3 fix).
    sale_stats_cte AS (
        SELECT
            item_id,
            branch_id,
            COUNT(DISTINCT doc_date)::INT                AS sale_day_cnt,
            COALESCE(SUM(net_qty), 0)::NUMERIC           AS total_qty_sold
        FROM  purchasing_salestransactionline
        WHERE doccode    = '115'
          AND doc_date  >= %(d30)s
          AND doc_date  <= %(calc_date)s
          AND item_id   IS NOT NULL
          AND branch_id IS NOT NULL
        GROUP BY item_id, branch_id
    ),

    -- ── 2. (item, branch) pairs with an expiry return in last 90 days ────────
    expiry_pairs AS (
        SELECT DISTINCT item_id, branch_id
        FROM  procurement_purchaseline
        WHERE return_type = 'expiry'
          AND doc_date   >= %(d90)s
          AND item_id    IS NOT NULL
          AND branch_id  IS NOT NULL
    ),

    -- ── 3. (item, to_branch) pairs with a pending transfer recommendation ────
    transfer_pairs AS (
        SELECT DISTINCT tr.item_id,
                        tr.to_branch_id AS branch_id
        FROM  purchasing_transferrecommendation     tr
        JOIN  purchasing_transferrecommendationrun  trr ON trr.id = tr.run_id
        WHERE trr.demand_run_id = %(run_pk)s
          AND tr.status = 'pending'
    ),

    -- ── 4. Items that had a purchase order placed in the last 30 days ─────────
    --    Uses item_code (= softech_id) because PurchaseLine may not have item FK.
    recent_buys AS (
        SELECT DISTINCT item_code
        FROM  procurement_purchaseline
        WHERE is_return  = FALSE
          AND doc_date  >= %(d30)s
          AND item_code IS NOT NULL
          AND item_code  <> ''
    ),

    -- ── 5. One-pass join: derive all intermediate values ──────────────────────
    base_calc AS (
        SELECT
            m.id,
            COALESCE(m.monthly_avg, 0)    AS monthly_avg,
            COALESCE(m.current_stock, 0)  AS current_stock,
            COALESCE(m.gap, 0)            AS gap,
            COALESCE(m.rate_30d, 0)       AS rate_30d,
            COALESCE(m.rate_365d, 0)      AS rate_365d,
            COALESCE(m.pack_price, 0)     AS pack_price,
            COALESCE(ci.cost_price, 0)    AS cost_price,

            -- coverage_days: how many days of stock remain at current demand rate
            CASE
                WHEN COALESCE(m.monthly_avg, 0) > 0
                THEN ROUND(
                         (COALESCE(m.current_stock, 0)
                          / (COALESCE(m.monthly_avg, 0) / 30.0)
                         )::NUMERIC, 1)
                ELSE NULL
            END AS coverage_days,

            -- daily_demand: expected units sold per day
            COALESCE(m.monthly_avg, 0) / 30.0 AS daily_demand,

            -- ── STOCKOUT DAYS (v3 logic) ──────────────────────────────────────
            --
            -- Step A: skip if item is too slow to detect
            --   daily_demand < ls_min_daily_demand → 0
            --
            -- Step B: BULK-SALE DETECTION
            --   If the branch actually sold >= monthly_avg × ls_bulk_sale_coverage_pct
            --   in the 30-day window, demand was fulfilled — just in large batches.
            --   Zero-sale days are gaps between bulk orders, not OOS.
            --   → stockout_days = 0
            --   Example (item 128643 OMNITROPE):
            --     monthly_avg=35.7, actual_qty_sold=80, coverage=80/35.7=224%% → 0 days
            --
            -- Step C: standard gap method
            --   stockout_days = expected_sale_days − actual_sale_days, capped at 30
            CASE
                -- A: too slow to measure
                WHEN COALESCE(m.monthly_avg, 0) / 30.0 < %(ls_min_daily_demand)s
                THEN 0

                -- B: bulk-sale — demand was actually fulfilled (qty check)
                WHEN COALESCE(ss.total_qty_sold, 0)
                     >= COALESCE(m.monthly_avg, 0) * %(ls_bulk_sale_coverage_pct)s
                THEN 0

                -- C: standard day-gap method
                ELSE GREATEST(0, LEAST(
                         LEAST(30, GREATEST(0,
                             ROUND(COALESCE(m.monthly_avg, 0)::NUMERIC, 0)::INT
                         ))
                         - COALESCE(ss.sale_day_cnt, 0),
                         30
                     ))
            END AS stockout_days,

            -- bottleneck_days: currently in stock but coverage < lead-time threshold
            CASE
                WHEN COALESCE(m.monthly_avg, 0) > 0
                 AND COALESCE(m.current_stock, 0) > 0
                 AND (COALESCE(m.current_stock, 0)
                      / (COALESCE(m.monthly_avg, 0) / 30.0)) < %(ls_bottleneck_days)s
                THEN %(ls_bottleneck_days)s::INT
                ELSE 0
            END AS bottleneck_days,

            -- lookup flags (evaluated once per row)
            (ep.item_id  IS NOT NULL) AS has_expiry,
            (tp.item_id  IS NOT NULL) AS has_transfer,
            (rb.item_code IS NOT NULL) AS has_recent_buy

        FROM  purchasing_itemdemandmetrics m
        JOIN  catalog_item ci ON ci.id = m.item_id
        LEFT JOIN sale_stats_cte ss ON ss.item_id   = m.item_id AND ss.branch_id   = m.branch_id
        LEFT JOIN expiry_pairs   ep ON ep.item_id   = m.item_id AND ep.branch_id   = m.branch_id
        LEFT JOIN transfer_pairs tp ON tp.item_id   = m.item_id AND tp.branch_id   = m.branch_id
        LEFT JOIN recent_buys    rb ON rb.item_code = ci.softech_id
        WHERE m.run_id = %(run_pk)s
    ),

    -- ── 6. Derive the 8 final MODULE 13 fields ───────────────────────────────
    final_vals AS (
        SELECT
            id,
            coverage_days,
            stockout_days,
            bottleneck_days,

            -- lost_qty_30d: estimated units lost to stockout
            CASE
                WHEN stockout_days > 0 AND daily_demand > 0
                THEN ROUND((stockout_days * daily_demand)::NUMERIC, 3)
                ELSE 0::NUMERIC
            END AS lost_qty_30d,

            -- lost_revenue_30d: lost units × pack price
            CASE
                WHEN stockout_days > 0 AND daily_demand > 0 AND pack_price > 0
                THEN ROUND((stockout_days * daily_demand * pack_price)::NUMERIC, 2)
                ELSE 0::NUMERIC
            END AS lost_revenue_30d,

            -- lost_margin_30d: lost units × (pack_price − cost_price)
            CASE
                WHEN stockout_days > 0 AND daily_demand > 0
                     AND pack_price > 0 AND cost_price > 0
                THEN ROUND(
                         (stockout_days * daily_demand * (pack_price - cost_price))::NUMERIC,
                         2)
                ELSE 0::NUMERIC
            END AS lost_margin_30d,

            -- availability_rate_30d: %% of 30 days item was available
            ROUND(((30.0 - stockout_days) / 30.0 * 100.0)::NUMERIC, 1)
                AS availability_rate_30d,

            -- root_cause waterfall (only meaningful when stockout_days > 0)
            CASE
                WHEN stockout_days = 0
                THEN 'unknown'

                WHEN has_expiry
                -- Recent expiry returns → expiry waste caused the OOS
                THEN 'expiry'

                WHEN has_transfer
                -- Surplus available at another branch but not redistributed
                THEN 'transfer'

                WHEN rate_365d > 0
                 AND rate_30d > rate_365d * %(ls_forecast_spike_ratio)s
                -- Demand spiked more than forecast_spike_ratio above annual rate
                THEN 'forecast'

                WHEN gap > 0 AND NOT has_recent_buy
                -- Gap exists AND no purchase order was placed → purchasing missed it
                THEN 'purchasing'

                WHEN gap > 0
                -- Gap exists but purchase WAS ordered → supplier delay / under-delivery
                THEN 'supplier'

                ELSE 'unknown'
            END AS root_cause

        FROM base_calc
    )

    -- ── 7. Write all 8 fields in one atomic UPDATE ───────────────────────────
    UPDATE purchasing_itemdemandmetrics t
    SET
        coverage_days         = f.coverage_days,
        stockout_days_30d     = f.stockout_days::SMALLINT,
        bottleneck_days_30d   = f.bottleneck_days::SMALLINT,
        lost_qty_30d          = f.lost_qty_30d,
        lost_revenue_30d      = f.lost_revenue_30d,
        lost_margin_30d       = f.lost_margin_30d,
        availability_rate_30d = f.availability_rate_30d,
        root_cause            = f.root_cause
    FROM final_vals f
    WHERE t.id = f.id
    RETURNING
        t.stockout_days_30d,
        t.lost_revenue_30d,
        t.lost_margin_30d,
        t.root_cause
    """

    # ── Aggregated rollup (single SQL, unchanged from v2) ────────────────────

    _UPDATE_AGGREGATED_SQL = """
        UPDATE purchasing_itemdemandaggregated agg
        SET
            total_lost_qty_30d            = sub.sum_lost_qty,
            total_lost_revenue_30d        = sub.sum_lost_rev,
            total_lost_margin_30d         = sub.sum_lost_margin,
            network_availability_rate_30d = sub.avg_avail
        FROM (
            SELECT
                item_id,
                SUM(lost_qty_30d)          AS sum_lost_qty,
                SUM(lost_revenue_30d)      AS sum_lost_rev,
                SUM(lost_margin_30d)       AS sum_lost_margin,
                AVG(availability_rate_30d) AS avg_avail
            FROM purchasing_itemdemandmetrics
            WHERE run_id = %s
            GROUP BY item_id
        ) sub
        WHERE agg.run_id  = %s
          AND agg.item_id = sub.item_id
    """

    # ── Supplier profile rollup (single SQL CTE UPDATE) ──────────────────────

    _UPDATE_SUPPLIER_SQL = """
        WITH supplier_rollup AS (
            SELECT
                ci.supplier_code,
                COALESCE(
                    SUM(m.lost_revenue_30d) FILTER (WHERE m.root_cause = 'supplier'),
                    0
                ) AS avoidable_loss,
                COALESCE(SUM(m.monthly_avg),   0) AS total_monthly_expected,
                COALESCE(SUM(m.lost_qty_30d),  0) AS total_lost_qty
            FROM  purchasing_itemdemandmetrics m
            JOIN  catalog_item ci ON ci.id = m.item_id
            WHERE m.run_id = %s
              AND ci.supplier_code IS NOT NULL
              AND ci.supplier_code <> ''
            GROUP BY ci.supplier_code
        )
        UPDATE procurement_supplierprofile sp
        SET
            avoidable_loss_value = sr.avoidable_loss,
            service_level_pct    = CASE
                WHEN sr.total_monthly_expected > 0
                THEN GREATEST(0,
                         ROUND(
                             ((sr.total_monthly_expected - sr.total_lost_qty)
                              / sr.total_monthly_expected * 100
                             )::NUMERIC,
                             2
                         )
                     )
                ELSE 100.00
            END
        FROM supplier_rollup sr
        WHERE sp.supplier_code = sr.supplier_code
    """

    # ─────────────────────────────────────────────────────────────────────────

    def __init__(self, demand_run):
        self.demand_run = demand_run
        self.calc_date  = demand_run.calc_date
        self.run_obj    = None

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC ENTRY POINT
    # ─────────────────────────────────────────────────────────────────────────

    def run(self):
        from .models import LostSalesRun, EngineConfig
        from collections import defaultdict

        self.run_obj = LostSalesRun.objects.create(
            demand_run=self.demand_run,
            status='running',
        )

        try:
            with transaction.atomic():
                calc_date = self.calc_date or datetime.date.today()
                d30       = calc_date - datetime.timedelta(days=30)
                d90       = calc_date - datetime.timedelta(days=90)

                # ── Load tunable parameters from EngineConfig singleton ───────
                cfg = EngineConfig.get()

                params = {
                    # Context
                    'run_pk':    self.demand_run.pk,
                    'd30':       d30,
                    'd90':       d90,
                    'calc_date': calc_date,
                    # MODULE 13 tunable thresholds (from EngineConfig)
                    'ls_min_daily_demand':       cfg.ls_min_daily_demand,
                    'ls_bulk_sale_coverage_pct': cfg.ls_bulk_sale_coverage_pct,
                    'ls_forecast_spike_ratio':   cfg.ls_forecast_spike_ratio,
                    'ls_bottleneck_days':        cfg.ls_bottleneck_days,
                }

                logger.info(
                    '[LostSalesEngine] Starting run %d | bulk_coverage=%.0f%%  '
                    'min_daily=%.3f  spike_ratio=%.2f  bottleneck=%dd',
                    self.demand_run.pk,
                    cfg.ls_bulk_sale_coverage_pct * 100,
                    cfg.ls_min_daily_demand,
                    cfg.ls_forecast_spike_ratio,
                    int(cfg.ls_bottleneck_days),
                )

                # ── ONE SQL round-trip: compute + write all 8 fields ──────────
                root_cause_counts: dict[str, int] = defaultdict(int)
                total_lost_rev    = Decimal('0')
                total_lost_margin = Decimal('0')
                items_affected    = 0

                with connection.cursor() as cur:
                    cur.execute(self._UPDATE_METRICS_SQL, params)
                    returned_rows = cur.fetchall()
                    # [(stockout_days, lost_revenue, lost_margin, root_cause), ...]

                for stockout_days, lost_rev, lost_margin, root_cause in returned_rows:
                    root_cause_counts[root_cause or 'unknown'] += 1
                    if lost_rev and lost_rev > 0:
                        items_affected    += 1
                        total_lost_rev    += Decimal(str(lost_rev))
                        total_lost_margin += Decimal(str(lost_margin or 0))

                row_count = len(returned_rows)

                if row_count == 0:
                    self.run_obj.status      = 'success'
                    self.run_obj.finished_at = timezone.now()
                    self.run_obj.save()
                    return self.run_obj

                # ── Aggregated rollup ────────────────────────────────────────
                with connection.cursor() as cur:
                    cur.execute(
                        self._UPDATE_AGGREGATED_SQL,
                        [self.demand_run.pk, self.demand_run.pk],
                    )

                # ── Supplier profile rollup ──────────────────────────────────
                with connection.cursor() as cur:
                    cur.execute(self._UPDATE_SUPPLIER_SQL, [self.demand_run.pk])

                # ── Finalize audit log ────────────────────────────────────────
                self.run_obj.items_affected       = items_affected
                self.run_obj.branch_item_pairs    = row_count
                self.run_obj.total_lost_revenue   = total_lost_rev
                self.run_obj.total_lost_margin    = total_lost_margin
                self.run_obj.root_cause_breakdown = dict(root_cause_counts)
                self.run_obj.status               = 'success'
                self.run_obj.finished_at          = timezone.now()
                self.run_obj.save()

                logger.info(
                    '[LostSalesEngine] Run %d OK | pairs=%d items_affected=%d '
                    'lost_rev=%.2f lost_margin=%.2f | causes=%s',
                    self.run_obj.pk,
                    row_count,
                    items_affected,
                    float(total_lost_rev),
                    float(total_lost_margin),
                    dict(root_cause_counts),
                )

        except Exception as exc:
            self.run_obj.status        = 'failed'
            self.run_obj.finished_at   = timezone.now()
            self.run_obj.error_message = str(exc)
            self.run_obj.save()
            logger.exception('[LostSalesEngine] Run %d FAILED: %s', self.run_obj.pk, exc)
            raise

        return self.run_obj
