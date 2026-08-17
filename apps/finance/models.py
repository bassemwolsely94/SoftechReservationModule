"""
apps/finance/models.py

Financial Intelligence Platform — PostgreSQL analytics layer.

This module stores the *semantic* financial picture derived from SOFTECH.
It never writes back to SOFTECH; it only reads and enriches.

Model hierarchy
───────────────
FinanceSchemaTable          — Phase 0 schema dictionary
Account                     — Phase 1-2 chart of accounts
FinancialPeriod             — time dimension
JournalEntry / JournalLine  — Phase 1 ledger
AccountBalance              — Phase 2 pre-computed balances
TreasuryMovement            — Phase 4 cash / bank / cheque
ExpenseRecord               — Phase 3 classified expenses
FinancialSnapshot           — Phase 6 pre-computed KPIs per period
FinanceSyncRun              — Phase 9 ETL audit log
"""
from django.db import models
from django.utils import timezone


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 0 — SCHEMA DICTIONARY
# ══════════════════════════════════════════════════════════════════════════════

class FinanceSchemaTable(models.Model):
    """
    Each row = one SOFTECH table discovered during Phase-0 scan.
    Populated by: python manage.py discover_finance_schema
    """
    table_name          = models.CharField(max_length=100, unique=True)
    inferred_purpose    = models.CharField(max_length=300, blank=True)
    row_count           = models.BigIntegerField(default=0)
    columns             = models.JSONField(default=list)   # [{name, type, length, colid}]
    sample_rows         = models.JSONField(default=list)   # up to 3 rows as dicts
    is_confirmed        = models.BooleanField(default=False)
    sync_enabled        = models.BooleanField(default=False)
    category            = models.CharField(max_length=50, blank=True)
    # e.g. accounts / journal / cash / bank / expense / payroll / other
    discovered_at       = models.DateTimeField(default=timezone.now)
    notes               = models.TextField(blank=True)

    class Meta:
        ordering = ['table_name']
        verbose_name        = 'جدول مالي مكتشف'
        verbose_name_plural = 'جداول مالية مكتشفة'

    def __str__(self):
        return f'{self.table_name} ({self.row_count:,} rows)'

    def column_names(self):
        return [c['name'] for c in (self.columns or [])]


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1-2 — CHART OF ACCOUNTS
# ══════════════════════════════════════════════════════════════════════════════

ACCOUNT_TYPE_CHOICES = [
    ('asset',     'أصول'),
    ('liability', 'التزامات'),
    ('equity',    'حقوق الملكية'),
    ('revenue',   'إيرادات'),
    ('expense',   'مصروفات'),
    ('cogs',      'تكلفة المبيعات'),
    ('contra',    'مقابل'),
    ('memo',      'إيضاح'),
    ('unknown',   'غير محدد'),
]

ACCOUNT_NATURE_CHOICES = [
    ('debit',  'مدين'),
    ('credit', 'دائن'),
]


class Account(models.Model):
    """
    Unified Chart of Accounts — synced from SOFTECH accmaster / acctree (if found)
    or built manually.  Supports unlimited hierarchy depth.
    """
    code         = models.CharField(max_length=50, unique=True, db_index=True)
    name         = models.CharField(max_length=500)
    name_ar      = models.CharField(max_length=500, blank=True)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, default='unknown')
    nature       = models.CharField(max_length=10, choices=ACCOUNT_NATURE_CHOICES, default='debit')
    parent       = models.ForeignKey(
        'self', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='children',
    )
    level        = models.IntegerField(default=1)
    is_leaf      = models.BooleanField(default=True)   # posting account (no children)
    is_active    = models.BooleanField(default=True)
    softech_code = models.CharField(max_length=50, blank=True)  # original key
    description  = models.TextField(blank=True)
    synced_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['code']
        verbose_name        = 'حساب'
        verbose_name_plural = 'الحسابات'
        indexes = [
            models.Index(fields=['account_type']),
            models.Index(fields=['parent']),
        ]

    def __str__(self):
        return f'{self.code} — {self.name_ar or self.name}'

    @property
    def display_name(self):
        return self.name_ar or self.name

    def ancestors(self):
        """Return ordered list of parent accounts up to root."""
        path, node = [], self
        while node.parent_id:
            node = node.parent
            path.insert(0, node)
        return path


