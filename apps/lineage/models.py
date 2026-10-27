"""
apps/lineage/models.py — shared transaction-lineage graph (doc 25 §4.1 / §7).

A thin, module-agnostic registry of the NATIVE documents our workflows touch, and of the
relationships between them. It never duplicates a document's business data — the mirrors
(finance.APInvoice / finance.Payment / customers.PurchaseHistory / pos_orders …) stay the
source; a DocumentRef only carries the identity + the few display fields a lineage graph
needs, plus a pointer back to the mirror row.

Identity rule (SOFTECH): docnumbers are per-(branch, doctype) sequences and repeat across
branches and years, so a native document is ALWAYS keyed by the 4-part key
(branchcode, doccode, docnumber, docdate). Vouchers (cheques) use doccode 'VCH' and
docnumber = cheqsno (unique per branch).
"""
from django.db import models


class DocumentRef(models.Model):
    SYSTEM_SOFTECH = 'softech'
    SYSTEM_POS     = 'pos_order'
    SYSTEM_CHOICES = [(SYSTEM_SOFTECH, 'SOFTECH'), (SYSTEM_POS, 'أمر بيع (المنصة)')]

    KIND_PURCHASE        = 'purchase'
    KIND_SUPPLIER_RETURN = 'supplier_return'
    KIND_SALE            = 'sale'
    KIND_SALE_RETURN     = 'sale_return'
    KIND_VOUCHER         = 'payment_voucher'
    KIND_CHOICES = [
        (KIND_PURCHASE,        'فاتورة شراء'),
        (KIND_SUPPLIER_RETURN, 'مرتجع مورد'),
        (KIND_SALE,            'فاتورة بيع'),
        (KIND_SALE_RETURN,     'مرتجع بيع'),
        (KIND_VOUCHER,         'سند صرف / قبض'),
    ]

    DOCCODE_VOUCHER = 'VCH'

    system     = models.CharField(max_length=12, choices=SYSTEM_CHOICES, default=SYSTEM_SOFTECH)
    doc_kind   = models.CharField(max_length=20, choices=KIND_CHOICES, db_index=True)
    branchcode = models.CharField(max_length=5, db_index=True)
    doccode    = models.CharField(max_length=5)
    docnumber  = models.CharField(max_length=20, db_index=True)
    docdate    = models.DateField(db_index=True)

    # display snapshot (refreshed from the mirror on every reconstruction)
    amount     = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    party_code = models.CharField(max_length=12, blank=True, db_index=True)   # supplier / contract account
    party_name = models.CharField(max_length=300, blank=True)
    phcode     = models.CharField(max_length=20, blank=True, db_index=True)   # customer PIC (sales)
    channel    = models.CharField(max_length=5, blank=True)                   # ptclassif (sales)
    usercode   = models.CharField(max_length=20, blank=True)
    doc_time   = models.DateTimeField(null=True, blank=True)
    note       = models.CharField(max_length=300, blank=True)

    # pointer back to the authoritative mirror row ('finance.apinvoice', 42)
    source_model = models.CharField(max_length=60, blank=True)
    source_pk    = models.BigIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'مستند مرجعي'
        verbose_name_plural = 'مستندات مرجعية'
        constraints = [
            models.UniqueConstraint(fields=['system', 'branchcode', 'doccode', 'docnumber', 'docdate'],
                                    name='uq_lineage_docref_4part'),
        ]
        indexes = [models.Index(fields=['source_model', 'source_pk'])]

    def __str__(self):
        return f'{self.get_doc_kind_display()} {self.branchcode}/{self.doccode}/{self.docnumber} ({self.docdate})'

    @property
    def label(self) -> str:
        return f'{self.branchcode}/{self.docnumber}'


class DocumentEdge(models.Model):
    """A relationship between two documents. Never deleted: a wrong link is REJECTED or
    SUPERSEDED so the history of what the system (or a person) believed stays visible."""
    REL_PAYS      = 'pays'        # voucher → purchase invoice (entitlement redemption)
    REL_FUNDED_BY = 'funded_by'   # voucher → the POS sale(s) its cash paid for
    REL_RETURNS   = 'returns'     # return doc → original doc
    REL_CANCELS   = 'cancels'     # full same-day return → the sale it voids
    REL_RELATED   = 'related_to'
    RELATION_CHOICES = [
        (REL_PAYS,      'يسدد'),
        (REL_FUNDED_BY, 'مموَّل منه'),
        (REL_RETURNS,   'مرتجع لـ'),
        (REL_CANCELS,   'يلغي'),
        (REL_RELATED,   'مرتبط بـ'),
    ]

    ORIGIN_NATIVE  = 'native'    # SOFTECH itself stores the link (e.g. chequestrans)
    ORIGIN_MATCHED = 'matched'   # our deterministic matcher proposed it
    ORIGIN_MANUAL  = 'manual'    # a person created it
    ORIGIN_CHOICES = [(ORIGIN_NATIVE, 'من SOFTECH'), (ORIGIN_MATCHED, 'مطابقة آلية'),
                      (ORIGIN_MANUAL, 'يدوي')]

    STATUS_PROPOSED   = 'proposed'
    STATUS_CONFIRMED  = 'confirmed'
    STATUS_REJECTED   = 'rejected'
    STATUS_SUPERSEDED = 'superseded'
    STATUS_CHOICES = [(STATUS_PROPOSED, 'مقترح'), (STATUS_CONFIRMED, 'مؤكد'),
                      (STATUS_REJECTED, 'مرفوض'), (STATUS_SUPERSEDED, 'مُستبدل')]

    from_ref   = models.ForeignKey(DocumentRef, on_delete=models.PROTECT, related_name='edges_out')
    to_ref     = models.ForeignKey(DocumentRef, on_delete=models.PROTECT, related_name='edges_in')
    relation   = models.CharField(max_length=12, choices=RELATION_CHOICES, db_index=True)
    amount     = models.DecimalField(max_digits=18, decimal_places=3, null=True, blank=True)
    origin     = models.CharField(max_length=8, choices=ORIGIN_CHOICES)
    status     = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PROPOSED,
                                  db_index=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)   # 0–100
    evidence   = models.JSONField(default=list, blank=True)    # [{signal, points, detail}]
    decided_by = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'علاقة مستندات'
        verbose_name_plural = 'علاقات المستندات'
        constraints = [
            models.UniqueConstraint(fields=['from_ref', 'to_ref', 'relation'],
                                    name='uq_lineage_edge'),
        ]

    def __str__(self):
        return f'{self.from_ref} —{self.relation}→ {self.to_ref} [{self.status}]'

    @property
    def is_active(self) -> bool:
        return self.status in (self.STATUS_PROPOSED, self.STATUS_CONFIRMED)
