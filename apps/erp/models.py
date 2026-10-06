"""
apps/erp/models.py

ERP Transaction Layer — READ-ONLY mirror of Sybase stktransm + stktrans.
Also stores localcustomers (PIC/delivery customers) separately from personsdata.

ABSOLUTE RULE: These tables are NEVER written to from Sybase.
Django only READS Sybase and WRITES to PostgreSQL.

stktransm (header) — one row per transaction document
stktrans  (lines)  — many rows per transaction, joined via transaction_id

Doccodes we sync:
    25  → Transfer receipt      (branch receives stock from another branch)
    30  → Customer return       (customer returns to pharmacy)
    115 → Sale to customer      (MOST IMPORTANT — tracks fulfillment)
    125 → Transfer issue        (branch sends stock to another branch)
"""
from django.db import models


# ── Local Customer (localcustomers table) ─────────────────────────────────────

class LocalCustomer(models.Model):
    """
    Mirror of Sybase localcustomers table.

    These are PIC (delivery/home) customers — separate from personsdata.
    phcode format: 140HD515
        140 = branch code
        HD  = type (HD=Home Delivery, etc.)
        515 = customer sequence

    IMPORTANT: This is NOT the same as customers.Customer.
    customers.Customer = personsdata (regular pharmacy customers)
    LocalCustomer      = localcustomers (delivery/PIC customers)

    They can be linked: Customer.softech_id may match LocalCustomer.phcode
    in some cases, but they are different ERP tables.
    """

    # ── PIC identity (PRIMARY KEY in ERP) ────────────────────────────────────
    phcode = models.CharField(
        max_length=30, unique=True, db_index=True,
        verbose_name='كود PIC',
        help_text='مثال: 140HD515 — كود العميل في نظام التوصيل',
    )

    # ── Name & contact ────────────────────────────────────────────────────────
    name = models.CharField(
        max_length=255, blank=True, db_index=True,
        verbose_name='اسم العميل',
    )
    phone = models.CharField(
        max_length=50, blank=True, db_index=True,
        verbose_name='رقم الهاتف',
    )
    phone_alt = models.CharField(
        max_length=50, blank=True,
        verbose_name='هاتف بديل',
    )

    # ── Branch ────────────────────────────────────────────────────────────────
    erp_branch_code = models.CharField(
        max_length=10, blank=True,
        verbose_name='كود الفرع في ERP',
    )
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='local_customers',
        verbose_name='الفرع',
    )

    # ── Address ───────────────────────────────────────────────────────────────
    address = models.TextField(blank=True, verbose_name='العنوان')
    area = models.CharField(max_length=100, blank=True, verbose_name='المنطقة')

    # ── Classification ────────────────────────────────────────────────────────
    customer_type = models.CharField(
        max_length=10, blank=True,
        verbose_name='نوع العميل',
        help_text='HD=Home Delivery, etc.',
    )
    is_active = models.BooleanField(default=True, verbose_name='نشط')

    # ── Link to regular Customer if exists ────────────────────────────────────
    linked_customer = models.OneToOneField(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='local_customer_profile',
        verbose_name='عميل مرتبط',
    )

    # ── Sync ──────────────────────────────────────────────────────────────────
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'عميل توصيل (PIC)'
        verbose_name_plural = 'عملاء التوصيل (PIC)'
        indexes = [
            models.Index(fields=['phone']),
            models.Index(fields=['erp_branch_code']),
        ]

    def __str__(self):
        return f'{self.phcode} | {self.name} | {self.phone}'

    @property
    def phcode_parts(self):
        """Parse phcode: 140HD515 → {branch: '140', type: 'HD', seq: '515'}"""
        code = self.phcode
        # Extract leading digits (branch)
        i = 0
        while i < len(code) and code[i].isdigit():
            i += 1
        branch = code[:i]
        # Extract letters (type)
        j = i
        while j < len(code) and code[j].isalpha():
            j += 1
        ctype = code[i:j]
        seq = code[j:]
        return {'branch': branch, 'type': ctype, 'seq': seq}

    @property
    def whatsapp_url(self):
        """Generate WhatsApp link for this customer's phone."""
        if not self.phone:
            return None
        clean = self.phone.strip().replace(' ', '').replace('-', '')
        if clean.startswith('0'):
            clean = '20' + clean[1:]  # Egypt country code
        return f'https://wa.me/{clean}'


# ── ERP Transaction Header ────────────────────────────────────────────────────

