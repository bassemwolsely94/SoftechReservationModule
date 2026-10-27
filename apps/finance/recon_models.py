"""
apps/finance/recon_models.py

A/P–A/R RECONCILIATION (سداد فواتير) — canonical read-only mirror + engine models.
See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.

Party-agnostic: supplier payables (SOFTECH doccode 10/120) AND customer
receivables (doccode 115/30). NOTHING here writes to SOFTECH — these are a
PostgreSQL mirror + reconciliation-engine scaffolding. Every mirror row carries a
source snapshot hash so Phase-G write-back can prove the SOFTECH row is unchanged.

Imported into apps/finance/models.py (`from .recon_models import *`) so the models
register under the `finance` app label and share its migration history.
"""
from django.db import models


# ── shared vocabularies ───────────────────────────────────────────────────────

PARTY_TYPE_CHOICES = [
    ('supplier', 'مورد'),
    ('customer', 'عميل'),
]

# Money direction relative to the pharmacy.
FLOW_DIRECTION_CHOICES = [
    ('out', 'صرف (دفع لمورد)'),      # payment to a supplier
    ('in',  'قبض (تحصيل من عميل)'),   # receipt from a customer
]

# SOFTECH document codes we mirror as invoices/liabilities/receivables.
DOCCODE_PURCHASE        = '10'    # supplier purchase  (payable, we pay OUT)
DOCCODE_RETURN_SUPPLIER = '120'   # return to supplier (reduces payable)
DOCCODE_SALE            = '115'   # customer sale      (receivable, we collect IN)
DOCCODE_RETURN_CUSTOMER = '30'    # customer return    (reduces receivable)


class ReconParty(models.Model):
    """
    A supplier or customer whose account we reconstruct. Thin bridge onto the
    SOFTECH `personsdata` row (personcode). Links to the richer masters we already
    have (invoices.VendorProfile / customers.Customer) when resolvable.
    """
    party_type          = models.CharField(max_length=10, choices=PARTY_TYPE_CHOICES, db_index=True)
    softech_personcode  = models.CharField(max_length=12, unique=True, db_index=True,
                                           verbose_name='كود الحساب SOFTECH')
    name                = models.CharField(max_length=300, blank=True)
    ptclassifcode       = models.CharField(max_length=8, blank=True)   # supplier/customer sub-type

    vendor_profile      = models.ForeignKey(
        'invoices.VendorProfile', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='recon_parties',
    )
    customer            = models.ForeignKey(
        'customers.Customer', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='recon_parties',
    )

    # حصر — opening term of  Opening + Purchases − Payments ± Adj = Closing
    opening_balance      = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    opening_balance_date = models.DateField(null=True, blank=True)
    # Latest SOFTECH running balance snapshot (personsdata buckets / personnewbal).
    softech_balance      = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    softech_balance_at   = models.DateTimeField(null=True, blank=True)

    is_active           = models.BooleanField(default=True)
    synced_at           = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['party_type', 'softech_personcode']
        verbose_name        = 'طرف تسوية'
        verbose_name_plural = 'أطراف التسوية'
        indexes = [models.Index(fields=['party_type', 'is_active'])]

    def __str__(self):
        return f'{self.get_party_type_display()} {self.softech_personcode} — {self.name}'


