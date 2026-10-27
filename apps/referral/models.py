"""
apps/referral/models.py

Voucher Referral System with fraud detection.

Models:
  ReferralCode    — one per customer (slug + QR)
  ReferralLead    — friend contact submitted by a customer
  ReferralEvent   — immutable audit trail (submitted→invited→registered→validated→rewarded)
  FraudSignal     — per-lead fraud scoring record

Workflow:
  Customer A shares ReferralCode → staff/campaign contacts lead phone →
  OTP invitation sent (via WhatsApp) → recipient registers →
  OTP validated → ReferralEvent.validated → loyalty points credited

Fraud rules enforced:
  - Duplicate phone: same phone cannot be submitted by multiple referrers
  - Self-referral: referrer phone == lead phone
  - Circular: A refers B who has already referred A
  - Device fingerprint: multiple accounts from same device
  - OTP abuse: >3 OTP failures = freeze lead
"""
import hashlib
import secrets
import string
from django.db import models
from django.utils import timezone


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ReferralCode — one per customer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _generate_code():
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(8))


class ReferralCode(models.Model):

    customer    = models.OneToOneField(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='referral_code',
        verbose_name='العميل',
    )
    code        = models.CharField(
        max_length=20, unique=True, db_index=True,
        default=_generate_code,
        verbose_name='كود الإحالة',
    )
    is_active   = models.BooleanField(default=True, verbose_name='نشط')

    # Statistics (denormalised for fast display)
    total_leads       = models.PositiveIntegerField(default=0, verbose_name='إجمالي الإحالات')
    validated_leads   = models.PositiveIntegerField(default=0, verbose_name='إحالات ناجحة')
    total_points_earned = models.PositiveIntegerField(default=0, verbose_name='نقاط مكتسبة من الإحالات')

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'كود إحالة'
        verbose_name_plural = 'أكواد الإحالة'

    def __str__(self):
        return f'{self.customer.name} — {self.code}'

    @classmethod
    def get_or_create_for(cls, customer) -> 'ReferralCode':
        ref, _ = cls.objects.get_or_create(customer=customer)
        return ref

    @property
    def referral_url(self) -> str:
        from django.conf import settings
        base = getattr(settings, 'FRONTEND_BASE_URL', 'https://app.elrezeiky.com')
        return f'{base}/register?ref={self.code}'

    def generate_qr_svg(self) -> str:
        """Return a simple SVG QR code data URI for the referral URL."""
        try:
            import qrcode
            import io
            qr = qrcode.QRCode(box_size=4, border=2)
            qr.add_data(self.referral_url)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            import base64
            b64 = base64.b64encode(buf.getvalue()).decode()
            return f'data:image/png;base64,{b64}'
        except Exception:
            return ''


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ReferralLead — friend contact submitted by customer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ReferralLead(models.Model):

    STATUS_CHOICES = [
        ('pending',     'بانتظار الاتصال'),
        ('invited',     'تم إرسال الدعوة'),
        ('registered',  'سجّل'),
        ('validated',   'تم التحقق'),
        ('rewarded',    'تم المكافأة'),
        ('rejected',    'مرفوض (احتيال)'),
        ('expired',     'انتهت الصلاحية'),
        ('frozen',      'مجمّد (OTP أبيوز)'),
    ]

    RELATIONSHIP_CHOICES = [
        ('family',    'عائلة'),
        ('friend',    'صديق'),
        ('colleague', 'زميل'),
        ('neighbor',  'جار'),
        ('other',     'أخرى'),
    ]

    referral_code = models.ForeignKey(
        ReferralCode,
        on_delete=models.CASCADE,
        related_name='leads',
        verbose_name='كود الإحالة',
    )
    # Referred-by (referrer) customer — shortcut to referral_code.customer
    referrer      = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='referred_leads',
        verbose_name='المُحيل',
    )

    # Lead details (submitted by referrer)
    lead_name     = models.CharField(max_length=255, verbose_name='اسم الصديق')
    lead_phone    = models.CharField(max_length=30, db_index=True, verbose_name='رقم هاتف الصديق')
    relationship  = models.CharField(
        max_length=15, choices=RELATIONSHIP_CHOICES,
        default='friend', verbose_name='الصلة',
    )
    notes         = models.TextField(blank=True, verbose_name='ملاحظات')

    status        = models.CharField(
        max_length=12, choices=STATUS_CHOICES,
        default='pending', db_index=True, verbose_name='الحالة',
    )

    # Linked customer created after registration
    registered_customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='referral_source',
        verbose_name='العميل المُسجَّل',
    )

    # OTP tracking (plain OTP NEVER stored — only attempt count)
    otp_attempts  = models.PositiveSmallIntegerField(default=0, verbose_name='محاولات OTP')
    invitation_sent_at = models.DateTimeField(null=True, blank=True)
    invitation_expires_at = models.DateTimeField(null=True, blank=True)

    # Fraud scoring
    fraud_score   = models.PositiveSmallIntegerField(
        default=0, verbose_name='درجة الاحتيال (0-100)',
    )
    fraud_flags   = models.JSONField(default=list, blank=True, verbose_name='مؤشرات الاحتيال')

    # Device fingerprint (collected at registration attempt)
    device_fingerprint = models.CharField(max_length=64, blank=True, db_index=True)

    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at    = models.DateTimeField(auto_now=True)
    validated_at  = models.DateTimeField(null=True, blank=True)
    rewarded_at   = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'إحالة'
        verbose_name_plural = 'الإحالات'
        # A phone can only be an active lead once
        constraints = [
            models.UniqueConstraint(
                fields=['lead_phone'],
                condition=models.Q(status__in=['pending', 'invited', 'registered']),
                name='referral_lead_phone_active_unique',
            )
        ]
        indexes = [
            models.Index(fields=['referrer', 'status']),
            models.Index(fields=['lead_phone', 'status']),
        ]

    def __str__(self):
        return f'{self.lead_name} ({self.lead_phone}) ← {self.referrer.name} [{self.get_status_display()}]'

    def increment_otp_attempt(self):
        self.otp_attempts += 1
        if self.otp_attempts >= 3:
            self.status = 'frozen'
        self.save(update_fields=['otp_attempts', 'status', 'updated_at'])

    def mark_invited(self):
        from datetime import timedelta
        self.status = 'invited'
        self.invitation_sent_at = timezone.now()
        self.invitation_expires_at = timezone.now() + timedelta(days=7)
        self.save(update_fields=['status', 'invitation_sent_at', 'invitation_expires_at', 'updated_at'])
        ReferralEvent.log(self, 'invited', 'تم إرسال دعوة OTP')

    def mark_registered(self, customer):
        self.status = 'registered'
        self.registered_customer = customer
        self.save(update_fields=['status', 'registered_customer', 'updated_at'])
        ReferralEvent.log(self, 'registered', f'سجّل العميل #{customer.pk}')

    def validate(self):
        self.status = 'validated'
        self.validated_at = timezone.now()
        self.save(update_fields=['status', 'validated_at', 'updated_at'])
        ReferralEvent.log(self, 'validated', 'تم التحقق من الإحالة')

    def reward(self, points_awarded: int):
        self.status = 'rewarded'
        self.rewarded_at = timezone.now()
        self.save(update_fields=['status', 'rewarded_at', 'updated_at'])
        ReferralEvent.log(self, 'rewarded', f'مكافأة {points_awarded} نقطة للمُحيل')
        # Update referral code statistics
        ReferralCode.objects.filter(pk=self.referral_code_id).update(
            validated_leads=models.F('validated_leads') + 1,
            total_points_earned=models.F('total_points_earned') + points_awarded,
        )

    def reject_fraud(self, reason: str):
        self.status = 'rejected'
        self.fraud_flags = self.fraud_flags + [reason]
        self.save(update_fields=['status', 'fraud_flags', 'updated_at'])
        ReferralEvent.log(self, 'rejected', f'رُفض — {reason}')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ReferralEvent — immutable audit trail
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ReferralEvent(models.Model):

    EVENT_CHOICES = [
        ('submitted',   'تم الإرسال'),
        ('invited',     'تم إرسال الدعوة'),
        ('registered',  'سجّل'),
        ('validated',   'تم التحقق'),
        ('rewarded',    'تم المكافأة'),
        ('rejected',    'مرفوض'),
        ('otp_attempt', 'محاولة OTP'),
        ('frozen',      'مجمّد'),
    ]

    lead       = models.ForeignKey(
        ReferralLead,
        on_delete=models.CASCADE,
        related_name='events',
        verbose_name='الإحالة',
    )
    event_type = models.CharField(max_length=15, choices=EVENT_CHOICES, db_index=True)
    message    = models.TextField(blank=True)
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    # Metadata payload (IP, device, etc.)
    meta       = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['created_at']
        verbose_name        = 'حدث إحالة'
        verbose_name_plural = 'أحداث الإحالة'

    def __str__(self):
        return f'[{self.get_event_type_display()}] إحالة #{self.lead_id} — {self.created_at:%Y-%m-%d %H:%M}'

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('ReferralEvent is immutable — cannot edit')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('ReferralEvent is immutable — cannot delete')

    @classmethod
    def log(cls, lead: ReferralLead, event_type: str, message: str = '',
            staff=None, meta: dict | None = None) -> 'ReferralEvent':
        return cls.objects.create(
            lead=lead,
            event_type=event_type,
            message=message,
            created_by=staff,
            meta=meta or {},
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FraudSignal — per-lead fraud scoring record
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FraudSignal(models.Model):

    SIGNAL_CHOICES = [
        ('duplicate_phone',     'هاتف مكرر'),
        ('self_referral',       'إحالة ذاتية'),
        ('circular_referral',   'إحالة دائرية'),
        ('device_collision',    'تصادم الجهاز'),
        ('otp_abuse',           'إساءة استخدام OTP'),
        ('mass_submission',     'إرسال جماعي مشبوه'),
        ('velocity',            'تجاوز معدل الإرسال'),
        ('known_fraud_device',  'جهاز محظور مسبقاً'),
    ]

    lead          = models.ForeignKey(
        ReferralLead,
        on_delete=models.CASCADE,
        related_name='fraud_signals',
        verbose_name='الإحالة',
    )
    signal_type   = models.CharField(
        max_length=25, choices=SIGNAL_CHOICES, db_index=True,
        verbose_name='نوع المؤشر',
    )
    score_delta   = models.PositiveSmallIntegerField(
        verbose_name='إضافة للدرجة',
        help_text='النقاط المضافة إلى fraud_score للإحالة',
    )
    detail        = models.TextField(blank=True, verbose_name='التفاصيل')
    detected_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-detected_at']
        verbose_name        = 'مؤشر احتيال'
        verbose_name_plural = 'مؤشرات الاحتيال'

    def __str__(self):
        return f'[{self.get_signal_type_display()}] إحالة #{self.lead_id} +{self.score_delta}'
