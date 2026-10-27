"""
apps/commerce/models.py — Phase 1 scaffolding for the Commerce Document engine.

A generic, type-driven document family that reuses the insurance module's line /
pricing / audit ideas WITHOUT touching it: quotations, retail/walk-in invoices,
and hospital allocation grids.  See the design doc for the locked decisions —
manual per-line pricing, 14 % inclusive VAT on flagged lines only, hand-entered
items, own QT-/INV- numbering, ours-only (no SOFTECH writeback), and the
Option-A allocation grid (one document, items × branches, AllocationCell qty).

Phase 1 is data + pricing only — no views, no export, no UI.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db import models

_Q = Decimal('0.01')


def q2(v) -> Decimal:
    return Decimal(str(v or 0)).quantize(_Q, rounding=ROUND_HALF_UP)


# ═══════════════════════════════════════════════════════════════════════════════
# TYPE REGISTRY — behaviour lives in config rows, not per-type if/else
# ═══════════════════════════════════════════════════════════════════════════════

class DocumentType(models.Model):
    PRICING_MANUAL   = 'manual_line'     # hand-typed price per line (quotation/retail)
    PRICING_PQ       = 'pq_aggregate'    # insurance PowerQuery aggregate (future adoption)
    PRICING_NONE     = 'none'
    PRICING_CHOICES  = [
        (PRICING_MANUAL, 'سعر يدوي لكل بند'),
        (PRICING_PQ,     'تجميعي (تأمين)'),
        (PRICING_NONE,   'بدون تسعير'),
    ]

    code            = models.CharField(max_length=30, unique=True, verbose_name='الكود')          # quotation | retail_invoice | allocation
    name            = models.CharField(max_length=100, verbose_name='الاسم')
    number_prefix   = models.CharField(max_length=8, verbose_name='بادئة الترقيم')                 # QT | INV | ALC
    pricing_profile = models.CharField(max_length=20, choices=PRICING_CHOICES,
                                       default=PRICING_MANUAL, verbose_name='طريقة التسعير')
    is_allocation   = models.BooleanField(default=False, verbose_name='شبكة توزيع (فروع)')
    # Lifecycle states as an ordered list of {code,label}; minimal/configurable for now.
    lifecycle       = models.JSONField(default=list, blank=True, verbose_name='مراحل الحالة')
    default_vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('14.00'),
                                           verbose_name='نسبة ض.ق.م الافتراضية %')
    is_active       = models.BooleanField(default=True, verbose_name='نشط')
    created_at      = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'نوع مستند'
        verbose_name_plural = 'أنواع المستندات'
        ordering            = ['name']

    def __str__(self):
        return f'{self.name} ({self.code})'


# ═══════════════════════════════════════════════════════════════════════════════
# RECIPIENTS — hospitals (multi-branch), retail customers, others
# ═══════════════════════════════════════════════════════════════════════════════

class Recipient(models.Model):
    KIND_HOSPITAL = 'hospital'
    KIND_RETAIL   = 'retail'
    KIND_OTHER    = 'other'
    KIND_CHOICES  = [
        (KIND_HOSPITAL, 'مستشفى / جهة متعددة الفروع'),
        (KIND_RETAIL,   'عميل تجزئة / توصيل'),
        (KIND_OTHER,    'أخرى'),
    ]

    name       = models.CharField(max_length=200, verbose_name='الاسم')
    kind       = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_OTHER, verbose_name='النوع')
    phone      = models.CharField(max_length=40, blank=True, verbose_name='الهاتف')
    address    = models.TextField(blank=True, verbose_name='العنوان')
    tax_id     = models.CharField(max_length=40, blank=True, verbose_name='الرقم الضريبي')
    notes      = models.TextField(blank=True, verbose_name='ملاحظات')
    is_active  = models.BooleanField(default=True, verbose_name='نشط')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'جهة مستلمة'
        verbose_name_plural = 'الجهات المستلمة'
        ordering            = ['name']

    def __str__(self):
        return self.name


class RecipientLocation(models.Model):
    """A branch / receiving end of a recipient — the columns of the allocation grid."""
    recipient  = models.ForeignKey(Recipient, on_delete=models.CASCADE,
                                   related_name='locations', verbose_name='الجهة')
    name       = models.CharField(max_length=120, verbose_name='اسم الفرع')
    code       = models.CharField(max_length=30, blank=True, verbose_name='كود الفرع')
    address    = models.TextField(blank=True, verbose_name='العنوان')
    sort_order = models.PositiveIntegerField(default=0, verbose_name='الترتيب')
    is_active  = models.BooleanField(default=True, verbose_name='نشط')

    class Meta:
        verbose_name        = 'فرع الجهة'
        verbose_name_plural = 'فروع الجهات'
        ordering            = ['recipient', 'sort_order', 'name']
        unique_together     = [['recipient', 'name']]

    def __str__(self):
        return f'{self.recipient.name} — {self.name}'


# ═══════════════════════════════════════════════════════════════════════════════
# DOCUMENT + LINES + ALLOCATION CELLS
# ═══════════════════════════════════════════════════════════════════════════════

def next_document_number(doc_type: 'DocumentType', on_date=None) -> str:
    """`{PREFIX}-{YYYY}-{NNNNN}` — per type, per year, gap-tolerant."""
    from django.utils import timezone
    year = (on_date or timezone.now().date()).year
    prefix = f'{doc_type.number_prefix}-{year}-'
    last = (CommerceDocument.objects
            .filter(doc_type=doc_type, number__startswith=prefix)
            .order_by('-number').values_list('number', flat=True).first())
    seq = 1
    if last:
        try:
            seq = int(last.rsplit('-', 1)[1]) + 1
        except (ValueError, IndexError):
            seq = CommerceDocument.objects.filter(doc_type=doc_type, number__startswith=prefix).count() + 1
    return f'{prefix}{seq:05d}'


class CommerceDocument(models.Model):
    STATUS_DRAFT = 'draft'

    doc_type    = models.ForeignKey(DocumentType, on_delete=models.PROTECT,
                                    related_name='documents', verbose_name='النوع')
    recipient   = models.ForeignKey(Recipient, on_delete=models.PROTECT,
                                    null=True, blank=True, related_name='documents', verbose_name='الجهة')
    number      = models.CharField(max_length=40, unique=True, verbose_name='رقم المستند')
    doc_date    = models.DateField(verbose_name='التاريخ')
    valid_until = models.DateField(null=True, blank=True, verbose_name='صالح حتى')   # quotations
    status      = models.CharField(max_length=30, default=STATUS_DRAFT, verbose_name='الحالة')
    vat_rate    = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('14.00'),
                                      verbose_name='نسبة ض.ق.م %')

    # Cached totals (recomputed via recompute_totals) — all VAT-inclusive except
    # subtotal_ex_vat, which is the taxable/base portion.
    subtotal_ex_vat = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='الصافي قبل الضريبة')
    vat_total       = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='إجمالي الضريبة')
    total           = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='الإجمالي شامل الضريبة')

    notes       = models.TextField(blank=True, verbose_name='ملاحظات')
    created_by  = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name='+', verbose_name='أنشأها')
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'مستند تجاري'
        verbose_name_plural = 'المستندات التجارية'
        ordering            = ['-doc_date', '-id']

    def __str__(self):
        return f'{self.number} — {self.recipient or "—"}'

    def recompute_totals(self, save=True):
        from .pricing import compute_document_totals
        # Drop any prefetched 'lines' (the viewset prefetches for the detail read)
        # so we re-read the CURRENT lines after an add/edit/cell mutation.
        self._prefetched_objects_cache = {}
        t = compute_document_totals(self)
        self.subtotal_ex_vat = t['subtotal_ex_vat']
        self.vat_total       = t['vat_total']
        self.total           = t['total']
        if save:
            self.save(update_fields=['subtotal_ex_vat', 'vat_total', 'total', 'updated_at'])
        return t


class DocumentLine(models.Model):
    document      = models.ForeignKey(CommerceDocument, on_delete=models.CASCADE,
                                      related_name='lines', verbose_name='المستند')
    sort_order    = models.PositiveIntegerField(default=0, verbose_name='الترتيب')
    item_code     = models.CharField(max_length=40, blank=True, verbose_name='كود الصنف')
    item_name     = models.CharField(max_length=200, verbose_name='اسم الصنف')          # hand-entered
    unit_price    = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                        verbose_name='سعر الوحدة (شامل الضريبة)')          # VAT-inclusive
    quantity      = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                        verbose_name='الكمية')                            # allocation: = Σ cells
    vat_applicable = models.BooleanField(default=False, verbose_name='خاضع للضريبة')
    notes         = models.CharField(max_length=200, blank=True, verbose_name='ملاحظة')

    class Meta:
        verbose_name        = 'بند مستند'
        verbose_name_plural = 'بنود المستند'
        ordering            = ['document', 'sort_order', 'id']

    def __str__(self):
        return f'{self.item_name} × {self.quantity}'

    # ── VAT-inclusive derivations ──────────────────────────────────────────────
    @property
    def line_total(self) -> Decimal:
        """Gross (VAT-inclusive) line amount."""
        return q2(Decimal(str(self.unit_price or 0)) * Decimal(str(self.quantity or 0)))

    def vat_amount(self, rate: Decimal) -> Decimal:
        """VAT PORTION already inside line_total (back-computed), 0 if not flagged.
        inclusive: vat = gross × r / (100 + r)."""
        if not self.vat_applicable:
            return Decimal('0.00')
        r = Decimal(str(rate or 0))
        return q2(self.line_total * r / (Decimal('100') + r))

    def base_amount(self, rate: Decimal) -> Decimal:
        return q2(self.line_total - self.vat_amount(rate))

    def sync_quantity_from_cells(self, save=True):
        """Allocation docs: line.quantity is the sum of its per-branch cells."""
        total = self.cells.aggregate(s=models.Sum('quantity'))['s'] or Decimal('0')
        self.quantity = q2(total)
        if save:
            self.save(update_fields=['quantity'])
        return self.quantity


class AllocationCell(models.Model):
    """Option-A allocation grid: quantity of one line at one branch (a matrix cell)."""
    line     = models.ForeignKey(DocumentLine, on_delete=models.CASCADE,
                                 related_name='cells', verbose_name='البند')
    location = models.ForeignKey(RecipientLocation, on_delete=models.CASCADE,
                                 related_name='cells', verbose_name='الفرع')
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الكمية')

    class Meta:
        verbose_name        = 'خلية توزيع'
        verbose_name_plural = 'خلايا التوزيع'
        unique_together     = [['line', 'location']]
        indexes             = [models.Index(fields=['line', 'location'])]

    def __str__(self):
        return f'{self.line_id}@{self.location_id} = {self.quantity}'