class ERPTransaction(models.Model):
    """
    Mirror of stktransm — one row per ERP document.

    transaction_id  : globally unique across all branches/doccodes
    doccode         : '25' | '30' | '115' | '125'
    phcode          : customer PIC code (localcustomers) — NULL for transfers
    branch          : FK to our Branch model (via softech_branch_id)
    reference_number: stktransm.docnumber (document sequence number)
    """

    DOCCODE_CHOICES = [
        ('25',  'استلام تحويل'),           # Transfer receipt
        ('30',  'مرتجع عميل'),            # Customer return
        ('115', 'بيع لعميل'),             # Sale to customer
        ('125', 'إصدار تحويل'),           # Transfer issue
    ]

    # ── Identity ──────────────────────────────────────────────────────────────
    transaction_id = models.CharField(
        max_length=100, unique=True, db_index=True,
        verbose_name='معرف المعاملة',
        help_text='Unique key: branchcode-doccode-docnumber-docdate',
    )
    doccode = models.CharField(
        max_length=5, choices=DOCCODE_CHOICES, db_index=True,
        verbose_name='كود المستند',
    )
    reference_number = models.CharField(
        max_length=50, blank=True,
        verbose_name='رقم المستند',
        help_text='stktransm.docnumber',
    )

    # ── Branch ────────────────────────────────────────────────────────────────
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='erp_transactions',
        verbose_name='الفرع',
    )
    softech_branch_code = models.CharField(
        max_length=10, blank=True,
        verbose_name='كود الفرع في ERP',
        help_text='Raw branchcode from Sybase — kept for audit',
    )

    # ── Customer (sales only, doccode=115/30) ─────────────────────────────────
    phcode = models.CharField(
        max_length=30, blank=True, db_index=True,
        verbose_name='كود العميل (PIC)',
        help_text='localcustomers.phcode — NULL for transfers',
    )
    # Resolved FK — may be NULL if phcode not yet in localcustomers sync
    local_customer = models.ForeignKey(
        'erp.LocalCustomer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='transactions',
        verbose_name='عميل التوصيل',
    )
    # Legacy link to personsdata customers (doccode 115 from stktrans)
    personsdata_customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='erp_transactions',
        verbose_name='عميل النظام',
    )

    # ── Date ─────────────────────────────────────────────────────────────────
    transaction_date = models.DateTimeField(
        db_index=True,
        verbose_name='تاريخ المعاملة',
    )

    # ── Financials ────────────────────────────────────────────────────────────
    total_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name='إجمالي المبلغ',
    )

    # ── Sync metadata ─────────────────────────────────────────────────────────
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-transaction_date']
        verbose_name = 'معاملة ERP'
        verbose_name_plural = 'معاملات ERP'
        indexes = [
            models.Index(fields=['doccode', 'transaction_date']),
            models.Index(fields=['doccode', 'branch']),
            models.Index(fields=['phcode', 'transaction_date']),
            models.Index(fields=['transaction_date']),
        ]

    def __str__(self):
        return f'[{self.doccode}] {self.transaction_id} | {self.softech_branch_code} | {self.transaction_date:%Y-%m-%d}'

    @property
    def is_sale(self):
        return self.doccode == '115'

    @property
    def is_return(self):
        return self.doccode == '30'

    @property
    def is_transfer_receipt(self):
        return self.doccode == '25'

    @property
    def is_transfer_issue(self):
        return self.doccode == '125'

    @property
    def doccode_label(self):
        return dict(self.DOCCODE_CHOICES).get(self.doccode, self.doccode)



# ── ERP Transaction Line ──────────────────────────────────────────────────────

class ERPTransactionLine(models.Model):
    """
    Mirror of stktrans — one row per item per transaction.

    phcode lives ONLY on the header (stktransm), never here.
    To find who bought what: join header → lines via transaction FK.
    """

    transaction = models.ForeignKey(
        ERPTransaction,
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name='المعاملة',
    )

    # ── Item (resolved + raw) ─────────────────────────────────────────────────
    item = models.ForeignKey(
        'catalog.Item',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='erp_lines',
        verbose_name='الصنف',
    )
    item_code = models.CharField(
        max_length=20, db_index=True,
        verbose_name='كود الصنف',
        help_text='Raw itemcode from stktrans — always stored for audit',
    )
    item_name = models.CharField(
        max_length=255, blank=True,
        verbose_name='اسم الصنف',
    )

    # ── Quantity & price ──────────────────────────────────────────────────────
    quantity = models.DecimalField(
        max_digits=12, decimal_places=3, default=0,
        verbose_name='الكمية',
    )
    unit_price = models.DecimalField(
        max_digits=10, decimal_places=3, default=0,
        verbose_name='سعر الوحدة',
    )
    line_total = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        verbose_name='إجمالي السطر',
    )

    # ── Store ─────────────────────────────────────────────────────────────────
    store_code = models.CharField(
        max_length=5, blank=True,
        verbose_name='كود المخزن',
    )

    class Meta:
        verbose_name = 'سطر معاملة ERP'
        verbose_name_plural = 'أسطر معاملات ERP'
        indexes = [
            models.Index(fields=['item_code']),
            models.Index(fields=['transaction', 'item_code']),
        ]

    def __str__(self):
        return f'{self.transaction_id} | {self.item_code} × {self.quantity}'

