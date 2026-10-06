"""
apps/loyalty/models.py

Customer Loyalty Engine.

Models:
  LoyaltyTier         — tier definitions (Bronze / Silver / Gold / VIP)
  LoyaltyAccount      — one account per customer (balance + tier)
  PointTransaction    — immutable point ledger (NEVER deleted or edited)
  RewardCatalog       — redeemable rewards
  RedemptionRequest   — customer redemption request

Design rules:
  - PointTransaction is IMMUTABLE — no update or delete endpoints
  - Balance is always computed as SUM of PointTransaction.points (signed)
  - earn_rate per item comes from catalog_item.itempointsys = 1 flag
  - Tier is recomputed after every earn transaction
  - All monetary values are in EGP
"""
from decimal import Decimal
from django.db import models
from django.utils import timezone


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LoyaltyTier — tier definitions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LoyaltyTier(models.Model):

    name          = models.CharField(max_length=50, unique=True, verbose_name='اسم المستوى')
    name_ar       = models.CharField(max_length=50, blank=True, verbose_name='الاسم بالعربية')
    order         = models.PositiveSmallIntegerField(
        default=0, verbose_name='الترتيب',
        help_text='0 = أدنى (Bronze), higher = better',
    )
    min_points    = models.PositiveIntegerField(
        default=0, verbose_name='الحد الأدنى للنقاط',
        help_text='النقاط المتراكمة (lifetime) للوصول إلى هذا المستوى',
    )
    color         = models.CharField(max_length=20, default='#CD7F32', verbose_name='اللون')
    icon          = models.CharField(max_length=10, default='🥉', verbose_name='الأيقونة')
    earn_multiplier = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal('1.00'),
        verbose_name='معامل الكسب',
        help_text='e.g. 1.5 = يكسب 50% نقاط إضافية',
    )
    benefits_description = models.TextField(blank=True, verbose_name='مزايا المستوى')

    class Meta:
        ordering = ['order']
        verbose_name        = 'مستوى الولاء'
        verbose_name_plural = 'مستويات الولاء'

    def __str__(self):
        return f'{self.icon} {self.name_ar or self.name} (≥ {self.min_points} نقطة)'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LoyaltyAccount — one per customer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LoyaltyAccount(models.Model):

    customer      = models.OneToOneField(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='loyalty_account',
        verbose_name='العميل',
    )
    tier          = models.ForeignKey(
        LoyaltyTier,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='members',
        verbose_name='المستوى الحالي',
    )

    # Denormalised balances — kept in sync by PointTransaction.save()
    # Source of truth is always SUM(PointTransaction.points)
    points_balance  = models.IntegerField(default=0, verbose_name='الرصيد الحالي')
    points_lifetime = models.PositiveIntegerField(
        default=0, verbose_name='إجمالي النقاط المكتسبة (مدى الحياة)',
        help_text='فقط المعاملات الإيجابية — يُستخدم لتحديد المستوى',
    )
    points_redeemed = models.PositiveIntegerField(default=0, verbose_name='إجمالي النقاط المستبدلة')

    # SOFTECH-authoritative balance — synced from localcustomers.{SOFTECH_POINTS_COLUMN}
    # every sync cycle and on every procedure call.  Read-only in Django.
    softech_points_balance = models.IntegerField(
        default=0,
        verbose_name='رصيد النقاط (SOFTECH)',
        help_text='الرصيد الفعلي في SOFTECH — المصدر الأساسي للرصيد.',
    )

    is_active     = models.BooleanField(default=True, verbose_name='نشط')
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'حساب الولاء'
        verbose_name_plural = 'حسابات الولاء'

    def __str__(self):
        tier = self.tier.name if self.tier else '—'
        return f'{self.customer.name} | {self.points_balance} نقطة | {tier}'

    @classmethod
    def get_or_create_for(cls, customer) -> 'LoyaltyAccount':
        account, _ = cls.objects.get_or_create(customer=customer)
        return account

    def recompute_tier(self):
        """Upgrade/downgrade tier based on lifetime points."""
        tier = (
            LoyaltyTier.objects
            .filter(min_points__lte=self.points_lifetime)
            .order_by('-order')
            .first()
        )
        if tier and self.tier_id != tier.pk:
            self.tier = tier
            self.save(update_fields=['tier', 'updated_at'])

    def add_points(self, points: int, reason: str, source_type: str = 'purchase',
                   source_id: int | None = None, notes: str = '') -> 'PointTransaction':
        """Earn points — creates a PointTransaction and updates balance."""
        tx = PointTransaction.objects.create(
            account=self,
            points=abs(points),
            transaction_type='earn',
            source_type=source_type,
            source_id=source_id,
            reason=reason,
            notes=notes,
        )
        self.points_balance  += abs(points)
        self.points_lifetime += abs(points)
        self.save(update_fields=['points_balance', 'points_lifetime', 'updated_at'])
        self.recompute_tier()
        return tx

    def redeem_points(self, points: int, reason: str, reward=None,
                      notes: str = '') -> 'PointTransaction':
        """Redeem points — raises ValueError if balance insufficient."""
        points = abs(points)
        if self.points_balance < points:
            raise ValueError(
                f'رصيد النقاط غير كافٍ: متاح {self.points_balance}، مطلوب {points}'
            )
        tx = PointTransaction.objects.create(
            account=self,
            points=-points,
            transaction_type='redeem',
            source_type='reward',
            source_id=reward.pk if reward else None,
            reason=reason,
            notes=notes,
        )
        self.points_balance  -= points
        self.points_redeemed += points
        self.save(update_fields=['points_balance', 'points_redeemed', 'updated_at'])
        return tx

    def adjust_points(self, points: int, reason: str, by_staff,
                      notes: str = '') -> 'PointTransaction':
        """Manual adjustment (positive or negative) by a staff member."""
        tx = PointTransaction.objects.create(
            account=self,
            points=points,
            transaction_type='adjust',
            reason=reason,
            notes=notes,
            created_by=by_staff,
        )
        self.points_balance += points
        if points > 0:
            self.points_lifetime += points
        self.save(update_fields=['points_balance', 'points_lifetime', 'updated_at'])
        self.recompute_tier()
        return tx

    def expire_points(self, points: int, reason: str = 'انتهاء صلاحية النقاط') -> 'PointTransaction':
        points = min(abs(points), self.points_balance)
        if points == 0:
            return None
        tx = PointTransaction.objects.create(
            account=self,
            points=-points,
            transaction_type='expire',
            reason=reason,
        )
        self.points_balance -= points
        self.save(update_fields=['points_balance', 'updated_at'])
        return tx


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PointTransaction — immutable ledger (NEVER edit or delete)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class PointTransaction(models.Model):

    TYPE_CHOICES = [
        ('earn',    'كسب'),
        ('redeem',  'استبدال'),
        ('adjust',  'تعديل يدوي'),
        ('expire',  'انتهاء صلاحية'),
        ('refund',  'استرداد'),
        ('referral','مكافأة إحالة'),
        ('campaign','مكافأة حملة'),
        ('bonus',   'مكافأة خاصة'),
    ]

    SOURCE_CHOICES = [
        ('purchase',  'فاتورة شراء'),
        ('referral',  'إحالة ناجحة'),
        ('reward',    'استبدال مكافأة'),
        ('campaign',  'حملة تسويقية'),
        ('manual',    'يدوي'),
    ]

    account          = models.ForeignKey(
        LoyaltyAccount,
        on_delete=models.CASCADE,
        related_name='transactions',
        verbose_name='الحساب',
    )
    points           = models.IntegerField(
        verbose_name='النقاط',
        help_text='موجب = كسب، سالب = استبدال/انتهاء/تعديل سالب',
    )
    transaction_type = models.CharField(
        max_length=10, choices=TYPE_CHOICES, db_index=True,
        verbose_name='نوع المعاملة',
    )
    source_type      = models.CharField(
        max_length=15, choices=SOURCE_CHOICES, default='manual',
        verbose_name='المصدر',
    )
    # Generic FK to the source object (invoice ID, referral event ID, etc.)
    source_id        = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    reason           = models.CharField(max_length=255, verbose_name='السبب')
    notes            = models.TextField(blank=True, verbose_name='ملاحظات')

    # Running balance snapshot at the time of this transaction
    balance_after    = models.IntegerField(default=0, verbose_name='الرصيد بعد المعاملة')

    created_by       = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='بواسطة',
    )
    created_at       = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'معاملة نقاط'
        verbose_name_plural = 'معاملات النقاط'
        indexes = [
            models.Index(fields=['account', 'created_at']),
            models.Index(fields=['transaction_type', 'created_at']),
        ]

    def __str__(self):
        sign = '+' if self.points > 0 else ''
        return f'{sign}{self.points} نقطة — {self.get_transaction_type_display()} — {self.reason}'

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('PointTransaction is immutable — cannot edit after creation')
        # Snapshot the balance after this transaction
        if not self.balance_after and self.account_id:
            try:
                self.balance_after = self.account.points_balance + self.points
            except Exception:
                pass
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('PointTransaction is immutable — cannot delete')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RewardCatalog — redeemable rewards
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RewardCatalog(models.Model):

    TYPE_CHOICES = [
        ('voucher',          'قسيمة خصم'),
        ('cashback',         'استرداد نقدي'),
        ('gift_product',     'منتج مجاني'),
        ('discount_coupon',  'كوبون خصم'),
        ('priority_delivery','توصيل أولوية'),
        ('vip_status',       'ترقية VIP'),
    ]

    name          = models.CharField(max_length=255, verbose_name='اسم المكافأة')
    name_ar       = models.CharField(max_length=255, blank=True)
    reward_type   = models.CharField(
        max_length=20, choices=TYPE_CHOICES, db_index=True,
        verbose_name='نوع المكافأة',
    )
    points_cost   = models.PositiveIntegerField(verbose_name='تكلفة النقاط')
    description   = models.TextField(blank=True, verbose_name='الوصف')

    # Type-specific payload — e.g. {"voucher_value": 50, "min_order": 200}
    reward_data   = models.JSONField(default=dict, blank=True, verbose_name='بيانات المكافأة')

    # Eligibility
    min_tier      = models.ForeignKey(
        LoyaltyTier,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='الحد الأدنى للمستوى',
    )
    valid_from    = models.DateField(null=True, blank=True)
    valid_to      = models.DateField(null=True, blank=True)
    stock_limit   = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name='الحد الأقصى للاستبدال',
    )
    redeemed_count = models.PositiveIntegerField(default=0, verbose_name='عدد مرات الاستبدال')

    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['points_cost']
        verbose_name        = 'مكافأة'
        verbose_name_plural = 'كتالوج المكافآت'

    def __str__(self):
        return f'{self.name_ar or self.name} — {self.points_cost} نقطة'

    @property
    def is_available(self) -> bool:
        today = timezone.now().date()
        if not self.is_active:
            return False
        if self.valid_from and today < self.valid_from:
            return False
        if self.valid_to and today > self.valid_to:
            return False
        if self.stock_limit is not None and self.redeemed_count >= self.stock_limit:
            return False
        return True


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RedemptionRequest — customer redemption request
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RedemptionRequest(models.Model):

    STATUS_CHOICES = [
        ('pending',   'بانتظار الموافقة'),
        ('approved',  'معتمد'),
        ('fulfilled', 'تم الصرف'),
        ('rejected',  'مرفوض'),
        ('cancelled', 'ملغى'),
    ]

    account       = models.ForeignKey(
        LoyaltyAccount,
        on_delete=models.CASCADE,
        related_name='redemptions',
        verbose_name='الحساب',
    )
    reward        = models.ForeignKey(
        RewardCatalog,
        on_delete=models.PROTECT,
        related_name='redemptions',
        verbose_name='المكافأة',
    )
    points_spent  = models.PositiveIntegerField(verbose_name='النقاط المستنفدة')
    status        = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='pending',
        db_index=True, verbose_name='الحالة',
    )
    notes         = models.TextField(blank=True)

    # Fulfilment link (e.g. the voucher generated)
    voucher       = models.ForeignKey(
        'vouchers.Voucher',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='loyalty_redemptions',
        verbose_name='القسيمة المُنشأة',
    )

    approved_by   = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_redemptions',
        verbose_name='اعتمد بواسطة',
    )
    approved_at   = models.DateTimeField(null=True, blank=True)
    fulfilled_at  = models.DateTimeField(null=True, blank=True)

    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'طلب استبدال'
        verbose_name_plural = 'طلبات الاستبدال'

    def __str__(self):
        return (
            f'{self.account.customer.name} ← {self.reward.name_ar or self.reward.name} '
            f'({self.points_spent} نقطة) — {self.get_status_display()}'
        )

    def approve(self, by_staff):
        self.status = 'approved'
        self.approved_by = by_staff
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        # Deduct points
        self.account.redeem_points(
            self.points_spent,
            reason=f'استبدال مكافأة: {self.reward.name_ar or self.reward.name}',
            reward=self.reward,
        )

    def reject(self, by_staff, reason=''):
        self.status = 'rejected'
        self.notes = reason
        self.approved_by = by_staff
        self.save(update_fields=['status', 'notes', 'approved_by', 'updated_at'])

    def fulfill(self, voucher=None):
        self.status = 'fulfilled'
        self.fulfilled_at = timezone.now()
        if voucher:
            self.voucher = voucher
        self.save(update_fields=['status', 'fulfilled_at', 'voucher', 'updated_at'])
        # Increment reward redemption counter
        RewardCatalog.objects.filter(pk=self.reward_id).update(
            redeemed_count=models.F('redeemed_count') + 1
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SoftechPointsLog — immutable audit trail for every SOFTECH procedure call
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class SoftechPointsLog(models.Model):
    """
    Immutable record of every EXEC sp_UpdatePICPoints call made from Django.
    One row per call — never updated or deleted.
    """

    customer     = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='softech_points_logs',
        verbose_name='العميل',
    )
    softech_pic  = models.CharField(max_length=30, db_index=True, verbose_name='PIC')

    delta        = models.IntegerField(verbose_name='تغيير النقاط',
                                       help_text='موجب = إضافة، سالب = خصم')
    reason       = models.CharField(max_length=255, blank=True, verbose_name='السبب')

    balance_before = models.IntegerField(default=0, verbose_name='الرصيد قبل')
    balance_after  = models.IntegerField(default=0, verbose_name='الرصيد بعد')

    success      = models.BooleanField(default=True, verbose_name='نجح')
    error_message = models.TextField(blank=True, verbose_name='رسالة الخطأ')

    created_by   = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='بواسطة',
    )
    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'سجل تعديل SOFTECH'
        verbose_name_plural = 'سجلات تعديل SOFTECH'
        indexes             = [models.Index(fields=['softech_pic', 'created_at'])]

    def __str__(self):
        sign = '+' if self.delta >= 0 else ''
        status = '✓' if self.success else '✗'
        return f'{status} {self.softech_pic} {sign}{self.delta} → {self.balance_after}'

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('SoftechPointsLog is immutable — cannot edit after creation')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('SoftechPointsLog is immutable — cannot delete')