class APInvoice(models.Model):
    """
    Mirror of one SOFTECH document that creates a payable/receivable
    (stktransm doccode 10/120/115/30), keyed by its 4-part SOFTECH key.
    Outstanding = doc_value − doc_value_pay.
    """
    party        = models.ForeignKey(ReconParty, on_delete=models.CASCADE, related_name='invoices')
    # 4-part SOFTECH composite key
    branchcode   = models.CharField(max_length=5, db_index=True)
    doccode      = models.CharField(max_length=5, db_index=True)
    docnumber    = models.CharField(max_length=20, db_index=True)
    docdate      = models.DateField(db_index=True)

    docnumber2   = models.CharField(max_length=40, blank=True, db_index=True,
                                    verbose_name='رقم مستند المورد/العميل')
    doc_value       = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    doc_value_pay   = models.DecimalField(max_digits=18, decimal_places=3, default=0,
                                          verbose_name='المسدد (من SOFTECH)')
    fat_status      = models.CharField(max_length=8, blank=True)   # fatcurrentstatus (90 ≈ closed)
    due_date        = models.DateField(null=True, blank=True)       # docpaydue
    usercode        = models.CharField(max_length=8, blank=True)
    comments        = models.TextField(blank=True, default='')   # stktransm.comments — الملاحظات
    is_return       = models.BooleanField(default=False)           # 120 / 30
    party_type      = models.CharField(max_length=10, choices=PARTY_TYPE_CHOICES, db_index=True)
    # SOFTECH running-balance snapshot AFTER this doc (F2 — the ledger's truth).
    person_new_bal  = models.DecimalField(max_digits=18, decimal_places=3, default=0)  # personnewbal
    trans_time      = models.DateTimeField(null=True, blank=True)   # precise ordering

    source_hash  = models.CharField(max_length=64, blank=True)     # sha of the SOFTECH row
    synced_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-docdate', 'branchcode', 'docnumber']
        verbose_name        = 'فاتورة/مستند تسوية'
        verbose_name_plural = 'فواتير/مستندات التسوية'
        constraints = [
            models.UniqueConstraint(
                fields=['branchcode', 'doccode', 'docnumber', 'docdate'],
                name='uq_apinvoice_softech_key',
            ),
        ]
        indexes = [
            models.Index(fields=['party', 'doccode']),
            models.Index(fields=['party_type', 'docdate']),
        ]

    def __str__(self):
        return f'{self.doccode}/{self.branchcode}/{self.docnumber} @ {self.docdate} = {self.doc_value}'

    @property
    def outstanding(self):
        """SOFTECH-header view: doc_value − doc_value_pay (what the ERP thinks)."""
        return (self.doc_value or 0) - (self.doc_value_pay or 0)

    @property
    def is_fully_settled(self):
        return self.outstanding <= 0

    @property
    def linked_amount(self):
        """Sum of OUR allocations (softech + approved) against this invoice."""
        if not self.pk:
            return 0
        return sum((a.amount for a in self.allocations.all()), start=0)

    @property
    def unlinked_amount(self):
        """doc_value not yet covered by any allocation — the matching target."""
        return (self.doc_value or 0) - self.linked_amount

    @staticmethod
    def remaining_from(doc_value, doc_value_pay, paid_links, approved):
        """«المتبقي (محسوب)» — a CALCULATED field, not a SOFTECH column:
        invoice value − what SOFTECH shows paid (header, or the payment links when
        they are more) − matches approved here but not yet written to SOFTECH.
        One definition for the page, the grouped view and the exports."""
        paid = max(doc_value_pay or 0, paid_links or 0)
        return (doc_value or 0) - paid - (approved or 0)

    @property
    def remaining_calc(self):
        """«المتبقي (محسوب)» of this invoice after matching (uses prefetched allocations)."""
        if not self.pk:
            return self.doc_value or 0
        links = approved = 0
        for a in self.allocations.all():
            if a.origin == 'approved':
                approved += a.amount
            elif a.origin in ('softech', 'written'):
                links += a.amount
        return self.remaining_from(self.doc_value, self.doc_value_pay, links, approved)

    def _open_credit_of(self, ret):
        links = approved = 0
        for a in ret.allocations.all():
            if a.origin == 'approved':
                approved += a.amount
            elif a.origin in ('softech', 'written'):
                links += a.amount
        left = self.remaining_from(ret.doc_value, ret.doc_value_pay, links, approved)
        return left if left >= 1 else 0          # same 1-EGP rule as recon_returns

    @property
    def returns_bound(self) -> list:
        """The returns whose lines reference THIS purchase (ReturnLink), with the part
        of their credit still open (uses prefetch returned_by__return_invoice__allocations)."""
        out = []
        for l in self.returned_by.all():
            r = l.return_invoice
            if r is None:
                continue
            open_ = min(l.amount or 0, self._open_credit_of(r))
            out.append({'id': r.id, 'label': f'{r.branchcode}/{str(r.docnumber).split(".")[0]}',
                        'docdate': r.docdate, 'amount': l.amount, 'open': open_})
        return out

    @property
    def open_return_credit(self):
        return sum((x['open'] for x in self.returns_bound), start=0)

    @property
    def net_remaining(self):
        """«الصافي بعد المرتجع (محسوب)» = «المتبقي (محسوب)» − open credit of its own returns."""
        return self.remaining_calc - self.open_return_credit


