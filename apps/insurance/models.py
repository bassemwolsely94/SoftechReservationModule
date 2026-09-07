"""
apps/insurance/models.py

Insurance Claims Processing & Invoicing Module (مطالبات التأمين)

Design rules:
  1. Softech creates the Motalba — this module only imports and processes it.
  2. InsuranceClaimPrescription + InsuranceClaimLine are FROZEN at import time.
     Never recalculated from live Softech data.
  3. Adjustments (InsuranceClaimAdjustment) store DELTAS over the frozen snapshot.
  4. Final invoice dataset = snapshot + adjustments + manual_rx - exclusions + supplements.

Layer map:
  Contract Setup  → InsuranceClient, InsuranceSubClient, InsuranceContract
  Import          → InsuranceClaim, InsuranceClaimPrescription, InsuranceClaimLine
  Adjustments     → InsuranceClaimAdjustment, InsuranceClaimManualRx,
                     InsuranceClaimExclusion, InsuranceClaimSupplement
  Collections     → InsurancePayment, InsuranceDeduction
"""
from decimal import Decimal
from django.db import models


# ── ITEM ORIGIN CLASSIFICATION ─────────────────────────────────────────────────

ITEM_CATEGORY_LOCAL    = 'local'
ITEM_CATEGORY_IMPORTED = 'imported'
ITEM_CATEGORY_TARSIA   = 'tarsia'

ITEM_CATEGORY_CHOICES = [
    (ITEM_CATEGORY_LOCAL,    'محلى'),
    (ITEM_CATEGORY_IMPORTED, 'مستورد'),
    (ITEM_CATEGORY_TARSIA,   'ترسية'),
]


# ═══════════════════════════════════════════════════════════════════════════════
# CONTRACT SETUP LAYER
# ═══════════════════════════════════════════════════════════════════════════════

class InsuranceClient(models.Model):
    """
    Top-level insurance entity (e.g. شركة جنوب القاهرة لتوزيع الكهرباء).
    Maps to a personcode / personsdata entry in Softech.
    """
    name              = models.CharField(max_length=200, verbose_name='اسم جهة التأمين')
    name_short        = models.CharField(max_length=60, blank=True, verbose_name='الاسم المختصر')
    softech_personcode = models.CharField(
        max_length=20, blank=True, db_index=True,
        verbose_name='كود العميل في سوفتك',
        help_text='personcode في stktransm لتصفية المعاملات'
    )
    address           = models.TextField(blank=True, verbose_name='العنوان')
    contact_name      = models.CharField(max_length=100, blank=True, verbose_name='اسم المسؤول')
    contact_phone     = models.CharField(max_length=30, blank=True, verbose_name='هاتف التواصل')
    notes             = models.TextField(blank=True, verbose_name='ملاحظات')
    is_active         = models.BooleanField(default=True, verbose_name='نشط')
    created_at        = models.DateTimeField(auto_now_add=True)
    updated_at        = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'جهة تأمين'
        verbose_name_plural = 'جهات التأمين'
        ordering            = ['name']

    def __str__(self):
        return self.name_short or self.name


class InsuranceSubClient(models.Model):
    """
    Subdivision of an insurance client (e.g. العاملين, المعاشات, الأسر).
    Each sub-client has its own personcode (or shares the parent's) and its own contract.
    """
    client            = models.ForeignKey(
        InsuranceClient, on_delete=models.CASCADE,
        related_name='subclients', verbose_name='جهة التأمين'
    )
    name              = models.CharField(max_length=200, verbose_name='اسم الفئة')
    softech_personcode = models.CharField(
        max_length=20, blank=True, db_index=True,
        verbose_name='كود الفئة في سوفتك',
        help_text='إذا كان مختلفاً عن كود جهة التأمين الرئيسية'
    )
    # Additional Softech person codes for this sub-client (comma-separated)
    additional_personcodes = models.TextField(
        blank=True, verbose_name='أكواد إضافية في سوفتك',
        help_text='أكواد personcode إضافية مفصولة بفاصلة'
    )
    notes             = models.TextField(blank=True, verbose_name='ملاحظات')
    is_active         = models.BooleanField(default=True, verbose_name='نشط')
    created_at        = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'فئة عملاء'
        verbose_name_plural = 'فئات العملاء'
        ordering            = ['client', 'name']
        unique_together     = [['client', 'name']]

    def __str__(self):
        return f'{self.client} — {self.name}'

    def get_all_personcodes(self):
        """Return list of all Softech person codes for this sub-client."""
        codes = []
        if self.softech_personcode:
            codes.append(self.softech_personcode.strip())
        elif self.client.softech_personcode:
            codes.append(self.client.softech_personcode.strip())
        if self.additional_personcodes:
            codes.extend(
                c.strip() for c in self.additional_personcodes.split(',')
                if c.strip()
            )
        return list(dict.fromkeys(codes))  # deduplicate preserving order


class InsuranceContract(models.Model):
    """
    Discount rules for a sub-client during a specific period.
    One contract = one set of discount rates applicable to one Motalba period.

    Discount formula per prescription:
        net = (local_total × (1 − local_discount_pct/100))
            + (imported_total × (1 − imported_discount_pct/100))
            + (tarsia_total × (1 − tarsia_discount_pct/100))
    """
    subclient             = models.ForeignKey(
        InsuranceSubClient, on_delete=models.CASCADE,
        related_name='contracts', verbose_name='فئة العملاء'
    )
    name                  = models.CharField(
        max_length=100, blank=True, verbose_name='اسم العقد',
        help_text='مثال: عقد 2026 — العاملين'
    )
    effective_from        = models.DateField(verbose_name='تاريخ بداية العقد')
    effective_to          = models.DateField(null=True, blank=True, verbose_name='تاريخ نهاية العقد')

    local_discount_pct    = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('17.00'),
        verbose_name='نسبة خصم المحلى %'
    )
    imported_discount_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('6.00'),
        verbose_name='نسبة خصم المستورد %'
    )
    tarsia_discount_pct   = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        verbose_name='نسبة خصم الترسية %'
    )

    # Softech ptclassifcode values to include (default: '15'=insurance, '10'=contract)
    softech_ptclassifcodes = models.CharField(
        max_length=100, default='15,10',
        verbose_name='أكواد التصنيف في سوفتك',
        help_text='ptclassifcode مفصولة بفاصلة — 15=تأمين صحي، 10=تعاقدات'
    )

    notes                 = models.TextField(blank=True, verbose_name='ملاحظات')
    created_at            = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'عقد تأمين'
        verbose_name_plural = 'عقود التأمين'
        ordering            = ['-effective_from']

    def __str__(self):
        return (
            self.name or
            f'{self.subclient} — {self.effective_from.strftime("%m/%Y")}'
        )

    def get_ptclassifcodes(self):
        return [c.strip() for c in self.softech_ptclassifcodes.split(',') if c.strip()]


