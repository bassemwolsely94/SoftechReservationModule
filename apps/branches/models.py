"""
apps/branches/models.py

Branch         — physical pharmacy branch.
BranchSettings — per-branch feature flags and notification gate.
"""
from django.db import models


class BranchQuerySet(models.QuerySet):
    def operational(self):
        """The live network nodes: HQ + retail branches (excludes closed/CC)."""
        return self.filter(kind__in=[Branch.KIND_HQ, Branch.KIND_RETAIL])

    def retail(self):
        return self.filter(kind=Branch.KIND_RETAIL)

    def pos_enabled_branches(self):
        return self.filter(pos_enabled=True)

    def with_local_db(self):
        """Branches that have their own reachable Sybase server."""
        return self.exclude(db_host='').exclude(db_host__isnull=True)


class Branch(models.Model):
    # ── Classification (authoritative operational status) ──────────────────────
    # is_active is NOT reliable — the SOFTECH branches table has no active flag, so
    # sync imports every row as active. `kind` is the curated truth used for
    # operational logic (health probes, POS gating, pickers). Closed branches keep
    # is_active=True so their HISTORICAL data stays attributed in analytics.
    KIND_HQ          = 'hq'
    KIND_RETAIL      = 'retail'
    KIND_CALL_CENTER = 'call_center'
    KIND_CLOSED      = 'closed'
    KIND_CHOICES = [
        (KIND_HQ,          'المركز الرئيسي'),
        (KIND_RETAIL,      'فرع بيع'),
        (KIND_CALL_CENTER, 'كول سنتر'),
        (KIND_CLOSED,      'مُغلق / لاغى'),
    ]
    kind = models.CharField(
        max_length=20, choices=KIND_CHOICES, default=KIND_RETAIL, db_index=True,
        verbose_name='نوع النقطة',
        help_text='التصنيف التشغيلي الموثوق — يُستخدم لفحص الاتصال وتفعيل نقاط البيع والقوائم',
    )
    # POS module: only branches explicitly enabled accept indirect-POS orders.
    pos_enabled = models.BooleanField(
        default=False, verbose_name='مفعّل لنقطة البيع',
        help_text='يسمح بإنشاء أوامر بيع POS غير مباشرة لهذا الفرع',
    )

    softech_branch_id = models.CharField(max_length=10, unique=True)
    code              = models.CharField(max_length=10, blank=True)
    name              = models.CharField(max_length=255)
    name_ar           = models.CharField(max_length=255, blank=True)
    address           = models.TextField(blank=True)
    phone             = models.CharField(max_length=50, blank=True)

    # ── Geolocation (used for delivery pickup geofencing) ──────────────────────
    latitude  = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
                                    verbose_name='خط العرض')
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True,
                                    verbose_name='خط الطول')

    # ── Branch database connection ─────────────────────────────────────────────
    # Each branch runs its own SOFTECH Sybase instance.
    # db_host = IP of the branch server (e.g. '192.168.1.5' for branch 160).
    # Leave blank if the branch uses HQ data only (no local DB).
    db_host = models.CharField(
        max_length=50, blank=True,
        verbose_name='IP قاعدة البيانات',
        help_text='عنوان IP لخادم Sybase الخاص بالفرع — مثال: 192.168.1.5',
    )
    db_port = models.PositiveIntegerField(
        default=5000,
        verbose_name='منفذ قاعدة البيانات',
        help_text='منفذ jConnect Sybase (افتراضي 5000)',
    )
    db_name = models.CharField(
        max_length=50, default='SOFTECHDB9', blank=True,
        verbose_name='اسم قاعدة البيانات',
        help_text='اسم قاعدة بيانات SOFTECH (افتراضي SOFTECHDB9)',
    )

    # is_active = False  → branch closed; NO new transactions; historical data visible
    is_active = models.BooleanField(default=True, verbose_name='نشط')

    # is_operational = False → temporarily suspended (maintenance, stockcount …)
    is_operational = models.BooleanField(
        default=True,
        verbose_name='قيد التشغيل',
        help_text='إيقاف مؤقت — لا يمكن إنشاء معاملات جديدة لكن البيانات التاريخية تبقى متاحة',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = BranchQuerySet.as_manager()

    class Meta:
        verbose_name        = 'فرع'
        verbose_name_plural = 'الفروع'
        ordering            = ['name']

    def __str__(self):
        return self.name_ar or self.name

    @property
    def is_hq(self):
        return self.kind == self.KIND_HQ

    @property
    def can_transact(self):
        """True only when the branch is both active AND operational."""
        return self.is_active and self.is_operational

    @property
    def effective_db_host(self):
        """SOFTECH DB host to actually connect to. HQ (softech_branch_id '100') and any branch
        with no own db_host fall back to the central settings.SYBASE_HOST — the same convention
        apps/sync uses (network_health.py). Without this, HQ reads/writes have no host and fail."""
        from django.conf import settings
        return (self.db_host or '').strip() or settings.SYBASE_HOST

    @property
    def effective_db_port(self):
        from django.conf import settings
        return self.db_port or getattr(settings, 'SYBASE_PORT', 5000) or 5000

    @property
    def display_name(self):
        return self.name_ar or self.name


class BranchSettings(models.Model):
    """
    Per-branch feature flags and notification gate.
    Created lazily via BranchSettings.for_branch(branch).
    """
    branch = models.OneToOneField(
        Branch, on_delete=models.CASCADE,
        related_name='settings', verbose_name='الفرع',
    )

    # ── Feature toggles ───────────────────────────────────────────────────────
    allow_reservations    = models.BooleanField(default=True, verbose_name='الحجوزات')
    allow_transfers       = models.BooleanField(default=True, verbose_name='التحويلات')
    allow_vouchers        = models.BooleanField(default=True, verbose_name='القسائم')
    allow_stockcount      = models.BooleanField(default=True, verbose_name='الجرد')
    allow_shortage        = models.BooleanField(default=True, verbose_name='قائمة النواقص')

    # ── Notification gate — admin can silence an entire branch ─────────────────
    notifications_enabled = models.BooleanField(
        default=True,
        verbose_name='تفعيل الإشعارات',
        help_text='إلغاء التفعيل يوقف جميع إشعارات الفرع',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'إعدادات الفرع'
        verbose_name_plural = 'إعدادات الفروع'

    def __str__(self):
        return f'إعدادات {self.branch}'

    @classmethod
    def for_branch(cls, branch):
        """Get or create settings for a branch (safe lazy initialisation)."""
        obj, _ = cls.objects.get_or_create(branch=branch)
        return obj