class Payment(models.Model):
    """
    Mirror of one SOFTECH payment/receipt voucher (`cheques` row), keyed by
    (branchcode, cheqsno). direction OUT = paid a supplier, IN = collected
    from a customer.
    """
    party            = models.ForeignKey(ReconParty, on_delete=models.CASCADE, related_name='payments')
    branchcode       = models.CharField(max_length=5, db_index=True)
    cheqsno          = models.IntegerField(db_index=True)              # top مسلسل
    cheqno           = models.CharField(max_length=20, blank=True)     # inner مسلسل
    ourcheqsno       = models.IntegerField(null=True, blank=True)      # رقم إيصال الصرف/الإستلام

    financial_doc_code = models.CharField(max_length=2, blank=True)    # 10=نقدي 20=شيك بنكي … (financialdocs)
    cheqtype         = models.CharField(max_length=2, blank=True)
    direction        = models.CharField(max_length=3, choices=FLOW_DIRECTION_CHOICES, db_index=True)
    party_type       = models.CharField(max_length=10, choices=PARTY_TYPE_CHOICES, db_index=True)

    voucher_date     = models.DateField(db_index=True)                 # cheqdate
    bankcode         = models.CharField(max_length=3, blank=True)      # cash box / bank
    amount           = models.DecimalField(max_digits=18, decimal_places=3, default=0)  # cheqvalue
    note             = models.CharField(max_length=250, blank=True)    # chequenote (often embeds inv serial)
    person_new_bal   = models.DecimalField(max_digits=18, decimal_places=3, default=0)  # personnewbal snapshot
    bank_new_bal     = models.DecimalField(max_digits=18, decimal_places=3, default=0)  # banknewbal snapshot
    block_inv        = models.BooleanField(default=False)              # منع سداد فواتير
    usercode         = models.CharField(max_length=8, blank=True)
    trans_time       = models.DateTimeField(null=True, blank=True)     # precise ordering (F2)

    # Reconstruction bookkeeping: a voucher with NO chequestrans link is the
    # historical problem we exist to fix.
    is_unallocated   = models.BooleanField(default=False, db_index=True,
                                           help_text='payment with no allocation — the historical problem')

    # Correction chains (recon_chains.detect_chains, doc 23 §17): a wrong مدفوعات
    # cancelled by a same-amount مقبوضات shortly after, optionally followed by the
    # corrected مدفوعات (same or another supplier). Owner-confirmed 2026-09-26.
    CHAIN_REVERSED = 'reversed'   # payment cancelled by a receipt → never settles an invoice
    CHAIN_REVERSAL = 'reversal'   # the receipt that cancels it
    CHAIN_REISSUE  = 'reissue'    # the corrected payment that follows
    CHAIN_REFUND   = 'refund'     # a receipt with no prior payment (supplier refund / return)
    CHAIN_ROLE_CHOICES = [
        ('', '—'),
        (CHAIN_REVERSED, 'سند صرف مُلغى بسند مقبوضات'),
        (CHAIN_REVERSAL, 'سند مقبوضات يلغي سند صرف'),
        (CHAIN_REISSUE,  'سند صرف تصحيحي بعد الإلغاء'),
        (CHAIN_REFUND,   'مقبوضات (استرداد من المورد)'),
    ]
    chain_role = models.CharField(max_length=10, choices=CHAIN_ROLE_CHOICES, blank=True,
                                  default='', db_index=True)
    chain_key  = models.CharField(max_length=40, blank=True, default='', db_index=True)
    chain_note = models.CharField(max_length=250, blank=True, default='')
    # the other vouchers of the same chain, readable («مقبوضات 150/61234 · صرف تصحيحي …»)
    chain_partners = models.CharField(max_length=300, blank=True, default='')

    # Bindings (recon_bindings.bind_all, owner 2026-09-29) — mirror only, never SOFTECH:
    #  • a مقبوضات that refunds PART of a مدفوعات (note/serial names it) → bound_payment;
    #    the payment's usable amount becomes amount − refunded_amount (matched NET)
    #  • a مقبوضات whose serial names a PURCHASE invoice → bound_invoice (owner undecided
    #    whether money-back or credit → shown + reviewed, numbers unchanged)
    bound_payment  = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name='bound_refunds')
    bound_invoice  = models.ForeignKey('finance.APInvoice', null=True, blank=True, on_delete=models.SET_NULL,
                                       related_name='bound_receipts')
    refunded_amount = models.DecimalField(max_digits=18, decimal_places=3, default=0,
                                          help_text='Σ receipts bound to this payment (refunded part)')
    bind_note = models.CharField(max_length=300, blank=True, default='')

    source_hash  = models.CharField(max_length=64, blank=True)
    synced_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-voucher_date', 'branchcode', 'cheqsno']
        verbose_name        = 'سند دفع/قبض'
        verbose_name_plural = 'سندات الدفع/القبض'
        constraints = [
            models.UniqueConstraint(fields=['branchcode', 'cheqsno'], name='uq_payment_softech_key'),
        ]
        indexes = [
            models.Index(fields=['party', 'voucher_date']),
            models.Index(fields=['party_type', 'is_unallocated']),
        ]

    def __str__(self):
        return f'سند {self.branchcode}/{self.cheqsno} = {self.amount} ({self.get_direction_display()})'

    @property
    def is_receipt(self) -> bool:
        return (self.cheqtype or '').strip() == '10'

    def allocation_effect(self, amount, invoice_is_return: bool):
        """How much of THIS voucher a link consumes. SOFTECH nets returns inside a
        payment voucher with a POSITIVE docvaluepaynow, so for a مدفوعات a return
        link is a CREDIT (voucher = Σ purchases − Σ returns); for a مقبوضات the
        return link is what the refund settles."""
        if self.is_receipt:
            return amount if invoice_is_return else -amount
        return -amount if invoice_is_return else amount

    @property
    def allocated_amount(self):
        if not self.pk:
            return 0
        return sum((self.allocation_effect(a.amount, a.invoice.is_return)
                    for a in self.allocations.select_related('invoice')), start=0)

    @property
    def net_amount(self):
        """What this voucher really paid: amount − the refunds bound to it."""
        return (self.amount or 0) - (self.refunded_amount or 0)

    @property
    def unallocated_amount(self):
        # a receipt that is bound (it refunds a payment / names an invoice) is explained,
        # not money waiting for an invoice
        if self.is_receipt and (self.bound_payment_id or self.bound_invoice_id):
            return 0
        return self.net_amount - (self.allocated_amount or 0)


