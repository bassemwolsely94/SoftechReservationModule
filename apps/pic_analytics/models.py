from django.db import models


class PicDayFact(models.Model):
    """Daily sales fact per PIC (Customer.softech_pic), rebuilt by day-replace. pic='' holds
    no-PIC sales. salesperson / channel_bucket are non-null so the unique grain works."""
    pic = models.CharField(max_length=30, db_index=True, blank=True)
    day = models.DateField(db_index=True)
    branch = models.ForeignKey('branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    salesperson = models.CharField(max_length=20, blank=True, default='')       # softech_user
    channel_bucket = models.CharField(max_length=20, blank=True, default='')
    invoices = models.IntegerField(default=0)
    returns = models.IntegerField(default=0)
    net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cost = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # KPI-board gross profit (profit channels, excluded items out): gp_net = line revenue, gp = gp_net - cost
    gp_net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    gp = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    units = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    lines = models.IntegerField(default=0)
    net_by_category = models.JSONField(default=dict, blank=True)               # {medicine_type: net}
    is_first_purchase = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=['pic', 'day', 'branch', 'salesperson', 'channel_bucket'], name='uniq_pic_day_fact')]
        indexes = [
            models.Index(fields=['day', 'branch'], name='picfact_day_branch'),
            models.Index(fields=['pic', 'day'], name='picfact_pic_day'),
        ]
        verbose_name = 'حقيقة يومية لعميل'
        verbose_name_plural = 'حقائق يومية للعملاء'

    def __str__(self):
        return f'{self.pic or "-"} {self.day} {self.net}'


class PicRollup(models.Model):
    """Per-PIC derived lifecycle figures as of a date."""
    pic = models.CharField(max_length=30, unique=True)
    as_of = models.DateField()
    first_purchase = models.DateField(null=True, blank=True)
    last_purchase = models.DateField(null=True, blank=True)
    prev_visit_before_last = models.DateField(null=True, blank=True)
    visits_12m = models.IntegerField(default=0)
    months_a = models.IntegerField(default=0)
    streak_b = models.IntegerField(default=0)
    cycle_days = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    cycle_bucket = models.CharField(max_length=10, blank=True, default='')
    lifetime_net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    home_branch = models.ForeignKey('branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        verbose_name = 'ملخص عميل'
        verbose_name_plural = 'ملخصات العملاء'

    def __str__(self):
        return f'{self.pic} @ {self.as_of}'


class PicAnalyticsAccess(models.Model):
    """A NAMED staff member allowed into PIC Analytics. Grants/revokes are kept (revoked_at)
    and written to AuditLog. Mirrors stock_audit.StockAuditAccess."""
    staff = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE, related_name='pic_analytics_grants')
    note = models.CharField(max_length=255, blank=True)
    granted_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, related_name='+')
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-granted_at']
        constraints = [models.UniqueConstraint(fields=['staff'], condition=models.Q(revoked_at__isnull=True),
                                               name='uniq_active_pic_analytics_access')]
        verbose_name = 'صلاحية تحليلات العملاء'
        verbose_name_plural = 'صلاحيات تحليلات العملاء'

    def __str__(self):
        return f'{self.staff_id} {"revoked" if self.revoked_at else "active"}'


class PhoneLabel(models.Model):
    """Classifies a calling number (staff, supplier, ...) so missed-call reports can skip it."""
    LABEL_CHOICES = [
        ('staff', 'موظف'), ('supplier', 'مورد'), ('branch', 'فرع'),
        ('doctor', 'طبيب'), ('spam', 'مزعج'), ('other', 'أخرى'),
    ]
    phone_key = models.CharField(max_length=15, unique=True)
    label = models.CharField(max_length=10, choices=LABEL_CHOICES)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'تصنيف رقم'
        verbose_name_plural = 'تصنيفات الأرقام'

    def __str__(self):
        return f'{self.phone_key} {self.label}'


class PicExclusion(models.Model):
    """A PIC that is not a real individual customer (a running account, a doctor's code, junk phones...)
    and so distorts the analytics. Applied at QUERY time (queries/filters.py + exclusions.py): the list can
    change without any rebuild. Soft delete (removed_at) keeps the history; re-adding creates a new row."""
    pic = models.CharField(max_length=30, db_index=True)
    reason = models.CharField(max_length=255)
    added_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, related_name='+')
    added_at = models.DateTimeField(auto_now_add=True)
    removed_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-added_at']
        constraints = [models.UniqueConstraint(fields=['pic'], condition=models.Q(removed_at__isnull=True),
                                               name='uniq_active_pic_exclusion')]
        verbose_name = 'عميل مستبعد من التحليل'
        verbose_name_plural = 'عملاء مستبعدون من التحليل'

    def __str__(self):
        return f'{self.pic} {"removed" if self.removed_at else "excluded"}'


class PicExportJob(models.Model):
    """One background Excel export (a 12-month workbook takes longer than nginx's 60 s, doc 33 §15).
    The xlsx bytes live in `data` (never under /media) and only the requester may read or download
    them. Jobs are deleted after 48 h; a queued/running job older than 15 min is reported failed
    (the process that ran it restarted). See apps/pic_analytics/jobs.py."""
    QUEUED, RUNNING, DONE, FAILED = 'queued', 'running', 'done', 'failed'
    STATUS_CHOICES = [(QUEUED, 'في الانتظار'), (RUNNING, 'جارٍ الإنشاء'), (DONE, 'جاهز'), (FAILED, 'فشل')]
    ACTIVE = (QUEUED, RUNNING)

    requested_by = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT, related_name='+')
    params = models.JSONField(default=dict, blank=True)          # raw query params {key: [values]}
    filters = models.JSONField(default=dict, blank=True)         # effective filters (for the audit entry)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=QUEUED)
    progress_pct = models.PositiveSmallIntegerField(default=0)
    progress_msg = models.CharField(max_length=120, blank=True, default='')
    file_name = models.CharField(max_length=200, blank=True, default='')
    data = models.BinaryField(null=True, blank=True, editable=False)
    rows = models.JSONField(default=dict, blank=True)            # {sheet: rows written}
    error = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['requested_by', '-created_at'], name='picexport_user_created')]
        constraints = [models.UniqueConstraint(fields=['requested_by'], condition=models.Q(status__in=['queued', 'running']),
                                               name='uniq_active_pic_export_job')]
        verbose_name = 'تصدير تحليلات العملاء'
        verbose_name_plural = 'تصديرات تحليلات العملاء'

    def __str__(self):
        return f'{self.pk} {self.status} {self.file_name}'
