"""
apps/tax_invoicing/models.py — fiscal documents sent to the Egyptian Tax Authority (ETA). Doc 36.

apps/insurance owns the claim (مطالبة). This module owns everything fiscal that follows it: the
draft, line review, approval, numbering, payload, submission and credit / debit notes.

Hard rules the schema carries:
  • One original invoice per claim (database constraint `one_original_invoice_per_claim`).
  • `internal_id` is the document's permanent identity. A retry never makes a new one.
  • Once approved, payload and totals are frozen; once ETA has it, they stay frozen for good.

Company-level data: a fiscal document belongs to the taxpayer, not to a branch, and one claim spans
branches. The gate is RBAC module `tax_invoicing`; `source_branchcode` is a reference only.
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class TaxIssuerProfile(models.Model):
    """The taxpayer's details and the accountant's decisions. One row (pk=1)."""
    name = models.CharField(max_length=200, blank=True)
    tax_id = models.CharField(max_length=30, blank=True, verbose_name='رقم التسجيل الضريبي')
    activity_code = models.CharField(max_length=10, blank=True)
    branch_id = models.CharField(max_length=10, blank=True, default='0')
    country = models.CharField(max_length=2, default='EG')
    governate = models.CharField(max_length=100, blank=True)
    region_city = models.CharField(max_length=100, blank=True)
    street = models.CharField(max_length=200, blank=True)
    building_number = models.CharField(max_length=30, blank=True)
    default_unit_type = models.CharField(max_length=10, blank=True, help_text='ETA unit code')

    # Accountant decisions. Blank means "not decided": submission stays blocked, never guessed.
    prices_include_vat = models.BooleanField(default=True, verbose_name='الأسعار شاملة الضريبة')
    vat_basis_confirmed_at = models.DateTimeField(null=True, blank=True)
    vat_basis_confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                               on_delete=models.SET_NULL, related_name='+')
    vat_tax_type = models.CharField(max_length=10, blank=True, help_text='ETA tax type for VAT')
    subtype_taxable = models.CharField(max_length=10, blank=True)
    subtype_exempt = models.CharField(max_length=10, blank=True)
    subtype_zero_rated = models.CharField(max_length=10, blank=True)

    # The validated rule for a single-line ETA invoice. Empty = ETA gets line-level detail.
    summary_code_type = models.CharField(max_length=3, blank=True)
    summary_item_code = models.CharField(max_length=60, blank=True)
    summary_description = models.CharField(max_length=200, blank=True, default='مطالبة مالية')
    summary_treatment = models.CharField(max_length=12, blank=True)
    summary_vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    summary_validated_at = models.DateTimeField(null=True, blank=True)
    summary_validated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.SET_NULL, related_name='+')

    # Largest unexplained difference between claim and invoice, in EGP (rounding only).
    reconcile_tolerance = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('1.00'))
    # Proposed policy, owner to decide (doc 36 §policies). Off means one reviewer may accept their own.
    exclusion_second_person = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'بيانات الممول'

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]


class TaxBuyerProfile(models.Model):
    """The receiver on the invoice, and how its invoice is presented."""
    MODE_SUMMARY, MODE_DETAILED = 'summary', 'detailed'
    MODE_CHOICES = [(MODE_SUMMARY, 'سطر واحد (مطالبة مالية)'), (MODE_DETAILED, 'تفصيلي')]

    client = models.OneToOneField('insurance.InsuranceClient', on_delete=models.PROTECT,
                                  related_name='tax_buyer_profile')
    receiver_type = models.CharField(max_length=1, default='B')
    tax_id = models.CharField(max_length=30, blank=True, verbose_name='رقم التسجيل الضريبي')
    legal_name = models.CharField(max_length=200, blank=True)
    country = models.CharField(max_length=2, default='EG')
    governate = models.CharField(max_length=100, blank=True)
    region_city = models.CharField(max_length=100, blank=True)
    street = models.CharField(max_length=200, blank=True)
    building_number = models.CharField(max_length=30, blank=True)
    presentation_mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_SUMMARY)
    # A written determination that this buyer's claims carry no VAT. Empty: VAT follows each item.
    zero_vat_basis = models.ForeignKey('TaxExclusionBasis', null=True, blank=True, on_delete=models.PROTECT,
                                       related_name='zero_vat_buyers')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'بيانات المشتري الضريبية'

    def __str__(self):
        return self.legal_name or str(self.client)


class TaxItemProfile(models.Model):
    """One SOFTECH item's ETA coding, tax treatment and list status: three separate questions."""
    CODE_APPROVED, CODE_MISSING, CODE_PENDING, CODE_REJECTED = 'approved', 'missing', 'pending', 'rejected'
    CODE_STATUS_CHOICES = [(CODE_APPROVED, 'كود معتمد'), (CODE_MISSING, 'بدون كود'),
                           (CODE_PENDING, 'قيد الاعتماد'), (CODE_REJECTED, 'كود مرفوض')]

    TREATMENT_TAXABLE, TREATMENT_EXEMPT = 'taxable', 'exempt'
    TREATMENT_ZERO, TREATMENT_UNCLASSIFIED = 'zero_rated', 'unclassified'
    TREATMENT_CHOICES = [(TREATMENT_TAXABLE, 'خاضع'), (TREATMENT_EXEMPT, 'معفى'),
                         (TREATMENT_ZERO, 'نسبة صفر'), (TREATMENT_UNCLASSIFIED, 'غير مصنف')]

    softech_itemcode = models.CharField(max_length=10, unique=True)
    item = models.ForeignKey('catalog.Item', null=True, blank=True, on_delete=models.SET_NULL,
                             related_name='tax_profiles')
    item_name = models.CharField(max_length=200, blank=True)
    item_name_ar = models.CharField(max_length=200, blank=True)

    code_type = models.CharField(max_length=3, blank=True, help_text='GS1 or EGS')
    gpc_code = models.CharField(max_length=10, blank=True)
    active_from = models.DateField(null=True, blank=True)
    active_to = models.DateField(null=True, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    eta_code = models.CharField(max_length=60, blank=True, db_index=True)
    coding_status = models.CharField(max_length=10, choices=CODE_STATUS_CHOICES, default=CODE_MISSING,
                                     db_index=True)
    unit_type = models.CharField(max_length=10, blank=True)

    tax_treatment = models.CharField(max_length=12, choices=TREATMENT_CHOICES,
                                     default=TREATMENT_UNCLASSIFIED, db_index=True)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    treatment_reference = models.CharField(max_length=200, blank=True)
    # What the workbook says. Input for the accountant, never a confirmed treatment.
    source_vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    source_vat_code = models.CharField(max_length=10, blank=True)
    treatment_confirmed_at = models.DateTimeField(null=True, blank=True)
    treatment_confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                               on_delete=models.SET_NULL, related_name='+')

    # The third, independent question. The owner's whitelist / blacklist is an input to it: a
    # blacklisted item goes to accountant review, and that never removes a line by itself.
    LIST_NONE, LIST_WHITE, LIST_BLACK = 'none', 'white', 'black'
    LIST_CHOICES = [(LIST_NONE, 'غير مدرج'), (LIST_WHITE, 'القائمة البيضاء'), (LIST_BLACK, 'القائمة السوداء')]
    DISP_INCLUDE, DISP_REVIEW, DISP_EXCLUSION = 'include', 'review', 'exclusion'
    DISPOSITION_CHOICES = [(DISP_INCLUDE, 'يُدرج في الفاتورة'), (DISP_REVIEW, 'يحتاج مراجعة المحاسب'),
                           (DISP_EXCLUSION, 'طلب استبعاد لكل بند')]
    list_status = models.CharField(max_length=5, choices=LIST_CHOICES, default=LIST_NONE, db_index=True)
    listed_reason = models.CharField(max_length=300, blank=True)
    disposition = models.CharField(max_length=10, choices=DISPOSITION_CHOICES, default=DISP_INCLUDE, db_index=True)
    # Which ETA system an ETA answer set coding_status in ('' = the owner's workbook or a manual entry, i.e. the
    # real registry). A status ETA's test system gave never counts against production (services.classify).
    coding_env = models.CharField(max_length=12, blank=True, default='', db_default='')
    # The last "does ETA hold this code?" check (coding.check_codes), per system.
    CHECK_FOUND, CHECK_INACTIVE, CHECK_NOT_FOUND = 'found', 'inactive', 'not_found'
    CHECK_CHOICES = [(CHECK_FOUND, 'موجود ومفعل لدى المصلحة'), (CHECK_INACTIVE, 'موجود وغير مفعل'),
                     (CHECK_NOT_FOUND, 'غير موجود لدى المصلحة')]
    eta_check_env = models.CharField(max_length=12, blank=True, default='', db_default='')
    eta_check_status = models.CharField(max_length=10, choices=CHECK_CHOICES, blank=True, default='', db_default='')
    eta_checked_at = models.DateTimeField(null=True, blank=True)
    eta_check_detail = models.JSONField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ترميز صنف ضريبي'
        ordering = ['softech_itemcode']

    def __str__(self):
        return f'{self.softech_itemcode} {self.eta_code}'.strip()