class ReturnLink(models.Model):
    """
    A supplier RETURN (doccode 120) → the PURCHASE invoice (doccode 10) it returns,
    from SOFTECH's return lines (stktrans.r_doccode/r_docnumber/r_docdate). About 1
    in 4–5 return lines carries this link; the rest are general returns. `amount` =
    Σ line transprice_total for that purchase within the return.
    """
    return_invoice   = models.ForeignKey('finance.APInvoice', on_delete=models.CASCADE,
                                         related_name='return_links')
    purchase_invoice = models.ForeignKey('finance.APInvoice', null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name='returned_by')
    purchase_branchcode = models.CharField(max_length=5)
    purchase_docnumber  = models.CharField(max_length=20)
    purchase_docdate    = models.DateField(null=True, blank=True)
    amount     = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    synced_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'ربط مرتجع بفاتورة شراء'
        verbose_name_plural = 'روابط المرتجعات'
        constraints = [
            models.UniqueConstraint(
                fields=['return_invoice', 'purchase_branchcode', 'purchase_docnumber', 'purchase_docdate'],
                name='uq_returnlink_key'),
        ]


class Allocation(models.Model):
    """
    An explicit "invoice ← amount from voucher" link — the ReconciliationAllocation
    primitive, mirroring SOFTECH `chequestrans.docvaluepaynow`. Native rows are
    origin='softech'; our reconstructed proposals become 'approved'/'written'.
    """
    ORIGIN_SOFTECH  = 'softech'    # already in chequestrans (ground truth)
    ORIGIN_PROPOSED = 'proposed'   # engine proposal, not yet approved
    ORIGIN_APPROVED = 'approved'   # human-approved, not yet written to SOFTECH
    ORIGIN_WRITTEN  = 'written'    # written back to SOFTECH (Phase G)
    ORIGIN_REVERSED = 'reversed'

    ORIGIN_CHOICES = [
        (ORIGIN_SOFTECH,  'من SOFTECH'),
        (ORIGIN_PROPOSED, 'مقترح'),
        (ORIGIN_APPROVED, 'معتمد'),
        (ORIGIN_WRITTEN,  'مكتوب في SOFTECH'),
        (ORIGIN_REVERSED, 'معكوس'),
    ]

    payment     = models.ForeignKey(Payment,   on_delete=models.CASCADE, related_name='allocations')
    invoice     = models.ForeignKey(APInvoice, on_delete=models.CASCADE, related_name='allocations')
    amount          = models.DecimalField(max_digits=18, decimal_places=3, default=0,
                                          verbose_name='المسدد الآن (docvaluepaynow)')
    cumulative_paid = models.DecimalField(max_digits=18, decimal_places=3, default=0,
                                          verbose_name='إجمالي المسدد (docvaluepaid)')
    origin      = models.CharField(max_length=10, choices=ORIGIN_CHOICES,
                                   default=ORIGIN_SOFTECH, db_index=True)

    # provenance to the candidate that produced a non-native allocation
    candidate   = models.ForeignKey('finance.MatchCandidate', null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name='allocations')
    source_hash = models.CharField(max_length=64, blank=True)
    synced_at   = models.DateTimeField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'تخصيص سداد'
        verbose_name_plural = 'تخصيصات السداد'
        constraints = [
            models.UniqueConstraint(fields=['payment', 'invoice'], name='uq_allocation_payment_invoice'),
        ]
        indexes = [models.Index(fields=['origin'])]

    def __str__(self):
        return f'فاتورة {self.invoice_id} ← {self.amount} من سند {self.payment_id} [{self.origin}]'


