"""
apps/branches/models.py

Branch         — physical pharmacy branch.
BranchSettings — per-branch feature flags and notification gate.
"""
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models.signals import post_delete, post_save

_HQ_CODE_CACHE = None


class HQNotConfigured(ImproperlyConfigured):
    """No single Branch of kind hq. An ImproperlyConfigured, so existing handlers still catch
    it; the API answers it with a 503 (core.exceptions.api_exception_handler)."""


def hq_code():
    """softech_branch_id of the single kind='hq' row (cached per process; the cache is
    dropped whenever a Branch is saved or deleted). Raises unless exactly one exists."""
    global _HQ_CODE_CACHE
    if _HQ_CODE_CACHE is None:
        codes = list(Branch.objects.filter(kind=Branch.KIND_HQ)
                     .values_list('softech_branch_id', flat=True)[:2])
        if len(codes) != 1:
            raise HQNotConfigured(
                f'Expected exactly one Branch with kind=hq, found {len(codes)}.')
        _HQ_CODE_CACHE = codes[0]
    return _HQ_CODE_CACHE


def order_codes(codes):
    """Sort branch codes (softech_branch_id) by Branch.display_order, then numeric code;
    codes with no Branch row go last (numeric first, then text). Duplicates are kept."""
    codes = [str(c) for c in codes]
    orders = dict(Branch.objects.filter(softech_branch_id__in=set(codes))
                  .values_list('softech_branch_id', 'display_order'))

    def key(c):
        num = (0, int(c), '') if c.isdigit() else (1, 0, c)
        return (0, orders[c], *num) if c in orders else (1, 0, *num)
    return sorted(codes, key=key)


def _reset_hq_code_cache(sender=None, **kwargs):
    global _HQ_CODE_CACHE
    _HQ_CODE_CACHE = None


class BranchQuerySet(models.QuerySet):
    def live(self):
        """The live network nodes: HQ + retail branches (excludes closed/CC/pending)."""
        return self.filter(kind__in=[Branch.KIND_HQ, Branch.KIND_RETAIL])

    def operational(self):
        """Alias of live() kept for existing callers."""
        return self.live()

    def retail(self):
        return self.filter(kind=Branch.KIND_RETAIL)

    def closed(self):
        return self.filter(kind=Branch.KIND_CLOSED)

    def pending(self):
        return self.filter(kind=Branch.KIND_PENDING)

    def ordered(self):
        return self.order_by('display_order', 'softech_branch_id')

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
    KIND_PENDING     = 'pending'
    KIND_CHOICES = [
        (KIND_HQ,          'المركز الرئيسي'),
        (KIND_RETAIL,      'فرع بيع'),
        (KIND_CALL_CENTER, 'كول سنتر'),
        (KIND_CLOSED,      'مُغلق / لاغى'),
        (KIND_PENDING,     'جديد — بانتظار التصنيف'),
    ]
    kind = models.CharField(
        max_length=20, choices=KIND_CHOICES, default=KIND_RETAIL, db_index=True,
        verbose_name='نوع النقطة',
        help_text='التصنيف التشغيلي الموثوق — يُستخدم لفحص الاتصال وتفعيل نقاط البيع والقوائم',
    )
    display_order = models.PositiveIntegerField(
        default=100, db_default=100, db_index=True, verbose_name='ترتيب العرض')
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
        help_text='عنوان IP لسيرفر Sybase الخاص بالفرع — مثال: 192.168.1.5',
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
        ordering            = ['display_order', 'softech_branch_id']

    def __str__(self):
        return self.name_ar or self.name

    @property
    def is_hq(self):
        return self.kind == self.KIND_HQ

    @property
    def is_live(self):
        return self.kind in (self.KIND_HQ, self.KIND_RETAIL)

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


post_save.connect(_reset_hq_code_cache, sender=Branch, dispatch_uid='branch_hq_cache_save')
post_delete.connect(_reset_hq_code_cache, sender=Branch, dispatch_uid='branch_hq_cache_del')


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
    # Small daily counts (Project 2) — pilot switch per branch, needs DAILY_COUNT_ENABLED too.
    daily_count_enabled   = models.BooleanField(default=False, verbose_name='الجرد اليومي')

    # ── Notification gate — admin can silence an entire branch ─────────────────
    notifications_enabled = models.BooleanField(
        default=True,
        verbose_name='تفعيل الإشعارات',
        help_text='إلغاء التفعيل يوقف جميع إشعارات الفرع',
    )

    # ── Working hours (local time, every day) — see apps/branches/hours.py ─────
    # Used by the stock audit's after-hours check (doc 32, check 9). Our own setting;
    # SOFTECH has no branch hours, so this is never synced.
    is_24h        = models.BooleanField(default=False, verbose_name='يعمل 24 ساعة')
    working_hours = models.JSONField(default=list, blank=True, verbose_name='مواعيد العمل',
                                     help_text='[{"from": "08:00", "to": "01:00"}] — optional "label", "doccodes"')

    # Phone alerts: the branch's shared mobile that receives urgent WhatsApp alerts.
    alert_mobile  = models.CharField(max_length=20, blank=True, default='', verbose_name='موبايل تنبيهات الفرع')

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
