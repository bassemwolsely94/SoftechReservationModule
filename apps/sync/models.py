from django.db import models
from django.utils import timezone


class SyncRun(models.Model):
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    records_synced = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    # Live phase/message for on-demand runs (e.g. items sync toast). Shape:
    # {'phase': 'items', 'message': '...', 'done': int, 'total': int}. Optional —
    # scheduled lanes leave it empty.
    progress = models.JSONField(default=dict, blank=True)
    # Which job produced the run ('fast' | 'slow' | 'full' | 'items' | 'retention' |
    # 'morning_chain' | …; blank on rows written before P-56) and whether a person
    # started it from /sync. A scheduled lane skips its tick while a manual run of
    # the same lane is in flight.
    lane = models.CharField(max_length=30, blank=True, default='', db_index=True)
    manual = models.BooleanField(default=False)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        duration = ''
        if self.completed_at:
            secs = (self.completed_at - self.started_at).seconds
            duration = f' ({secs}s)'
        return f"Sync {self.started_at:%Y-%m-%d %H:%M} — {self.status}{duration}"

    @property
    def duration_seconds(self):
        if self.completed_at:
            return (self.completed_at - self.started_at).seconds
        return None


class SyncLog(models.Model):
    sync_run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name='logs')
    table_name = models.CharField(max_length=100)
    records_processed = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.table_name}: {self.records_processed} records"


# ─────────────────────────────────────────────────────────────────────────────
# SOFTECH master-data label caches
# Populated on every sync run from persontypes / persontypesclassif.
# Used by analytics filter_options so labels are available even before a full
# customer re-sync populates Customer.person_classif_label.
# ─────────────────────────────────────────────────────────────────────────────

class SoftechPersonType(models.Model):
    """Cache of SOFTECHDB9.dbo.persontypes — ptcode → Arabic label."""
    ptcode   = models.CharField(max_length=10, unique=True, db_index=True,
                                verbose_name='كود نوع الشخص')
    ptdescr  = models.CharField(max_length=150, blank=True,
                                verbose_name='وصف نوع الشخص (عربي)')
    ptedescr = models.CharField(max_length=150, blank=True,
                                verbose_name='وصف نوع الشخص (إنجليزي)')

    class Meta:
        verbose_name        = 'نوع الشخص (SOFTECH)'
        verbose_name_plural = 'أنواع الأشخاص (SOFTECH)'
        ordering            = ['ptcode']

    def __str__(self):
        return f'{self.ptcode} — {self.ptdescr or self.ptedescr}'


class SoftechPersonClassif(models.Model):
    """
    Cache of SOFTECHDB9.dbo.persontypesclassif.
    (ptcode, ptclassifcode) → ptclassifdescr (Arabic channel/classification label).

    Example rows:
      ('01', '846') → 'عميل نقدي'
      ('01', '341') → 'معاقدات / آجل'
      ('01', '492') → 'عميل Delivery'
    """
    ptcode         = models.CharField(max_length=10, db_index=True,
                                      verbose_name='كود نوع الشخص')
    ptclassifcode  = models.CharField(max_length=10, db_index=True,
                                      verbose_name='كود التصنيف')
    ptclassifdescr = models.CharField(max_length=150, blank=True,
                                      verbose_name='وصف التصنيف (عربي)')

    class Meta:
        unique_together     = [('ptcode', 'ptclassifcode')]
        verbose_name        = 'تصنيف نوع الشخص (SOFTECH)'
        verbose_name_plural = 'تصنيفات أنواع الأشخاص (SOFTECH)'
        ordering            = ['ptclassifcode']

    def __str__(self):
        return f'{self.ptclassifcode} — {self.ptclassifdescr}'


class SoftechLoadStat(models.Model):
    """Hourly roll-up of what the platform asks of SOFTECH (doc 30, step 1.0).

    One row per (hour, node, scope, caller). Filled from an in-memory buffer by
    apps.sync.softech_load — never one write per query. `scope` is the scheduled job,
    management command or 'web'; `caller` is the first apps/ function on the stack.
    """
    hour        = models.DateTimeField(db_index=True, verbose_name='الساعة')
    node        = models.CharField(max_length=64, verbose_name='السيرفر')
    scope       = models.CharField(max_length=80, verbose_name='المهمة / المصدر')
    caller      = models.CharField(max_length=200, verbose_name='الكود المستدعي')
    connects         = models.PositiveIntegerField(default=0, verbose_name='اتصالات')
    connect_failures = models.PositiveIntegerField(default=0, verbose_name='اتصالات فاشلة')
    connect_ms       = models.BigIntegerField(default=0, verbose_name='زمن الاتصال (مللي)')
    queries          = models.PositiveIntegerField(default=0, verbose_name='استعلامات')
    query_errors     = models.PositiveIntegerField(default=0, verbose_name='استعلامات فاشلة')
    query_ms         = models.BigIntegerField(default=0, verbose_name='زمن الاستعلامات (مللي)')
    max_query_ms     = models.PositiveIntegerField(default=0, verbose_name='أبطأ استعلام (مللي)')
    rows             = models.BigIntegerField(default=0, verbose_name='صفوف مسحوبة')

    class Meta:
        verbose_name = 'حمل SOFTECH (ساعي)'
        verbose_name_plural = 'حمل SOFTECH (ساعي)'
        constraints = [models.UniqueConstraint(fields=['hour', 'node', 'scope', 'caller'],
                                               name='uniq_softech_load_bucket')]
        ordering = ['-hour']

    def __str__(self):
        return f'{self.hour:%Y-%m-%d %H}h {self.scope} {self.caller}'