# ══════════════════════════════════════════════════════════════════════════════
# TIME DIMENSION
# ══════════════════════════════════════════════════════════════════════════════

PERIOD_TYPE_CHOICES = [
    ('month',   'شهري'),
    ('quarter', 'ربع سنوي'),
    ('year',    'سنوي'),
]


class FinancialPeriod(models.Model):
    """
    A reporting window (month, quarter, or year).
    All financial snapshots and balances link to a period.
    month=0 means annual aggregation.
    """
    year         = models.IntegerField()
    month        = models.IntegerField(default=0)   # 0 = annual / 1-12 = monthly
    period_type  = models.CharField(max_length=10, choices=PERIOD_TYPE_CHOICES, default='month')
    period_start = models.DateField()
    period_end   = models.DateField()
    label        = models.CharField(max_length=20, blank=True)  # e.g. "2024-03", "2024-Q1"
    is_closed    = models.BooleanField(default=False)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('year', 'month', 'period_type')]
        ordering        = ['-year', '-month']
        verbose_name        = 'فترة مالية'
        verbose_name_plural = 'الفترات المالية'

    def __str__(self):
        return self.label or f'{self.year}-{self.month:02d}'

    def save(self, *args, **kwargs):
        if not self.label:
            if self.period_type == 'month':
                self.label = f'{self.year}-{self.month:02d}'
            elif self.period_type == 'quarter':
                q = (self.month - 1) // 3 + 1
                self.label = f'{self.year}-Q{q}'
            else:
                self.label = str(self.year)
        super().save(*args, **kwargs)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — JOURNAL ENGINE
# ══════════════════════════════════════════════════════════════════════════════

ENTRY_TYPE_CHOICES = [
    ('manual',        'يدوي'),
    ('sales',         'مبيعات'),
    ('purchase',      'مشتريات'),
    ('cash_receipt',  'قبض نقدي'),
    ('cash_payment',  'صرف نقدي'),
    ('bank_receipt',  'قبض بنكي'),
    ('bank_payment',  'صرف بنكي'),
    ('depreciation',  'استهلاك'),
    ('adjustment',    'تسوية'),
    ('closing',       'إقفال'),
    ('opening',       'افتتاح'),
    ('expense',       'مصروف'),
    ('payroll',       'رواتب'),
    ('other',         'أخرى'),
]


class JournalEntry(models.Model):
    """
    One journal entry (header).  Lines are in JournalLine.
    Synced from SOFTECH journalm / equivalent table.
    """
    softech_number = models.CharField(max_length=100, blank=True, db_index=True)
    entry_date     = models.DateField(db_index=True)
    branch         = models.ForeignKey(
        'branches.Branch', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='journal_entries',
    )
    description    = models.CharField(max_length=1000, blank=True)
    description_ar = models.CharField(max_length=1000, blank=True)
    entry_type     = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES, default='manual')
    reference      = models.CharField(max_length=200, blank=True)
    total_debit    = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    total_credit   = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    is_balanced    = models.BooleanField(default=True)
    period         = models.ForeignKey(
        FinancialPeriod, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='journal_entries',
    )
    source_table   = models.CharField(max_length=100, blank=True)
    synced_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-entry_date', '-id']
        verbose_name        = 'قيد يومية'
        verbose_name_plural = 'قيود اليومية'
        indexes = [
            models.Index(fields=['entry_date', 'branch']),
            models.Index(fields=['entry_type']),
            models.Index(fields=['period']),
            models.Index(fields=['softech_number']),
        ]

    def __str__(self):
        return f'{self.softech_number or self.pk} | {self.entry_date} | {self.total_debit:,.2f}'