class ReconciliationRun(models.Model):
    """One execution of the reconciliation engine over a scope (party/date)."""
    MODE_READONLY  = 'readonly'    # analyse only
    MODE_SUGGEST   = 'suggest'     # generate proposals
    MODE_WRITEBACK = 'writeback'   # Phase G (gated) — not enabled yet

    MODE_CHOICES = [
        (MODE_READONLY,  'قراءة فقط'),
        (MODE_SUGGEST,   'اقتراح'),
        (MODE_WRITEBACK, 'كتابة في SOFTECH'),
    ]

    STATUS_CHOICES = [
        ('pending', 'قيد الانتظار'),
        ('running', 'جارٍ'),
        ('success', 'نجح'),
        ('partial', 'جزئي'),
        ('failed',  'فشل'),
    ]

    mode          = models.CharField(max_length=12, choices=MODE_CHOICES, default=MODE_READONLY)
    status        = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending', db_index=True)
    party_type    = models.CharField(max_length=10, choices=PARTY_TYPE_CHOICES, blank=True)
    party         = models.ForeignKey(ReconParty, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='runs')
    date_from     = models.DateField(null=True, blank=True)
    date_to       = models.DateField(null=True, blank=True)
    rules_version = models.CharField(max_length=20, blank=True)   # scoring config version (auditable)
    params        = models.JSONField(default=dict)
    counts        = models.JSONField(default=dict)   # {invoices, payments, candidates, exceptions, ...}
    started_at    = models.DateTimeField(auto_now_add=True)
    finished_at   = models.DateTimeField(null=True, blank=True)
    triggered_by  = models.CharField(max_length=100, blank=True)
    notes         = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']
        verbose_name        = 'تشغيل تسوية'
        verbose_name_plural = 'تشغيلات التسوية'

    def __str__(self):
        return f'{self.get_mode_display()} | {self.started_at:%Y-%m-%d %H:%M} | {self.status}'


