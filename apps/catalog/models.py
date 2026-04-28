from django.db import models


class Category(models.Model):
    softech_id = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    name_ar = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['name']

    def __str__(self):
        return self.name_ar or self.name


class Item(models.Model):
    softech_id = models.CharField(max_length=6, unique=True)          # itemcode varchar(6)
    name = models.CharField(max_length=100, db_index=True)             # itemname
    name_scientific = models.CharField(max_length=100, blank=True)    # itemname_scientific
    barcode = models.CharField(max_length=15, blank=True, db_index=True)  # itembarcode
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    supplier_code = models.CharField(max_length=8, blank=True)         # suppcode
    family_code = models.CharField(max_length=5, blank=True)           # familycode
    unit_price = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    unit_sale_price = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    medicine_type = models.CharField(max_length=2, blank=True)         # itemmedicine
    requires_fridge = models.BooleanField(default=False)               # fridgeitem='1'
    comment = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)
    last_synced = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def display_name(self):
        if self.name_scientific:
            return f"{self.name} ({self.name_scientific})"
        return self.name


class ItemStock(models.Model):
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name='stock_levels')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE)
    softech_store_code = models.CharField(max_length=3, blank=True)   # storecode
    quantity_on_hand = models.DecimalField(max_digits=10, decimal_places=3, default=0)  # nowqty
    monthly_qty = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    on_order_qty = models.DecimalField(max_digits=10, decimal_places=3, default=0)
    last_synced = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('item', 'branch', 'softech_store_code')

    def __str__(self):
        return f"{self.item.name} @ {self.branch.name}: {self.quantity_on_hand}"

    @property
    def stock_status(self):
        if self.quantity_on_hand <= 0:
            return 'out_of_stock'
        if self.quantity_on_hand < 5:
            return 'low_stock'
        return 'in_stock'

    @property
    def stock_status_label(self):
        return {
            'out_of_stock': 'نفد من المخزن',
            'low_stock': 'مخزون منخفض',
            'in_stock': 'متاح',
        }.get(self.stock_status, 'غير معروف')
