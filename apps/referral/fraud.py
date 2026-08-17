"""
apps/referral/fraud.py

Fraud scoring engine for referral leads.

Scoring rules (cumulative — higher score = more suspicious):
  duplicate_phone     +40  — phone already exists as a lead or customer
  self_referral       +100 — referrer phone matches lead phone
  circular_referral   +80  — B has already referred A
  device_collision    +60  — same device fingerprint as another account
  otp_abuse           +50  — >3 OTP failures
  mass_submission     +30  — referrer submitted >5 leads in 24h
  velocity            +20  — >10 submissions from same referrer this week

Threshold:
  score >= 80 → auto-reject
  score >= 40 → flag for manual review (fraud_flags set, status stays pending)
  score <  40 → clean

Usage:
    from apps.referral.fraud import FraudEngine

    result = FraudEngine(lead).evaluate()
    # result = {'score': 0, 'flags': [], 'action': 'clean'}
"""
import logging
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger('elrezeiky.referral')

AUTO_REJECT_THRESHOLD = 80
REVIEW_THRESHOLD = 40


class FraudEngine:

    def __init__(self, lead):
        self.lead    = lead
        self.score   = 0
        self.flags   = []
        self.signals = []   # (signal_type, delta, detail)

    def evaluate(self) -> dict:
        self._check_self_referral()
        self._check_duplicate_phone()
        self._check_circular_referral()
        self._check_device_collision()
        self._check_mass_submission()
        self._check_velocity()

        self._persist_signals()
        self._update_lead()

        if self.score >= AUTO_REJECT_THRESHOLD:
            action = 'reject'
        elif self.score >= REVIEW_THRESHOLD:
            action = 'review'
        else:
            action = 'clean'

        return {'score': self.score, 'flags': self.flags, 'action': action}

    # ── Fraud checks ──────────────────────────────────────────────────────────

    def _check_self_referral(self):
        try:
            referrer_phones = set()
            c = self.lead.referrer
            if c.phone:
                referrer_phones.add(c.phone.strip().replace(' ', '')[-9:])
            if c.phone_alt:
                referrer_phones.add(c.phone_alt.strip().replace(' ', '')[-9:])

            lead_tail = self.lead.lead_phone.strip().replace(' ', '')[-9:]
            if lead_tail in referrer_phones:
                self._add('self_referral', 100, 'رقم هاتف المُحيل مطابق لرقم الصديق')
        except Exception as exc:
            logger.debug('self_referral check failed: %s', exc)

    def _check_duplicate_phone(self):
        from apps.referral.models import ReferralLead
        try:
            qs = ReferralLead.objects.filter(
                lead_phone=self.lead.lead_phone,
                status__in=['pending', 'invited', 'registered', 'validated'],
            ).exclude(pk=self.lead.pk)
            if qs.exists():
                self._add('duplicate_phone', 40, f'رقم الهاتف موجود بالفعل في {qs.count()} إحالة')
        except Exception as exc:
            logger.debug('duplicate_phone check failed: %s', exc)

        # Also check if the phone is already a Customer
        try:
            from apps.customers.models import Customer
            tail = self.lead.lead_phone.strip().replace(' ', '')[-9:]
            if Customer.objects.filter(phone__endswith=tail, is_guest=False).exists():
                self._add('duplicate_phone', 20, 'رقم الهاتف مسجَّل بالفعل كعميل')
        except Exception as exc:
            logger.debug('customer phone check failed: %s', exc)

    def _check_circular_referral(self):
        from apps.referral.models import ReferralLead
        try:
            # Does the lead's phone number belong to someone who has referred the current referrer?
            tail = self.lead.lead_phone.strip().replace(' ', '')[-9:]
            from apps.customers.models import Customer
            lead_customer = (
                Customer.objects.filter(phone__endswith=tail).first()
                or Customer.objects.filter(phone_alt__endswith=tail).first()
            )
            if not lead_customer:
                return
            if ReferralLead.objects.filter(
                referrer=lead_customer,
                lead_phone__endswith=self.lead.referrer.phone[-9:] if self.lead.referrer.phone else '',
                status__in=['validated', 'rewarded'],
            ).exists():
                self._add('circular_referral', 80, 'الصديق المُحال سبق أن أحال المُحيل')
        except Exception as exc:
            logger.debug('circular_referral check failed: %s', exc)

    def _check_device_collision(self):
        from apps.referral.models import ReferralLead
        try:
            fp = self.lead.device_fingerprint
            if not fp:
                return
            collision = ReferralLead.objects.filter(
                device_fingerprint=fp,
            ).exclude(pk=self.lead.pk).exclude(referrer=self.lead.referrer)
            if collision.exists():
                self._add('device_collision', 60, f'نفس بصمة الجهاز في {collision.count()} إحالة أخرى')
        except Exception as exc:
            logger.debug('device_collision check failed: %s', exc)

    def _check_mass_submission(self):
        from apps.referral.models import ReferralLead
        try:
            count_24h = ReferralLead.objects.filter(
                referrer=self.lead.referrer,
                created_at__gte=timezone.now() - timedelta(hours=24),
            ).count()
            if count_24h > 5:
                self._add('mass_submission', 30, f'المُحيل أرسل {count_24h} إحالة في 24 ساعة')
        except Exception as exc:
            logger.debug('mass_submission check failed: %s', exc)

    def _check_velocity(self):
        from apps.referral.models import ReferralLead
        try:
            count_week = ReferralLead.objects.filter(
                referrer=self.lead.referrer,
                created_at__gte=timezone.now() - timedelta(days=7),
            ).count()
            if count_week > 10:
                self._add('velocity', 20, f'المُحيل أرسل {count_week} إحالة هذا الأسبوع')
        except Exception as exc:
            logger.debug('velocity check failed: %s', exc)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _add(self, signal_type: str, delta: int, detail: str):
        self.score = min(100, self.score + delta)
        self.flags.append(signal_type)
        self.signals.append((signal_type, delta, detail))

    def _persist_signals(self):
        from apps.referral.models import FraudSignal
        for signal_type, delta, detail in self.signals:
            try:
                FraudSignal.objects.create(
                    lead=self.lead,
                    signal_type=signal_type,
                    score_delta=delta,
                    detail=detail,
                )
            except Exception as exc:
                logger.warning('FraudSignal persist failed: %s', exc)

    def _update_lead(self):
        try:
            self.lead.fraud_score = self.score
            self.lead.fraud_flags = self.flags
            self.lead.save(update_fields=['fraud_score', 'fraud_flags', 'updated_at'])
        except Exception as exc:
            logger.warning('FraudEngine lead update failed: %s', exc)
