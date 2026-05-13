from django.db import models


class ShortageList(models.Model):
    """
    A shortage document — one per branch per event (e.g. supplier visit, weekly count).
    Contains multiple ShortageItem lines.
    """
    STATUS = [
        ('open',      'مفتوحة'),
        ('submitted', 'مُرسَلة'),
        ('resolved',  'محلولة'),
    ]

    branch        = models.ForeignKey('branches.Branch', on_delete=models.CASCADE,
                                      related_name='shortage_lists', verbose_name='الفرع')
    created_by    = models.ForeignKey('users.StaffProfile', on_delete=models.SET_NULL,
                                      null=True, related_name='shortage_lists',
                                      verbose_name='أُنشئت بواسطة')
    status        = models.CharField(max_length=15, choices=STATUS, default='open',
                                     verbose_name='الحالة')
    title         = models.CharField(max_length=200, blank=True, verbose_name='العنوان')
    notes         = models.TextField(blank=True, verbose_name='ملاحظات')
    source        = models.CharField(max_length=30, default='manual',
                                     verbose_name='المصدر',
                                     help_text='manual | ocr | imported')
    # For OCR uploads
    source_image  = models.ImageField(upload_to='shortage_images/', null=True, blank=True,
                                       verbose_name='صورة القائمة')
    created_at    = models.DateTimeField(auto_now_add=True)
    updated_at    = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name        = 'قائمة نواقص'
        verbose_name_plural = 'قوائم النواقص'
        ordering            = ['-created_at']

    def __str__(self):
        return f'نواقص {self.branch} — {self.created_at:%Y-%m-%d}'


class ShortageItem(models.Model):
    """
    One item in a shortage list.
    May be matched to a catalog Item (via fuzzy matching) or left unmatched.
    """
    shortage_list    = models.ForeignKey(ShortageList, on_delete=models.CASCADE,
                                          related_name='items', verbose_name='قائمة النواقص')
    # Catalog match (populated by matcher)
    item             = models.ForeignKey('catalog.Item', on_delete=models.SET_NULL,
                                          null=True, blank=True, related_name='+',
                                          verbose_name='الصنف المطابق')
    # Raw name as entered/scanned
    raw_name         = models.CharField(max_length=300, verbose_name='الاسم كما أُدخل')
    quantity_needed  = models.DecimalField(max_digits=10, decimal_places=3, default=1,
                                            verbose_name='الكمية المطلوبة')
    unit             = models.CharField(max_length=20, blank=True, verbose_name='الوحدة')
    notes            = models.CharField(max_length=300, blank=True, verbose_name='ملاحظات')

    # Match metadata
    match_score      = models.FloatField(null=True, blank=True, verbose_name='نسبة التطابق')
    is_confirmed     = models.BooleanField(default=False, verbose_name='مُأكَّد')
    is_unmatched     = models.BooleanField(default=False, verbose_name='غير مطابق')

    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name        = 'صنف ناقص'
        verbose_name_plural = 'أصناف النواقص'
        ordering            = ['raw_name']

    def __str__(self):
        return f'{self.raw_name} × {self.quantity_needed}'
