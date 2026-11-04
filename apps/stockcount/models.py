"""
apps/stockcount/models.py  — v2

Complete rewrite replacing the simple line-based model with the
transaction-driven snapshot architecture.

Two models:
  StockCountSession  — one per count cycle (the "job")
  StockCountSnapshot — one IMMUTABLE row per item (expected_qty frozen at
                       snapshot time; counted_qty / difference filled on upload)
"""
from django.db import models


# ── Doccode reference ─────────────────────────────────────────────────────────
DOCCODE_LABELS = {
    '10':  'مشتريات من الموردين',
    '25':  'استلام تحويل وارد (فرع / مركز)',
    '50':  'تسوية زيادة جرد',
    '80':  'مبيعات حجوزات',
    '115': 'مبيعات',
    '120': 'مرتجعات للموردين',
    '125': 'تحويل صادر (إلى فرع / مركز)',
    '150': 'تسوية نقص جرد',
}

PRESET_DOCCODES = {
    'sold_today':       ['115', '80'],
    'returns_today':    ['120'],
    'received_hq':      ['25'],
    'purchased_today':  ['10'],
    'transferred_out':  ['125'],
}


class StockCountSession(models.Model):
    """One complete stock-count cycle: configure → snapshot → export → upload → variance."""

    STATUS_CHOICES = [
        ('draft',          'مسودة'),
        ('snapshot_taken', 'تم أخذ اللقطة'),
        ('exported',       'تم التصدير'),
        ('uploaded',       'تم رفع النتائج'),
        ('variance_ready', 'الفروق جاهزة'),
        ('closed',         'مغلق'),
    ]

    MODE_CHOICES = [
        ('transaction',  'مبني على الحركات'),
        ('full',         'جرد شامل'),
        ('filtered',     'جرد مفلتر'),
        # Physical near-expiry audit: item list comes from the batches
        # purchase-expiry engine (spawned session); stock is captured like a
        # filtered count, and counters also record the real shelf expiry.
        ('expiry_audit', 'جرد صلاحية (تدقيق مادي)'),
        # Small daily count (Project 2): one session per salesperson per branch per day.
        ('daily',        'جرد يومي'),
    ]

    # ── Identity ──────────────────────────────────────────────────────────────
    name   = models.CharField(max_length=200, verbose_name='اسم جلسة الجرد')
    mode   = models.CharField(max_length=20, choices=MODE_CHOICES,
                              default='transaction', verbose_name='النوع')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default='draft', verbose_name='الحالة')
    notes  = models.TextField(blank=True, verbose_name='ملاحظات')

    # ── Scope / filters ───────────────────────────────────────────────────────
    branch_code       = models.CharField(max_length=20, verbose_name='كود الفرع')
    date_from         = models.DateField(null=True, blank=True, verbose_name='من تاريخ')
    date_to           = models.DateField(null=True, blank=True, verbose_name='إلى تاريخ')
    doccodes          = models.JSONField(default=list, verbose_name='أكواد المستند')
    user_code_filter  = models.CharField(max_length=50, blank=True,
                                         verbose_name='فلتر كود المستخدم')
    category_filter   = models.CharField(max_length=50, blank=True,
                                         verbose_name='فلتر التصنيف')
    item_codes_filter = models.JSONField(default=list,
                                         verbose_name='قائمة أصناف محددة')

    # ── Daily count (mode='daily') ────────────────────────────────────────────
    assigned_to = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='daily_count_sessions', verbose_name='المكلّف بالجرد',
    )
    count_date  = models.DateField(null=True, blank=True, db_index=True, verbose_name='يوم الجرد')

    # ── Aggregated counters (updated on upload) ───────────────────────────────
    item_count    = models.IntegerField(default=0, verbose_name='عدد الأصناف')
    surplus_count = models.IntegerField(default=0, verbose_name='عدد الزيادات')
    deficit_count = models.IntegerField(default=0, verbose_name='عدد النواقص')
    ok_count      = models.IntegerField(default=0, verbose_name='عدد المطابقات')

    # ── Audit / ownership ─────────────────────────────────────────────────────
    created_by  = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True,
        related_name='sc_sessions_created', verbose_name='أُنشئت بواسطة',
    )
    snapshot_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sc_sessions_snapshot', verbose_name='تم اللقطة بواسطة',
    )
    uploaded_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='sc_sessions_uploaded', verbose_name='رُفع بواسطة',
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at  = models.DateTimeField(auto_now_add=True)
    snapshot_at = models.DateTimeField(null=True, blank=True)
    exported_at = models.DateTimeField(null=True, blank=True)
    uploaded_at = models.DateTimeField(null=True, blank=True)
    variance_at = models.DateTimeField(null=True, blank=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'جلسة جرد'
        verbose_name_plural = 'جلسات الجرد'
        ordering            = ['-created_at']
        indexes = [
            models.Index(fields=['branch_code', 'status'],
                         name='sc_session_branch_status_idx'),
            models.Index(fields=['created_at'],
                         name='sc_session_created_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['assigned_to', 'count_date', 'branch_code'],
                condition=models.Q(mode='daily'),
                name='uniq_daily_count_per_person_day',
            ),
        ]

    def __str__(self):
        return f'{self.name} — {self.branch_code} ({self.get_status_display()})'


class StockCountSnapshot(models.Model):
    """
    IMMUTABLE per-item expected quantity record.

    Rules:
      • expected_qty is set at snapshot time and never modified afterwards.
      • counted_qty is NULL until the user uploads the count sheet.
      • difference = counted_qty − expected_qty  (computed on upload).
      • variance_type:  '' → not yet counted | 'ok' | 'surplus' | 'deficit'
    """
    VARIANCE_CHOICES = [
        ('',        'لم يُجرَد بعد'),
        ('ok',      'مطابق'),
        ('surplus', 'زيادة'),
        ('deficit', 'نقص'),
    ]

    session       = models.ForeignKey(
        StockCountSession, on_delete=models.CASCADE,
        related_name='snapshots', verbose_name='الجلسة',
    )
    item_code     = models.CharField(max_length=20, db_index=True,
                                     verbose_name='كود الصنف')
    item_name     = models.CharField(max_length=255, verbose_name='اسم الصنف')
    item_medicine = models.CharField(max_length=10, blank=True,
                                     verbose_name='تصنيف الدواء (itemmedicine)')
    category_name = models.CharField(max_length=255, blank=True,
                                     verbose_name='التصنيف')
    branch_code   = models.CharField(max_length=20, verbose_name='كود الفرع')

    # ── Immutable ─────────────────────────────────────────────────────────────
    expected_qty  = models.DecimalField(max_digits=12, decimal_places=3,
                                        verbose_name='الكمية المتوقعة')
    snapshot_time = models.DateTimeField(auto_now_add=True,
                                         verbose_name='وقت أخذ اللقطة')

    # ── Result (populated on upload) ──────────────────────────────────────────
    counted_qty   = models.DecimalField(max_digits=12, decimal_places=3,
                                        null=True, blank=True,
                                        verbose_name='الكمية المعدودة')
    difference    = models.DecimalField(max_digits=12, decimal_places=3,
                                        null=True, blank=True,
                                        verbose_name='الفارق')
    variance_type = models.CharField(max_length=10, choices=VARIANCE_CHOICES,
                                     blank=True, default='',
                                     verbose_name='نوع الانحراف')

    # ── Expiry audit (expiry_audit mode) ──────────────────────────────────────
    # entered_expiry_hint: earliest expiry keyed on the historical purchase
    #   entries that flagged this item (context only — NOT trusted as truth).
    # physical_expiry: the REAL shelf expiry the counter records during the
    #   physical check. This is the source of truth for the audit.
    entered_expiry_hint = models.DateField(
        null=True, blank=True, verbose_name='الصلاحية المُدخَلة (استرشادي)')
    physical_expiry     = models.DateField(
        null=True, blank=True, verbose_name='الصلاحية الفعلية على الرف')

    class Meta:
        verbose_name        = 'لقطة جرد'
        verbose_name_plural = 'لقطات الجرد'
        unique_together     = [('session', 'item_code')]
        ordering            = ['item_name']
        indexes = [
            models.Index(fields=['session', 'variance_type'],
                         name='sc_snap_variance_idx'),
            models.Index(fields=['session', 'item_code'],
                         name='sc_snap_item_idx'),
        ]

    def __str__(self):
        return (f'Session {self.session_id} / {self.item_code} '
                f'exp={self.expected_qty} cnt={self.counted_qty}')


# ── Daily counts (جرد يومي) — Project 2, design 2026-11-03 ─────────────────────
# One StockCountSession (mode='daily') per salesperson per branch per day. Each assigned item is a
# DailyCountPick; every submission is an immutable DailyCountAttempt (expected read at that moment).
# The session's StockCountSnapshot row mirrors the LATEST attempt so the variance screens and the
# stock-audit "adjustment after count" check keep working. Counts never write to SOFTECH.

class DailyCountPick(models.Model):
    ST_PENDING   = 'pending'
    ST_COUNTED   = 'counted'
    ST_RECOUNT   = 'recount'
    ST_ACCEPTED  = 'accepted'
    ST_ESCALATED = 'escalated'
    ST_MISSED    = 'missed'
    STATUS_CHOICES = [
        (ST_PENDING,   'لم يُجرد'),
        (ST_COUNTED,   'تم الجرد'),
        (ST_RECOUNT,   'مطلوب إعادة جرد'),
        (ST_ACCEPTED,  'تم الاعتماد'),
        (ST_ESCALATED, 'مُحال للمراجع'),
        (ST_MISSED,    'لم يُنجز'),
    ]

    session   = models.ForeignKey(StockCountSession, on_delete=models.CASCADE, related_name='daily_picks')
    item_code = models.CharField(max_length=20, verbose_name='كود الصنف')
    item_name = models.CharField(max_length=255, verbose_name='اسم الصنف')
    reasons   = models.JSONField(default=list, verbose_name='أسباب الاختيار')
    weight    = models.DecimalField(max_digits=8, decimal_places=4, default=0, verbose_name='وزن الخطورة')
    ask_expiry = models.BooleanField(default=False, verbose_name='يُطلب تاريخ الصلاحية')
    status    = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ST_PENDING, db_index=True)

    latest_attempt = models.ForeignKey('DailyCountAttempt', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+')
    # a recount can be handed to another salesperson at the branch (still blind)
    recount_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='daily_count_recounts')

    escalated         = models.BooleanField(default=False, verbose_name='مُحال للمراجع')
    escalation_reason = models.CharField(max_length=255, blank=True)
    review_reason = models.CharField(max_length=40, blank=True, verbose_name='سبب الفرق')
    review_note   = models.TextField(blank=True)
    needs_softech_adjustment = models.BooleanField(default=False, verbose_name='يحتاج تسوية في SOFTECH')
    reviewed_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'صنف جرد يومي'
        verbose_name_plural = 'أصناف الجرد اليومي'
        ordering = ['item_name']
        constraints = [models.UniqueConstraint(fields=['session', 'item_code'], name='uniq_daily_pick_item')]