# ═══════════════════════════════════════════════════════════════════════════════
# CLAIM (MOTALBA) — MASTER RECORD
# ═══════════════════════════════════════════════════════════════════════════════

class InsuranceClaim(models.Model):

    STATUS_DRAFT          = 'draft'
    STATUS_READY          = 'ready'
    STATUS_SUBMITTED      = 'submitted'
    STATUS_UNDER_REVIEW   = 'under_review'
    STATUS_PARTIALLY_PAID = 'partially_paid'
    STATUS_PAID           = 'paid'
    STATUS_REJECTED       = 'rejected'
    STATUS_CANCELLED      = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_DRAFT,          'مسودة'),
        (STATUS_READY,          'جاهزة للطباعة'),
        (STATUS_SUBMITTED,      'مُقدَّمة'),
        (STATUS_UNDER_REVIEW,   'قيد المراجعة'),
        (STATUS_PARTIALLY_PAID, 'مدفوعة جزئياً'),
        (STATUS_PAID,           'مدفوعة'),
        (STATUS_REJECTED,       'مرفوضة'),
        (STATUS_CANCELLED,      'ملغاة'),
    ]

    # ── Identity ───────────────────────────────────────────────────────────────
    claim_number   = models.CharField(
        max_length=30, unique=True, verbose_name='رقم المطالبة',
        help_text='مثال: MT-2026-00001'
    )
    subclient      = models.ForeignKey(
        InsuranceSubClient, on_delete=models.PROTECT,
        related_name='claims', verbose_name='فئة العملاء'
    )
    contract       = models.ForeignKey(
        InsuranceContract, on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='claims', verbose_name='العقد المُطبَّق'
    )

    # ── Period ─────────────────────────────────────────────────────────────────
    period_from    = models.DateField(verbose_name='من تاريخ')
    period_to      = models.DateField(verbose_name='إلى تاريخ')

    # ── Softech Import Info ─────────────────────────────────────────────────────
    softech_motalba_no = models.CharField(
        max_length=30, blank=True, verbose_name='رقم المطالبة في سوفتك'
    )
    imported_personcodes = models.TextField(
        blank=True, verbose_name='أكواد سوفتك المستخدمة',
        help_text='personcode values used for import — comma separated'
    )
    imported_branches    = models.TextField(
        blank=True, verbose_name='الفروع المُدرجة',
        help_text='branchcodes comma separated — empty = all branches'
    )
    imported_at          = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ الاستيراد')
    imported_by          = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='imported_claims',
        verbose_name='استُورد بواسطة'
    )

    # ── Frozen Snapshot Totals (calculated at import, never recalculated) ──────
    snapshot_rx_count         = models.PositiveIntegerField(default=0, verbose_name='عدد الروشتات (snapshot)')
    snapshot_local_before     = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='المحلى قبل الخصم (snapshot)')
    snapshot_imported_before  = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='المستورد قبل الخصم (snapshot)')
    snapshot_tarsia_before    = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='الترسية قبل الخصم (snapshot)')
    snapshot_gross_before     = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='الإجمالى قبل الخصم (snapshot)')
    snapshot_total_discount   = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='إجمالى الخصم (snapshot)')
    snapshot_net_after        = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='صافى الفاتورة (snapshot)')

    # ── Final Totals (recalculated after adjustments) ─────────────────────────
    final_rx_count         = models.PositiveIntegerField(default=0, verbose_name='عدد الروشتات النهائي')
    final_local_before     = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='المحلى قبل الخصم')
    final_imported_before  = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='المستورد قبل الخصم')
    final_tarsia_before    = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='الترسية قبل الخصم')
    final_gross_before     = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='الإجمالى قبل الخصم')
    final_total_discount   = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='إجمالى الخصم')
    final_net_after        = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='صافى الفاتورة')

    # ── Discount rates frozen at claim creation ────────────────────────────────
    applied_local_disc_pct    = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name='نسبة خصم المحلى المُطبَّقة %')
    applied_imported_disc_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name='نسبة خصم المستورد المُطبَّقة %')
    applied_tarsia_disc_pct   = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name='نسبة خصم الترسية المُطبَّقة %')

    # ── Status & workflow ──────────────────────────────────────────────────────
    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT, verbose_name='الحالة')
    submitted_at   = models.DateTimeField(null=True, blank=True, verbose_name='تاريخ التقديم')
    expected_payment_date = models.DateField(null=True, blank=True, verbose_name='تاريخ التحصيل المتوقع')

    notes          = models.TextField(blank=True, verbose_name='ملاحظات')
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    created_by     = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_claims',
        verbose_name='أُنشئت بواسطة'
    )

    class Meta:
        verbose_name        = 'مطالبة تأمين'
        verbose_name_plural = 'مطالبات التأمين'
        ordering            = ['-period_from', '-claim_number']

    def __str__(self):
        return f'{self.claim_number} — {self.subclient}'

    @property
    def client(self):
        return self.subclient.client

    # Once a claim is submitted (or beyond), its content is locked: no edits to
    # prescriptions / adjustments / exclusions / manual-rx / re-import.  Further
    # changes must be made through a supplement (ملحق) to preserve the submitted
    # record.  Draft / ready / rejected / cancelled remain editable.
    LOCKED_STATUSES = ('submitted', 'under_review', 'partially_paid', 'paid')

    @property
    def is_locked(self):
        return self.status in self.LOCKED_STATUSES


# ═══════════════════════════════════════════════════════════════════════════════
# FROZEN SNAPSHOT — IMPORTED FROM SOFTECH
# ═══════════════════════════════════════════════════════════════════════════════

