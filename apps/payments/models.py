"""
apps/payments/models.py

Module 6: External Payment Tracking
Two models: ExternalPayment, PaymentReconciliationLog
"""
from datetime import date

from django.conf import settings
from django.db import models


class ExternalPayment(models.Model):
    """
    Records a payment made outside the SOFTECH ERP cashier
    (e.g. InstaPay, Vodafone Cash, bank transfer).
    """

    METHOD_CASH          = 'cash'
    METHOD_INSTAPAY      = 'instapay'
    METHOD_VODAFONE_CASH = 'vodafone_cash'
    METHOD_ORANGE_CASH   = 'orange_cash'
    METHOD_ETISALAT_CASH = 'etisalat_cash'
    METHOD_FAWRY         = 'fawry'
    METHOD_POS_TERMINAL  = 'pos_terminal'
    METHOD_CASH_DEPOSIT  = 'cash_deposit'
    METHOD_BANK_TRANSFER = 'bank_transfer'
    METHOD_OTHER         = 'other'

    METHOD_CHOICES = [
        (METHOD_CASH,          'كاش'),
        (METHOD_INSTAPAY,      'إنستاباي'),
        (METHOD_VODAFONE_CASH, 'فودافون كاش'),
        (METHOD_ORANGE_CASH,   'أورنج كاش'),
        (METHOD_ETISALAT_CASH, 'اتصالات كاش'),
        (METHOD_FAWRY,         'فوري'),
        (METHOD_POS_TERMINAL,  'POS'),
        (METHOD_CASH_DEPOSIT,  'إيداع نقدي'),
        (METHOD_BANK_TRANSFER, 'تحويل بنكي'),
        (METHOD_OTHER,         'أخرى'),
    ]

    STATUS_PENDING      = 'pending'
    STATUS_CONFIRMED    = 'confirmed'
    STATUS_RECONCILED   = 'reconciled'
    STATUS_DISPUTED     = 'disputed'
    STATUS_CANCELLED    = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING,    'انتظار'),
        (STATUS_CONFIRMED,  'مؤكد'),
        (STATUS_RECONCILED, 'مُسوَّى'),
        (STATUS_DISPUTED,   'متنازع عليه'),
        (STATUS_CANCELLED,  'ملغى'),
    ]

    # SOFTECH references
    softech_invoice_code = models.CharField(
        max_length=100, blank=True, db_index=True,
        verbose_name='كود فاتورة SOFTECH',
    )
    softech_doc_number = models.CharField(
        max_length=100, blank=True,
        verbose_name='رقم مستند SOFTECH',
    )

    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.CASCADE,
        related_name='external_payments',
        verbose_name='الفرع',
    )
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='external_payments',
        verbose_name='العميل',
    )
    customer_name  = models.CharField(max_length=255, blank=True, verbose_name='اسم العميل')
    customer_phone = models.CharField(max_length=50, blank=True, verbose_name='هاتف العميل')

    method = models.CharField(
        max_length=20, choices=METHOD_CHOICES,
        verbose_name='طريقة الدفع',
    )
    amount = models.DecimalField(
        max_digits=12, decimal_places=2,
        verbose_name='المبلغ المدفوع',
    )
    invoice_total = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name='إجمالي الفاتورة',
    )
    is_partial = models.BooleanField(default=False, verbose_name='دفع جزئي')
    remaining_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name='المبلغ المتبقي',
    )
    reference_number = models.CharField(
        max_length=200, blank=True, db_index=True,
        verbose_name='رقم المرجع / رقم التحويل',
    )
    screenshot = models.ImageField(
        upload_to='payments/screenshots/',
        null=True, blank=True,
        verbose_name='صورة الإيصال',
    )
    payment_date = models.DateField(
        default=date.today,
        verbose_name='تاريخ الدفع',
    )
    status = models.CharField(
        max_length=15, choices=STATUS_CHOICES,
        default=STATUS_PENDING, db_index=True,
        verbose_name='الحالة',
    )
    notes = models.TextField(blank=True, verbose_name='ملاحظات')

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_payments',
        verbose_name='أنشأ بواسطة',
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='confirmed_payments',
        verbose_name='أكد بواسطة',
    )
    confirmed_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت التأكيد')
    created_at   = models.DateTimeField(auto_now_add=True, verbose_name='تاريخ الإنشاء')
    updated_at   = models.DateTimeField(auto_now=True, verbose_name='آخر تعديل')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'دفعة خارجية'
        verbose_name_plural = 'الدفعات الخارجية'
        indexes = [
            models.Index(fields=['method'],       name='pay_method'),
            models.Index(fields=['status'],        name='pay_status'),
            models.Index(fields=['payment_date'],  name='pay_payment_date'),
            models.Index(fields=['branch'],        name='pay_branch'),
            models.Index(fields=['payment_date', 'branch'], name='pay_date_branch'),
        ]

    def __str__(self):
        return (
            f'دفعة #{self.pk} — {self.get_method_display()} '
            f'{self.amount} ج.م ({self.get_status_display()})'
        )


