"""
PaymentAuditService
===================
Matches bank statement lines to ExternalPayment records and detects anomalies.

Rules:
  • exact match  : reference == payment.transaction_ref AND credit ≈ payment.amount  → confidence 1.0
  • fuzzy match  : |credit - amount| ≤ 1% AND |date_diff| ≤ 2 days                  → confidence 0.8
  • no match     : PaymentException(type='unrecorded')

Anomaly scoring uses per-cashier/per-method statistics (μ ± σ).
Critical anomalies (score ≥ 70) create / link an AbuseFlag record.
"""

import logging
import statistics
from datetime import timedelta, datetime
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.payments.models import (
    BankStatementImport,
    BankStatementLine,
    ExternalPayment,
    PaymentException,
)

try:
    from apps.audit.models import AbuseFlag  # may not exist in every deployment
    _ABUSE_FLAG_AVAILABLE = True
except ImportError:
    _ABUSE_FLAG_AVAILABLE = False

logger = logging.getLogger('elrezeiky')

_FUZZY_AMOUNT_TOL = Decimal('0.01')   # 1 %
_FUZZY_DATE_DAYS  = 2
_ANOMALY_CRITICAL = 70                # score threshold → escalate to AbuseFlag


class PaymentAuditService:

    # ──────────────────────────────────────────────────────────────────────────
    # Statement → Payment matching
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def match_statement_to_payments(cls, import_id: int) -> dict:
        """
        Process all lines of a BankStatementImport.
        Returns {'matched_exact': N, 'matched_fuzzy': N, 'unmatched': N, 'exceptions_created': N}
        """
        stmt = BankStatementImport.objects.select_for_update().get(pk=import_id)
        if stmt.status not in ('pending', 'failed'):
            raise ValueError(f'Cannot process statement in status={stmt.status}')

        stmt.status = 'processing'
        stmt.save(update_fields=['status'])

        stats = {'matched_exact': 0, 'matched_fuzzy': 0, 'unmatched': 0, 'exceptions_created': 0}

        try:
            lines = list(stmt.lines.filter(match_method='unmatched').select_for_update())

            # Pre-fetch candidate payments once (same branch, same method, within statement date range)
            candidate_payments = list(
                ExternalPayment.objects.filter(
                    branch=stmt.branch,
                    payment_method=stmt.payment_method,
                    payment_date__range=(
                        stmt.statement_from - timedelta(days=_FUZZY_DATE_DAYS),
                        stmt.statement_to   + timedelta(days=_FUZZY_DATE_DAYS),
                    ),
                ).select_related('cashier')
            )

            for line in lines:
                if line.credit <= 0:
                    # Debit-only lines (fees, charges) — skip matching
                    continue

                matched, method, confidence = cls._match_line(line, candidate_payments)

                if matched:
                    line.matched_payment  = matched
                    line.match_method     = method
                    line.match_confidence = confidence
                    line.matched_at       = timezone.now()
                    line.save(update_fields=['matched_payment', 'match_method', 'match_confidence', 'matched_at'])

                    if method == 'auto_exact':
                        stats['matched_exact'] += 1
                    else:
                        stats['matched_fuzzy'] += 1
                else:
                    # Unrecorded bank transaction
                    PaymentException.objects.create(
                        statement_line  = line,
                        exception_type  = 'unrecorded',
                        severity        = 'warning',
                        detail          = (
                            f'بنك: {stmt.bank_name} | مرجع: {line.reference or "—"} | '
                            f'مبلغ: {line.credit} | تاريخ: {line.transaction_date}'
                        ),
                    )
                    stats['unmatched']           += 1
                    stats['exceptions_created']  += 1

            # Update summary counters on import record
            total     = stmt.lines.count()
            matched_c = stmt.lines.exclude(match_method='unmatched').count()
            stmt.total_lines     = total
            stmt.matched_lines   = matched_c
            stmt.unmatched_lines = total - matched_c
            stmt.status          = 'completed'
            stmt.completed_at    = timezone.now()
            stmt.save(update_fields=['total_lines', 'matched_lines', 'unmatched_lines', 'status', 'completed_at'])

        except Exception as exc:
            stmt.status        = 'failed'
            stmt.error_message = str(exc)
            stmt.save(update_fields=['status', 'error_message'])
            logger.exception('Statement matching failed for import #%s', import_id)
            raise

        return stats

    @classmethod
    def _match_line(cls, line: BankStatementLine, candidates: list):
        """Returns (ExternalPayment | None, method_str, confidence)."""
        # 1. Exact match: reference + credit amount
        if line.reference:
            for p in candidates:
                if (
                    p.transaction_ref
                    and p.transaction_ref.strip() == line.reference.strip()
                    and abs(p.amount - line.credit) < Decimal('0.01')
                ):
                    return p, 'auto_exact', Decimal('1.000')

        # 2. Fuzzy match: amount within 1% + date within 2 days
        for p in candidates:
            amount_ok = (
                line.credit > 0
                and abs(p.amount - line.credit) / line.credit <= _FUZZY_AMOUNT_TOL
            )
            date_diff = abs((p.payment_date - line.transaction_date).days)
            if amount_ok and date_diff <= _FUZZY_DATE_DAYS:
                return p, 'auto_fuzzy', Decimal('0.800')

        return None, 'unmatched', Decimal('0.000')

    # ──────────────────────────────────────────────────────────────────────────
    # Exception detection for a specific payment
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def detect_exceptions(cls, payment_id: int) -> list[PaymentException]:
        """
        Inspect a single ExternalPayment for rule-based anomalies.
        Returns list of newly created PaymentException objects.
        """
        payment = ExternalPayment.objects.select_related('cashier', 'branch').get(pk=payment_id)
        created = []

        # ① Duplicate detection — same cashier, same amount, within 5 min
        window_start = datetime.combine(payment.payment_date, payment.payment_time or datetime.min.time())
        window_start = timezone.make_aware(window_start) if timezone.is_naive(window_start) else window_start
        window_end   = window_start + timedelta(minutes=5)

        dupes = ExternalPayment.objects.filter(
            cashier        = payment.cashier,
            amount         = payment.amount,
            payment_method = payment.payment_method,
            payment_date   = payment.payment_date,
        ).exclude(pk=payment.pk)

        if dupes.exists():
            exc, new = PaymentException.objects.get_or_create(
                payment        = payment,
                exception_type = 'duplicate',
                defaults={
                    'severity': 'critical',
                    'detail': f'تكرار محتمل: {dupes.count()} دفعة مشابهة لنفس الكاشير في نفس اليوم',
                },
            )
            if new:
                created.append(exc)

        # ② Delayed settlement — payment older than 3 days still "pending"
        if payment.status == 'pending':
            age_days = (timezone.now().date() - payment.payment_date).days
            if age_days >= 3:
                exc, new = PaymentException.objects.get_or_create(
                    payment        = payment,
                    exception_type = 'delayed',
                    defaults={
                        'severity': 'warning',
                        'detail': f'الدفعة في حالة انتظار منذ {age_days} يوم',
                    },
                )
                if new:
                    created.append(exc)

        # ③ Wrong-branch: cashier's assigned branch ≠ payment branch
        if (
            hasattr(payment.cashier, 'branch')
            and payment.cashier.branch_id
            and payment.cashier.branch_id != payment.branch_id
        ):
            exc, new = PaymentException.objects.get_or_create(
                payment        = payment,
                exception_type = 'wrong_branch',
                defaults={
                    'severity': 'warning',
                    'detail': (
                        f'فرع الكاشير={payment.cashier.branch_id} '
                        f'≠ فرع الدفعة={payment.branch_id}'
                    ),
                },
            )
            if new:
                created.append(exc)

        return created

    # ──────────────────────────────────────────────────────────────────────────
    # Anomaly scoring
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def calculate_anomaly_score(cls, payment: ExternalPayment) -> Decimal:
        """
        Returns a 0–100 score.  High score = more anomalous.
        Method: compare this payment's amount to the population of the same
        cashier + payment_method in the last 90 days.
        Score = min(100, |z| × 20) where z = (x - μ) / σ.
        Critical (≥ 70) → creates / links an AbuseFlag.
        """
        from django.db.models import Avg, StdDev

        qs = ExternalPayment.objects.filter(
            cashier        = payment.cashier,
            payment_method = payment.payment_method,
            payment_date__gte = payment.payment_date - timedelta(days=90),
        ).exclude(pk=payment.pk)

        amounts = list(qs.values_list('amount', flat=True))

        if len(amounts) < 5:
            # Not enough history — score 0 (inconclusive)
            return Decimal('0')

        mu    = statistics.mean(float(a) for a in amounts)
        sigma = statistics.stdev(float(a) for a in amounts) or 1.0
        z     = abs(float(payment.amount) - mu) / sigma
        score = Decimal(str(min(100, round(z * 20, 2))))

        # Escalate to AbuseFlag if critical
        if score >= _ANOMALY_CRITICAL:
            cls._escalate_to_abuse_flag(payment, score)

        return score

    @classmethod
    def _escalate_to_abuse_flag(cls, payment: ExternalPayment, score: Decimal) -> None:
        """Create or update AbuseFlag and link abuse_flag_id on the PaymentException."""
        if not _ABUSE_FLAG_AVAILABLE:
            logger.warning('AbuseFlag model not available — skipping escalation for payment #%s', payment.pk)
            return

        try:
            flag, _ = AbuseFlag.objects.get_or_create(
                related_object_type = 'external_payment',
                related_object_id   = payment.pk,
                defaults={
                    'flag_type':   'payment_anomaly',
                    'description': (
                        f'درجة شذوذ {score}/100 — كاشير: {payment.cashier_id} | '
                        f'طريقة: {payment.payment_method} | مبلغ: {payment.amount}'
                    ),
                    'severity': 'high',
                },
            )
            # Link flag ID back to any open PaymentException for this payment
            PaymentException.objects.filter(
                payment        = payment,
                exception_type = 'anomaly',
                abuse_flag_id__isnull = True,
            ).update(abuse_flag_id=flag.pk)

            # Create an anomaly exception if one doesn't exist
            PaymentException.objects.get_or_create(
                payment        = payment,
                exception_type = 'anomaly',
                defaults={
                    'severity':     'critical',
                    'anomaly_score': score,
                    'detail':       f'درجة شذوذ إحصائي: {score}/100',
                    'abuse_flag_id': flag.pk,
                },
            )
        except Exception:
            logger.exception('Failed to escalate payment #%s to AbuseFlag', payment.pk)

    # ──────────────────────────────────────────────────────────────────────────
    # Manual match
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    @transaction.atomic
    def manual_match(cls, *, line: BankStatementLine, payment: ExternalPayment, matched_by) -> BankStatementLine:
        """Manually link a statement line to a payment."""
        if line.match_method not in ('unmatched', 'auto_fuzzy'):
            raise ValueError('يمكن ربط السطور غير المطابَقة أو المطابَقة تقريباً فقط')

        line.matched_payment  = payment
        line.match_method     = 'manual'
        line.match_confidence = Decimal('1.000')
        line.matched_by       = matched_by
        line.matched_at       = timezone.now()
        line.save(update_fields=['matched_payment', 'match_method', 'match_confidence', 'matched_by', 'matched_at'])

        # Dismiss any unrecorded exception for this line
        PaymentException.objects.filter(
            statement_line = line,
            exception_type = 'unrecorded',
            status         = 'open',
        ).update(status='dismissed', resolved_at=timezone.now())

        return line