class InsuranceClaimPrescription(models.Model):
    """
    One prescription (روشتة / فاتورة) imported from Softech.
    Values are FROZEN at import time. Never updated from live Softech data.

    sequence: display order (م) in the invoice — 1-based per claim day.
    """
    claim             = models.ForeignKey(
        InsuranceClaim, on_delete=models.CASCADE,
        related_name='prescriptions', verbose_name='المطالبة'
    )
    # Softech reference
    softech_docnumber = models.CharField(max_length=30, verbose_name='رقم الفاتورة في سوفتك')
    softech_docdate   = models.DateField(verbose_name='تاريخ الصرف')
    softech_branchcode = models.CharField(max_length=10, blank=True, verbose_name='كود الفرع')
    softech_personcode = models.CharField(max_length=20, blank=True, verbose_name='كود العميل')

    # Patient info (from Softech — frozen at import)
    patient_name      = models.CharField(max_length=200, blank=True, verbose_name='اسم المريض')

    # Display sequence within the claim (م)
    sequence          = models.PositiveIntegerField(default=0, verbose_name='م')

    # ── Frozen financial snapshot ──────────────────────────────────────────────
    local_before      = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='المحلى قبل الخصم')
    imported_before   = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='المستورد قبل الخصم')
    tarsia_before     = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الترسية قبل الخصم')
    gross_before      = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الإجمالى قبل الخصم')
    local_discount    = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='خصم المحلى')
    imported_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='خصم المستورد')
    tarsia_discount   = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='خصم الترسية')
    total_discount    = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='إجمالى الخصم')
    net_after         = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='صافى الفاتورة')
    # SOFTECH's own stored net (docvaluerequired) — REFERENCE ONLY, for flagging.
    # net_after uses the Power-Query formula; if it differs from softech_net the
    # prescription is highlighted for review (possible item misclassification).
    softech_net       = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                                            verbose_name='صافى سوفتك (مرجعي)')

    class Meta:
        verbose_name        = 'روشتة مطالبة'
        verbose_name_plural = 'روشتات المطالبة'
        ordering            = ['softech_docdate', 'sequence']
        unique_together     = [['claim', 'softech_docnumber']]

    @property
    def softech_net_diff(self):
        """net_after − softech_net (None when no reference). Non-zero ⇒ review."""
        if self.softech_net is None:
            return None
        from decimal import Decimal
        return (Decimal(str(self.net_after or 0)) - Decimal(str(self.softech_net))).quantize(Decimal('0.01'))

    @property
    def softech_mismatch(self):
        d = self.softech_net_diff
        from decimal import Decimal
        return d is not None and abs(d) > Decimal('0.01')

    def __str__(self):
        return f'فاتورة {self.softech_docnumber} — {self.patient_name}'


class InsuranceClaimLine(models.Model):
    """
    One item line within a prescription. FROZEN at import.
    Used for audit drill-down: Claim → Prescription → Items → Discount calc.
    """
    prescription      = models.ForeignKey(
        InsuranceClaimPrescription, on_delete=models.CASCADE,
        related_name='lines', verbose_name='الروشتة'
    )
    softech_itemcode  = models.CharField(max_length=10, verbose_name='كود الصنف')
    item_name         = models.CharField(max_length=200, blank=True, verbose_name='اسم الصنف')
    item_category     = models.CharField(
        max_length=10, choices=ITEM_CATEGORY_CHOICES,
        default=ITEM_CATEGORY_LOCAL, verbose_name='تصنيف الصنف'
    )
    # Raw Softech classification fields (for audit)
    softech_origin_code    = models.CharField(max_length=10, blank=True, verbose_name='كود الأصل')
    softech_imported_flag  = models.BooleanField(default=False, verbose_name='مستورد في سوفتك')
    softech_store_classif  = models.CharField(max_length=10, blank=True, verbose_name='تصنيف التعاقد')

    quantity          = models.DecimalField(max_digits=10, decimal_places=3, default=1, verbose_name='الكمية')
    unit_price        = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name='السعر')
    line_total        = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الإجمالى')

    # Calculated discount for this line
    discount_pct      = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name='نسبة الخصم %')
    discount_amt      = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='قيمة الخصم')
    net_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الصافى')

    # Manual line edit (item swap / qty / price) — gated behind an unlock button
    # in the UI.  original_json snapshots the pre-edit line so it can be reset.
    is_manually_edited = models.BooleanField(default=False, verbose_name='عُدِّل يدوياً')
    original_json      = models.JSONField(null=True, blank=True, verbose_name='القيم الأصلية')

    class Meta:
        verbose_name        = 'بند روشتة'
        verbose_name_plural = 'بنود الروشتة'
        ordering            = ['id']

    def __str__(self):
        return f'{self.item_name} × {self.quantity}'


# ═══════════════════════════════════════════════════════════════════════════════
# ADJUSTMENT LAYER — USER OVERRIDES (never mutates snapshot)
# ═══════════════════════════════════════════════════════════════════════════════

class InsuranceClaimAdjustment(models.Model):
    """
    User override for one prescription's financial values.
    The final invoice uses adjusted values when present; snapshot otherwise.

    Stores full override values (not deltas) — simpler to reason about.
    Original snapshot values are always recoverable from InsuranceClaimPrescription.
    """
    prescription       = models.OneToOneField(
        InsuranceClaimPrescription, on_delete=models.CASCADE,
        related_name='adjustment', verbose_name='الروشتة'
    )
    # Override amounts — None means "use snapshot value"
    local_before       = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='المحلى قبل الخصم (معدَّل)')
    imported_before    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='المستورد قبل الخصم (معدَّل)')
    tarsia_before      = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='الترسية قبل الخصم (معدَّل)')
    # Override net directly (for cases where user knows the final value)
    net_override       = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='صافى الفاتورة (تجاوز مباشر)')

    reason             = models.TextField(verbose_name='سبب التعديل')
    adjusted_by        = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, related_name='+', verbose_name='عُدِّل بواسطة'
    )
    adjusted_at        = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'تعديل روشتة'
        verbose_name_plural = 'تعديلات الروشتات'

    def __str__(self):
        return f'تعديل — {self.prescription}'


class InsuranceClaimManualRx(models.Model):
    """
    Manually added prescription — fetched from Softech by receipt number.
    May belong to a different customer / date range than the claim.
    """
    POSITION_BEFORE = 'before'
    POSITION_AFTER  = 'after'
    POSITION_DATE   = 'date'

    POSITION_CHOICES = [
        (POSITION_BEFORE, 'قبل الفترة (ملحق سابق)'),
        (POSITION_AFTER,  'بعد الفترة (ملحق لاحق)'),
        (POSITION_DATE,   'يوم محدد'),
    ]

    claim              = models.ForeignKey(
        InsuranceClaim, on_delete=models.CASCADE,
        related_name='manual_rx', verbose_name='المطالبة'
    )
    softech_docnumber  = models.CharField(max_length=30, verbose_name='رقم الفاتورة في سوفتك')
    softech_docdate    = models.DateField(verbose_name='تاريخ الصرف الفعلي')
    softech_branchcode = models.CharField(max_length=10, blank=True, verbose_name='الفرع')
    softech_personcode = models.CharField(max_length=20, blank=True, verbose_name='كود العميل الأصلي')
    patient_name       = models.CharField(max_length=200, blank=True, verbose_name='اسم المريض')
    original_client_warning = models.TextField(
        blank=True, verbose_name='تحذير',
        help_text='Populated if the Rx belongs to a different client or date range'
    )

    local_before       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    imported_before    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tarsia_before      = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_before       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    local_discount     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    imported_discount  = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tarsia_discount    = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_discount     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    net_after          = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Print position
    position           = models.CharField(max_length=10, choices=POSITION_CHOICES, default=POSITION_BEFORE, verbose_name='موضع الطباعة')
    print_date         = models.DateField(
        null=True, blank=True, verbose_name='تاريخ الطباعة',
        help_text='Used when position=date — the invoice date this Rx prints under'
    )
    sequence           = models.PositiveIntegerField(default=0, verbose_name='ترتيب')

    is_excluded        = models.BooleanField(default=False, verbose_name='مُستثناة')
    is_manually_edited = models.BooleanField(default=False, verbose_name='عُدِّلت يدوياً')

    added_by           = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, related_name='+', verbose_name='أُضيف بواسطة'
    )
    reason             = models.TextField(blank=True, verbose_name='سبب الإضافة')
    added_at           = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'روشتة مضافة يدوياً'
        verbose_name_plural = 'الروشتات المضافة يدوياً'
        ordering            = ['position', 'print_date', 'sequence']

    def __str__(self):
        return f'إضافة يدوية — {self.softech_docnumber}'


