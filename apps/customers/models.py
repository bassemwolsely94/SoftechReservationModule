from django.db import models


class Customer(models.Model):
    softech_id = models.CharField(max_length=13, unique=True, null=True, blank=True)
    softech_ptcode = models.CharField(max_length=3, blank=True)
    softech_ptclassifcode = models.CharField(max_length=5, blank=True)
    name = models.CharField(max_length=255, db_index=True)
    phone = models.CharField(max_length=50, db_index=True, blank=True)
    phone_alt = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    chronic_conditions = models.TextField(blank=True)      # staff-entered
    notes_softech = models.TextField(blank=True)            # personnote from SOFTECH
    discount_percent = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    preferred_branch = models.ForeignKey(
        'branches.Branch', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='customers'
    )
    created_by = models.ForeignKey(
        'users.StaffProfile', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='created_customers'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.phone})"

    @property
    def customer_type_label(self):
        labels = {
            '90': 'توصيل',      # Delivery
            '91': 'كاش',         # Cash
            '15': 'تأمين صحي',   # Insurance
        }
        return labels.get(self.softech_ptclassifcode, 'عميل')

    @property
    def customer_type_color(self):
        colors = {
            '90': 'blue',
            '91': 'gray',
            '15': 'green',
        }
        return colors.get(self.softech_ptclassifcode, 'gray')

    @property
    def total_purchases(self):
        return self.purchases.count()

    @property
    def lifetime_value(self):
        from django.db.models import Sum
        result = self.purchases.aggregate(total=Sum('total_amount'))
        return result['total'] or 0


class CustomerNote(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='notes')
    note = models.TextField()
    created_by = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note for {self.customer.name} at {self.created_at:%Y-%m-%d}"


class PurchaseHistory(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='purchases')
    softech_invoice_id = models.CharField(max_length=150, unique=True)
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE)
    doc_code = models.CharField(max_length=3, blank=True)  # '115' = sale, '30' = return
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    invoice_date = models.DateTimeField(null=True, blank=True)
    last_synced = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-invoice_date']

    @property
    def is_return(self):
        return self.doc_code == '30'


class PurchaseHistoryLine(models.Model):
    purchase = models.ForeignKey(PurchaseHistory, on_delete=models.CASCADE, related_name='lines')
    item = models.ForeignKey('catalog.Item', on_delete=models.SET_NULL, null=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=3)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)