class PaymentReconciliationLog(models.Model):
    """Immutable audit trail for every action taken on an ExternalPayment."""
    payment = models.ForeignKey(
        ExternalPayment,
        on_delete=models.CASCADE,
        related_name='reconciliation_logs',
        verbose_name='الدفعة',
    )
    action = models.CharField(
        max_length=50,
        verbose_name='الإجراء',
        help_text='confirmed / disputed / reconciled / note_added',
    )
    notes    = models.TextField(blank=True, verbose_name='ملاحظات')
    variance = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name='الفارق',
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='بواسطة',
    )
    performed_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت الإجراء')

    class Meta:
        ordering = ['performed_at']
        verbose_name = 'سجل تسوية دفعة'
        verbose_name_plural = 'سجلات تسوية الدفعات'

    def __str__(self):
        return f'دفعة #{self.payment_id}: {self.action} — {self.performed_at:%Y-%m-%d %H:%M}'


# ══════════════════════════════════════════════════════════════════════════════
# PAYMENT AUDIT — Bank / Wallet Statement Reconciliation
# ══════════════════════════════════════════════════════════════════════════════

class BankStatementImport(models.Model):
    """
    One uploaded bank/wallet statement file per import session.
    Lines are parsed into BankStatementLine rows.
    """
    STATUS_PENDING    = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED  = 'completed'
    STATUS_FAILED     = 'failed'

    STATUS_CHOICES = [
        (STATUS_PENDING,    'في الانتظار'),
        (STATUS_PROCESSING, 'قيد المعالجة'),
        (STATUS_COMPLETED,  'مكتمل'),
        (STATUS_FAILED,     'فشل'),
    ]

    branch          = models.ForeignKey(
        'branches.Branch', on_delete=models.PROTECT,
        related_name='statement_imports', verbose_name='الفرع',
    )
    bank_name       = models.CharField(max_length=100, verbose_name='اسم البنك / المحفظة')
    account_number  = models.CharField(max_length=50, blank=True, verbose_name='رقم الحساب')
    payment_method  = models.CharField(
        max_length=20, choices=ExternalPayment.METHOD_CHOICES,
        verbose_name='طريقة الدفع',
    )
    statement_from  = models.DateField(verbose_name='من تاريخ')
    statement_to    = models.DateField(verbose_name='إلى تاريخ')
    raw_file        = models.FileField(
        upload_to='payments/statements/%Y/%m/',
        verbose_name='ملف الكشف',
    )
    status          = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default=STATUS_PENDING,
        db_index=True, verbose_name='الحالة',
    )
    total_lines     = models.PositiveIntegerField(default=0, verbose_name='إجمالي السطور')
    matched_lines   = models.PositiveIntegerField(default=0, verbose_name='سطور مطابَقة')
    unmatched_lines = models.PositiveIntegerField(default=0, verbose_name='سطور غير مطابَقة')
    error_message   = models.TextField(blank=True, verbose_name='رسالة الخطأ')
    imported_by     = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='statement_imports',
        verbose_name='رُفع بواسطة',
    )
    imported_at     = models.DateTimeField(auto_now_add=True, verbose_name='وقت الرفع')
    completed_at    = models.DateTimeField(null=True, blank=True, verbose_name='وقت الإكمال')

    class Meta:
        ordering            = ['-imported_at']
        verbose_name        = 'استيراد كشف حساب'
        verbose_name_plural = 'استيرادات كشوف الحسابات'

    def __str__(self):
        return f'{self.bank_name} | {self.statement_from} → {self.statement_to} | {self.branch}'


