"""
PaymentAuditService
===================
Matches bank statement lines to ExternalPayment records and detects anomalies.

Rules:
  • exact match  : reference == payment.reference_number AND credit ≈ payment.amount  → confidence 1.0
  • fuzzy match  : |credit - amount| ≤ 1% AND |date_diff| ≤ 2 days                  → confidence 0.8
  • no match     : PaymentException(type='unrecorded')

Anomaly scoring uses per-recorder (created_by) / per-method statistics (μ ± σ).
Critical anomalies (score ≥ 70) create / link an AbuseFlag record.
"""

import logging
import statistics
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.payments.models import (
    BankStatementImport,
    BankStatementLine,
    ExternalPayment,
    PaymentException,
)

from apps.audit.models import AbuseFlag
from core.branch_scope import sees_all_branches

logger = logging.getLogger('elrezeiky')

_FUZZY_AMOUNT_TOL = Decimal('0.01')   # 1 %
_FUZZY_DATE_DAYS  = 2
_ANOMALY_CRITICAL = 70                # score threshold → escalate to AbuseFlag
_ANOMALY_MIN_SAMPLES = 5               # fewer samples → score 0 (inconclusive)
_ANOMALY_WINDOW_DAYS = 90              # population window


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
                    method=stmt.payment_method,
                    payment_date__range=(
                        stmt.statement_from - timedelta(days=_FUZZY_DATE_DAYS),
                        stmt.statement_to   + timedelta(days=_FUZZY_DATE_DAYS),
                    ),
                )
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
                    p.reference_number
                    and p.reference_number.strip() == line.reference.strip()
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
    # (run nightly by `run_payment_exception_checks` when the setting
    #  payments.exception_checks_enabled is on). These checks only create
    #  PaymentException / AbuseFlag rows — never change a payment, a match or SOFTECH.
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _creator_profile(payment: ExternalPayment):
        """The StaffProfile of the user who recorded the payment, or None."""
        user = payment.created_by
        return getattr(user, 'staff_profile', None) if user is not None else None

    @classmethod
    def _record(cls, created: list, payment, exception_type, severity, detail) -> None:
        exc, new = PaymentException.objects.get_or_create(
            payment=payment, exception_type=exception_type,
            defaults={'severity': severity, 'detail': detail},
        )
        if new:
            created.append(exc)

    @classmethod
    def detect_exceptions(cls, payment_id: int) -> list[PaymentException]:
        """
        Inspect a single ExternalPayment for rule-based anomalies.
        Returns the newly created PaymentException objects (at most one per payment + type,
        so a rerun creates nothing new).
        """
        payment = ExternalPayment.objects.select_related(
            'created_by__staff_profile__branch', 'branch',
        ).get(pk=payment_id)
        created = []

        # ① Duplicate — same recorder, amount, method and day. The payment time is not stored,
        #    so the window is the whole payment day.
        if payment.created_by_id is not None:
            n = (ExternalPayment.objects.filter(
                    created_by_id = payment.created_by_id,
                    amount        = payment.amount,
                    method        = payment.method,
                    payment_date  = payment.payment_date,
                 ).exclude(pk=payment.pk).exclude(status=ExternalPayment.STATUS_CANCELLED).count())
            if n:
                cls._record(
                    created, payment, PaymentException.TYPE_DUPLICATE, PaymentException.SEVERITY_CRITICAL,
                    f'تكرار محتمل: {n} دفعة أخرى بنفس المبلغ وطريقة الدفع سجّلها نفس المستخدم '
                    f'في نفس اليوم ({payment.payment_date}) — وقت الدفع غير مسجّل، فالمقارنة باليوم كله',
                )

        # ② Delayed settlement — payment older than 3 days still "pending"
        if payment.status == ExternalPayment.STATUS_PENDING:
            age_days = (timezone.localdate() - payment.payment_date).days
            if age_days >= 3:
                cls._record(
                    created, payment, PaymentException.TYPE_DELAYED, PaymentException.SEVERITY_WARNING,
                    f'الدفعة في حالة انتظار منذ {age_days} يوم',
                )

        # ③ Wrong branch — the recorder's home branch ≠ the payment branch. All-branch users
        #    (call center, HQ roles, access_all_branches) legitimately record for any branch.
        profile = cls._creator_profile(payment)
        if (
            profile is not None
            and profile.branch_id
            and not sees_all_branches(profile)
            and profile.branch_id != payment.branch_id
        ):
            cls._record(
                created, payment, PaymentException.TYPE_WRONG_BRANCH, PaymentException.SEVERITY_WARNING,
                f'فرع المستخدم: {profile.branch} ≠ فرع الدفعة: {payment.branch}',
            )

        return created

    # ──────────────────────────────────────────────────────────────────────────
    # Anomaly scoring
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def _anomaly_stats(cls, payment: ExternalPayment):
        """(score, mean, stdev, samples) against the same recorder + method, last 90 days."""
        if payment.created_by_id is None:
            return Decimal('0'), None, None, 0
        amounts = list(
            ExternalPayment.objects.filter(
                created_by_id     = payment.created_by_id,
                method            = payment.method,
                payment_date__gte = payment.payment_date - timedelta(days=_ANOMALY_WINDOW_DAYS),
            ).exclude(pk=payment.pk).exclude(status=ExternalPayment.STATUS_CANCELLED)
            .values_list('amount', flat=True)
        )
        if len(amounts) < _ANOMALY_MIN_SAMPLES:
            return Decimal('0'), None, None, len(amounts)   # not enough history — inconclusive
        mu    = statistics.mean(float(a) for a in amounts)
        sigma = statistics.stdev(float(a) for a in amounts) or 1.0
        z     = abs(float(payment.amount) - mu) / sigma
        score = Decimal(str(min(100, round(z * 20, 2))))
        return score, mu, sigma, len(amounts)

    @classmethod
    def calculate_anomaly_score(cls, payment: ExternalPayment) -> Decimal:
        """
        Returns a 0–100 score.  High score = more anomalous.
        Method: compare this payment's amount to the population of the same
        recorder (created_by) + method in the last 90 days, cancelled payments excluded.
        Score = min(100, |z| × 20) where z = (x - μ) / σ; fewer than 5 samples → 0;
        no recorder → 0. Critical (≥ 70) → an 'anomaly' PaymentException + an AbuseFlag.
        """
        score, mu, sigma, samples = cls._anomaly_stats(payment)
        if score >= _ANOMALY_CRITICAL:
            cls._escalate_to_abuse_flag(payment, score, mean=mu, stdev=sigma, samples=samples)
        return score

    @classmethod
    def _escalate_to_abuse_flag(cls, payment: ExternalPayment, score: Decimal, *,
                                mean=None, stdev=None, samples=0) -> None:
        """Record the 'anomaly' PaymentException and raise ONE payment_anomaly AbuseFlag on the
        recorder for review (none when the recorder has no staff profile), linked back through
        abuse_flag_id. A flag already raised for this payment (any status — a reviewed or
        dismissed one is not re-raised every night) is reused."""
        try:
            with transaction.atomic():
                flag = None
                profile = cls._creator_profile(payment)
                if profile is not None:
                    existing = AbuseFlag.objects.filter(flag_type='payment_anomaly',
                                                        evidence__payment_id=payment.pk)
                    flag = existing.filter(status='open').first() or existing.first()
                    if flag is None:
                        flag = AbuseFlag.objects.create(
                            staff        = profile,
                            flag_type    = 'payment_anomaly',
                            severity     = 'critical',
                            description  = (
                                f'دفعة غير معتادة: درجة شذوذ {score}/100 — '
                                f'طريقة الدفع: {payment.get_method_display()} | المبلغ: {payment.amount} ج.م'
                            ),
                            evidence     = {
                                'payment_id': payment.pk,
                                'score': float(score),
                                'mean': round(mean, 2) if mean is not None else None,
                                'stdev': round(stdev, 2) if stdev is not None else None,
                                'samples': samples,
                            },
                            count        = 1,
                            window_hours = _ANOMALY_WINDOW_DAYS * 24,
                        )

                exc, _ = PaymentException.objects.get_or_create(
                    payment        = payment,
                    exception_type = PaymentException.TYPE_ANOMALY,
                    defaults={
                        'severity':      PaymentException.SEVERITY_CRITICAL,
                        'anomaly_score': score,
                        'detail':        f'درجة شذوذ إحصائي: {score}/100',
                        'abuse_flag_id': flag.pk if flag else None,
                    },
                )
                if flag is not None and exc.abuse_flag_id is None:
                    exc.abuse_flag_id = flag.pk
                    exc.save(update_fields=['abuse_flag_id'])
        except Exception:
            logger.exception('Failed to escalate payment #%s to AbuseFlag', payment.pk)

    @classmethod
    def run_exception_checks(cls, *, days: int = 7) -> dict:
        """Both checks over payments created in the last `days` days (cancelled ones skipped).
        Idempotent: a rerun creates nothing new. Writes only PaymentException / AbuseFlag."""
        since = timezone.now() - timedelta(days=days)
        ids = list(ExternalPayment.objects.filter(created_at__gte=since)
                   .exclude(status=ExternalPayment.STATUS_CANCELLED)
                   .order_by('pk').values_list('pk', flat=True))
        anomalies_qs = PaymentException.objects.filter(exception_type=PaymentException.TYPE_ANOMALY)
        flags_qs = AbuseFlag.objects.filter(flag_type='payment_anomaly')
        anomalies_before, flags_before = anomalies_qs.count(), flags_qs.count()
        exceptions = failed = 0
        for pk in ids:
            try:                        # one bad payment must not stop the rest of the run
                exceptions += len(cls.detect_exceptions(pk))
                cls.calculate_anomaly_score(
                    ExternalPayment.objects.select_related('created_by__staff_profile').get(pk=pk))
            except Exception:
                failed += 1
                logger.exception('payment exception checks failed for payment #%s', pk)
        return {
            'payments': len(ids),
            'failed': failed,
            'exceptions_created': exceptions,
            'anomalies_created': anomalies_qs.count() - anomalies_before,
            'flags_created': flags_qs.count() - flags_before,
        }

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
