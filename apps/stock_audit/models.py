"""
apps/stock_audit/models.py

Stock Transactions Audit (doc 32) — Phase 1: the read-only stock movement mirror.

StockLedgerLine     — one SOFTECH `stktrans` line, every doccode, read from HQ (which
                      holds every branch's lines). Rolling window (STOCK_AUDIT_WINDOW_DAYS).
StockLedgerSyncRun  — audit trail for one `sync_stock_ledger` run.

`stktrans` has no line id, so the mirror is refreshed by REPLACING whole docdate days:
every line SOFTECH returns for [date_from, date_to) replaces what we held for those days.
Re-running is idempotent and also picks up lines edited or deleted in SOFTECH.
Never written to SOFTECH.
"""
from django.db import models


class StockLedgerLine(models.Model):
    # ── Document ──────────────────────────────────────────────────────────────
    branchcode = models.CharField(max_length=5, verbose_name='كود الفرع')
    doccode    = models.CharField(max_length=3, verbose_name='نوع المستند')
    docnumber  = models.BigIntegerField(verbose_name='رقم المستند')
    docdate    = models.DateField(verbose_name='تاريخ المستند')
    trans_time = models.DateTimeField(null=True, blank=True, verbose_name='وقت الإدخال')
    storecode  = models.CharField(max_length=3, blank=True, verbose_name='المخزن')
    storecode2 = models.CharField(max_length=3, blank=True, verbose_name='المخزن المقابل')
    usercode   = models.CharField(max_length=5, blank=True, db_index=True, verbose_name='مستخدم SOFTECH')
    personcode = models.CharField(max_length=8, blank=True, verbose_name='العميل / المورد')
    suppliercode = models.CharField(max_length=8, blank=True)

    # ── Item ──────────────────────────────────────────────────────────────────
    itemcode = models.CharField(max_length=6, verbose_name='كود الصنف')
    item = models.ForeignKey('catalog.Item', on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='+')
    itemexpirydate = models.DateField(null=True, blank=True)

    # ── Quantities / prices (SOFTECH precision) ───────────────────────────────
    transqty     = models.DecimalField(max_digits=12, decimal_places=5, default=0)
    newqty       = models.DecimalField(max_digits=12, decimal_places=5, default=0,
                                       help_text='Stock after this line')
    bonusqty     = models.DecimalField(max_digits=12, decimal_places=5, default=0)
    retqty       = models.DecimalField(max_digits=12, decimal_places=5, default=0)
    transprice   = models.DecimalField(max_digits=11, decimal_places=4, default=0,
                                       help_text='Sales: VAT-inclusive unit price')
    transprice_total = models.DecimalField(max_digits=13, decimal_places=4, default=0)
    newcostprice = models.DecimalField(max_digits=11, decimal_places=4, default=0,
                                       help_text='Weighted-average cost after this line, before VAT')
    itemsaleprice     = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    itemsalestax      = models.DecimalField(max_digits=10, decimal_places=4, default=0,
                                            help_text='VAT amount inside the list price')
    itemsaleprice_tax = models.DecimalField(max_digits=11, decimal_places=4, default=0,
                                            help_text='List price net of VAT')
    pharmacydiscp   = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    additionaldiscp = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                          help_text='Sales lines: VAT rate %')
    custdiscp       = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    specialdiscp    = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # ── References (returns → original sale; transfers → source document) ────
    r_doccode   = models.CharField(max_length=3, blank=True)
    r_docnumber = models.BigIntegerField(null=True, blank=True)
    r_docdate   = models.DateField(null=True, blank=True)
    s_doccode   = models.CharField(max_length=3, blank=True)
    s_docnumber = models.BigIntegerField(null=True, blank=True)
    s_docdate   = models.DateField(null=True, blank=True)

    synced_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'حركة مخزون (مرآة SOFTECH)'
        verbose_name_plural = 'حركات المخزون (مرآة SOFTECH)'
        indexes = [
            models.Index(fields=['docdate'], name='sa_ledger_docdate'),
            models.Index(fields=['branchcode', 'doccode', 'trans_time'], name='sa_ledger_br_doc_time'),
            models.Index(fields=['itemcode', 'branchcode', 'trans_time'], name='sa_ledger_item_br_time'),
            models.Index(fields=['usercode', 'trans_time'], name='sa_ledger_user_time'),
            models.Index(fields=['branchcode', 'doccode', 'docnumber', 'docdate'], name='sa_ledger_doc'),
        ]

    def __str__(self):
        return f'{self.branchcode}/{self.doccode}/{self.docnumber} {self.docdate} · {self.itemcode} × {self.transqty}'


