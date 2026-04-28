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