class TaxExclusionBasis(models.Model):
    """A documented legal basis for leaving a line off an official invoice. None is seeded: until
    an authorized person records one, no exclusion can be approved and those drafts stay blocked."""
    KIND_EXCLUSION, KIND_ZERO_VAT = 'exclusion', 'zero_vat'
    KIND_CHOICES = [(KIND_EXCLUSION, 'استبعاد بند'), (KIND_ZERO_VAT, 'عدم استحقاق ضريبة')]
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_EXCLUSION)
    title = models.CharField(max_length=200)
    reference_number = models.CharField(max_length=100)
    issued_by = models.CharField(max_length=200)
    document_url = models.CharField(max_length=500, blank=True)
    applies_to = models.TextField(help_text='Which items or situations the document covers')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'أساس استبعاد موثق'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.reference_number} — {self.title}'


class TaxSequence(models.Model):
    """Gap-free document numbering, per document type and year."""
    doc_type = models.CharField(max_length=1)
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['doc_type', 'year'], name='one_tax_sequence_per_type_year')]


class TaxDocument(models.Model):
    TYPE_INVOICE, TYPE_CREDIT, TYPE_DEBIT = 'i', 'c', 'd'
    TYPE_CHOICES = [(TYPE_INVOICE, 'فاتورة'), (TYPE_CREDIT, 'إشعار دائن'), (TYPE_DEBIT, 'إشعار مدين')]

    DRAFT, APPROVED, SUBMITTING, UNCERTAIN = 'draft', 'approved', 'submitting', 'uncertain'
    SUBMITTED, VALID, INVALID, REJECTED = 'submitted', 'valid', 'invalid', 'rejected'
    STATUS_CHOICES = [
        (DRAFT, 'مسودة'), (APPROVED, 'معتمدة'), (SUBMITTING, 'جارٍ الإرسال'),
        (UNCERTAIN, 'نتيجة غير مؤكدة'), (SUBMITTED, 'مُرسلة'), (VALID, 'مقبولة'),
        (INVALID, 'غير صالحة'), (REJECTED, 'مرفوضة عند الإرسال'),
    ]
    TRANSITIONS = {
        DRAFT: [APPROVED],
        APPROVED: [DRAFT, SUBMITTING],
        SUBMITTING: [SUBMITTED, REJECTED, APPROVED, UNCERTAIN],
        UNCERTAIN: [SUBMITTED, VALID, INVALID, APPROVED],
        SUBMITTED: [VALID, INVALID],
        VALID: [],
        INVALID: [DRAFT],
        REJECTED: [DRAFT],
    }
    # ETA may hold it, or does: what was approved can no longer change.
    SENT_STATUSES = (SUBMITTING, UNCERTAIN, SUBMITTED, VALID)
    FROZEN_STATUSES = (APPROVED,) + SENT_STATUSES
    _FROZEN_FIELDS = ('payload_text', 'payload_hash', 'date_time_issued', 'total_sales', 'total_discount',
                      'net_amount', 'vat_amount', 'total_amount')

    doc_type = models.CharField(max_length=1, choices=TYPE_CHOICES, default=TYPE_INVOICE)
    internal_id = models.CharField(max_length=30, unique=True, editable=False)
    claim = models.ForeignKey('insurance.InsuranceClaim', on_delete=models.PROTECT, related_name='tax_documents')
    original = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='notes')
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=DRAFT, db_index=True)

    # Exactly what was read from the claim on first import. Never rewritten.
    source_snapshot = models.JSONField(default=dict)
    # After a deliberate refresh of a draft: the claim's content the lines now follow.
    source_snapshot_current = models.JSONField(default=dict, blank=True)
    source_hash = models.CharField(max_length=64, blank=True)
    source_refreshed_at = models.DateTimeField(null=True, blank=True)
    source_claim_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    presentation_mode = models.CharField(max_length=10, choices=TaxBuyerProfile.MODE_CHOICES,
                                         default=TaxBuyerProfile.MODE_SUMMARY)

    total_sales = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    total_discount = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    net_amount = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    vat_amount = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    total_amount = models.DecimalField(max_digits=16, decimal_places=5, default=0)

    # Exact bytes frozen at approval: a JSONField would rewrite numbers and break the signature.
    payload_text = models.TextField(blank=True)
    payload_hash = models.CharField(max_length=64, blank=True)
    date_time_issued = models.DateTimeField(null=True, blank=True)
    signed_payload_text = models.TextField(blank=True)

    # Notes only
    reason = models.TextField(blank=True)

    # ETA's answer
    eta_uuid = models.CharField(max_length=64, blank=True, db_index=True)
    eta_long_id = models.CharField(max_length=64, blank=True)
    eta_submission_uuid = models.CharField(max_length=64, blank=True)
    eta_status_reason = models.TextField(blank=True)
    eta_checked_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name='+')
    approved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'مستند ضريبي'
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['claim'], condition=Q(doc_type='i'),
                                    name='one_original_invoice_per_claim'),
            models.CheckConstraint(
                check=(Q(doc_type='i', original__isnull=True) | (Q(doc_type__in=['c', 'd']) & Q(original__isnull=False))),
                name='notes_link_to_their_original'),
        ]

    def __str__(self):
        return self.internal_id

    def save(self, *args, **kwargs):
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).values('status', *self._FROZEN_FIELDS).first()
            if old and old['status'] in self.SENT_STATUSES:
                for f in self._FROZEN_FIELDS:
                    if getattr(self, f) != old[f]:
                        raise ValidationError(f'{self.internal_id}: لا يمكن تغيير {f} بعد الإرسال')
        super().save(*args, **kwargs)