class DailyCountAttempt(models.Model):
    """IMMUTABLE — one row per count submission (first count or recount). Never updated."""
    SRC_LIVE   = 'live'
    SRC_MIRROR = 'mirror'
    SOURCE_CHOICES = [(SRC_LIVE, 'SOFTECH مباشرة'), (SRC_MIRROR, 'نسخة محلية')]

    pick        = models.ForeignKey(DailyCountPick, on_delete=models.CASCADE, related_name='attempts')
    counted_by  = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, related_name='+')
    counted_qty = models.DecimalField(max_digits=12, decimal_places=3)
    expected_qty = models.DecimalField(max_digits=12, decimal_places=3)
    expected_source  = models.CharField(max_length=6, choices=SOURCE_CHOICES)
    expected_read_at = models.DateTimeField()
    difference  = models.DecimalField(max_digits=12, decimal_places=3)
    value_egp   = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    physical_expiry = models.DateField(null=True, blank=True)
    client_token = models.CharField(max_length=64, null=True, blank=True, unique=True)
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'محاولة جرد يومي'
        verbose_name_plural = 'محاولات الجرد اليومي'
        ordering = ['-created_at']


class DailyCountSettings(models.Model):
    """Singleton (pk=1) — chain-wide rules for the daily counts. Edited by management."""
    items_per_person   = models.PositiveSmallIntegerField(default=20)
    include_pharmacists = models.BooleanField(default=False)
    job_hour           = models.PositiveSmallIntegerField(default=7)   # Cairo hour the lists appear
    rotation_days      = models.PositiveSmallIntegerField(default=14)
    expiry_days        = models.PositiveSmallIntegerField(default=90)
    adjust_window_days = models.PositiveSmallIntegerField(default=60)
    escalate_value_egp = models.DecimalField(max_digits=10, decimal_places=2, default=200)
    escalate_repeat_count = models.PositiveSmallIntegerField(default=3)
    escalate_repeat_days  = models.PositiveSmallIntegerField(default=30)
    match_tolerance    = models.DecimalField(max_digits=6, decimal_places=3, default=0,
                                             help_text='|difference| ≤ this (packs) counts as a match')
    w_value   = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    w_rate    = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    w_adjust  = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    w_finding = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    w_loss    = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    w_expiry  = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    w_never   = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إعدادات الجرد اليومي'
        verbose_name_plural = 'إعدادات الجرد اليومي'

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