class JournalLine(models.Model):
    """One debit or credit line inside a JournalEntry."""
    entry        = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name='lines')
    line_number  = models.IntegerField(default=1)
    account      = models.ForeignKey(
        Account, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='journal_lines',
    )
    account_code = models.CharField(max_length=50, blank=True)  # raw SOFTECH code
    description  = models.CharField(max_length=500, blank=True)
    debit        = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    credit       = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    cost_center  = models.CharField(max_length=50, blank=True)
    party_code   = models.CharField(max_length=50, blank=True)
    party_name   = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['entry', 'line_number']
        verbose_name        = 'سطر قيد'
        verbose_name_plural = 'سطور القيود'


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — PRE-COMPUTED ACCOUNT BALANCES
# ══════════════════════════════════════════════════════════════════════════════

class AccountBalance(models.Model):
    """
    Pre-computed debit / credit / balance per account × period × branch.
    Recomputed by sync_finance after each journal sync.
    Enables instant trial-balance and account-statement queries.
    """
    account         = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='balances')
    period          = models.ForeignKey(FinancialPeriod, on_delete=models.CASCADE, related_name='balances')
    branch          = models.ForeignKey(
        'branches.Branch', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='account_balances',
    )
    opening_balance = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    total_debit     = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    total_credit    = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    closing_balance = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    movement_count  = models.IntegerField(default=0)

    class Meta:
        unique_together = [('account', 'period', 'branch')]
        verbose_name        = 'رصيد حساب'
        verbose_name_plural = 'أرصدة الحسابات'
        indexes = [
            models.Index(fields=['period', 'branch']),
            models.Index(fields=['account', 'period']),
        ]

    def __str__(self):
        return f'{self.account.code} | {self.period} | {self.closing_balance:,.2f}'


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 — TREASURY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

DIRECTION_CHOICES    = [('in', 'قبض'), ('out', 'صرف')]
PAYMENT_METHOD_CHOICES = [
    ('cash',     'نقدي'),
    ('cheque',   'شيك'),
    ('transfer', 'تحويل بنكي'),
    ('card',     'بطاقة'),
    ('credit',   'آجل / تسهيل'),
    ('other',    'أخرى'),
]
TREASURY_TYPE_CHOICES = [
    ('receipt',     'إيصال'),
    ('payment',     'دفعة'),
    ('transfer',    'تحويل داخلي'),
    ('opening',     'رصيد افتتاحي'),
    ('adjustment',  'تسوية'),
]
PARTY_TYPE_CHOICES = [
    ('supplier', 'مورد'),
    ('customer', 'عميل'),
    ('employee', 'موظف'),
    ('bank',     'بنك'),
    ('other',    'أخرى'),
]


class TreasuryMovement(models.Model):
    """
    Cash / bank / cheque movement.
    Synced from SOFTECH cashtrans / banktrans / cheques tables (if discovered).
    """
    softech_number = models.CharField(max_length=100, blank=True, db_index=True)
    movement_date  = models.DateField(db_index=True)
    movement_type  = models.CharField(max_length=20, choices=TREASURY_TYPE_CHOICES, default='receipt')
    direction      = models.CharField(max_length=3, choices=DIRECTION_CHOICES)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='cash')
    account_code   = models.CharField(max_length=50, blank=True)
    branch         = models.ForeignKey(
        'branches.Branch', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='treasury_movements',
    )
    amount         = models.DecimalField(max_digits=18, decimal_places=3)
    description    = models.CharField(max_length=500, blank=True)
    reference      = models.CharField(max_length=200, blank=True)
    party_code     = models.CharField(max_length=50, blank=True)
    party_name     = models.CharField(max_length=300, blank=True)
    party_type     = models.CharField(max_length=20, choices=PARTY_TYPE_CHOICES, blank=True)
    cheque_number  = models.CharField(max_length=50, blank=True)
    cheque_date    = models.DateField(null=True, blank=True)
    bank_name      = models.CharField(max_length=200, blank=True)
    period         = models.ForeignKey(
        FinancialPeriod, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='treasury_movements',
    )
    source_table   = models.CharField(max_length=100, blank=True)
    synced_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-movement_date', '-id']
        verbose_name        = 'حركة خزينة'
        verbose_name_plural = 'حركات الخزينة'
        indexes = [
            models.Index(fields=['movement_date', 'branch']),
            models.Index(fields=['direction']),
            models.Index(fields=['payment_method']),
            models.Index(fields=['period']),
            models.Index(fields=['party_code']),
            models.Index(fields=['softech_number']),
        ]

    def __str__(self):
        sign = '+' if self.direction == 'in' else '-'
        return f'{sign}{self.amount:,.2f} | {self.movement_date} | {self.party_name or self.account_code}'


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — EXPENSE INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