class InsuranceClaimExclusion(models.Model):
    """
    Soft-exclude a prescription from print output without deleting the snapshot.
    The prescription remains in the database for audit purposes.
    """
    prescription  = models.OneToOneField(
        InsuranceClaimPrescription, on_delete=models.CASCADE,
        related_name='exclusion', verbose_name='الروشتة'
    )
    reason        = models.TextField(verbose_name='سبب الاستثناء')
    excluded_by   = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, related_name='+', verbose_name='استُثني بواسطة'
    )
    excluded_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'روشتة مستثناة'
        verbose_name_plural = 'الروشتات المستثناة'

    def __str__(self):
        return f'استثناء — {self.prescription}'


class InsuranceClaimSupplement(models.Model):
    """
    ملحق — a supplement block attached to the claim.

    Types:
      before_claim  → ملحق سابق: prints before the first day of the claim
      within_claim  → ملحق يوم: prints under a specific date inside the claim
      after_claim   → ملحق لاحق: prints after the last day
      standalone    → ملحق مستقل: separate printout with its own number

    A supplement is a pre-aggregated row (not individual Rx lines) that gets
    inserted into the يوميات output at the specified position.
    """
    SUPPLEMENT_BEFORE     = 'before_claim'
    SUPPLEMENT_WITHIN     = 'within_claim'
    SUPPLEMENT_AFTER      = 'after_claim'
    SUPPLEMENT_STANDALONE = 'standalone'

    SUPPLEMENT_CHOICES = [
        (SUPPLEMENT_BEFORE,     'ملحق سابق'),
        (SUPPLEMENT_WITHIN,     'ملحق يوم'),
        (SUPPLEMENT_AFTER,      'ملحق لاحق'),
        (SUPPLEMENT_STANDALONE, 'ملحق مستقل'),
    ]

    claim              = models.ForeignKey(
        InsuranceClaim, on_delete=models.CASCADE,
        related_name='supplements', verbose_name='المطالبة'
    )
    supplement_type    = models.CharField(max_length=20, choices=SUPPLEMENT_CHOICES, verbose_name='نوع الملحق')
    supplement_number  = models.CharField(
        max_length=10, blank=True, verbose_name='رقم الملحق',
        help_text='مثال: ملحق 1، ملحق 2'
    )
    label              = models.CharField(
        max_length=200, default='ملحق يوميات', verbose_name='التسمية',
        help_text='يظهر في عمود اسم المريض بالفاتورة'
    )

    # Which date to print under (for within_claim) or the actual date for before/after
    print_date         = models.DateField(null=True, blank=True, verbose_name='تاريخ الطباعة')

    # Aggregate financial values for this supplement
    local_before       = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='المحلى قبل الخصم')
    imported_before    = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='المستورد قبل الخصم')
    tarsia_before      = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الترسية قبل الخصم')
    gross_before       = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الإجمالى قبل الخصم')
    local_discount     = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='خصم المحلى')
    imported_discount  = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='خصم المستورد')
    tarsia_discount    = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='خصم الترسية')
    total_discount     = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='إجمالى الخصم')
    net_after          = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='صافى الفاتورة')

    # Linked manual Rx that make up this supplement (for audit)
    # M2M to InsuranceClaimManualRx (optional — supplement can also be entered as a lump sum)
    rx_count           = models.PositiveIntegerField(default=1, verbose_name='عدد الروشتات')
    notes              = models.TextField(blank=True, verbose_name='ملاحظات')

    is_excluded        = models.BooleanField(default=False, verbose_name='مُستثنى')
    is_manually_edited = models.BooleanField(default=False, verbose_name='عُدِّل يدوياً')

    sort_order         = models.PositiveSmallIntegerField(default=0, verbose_name='ترتيب')
    created_by         = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, related_name='+', verbose_name='أُنشئ بواسطة'
    )
    created_at         = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'ملحق'
        verbose_name_plural = 'ملاحق المطالبات'
        ordering            = ['sort_order', 'print_date']

    def __str__(self):
        return f'{self.get_supplement_type_display()} — {self.claim}'


# ═══════════════════════════════════════════════════════════════════════════════
# COLLECTIONS LAYER
# ═══════════════════════════════════════════════════════════════════════════════

class InsurancePayment(models.Model):
    """Payment received against a claim (Insurance Receivable tracking)."""
    claim          = models.ForeignKey(
        InsuranceClaim, on_delete=models.CASCADE,
        related_name='payments', verbose_name='المطالبة'
    )
    payment_date   = models.DateField(verbose_name='تاريخ الدفع')
    amount         = models.DecimalField(max_digits=14, decimal_places=2, verbose_name='المبلغ المُحصَّل')
    reference      = models.CharField(max_length=100, blank=True, verbose_name='رقم التحويل / الشيك')
    notes          = models.TextField(blank=True, verbose_name='ملاحظات')
    recorded_by    = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, related_name='+', verbose_name='سُجِّل بواسطة'
    )
    recorded_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'دفعة تحصيل'
        verbose_name_plural = 'دفعات التحصيل'
        ordering            = ['-payment_date']

    def __str__(self):
        return f'{self.amount} EGP — {self.claim}'


class InsuranceDeduction(models.Model):
    """
    A deduction made by the insurance company on a submitted claim.
    Insurance companies rarely pay 100% — this tracks rejected items / prescriptions.
    """
    REASON_NOT_COVERED    = 'not_covered'
    REASON_DUPLICATE      = 'duplicate'
    REASON_OVER_LIMIT     = 'over_limit'
    REASON_MISSING_DOCS   = 'missing_docs'
    REASON_CLASSIFICATION = 'classification'
    REASON_OTHER          = 'other'

    REASON_CHOICES = [
        (REASON_NOT_COVERED,    'صنف غير مشمول'),
        (REASON_DUPLICATE,      'روشتة مكررة'),
        (REASON_OVER_LIMIT,     'تجاوز الحد المسموح'),
        (REASON_MISSING_DOCS,   'وثائق ناقصة'),
        (REASON_CLASSIFICATION, 'خطأ في التصنيف'),
        (REASON_OTHER,          'أخرى'),
    ]

    claim           = models.ForeignKey(
        InsuranceClaim, on_delete=models.CASCADE,
        related_name='deductions', verbose_name='المطالبة'
    )
    prescription    = models.ForeignKey(
        InsuranceClaimPrescription, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='deductions',
        verbose_name='الروشتة المتعلقة'
    )
    item_name       = models.CharField(max_length=200, blank=True, verbose_name='الصنف المرفوض')
    reason_code     = models.CharField(max_length=20, choices=REASON_CHOICES, default=REASON_OTHER, verbose_name='سبب الخصم')
    reason_detail   = models.TextField(blank=True, verbose_name='تفاصيل السبب')
    amount          = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='قيمة الخصم')
    recorded_by     = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, related_name='+', verbose_name='سُجِّل بواسطة'
    )
    recorded_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'خصم / رفض'
        verbose_name_plural = 'الخصومات والمرفوضات'
        ordering            = ['-recorded_at']

    def __str__(self):
        return f'{self.amount} EGP — {self.reason_detail or self.get_reason_code_display()}'


