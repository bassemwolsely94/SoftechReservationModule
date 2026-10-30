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