class TaxDocumentLine(models.Model):
    """One source line of the claim and what happens to it. All source lines stay, whatever their
    status: the source sale is kept complete."""
    ST_APPROVED, ST_EXEMPT, ST_UNCODED, ST_PENDING, ST_EXCLUDED = 'approved', 'exempt', 'uncoded', 'pending', 'excluded'
    STATUS_CHOICES = [(ST_APPROVED, 'معتمد'), (ST_EXEMPT, 'معفى'), (ST_UNCODED, 'غير مُرمَّز'),
                      (ST_PENDING, 'قيد المراجعة'), (ST_EXCLUDED, 'مستبعد')]

    document = models.ForeignKey(TaxDocument, on_delete=models.CASCADE, related_name='lines')
    source_line_id = models.BigIntegerField(null=True, blank=True)
    source_docnumber = models.CharField(max_length=30, blank=True)
    source_docdate = models.DateField(null=True, blank=True)
    source_branchcode = models.CharField(max_length=10, blank=True)
    softech_itemcode = models.CharField(max_length=10, db_index=True)
    item_name = models.CharField(max_length=200, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    source_gross = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    source_discount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    source_net = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    softech_line_net = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    # Set by validation from the item's confirmed mapping; frozen by the approved payload.
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=ST_PENDING, db_index=True)
    status_reason = models.CharField(max_length=300, blank=True)
    code_type = models.CharField(max_length=3, blank=True)
    eta_code = models.CharField(max_length=60, blank=True)
    unit_type = models.CharField(max_length=10, blank=True)
    tax_treatment = models.CharField(max_length=12, blank=True)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    net_ex_vat = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    vat_amount = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    total_incl_vat = models.DecimalField(max_digits=16, decimal_places=5, default=0)

    # Notes: the original line this adjusts, and the amount it affects.
    adjusts_line = models.ForeignKey('self', null=True, blank=True, on_delete=models.PROTECT, related_name='adjustments')

    class Meta:
        verbose_name = 'بند مستند ضريبي'
        ordering = ['id']
        constraints = [models.UniqueConstraint(fields=['document', 'source_line_id'],
                                               condition=Q(source_line_id__isnull=False),
                                               name='one_tax_line_per_source_line')]

    @property
    def on_invoice(self):
        return self.status in (self.ST_APPROVED, self.ST_EXEMPT)