# ═══════════════════════════════════════════════════════════════════════════════
# PARENT CLIENT — عميل أب
# Aggregates multiple InsuranceClient records for grand-total reporting.
# Example: "شركة الكهرباء" (parent) → العاملين + المعاشات + الأسر (children).
# ═══════════════════════════════════════════════════════════════════════════════

class InsuranceParentClient(models.Model):
    """
    Top-level grouping of multiple InsuranceClient entities.
    Used to produce consolidated grand-total reports across all sub-clients.

    Softech may have a single parent personcode that internally owns several
    child personcodes — this mirrors that hierarchy in our system.
    """
    name                = models.CharField(max_length=200, verbose_name='اسم العميل الأب')
    name_short          = models.CharField(max_length=60, blank=True, verbose_name='الاسم المختصر')
    softech_personcode  = models.CharField(
        max_length=20, blank=True, db_index=True,
        verbose_name='كود العميل الأب في سوفتك',
        help_text='personcode الرئيسي الجامع في سوفتك (إن وُجد)'
    )
    notes               = models.TextField(blank=True, verbose_name='ملاحظات')
    is_active           = models.BooleanField(default=True, verbose_name='نشط')
    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'عميل أب'
        verbose_name_plural = 'العملاء الآباء'
        ordering            = ['name']

    def __str__(self):
        return self.name_short or self.name

    def total_outstanding(self):
        """Sum of final_net_after across all active non-paid claims of all children."""
        from django.db.models import Sum
        return (
            InsuranceClaim.objects
            .filter(
                subclient__client__parent__id=self.pk,
                status__in=[
                    InsuranceClaim.STATUS_DRAFT,
                    InsuranceClaim.STATUS_READY,
                    InsuranceClaim.STATUS_SUBMITTED,
                    InsuranceClaim.STATUS_UNDER_REVIEW,
                    InsuranceClaim.STATUS_PARTIALLY_PAID,
                ]
            )
            .aggregate(total=Sum('final_net_after'))['total'] or Decimal('0')
        )


# Add parent FK to InsuranceClient (nullable — existing clients keep working)
InsuranceClient.add_to_class(
    'parent',
    models.ForeignKey(
        InsuranceParentClient,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='clients',
        verbose_name='العميل الأب',
    )
)


# ═══════════════════════════════════════════════════════════════════════════════
# BILLING GROUPS — تقسيم المطالبة إلى فئات فرعية
# Splits a single claim's prescriptions into separate invoice groups.
# Each group → its own exported invoice (daily_detail + cover).
# Example: claim for personcode 4227 split into "نقدي" + "تأمين صحي" groups.
# ═══════════════════════════════════════════════════════════════════════════════

class InsuranceClaimBillingGroup(models.Model):
    """
    A named sub-division of a claim.

    The user creates groups, assigns prescriptions to them (manually or by
    auto-filter rules), then exports each group as a separate invoice.

    Prescriptions not assigned to any group belong to the default group
    (billing_group=NULL on InsuranceClaimPrescription).
    """
    claim               = models.ForeignKey(
        InsuranceClaim, on_delete=models.CASCADE,
        related_name='billing_groups', verbose_name='المطالبة'
    )
    code                = models.CharField(
        max_length=20, verbose_name='كود الفئة',
        help_text='مثال: CASH, INS, DEPT-ADMIN — يُستخدم كـ sub-personcode في التقارير'
    )
    name                = models.CharField(max_length=100, verbose_name='اسم الفئة')
    description         = models.TextField(blank=True, verbose_name='وصف')

    # ── Auto-filter rules (used by bulk-assign action) ────────────────────────
    # Prescriptions matching these filters are auto-assigned to this group.
    # All non-null filters are ANDed.  Empty = no auto-filter.
    filter_relative_degree  = models.CharField(
        max_length=20, blank=True, verbose_name='تصفية حسب درجة القرابة',
        help_text='مثال: للعضو، للزوجة، للأبناء (من companiesitems.relativedegree)'
    )
    filter_dept_name        = models.CharField(
        max_length=40, blank=True, verbose_name='تصفية حسب الإدارة',
        help_text='companiesitems.deptname'
    )
    filter_hi_type_code     = models.CharField(
        max_length=1, blank=True, verbose_name='تصفية حسب نوع التأمين',
        help_text='companiesitems.hi_typecode'
    )
    filter_patient_no_prefix = models.CharField(
        max_length=10, blank=True, verbose_name='تصفية حسب بادئة رقم المريض',
        help_text='مثال: A للموظفين، R للمتقاعدين'
    )

    # ── Denormalised totals (recomputed on assignment change) ─────────────────
    rx_count            = models.PositiveIntegerField(default=0, verbose_name='عدد الروشتات')
    gross_before        = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='الإجمالى قبل الخصم')
    total_discount      = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='إجمالى الخصم')
    net_after           = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='صافى الفاتورة')

    sort_order          = models.PositiveSmallIntegerField(default=0, verbose_name='ترتيب')
    created_by          = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, related_name='+', verbose_name='أُنشئت بواسطة'
    )
    created_at          = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'فئة فوترة'
        verbose_name_plural = 'فئات الفوترة'
        ordering            = ['claim', 'sort_order', 'code']
        unique_together     = [['claim', 'code']]

    def __str__(self):
        return f'{self.claim.claim_number} / {self.name}'

    def refresh_totals(self):
        """Recompute denormalised totals from assigned prescriptions + manual Rx."""
        from django.db.models import Sum, Count
        agg = self.prescriptions.aggregate(
            cnt=Count('id'),
            gb=Sum('gross_before'),
            td=Sum('total_discount'),
            na=Sum('net_after'),
        )
        magg = self.manual_rx.filter(is_excluded=False).aggregate(
            cnt=Count('id'),
            gb=Sum('gross_before'),
            td=Sum('total_discount'),
            na=Sum('net_after'),
        )
        # Non-standalone supplements assigned to this group (standalone are
        # separate printouts, excluded from grand totals — mirrors the claim).
        sagg = self.supplements.filter(is_excluded=False).exclude(supplement_type='standalone').aggregate(
            cnt=Sum('rx_count'),
            gb=Sum('gross_before'),
            td=Sum('total_discount'),
            na=Sum('net_after'),
        )
        self.rx_count       = (agg['cnt'] or 0) + (magg['cnt'] or 0) + (sagg['cnt'] or 0)
        self.gross_before   = (agg['gb']  or Decimal('0')) + (magg['gb'] or Decimal('0')) + (sagg['gb'] or Decimal('0'))
        self.total_discount = (agg['td']  or Decimal('0')) + (magg['td'] or Decimal('0')) + (sagg['td'] or Decimal('0'))
        self.net_after      = (agg['na']  or Decimal('0')) + (magg['na'] or Decimal('0')) + (sagg['na'] or Decimal('0'))
        self.save(update_fields=['rx_count', 'gross_before', 'total_discount', 'net_after'])

    def auto_assign_prescriptions(self):
        """
        Assign prescriptions that match this group's filter rules.
        Skips prescriptions already assigned to another group.
        Returns count of newly assigned prescriptions.
        """
        qs = InsuranceClaimPrescription.objects.filter(
            claim=self.claim,
            billing_group__isnull=True,
        )
        if self.filter_relative_degree:
            qs = qs.filter(relative_degree=self.filter_relative_degree)
        if self.filter_dept_name:
            qs = qs.filter(dept_name__icontains=self.filter_dept_name)
        if self.filter_hi_type_code:
            qs = qs.filter(hi_type_code=self.filter_hi_type_code)
        if self.filter_patient_no_prefix:
            qs = qs.filter(patient_no__startswith=self.filter_patient_no_prefix)
        count = qs.update(billing_group=self)
        if count:
            self.refresh_totals()
        return count


