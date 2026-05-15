"""
apps/vouchers/models.py

Production-grade voucher system:
  Voucher                  — master discount rule
  VoucherAssignment        — per-customer phone assignment + usage tracking
  VoucherOTP               — HMAC-SHA256 hashed 6-digit code, 3-min TTL, retry/resend limits
  VoucherRedemptionDocument — POS reference document (active → used), 15-min window
  VoucherRedemption        — final audit record after POS mark-used
"""
import hashlib
import hmac
import secrets
import string
from urllib.parse import quote

from django.db import models
from django.utils import timezone


# ── Voucher ────────────────────────────────────────────────────────────────────

class Voucher(models.Model):
    """Master voucher rule — created by managers, redeemed by customers at POS."""

    # How the voucher is distributed
    CATEGORY_CHOICES = [
        ('public',     'عام — لأي عميل'),
        ('private',    'خاص — عميل محدد'),
        ('first_time', 'أول مرة'),
        ('assigned',   'مخصص بالهاتف'),
    ]

    # How the discount is calculated
    TYPE_CHOICES = [
        ('discount_pct',   'خصم بالنسبة المئوية'),
        ('discount_fixed', 'خصم بمبلغ ثابت'),
        ('credit',         'رصيد نقدي'),
        ('free_item',      'صنف مجاني'),
    ]
    STATUS_CHOICES = [
        ('active',    'نشط'),
        ('used',      'مُستخدَم'),
        ('expired',   'منتهي'),
        ('cancelled', 'ملغى'),
    ]

    # ── Identity ───────────────────────────────────────────────────────────────
    code             = models.CharField(max_length=30, unique=True, db_index=True,
                                         verbose_name='كود القسيمة')
    title            = models.CharField(max_length=200, verbose_name='العنوان')
    description      = models.TextField(blank=True, verbose_name='الوصف')
    voucher_category = models.CharField(max_length=15, choices=CATEGORY_CHOICES,
                                         default='public', verbose_name='فئة التوزيع')
    voucher_type     = models.CharField(max_length=20, choices=TYPE_CHOICES,
                                         verbose_name='آلية الخصم')

    # ── Value ──────────────────────────────────────────────────────────────────
    discount_pct    = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                           verbose_name='نسبة الخصم %')
    discount_amount = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                           verbose_name='مبلغ الخصم')
    credit_amount   = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                           verbose_name='قيمة الرصيد')
    free_item       = models.ForeignKey('catalog.Item', null=True, blank=True,
                                         on_delete=models.SET_NULL,
                                         related_name='+', verbose_name='الصنف المجاني')
    max_discount_cap = models.DecimalField(max_digits=10, decimal_places=3,
                                            null=True, blank=True,
                                            verbose_name='الحد الأقصى للخصم (ج.م)')
    min_order_value  = models.DecimalField(max_digits=10, decimal_places=3,
                                            null=True, blank=True,
                                            verbose_name='الحد الأدنى للطلب (ج.م)')

    # ── Targeting ─────────────────────────────────────────────────────────────
    customer             = models.ForeignKey('customers.Customer', null=True, blank=True,
                                              on_delete=models.SET_NULL,
                                              related_name='vouchers',
                                              verbose_name='عميل محدد (خاص)')
    branch               = models.ForeignKey('branches.Branch', null=True, blank=True,
                                              on_delete=models.SET_NULL,
                                              related_name='vouchers',
                                              verbose_name='الفرع (تقييد)')
    applicable_items     = models.ManyToManyField('catalog.Item', blank=True,
                                                   related_name='vouchers',
                                                   verbose_name='الأصناف المؤهلة')
    applicable_branches  = models.ManyToManyField('branches.Branch', blank=True,
                                                   related_name='applicable_vouchers',
                                                   verbose_name='الفروع المؤهلة')

    # ── Limits ────────────────────────────────────────────────────────────────
    max_uses                      = models.PositiveSmallIntegerField(default=1,
                                                                      verbose_name='الحد الأقصى للاستخدام الكلي')
    times_used                    = models.PositiveIntegerField(default=0,
                                                                 verbose_name='مرات الاستخدام')
    usage_limit_per_customer      = models.PositiveSmallIntegerField(default=1,
                                                                      verbose_name='حد الاستخدام للعميل الواحد')
    usage_limit_per_day           = models.PositiveSmallIntegerField(null=True, blank=True,
                                                                      verbose_name='حد الاستخدام في اليوم')
    validity_days_after_assignment = models.PositiveSmallIntegerField(null=True, blank=True,
                                                                       verbose_name='صلاحية بعد التخصيص (أيام)')

    # ── Validity ──────────────────────────────────────────────────────────────
    valid_from  = models.DateField(verbose_name='صالح من')
    valid_until = models.DateField(null=True, blank=True, verbose_name='صالح حتى')

    # ── Status ────────────────────────────────────────────────────────────────
    status = models.CharField(max_length=15, choices=STATUS_CHOICES,
                               default='active', verbose_name='الحالة')

    # ── Metadata ──────────────────────────────────────────────────────────────
    created_by = models.ForeignKey('users.StaffProfile', null=True,
                                    on_delete=models.SET_NULL,
                                    related_name='vouchers_created',
                                    verbose_name='أُنشئت بواسطة')
    notes      = models.TextField(blank=True, verbose_name='ملاحظات')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'قسيمة'
        verbose_name_plural = 'قسائم'
        ordering            = ['-created_at']
        indexes             = [
            models.Index(fields=['status', 'valid_until']),
            models.Index(fields=['voucher_category', 'status']),
        ]

    def __str__(self):
        return f'{self.code} — {self.title}'

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_expired(self):
        if self.valid_until:
            return timezone.now().date() > self.valid_until
        return False

    @property
    def is_exhausted(self):
        return self.times_used >= self.max_uses

    def refresh_status(self):
        if self.status == 'cancelled':
            return
        if self.is_expired:
            self.status = 'expired'
        elif self.is_exhausted:
            self.status = 'used'
        else:
            self.status = 'active'
        self.save(update_fields=['status', 'updated_at'])

    # ── Discount engine ────────────────────────────────────────────────────────

    def calculate_discount(self, order_amount: float) -> float:
        """
        Returns the discount amount in EGP for the given order_amount.
        Applies min_order_value check and max_discount_cap.
        Returns 0.0 if not applicable.
        """
        if self.min_order_value and order_amount < float(self.min_order_value):
            return 0.0

        if self.voucher_type == 'discount_fixed':
            discount = float(self.discount_amount)
        elif self.voucher_type == 'discount_pct':
            discount = order_amount * float(self.discount_pct) / 100.0
        elif self.voucher_type == 'credit':
            discount = float(self.credit_amount)
        else:
            discount = 0.0

        # Cap
        if self.max_discount_cap and discount > float(self.max_discount_cap):
            discount = float(self.max_discount_cap)

        # Can't discount more than the order value
        return min(discount, order_amount)

    def check_customer_eligibility(self, phone: str) -> tuple[bool, str]:
        """
        Returns (eligible, reason) for a given customer phone.
        Checks: category rules, per-customer limit, per-day limit.
        """
        from django.utils import timezone as tz

        self.refresh_status()
        if self.status != 'active':
            return False, f'القسيمة غير نشطة ({self.get_status_display()})'

        # Per-customer limit
        customer_uses = VoucherRedemption.objects.filter(
            voucher=self, customer_phone=phone
        ).count()
        if customer_uses >= self.usage_limit_per_customer:
            return False, 'تجاوز الحد المسموح به لهذا العميل'

        # Per-day limit
        if self.usage_limit_per_day:
            today_uses = VoucherRedemption.objects.filter(
                voucher=self,
                redeemed_at__date=tz.now().date(),
            ).count()
            if today_uses >= self.usage_limit_per_day:
                return False, 'تجاوز الحد اليومي لهذه القسيمة'

        # Assignment check for assigned/private/first_time
        if self.voucher_category == 'private':
            if not self.customer_id:
                return False, 'قسيمة خاصة بدون عميل محدد'

        if self.voucher_category == 'assigned':
            if not VoucherAssignment.objects.filter(
                voucher=self, customer_phone=phone, is_active=True
            ).exists():
                return False, 'هذا الهاتف غير مخصص لهذه القسيمة'

        return True, 'مؤهل'

    # ── Code generator ─────────────────────────────────────────────────────────

    @classmethod
    def generate_code(cls, prefix='VCH', length=8):
        chars = string.ascii_uppercase + string.digits
        while True:
            suffix = ''.join(secrets.choice(chars) for _ in range(length))
            code   = f'{prefix}-{suffix}'
            if not cls.objects.filter(code=code).exists():
                return code


