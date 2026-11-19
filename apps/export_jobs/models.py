"""
apps/export_jobs/models.py — one background export (performance Stage 4).

Generalised from PicExportJob (doc 33 §15): a file that takes longer than a web request should is
built by a job, the screen polls it and downloads it once. The bytes live in `data` (never under
/media); only the requester may read or download them. Jobs are deleted after 48 h; a job with no
progress for 15 min is reported failed (the process that ran it restarted). See runner.py.
"""
from django.db import models


class ExportJob(models.Model):
    QUEUED, RUNNING, DONE, FAILED = 'queued', 'running', 'done', 'failed'
    STATUS_CHOICES = [(QUEUED, 'في الانتظار'), (RUNNING, 'جارٍ الإنشاء'), (DONE, 'جاهز'), (FAILED, 'فشل')]
    ACTIVE = (QUEUED, RUNNING)

    kind = models.CharField(max_length=40)                       # registry.KINDS key
    requested_by = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT, related_name='+')
    params = models.JSONField(default=dict, blank=True)          # raw query params {key: [values]} or the JSON body
    meta = models.JSONField(default=dict, blank=True)            # effective filters (for the audit entry)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=QUEUED)
    progress_pct = models.PositiveSmallIntegerField(default=0)
    progress_msg = models.CharField(max_length=120, blank=True, default='')
    file_name = models.CharField(max_length=200, blank=True, default='')
    content_type = models.CharField(max_length=120, blank=True, default='')
    data = models.BinaryField(null=True, blank=True, editable=False)
    rows = models.JSONField(default=dict, blank=True)            # {sheet: rows written}
    error = models.CharField(max_length=255, blank=True, default='')
    worker = models.CharField(max_length=10, blank=True, default='')   # 'thread' | 'service'
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['requested_by', 'kind', '-created_at'], name='exportjob_user_kind'),
                   models.Index(fields=['status', 'created_at'], name='exportjob_status_created')]
        constraints = [models.UniqueConstraint(fields=['requested_by', 'kind'],
                                               condition=models.Q(status__in=['queued', 'running']),
                                               name='uniq_active_export_job')]
        verbose_name = 'ملف تصدير'
        verbose_name_plural = 'ملفات التصدير'

    def __str__(self):
        return f'{self.pk} {self.kind} {self.status} {self.file_name}'