class StockLedgerSyncRun(models.Model):
    """Audit trail for one `sync_stock_ledger` run (HQ, docdate-day replace)."""
    STATUS_CHOICES = [('running', 'يعمل'), ('success', 'ناجح'),
                      ('partial', 'جزئي'), ('failed', 'فشل')]

    started_at  = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')
    date_from   = models.DateField(null=True, blank=True)
    date_to     = models.DateField(null=True, blank=True, help_text='Exclusive')
    chunks_ok     = models.PositiveIntegerField(default=0)
    chunks_failed = models.PositiveIntegerField(default=0)
    rows_synced   = models.PositiveIntegerField(default=0)
    rows_pruned   = models.PositiveIntegerField(default=0)
    detail        = models.JSONField(default=dict)   # {chunk_start: {ok/rows/error}}
    triggered_by  = models.CharField(max_length=50, blank=True)

    class Meta:
        verbose_name        = 'تشغيل مزامنة حركات المخزون'
        verbose_name_plural = 'تشغيلات مزامنة حركات المخزون'
        ordering = ['-started_at']

    def __str__(self):
        return f'StockLedgerSync #{self.pk} — {self.status} — {self.started_at:%Y-%m-%d %H:%M}'

    def finish(self, status='success'):
        from django.utils import timezone as _tz
        self.status = status
        self.finished_at = _tz.now()
        self.save(update_fields=['status', 'finished_at', 'date_from', 'date_to', 'chunks_ok',
                                 'chunks_failed', 'rows_synced', 'rows_pruned', 'detail'])


# ── Phase 2: rules, branch overrides, engine runs, findings ───────────────────

class StockAuditRule(models.Model):
    """One row per check (seeded from rules.RULES). `params` holds the chain-wide thresholds;
    their meaning and limits are defined per rule in rules.RULES and validated server-side."""
    code     = models.CharField(max_length=40, unique=True, verbose_name='كود الفحص')
    enabled  = models.BooleanField(default=True, verbose_name='مُفعّل')
    params   = models.JSONField(default=dict, verbose_name='الحدود')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['code']
        verbose_name = 'فحص تدقيق المخزون'
        verbose_name_plural = 'فحوص تدقيق المخزون'

    def __str__(self):
        return f'{self.code} {"on" if self.enabled else "off"} {self.params}'


class StockAuditRuleOverride(models.Model):
    """Branch-specific values merged over the rule's chain-wide params. `enabled` None = inherit."""
    rule   = models.ForeignKey(StockAuditRule, on_delete=models.CASCADE, related_name='overrides')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, related_name='+')
    enabled = models.BooleanField(null=True, blank=True, verbose_name='مُفعّل (فارغ = كالعام)')
    params  = models.JSONField(default=dict, verbose_name='حدود الفرع')
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                   null=True, blank=True, related_name='+')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['rule', 'branch'], name='uniq_stock_audit_override')]
        verbose_name = 'حدود فرع لفحص'
        verbose_name_plural = 'حدود الفروع للفحوص'

    def __str__(self):
        return f'{self.rule.code} @ {self.branch_id}: {self.params}'


class StockAuditRun(models.Model):
    """One engine run — window, the effective params used per rule/branch, counts."""
    STATUS_CHOICES = [('running', 'يعمل'), ('success', 'ناجح'),
                      ('partial', 'جزئي'), ('failed', 'فشل')]

    started_at  = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    status      = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')
    date_from   = models.DateField(null=True, blank=True)
    date_to     = models.DateField(null=True, blank=True, help_text='Exclusive')
    params_used = models.JSONField(default=dict)   # {rule: {branch: effective params}}
    counts      = models.JSONField(default=dict)   # {rule: {new, updated, reopened, seen, error?}}
    triggered_by = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'تشغيل تدقيق المخزون'
        verbose_name_plural = 'تشغيلات تدقيق المخزون'

    def __str__(self):
        return f'StockAuditRun #{self.pk} — {self.status} — {self.started_at:%Y-%m-%d %H:%M}'