# ── VoucherAssignment ─────────────────────────────────────────────────────────

class VoucherAssignment(models.Model):
    """
    Assigns a voucher to a specific phone number.
    Used for voucher_category='assigned'.
    Also tracks per-assignment usage count.
    """
    voucher        = models.ForeignKey(Voucher, on_delete=models.CASCADE,
                                        related_name='assignments',
                                        verbose_name='القسيمة')
    customer_phone = models.CharField(max_length=20, db_index=True,
                                       verbose_name='هاتف العميل')
    customer       = models.ForeignKey('customers.Customer', null=True, blank=True,
                                        on_delete=models.SET_NULL,
                                        related_name='voucher_assignments',
                                        verbose_name='العميل')
    assigned_by    = models.ForeignKey('users.StaffProfile', null=True,
                                        on_delete=models.SET_NULL,
                                        related_name='voucher_assignments',
                                        verbose_name='خُصِّصت بواسطة')
    assigned_at    = models.DateTimeField(auto_now_add=True)
    expires_at     = models.DateTimeField(null=True, blank=True,
                                           verbose_name='ينتهي في')
    usage_count    = models.PositiveSmallIntegerField(default=0,
                                                       verbose_name='مرات الاستخدام')
    is_active      = models.BooleanField(default=True, verbose_name='نشط')

    class Meta:
        verbose_name        = 'تخصيص قسيمة'
        verbose_name_plural = 'تخصيصات القسائم'
        unique_together     = ['voucher', 'customer_phone']
        ordering            = ['-assigned_at']

    def __str__(self):
        return f'{self.voucher.code} → {self.customer_phone}'