# Add companiesitems fields + billing_group FK to InsuranceClaimPrescription
for _fname, _field in [
    ('roshetta_no',     models.CharField(max_length=15, blank=True, db_index=True, verbose_name='رقم الروشتة')),
    ('patient_no',      models.CharField(max_length=15, blank=True, verbose_name='رقم المريض')),
    ('financial_no',    models.CharField(max_length=15, blank=True, verbose_name='الرقم المالي')),
    ('file_no',         models.CharField(max_length=15, blank=True, verbose_name='رقم الملف')),
    ('membership_no',   models.CharField(max_length=15, blank=True, verbose_name='رقم العضوية')),
    ('dept_name',       models.CharField(max_length=40, blank=True, verbose_name='اسم الإدارة')),
    ('relative_degree', models.CharField(max_length=20, blank=True, verbose_name='درجة القرابة',
                                         help_text='للعضو / للزوجة / للأبناء')),
    ('hi_type_code',    models.CharField(max_length=2, blank=True, verbose_name='نوع التأمين الصحي')),
    ('exam_date',       models.DateField(null=True, blank=True, verbose_name='تاريخ الفحص')),
    ('billing_group',   models.ForeignKey(
        InsuranceClaimBillingGroup, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='prescriptions',
        verbose_name='فئة الفوترة',
    )),
]:
    InsuranceClaimPrescription.add_to_class(_fname, _field)


# Manual Rx can also be assigned to a billing group (sub-category), like a
# prescription — so a manually-added receipt shows up on the right sub-invoice.
InsuranceClaimManualRx.add_to_class(
    'billing_group',
    models.ForeignKey(
        InsuranceClaimBillingGroup, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='manual_rx',
        verbose_name='فئة الفوترة',
    ),
)

# Supplements (ملحق) are likewise assignable to a billing group so a supplement
# block appears only on the intended sub-invoice, not on every group's export.
InsuranceClaimSupplement.add_to_class(
    'billing_group',
    models.ForeignKey(
        InsuranceClaimBillingGroup, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='supplements',
        verbose_name='فئة الفوترة',
    ),
)


# ═══════════════════════════════════════════════════════════════════════════════
# SOFTECH CACHE — motalba + companiesitems (last 90 days mirror)
# Populated by the sync engine for fast in-DB queries instead of live Sybase.
# ═══════════════════════════════════════════════════════════════════════════════

class MotalbaCache(models.Model):
    """
    Local PostgreSQL mirror of SOFTECHDB9.dbo.motalba (invdel=1 rows only).
    Sync window: last 90 days, incremental after initial load.
    """
    personcode          = models.CharField(max_length=8, db_index=True, verbose_name='كود العميل')
    motalbano           = models.IntegerField(db_index=True, verbose_name='رقم المطالبة')
    branchcode          = models.CharField(max_length=5, verbose_name='الفرع')
    docnumber           = models.CharField(max_length=10, db_index=True, verbose_name='رقم الفاتورة')
    docdate             = models.DateField(db_index=True, verbose_name='تاريخ الصرف')
    motalbasdate        = models.DateField(null=True, blank=True, verbose_name='بداية فترة المطالبة')
    motalbafdate        = models.DateField(null=True, blank=True, verbose_name='نهاية فترة المطالبة')
    doccode             = models.CharField(max_length=3, verbose_name='كود المستند', help_text='115=بيع, 30=مرتجع')
    docvalue_grandtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='إجمالى سعر الجمهور')
    docvaluerequired    = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='المطلوب')
    motalba_docorder    = models.SmallIntegerField(default=0, verbose_name='ترتيب في المطالبة')
    ppersoncode         = models.CharField(max_length=8, blank=True, verbose_name='كود المريض')
    patientcode         = models.IntegerField(null=True, blank=True, verbose_name='كود المريض (int)')
    custbranchcode      = models.CharField(max_length=5, blank=True, verbose_name='فرع العميل')
    usercode            = models.CharField(max_length=5, blank=True, verbose_name='كود المستخدم')
    synced_at           = models.DateTimeField(auto_now=True, verbose_name='آخر مزامنة')

    class Meta:
        verbose_name        = 'كاش مطالبة'
        verbose_name_plural = 'كاش المطالبات'
        unique_together     = [['personcode', 'motalbano', 'branchcode', 'docnumber', 'doccode']]
        indexes             = [
            models.Index(fields=['personcode', 'motalbano']),
            models.Index(fields=['docdate']),
            models.Index(fields=['docnumber', 'branchcode']),
        ]

    def __str__(self):
        return f'motalba={self.motalbano} doc={self.docnumber}'