class TaxLineReview(models.Model):
    """The accountant's decision on a line. An exclusion needs a written reason and a documented
    basis, and its reviewer must be someone other than whoever asked for it."""
    CAT_CODING, CAT_EXEMPT, CAT_INCLUDE, CAT_EXCLUSION = 'coding', 'exempt', 'include', 'exclusion'
    CATEGORY_CHOICES = [(CAT_CODING, 'مشكلة ترميز مؤقتة'), (CAT_EXEMPT, 'صنف معفى'),
                        (CAT_INCLUDE, 'يُدرج في الفاتورة'), (CAT_EXCLUSION, 'طلب استبعاد من المستند')]
    OPEN, ACCEPTED, DECLINED = 'open', 'accepted', 'declined'
    STATE_CHOICES = [(OPEN, 'مفتوح'), (ACCEPTED, 'مقبول'), (DECLINED, 'مرفوض')]

    line = models.ForeignKey(TaxDocumentLine, null=True, on_delete=models.SET_NULL, related_name='reviews')
    document = models.ForeignKey(TaxDocument, on_delete=models.PROTECT, related_name='line_reviews')
    source_line_id = models.BigIntegerField(null=True, blank=True)
    softech_itemcode = models.CharField(max_length=10)
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES)
    state = models.CharField(max_length=8, choices=STATE_CHOICES, default=OPEN, db_index=True)
    reason = models.TextField()
    supporting_reference = models.CharField(max_length=200, blank=True)
    basis = models.ForeignKey(TaxExclusionBasis, null=True, blank=True, on_delete=models.PROTECT, related_name='reviews')
    effect_net = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    effect_vat = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    effect_gross = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    class Meta:
        verbose_name = 'مراجعة بند'
        ordering = ['-requested_at', '-id']
        constraints = [models.UniqueConstraint(fields=['line'], condition=Q(state='open'),
                                               name='one_open_review_per_line')]