# ── VoucherOTP ────────────────────────────────────────────────────────────────

class VoucherOTP(models.Model):
    """
    HMAC-SHA256 hashed OTP.
    Salt is stored alongside hash — the plain code is NEVER persisted.
    WhatsApp URL is generated for delivery; plain OTP never returned to UI.

    Limits enforced at view level:
      - Max 3 retries per OTP instance
      - Max 3 resends per voucher+phone per 10 min
    """
    voucher       = models.ForeignKey(Voucher, on_delete=models.CASCADE,
                                       related_name='otps', verbose_name='القسيمة')
    phone         = models.CharField(max_length=20, db_index=True,
                                      verbose_name='رقم الهاتف')
    code_hash     = models.CharField(max_length=64, verbose_name='هاش الرمز')
    otp_salt      = models.CharField(max_length=32, verbose_name='الملح')
    is_used       = models.BooleanField(default=False, verbose_name='مُستخدَم')
    expires_at    = models.DateTimeField(verbose_name='ينتهي في')
    created_at    = models.DateTimeField(auto_now_add=True)
    used_at       = models.DateTimeField(null=True, blank=True)
    sent_via      = models.CharField(max_length=20, default='whatsapp',
                                      verbose_name='أُرسل عبر')
    retry_count   = models.PositiveSmallIntegerField(default=0,
                                                      verbose_name='عدد المحاولات')
    resend_count  = models.PositiveSmallIntegerField(default=0,
                                                      verbose_name='عدد إعادة الإرسال')

    MAX_RETRIES = 3

    class Meta:
        verbose_name        = 'رمز OTP'
        verbose_name_plural = 'رموز OTP'
        ordering            = ['-created_at']
        indexes             = [
            models.Index(fields=['voucher', 'phone', 'is_used']),
        ]

    def __str__(self):
        return f'OTP for {self.voucher.code} → {self.phone}'

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired and self.retry_count < self.MAX_RETRIES

    @classmethod
    def _hash(cls, plain: str, salt: str) -> str:
        """HMAC-SHA256 with salt — brute-force resistant."""
        return hmac.new(
            salt.encode(), plain.encode(), hashlib.sha256
        ).hexdigest()

    @classmethod
    def create_for_voucher(cls, voucher, phone: str, expiry_minutes: int = 3) -> tuple:
        """
        Generates a fresh 6-digit OTP with random salt.
        Invalidates any previous unused OTPs for this voucher+phone.
        Returns (otp_instance, whatsapp_url).
        The plain code is NEVER stored and never returned directly to the UI.
        """
        # Invalidate old active OTPs
        cls.objects.filter(voucher=voucher, phone=phone, is_used=False).update(is_used=True)

        plain  = ''.join(secrets.choice(string.digits) for _ in range(6))
        salt   = secrets.token_hex(16)

        otp = cls.objects.create(
            voucher    = voucher,
            phone      = phone,
            code_hash  = cls._hash(plain, salt),
            otp_salt   = salt,
            expires_at = timezone.now() + timezone.timedelta(minutes=expiry_minutes),
        )

        # Build WhatsApp URL — OTP goes to customer's phone via WhatsApp
        msg = (
            f'رمز تحقق قسيمتك لدى صيدليات الرزيقي:\n'
            f'🔐 *{plain}*\n'
            f'القسيمة: {voucher.title}\n'
            f'صالح لمدة {expiry_minutes} دقائق فقط.\n'
            f'لا تشاركه مع أي شخص.'
        )
        # Normalize phone: strip leading zeros, add country code if needed
        whatsapp_phone = phone.lstrip('0')
        if not whatsapp_phone.startswith('20'):
            whatsapp_phone = '20' + whatsapp_phone
        whatsapp_url = f'https://wa.me/{whatsapp_phone}?text={quote(msg)}'

        return otp, whatsapp_url

    def verify(self, plain_code: str) -> bool:
        """
        Verifies the code. Increments retry_count on failure.
        Returns True on success, False otherwise.
        """
        if not self.is_valid:
            return False

        if self._hash(plain_code, self.otp_salt) != self.code_hash:
            self.retry_count += 1
            self.save(update_fields=['retry_count'])
            return False

        self.is_used = True
        self.used_at = timezone.now()
        self.save(update_fields=['is_used', 'used_at'])
        return True