class StockAuditFinding(models.Model):
    """One detected fact. Re-runs update it (dedup_key); review status is never reset,
    except that a dismissed finding is reopened when its value grows by more than 50%."""
    SEV_INFO, SEV_WARNING, SEV_CRITICAL = 'info', 'warning', 'critical'
    SEVERITY_CHOICES = [(SEV_INFO, 'معلومة'), (SEV_WARNING, 'تنبيه'), (SEV_CRITICAL, 'حرج')]
    ST_OPEN, ST_REVIEWED, ST_DISMISSED, ST_ESCALATED = 'open', 'reviewed', 'dismissed', 'escalated'
    STATUS_CHOICES = [(ST_OPEN, 'مفتوح'), (ST_REVIEWED, 'تمت المراجعة'),
                      (ST_DISMISSED, 'تم التجاهل'), (ST_ESCALATED, 'تم التصعيد')]
    # Review moves allowed by the API (a note is required for every move except → reviewed).
    TRANSITIONS = {
        ST_OPEN:      {ST_REVIEWED, ST_DISMISSED, ST_ESCALATED},
        ST_ESCALATED: {ST_REVIEWED, ST_DISMISSED},
        ST_REVIEWED:  {ST_OPEN},
        ST_DISMISSED: {ST_OPEN},
    }

    rule_code = models.CharField(max_length=40, db_index=True)
    dedup_key = models.CharField(max_length=200)
    severity  = models.CharField(max_length=10, choices=SEVERITY_CHOICES, db_index=True)
    status    = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ST_OPEN, db_index=True)

    # where / what / who
    branchcode = models.CharField(max_length=5, db_index=True)
    branch     = models.ForeignKey('branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    itemcode   = models.CharField(max_length=6, blank=True, db_index=True)
    item       = models.ForeignKey('catalog.Item', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    doccode    = models.CharField(max_length=3, blank=True)
    docnumber  = models.BigIntegerField(null=True, blank=True)
    docdate    = models.DateField(null=True, blank=True, db_index=True)
    occurred_at = models.DateTimeField(null=True, blank=True, db_index=True)
    softech_user = models.CharField(max_length=5, blank=True, db_index=True)
    staff      = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    personcode = models.CharField(max_length=8, blank=True)

    # measurement
    value_egp = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    metric    = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    threshold = models.DecimalField(max_digits=16, decimal_places=4, null=True, blank=True)
    evidence  = models.JSONField(default=dict)
    message_ar = models.TextField(blank=True)
    message_en = models.TextField(blank=True)

    # lifecycle
    first_run = models.ForeignKey(StockAuditRun, on_delete=models.SET_NULL, null=True, related_name='+')
    last_run  = models.ForeignKey(StockAuditRun, on_delete=models.SET_NULL, null=True, related_name='+')
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen  = models.DateTimeField()
    reviewed_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    class Meta:
        ordering = ['-occurred_at']
        constraints = [models.UniqueConstraint(fields=['rule_code', 'dedup_key'], name='uniq_stock_audit_finding')]
        indexes = [
            models.Index(fields=['rule_code', 'status', 'severity'], name='sa_find_rule_status'),
            models.Index(fields=['branchcode', 'status'], name='sa_find_branch_status'),
        ]
        verbose_name = 'ملاحظة تدقيق مخزون'
        verbose_name_plural = 'ملاحظات تدقيق المخزون'

    def __str__(self):
        return f'{self.rule_code} [{self.severity}/{self.status}] {self.branchcode} {self.itemcode} {self.value_egp}'


class StockAuditAccess(models.Model):
    """A NAMED branch manager allowed to see and review findings for their own branches
    (owner decision 2026-10-26: not the whole pharmacist role). Grants and revokes are kept
    (revoked_at) and written to AuditLog. Shift managers may become a second level later."""
    LEVEL_BRANCH_MANAGER = 'branch_manager'
    LEVEL_CHOICES = [(LEVEL_BRANCH_MANAGER, 'مدير فرع')]

    staff = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE, related_name='stock_audit_grants')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=LEVEL_BRANCH_MANAGER)
    note  = models.CharField(max_length=255, blank=True)
    granted_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, related_name='+')
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_by = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-granted_at']
        constraints = [models.UniqueConstraint(fields=['staff'], condition=models.Q(revoked_at__isnull=True),
                                               name='uniq_active_stock_audit_access')]
        verbose_name = 'صلاحية تدقيق المخزون لمدير فرع'
        verbose_name_plural = 'صلاحيات تدقيق المخزون لمديري الفروع'

    def __str__(self):
        return f'{self.staff_id} {self.level} {"revoked" if self.revoked_at else "active"}'
