from django.db import models


class StockCountSession(models.Model):
    """
    One physical stock-count event at a branch.
    Can be created from a SOFTECH stktrans document or from scratch.
    """
    STATUS = [
        ('open',      'قيد الجرد'),
        ('completed', 'مكتمل'),
        ('cancelled', 'ملغى'),
    ]

    branch          = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                        related_name='stock_counts', verbose_name='الفرع')
    created_by      = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                        null=True, related_name='stock_counts',
                                        verbose_name='أُنشئت بواسطة')
    status          = models.CharField(max_length=15, choices=STATUS, default='open',
                                       verbose_name='الحالة')
    notes           = models.TextField(blank=True, verbose_name='ملاحظات')

    # Optional link to a SOFTECH document that was used to populate items
    erp_doc_code    = models.CharField(max_length=10, blank=True, verbose_name='كود المستند ERP')
    erp_doc_number  = models.CharField(max_length=20, blank=True, verbose_name='رقم المستند ERP')

    count_date      = models.DateField(verbose_name='تاريخ الجرد')
    created_at      = models.DateTimeField(auto_now_add=True)
    completed_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name        = 'جلسة جرد'
        verbose_name_plural = 'جلسات الجرد'
        ordering            = ['-created_at']

    def __str__(self):
        return f'جرد {self.branch} — {self.count_date}'

    @property
    def total_lines(self):
        return self.lines.count()

    @property
    def discrepancy_count(self):
        return self.lines.filter(has_discrepancy=True).count()


class StockCountLine(models.Model):
    """
    One item line inside a stock-count session.
    Stores system quantity (from Django ItemStock) and actual counted quantity.
    """
    session         = models.ForeignKey(StockCountSession, on_delete=models.CASCADE,
                                        related_name='lines', verbose_name='جلسة الجرد')
    item            = models.ForeignKey('catalog.Item', on_delete=models.CASCADE,
                                        null=True, blank=True, related_name='+',
                                        verbose_name='الصنف')
    manual_item_name = models.CharField(max_length=200, blank=True,
                                         verbose_name='اسم الصنف (يدوي)')

    # Quantities
    system_qty      = models.DecimalField(max_digits=10, decimal_places=3, default=0,
                                          verbose_name='كمية النظام')
    counted_qty     = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True,
                                           verbose_name='الكمية المعدودة')
    # Difference = counted_qty - system_qty (positive = surplus, negative = shortage)
    difference      = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True,
                                           verbose_name='الفرق')
    has_discrepancy = models.BooleanField(default=False, verbose_name='يوجد فرق')

    # Reference to ERP transaction line (optional)
    erp_transqty    = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True,
                                           verbose_name='كمية ERP')
    notes           = models.CharField(max_length=300, blank=True, verbose_name='ملاحظات السطر')
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'سطر جرد'
        verbose_name_plural = 'سطور الجرد'
        ordering            = ['item__name']

    def save(self, *args, **kwargs):
        if self.counted_qty is not None and self.system_qty is not None:
            self.difference = self.counted_qty - self.system_qty
            self.has_discrepancy = abs(self.difference) > 0.001
        super().save(*args, **kwargs)

    def __str__(self):
        name = self.item.name if self.item_id else self.manual_item_name
        return f'{name}: sys={self.system_qty}, counted={self.counted_qty}'
