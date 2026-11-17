"""SOFTECH screen RPA (Stage 1): screens, approved recipes, jobs, documents, lines, devices, runs.

The extension never writes to SOFTECH here. A Windows agent types into the SOFTECH screen under a
frozen, approved recipe; these tables hold what it was asked to type and what happened.
"""
from django.core.exceptions import ValidationError
from django.db import models


class RpaScreen(models.Model):
    KEYS = [
        ('issue_125', 'إذن صرف للفروع'),
        ('stockcount', 'جرد'),
        ('purchase_10', 'فاتورة مشتريات'),
        ('return_120', 'مرتجع مشتريات'),
    ]
    key = models.CharField(max_length=30, unique=True, choices=KEYS)
    title_ar = models.CharField(max_length=120)
    enabled = models.BooleanField(default=False)
    live = models.BooleanField(default=False)   # False = dry-run only

    def __str__(self):
        return self.title_ar


class RpaRecipe(models.Model):
    STATUS = [('draft', 'مسودة'), ('approved', 'معتمدة'), ('retired', 'متقاعدة')]
    CONTENT_FIELDS = (
        'screen_id', 'version', 'window_title', 'cell_delay', 'form_delay', 'header_checklist',
        'line_cells', 'ref_cells', 'save_keys', 'cancel_keys', 'popups', 'source_filename',
        'created_by_id',
    )

    screen = models.ForeignKey(RpaScreen, on_delete=models.PROTECT, related_name='recipes')
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUS, default='draft')
    window_title = models.CharField(max_length=200, blank=True, default='')
    cell_delay = models.DecimalField(max_digits=5, decimal_places=2, default='0.2')
    form_delay = models.DecimalField(max_digits=5, decimal_places=2, default='0.25')
    header_checklist = models.JSONField(default=list, blank=True)
    line_cells = models.JSONField(default=list, blank=True)
    ref_cells = models.JSONField(default=list, blank=True)
    save_keys = models.JSONField(default=list, blank=True)
    cancel_keys = models.JSONField(default=list, blank=True)
    popups = models.JSONField(default=list, blank=True)
    source_filename = models.CharField(max_length=255, blank=True, default='')
    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT, related_name='rpa_recipes_created')
    approved_by = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='rpa_recipes_approved')
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['screen', 'version'], name='rpa_recipe_screen_version_uniq'),
            # backstop: at most one approved recipe per screen
            models.UniqueConstraint(fields=['screen'], condition=models.Q(status='approved'),
                                    name='rpa_recipe_one_approved_per_screen'),
        ]

    def __str__(self):
        return f'{self.screen_id} v{self.version} ({self.status})'

    def _normalised(self, name):
        """The field's Python value, so Decimal('0.20') == 0.2 == '0.2' compare equal."""
        field = self._meta.get_field(name)
        value = getattr(self, field.attname)
        if isinstance(field, models.DecimalField) and value is not None:
            return field.to_python(str(value)).normalize()
        return value

    def save(self, *args, **kwargs):
        # Approved content is frozen and approved -> retired is the only status move; a retired
        # recipe is final. (Going back to draft would reopen the content for editing.)
        if self.pk:
            stored = RpaRecipe.objects.filter(pk=self.pk).first()
            if stored is not None and stored.status in ('approved', 'retired'):
                allowed = {'approved': ('approved', 'retired'), 'retired': ('retired',)}[stored.status]
                changed = self.status not in allowed or any(
                    stored._normalised(n) != self._normalised(n) for n in self.CONTENT_FIELDS)
                if changed:
                    raise ValidationError('recipe is immutable once approved')
        super().save(*args, **kwargs)


class RpaDevice(models.Model):
    staff = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT, related_name='rpa_devices')
    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT,
                                   related_name='rpa_devices_created')
    label = models.CharField(max_length=120)
    token_hash = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    # why the last claim handed nothing out although work may wait (e.g. SOFTECH unreachable); '' = fine
    last_claim_error = models.CharField(max_length=255, blank=True, default='')
    last_claim_error_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.label