class BankStatementLine(models.Model):
    """
    One transaction row parsed from a BankStatementImport.
    Matched to ExternalPayment by the PaymentAuditService.
    """
    MATCH_AUTO_EXACT  = 'auto_exact'
    MATCH_AUTO_FUZZY  = 'auto_fuzzy'
    MATCH_MANUAL      = 'manual'
    MATCH_UNMATCHED   = 'unmatched'

    MATCH_METHOD_CHOICES = [
        (MATCH_AUTO_EXACT, 'تطابق تلقائي دقيق'),
        (MATCH_AUTO_FUZZY, 'تطابق تلقائي تقريبي'),
        (MATCH_MANUAL,     'تطابق يدوي'),
        (MATCH_UNMATCHED,  'غير مطابَق'),
    ]

    statement_import   = models.ForeignKey(
        BankStatementImport, on_delete=models.CASCADE,
        related_name='lines', verbose_name='الكشف',
    )
    transaction_date   = models.DateField(verbose_name='تاريخ الحركة', db_index=True)
    value_date         = models.DateField(null=True, blank=True, verbose_name='تاريخ القيمة')
    reference          = models.CharField(max_length=200, blank=True, db_index=True, verbose_name='رقم المرجع')
    description        = models.CharField(max_length=500, blank=True, verbose_name='البيان')
    debit              = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='مدين')
    credit             = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='دائن')
    balance            = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True, verbose_name='الرصيد')

    matched_payment    = models.ForeignKey(
        ExternalPayment, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='statement_lines',
        verbose_name='الدفعة المطابِقة',
    )
    match_confidence   = models.DecimalField(
        max_digits=4, decimal_places=3, default=0,
        verbose_name='درجة الثقة (0–1)',
    )
    match_method       = models.CharField(
        max_length=15, choices=MATCH_METHOD_CHOICES, default=MATCH_UNMATCHED,
        db_index=True, verbose_name='طريقة المطابقة',
    )
    matched_by         = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='manual_matches',
        verbose_name='طابَق بواسطة',
    )
    matched_at         = models.DateTimeField(null=True, blank=True, verbose_name='وقت المطابقة')

    class Meta:
        ordering            = ['transaction_date', 'id']
        verbose_name        = 'سطر كشف حساب'
        verbose_name_plural = 'سطور كشوف الحسابات'
        indexes = [
            models.Index(fields=['statement_import', 'match_method'], name='stmt_line_import_match_idx'),
            models.Index(fields=['transaction_date', 'credit'],       name='stmt_line_date_credit_idx'),
        ]

    def __str__(self):
        amount = self.credit or self.debit
        return f'{self.transaction_date} | {self.reference} | {amount:,.2f}'