class TaxSubmissionAttempt(models.Model):
    """One real call to ETA, opened before the call so a crash still leaves a trace."""
    STARTED, ACCEPTED, REJECTED, FAILED, TIMEOUT = 'started', 'accepted', 'rejected', 'failed', 'timeout'
    STATE_CHOICES = [(STARTED, 'بدأت'), (ACCEPTED, 'استلمتها المصلحة'), (REJECTED, 'رفضتها المصلحة'),
                     (FAILED, 'فشلت ولم تصل'), (TIMEOUT, 'نتيجة غير مؤكدة')]

    document = models.ForeignKey(TaxDocument, on_delete=models.PROTECT, related_name='attempts')
    state = models.CharField(max_length=10, choices=STATE_CHOICES, default=STARTED)
    payload_hash = models.CharField(max_length=64)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at', '-id']


class TaxAuditEvent(models.Model):
    """Who / what / when / why / before-after, for documents and for their settings. Append only."""
    document = models.ForeignKey(TaxDocument, null=True, blank=True, on_delete=models.PROTECT, related_name='events')
    entity = models.CharField(max_length=30, default='document')
    entity_id = models.CharField(max_length=40, blank=True)
    action = models.CharField(max_length=40, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    reason = models.TextField(blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('سجل التدقيق لا يُعدَّل')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('سجل التدقيق لا يُحذف')


# ── Item codes (EGS) ───────────────────────────────────────────────────────────────────────────

class TaxCodeRequest(models.Model):
    """One request to ETA to register an internal (EGS) code for one item, followed until ETA decides.

    prepared → sending → submitted → approved | rejected
                       ↘ failed (ETA said no, or never got it: safe to send again)
                       ↘ uncertain (we can't tell: ask ETA before sending again)
    The item's own coding fields change only from ETA's answer: pending on submit, approved or
    rejected on ETA's decision. Nothing here marks a code approved by itself.
    """
    PREPARED, SENDING, SUBMITTED, APPROVED, REJECTED, FAILED, UNCERTAIN, CANCELLED = (
        'prepared', 'sending', 'submitted', 'approved', 'rejected', 'failed', 'uncertain', 'cancelled')
    STATUS_CHOICES = [(PREPARED, 'جاهز للإرسال'), (SENDING, 'جارٍ الإرسال'), (SUBMITTED, 'لدى المصلحة — قيد المراجعة'),
                      (APPROVED, 'اعتمدته المصلحة'), (REJECTED, 'رفضته المصلحة'), (FAILED, 'لم يُقبل الطلب'),
                      (UNCERTAIN, 'نتيجة غير مؤكدة'), (CANCELLED, 'أُلغي')]
    OPEN_STATES = (PREPARED, SENDING, SUBMITTED, UNCERTAIN)
    TRANSITIONS = {
        PREPARED: [SENDING, CANCELLED],
        SENDING: [SUBMITTED, FAILED, UNCERTAIN],
        SUBMITTED: [APPROVED, REJECTED],
        UNCERTAIN: [SUBMITTED, FAILED, APPROVED, REJECTED],
        FAILED: [SENDING, CANCELLED, SUBMITTED, APPROVED, REJECTED],
        APPROVED: [], REJECTED: [], CANCELLED: [],
    }

    profile = models.ForeignKey(TaxItemProfile, on_delete=models.PROTECT, related_name='code_requests')
    # new: a code the item does not have yet. mirror: the item's existing real code, registered in a test
    # system so test documents can carry it; its answer never changes the item's real coding.
    PURPOSE_NEW, PURPOSE_MIRROR = 'new', 'mirror'
    PURPOSE_CHOICES = [(PURPOSE_NEW, 'كود جديد'), (PURPOSE_MIRROR, 'تسجيل الكود الحالي في المنظومة التجريبية')]
    purpose = models.CharField(max_length=8, choices=PURPOSE_CHOICES, default=PURPOSE_NEW, db_default=PURPOSE_NEW)
    item_code = models.CharField(max_length=60, db_index=True, help_text='EG-<tax id>-<internal code>')
    parent_code = models.CharField(max_length=20, help_text='GPC level-4 (brick) code')
    code_name = models.CharField(max_length=200)
    code_name_ar = models.CharField(max_length=200)
    description = models.CharField(max_length=300, blank=True)
    description_ar = models.CharField(max_length=300, blank=True)
    active_from = models.DateField()
    request_reason = models.CharField(max_length=300, blank=True)
    environment = models.CharField(max_length=12, blank=True, help_text='The ETA system it went to')

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PREPARED, db_index=True)
    eta_request_id = models.CharField(max_length=30, blank=True)
    eta_status = models.CharField(max_length=20, blank=True)
    eta_response = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)

    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    prepared_at = models.DateTimeField(auto_now_add=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    sent_at = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'طلب كود صنف من المصلحة'
        ordering = ['-prepared_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['profile'], condition=Q(status__in=['prepared', 'sending', 'submitted', 'uncertain']),
                                    name='one_open_code_request_per_item'),
        ]

    def __str__(self):
        return f'{self.item_code} {self.status}'