class SlowRequest(models.Model):
    """One API request slower than settings.SLOW_REQUEST_MS (default 1000), written by
    apps.sync.middleware.SlowRequestMiddleware. `path` is the URL ROUTE pattern
    (e.g. api/transits/<int:pk>/), never the raw URL with ids or query strings.
    Kept 30 days (apps.sync.maintenance). Feeds the /sync slow-endpoint report (P-56)."""
    at          = models.DateTimeField(auto_now_add=True, db_index=True)
    path        = models.CharField(max_length=255, db_index=True)
    method      = models.CharField(max_length=8)
    status_code = models.PositiveSmallIntegerField()
    duration_ms = models.PositiveIntegerField()
    role        = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ['-at']

    def __str__(self):
        return f'{self.method} {self.path} {self.duration_ms}ms'


class SyncWatermark(models.Model):
    """How far a SOFTECH table has been read (doc 40 §3.1). One row per stream, e.g. `stkbal`.

    `value_ts` is a SOFTECH-side stamp taken from the rows' own column (never our clock), stored as an
    aware Cairo time. It only moves forward; reads use it minus an overlap. Ignored while the stream's
    switch (SYNC_DELTA_*) is `off`."""
    stream = models.CharField(max_length=60, unique=True, verbose_name='المصدر')
    value_ts = models.DateTimeField(null=True, blank=True, verbose_name='آخر ختم مقروء')
    value_num = models.BigIntegerField(null=True, blank=True, verbose_name='آخر رقم مقروء')
    mode = models.CharField(max_length=10, default='off', verbose_name='الوضع')
    last_delta_at = models.DateTimeField(null=True, blank=True, verbose_name='آخر قراءة للتغيّرات')
    last_full_at = models.DateTimeField(null=True, blank=True, verbose_name='آخر قراءة كاملة')
    last_full_ok = models.BooleanField(default=False, verbose_name='آخر قراءة كاملة سليمة')
    rows_last_delta = models.PositiveIntegerField(default=0, verbose_name='صفوف آخر قراءة للتغيّرات')
    misses_last_shadow = models.PositiveIntegerField(default=0, verbose_name='فوائت آخر مقارنة')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'علامة مزامنة سوفتك'
        verbose_name_plural = 'علامات مزامنة سوفتك'

    def __str__(self):
        return f'{self.stream} @ {self.value_ts} ({self.mode})'


class DeltaShadowRun(models.Model):
    """One SHADOW comparison (doc 40 §6.1): the full read still writes; the delta read is only compared.
    `missed` = keys that really changed this run but the delta read did not return; must stay 0 for the
    7 days before a stream may go ON (owner sign-off S2). Sample keys are SOFTECH codes only."""
    stream = models.CharField(max_length=60, db_index=True, verbose_name='المصدر')
    at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='الوقت')
    rows_full = models.PositiveIntegerField(default=0, verbose_name='صفوف القراءة الكاملة')
    rows_changed = models.PositiveIntegerField(default=0, verbose_name='صفوف تغيّرت فعلاً')
    rows_delta = models.PositiveIntegerField(default=0, verbose_name='صفوف قراءة التغيّرات')
    missed = models.PositiveIntegerField(default=0, verbose_name='فوائت')
    missed_new = models.PositiveIntegerField(default=0, verbose_name='صفوف جديدة لم تُقرأ')
    missed_sample = models.JSONField(default=list, blank=True, verbose_name='أمثلة')
    full_ms = models.PositiveIntegerField(default=0, verbose_name='زمن القراءة الكاملة (مللي)')
    delta_ms = models.PositiveIntegerField(default=0, verbose_name='زمن قراءة التغيّرات (مللي)')
    watermark_from = models.DateTimeField(null=True, blank=True)
    watermark_to = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True, default='', verbose_name='ملاحظة')

    class Meta:
        ordering = ['-at']
        verbose_name = 'مقارنة قراءة التغيّرات'
        verbose_name_plural = 'مقارنات قراءة التغيّرات'

    def __str__(self):
        return f'{self.stream} {self.at:%Y-%m-%d %H:%M} missed={self.missed}'


class StockFullCheck(models.Model):
    """One FULL stock read while the delta switch is `on` (doc 40 §3.3): the daily safety net (first fast run after
    04:00), a manual / full-lane run, a first run without a watermark, or a fallback after a failed delta read.
    `corrected` + `zeroed` = rows the delta runs had left different from SOFTECH (0 on a clean day); per_branch
    breaks them down by SOFTECH branch code. This is the count-and-total check of doc 40 §6.2 for ON."""
    at = models.DateTimeField(default=timezone.now, db_index=True, verbose_name='الوقت')
    reason = models.CharField(max_length=20, blank=True, default='', verbose_name='السبب')
    rows_full = models.PositiveIntegerField(default=0, verbose_name='صفوف القراءة الكاملة')
    corrected = models.PositiveIntegerField(default=0, verbose_name='صفوف تم تصحيحها')
    zeroed = models.PositiveIntegerField(default=0, verbose_name='صفوف نفدت وتم تصفيرها')
    per_branch = models.JSONField(default=dict, blank=True, verbose_name='حسب الفرع')
    ok = models.BooleanField(default=True, verbose_name='سليمة')
    full_ms = models.PositiveIntegerField(default=0, verbose_name='الزمن (مللي)')
    note = models.CharField(max_length=200, blank=True, default='', verbose_name='ملاحظة')

    class Meta:
        ordering = ['-at']
        verbose_name = 'مطابقة مخزون كاملة'
        verbose_name_plural = 'مطابقات المخزون الكاملة'

    def __str__(self):
        return f'{self.at:%Y-%m-%d %H:%M} {self.reason} corrected={self.corrected} zeroed={self.zeroed}'