class MatchCandidate(models.Model):
    """
    A proposed (invoice, payment) reconciliation with an explainable confidence.
    Competing candidates for the same invoice/payment can coexist until resolved.
    """
    CONF_HIGH     = 'high'
    CONF_MEDIUM   = 'medium'
    CONF_LOW      = 'low'
    CONF_CONFLICT = 'conflict'

    CONF_CHOICES = [
        (CONF_HIGH,     'ثقة عالية'),
        (CONF_MEDIUM,   'ثقة متوسطة'),
        (CONF_LOW,      'ثقة منخفضة'),
        (CONF_CONFLICT, 'تعارض'),
    ]

    STATUS_PROPOSED   = 'proposed'
    STATUS_APPROVED   = 'approved'
    STATUS_REJECTED   = 'rejected'
    STATUS_WRITTEN    = 'written'
    STATUS_SUPERSEDED = 'superseded'

    STATUS_CHOICES = [
        (STATUS_PROPOSED,   'مقترح'),
        (STATUS_APPROVED,   'معتمد'),
        (STATUS_REJECTED,   'مرفوض'),
        (STATUS_WRITTEN,    'مكتوب'),
        (STATUS_SUPERSEDED, 'مُستبدل'),
    ]

    run              = models.ForeignKey(ReconciliationRun, null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name='candidates')
    party            = models.ForeignKey(ReconParty, on_delete=models.CASCADE, related_name='candidates')
    invoice          = models.ForeignKey(APInvoice, on_delete=models.CASCADE, related_name='candidates')
    payment          = models.ForeignKey(Payment,   on_delete=models.CASCADE, related_name='candidates')
    proposed_amount  = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, default=0)   # 0–100
    confidence_class = models.CharField(max_length=10, choices=CONF_CHOICES,
                                        default=CONF_LOW, db_index=True)
    status           = models.CharField(max_length=12, choices=STATUS_CHOICES,
                                        default=STATUS_PROPOSED, db_index=True)
    rules_version    = models.CharField(max_length=20, blank=True)

    # HOW the pair was found (pairwise scoring vs the max-allocation strategies) and
    # the group it belongs to (one voucher → several invoices, several vouchers → one
    # invoice) so a reviewer can approve/reject the whole split at once.
    STRATEGY_CHOICES = [
        ('pairwise',       'مطابقة مباشرة (مرجع/مبلغ)'),
        ('multi_ref',      'سند يذكر عدة فواتير'),
        ('exact_unique',   'مبلغ مطابق فريد'),
        ('same_amount_nearest', 'نفس المبلغ — الأقرب تاريخًا'),
        ('net_returns',    'مقاصة مع مرتجعات'),
        ('subset_oldest',  'سداد بالأقدم (مجموع فواتير)'),
        ('subset_window',  'مجموع فواتير متتالية'),
        ('installments',   'أقساط لفاتورة واحدة'),
        ('fifo_residual',  'توزيع المتبقي بالأقدم'),
    ]
    strategy  = models.CharField(max_length=20, choices=STRATEGY_CHOICES, default='pairwise',
                                 db_index=True)
    group_key = models.CharField(max_length=60, blank=True, db_index=True)

    decided_by    = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='recon_decisions')
    decided_at    = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-confidence_score', '-created_at']
        verbose_name        = 'مرشح مطابقة'
        verbose_name_plural = 'مرشحو المطابقة'
        constraints = [
            models.UniqueConstraint(fields=['invoice', 'payment', 'run'],
                                    name='uq_candidate_invoice_payment_run'),
        ]
        indexes = [
            models.Index(fields=['status', 'confidence_class']),
            models.Index(fields=['party', 'status']),
        ]

    def __str__(self):
        return f'فاتورة {self.invoice_id} ↔ سند {self.payment_id} @ {self.confidence_score}% [{self.status}]'


