"""
management command: segment_customers

Computes CRM segmentation fields for all active customers:
  - ltv                   — net lifetime value (sales minus returns)
  - last_visit_date       — most recent invoice date
  - days_since_last_visit — delta from today
  - purchase_count_90d    — invoices in last 90 days
  - complaint_risk_score  — 0-100 risk score
  - segment               — vip/loyal/regular/at_risk/dormant/new/churned
  - churn_score           — 0.0-1.0 churn probability
  - churn_segment         — low/medium/high/critical

Churn scoring algorithm (multi-factor):
  Factor 1  Recency (35%): days since last purchase, decay curve
  Factor 2  Frequency trend (25%): is purchase rate dropping?
  Factor 3  Chronic miss (20%): missed refills from followups.FollowUpTask
  Factor 4  Complaint signal (15%): unresolved complaints
  Factor 5  Demand frustration (5%): unfulfilled demand requests

Also invokes CustomerHealthEngine to build/refresh CustomerHealthProfile
for all customers with purchase history (chronic condition detection).

Run daily via APScheduler (02:00 local time).
Safe to run repeatedly — fully idempotent via bulk_update.
"""
import logging
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.db.models import Sum, Count, Max, Q
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── Thresholds (tune per business) ───────────────────────────────────────────
VIP_LTV_THRESHOLD   = 5_000   # EGP net lifetime value
LOYAL_MIN_PURCHASES = 3       # min invoices in 90-day window
NEW_GRACE_DAYS      = 60      # customer considered "new" for this many days
AT_RISK_MIN_DAYS    = 90
AT_RISK_MAX_DAYS    = 180
DORMANT_MIN_DAYS    = 180
DORMANT_MAX_DAYS    = 365
CHURNED_MIN_DAYS    = 365


def _compute_segment(ltv, days, purchase_count_90d, age_days):
    """Return segment string given computed metrics."""
    if ltv is None:
        ltv = 0
    if days is None:
        # No purchase ever
        if age_days <= NEW_GRACE_DAYS:
            return 'new'
        return 'churned'

    if ltv >= VIP_LTV_THRESHOLD and days <= AT_RISK_MIN_DAYS:
        return 'vip'
    if purchase_count_90d >= LOYAL_MIN_PURCHASES and days <= AT_RISK_MIN_DAYS:
        return 'loyal'
    if days <= AT_RISK_MIN_DAYS:
        return 'regular'
    if days <= AT_RISK_MAX_DAYS:
        return 'at_risk'
    if days <= DORMANT_MAX_DAYS:
        return 'dormant'
    return 'churned'


def _compute_risk_score(complaint_count, call_count_30d, demand_unfulfilled, days):
    """
    Returns 0-100 complaint/escalation risk score.
    Higher = more likely to escalate or churn.
    """
    score = 0
    # Complaints in last 90 days
    score += min(complaint_count * 20, 40)
    # Recent call volume (high call count = frustrated)
    if call_count_30d >= 5:
        score += 20
    elif call_count_30d >= 3:
        score += 10
    # Unfulfilled demand requests
    score += min(demand_unfulfilled * 10, 20)
    # Recency risk
    if days and days > DORMANT_MIN_DAYS:
        score += 20
    elif days and days > AT_RISK_MIN_DAYS:
        score += 10
    return min(score, 100)


def _compute_churn_score(
    days: int | None,
    count_90d: int,
    count_prev_90d: int,
    missed_refills: int,
    complaint_count: int,
    demand_unfulfilled: int,
) -> tuple[float, str]:
    """
    Multi-factor churn probability score (0.0 – 1.0).
    Returns (score, churn_segment).

    Factor weights:
      Recency          35%
      Frequency drop   25%
      Chronic miss     20%
      Complaints       15%
      Demand frustr.    5%
    """
    score = 0.0

    # ── Factor 1: Recency (35%) ───────────────────────────────────────────────
    if days is None:
        recency = 0.80  # never bought = high churn risk
    elif days > 365:
        recency = 1.00
    elif days > 180:
        recency = 0.75
    elif days > 90:
        recency = 0.45
    elif days > 60:
        recency = 0.20
    else:
        recency = 0.05
    score += recency * 0.35

    # ── Factor 2: Frequency trend (25%) ──────────────────────────────────────
    if count_prev_90d > 0 and count_90d < count_prev_90d * 0.5:
        freq_drop = 0.90   # dropped by more than half → strong signal
    elif count_prev_90d > 0 and count_90d < count_prev_90d * 0.75:
        freq_drop = 0.55
    elif count_90d == 0 and count_prev_90d > 0:
        freq_drop = 0.70
    else:
        freq_drop = 0.10
    score += freq_drop * 0.25

    # ── Factor 3: Chronic missed refills (20%) ────────────────────────────────
    if missed_refills >= 3:
        chronic_signal = 0.90
    elif missed_refills == 2:
        chronic_signal = 0.65
    elif missed_refills == 1:
        chronic_signal = 0.40
    else:
        chronic_signal = 0.0
    score += chronic_signal * 0.20

    # ── Factor 4: Complaints (15%) ────────────────────────────────────────────
    complaint_signal = min(1.0, complaint_count * 0.35)
    score += complaint_signal * 0.15

    # ── Factor 5: Demand frustration (5%) ────────────────────────────────────
    demand_signal = min(1.0, demand_unfulfilled * 0.25)
    score += demand_signal * 0.05

    score = round(min(1.0, score), 4)

    if score >= 0.70:
        segment = 'critical'
    elif score >= 0.45:
        segment = 'high'
    elif score >= 0.25:
        segment = 'medium'
    else:
        segment = 'low'

    return score, segment


