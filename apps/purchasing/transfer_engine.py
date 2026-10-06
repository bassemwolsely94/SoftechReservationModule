"""
apps/purchasing/transfer_engine.py

MODULE 2 — Inter-Branch Transfer Engine
========================================

Reads ItemDemandMetrics for a completed DemandCalculationRun and generates
inter-branch transfer recommendations that eliminate shortages by drawing
from branches that have stock above their safety-stock level.

ALGORITHM (per item):
  1. deficit_branches  = branches where gap > 0, sorted by priority DESC
  2. surplus_branches  = branches where current_stock > safety_stock,
                         surplus = current_stock − safety_stock, sorted DESC
  3. Greedy matching:
       For each deficit branch (highest priority first):
           remaining_need = gap
           For each surplus branch (most surplus first):
               transfer_qty = min(remaining_need, available_surplus)
               if transfer_qty ≥ 0.5: record recommendation
               deduct from available_surplus
               break when remaining_need ≤ 0

RULES:
  • Source branch NEVER drops below safety_stock
    (surplus = current_stock − safety_stock caps every draw)
  • Partial fills are allowed (one deficit branch may receive from multiple
    surplus branches; one surplus branch may feed multiple deficit branches)
  • Quantities are kept fractional — the approver rounds to physical units
  • Minimum meaningful transfer: 0.5 units (skip below this threshold)

OUTPUT:
  • TransferRecommendationRun  (1 per DemandCalculationRun)
  • TransferRecommendation     (N per run, one per matched pair)
"""

import logging
import math
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger('elrezeiky.purchasing')

_D = lambda v: Decimal(str(v)) if v is not None else Decimal('0')

MIN_TRANSFER_QTY = 0.5   # units below this are skipped (too small to bother)