class MatchEvidence(models.Model):
    """One explainable signal contributing to a MatchCandidate's confidence."""
    SIGNAL_CHOICES = [
        ('party',     'الطرف'),
        ('amount',    'المبلغ'),
        ('reference', 'المرجع/المسلسل'),
        ('note',      'الملاحظات'),
        ('temporal',  'قرب التاريخ'),
        ('branch',    'الفرع'),
        ('bank',      'البنك/الخزينة'),
        ('user',      'المستخدم'),
        ('method',    'طريقة الدفع'),
        ('sequence',  'التسلسل'),
        ('duplicate', 'تكرار'),
    ]
    # visual chip: ✓ exact | ≈ approximate | ⚠ conflict | ✕ mismatch
    OUTCOME_CHOICES = [
        ('exact',       '✓ مطابق'),
        ('approximate', '≈ تقريبي'),
        ('conflict',    '⚠ تعارض'),
        ('mismatch',    '✕ غير مطابق'),
    ]

    candidate    = models.ForeignKey(MatchCandidate, on_delete=models.CASCADE, related_name='evidence')
    signal       = models.CharField(max_length=12, choices=SIGNAL_CHOICES, db_index=True)
    outcome      = models.CharField(max_length=12, choices=OUTCOME_CHOICES, default='approximate')
    weight       = models.DecimalField(max_digits=6, decimal_places=3, default=0)   # configured weight
    contribution = models.DecimalField(max_digits=6, decimal_places=3, default=0)   # weight × outcome factor
    detail       = models.CharField(max_length=300, blank=True)   # human-readable "why"

    class Meta:
        ordering = ['-contribution']
        verbose_name        = 'دليل مطابقة'
        verbose_name_plural = 'أدلة المطابقة'

    def __str__(self):
        return f'{self.get_signal_display()} {self.get_outcome_display()} ({self.contribution})'


