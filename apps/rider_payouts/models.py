"""
apps/rider_payouts/models.py — ride-level rider payout ledger (C22 / P-48).

An internal record and report of what each rider is owed: it moves no money, writes nothing to
SOFTECH, makes no cash entry and posts nothing to payroll. Cash collection (delivery.CashCollection,
DeliveryOrder.collected_amount) is a separate thing and is never read or changed here.

    RiderPayoutPeriod      one rider × branch × calendar month: the summary a manager finalizes
    RiderPayoutRide        one ledger row per completed ride (app-built from a delivered order, or
                           entered by the branch at shift end); amounts from apps/rider_payouts/rule.py
    RiderPayoutAdjustment  an extra or a deduction on a period, always with a reason
    RiderPayoutAuditEvent  who / what / when / why / before-after for every finalize, unlock,
                           adjustment, ride entry / void and ledger build (append-only)

A finalized period is locked: no recalculation, ride or adjustment touches it until an admin
unlocks it with a reason (the D-16 pattern of apps/incentives).
"""
from decimal import Decimal

from django.db import models


class RiderPayoutPeriod(models.Model):
    driver = models.ForeignKey('delivery.DeliveryDriver', on_delete=models.PROTECT,
                               related_name='payout_periods', verbose_name='الطيار')
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT,
                               related_name='rider_payout_periods', verbose_name='الفرع')
    month = models.DateField(verbose_name='الشهر', help_text='أول يوم في الشهر')

    rides_count = models.PositiveIntegerField(default=0, verbose_name='عدد الرحلات')
    deliveries_count = models.PositiveIntegerField(default=0, verbose_name='عدد التوصيلات')
    days_count = models.PositiveIntegerField(default=0, verbose_name='أيام العمل')
    distance_km = models.DecimalField(max_digits=9, decimal_places=2, default=Decimal('0'),
                                      verbose_name='المسافة (كم)')
    rides_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'),
                                       verbose_name='أجر الرحلات')
    minimum_topup = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'),
                                        verbose_name='استكمال الحد الأدنى اليومي')
    adjustments_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'),
                                            verbose_name='الإضافات والخصومات')
    total_payout = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0'),
                                       verbose_name='الإجمالي المستحق')
    rule = models.JSONField(default=dict, blank=True, verbose_name='أرقام القاعدة المستخدمة')
    recalculated_at = models.DateTimeField(null=True, blank=True, verbose_name='آخر احتساب')

    is_finalized = models.BooleanField(default=False, db_index=True, verbose_name='مُعتمد')
    finalized_at = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الاعتماد')
    finalized_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='+', verbose_name='اعتمد بواسطة')
    finalize_reason = models.TextField(blank=True, verbose_name='ملاحظة الاعتماد')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'فترة أجور طيار'
        verbose_name_plural = 'فترات أجور الطيارين'
        ordering = ['-month', 'branch_id', 'driver_id']
        constraints = [
            models.UniqueConstraint(fields=['driver', 'branch', 'month'], name='rider_payout_period_uniq'),
        ]
        indexes = [models.Index(fields=['branch', 'month'], name='rider_payout_period_bm')]

    def __str__(self):
        return f'{self.driver_id} / {self.branch_id} / {self.month:%Y-%m}'


