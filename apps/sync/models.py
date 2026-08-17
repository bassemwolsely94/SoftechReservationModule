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