class ReconException(models.Model):
    """A flagged anomaly / risk. Escalates to audit.AbuseFlag for critical cases."""
    TYPE_DUPLICATE_PAYMENT = 'duplicate_payment'
    TYPE_DUPLICATE_INVOICE = 'duplicate_invoice'
    TYPE_OVERPAYMENT       = 'overpayment'
    TYPE_UNDERPAYMENT      = 'underpayment'
    TYPE_UNPAID_OLD        = 'unpaid_old'
    TYPE_ORPHAN_PAYMENT    = 'orphan_payment'     # payment with no plausible invoice
    TYPE_PAID_NO_LINK      = 'paid_no_link'       # settled invoice, no allocation row (the core problem)
    TYPE_BALANCE_MISMATCH  = 'balance_mismatch'   # reconstructed ≠ SOFTECH balance
    TYPE_REUSED_REFERENCE  = 'reused_reference'
    TYPE_SUPPLIER_MISMATCH = 'supplier_mismatch'
    TYPE_CANCELLED         = 'cancelled_reversed'
    TYPE_MISALLOCATION     = 'misallocation'       # SOFTECH linked a payment to the wrong same-party invoice
    TYPE_PAID_RETURNED     = 'paid_returned'       # purchase paid although (partly) returned
    TYPE_OPEN_RETURN       = 'open_return'         # return not yet netted/refunded — supplier owes us
    TYPE_RECEIPT_ON_INVOICE = 'receipt_on_invoice' # مقبوضات naming a purchase invoice — owner decides meaning
    TYPE_SUSPECT_AMOUNT    = 'suspect_amount'      # voucher amount judged an entry error (owner) — never auto-matched
    TYPE_ANOMALY           = 'anomaly'

    TYPE_CHOICES = [
        (TYPE_DUPLICATE_PAYMENT, 'سند مكرر'),
        (TYPE_DUPLICATE_INVOICE, 'فاتورة مكررة'),
        (TYPE_OVERPAYMENT,       'دفع زائد'),
        (TYPE_UNDERPAYMENT,      'دفع ناقص'),
        (TYPE_UNPAID_OLD,        'فاتورة قديمة غير مسددة'),
        (TYPE_ORPHAN_PAYMENT,    'سند بلا فاتورة'),
        (TYPE_PAID_NO_LINK,      'مسدد بلا ربط'),
        (TYPE_BALANCE_MISMATCH,  'فرق رصيد غير مفسَّر'),
        (TYPE_REUSED_REFERENCE,  'مرجع مُعاد استخدامه'),
        (TYPE_SUPPLIER_MISMATCH, 'عدم تطابق الطرف'),
        (TYPE_CANCELLED,         'ملغى/معكوس'),
        (TYPE_MISALLOCATION,     'ربط خاطئ (تبادل فواتير)'),
        (TYPE_PAID_RETURNED,     'فاتورة مسددة رغم إرجاعها'),
        (TYPE_OPEN_RETURN,       'مرتجع مستحق على المورد'),
        (TYPE_RECEIPT_ON_INVOICE, 'مقبوضات مرتبطة بفاتورة شراء (تحتاج تحديد)'),
        (TYPE_SUSPECT_AMOUNT,    'مبلغ السند مشكوك فيه (خطأ إدخال محتمل)'),
        (TYPE_ANOMALY,           'شذوذ'),
    ]

    SEVERITY_CHOICES = [
        ('info',     'معلومة'),
        ('warning',  'تحذير'),
        ('critical', 'حرج'),
    ]
    STATUS_CHOICES = [
        ('open',          'مفتوح'),
        ('investigating', 'قيد التحقيق'),
        ('resolved',      'محلول'),
        ('dismissed',     'مرفوض'),
    ]

    run            = models.ForeignKey(ReconciliationRun, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='exceptions')
    party          = models.ForeignKey(ReconParty, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='exceptions')
    invoice        = models.ForeignKey(APInvoice, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='exceptions')
    payment        = models.ForeignKey(Payment, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='exceptions')
    exception_type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_index=True)
    severity       = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='warning', db_index=True)
    anomaly_score  = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    detail         = models.TextField(blank=True)
    status         = models.CharField(max_length=15, choices=STATUS_CHOICES, default='open', db_index=True)
    abuse_flag_id  = models.PositiveIntegerField(null=True, blank=True)
    resolved_by    = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name='recon_exceptions_resolved')
    resolved_at    = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)
    created_at     = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'استثناء تسوية'
        verbose_name_plural = 'استثناءات التسوية'
        indexes = [
            models.Index(fields=['status', 'severity']),
            models.Index(fields=['exception_type', 'status']),
        ]

    def __str__(self):
        return f'[{self.get_severity_display()}] {self.get_exception_type_display()} | {self.get_status_display()}'


class ReconAuditEvent(models.Model):
    """
    Immutable audit trail for every reconciliation decision / write. Answers,
    years later, WHY a payment was matched to an invoice (§22). Never edited.
    """
    action        = models.CharField(max_length=50, db_index=True,
                                     help_text='candidate_proposed / approved / rejected / '
                                               'allocation_written / reversed / run_started / …')
    run           = models.ForeignKey(ReconciliationRun, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='audit_events')
    party         = models.ForeignKey(ReconParty, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='audit_events')
    candidate     = models.ForeignKey(MatchCandidate, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='audit_events')
    allocation    = models.ForeignKey(Allocation, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='audit_events')
    rules_version = models.CharField(max_length=20, blank=True)
    before_state  = models.JSONField(default=dict)   # snapshot / hash before
    after_state   = models.JSONField(default=dict)   # snapshot / hash after
    detail        = models.TextField(blank=True)
    error         = models.TextField(blank=True)
    performed_by  = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='recon_audit_events')
    performed_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-performed_at']
        verbose_name        = 'حدث تدقيق تسوية'
        verbose_name_plural = 'أحداث تدقيق التسوية'

    def __str__(self):
        return f'{self.action} | {self.performed_at:%Y-%m-%d %H:%M}'
