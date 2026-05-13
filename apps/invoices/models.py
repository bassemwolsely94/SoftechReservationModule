"""
apps/invoices/models.py

SupplierInvoice — a scanned / manually entered supplier invoice.
InvoiceLine    — one item line on that invoice.

OCR workflow:
  1. Upload image → SupplierInvoice created with status='pending'
  2. Background task (or synchronous call) runs pytesseract/easyocr
  3. Lines extracted → InvoiceLine rows created with raw_text
  4. Fuzzy matcher (reuses shortage.matching) links each line to catalog Item
  5. User reviews & confirms matches, adjusts discount rates
  6. Invoice finalized
"""
from django.db import models


class SupplierInvoice(models.Model):
    STATUS = [
        ('pending',    'في الانتظار'),
        ('processing', 'جاري المعالجة'),
        ('review',     'قيد المراجعة'),
        ('confirmed',  'مُأكَّدة'),
        ('rejected',   'مرفوضة'),
    ]

    branch          = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                         related_name='invoices', verbose_name='الفرع')
    created_by      = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                         null=True, related_name='invoices',
                                         verbose_name='أُنشئت بواسطة')
    status          = models.CharField(max_length=20, choices=STATUS, default='pending',
                                        verbose_name='الحالة')

    # Supplier info (manual or extracted)
    supplier_name   = models.CharField(max_length=200, blank=True, verbose_name='اسم المورد')
    invoice_number  = models.CharField(max_length=50, blank=True, verbose_name='رقم الفاتورة')
    invoice_date    = models.DateField(null=True, blank=True, verbose_name='تاريخ الفاتورة')
    currency        = models.CharField(max_length=10, default='EGP', verbose_name='العملة')

    # Discount at invoice level (applied to all lines unless overridden)
    global_discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                               verbose_name='خصم عام %')
    global_discount_amt = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                               verbose_name='خصم عام بمبلغ')

    # Source image (for OCR)
    source_image    = models.ImageField(upload_to='invoice_images/', null=True, blank=True,
                                         verbose_name='صورة الفاتورة')
    raw_ocr_text    = models.TextField(blank=True, verbose_name='نص OCR الخام')

    notes           = models.TextField(blank=True, verbose_name='ملاحظات')
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'فاتورة مورد'
        verbose_name_plural = 'فواتير الموردين'
        ordering            = ['-created_at']

    def __str__(self):
        return f'فاتورة {self.supplier_name or "?"} — {self.invoice_number or self.id}'

    @property
    def total_before_discount(self):
        return sum(l.line_total or 0 for l in self.lines.all())

    @property
    def total_after_discount(self):
        sub = self.total_before_discount
        pct = float(self.global_discount_pct or 0)
        amt = float(self.global_discount_amt or 0)
        return sub * (1 - pct / 100) - amt


class InvoiceLine(models.Model):
    invoice         = models.ForeignKey(SupplierInvoice, on_delete=models.CASCADE,
                                         related_name='lines', verbose_name='الفاتورة')
    item            = models.ForeignKey('catalog.Item', on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name='+',
                                         verbose_name='الصنف المطابق')
    raw_text        = models.CharField(max_length=500, blank=True, verbose_name='النص الخام')
    manual_name     = models.CharField(max_length=300, blank=True, verbose_name='اسم يدوي')

    quantity        = models.DecimalField(max_digits=10, decimal_places=3, default=1,
                                           verbose_name='الكمية')
    unit_price      = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                           verbose_name='سعر الوحدة')
    discount_pct    = models.DecimalField(max_digits=5, decimal_places=2, default=0,
                                           verbose_name='خصم السطر %')
    discount_amt    = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                           verbose_name='خصم السطر بمبلغ')
    line_total      = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True,
                                           verbose_name='الإجمالي')

    match_score     = models.FloatField(null=True, blank=True, verbose_name='نسبة التطابق')
    is_confirmed    = models.BooleanField(default=False, verbose_name='مُأكَّد')
    notes           = models.CharField(max_length=300, blank=True, verbose_name='ملاحظات')
    order           = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name        = 'سطر فاتورة'
        verbose_name_plural = 'سطور الفواتير'
        ordering            = ['order', 'id']

    def compute_total(self):
        qty   = float(self.quantity or 0)
        price = float(self.unit_price or 0)
        sub   = qty * price
        disc_p = float(self.discount_pct or 0)
        disc_a = float(self.discount_amt or 0)
        return sub * (1 - disc_p / 100) - disc_a

    def save(self, *args, **kwargs):
        self.line_total = self.compute_total()
        super().save(*args, **kwargs)