EXPENSE_CATEGORY_CHOICES = [
    ('payroll',       'رواتب وأجور'),
    ('rent',          'إيجارات'),
    ('utilities',     'مرافق (كهرباء / مياه / اتصالات)'),
    ('fuel',          'وقود ومواصلات'),
    ('maintenance',   'صيانة'),
    ('delivery',      'توصيل وشحن'),
    ('marketing',     'تسويق وإعلان'),
    ('finance_cost',  'تكاليف تمويلية'),
    ('bank_charges',  'رسوم بنكية'),
    ('taxes',         'ضرائب ورسوم'),
    ('shrinkage',     'فاقد وعجز'),
    ('expiry',        'منتهي الصلاحية'),
    ('returns',       'مرتجعات من العملاء'),
    ('admin',         'مصروفات إدارية'),
    ('depreciation',  'استهلاك أصول'),
    ('insurance',     'تأمين'),
    ('other',         'أخرى'),
]


class ExpenseRecord(models.Model):
    """
    One classified expense line.
    Sourced from SOFTECH expense tables or from journal lines typed as 'expense'.
    """
    softech_ref  = models.CharField(max_length=100, blank=True, db_index=True)
    expense_date = models.DateField(db_index=True)
    category     = models.CharField(max_length=30, choices=EXPENSE_CATEGORY_CHOICES, default='other')
    sub_category = models.CharField(max_length=100, blank=True)
    branch       = models.ForeignKey(
        'branches.Branch', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='expense_records',
    )
    amount       = models.DecimalField(max_digits=18, decimal_places=3)
    description  = models.CharField(max_length=500, blank=True)
    vendor       = models.CharField(max_length=300, blank=True)
    reference    = models.CharField(max_length=200, blank=True)
    account_code = models.CharField(max_length=50, blank=True)
    cost_center  = models.CharField(max_length=50, blank=True)
    is_recurring = models.BooleanField(default=False)
    period       = models.ForeignKey(
        FinancialPeriod, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='expense_records',
    )
    source_table = models.CharField(max_length=100, blank=True)
    synced_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-expense_date', '-id']
        verbose_name        = 'سجل مصروفات'
        verbose_name_plural = 'سجلات المصروفات'
        indexes = [
            models.Index(fields=['expense_date', 'branch']),
            models.Index(fields=['category']),
            models.Index(fields=['period']),
        ]

    def __str__(self):
        return f'{self.get_category_display()} | {self.amount:,.2f} | {self.expense_date}'


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 6 — FINANCIAL SNAPSHOT (pre-computed KPIs per period)
# ══════════════════════════════════════════════════════════════════════════════