class Command(BaseCommand):
    help = 'Compute CRM segmentation fields for all customers (idempotent)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size', type=int, default=500,
            help='Customers per bulk_update batch (default: 500)',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Compute but do not save — prints a sample instead',
        )

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size', type=int, default=500,
            help='Customers per bulk_update batch (default: 500)',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Compute but do not save — prints a sample instead',
        )
        parser.add_argument(
            '--skip-health', action='store_true',
            help='Skip CustomerHealthProfile rebuild (faster, use for quick segment refresh)',
        )

    def handle(self, *args, **options):
        from apps.customers.models import Customer, PurchaseHistory

        batch_size  = options['batch_size']
        dry_run     = options['dry_run']
        skip_health = options['skip_health']
        today       = date.today()
        now         = timezone.now()

        self.stdout.write(f'[segment_customers] Started at {now:%Y-%m-%d %H:%M}')

        # ── 1. Net LTV per customer (sales - returns) ─────────────────────────
        sales_code  = '115'
        return_code = '30'
        cutoff_90   = today - timedelta(days=90)
        cutoff_180  = today - timedelta(days=180)

        ltv_map = {}
        for row in (
            PurchaseHistory.objects
            .filter(doc_code__in=(sales_code, return_code))
            .values('customer_id')
            .annotate(
                sales=Sum('total_amount', filter=Q(doc_code=sales_code)),
                returns=Sum('total_amount', filter=Q(doc_code=return_code)),
            )
        ):
            sales   = float(row['sales'] or 0)
            returns = float(row['returns'] or 0)
            ltv_map[row['customer_id']] = round(sales - returns, 2)

        # Last visit date
        last_visit_map = {
            row['customer_id']: row['last']
            for row in PurchaseHistory.objects
            .filter(doc_code=sales_code, invoice_date__isnull=False)
            .values('customer_id')
            .annotate(last=Max('invoice_date'))
        }

        # Purchase count: last 90d and previous 90d (for frequency trend)
        count_90d_map = {
            row['customer_id']: row['cnt']
            for row in PurchaseHistory.objects
            .filter(doc_code=sales_code, invoice_date__date__gte=cutoff_90)
            .values('customer_id').annotate(cnt=Count('id'))
        }
        count_prev_90d_map = {
            row['customer_id']: row['cnt']
            for row in PurchaseHistory.objects
            .filter(
                doc_code=sales_code,
                invoice_date__date__gte=cutoff_180,
                invoice_date__date__lt=cutoff_90,
            )
            .values('customer_id').annotate(cnt=Count('id'))
        }

        # ── 2. Complaint count (90 days) ──────────────────────────────────────
        complaint_map = {}
        try:
            from apps.callcenter.models import CustomerCase
            for row in (
                CustomerCase.objects
                .filter(category='complaint', created_at__date__gte=today - timedelta(days=90))
                .values('customer_id').annotate(cnt=Count('id'))
            ):
                complaint_map[row['customer_id']] = row['cnt']
        except Exception:
            pass

        # ── 3. Call frequency (30 days) ───────────────────────────────────────
        call_map = {}
        try:
            from apps.callcenter.models import CallLog
            for row in (
                CallLog.objects
                .filter(called_at__date__gte=today - timedelta(days=30))
                .exclude(customer__isnull=True)
                .values('customer_id').annotate(cnt=Count('id'))
            ):
                call_map[row['customer_id']] = row['cnt']
        except Exception:
            pass

        # ── 4. Unfulfilled demand requests ────────────────────────────────────
        # Phase 4: count BOTH still-open demands AND recent LOST ones. A lost
        # demand (we failed to supply) is a stronger churn signal than an open
        # one. Lost is windowed to 180d so it doesn't accumulate forever.
        demand_map = {}
        try:
            from apps.demand.models import DemandRecord
            demand_cutoff = today - timedelta(days=180)
            for row in (
                DemandRecord.objects
                .filter(
                    Q(status__in=('new', 'assigned', 'follow_up', 'stock_eta',
                                  'transfer_suggested', 'purchasing_flagged'))
                    | Q(status='lost', updated_at__date__gte=demand_cutoff)
                )
                .exclude(customer__isnull=True)
                .values('customer_id').annotate(cnt=Count('id'))
            ):
                demand_map[row['customer_id']] = row['cnt']
        except Exception:
            pass

        # ── 5. Missed chronic refills (followups.FollowUpTask) ────────────────
        missed_refills_map = {}
        try:
            from apps.followups.models import FollowUpTask
            for row in (
                FollowUpTask.objects
                .filter(status='missed')
                .exclude(customer__isnull=True)
                .values('customer_id').annotate(cnt=Count('id'))
            ):
                missed_refills_map[row['customer_id']] = row['cnt']
        except Exception:
            pass

        # ── 6. Iterate and compute all scores ─────────────────────────────────
        to_update = []
        update_fields = [
            'ltv', 'last_visit_date', 'days_since_last_visit',
            'purchase_count_90d', 'complaint_risk_score',
            'segment', 'segment_updated_at',
            'churn_score', 'churn_segment', 'churn_updated_at',
        ]

        total = changed = 0

        for customer in Customer.objects.only(
            'id', 'created_at',
            'segment', 'ltv', 'last_visit_date',
            'days_since_last_visit', 'purchase_count_90d',
            'complaint_risk_score', 'segment_updated_at',
            'churn_score', 'churn_segment', 'churn_updated_at',
        ).iterator(chunk_size=1000):

            cid        = customer.id
            ltv_val    = ltv_map.get(cid)
            last_visit = last_visit_map.get(cid)

            if last_visit:
                lv_date = last_visit.date() if hasattr(last_visit, 'date') else last_visit
                days    = (today - lv_date).days
            else:
                lv_date = None
                days    = None

            count_90d      = count_90d_map.get(cid, 0)
            count_prev_90d = count_prev_90d_map.get(cid, 0)
            age_days       = (today - customer.created_at.date()).days

            segment = _compute_segment(ltv_val, days, count_90d, age_days)

            risk = _compute_risk_score(
                complaint_count    = complaint_map.get(cid, 0),
                call_count_30d     = call_map.get(cid, 0),
                demand_unfulfilled = demand_map.get(cid, 0),
                days               = days,
            )

            churn_score, churn_segment = _compute_churn_score(
                days               = days,
                count_90d          = count_90d,
                count_prev_90d     = count_prev_90d,
                missed_refills     = missed_refills_map.get(cid, 0),
                complaint_count    = complaint_map.get(cid, 0),
                demand_unfulfilled = demand_map.get(cid, 0),
            )

            customer.ltv                   = ltv_val
            customer.last_visit_date       = lv_date
            customer.days_since_last_visit = days
            customer.purchase_count_90d    = count_90d
            customer.complaint_risk_score  = risk
            customer.segment               = segment
            customer.segment_updated_at    = now
            customer.churn_score           = churn_score
            customer.churn_segment         = churn_segment
            customer.churn_updated_at      = now

            to_update.append(customer)
            total += 1

            if len(to_update) >= batch_size:
                if not dry_run:
                    Customer.objects.bulk_update(to_update, update_fields)
                changed += len(to_update)
                to_update.clear()

        if to_update:
            if not dry_run:
                Customer.objects.bulk_update(to_update, update_fields)
            changed += len(to_update)

        suffix = ' [DRY RUN]' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'[segment_customers] Segmentation done{suffix}: {changed}/{total} customers'
        ))

        # ── 7. Build CustomerHealthProfile (disease detection) ────────────────
        if not skip_health and not dry_run:
            self.stdout.write('[segment_customers] Building health profiles…')
            try:
                from apps.customers.health_engine import CustomerHealthEngine
                result = CustomerHealthEngine.run_batch(batch_size=batch_size)
                self.stdout.write(self.style.SUCCESS(
                    f'[segment_customers] Health profiles: '
                    f'{result["processed"]} built, {result["errors"]} errors'
                ))
            except Exception as exc:
                self.stdout.write(self.style.WARNING(
                    f'[segment_customers] Health engine failed: {exc}'
                ))

        logger.info(
            'segment_customers: %d/%d customers updated%s',
            changed, total, suffix,
        )