class CompaniesItemsCache(models.Model):
    """
    Local PostgreSQL mirror of SOFTECHDB9.dbo.companiesitems (last 90 days).
    Provides rich patient/prescription metadata at query speed.
    """
    branchcode      = models.CharField(max_length=5, db_index=True, verbose_name='الفرع')
    docnumber       = models.CharField(max_length=10, db_index=True, verbose_name='رقم الفاتورة')
    doccode         = models.CharField(max_length=3, verbose_name='كود المستند')
    docdate         = models.DateField(null=True, blank=True, db_index=True, verbose_name='تاريخ الصرف')
    patientname     = models.CharField(max_length=40, blank=True, verbose_name='اسم المريض')
    patientno       = models.CharField(max_length=15, blank=True, verbose_name='رقم المريض')
    financialno     = models.CharField(max_length=10, blank=True, verbose_name='الرقم المالي')
    fileno          = models.CharField(max_length=10, blank=True, verbose_name='رقم الملف')
    roshettano      = models.CharField(max_length=10, blank=True, db_index=True, verbose_name='رقم الروشتة')
    membershipno    = models.CharField(max_length=10, blank=True, verbose_name='رقم العضوية')
    deptname        = models.CharField(max_length=40, blank=True, verbose_name='اسم الإدارة')
    relativedegree  = models.CharField(max_length=20, blank=True, verbose_name='درجة القرابة')
    hi_typecode     = models.CharField(max_length=2, blank=True, verbose_name='نوع التأمين الصحي')
    examdate        = models.DateField(null=True, blank=True, verbose_name='تاريخ الفحص')
    synced_at       = models.DateTimeField(auto_now=True, verbose_name='آخر مزامنة')

    class Meta:
        verbose_name        = 'كاش بيانات المرضى'
        verbose_name_plural = 'كاش بيانات المرضى'
        unique_together     = [['branchcode', 'docnumber', 'doccode']]
        indexes             = [
            models.Index(fields=['docnumber', 'branchcode']),
            models.Index(fields=['docdate']),
        ]

    def __str__(self):
        return f'{self.patientname} — doc={self.docnumber}'


# ═══════════════════════════════════════════════════════════════════════════════
# APPLY-CURRENT-MASTER AUDIT  (pre-mutation snapshot + undo)
# Records the BEFORE values whenever apply_current_master() re-freezes a claim's
# lines, so the action is auditable and fully reversible.
# ═══════════════════════════════════════════════════════════════════════════════

class InsuranceApplyMasterRun(models.Model):
    """One 'apply current master data' operation on a claim."""
    claim          = models.ForeignKey(
        InsuranceClaim, on_delete=models.CASCADE,
        related_name='apply_runs', verbose_name='المطالبة'
    )
    applied_at     = models.DateTimeField(auto_now_add=True, verbose_name='وقت التطبيق')
    applied_by     = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+', verbose_name='طُبِّق بواسطة'
    )
    apply_price    = models.BooleanField(default=True, verbose_name='طُبِّقت الأسعار')
    apply_category = models.BooleanField(default=True, verbose_name='طُبِّق التصنيف')

    lines_updated         = models.PositiveIntegerField(default=0, verbose_name='بنود محدَّثة')
    prescriptions_updated = models.PositiveIntegerField(default=0, verbose_name='روشتات محدَّثة')
    net_before     = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='الصافى قبل')
    net_after      = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='الصافى بعد')

    # Full pre-mutation state (prescription totals + claim totals) as JSON, so
    # undo is lossless even when prescription totals were dgt-scaled at import
    # (line sums ≠ prescription totals by design).
    pre_state      = models.JSONField(null=True, blank=True, verbose_name='الحالة قبل التطبيق')

    reverted       = models.BooleanField(default=False, verbose_name='تم التراجع')
    reverted_at    = models.DateTimeField(null=True, blank=True, verbose_name='وقت التراجع')
    reverted_by    = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+', verbose_name='تراجع بواسطة'
    )

    class Meta:
        verbose_name        = 'تطبيق بيانات الكتالوج'
        verbose_name_plural = 'عمليات تطبيق بيانات الكتالوج'
        ordering            = ['-applied_at']

    def __str__(self):
        return f'apply#{self.pk} — {self.claim.claim_number} ({self.lines_updated} lines)'


class InsuranceClaimLineBackup(models.Model):
    """Pre-mutation snapshot of a single InsuranceClaimLine for one apply run."""
    run               = models.ForeignKey(
        InsuranceApplyMasterRun, on_delete=models.CASCADE,
        related_name='line_backups', verbose_name='عملية التطبيق'
    )
    line              = models.ForeignKey(
        InsuranceClaimLine, on_delete=models.CASCADE,
        related_name='backups', verbose_name='البند'
    )
    # Snapshot of the fields apply_current_master overwrites
    item_category     = models.CharField(max_length=10, verbose_name='التصنيف')
    unit_price        = models.DecimalField(max_digits=10, decimal_places=3, default=0, verbose_name='السعر')
    line_total        = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الإجمالى')
    discount_pct      = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name='نسبة الخصم %')
    discount_amt      = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='قيمة الخصم')
    net_amount        = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الصافى')

    class Meta:
        verbose_name        = 'نسخة بند (تطبيق)'
        verbose_name_plural = 'نسخ البنود (تطبيق)'
        indexes             = [models.Index(fields=['run', 'line'])]

    def __str__(self):
        return f'backup line={self.line_id} run={self.run_id}'


# ═══════════════════════════════════════════════════════════════════════════════
# EXPORT / PRINT PROFILE — customizable headers, footers, fonts, fills, spacing
# Resolved per claim: subclient-specific profile → global default → built-ins.
# ═══════════════════════════════════════════════════════════════════════════════