class RiderPayoutRide(models.Model):
    SOURCE_APP = 'app'
    SOURCE_BRANCH = 'branch'
    SOURCE_CHOICES = [
        (SOURCE_APP, 'من طلب توصيل مُسلَّم'),
        (SOURCE_BRANCH, 'إدخال الفرع'),
    ]

    period = models.ForeignKey(RiderPayoutPeriod, on_delete=models.PROTECT, related_name='rides',
                               verbose_name='الفترة')
    driver = models.ForeignKey('delivery.DeliveryDriver', on_delete=models.PROTECT,
                               related_name='payout_rides', verbose_name='الطيار')
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT,
                               related_name='rider_payout_rides', verbose_name='الفرع')
    ride_date = models.DateField(db_index=True, verbose_name='التاريخ')
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, verbose_name='المصدر')
    # App-built rides: one per delivered order, ever (the build is idempotent on this key).
    order = models.OneToOneField('delivery.DeliveryOrder', on_delete=models.PROTECT, null=True, blank=True,
                                 related_name='payout_ride', verbose_name='طلب التوصيل')
    # Branch entries: the order / invoice numbers the cashier wrote for the ride.
    order_refs = models.CharField(max_length=500, blank=True, verbose_name='الطلبات')
    deliveries = models.PositiveSmallIntegerField(default=1, verbose_name='عدد التوصيلات')
    distance_km = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True,
                                      verbose_name='المسافة (كم)')
    zone = models.CharField(max_length=200, blank=True, verbose_name='المنطقة')
    flat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'),
                                      verbose_name='الأجر الثابت')
    distance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'),
                                          verbose_name='أجر المسافة')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0'), verbose_name='أجر الرحلة')
    note = models.CharField(max_length=500, blank=True, verbose_name='ملاحظة')
    # A double-click / retry of the same branch entry sends the same key (a UUID) → one row.
    client_ref = models.UUIDField(null=True, blank=True, unique=True)

    is_void = models.BooleanField(default=False, db_index=True, verbose_name='ملغاة')
    void_reason = models.TextField(blank=True, verbose_name='سبب الإلغاء')
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='+')

    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', verbose_name='سجّل بواسطة')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'رحلة طيار'
        verbose_name_plural = 'رحلات الطيارين'
        ordering = ['-ride_date', '-id']
        indexes = [models.Index(fields=['branch', 'ride_date'], name='rider_payout_ride_bd'),
                   models.Index(fields=['driver', 'ride_date'], name='rider_payout_ride_dd')]

    def __str__(self):
        return f'{self.driver_id} {self.ride_date} {self.amount}'


class RiderPayoutAdjustment(models.Model):
    period = models.ForeignKey(RiderPayoutPeriod, on_delete=models.PROTECT, related_name='adjustments',
                               verbose_name='الفترة')
    adj_date = models.DateField(verbose_name='التاريخ')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='المبلغ (+ إضافة / - خصم)')
    reason = models.TextField(verbose_name='السبب')
    is_removed = models.BooleanField(default=False, db_index=True)
    removed_reason = models.TextField(blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'إضافة / خصم أجر طيار'
        verbose_name_plural = 'إضافات وخصومات أجور الطيارين'
        ordering = ['adj_date', 'id']


class RiderPayoutAuditEvent(models.Model):
    """Append-only. Protected from its period, ride and adjustment."""
    ACTION_CHOICES = [
        ('ledger_built', 'بناء السجل من طلبات التوصيل'),
        ('ride_added', 'إضافة رحلة'),
        ('ride_voided', 'إلغاء رحلة'),
        ('adjustment_added', 'إضافة / خصم'),
        ('adjustment_removed', 'حذف إضافة / خصم'),
        ('period_finalized', 'اعتماد فترة'),
        ('period_unlocked', 'فتح اعتماد فترة'),
    ]

    action = models.CharField(max_length=30, choices=ACTION_CHOICES, db_index=True, verbose_name='الإجراء')
    period = models.ForeignKey(RiderPayoutPeriod, on_delete=models.PROTECT, null=True, blank=True,
                               related_name='audit_events', verbose_name='الفترة')
    ride = models.ForeignKey(RiderPayoutRide, on_delete=models.PROTECT, null=True, blank=True,
                             related_name='audit_events')
    adjustment = models.ForeignKey(RiderPayoutAdjustment, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='audit_events')
    actor = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='+', verbose_name='بواسطة')
    actor_name = models.CharField(max_length=150, blank=True, verbose_name='اسم المنفذ')
    reason = models.TextField(blank=True, verbose_name='السبب')
    before = models.JSONField(default=dict, blank=True, verbose_name='قبل')
    after = models.JSONField(default=dict, blank=True, verbose_name='بعد')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'سجل تدقيق أجور الطيارين'
        verbose_name_plural = 'سجلات تدقيق أجور الطيارين'
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.action} — {self.period_id} ({self.actor_name or "system"})'
