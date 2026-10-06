"""
ForecastService
===============
Computes per-item, per-branch demand forecasts and writes results into
ItemDemandMetrics (purchasing app). Never duplicates fields — always extends.

Algorithm (per item × branch):
  base_demand = monthly_avg × seasonal_index × (1 + yoy_growth_rate)
  forecast_30d = base_demand
  forecast_90d = base_demand × 3

Confidence score (0–1) weighted sum of:
  • data window (≥24 months data → +0.4)
  • availability_rate_30d (>95% → +0.3)
  • ABC class (A → +0.3, B → +0.2, C → +0.1)

Demand pattern classification:
  rate_30d / rate_365d > 1.15  → trend_up
  rate_30d / rate_365d < 0.85  → trend_down
  coefficient_of_variation > 1  → spike
  else                          → stable

Stockout date:
  current_stock / daily_demand  (days from today)
"""

import logging
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger('elrezeiky')

_TREND_UP_RATIO   = Decimal('1.15')
_TREND_DOWN_RATIO = Decimal('0.85')
_CV_SPIKE_THRESH  = Decimal('1.00')


class ForecastService:

    @classmethod
    def run_forecast(cls, *, triggered_by=None, branch_ids=None, item_ids=None) -> dict:
        """
        Full forecast run. Writes into ItemDemandMetrics.
        Returns {'items_processed': N, 'run_id': pk}
        """
        from apps.forecasting.models import ForecastRun
        from apps.purchasing.models import ItemDemandMetrics

        run = ForecastRun.objects.create(
            triggered_by = triggered_by,
            parameters   = {
                'branch_ids': branch_ids,
                'item_ids':   item_ids,
            },
        )

        qs = ItemDemandMetrics.objects.select_related('item', 'branch')
        if branch_ids:
            qs = qs.filter(branch_id__in=branch_ids)
        if item_ids:
            qs = qs.filter(item_id__in=item_ids)

        processed = 0
        errors    = 0

        for metrics in qs.iterator(chunk_size=500):
            try:
                cls._forecast_one(metrics)
                processed += 1
            except Exception:
                logger.exception('Forecast failed for item=%s branch=%s', metrics.item_id, metrics.branch_id)
                errors += 1

        run.status          = 'completed' if not errors else 'failed'
        run.completed_at    = timezone.now()
        run.items_processed = processed
        if errors:
            run.error = f'{errors} items failed — see server logs'
        run.save(update_fields=['status', 'completed_at', 'items_processed', 'error'])

        return {'items_processed': processed, 'errors': errors, 'run_id': run.pk}

    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def _forecast_one(cls, metrics) -> None:
        """Compute and write forecast fields for a single ItemDemandMetrics row."""
        seasonal_index = cls._get_seasonal_index(metrics.item_id, metrics.branch_id)
        yoy            = cls._yoy_growth_rate(metrics)
        monthly_avg    = cls._monthly_avg(metrics)
        confidence     = cls._confidence(metrics)
        pattern        = cls._demand_pattern(metrics)
        stockout_date  = cls._stockout_date(metrics)
        expiry_risk    = cls._expiry_risk(metrics)

        base_30 = monthly_avg * seasonal_index * (Decimal('1') + yoy)
        base_90 = base_30 * Decimal('3')

        metrics.seasonal_index             = seasonal_index
        metrics.yoy_growth_rate            = yoy
        metrics.forecast_next_30d          = base_30.quantize(Decimal('0.01'), ROUND_HALF_UP)
        metrics.forecast_next_90d          = base_90.quantize(Decimal('0.01'), ROUND_HALF_UP)
        metrics.forecast_confidence        = confidence.quantize(Decimal('0.0001'), ROUND_HALF_UP)
        metrics.demand_pattern             = pattern
        metrics.expected_stockout_date     = stockout_date
        metrics.expected_expiry_risk_value = expiry_risk

        metrics.save(update_fields=[
            'seasonal_index', 'yoy_growth_rate',
            'forecast_next_30d', 'forecast_next_90d', 'forecast_confidence',
            'demand_pattern', 'expected_stockout_date', 'expected_expiry_risk_value',
        ])

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def _get_seasonal_index(cls, item_id, branch_id) -> Decimal:
        """
        Lookup SeasonalityIndex for current month.
        Priority: item-specific > category-level > global (item=None, category=None).
        Falls back to 1.0 if none found.
        """
        from apps.forecasting.models import SeasonalityIndex

        month = date.today().month

        # Item-specific
        si = SeasonalityIndex.objects.filter(item_id=item_id, month=month).first()
        if si:
            return si.index_value

        # Category-level — requires item → category FK
        try:
            from apps.catalog.models import Item
            item = Item.objects.only('category_id').get(pk=item_id)
            si = SeasonalityIndex.objects.filter(category_id=item.category_id, item__isnull=True, month=month).first()
            if si:
                return si.index_value
        except Exception:
            pass

        # Global
        si = SeasonalityIndex.objects.filter(item__isnull=True, category__isnull=True, month=month).first()
        return si.index_value if si else Decimal('1.0000')

    @classmethod
    def _monthly_avg(cls, metrics) -> Decimal:
        """
        Use rate_30d (daily demand) × 30 as the monthly baseline.
        Falls back to rate_365d × 30 if rate_30d is zero.
        """
        r30  = getattr(metrics, 'rate_30d',  None) or Decimal('0')
        r365 = getattr(metrics, 'rate_365d', None) or Decimal('0')
        daily = r30 if r30 > 0 else r365
        return (daily * Decimal('30')).quantize(Decimal('0.01'), ROUND_HALF_UP)

    @classmethod
    def _yoy_growth_rate(cls, metrics) -> Decimal:
        """
        YoY = (rate_365d - prev_year_rate) / prev_year_rate.
        ItemDemandMetrics does not store prev_year_rate natively so we return 0
        unless the field was pre-populated externally.
        """
        stored = getattr(metrics, 'yoy_growth_rate', None)
        if stored is not None:
            return stored
        return Decimal('0.0000')

    @classmethod
    def _confidence(cls, metrics) -> Decimal:
        """0–1 confidence score."""
        score = Decimal('0')

        # Data window proxy: use months_of_data if available, else rate_365d > 0
        has_annual = bool(getattr(metrics, 'rate_365d', None))
        score += Decimal('0.4') if has_annual else Decimal('0.2')

        avail = getattr(metrics, 'availability_rate_30d', None) or Decimal('0')
        if avail >= Decimal('95'):
            score += Decimal('0.3')
        elif avail >= Decimal('80'):
            score += Decimal('0.15')

        abc = getattr(metrics, 'abc_class', '') or ''
        abc_bonus = {'A': Decimal('0.3'), 'B': Decimal('0.2'), 'C': Decimal('0.1')}.get(abc.upper(), Decimal('0.1'))
        score += abc_bonus

        return min(score, Decimal('1.0000'))

    @classmethod
    def _demand_pattern(cls, metrics) -> str:
        r30  = getattr(metrics, 'rate_30d',  None) or Decimal('0')
        r365 = getattr(metrics, 'rate_365d', None) or Decimal('0')

        if not r365:
            return 'stable'

        ratio = r30 / r365

        # Spike: high coefficient of variation — use std_dev / mean if available
        cv = getattr(metrics, 'coefficient_of_variation', None)
        if cv and Decimal(str(cv)) > _CV_SPIKE_THRESH:
            return 'spike'

        if ratio >= _TREND_UP_RATIO:
            return 'trend_up'
        if ratio <= _TREND_DOWN_RATIO:
            return 'trend_down'
        return 'stable'

    @classmethod
    def _stockout_date(cls, metrics) -> date | None:
        current_stock = getattr(metrics, 'current_stock', None) or Decimal('0')
        r30           = getattr(metrics, 'rate_30d',  None) or Decimal('0')
        r365          = getattr(metrics, 'rate_365d', None) or Decimal('0')
        daily         = r30 if r30 > 0 else r365

        if not daily or current_stock <= 0:
            return None

        days_left = float(current_stock) / float(daily)
        return date.today() + timedelta(days=int(days_left))

    @classmethod
    def _expiry_risk(cls, metrics) -> Decimal | None:
        """
        Value of stock that will expire before it can be sold.
        Requires BatchService — graceful fallback if unavailable.
        """
        try:
            from apps.batches.service import BatchService
            from apps.batches.models import StockBatch
            from django.db.models import F

            today    = date.today()
            r30      = getattr(metrics, 'rate_30d',  None) or Decimal('0')
            r365     = getattr(metrics, 'rate_365d', None) or Decimal('0')
            daily    = r30 if r30 > 0 else r365

            at_risk_value = Decimal('0')
            batches = StockBatch.objects.filter(
                item_id   = metrics.item_id,
                branch_id = metrics.branch_id,
                is_active = True,
                expiry_date__isnull = False,
                expiry_date__lte    = today + timedelta(days=90),
            )
            for batch in batches:
                days_left = (batch.expiry_date - today).days
                sellable  = float(daily) * days_left if daily else 0
                will_expire = max(0, float(batch.current_qty) - sellable)
                unit_cost   = float(getattr(metrics.item, 'cost_price', 0) or 0)
                at_risk_value += Decimal(str(will_expire * unit_cost))

            return at_risk_value.quantize(Decimal('0.01'), ROUND_HALF_UP)
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Seasonality index computation
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def compute_all_seasonality(cls, years: int = 2, min_months: int = 6,
                                floor: float = 0.25) -> dict:
        """
        Efficient BATCH seasonality: one SQL over all items, then bulk-upsert
        per-item SeasonalityIndex rows. Only items with sales in >= min_months
        distinct months get indices (sparse items stay unseasonal = 1.0 in the
        consumer). Indices are floored so a zero-sales month doesn't zero the
        forecast. Returns {items, rows}.
        """
        from decimal import Decimal
        from django.db import connection
        from apps.forecasting.models import SeasonalityIndex

        cutoff = date.today() - timedelta(days=years * 365)
        with connection.cursor() as cur:
            cur.execute("""
                SELECT item_id, EXTRACT(MONTH FROM doc_date)::int AS m, SUM(net_qty) AS total
                FROM purchasing_salestransactionline
                WHERE item_id IS NOT NULL AND doccode = '115' AND doc_date >= %s
                GROUP BY item_id, EXTRACT(MONTH FROM doc_date)
            """, [cutoff])
            rows = cur.fetchall()

        per_item = {}
        for item_id, m, total in rows:
            per_item.setdefault(item_id, {})[int(m)] = float(total or 0)

        objs = []
        for item_id, months in per_item.items():
            active = [mm for mm, v in months.items() if v > 0]
            if len(active) < min_months:
                continue
            avg = sum(months.values()) / 12.0
            if avg <= 0:
                continue
            for mm in range(1, 13):
                idx = max(floor, months.get(mm, 0.0) / avg)
                objs.append(SeasonalityIndex(
                    item_id=item_id, category=None, month=mm,
                    index_value=Decimal(str(round(idx, 4))), computed_from_years=years,
                ))

        # Full recompute of per-item indices.
        SeasonalityIndex.objects.filter(item__isnull=False, category__isnull=True).delete()
        SeasonalityIndex.objects.bulk_create(objs, batch_size=2000)
        return {'items': len({o.item_id for o in objs}), 'rows': len(objs)}

    @classmethod
    def compute_seasonality_indices(cls, item_id: int, years: int = 2) -> list:
        """
        Compute per-month seasonal indices from historical SalesTransactionLine data.
        Writes / updates SeasonalityIndex rows.
        Returns list of (month, index_value) tuples.
        """
        from apps.purchasing.models import SalesTransactionLine
        from apps.forecasting.models import SeasonalityIndex
        from django.db.models import Sum
        from django.db.models.functions import ExtractMonth

        cutoff = date.today() - timedelta(days=years * 365)

        monthly_totals = (
            SalesTransactionLine.objects
            .filter(item_id=item_id, doc_date__gte=cutoff, doccode='115')
            .annotate(month=ExtractMonth('doc_date'))
            .values('month')
            .annotate(total=Sum('net_qty'))
            .order_by('month')
        )

        totals = {row['month']: Decimal(str(row['total'] or 0)) for row in monthly_totals}
        if not totals:
            return []

        grand_avg = sum(totals.values()) / Decimal('12')
        if not grand_avg:
            return []

        results = []
        for month in range(1, 13):
            month_total = totals.get(month, Decimal('0'))
            idx_value   = (month_total / grand_avg).quantize(Decimal('0.0001'), ROUND_HALF_UP)

            SeasonalityIndex.objects.update_or_create(
                item=None if not item_id else _item_stub(item_id),
                category=None,
                month=month,
                defaults={
                    'index_value':          idx_value,
                    'computed_from_years':  years,
                },
            )
            results.append((month, idx_value))

        return results


def _item_stub(item_id):
    """Return a minimal Item proxy to avoid a DB hit inside update_or_create."""
    from apps.catalog.models import Item
    return Item(pk=item_id)
