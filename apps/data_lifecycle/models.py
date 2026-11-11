"""
apps/data_lifecycle/models.py

Data lifecycle (design docs/superpowers/specs/2026-11-07-data-lifecycle-design.md).

Company-level by nature: nothing here belongs to one branch, so none of it goes through
core/branch_scope. Who may see it (§7): admin everything; supervisor and quality manager the Growth and
Problems views only; rule changes, restore and held-file view are admin only, checked on the server.
No SOFTECH reads or writes. Held prescriptions are never reachable by URL.

HeldFile is deliberately not registered in Django admin: its rows name prescription files.
"""
from django.db import models
from django.utils import timezone

MODE_OFF = 'off'
MODE_PREVIEW = 'preview'
MODE_ON = 'on'
MODE_CHOICES = [(MODE_OFF, 'متوقفة'), (MODE_PREVIEW, 'معاينة'), (MODE_ON, 'تعمل')]


class LifecycleRulePolicy(models.Model):
    """The admin's choice for one rule. No row = the register's defaults. Written only by policy.set_policy."""
    rule_key = models.CharField(max_length=40, unique=True)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_PREVIEW)
    keep_days_override = models.PositiveIntegerField(null=True, blank=True)
    changed_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    changed_at = models.DateTimeField(auto_now=True)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ['rule_key']
        verbose_name = 'سياسة قاعدة'
        verbose_name_plural = 'سياسات القواعد'

    def __str__(self):
        return f'{self.rule_key}: {self.mode}'


class LifecycleRun(models.Model):
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    is_preview = models.BooleanField(default=False)
    sync_run = models.ForeignKey('sync.SyncRun', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'تشغيل قواعد'
        verbose_name_plural = 'تشغيلات القواعد'

    def __str__(self):
        return f'{"preview" if self.is_preview else "real"} {self.started_at:%Y-%m-%d %H:%M}'


class LifecycleRunLine(models.Model):
    """One rule in one run. `count` is rows for a row rule and files for a file rule.
    `is_preview` is per line: a real run still only previews the rules that are in preview mode."""
    run = models.ForeignKey(LifecycleRun, on_delete=models.CASCADE, related_name='lines')
    rule_key = models.CharField(max_length=40)
    count = models.BigIntegerField(default=0)
    bytes = models.BigIntegerField(default=0)
    skipped_shared = models.IntegerField(default=0)
    stopped_by_breaker = models.BooleanField(default=False)
    error = models.TextField(blank=True)
    is_preview = models.BooleanField(default=False)

    class Meta:
        ordering = ['rule_key']
        indexes = [models.Index(fields=['rule_key', 'is_preview'])]
        verbose_name = 'نتيجة قاعدة'
        verbose_name_plural = 'نتائج القواعد'

    def __str__(self):
        return f'{self.rule_key}: {self.count}'


class HeldFile(models.Model):
    """A file in the holding folder. Outlives the row it came from.

    `rows` lists every reference that was cleared as {model, pk, field, value}, because one file can
    have several rows. primary_* is the first of them, indexed so a screen can find the held file of a
    record. All blank when no record used the file (rule `unreferenced`). For a staff deletion or replacement
    `rows` is empty (nothing is left to clear) and primary_* says which record the file came from."""
    original_path = models.CharField(max_length=500)
    hold_path = models.CharField(max_length=500)
    rule_key = models.CharField(max_length=40, db_index=True)
    size = models.BigIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    moved_at = models.DateTimeField(default=timezone.now)
    purge_after = models.DateTimeField(db_index=True)
    restored_at = models.DateTimeField(null=True, blank=True)
    restored_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    purged_at = models.DateTimeField(null=True, blank=True)
    # Who deleted the record or replaced the file (rule_key record_deleted / file_replaced). Null for a rule's
    # own hold and for a change made outside a request.
    deleted_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    primary_model = models.CharField(max_length=100, blank=True)
    primary_pk = models.CharField(max_length=64, blank=True)
    primary_field = models.CharField(max_length=100, blank=True)
    rows = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-moved_at']
        indexes = [models.Index(fields=['primary_model', 'primary_pk', 'primary_field'])]
        verbose_name = 'ملف محجوز'
        verbose_name_plural = 'الملفات المحجوزة'

    def __str__(self):
        return f'{self.rule_key} #{self.pk}'


class ObsoleteItemSeen(models.Model):
    """The mirrored item has no date for when it became obsolete, so this records when we first saw it.
    Never changes the item itself."""
    item = models.OneToOneField('catalog.Item', on_delete=models.CASCADE, related_name='+')
    first_seen_at = models.DateTimeField(default=timezone.now)
    cleared_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'صنف متوقف'
        verbose_name_plural = 'الأصناف المتوقفة'

    def __str__(self):
        return f'item {self.item_id}'


class UnreferencedFileSeen(models.Model):
    """A file under media/ that no record used, for the "2 scans 30 days apart" rule."""
    path = models.CharField(max_length=500, unique=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'ملف بلا سجل'
        verbose_name_plural = 'ملفات بلا سجل'

    def __str__(self):
        return self.path


class TableSizeSnapshot(models.Model):
    """Daily table sizes, shipped early so growth history exists before the data health screen (§6 Stage 5)."""
    taken_at = models.DateTimeField(default=timezone.now, db_index=True)
    table = models.CharField(max_length=128)
    total_bytes = models.BigIntegerField(default=0)
    heap_bytes = models.BigIntegerField(default=0)
    index_bytes = models.BigIntegerField(default=0)
    row_estimate = models.BigIntegerField(default=0)

    class Meta:
        ordering = ['-taken_at']
        indexes = [models.Index(fields=['table', 'taken_at'])]
        verbose_name = 'حجم جدول'
        verbose_name_plural = 'أحجام الجداول'

    def __str__(self):
        return f'{self.table} {self.taken_at:%Y-%m-%d}'