class FinancialSnapshot(models.Model):
    """
    Pre-computed financial KPI snapshot for a period × branch combination.
    branch=None means consolidated (all branches).
    Recomputed by sync_finance after each sync cycle.
    The snapshot integrates:
      - Revenue & COGS from existing analytics/procurement models
      - Expenses from ExpenseRecord
      - Treasury from TreasuryMovement
      - Journal balances from AccountBalance (if accounting tables discovered)
    """
    period = models.ForeignKey(FinancialPeriod, on_delete=models.CASCADE, related_name='snapshots')
    branch = models.ForeignKey(
        'branches.Branch', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='financial_snapshots',
    )

    # ── Revenue (from sales sync) ─────────────────────────────────────────────
    gross_revenue       = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    returns_value       = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_revenue         = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── COGS & Gross Profit (from procurement) ────────────────────────────────
    cogs                = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    gross_profit        = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    gross_margin_pct    = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Purchases (direct from procurement) ───────────────────────────────────
    total_purchases        = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_purchase_returns = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_purchases          = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── Operating Expenses (from ExpenseRecord) ───────────────────────────────
    total_expenses    = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    payroll_expenses  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    rent_expenses     = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    utility_expenses  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    other_expenses    = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── Profit ────────────────────────────────────────────────────────────────
    operating_profit  = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    ebitda            = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_profit        = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_margin_pct    = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # ── Cash Flow (from TreasuryMovement) ────────────────────────────────────
    cash_inflow       = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    cash_outflow      = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    net_cash_flow     = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── Balance Sheet KPIs (from AccountBalance, when available) ─────────────
    total_assets      = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_liabilities = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    equity            = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    working_capital   = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    inventory_value   = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_receivables = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    total_payables    = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    # ── Ratios ────────────────────────────────────────────────────────────────
    current_ratio     = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    quick_ratio       = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    debt_ratio        = models.DecimalField(max_digits=8, decimal_places=4, default=0)

    # ── Metadata ─────────────────────────────────────────────────────────────
    data_sources      = models.JSONField(default=list)   # which sources contributed
    is_complete       = models.BooleanField(default=False)
    computed_at       = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('period', 'branch')]
        ordering = ['-period']
        verbose_name        = 'لقطة مالية'
        verbose_name_plural = 'اللقطات المالية'
        indexes = [models.Index(fields=['period', 'branch'])]

    def __str__(self):
        b = self.branch.name if self.branch else 'موحد'
        return f'{self.period} | {b} | صافي: {self.net_profit:,.0f}'


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 9 — ETL AUDIT LOG
# ══════════════════════════════════════════════════════════════════════════════

SYNC_STATUS_CHOICES = [
    ('pending',  'قيد الانتظار'),
    ('running',  'جارٍ'),
    ('success',  'نجح'),
    ('partial',  'جزئي'),
    ('failed',   'فشل'),
]

SYNC_TYPE_CHOICES = [
    ('discovery',    'اكتشاف المخطط'),
    ('full',         'كامل'),
    ('incremental',  'تدريجي'),
    ('snapshot',     'لقطة فقط'),
]


class FinanceSyncRun(models.Model):
    """
    Audit log for every finance sync / discovery run.
    """
    started_at   = models.DateTimeField(auto_now_add=True)
    finished_at  = models.DateTimeField(null=True, blank=True)
    status       = models.CharField(max_length=20, choices=SYNC_STATUS_CHOICES, default='pending')
    sync_type    = models.CharField(max_length=20, choices=SYNC_TYPE_CHOICES, default='incremental')
    period_start = models.DateField(null=True, blank=True)
    period_end   = models.DateField(null=True, blank=True)
    records_synced   = models.JSONField(default=dict)   # {table_name: row_count}
    errors           = models.JSONField(default=list)   # [{table, message}]
    triggered_by     = models.CharField(max_length=100, blank=True)
    notes            = models.TextField(blank=True)
    duration_seconds = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name        = 'تشغيل مزامنة مالية'
        verbose_name_plural = 'تشغيلات المزامنة المالية'

    def __str__(self):
        return f'{self.get_sync_type_display()} | {self.started_at:%Y-%m-%d %H:%M} | {self.status}'

    def mark_done(self, success: bool = True, status: str | None = None, records: dict | None = None):
        """
        Convenience method to close out a sync run.
        ``success`` overrides ``status`` if both supplied.
        ``records`` populates records_synced.
        """
        self.finished_at = timezone.now()
        if status:
            self.status = status
        else:
            self.status = 'success' if success else 'failed'
        if records:
            self.records_synced = records
        if self.started_at:
            self.duration_seconds = int((self.finished_at - self.started_at).total_seconds())
        self.save(update_fields=['finished_at', 'status', 'duration_seconds', 'records_synced'])