class TransferEngine:
    """
    Generate inter-branch transfer recommendations from an already-completed
    DemandCalculationRun.

    Usage:
        rec_run = TransferEngine(demand_run_obj).run()

    The engine is intentionally read-only against ItemDemandMetrics — it
    only writes TransferRecommendation* rows.
    """

    def __init__(self, demand_run):
        self.demand_run = demand_run
        self.rec_run    = None   # TransferRecommendationRun (created in run())

    # ── Entry point ───────────────────────────────────────────────────────────

    def run(self):
        """
        Execute the full matching pipeline.
        Returns the TransferRecommendationRun object.
        """
        from .models import (
            TransferRecommendationRun,
            TransferRecommendation,
            ItemDemandMetrics,
        )
        import time
        t0 = time.monotonic()

        # Create the run record
        self.rec_run = TransferRecommendationRun.objects.create(
            demand_run=self.demand_run,
            status='running',
        )
        logger.info(
            '[TransferEngine] Run %d started for DemandRun %d',
            self.rec_run.pk, self.demand_run.pk,
        )

        try:
            # ── 1. Load all metrics for this demand run ───────────────────────
            metrics_qs = (
                ItemDemandMetrics.objects
                .filter(run=self.demand_run)
                .select_related('item', 'branch')
                .only(
                    'item_id', 'branch_id', 'item__name', 'item__softech_id',
                    'branch__name', 'branch__name_ar',
                    'current_stock', 'safety_stock', 'gap', 'priority',
                    'monthly_avg', 'pack_price', 'abc_class',
                )
            )

            # ── 2. Group by item ──────────────────────────────────────────────
            by_item = defaultdict(list)
            for m in metrics_qs:
                by_item[m.item_id].append(m)

            logger.info(
                '[TransferEngine] Loaded %d metrics across %d items',
                metrics_qs.count(), len(by_item),
            )

            # ── 3. Match deficit ↔ surplus per item ───────────────────────────
            recommendations = self._match_all(by_item)

            # ── 4. Bulk persist ───────────────────────────────────────────────
            BATCH = 500
            total_recs = 0
            for i in range(0, len(recommendations), BATCH):
                chunk = recommendations[i:i + BATCH]
                TransferRecommendation.objects.bulk_create(
                    chunk,
                    update_conflicts=True,
                    unique_fields=['run', 'item', 'from_branch', 'to_branch'],
                    update_fields=[
                        'quantity', 'pack_price', 'estimated_value',
                        'priority_score',
                        'from_stock', 'from_safety', 'from_surplus', 'from_monthly_avg',
                        'to_stock', 'to_gap', 'to_monthly_avg', 'to_priority',
                        'abc_class',
                    ],
                )
                total_recs += len(chunk)

            items_covered = len({r.item_id for r in recommendations})
            total_value   = sum(float(r.estimated_value) for r in recommendations)

            elapsed = time.monotonic() - t0
            self.rec_run.status               = 'success'
            self.rec_run.finished_at          = timezone.now()
            self.rec_run.total_recommendations = total_recs
            self.rec_run.total_items_covered   = items_covered
            self.rec_run.total_transfer_value  = _D(total_value)
            self.rec_run.save()

            logger.info(
                '[TransferEngine] Run %d OK | %d recommendations | %d items | value=%.0f | %.1fs',
                self.rec_run.pk, total_recs, items_covered, total_value, elapsed,
            )

        except Exception as exc:
            elapsed = time.monotonic() - t0
            self.rec_run.status        = 'failed'
            self.rec_run.finished_at   = timezone.now()
            self.rec_run.error_message = str(exc)
            self.rec_run.save()
            logger.exception(
                '[TransferEngine] Run %d FAILED (%.1fs): %s',
                self.rec_run.pk, elapsed, exc,
            )
            raise

        return self.rec_run

    # ── Core matching logic ───────────────────────────────────────────────────

    def _match_all(self, by_item: dict) -> list:
        """
        Iterate over all items and generate TransferRecommendation objects.
        Returns a flat list (not yet persisted).
        """
        from .models import TransferRecommendation

        all_recs = []

        for item_id, branch_metrics in by_item.items():
            # Split into deficit and surplus buckets
            deficit_list = []   # [(metric, gap_float)]
            surplus_list = []   # [(metric, surplus_float)]

            for m in branch_metrics:
                gap     = float(m.gap)
                stock   = float(m.current_stock)
                safety  = float(m.safety_stock)
                surplus = stock - safety

                if gap > 0:
                    deficit_list.append((m, gap))
                if surplus > 0:
                    surplus_list.append((m, surplus))

            # Nothing to match for this item
            if not deficit_list or not surplus_list:
                continue

            # Sort: deficit by priority DESC, surplus by surplus DESC
            deficit_list.sort(key=lambda x: float(x[0].priority), reverse=True)
            surplus_list.sort(key=lambda x: x[1],                  reverse=True)

            # Mutable available pool: {branch_id → remaining_surplus}
            available = {m.branch_id: s for m, s in surplus_list}

            # Build a fast-lookup dict: branch_id → surplus_metric
            # so we avoid repeated list scans for pack_price / stock snapshot
            surplus_meta = {m.branch_id: m for m, _ in surplus_list}

            for deficit_metric, gap in deficit_list:
                remaining_need = gap
                dst_branch_id  = deficit_metric.branch_id

                # Rebuild active surplus list sorted by current available DESC.
                # Only includes branches that still have meaningful stock and
                # are not the destination branch.  Rebuilding each time ensures
                # we always draw from the richest source even after deductions.
                active_surplus = sorted(
                    (
                        (bid, avail)
                        for bid, avail in available.items()
                        if bid != dst_branch_id and avail >= MIN_TRANSFER_QTY
                    ),
                    key=lambda x: x[1],
                    reverse=True,
                )

                if not active_surplus:
                    continue   # no usable source for this deficit branch

                for src_branch_id, avail in active_surplus:
                    transfer_qty = min(remaining_need, avail)

                    # Skip negligibly small transfers
                    if transfer_qty < MIN_TRANSFER_QTY:
                        continue

                    surplus_metric  = surplus_meta[src_branch_id]
                    pack_price      = float(surplus_metric.pack_price)
                    estimated_value = transfer_qty * pack_price

                    all_recs.append(TransferRecommendation(
                        run              = self.rec_run,
                        item_id          = item_id,
                        from_branch_id   = src_branch_id,
                        to_branch_id     = dst_branch_id,
                        quantity         = _D(transfer_qty),
                        pack_price       = _D(pack_price),
                        estimated_value  = _D(estimated_value),
                        priority_score   = float(deficit_metric.priority),
                        # Source-branch snapshot
                        from_stock       = _D(float(surplus_metric.current_stock)),
                        from_safety      = _D(float(surplus_metric.safety_stock)),
                        from_surplus     = _D(avail),
                        from_monthly_avg = _D(float(surplus_metric.monthly_avg)),
                        # Destination-branch snapshot
                        to_stock         = _D(float(deficit_metric.current_stock)),
                        to_gap           = _D(gap),
                        to_monthly_avg   = _D(float(deficit_metric.monthly_avg)),
                        to_priority      = float(deficit_metric.priority),
                        abc_class        = deficit_metric.abc_class,
                    ))

                    available[src_branch_id] -= transfer_qty
                    remaining_need           -= transfer_qty

                    if remaining_need <= MIN_TRANSFER_QTY:
                        break  # deficit fully covered (or residual < threshold)

        logger.info(
            '[TransferEngine] Matching complete: %d recommendations for %d items',
            len(all_recs), len({r.item_id for r in all_recs}),
        )
        return all_recs