class PaymentException(models.Model):
    """
    A flagged anomaly detected by the PaymentAuditService.
    Links to an ExternalPayment, a BankStatementLine, or both.
    Escalates to apps.audit.AbuseFlag for critical fraud signals.
    """
    TYPE_MISSING       = 'missing'         # payment in ERP, absent from bank statement
    TYPE_UNRECORDED    = 'unrecorded'      # in bank statement, absent from ERP
    TYPE_DUPLICATE     = 'duplicate'       # same amount/cashier/day twice
    TYPE_PARTIAL       = 'partial'         # amount mismatch (invoice vs paid)
    TYPE_WRONG_BRANCH  = 'wrong_branch'    # payment registered at wrong branch
    TYPE_WRONG_AMOUNT  = 'wrong_amount'    # variance > tolerance
    TYPE_WRONG_CASHIER = 'wrong_cashier'   # different cashier from expected
    TYPE_DELAYED       = 'delayed'         # settlement delay > threshold
    TYPE_ANOMALY       = 'anomaly'         # statistical outlier / fraud signal

    TYPE_CHOICES = [
        (TYPE_MISSING,       'دفعة مفقودة من الكشف'),
        (TYPE_UNRECORDED,    'حركة بنكية غير مُسجَّلة'),
        (TYPE_DUPLICATE,     'دفعة مكررة'),
        (TYPE_PARTIAL,       'دفع جزئي'),
        (TYPE_WRONG_BRANCH,  'فرع خاطئ'),
        (TYPE_WRONG_AMOUNT,  'مبلغ خاطئ'),
        (TYPE_WRONG_CASHIER, 'كاشير خاطئ'),
        (TYPE_DELAYED,       'تسوية متأخرة'),
        (TYPE_ANOMALY,       'شذوذ / إشارة احتيال'),
    ]

    SEVERITY_INFO     = 'info'
    SEVERITY_WARNING  = 'warning'
    SEVERITY_CRITICAL = 'critical'

    SEVERITY_CHOICES = [
        (SEVERITY_INFO,     'معلومة'),
        (SEVERITY_WARNING,  'تحذير'),
        (SEVERITY_CRITICAL, 'حرج'),
    ]

    STATUS_OPEN          = 'open'
    STATUS_INVESTIGATING = 'investigating'
    STATUS_RESOLVED      = 'resolved'
    STATUS_DISMISSED     = 'dismissed'

    STATUS_CHOICES = [
        (STATUS_OPEN,          'مفتوح'),
        (STATUS_INVESTIGATING, 'قيد التحقيق'),
        (STATUS_RESOLVED,      'محلول'),
        (STATUS_DISMISSED,     'مرفوض'),
    ]

    payment        = models.ForeignKey(
        ExternalPayment, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='exceptions',
        verbose_name='الدفعة',
    )
    statement_line = models.ForeignKey(
        BankStatementLine, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='exceptions',
        verbose_name='سطر الكشف',
    )
    exception_type = models.CharField(
        max_length=20, choices=TYPE_CHOICES, db_index=True,
        verbose_name='نوع الاستثناء',
    )
    severity       = models.CharField(
        max_length=10, choices=SEVERITY_CHOICES, default=SEVERITY_WARNING,
        db_index=True, verbose_name='الخطورة',
    )
    anomaly_score  = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        verbose_name='درجة الشذوذ (0–100)',
    )
    detail         = models.TextField(blank=True, verbose_name='تفاصيل')
    status         = models.CharField(
        max_length=15, choices=STATUS_CHOICES, default=STATUS_OPEN,
        db_index=True, verbose_name='الحالة',
    )
    assigned_to    = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='payment_exceptions_assigned',
        verbose_name='مُسنَد إلى',
    )
    resolved_by    = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='payment_exceptions_resolved',
        verbose_name='حُلَّ بواسطة',
    )
    resolved_at      = models.DateTimeField(null=True, blank=True, verbose_name='وقت الحل')
    resolution_notes = models.TextField(blank=True, verbose_name='ملاحظات الحل')
    # FK to AbuseFlag for critical anomalies (set by PaymentAuditService)
    abuse_flag_id    = models.PositiveIntegerField(null=True, blank=True, verbose_name='رقم إشارة الاحتيال')
    created_at       = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='وقت الإنشاء')

    class Meta:
        ordering            = ['-created_at']
        verbose_name        = 'استثناء دفعة'
        verbose_name_plural = 'استثناءات الدفعات'
        indexes = [
            models.Index(fields=['status', 'severity'],       name='payexc_status_sev_idx'),
            models.Index(fields=['exception_type', 'status'], name='payexc_type_status_idx'),
        ]

    def __str__(self):
        return f'[{self.get_severity_display()}] {self.get_exception_type_display()} | {self.get_status_display()}'