# ── Signing ────────────────────────────────────────────────────────────────────────────────────

class TaxSigningJob(models.Model):
    """Text waiting for the seal. The workstation's agent pulls it over the VPN and returns a signature."""
    KIND_DOCUMENT, KIND_SMOKE = 'document', 'smoke'
    KIND_CHOICES = [(KIND_DOCUMENT, 'مستند'), (KIND_SMOKE, 'اختبار')]
    PENDING, CLAIMED, SIGNED, FAILED, EXPIRED = 'pending', 'claimed', 'signed', 'failed', 'expired'
    STATUS_CHOICES = [(PENDING, 'بالانتظار'), (CLAIMED, 'جارٍ التوقيع'), (SIGNED, 'تم التوقيع'), (FAILED, 'فشل'),
                      (EXPIRED, 'انتهى الوقت')]

    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=PENDING, db_index=True)
    canonical_text = models.TextField()
    canonical_sha256 = models.CharField(max_length=64)
    signature = models.TextField(blank=True)
    error = models.TextField(blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at', 'id']


class TaxSigningCertification(models.Model):
    """The result of a smoke test on the real token, verified on the server. Live sending needs a pass."""
    job = models.ForeignKey(TaxSigningJob, null=True, on_delete=models.SET_NULL, related_name='certifications')
    passed = models.BooleanField(default=False)
    subject = models.CharField(max_length=500, blank=True)
    issuer = models.CharField(max_length=500, blank=True)
    thumbprint = models.CharField(max_length=64, blank=True)
    not_after = models.DateTimeField(null=True, blank=True)
    detail = models.TextField(blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


# ── E-receipts for branch POS sales ────────────────────────────────────────────────────────────

class TaxChannelRule(models.Model):
    """How a SOFTECH sales channel (ptclassifcode) reaches ETA. Unknown channel = held, never dropped."""
    MODE_RECEIPT, MODE_INVOICE, MODE_UNDECIDED = 'receipt', 'invoice', 'undecided'
    MODE_CHOICES = [(MODE_RECEIPT, 'إيصال إلكتروني'), (MODE_INVOICE, 'فاتورة على مطالبة'), (MODE_UNDECIDED, 'لم يتحدد')]
    ptclassifcode = models.CharField(max_length=5, unique=True)
    label = models.CharField(max_length=100, blank=True)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_UNDECIDED)
    note = models.CharField(max_length=300, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['ptclassifcode']


class TaxReceiptBranchConfig(models.Model):
    """One branch's registered POS. Secrets stay in the environment; this names the variables."""
    softech_branchcode = models.CharField(max_length=5, unique=True)
    branch = models.ForeignKey('branches.Branch', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    is_enabled = models.BooleanField(default=False)
    seller_branch_code = models.CharField(max_length=50, blank=True, help_text='ETA branch code')
    device_serial = models.CharField(max_length=100, blank=True)
    pos_os_version = models.CharField(max_length=50, blank=True)
    pos_model_framework = models.CharField(max_length=10, blank=True)
    client_id = models.CharField(max_length=100, blank=True)
    secret_env = models.CharField(max_length=60, blank=True)
    preshared_key_env = models.CharField(max_length=60, blank=True)
    activity_code = models.CharField(max_length=10, blank=True)
    governate = models.CharField(max_length=100, blank=True)
    region_city = models.CharField(max_length=100, blank=True)
    street = models.CharField(max_length=200, blank=True)
    building_number = models.CharField(max_length=100, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    last_uuid = models.CharField(max_length=64, blank=True, editable=False)
    # Where this device's receipt chain starts, decided once before the first receipt (receipts.start_chain):
    #   fresh     ETA holds no receipt from this device, so previousUUID starts empty;
    #   handover  the device was used by another program (Invoicer); our first receipt follows its last one.
    CHAIN_FRESH, CHAIN_HANDOVER = 'fresh', 'handover'
    CHAIN_CHOICES = [(CHAIN_FRESH, 'جهاز جديد بلا إيصالات سابقة'), (CHAIN_HANDOVER, 'استلام من برنامج سابق')]
    chain_start = models.CharField(max_length=10, choices=CHAIN_CHOICES, blank=True, default='', db_default='')
    chain_start_uuid = models.CharField(max_length=64, blank=True, default='', db_default='', editable=False)
    chain_start_detail = models.JSONField(null=True, blank=True, editable=False)
    chain_start_at = models.DateTimeField(null=True, blank=True, editable=False)
    chain_start_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name='+', editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['softech_branchcode']


class TaxReceiptAttempt(models.Model):
    STARTED, ACCEPTED, FAILED, TIMEOUT = 'started', 'accepted', 'failed', 'timeout'
    STATE_CHOICES = [(STARTED, 'بدأت'), (ACCEPTED, 'استلمتها المصلحة'), (FAILED, 'فشلت ولم تصل'), (TIMEOUT, 'نتيجة غير مؤكدة')]
    config = models.ForeignKey(TaxReceiptBranchConfig, on_delete=models.PROTECT, related_name='attempts')
    state = models.CharField(max_length=8, choices=STATE_CHOICES, default=STARTED)
    receipt_count = models.PositiveIntegerField(default=0)
    submission_uuid = models.CharField(max_length=64, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    error = models.TextField(blank=True)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at', '-id']


class TaxReceipt(models.Model):
    HELD, BY_INVOICE, READY, ISSUED = 'held', 'by_invoice', 'ready', 'issued'
    SUBMITTING, UNCERTAIN, SUBMITTED = 'submitting', 'uncertain', 'submitted'
    ACCEPTED, REJECTED = 'accepted', 'rejected'
    STATUS_CHOICES = [
        (HELD, 'محجوز للمراجعة'), (BY_INVOICE, 'تغطيه فاتورة مطالبة'), (READY, 'جاهز للإصدار'), (ISSUED, 'صدر وينتظر الإرسال'),
        (SUBMITTING, 'جارٍ الإرسال'), (UNCERTAIN, 'نتيجة غير مؤكدة'), (SUBMITTED, 'مُرسل'), (ACCEPTED, 'مقبول'), (REJECTED, 'مرفوض'),
    ]
    TRANSITIONS = {
        HELD: [READY, BY_INVOICE], BY_INVOICE: [HELD, READY], READY: [HELD, BY_INVOICE, ISSUED], ISSUED: [SUBMITTING],
        SUBMITTING: [ISSUED, UNCERTAIN, SUBMITTED, REJECTED], UNCERTAIN: [ISSUED, SUBMITTED, ACCEPTED, REJECTED],
        SUBMITTED: [ACCEPTED, REJECTED], ACCEPTED: [], REJECTED: [],
    }
    softech_branchcode = models.CharField(max_length=5, db_index=True)
    doccode = models.CharField(max_length=3)
    docnumber = models.CharField(max_length=20)
    docdate = models.DateField()
    channel = models.CharField(max_length=5, blank=True, db_index=True)
    sold_at = models.DateTimeField()
    source_value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    original_ref = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=HELD, db_index=True)
    hold_reasons = models.JSONField(default=list, blank=True)
    net_amount = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    vat_amount = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    total_amount = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    uuid = models.CharField(max_length=64, blank=True, db_index=True)
    previous_uuid = models.CharField(max_length=64, blank=True)
    payload_text = models.TextField(blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    attempt = models.ForeignKey(TaxReceiptAttempt, null=True, blank=True, on_delete=models.SET_NULL, related_name='receipts')
    submission_uuid = models.CharField(max_length=64, blank=True)
    eta_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'إيصال إلكتروني'
        ordering = ['-sold_at', '-id']
        constraints = [models.UniqueConstraint(fields=['softech_branchcode', 'doccode', 'docnumber', 'docdate'],
                                               name='one_receipt_per_softech_document')]


class TaxReceiptLine(models.Model):
    receipt = models.ForeignKey(TaxReceipt, on_delete=models.CASCADE, related_name='lines')
    itemcode = models.CharField(max_length=10, db_index=True)
    item_name = models.CharField(max_length=200, blank=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=5, default=0)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    source_vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    status = models.CharField(max_length=10, default='pending', db_index=True)
    status_reason = models.CharField(max_length=300, blank=True)
    code_type = models.CharField(max_length=3, blank=True)
    eta_code = models.CharField(max_length=60, blank=True)
    unit_type = models.CharField(max_length=10, blank=True)
    tax_treatment = models.CharField(max_length=12, blank=True)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    net_ex_vat = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    vat_amount = models.DecimalField(max_digits=16, decimal_places=5, default=0)
    total_incl_vat = models.DecimalField(max_digits=16, decimal_places=5, default=0)

    class Meta:
        ordering = ['id']