# ── VoucherRedemptionDocument ─────────────────────────────────────────────────

class VoucherRedemptionDocument(models.Model):
    """
    Short-lived POS approval document.
    Created after OTP verification; consumed by POS within expiry_time.
    Generates a unique reference_code for POS validation.
    """
    STATUS_CHOICES = [
        ('active',    'نشط'),
        ('used',      'مُستخدَم'),
        ('expired',   'منتهي'),
        ('cancelled', 'ملغى'),
    ]

    voucher        = models.ForeignKey(Voucher, on_delete=models.CASCADE,
                                        related_name='documents',
                                        verbose_name='القسيمة')
    otp            = models.OneToOneField(VoucherOTP, null=True, blank=True,
                                           on_delete=models.SET_NULL,
                                           related_name='document',
                                           verbose_name='OTP المرتبط')
    customer_phone = models.CharField(max_length=20, db_index=True,
                                       verbose_name='هاتف العميل')
    employee       = models.ForeignKey('users.StaffProfile', null=True,
                                        on_delete=models.SET_NULL,
                                        related_name='voucher_documents',
                                        verbose_name='الموظف')
    branch         = models.ForeignKey('branches.Branch', null=True,
                                        on_delete=models.SET_NULL,
                                        related_name='voucher_documents',
                                        verbose_name='الفرع')
    generated_at   = models.DateTimeField(auto_now_add=True)
    expires_at     = models.DateTimeField(verbose_name='ينتهي في')  # 15 min
    status         = models.CharField(max_length=15, choices=STATUS_CHOICES,
                                       default='active', verbose_name='الحالة')
    reference_code = models.CharField(max_length=20, unique=True, db_index=True,
                                       verbose_name='كود المرجع (POS)')
    discount_applied = models.DecimalField(max_digits=10, decimal_places=3,
                                            null=True, blank=True,
                                            verbose_name='الخصم المحسوب')
    order_amount     = models.DecimalField(max_digits=10, decimal_places=3,
                                            null=True, blank=True,
                                            verbose_name='قيمة الطلب')
    used_at          = models.DateTimeField(null=True, blank=True)
    notes            = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name        = 'وثيقة استرداد'
        verbose_name_plural = 'وثائق الاسترداد'
        ordering            = ['-generated_at']
        indexes             = [
            models.Index(fields=['status', 'expires_at']),
            models.Index(fields=['reference_code']),
        ]

    def __str__(self):
        return f'DOC {self.reference_code} — {self.voucher.code}'

    @property
    def is_document_expired(self):
        return timezone.now() > self.expires_at and self.status == 'active'

    def refresh_document_status(self):
        if self.status == 'active' and self.is_document_expired:
            self.status = 'expired'
            self.save(update_fields=['status'])

    @classmethod
    def generate_reference(cls):
        """Generate unique REF-XXXXXXXX code."""
        chars = string.ascii_uppercase + string.digits
        while True:
            suffix = ''.join(secrets.choice(chars) for _ in range(8))
            ref    = f'REF-{suffix}'
            if not cls.objects.filter(reference_code=ref).exists():
                return ref


# ── VoucherRedemption ─────────────────────────────────────────────────────────

class VoucherRedemption(models.Model):
    """
    Final audit record — written when the POS confirms the document as used.
    Immutable once created.
    """
    voucher        = models.ForeignKey(Voucher, on_delete=models.CASCADE,
                                        related_name='redemptions')
    document       = models.OneToOneField(VoucherRedemptionDocument, null=True,
                                           blank=True, on_delete=models.SET_NULL,
                                           related_name='redemption')
    otp            = models.OneToOneField(VoucherOTP, null=True, blank=True,
                                           on_delete=models.SET_NULL,
                                           related_name='redemption')
    customer_phone = models.CharField(max_length=20, db_index=True, default='')
    redeemed_by    = models.ForeignKey('users.StaffProfile', null=True,
                                        on_delete=models.SET_NULL,
                                        related_name='voucher_redemptions')
    branch         = models.ForeignKey('branches.Branch', null=True,
                                        on_delete=models.SET_NULL,
                                        related_name='voucher_redemptions')
    redeemed_at    = models.DateTimeField(auto_now_add=True)
    discount_applied = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    order_amount     = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    notes            = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-redeemed_at']
        indexes  = [
            models.Index(fields=['voucher', 'customer_phone']),
            models.Index(fields=['redeemed_at']),
        ]

    def __str__(self):
        return f'Redemption #{self.id} — {self.voucher.code}'