class InsuranceExportProfile(models.Model):
    """
    Print-customization profile for the claim Excel templates.

    Header/footer sections are free text supporting placeholders:
      {client} {subclient} {claim_number} {month} {period_from} {period_to}
      {call_center} {page} {pages} {rx_count} {net}
    Use \n (newline) inside a section for multiple lines.
    """
    BORDER_CHOICES = [
        ('none', 'بدون'), ('thin', 'رفيع'), ('medium', 'متوسط'), ('thick', 'سميك'),
    ]

    name        = models.CharField(max_length=100, verbose_name='اسم الملف')
    is_default  = models.BooleanField(default=False, verbose_name='الافتراضي العام',
                                      help_text='يُطبَّق على كل المطالبات ما لم توجد قواعد أخص')
    subclient   = models.ForeignKey(
        InsuranceSubClient, on_delete=models.CASCADE, null=True, blank=True,
        related_name='export_profiles', verbose_name='خاص بالفئة',
        help_text='اتركه فارغاً ليكون ملفاً عاماً'
    )

    # ── Header sections (free text + placeholders) ────────────────────────────
    header_left   = models.TextField(blank=True, default='', verbose_name='ترويسة - يسار')
    header_center = models.TextField(blank=True, default='', verbose_name='ترويسة - وسط')
    header_right  = models.TextField(blank=True, default='', verbose_name='ترويسة - يمين')
    # ── Footer sections ───────────────────────────────────────────────────────
    footer_left   = models.TextField(blank=True, default='', verbose_name='تذييل - يسار')
    footer_center = models.TextField(blank=True, default='صفحة {page} من {pages}', verbose_name='تذييل - وسط')
    footer_right  = models.TextField(blank=True, default='', verbose_name='تذييل - يمين')

    # ── Typography / colors ───────────────────────────────────────────────────
    font_name          = models.CharField(max_length=40, default='Arial', verbose_name='الخط')
    header_font_size   = models.PositiveSmallIntegerField(default=10, verbose_name='حجم خط العناوين')
    header_fill        = models.CharField(max_length=6, default='1F4E79', verbose_name='لون تعبئة العناوين')
    header_font_color  = models.CharField(max_length=6, default='FFFFFF', verbose_name='لون خط العناوين')
    subtotal_font_size = models.PositiveSmallIntegerField(default=10, verbose_name='حجم خط المجاميع اليومية')
    subtotal_fill      = models.CharField(max_length=6, default='D6E4F0', verbose_name='لون تعبئة المجاميع اليومية')
    total_font_size    = models.PositiveSmallIntegerField(default=11, verbose_name='حجم خط الإجمالى')
    total_fill         = models.CharField(max_length=6, default='E2EFDA', verbose_name='لون تعبئة الإجمالى')

    # ── Borders + layout ──────────────────────────────────────────────────────
    border_style       = models.CharField(max_length=8, choices=BORDER_CHOICES, default='thin', verbose_name='سُمك الإطار')
    day_block_blank_rows = models.PositiveSmallIntegerField(default=4, verbose_name='أسطر فارغة بين الأيام')
    repeat_header_each_page = models.BooleanField(default=True, verbose_name='تكرار العناوين بكل صفحة')

    # ── Watermark / logo (faded PNG placed on each printed sheet) ─────────────
    # Upload a pre-faded / light PNG — it floats over the data as a watermark.
    watermark_image    = models.FileField(
        upload_to='insurance/watermarks/', blank=True, null=True,
        verbose_name='صورة العلامة المائية (PNG)',
        help_text='يُفضَّل صورة فاتحة/شفافة لتظهر كعلامة مائية خلف البيانات'
    )
    watermark_width_cm = models.DecimalField(
        max_digits=5, decimal_places=1, default=Decimal('8.0'),
        verbose_name='عرض العلامة المائية (سم)'
    )
    watermark_anchor   = models.CharField(
        max_length=6, default='C15', verbose_name='موضع العلامة المائية',
        help_text='خلية الإرساء، مثل C15'
    )
    base_template_note = models.TextField(blank=True, default='', verbose_name='ملاحظات القالب')

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'ملف طباعة المطالبة'
        verbose_name_plural = 'ملفات طباعة المطالبات'
        ordering            = ['-is_default', 'name']

    def __str__(self):
        scope = self.subclient.name if self.subclient else ('عام' if self.is_default else '')
        return f'{self.name} ({scope})'

    @classmethod
    def resolve_for_claim(cls, claim):
        """Subclient-specific profile → global default → None (built-in defaults)."""
        prof = cls.objects.filter(subclient=claim.subclient_id).first()
        if prof:
            return prof
        return cls.objects.filter(is_default=True, subclient__isnull=True).first()


class InsurancePivotTemplate(models.Model):
    """
    A saved pivot/cross-tab configuration (reusable analysis template) built on
    the pivot engine.  Lets users save named groupings (incl. companiesitems
    dimensions: dept, relative degree, hi-type) and re-run / export them.
    """
    name      = models.CharField(max_length=100, verbose_name='اسم القالب')
    source    = models.CharField(max_length=20, default='prescriptions', verbose_name='المصدر')
    row_dim   = models.CharField(max_length=30, verbose_name='تجميع الصفوف')
    col_dim   = models.CharField(max_length=30, blank=True, default='', verbose_name='تجميع الأعمدة')
    measure   = models.CharField(max_length=20, default='net', verbose_name='المقياس')
    is_shared = models.BooleanField(default=True, verbose_name='متاح للجميع')
    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+', verbose_name='أُنشئ بواسطة'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'قالب تحليل'
        verbose_name_plural = 'قوالب التحليل'
        ordering            = ['name']

    def __str__(self):
        return self.name


# ═══════════════════════════════════════════════════════════════════════════════
# ITEM CLASSIFICATION OVERRIDE — correct محلى/مستورد/ترسية for mis-defined items
# ═══════════════════════════════════════════════════════════════════════════════

class InsuranceItemClassificationOverride(models.Model):
    """
    A manual correction of an item's insurance classification (محلى/مستورد/ترسية).

    Some items are wrongly flagged in the catalog master (itemsorigin.importedorigin
    → catalog.Item.is_imported) — e.g. defined as مستورد when they are really محلى.
    That gives them the (larger) imported discount, and the insurance entity then
    deducts them in full when the motalba is reviewed.

    This table lets staff fix the classification WITHOUT touching the shared
    catalog master (which is re-synced from SOFTECH and would overwrite a direct
    edit).  The override is GLOBAL by item code — the item's origin is a fact, not
    contract-specific — and is consulted by classify_item on every future import.
    For already-imported DRAFT claims, staff apply the corrections per claim via
    the audited apply-engine (revertible), before the motalba is issued.

    Two modes:
      • force  — a single correct category applied EVERYWHERE (item mis-defined).
      • review — a DUAL-ORIGIN item that is legitimately محلى in some motalbas and
                 مستورد in others (two origins under one code, e.g. PLAVIX 33555,
                 acti-colla, fast-freeze).  NOT forced globally; instead it is
                 flagged so staff decide its category PER MOTALBA in the فحص
                 الفروقات tab.  forced_category is only a suggested default here.
    """
    MODE_FORCE  = 'force'
    MODE_REVIEW = 'review'
    MODE_CHOICES = [
        (MODE_FORCE,  'فرض تصنيف موحّد'),
        (MODE_REVIEW, 'مراجعة يدوية لكل مطالبة (منشأ مزدوج)'),
    ]

    item_code       = models.CharField(
        max_length=10, unique=True, db_index=True,
        verbose_name='كود الصنف', help_text='itemcode في سوفتك'
    )
    item_name       = models.CharField(max_length=200, blank=True, verbose_name='اسم الصنف')
    mode            = models.CharField(
        max_length=10, choices=MODE_CHOICES, default=MODE_FORCE, verbose_name='النوع'
    )
    forced_category = models.CharField(
        max_length=10, choices=ITEM_CATEGORY_CHOICES,
        default=ITEM_CATEGORY_LOCAL, verbose_name='التصنيف الصحيح'
    )
    is_active       = models.BooleanField(default=True, verbose_name='مُفعَّل')
    reason          = models.CharField(max_length=300, blank=True, verbose_name='سبب التصويب')

    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+', verbose_name='أُنشئ بواسطة'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'تصويب تصنيف صنف'
        verbose_name_plural = 'تصويبات تصنيف الأصناف'
        ordering            = ['item_code']

    def __str__(self):
        return f'{self.item_code} → {self.get_forced_category_display()}'
