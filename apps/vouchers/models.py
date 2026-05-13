"""
apps/vouchers/models.py

Voucher — a discount/credit document issued to a customer or staff member.
VoucherOTP — one-time password for in-store redemption (hashed, 3-min expiry, single-use).
"""
import hashlib
import secrets
import string
from django.db import models
from django.utils import timezone


class Voucher(models.Model):
    TYPE_CHOICES = [
        ('discount_pct',  'خصم بالنسبة المئوية'),
        ('discount_fixed','خصم بمبلغ ثابت'),
        ('credit',        'رصيد نقدي'),
        ('free_item',     'صنف مجاني'),
    ]
    STATUS_CHOICES = [
        ('active',   'نشط'),
        ('used',     'مُستخدَم'),
        ('expired',  'منتهي'),
        ('cancelled','ملغى'),
    ]

    # Identity
    code         = models.CharField(max_length=30, unique=True, db_index=True, verbose_name='كود القسيمة')
    title        = models.CharField(max_length=200, verbose_name='العنوان')
    description  = models.TextField(blank=True, verbose_name='الوصف')
    voucher_type = models.CharField(max_length=20, choices=TYPE_CHOICES, verbose_name='النوع')

    # Value
    discount_pct   = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name='نسبة الخصم %')
    discount_amount = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name='مبلغ الخصم')
    credit_amount  = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name='قيمة الرصيد')
    free_item      = models.ForeignKey('catalog.Item', null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name='+', verbose_name='الصنف المجاني')

    # Targeting
    customer       = models.ForeignKey('customers.Customer', null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='vouchers',
                                        verbose_name='العميل')
    branch         = models.ForeignKey('branches.Branch', null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='vouchers',
                                        verbose_name='الفرع (تقييد)')

    # Validity
    valid_from     = models.DateField(verbose_name='صالح من')
    valid_until    = models.DateField(null=True, blank=True, verbose_name='صالح حتى')
    max_uses       = models.PositiveSmallIntegerField(default=1, verbose_name='الحد الأقصى للاستخدام')
    times_used     = models.PositiveSmallIntegerField(default=0, verbose_name='مرات الاستخدام')

    # Status
    status         = models.CharField(max_length=15, choices=STATUS_CHOICES, default='active', verbose_name='الحالة')

    # Metadata
    created_by     = models.ForeignKey('users.StaffProfile', null=True, on_delete=models.SET_NULL,
                                        related_name='vouchers_created', verbose_name='أُنشئت بواسطة')
    notes          = models.TextField(blank=True, verbose_name='ملاحظات')
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'قسيمة'
        verbose_name_plural = 'قسائم'
        ordering            = ['-created_at']

    def __str__(self):
        return f'{self.code} — {self.title}'

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

    @classmethod
    def generate_code(cls, prefix='VCH', length=8):
        """Generate a unique alphanumeric code."""
        chars = string.ascii_uppercase + string.digits
        while True:
            suffix = ''.join(secrets.choice(chars) for _ in range(length))
            code   = f'{prefix}-{suffix}'
            if not cls.objects.filter(code=code).exists():
                return code


class VoucherOTP(models.Model):
    """
    One-time password for redeeming a voucher at the POS / store counter.
    Hash-stored for security; expires after N minutes (default 3).
    """
    voucher      = models.ForeignKey(Voucher, on_delete=models.CASCADE,
                                      related_name='otps', verbose_name='القسيمة')
    phone        = models.CharField(max_length=20, verbose_name='رقم الهاتف')
    code_hash    = models.CharField(max_length=64, verbose_name='هاش الرمز')
    is_used      = models.BooleanField(default=False, verbose_name='مُستخدَم')
    expires_at   = models.DateTimeField(verbose_name='ينتهي في')
    created_at   = models.DateTimeField(auto_now_add=True)
    used_at      = models.DateTimeField(null=True, blank=True)
    sent_via     = models.CharField(max_length=20, default='whatsapp', verbose_name='أُرسل عبر')

    class Meta:
        verbose_name        = 'رمز OTP'
        verbose_name_plural = 'رموز OTP'
        ordering            = ['-created_at']

    def __str__(self):
        return f'OTP for {self.voucher.code} → {self.phone}'

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired

    @classmethod
    def _hash(cls, code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()

    @classmethod
    def create_for_voucher(cls, voucher, phone: str, expiry_minutes: int = 3) -> tuple:
        """
        Creates a new OTP, hashes it, returns (otp_instance, plain_code).
        Any previous unused OTPs for this voucher+phone are invalidated.
        """
        # Invalidate old OTPs
        cls.objects.filter(voucher=voucher, phone=phone, is_used=False).update(is_used=True)

        plain = ''.join(secrets.choice(string.digits) for _ in range(6))
        otp = cls.objects.create(
            voucher    = voucher,
            phone      = phone,
            code_hash  = cls._hash(plain),
            expires_at = timezone.now() + timezone.timedelta(minutes=expiry_minutes),
        )
        return otp, plain

    def verify(self, plain_code: str) -> bool:
        """Returns True and marks used if the code matches and is not expired/used."""
        if not self.is_valid:
            return False
        if self._hash(plain_code) != self.code_hash:
            return False
        self.is_used  = True
        self.used_at  = timezone.now()
        self.save(update_fields=['is_used', 'used_at'])
        return True


class VoucherRedemption(models.Model):
    """Audit log of each successful redemption."""
    voucher     = models.ForeignKey(Voucher, on_delete=models.CASCADE,
                                     related_name='redemptions')
    otp         = models.OneToOneField(VoucherOTP, null=True, blank=True,
                                        on_delete=models.SET_NULL)
    redeemed_by = models.ForeignKey('users.StaffProfile', null=True,
                                     on_delete=models.SET_NULL)
    branch      = models.ForeignKey('branches.Branch', null=True,
                                     on_delete=models.SET_NULL)
    redeemed_at = models.DateTimeField(auto_now_add=True)
    notes       = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['-redeemed_at']