class RpaJob(models.Model):
    SOURCE_KINDS = [('excel', 'excel'), ('distribution_plan', 'distribution_plan'), ('reshuffle', 'reshuffle')]
    STATUS = [('uploaded', 'uploaded'), ('approved', 'approved'), ('cancelled', 'cancelled'), ('done', 'done')]

    screen = models.ForeignKey(RpaScreen, on_delete=models.PROTECT, related_name='jobs')
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, related_name='rpa_jobs')
    target_branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT, null=True, blank=True,
                                      related_name='rpa_jobs_received')
    recipe = models.ForeignKey(RpaRecipe, on_delete=models.PROTECT, null=True, blank=True, related_name='jobs')
    created_by = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT, related_name='rpa_jobs_created')
    approved_by = models.ForeignKey('users.StaffProfile', on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='rpa_jobs_approved')
    store_code = models.CharField(max_length=20, blank=True, default='')
    source_kind = models.CharField(max_length=20, choices=SOURCE_KINDS, default='excel')
    source_ref = models.CharField(max_length=120, blank=True, default='')
    filename = models.CharField(max_length=255, blank=True, default='')
    upload_sha256 = models.CharField(max_length=64, blank=True, default='', db_index=True)
    status = models.CharField(max_length=12, choices=STATUS, default='uploaded')
    dry_run = models.BooleanField(default=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class RpaDocument(models.Model):
    STATUS = [
        ('pending', 'pending'), ('approved', 'approved'), ('in_progress', 'in_progress'),
        ('dry_run_ok', 'dry_run_ok'), ('posted', 'posted'), ('needs_person', 'needs_person'),
        ('cancelled', 'cancelled'),
    ]
    job = models.ForeignKey(RpaJob, on_delete=models.CASCADE, related_name='documents')
    claimed_by = models.ForeignKey(RpaDevice, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name='claimed_documents')
    seq = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=14, choices=STATUS, default='pending')
    claimed_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    softech_docnumber = models.IntegerField(null=True, blank=True)
    verify_result = models.JSONField(default=dict, blank=True)
    needs_person_reason = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['job_id', 'seq']

    @property
    def reference(self):
        return f'RPA-{self.pk}'


class RpaLine(models.Model):
    STATUS = [('matched', 'matched'), ('unmatched', 'unmatched'), ('error', 'error')]
    document = models.ForeignKey(RpaDocument, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey('catalog.Item', on_delete=models.PROTECT, null=True, blank=True,
                             related_name='rpa_lines')
    row_no = models.PositiveIntegerField()
    raw = models.JSONField(default=dict, blank=True)
    itemcode = models.CharField(max_length=40, blank=True, default='')
    qty = models.DecimalField(max_digits=12, decimal_places=5, default=0)
    expiry = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='matched')
    message = models.CharField(max_length=255, blank=True, default='')
    warning = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['document_id', 'row_no']


class RpaRun(models.Model):
    MODES = [('dry_run', 'dry_run'), ('live', 'live')]
    OUTCOMES = [
        ('', 'open'), ('dry_run_ok', 'dry_run_ok'), ('saved', 'saved'),
        ('stopped_by_operator', 'stopped_by_operator'), ('wrong_window', 'wrong_window'),
        ('unknown_popup', 'unknown_popup'), ('timeout', 'timeout'), ('error', 'error'),
    ]
    document = models.ForeignKey(RpaDocument, on_delete=models.CASCADE, related_name='runs')
    device = models.ForeignKey(RpaDevice, on_delete=models.PROTECT, related_name='runs')
    recipe = models.ForeignKey(RpaRecipe, on_delete=models.PROTECT, related_name='runs')
    mode = models.CharField(max_length=8, choices=MODES, default='dry_run')
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=OUTCOMES, blank=True, default='')
    steps = models.JSONField(default=list, blank=True)


class RpaScreenshot(models.Model):
    run = models.ForeignKey(RpaRun, on_delete=models.CASCADE, related_name='shots')
    step_index = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to='rpa/%Y/%m/')
    created_at = models.DateTimeField(auto_now_add=True)
