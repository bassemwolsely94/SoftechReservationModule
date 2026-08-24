"""
apps/pos_orders/models.py

PostgreSQL mirror of the SOFTECH Indirect-POS *pending* sales order that our
extended system creates and sends to a branch cashier. PG is the system of record
for OUR metadata (channel, referral doctor, prescription, originating call, audit);
SOFTECH is authoritative for the order itself once pushed.

Behaviour fully reverse-engineered in:
    docs/architecture/SOFTECH_INDIRECT_POS_ORDER_WRITEBACK.md   (§6a–§6k)
    docs/architecture/14_PHASE2_INDIRECT_POS_WRITER_DESIGN.md

Write surface (PENDING side only): stktransm5 (header) + stktrans5 (lines) +
branchesales5 (tenders). We NEVER write final stktransm/stktrans/branchesales,
stkbal, picpoints, accounting or e-invoice — the cashier's settlement does that.
"""
from django.db import models
from django.conf import settings


# ── SOFTECH mapping tables ──────────────────────────────────────────────────
# channel → ptclassifcode (all customer sales use ptcode='10'; see spec §6c)
CHANNEL_TO_PTCLASSIF = {
    'cash':       '91',   # عميل نقدى
    'delivery':   '90',   # عميل Delivery
    'contract':   '10',   # تعاقدات / آجل
    'insurance':  '15',   # تأمين صحي
    'employee':   '11',   # موظفيين
    'vip':        '99',   # Vip
    'permanent':  '30',   # عميل دائم
    'compensation': '17', # تعويضات الشركات (corporate compensation — credit, claim + cc, 0 points)
    'donation':   '16',   # تبرعات (donations — credit, claim + cc, 0 points)
    'card_receipt': '12', # إيصال إلكترونى بالبطاقة الشخصية (card tender, claim + cc, 0 points)
}
PTCODE_CUSTOMER = '10'    # ptcode for all customer sales

# Claim channels — every NAMED-account sale (all except anonymous cash/delivery) carries a companiesitems
# (patient/claim/emp-data) record + a branchesalescc (credit/cost-center) record. Verified native: ptclassif
# 10/15/17/16/12 AND employee(11)/permanent(30) all have claim + cc. Cash(91)/delivery(90) do not.
CLAIM_CHANNELS = {'contract', 'insurance', 'employee', 'permanent',
                  'compensation', 'donation', 'card_receipt'}

# doc_kind → SOFTECH doccode + the lastdocnumbers counter column (spec §6h/§6i)
DOCKIND_TO_DOCCODE = {'sale': '115', 'return': '30'}
DOCKIND_TO_COUNTER = {'sale': 'lastdocnumberout_cust', 'return': 'lastdocnumberin_cust'}

# pay_type → SOFTECH paymenttype (spec §6e)
PAYTYPE_TO_SOFTECH = {'cash': '30', 'credit': '10', 'card': '40'}


class SoftechSalesOrder(models.Model):
    """A pending indirect-POS order (header) destined for a branch cashier."""

    STATUS_DRAFT       = 'draft'
    STATUS_READY       = 'ready'
    STATUS_QUEUED      = 'queued'        # ready, but the branch/SOFTECH was unreachable → retry
    STATUS_PUSHING     = 'pushing'
    STATUS_PUSHED      = 'pushed'
    STATUS_PUSH_FAILED = 'push_failed'
    STATUS_SETTLED     = 'settled'
    STATUS_CANCELLED   = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT,       'مسودة'),
        (STATUS_READY,       'جاهز للإرسال'),
        (STATUS_QUEUED,      'بانتظار الاتصال (طابور)'),
        (STATUS_PUSHING,     'جارٍ الإرسال'),
        (STATUS_PUSHED,      'بانتظار الكاشير'),
        (STATUS_PUSH_FAILED, 'فشل الإرسال'),
        (STATUS_SETTLED,     'تم التحصيل (الكاشير)'),
        (STATUS_CANCELLED,   'ملغى'),
    ]

    CHANNEL_CHOICES = [
        ('cash',      'نقدى'),
        ('delivery',  'توصيل'),
        ('contract',  'تعاقد / آجل'),
        ('insurance', 'تأمين'),
        ('employee',  'موظفين'),
        ('vip',       'VIP'),
        ('permanent', 'عميل دائم'),
        ('compensation', 'تعويضات الشركات'),
        ('donation',  'تبرعات'),
        ('card_receipt', 'إيصال بالبطاقة الشخصية'),
    ]
    DOC_KIND_CHOICES = [('sale', 'بيع'), ('return', 'مرتجع')]

    # ── identity / lifecycle ────────────────────────────────────────────────
    status   = models.CharField(max_length=12, choices=STATUS_CHOICES,
                                default=STATUS_DRAFT, db_index=True, verbose_name='الحالة')
    channel  = models.CharField(max_length=12, choices=CHANNEL_CHOICES,
                                default='cash', db_index=True, verbose_name='قناة البيع')
    doc_kind = models.CharField(max_length=8, choices=DOC_KIND_CHOICES,
                                default='sale', verbose_name='نوع المستند')
    # idempotency marker (stashed in vf2/comments on the SOFTECH row). UNIQUE so a
    # replayed offline create (same token) can't make a duplicate PG order — Postgres
    # treats NULLs as distinct, so legacy rows without a token are unaffected.
    client_token = models.UUIDField(editable=False, null=True, blank=True, unique=True)

    # ── target branch ───────────────────────────────────────────────────────
    branch = models.ForeignKey('branches.Branch', on_delete=models.PROTECT,
                               related_name='pos_orders', verbose_name='الفرع')
    softech_branchcode = models.CharField(max_length=5, verbose_name='كود فرع SOFTECH')
    store_code         = models.CharField(max_length=3, verbose_name='كود المخزن')

    # ── customer ──────────────────────────────────────────────────────────────
    customer   = models.ForeignKey('customers.Customer', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='pos_orders',
                                   verbose_name='العميل')
    softech_pic      = models.CharField(max_length=18, blank=True, verbose_name='PIC')
    customer_name    = models.CharField(max_length=255, blank=True, verbose_name='اسم العميل')
    cust_branch_code = models.CharField(max_length=8, blank=True, verbose_name='كود حساب العميل (personcode)')

    # ── SOFTECH refs (writer / reconciler fill these) ──────────────────────────
    softech_docnumber       = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True,
                                                  verbose_name='مسلسل الصرف (pending)')
    softech_docdate         = models.DateField(null=True, blank=True)
    softech_final_docnumber = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True,
                                                  verbose_name='رقم الفاتورة النهائية')
    return_of_invoice       = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True,
                                                  verbose_name='مرتجع للفاتورة')

    # ── money (computed by pricing.py — mirror the header) ────────────────────
    doc_value       = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='القيمة (صافي)')
    doc_value_gross = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الإجمالي قبل الخصم')
    doc_value_cogs  = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='التكلفة')
    doc_value_tax   = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='الضريبة')
    doc_value_pay   = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='المحصّل الآن')
    patient_payment = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='دفعة العميل')

    # ── OUR EXTRAS (richer than / absent in SOFTECH) ──────────────────────────
    referral_doctor_name = models.CharField(max_length=120, blank=True, verbose_name='الطبيب المُحيل')
    referral_doctor_code = models.CharField(max_length=13, blank=True, verbose_name='كود الطبيب (refdoctorcode)')
    prescription_image   = models.ImageField(upload_to='pos_orders/prescriptions/%Y/%m/', null=True, blank=True,
                                             verbose_name='صورة الروشتة')
    source_call      = models.ForeignKey('callcenter.CallLog', null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name='pos_orders',
                                         verbose_name='المكالمة المصدر')
    source_call_item = models.ForeignKey('callcenter.CallItem', null=True, blank=True,
                                         on_delete=models.SET_NULL, related_name='pos_orders')
    notes = models.TextField(blank=True, verbose_name='ملاحظات')

    # ── people ────────────────────────────────────────────────────────────────
    created_by      = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='created_pos_orders')
    seller_usercode  = models.CharField(max_length=5, blank=True, verbose_name='كود البائع')
    cashier_usercode = models.CharField(max_length=5, blank=True, verbose_name='كود الكاشير')

    # When cloned from a real order: native header fields we must reproduce but don't
    # compute (cust_professional, origintaxp, cust_branch_store…). Contract/patient
    # sales need cust_professional set or the RETURN is rejected ("enter patient data").
    source_header_raw = models.JSONField(default=dict, blank=True)
    # Contract/insurance pending companions copied from the source order so the
    # duplicate settles into a RETURNABLE contract sale (companiesitems5 = the
    # patient/insurance claim; branchesalescc5 = cost-center/credit record).
    source_companies_raw = models.JSONField(default=dict, blank=True)
    source_cc_raw         = models.JSONField(default=list, blank=True)

    # ── SOFTECH screen header extras ──────────────────────────────────────────
    doc_date        = models.DateField(null=True, blank=True)                         # تاريخ المستند
    change_discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # خصم فكة (PG-only; trims net)
    payment_method  = models.CharField(max_length=8, blank=True)                       # أسلوب السداد (header)
    alt_price        = models.BooleanField(default=False)   # السعر البديل
    sell_at_cost     = models.BooleanField(default=False)   # بيع بالتكلفة
    print_receipt    = models.BooleanField(default=True)    # طباعة رسيت
    items_reservation = models.BooleanField(default=False)  # حجز أصناف (Reservation)

    # ── immutable execution audit ─────────────────────────────────────────────
    erp_executed_at = models.DateTimeField(null=True, blank=True)
    erp_payload     = models.JSONField(default=dict, blank=True, verbose_name='الحمولة المُرسلة')
    erp_readback    = models.JSONField(default=dict, blank=True, verbose_name='قراءة التحقق')
    erp_error       = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'أمر بيع غير مباشر'
        verbose_name_plural = 'أوامر البيع غير المباشرة'
        indexes = [
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['softech_branchcode', 'softech_docnumber']),
        ]

    def __str__(self):
        return f'POS-{self.pk} [{self.get_status_display()}] {self.softech_pic or self.customer_name}'

    # ── SOFTECH-mapping helpers ───────────────────────────────────────────────
    @property
    def softech_doccode(self):
        return DOCKIND_TO_DOCCODE[self.doc_kind]

    @property
    def softech_ptclassifcode(self):
        return CHANNEL_TO_PTCLASSIF.get(self.channel, '91')

    @property
    def softech_counter_column(self):
        return DOCKIND_TO_COUNTER[self.doc_kind]

    @property
    def is_locked(self):
        """Immutable once it has been pushed/settled (corrections via a return)."""
        return self.status in (self.STATUS_PUSHING, self.STATUS_PUSHED,
                               self.STATUS_SETTLED, self.STATUS_CANCELLED)


class SoftechSalesOrderLine(models.Model):
    """One item line → stktrans5 row."""
    order = models.ForeignKey(SoftechSalesOrder, on_delete=models.CASCADE, related_name='lines')
    item  = models.ForeignKey('catalog.Item', null=True, blank=True, on_delete=models.PROTECT,
                              related_name='pos_order_lines')
    softech_itemcode = models.CharField(max_length=6, verbose_name='كود الصنف')
    item_name        = models.CharField(max_length=120, blank=True)

    qty                 = models.DecimalField(max_digits=12, decimal_places=3, default=1, verbose_name='الكمية')
    item_sale_price     = models.DecimalField(max_digits=12, decimal_places=4, default=0)  # itemsaleprice (per branch)
    item_sale_price_tax = models.DecimalField(max_digits=12, decimal_places=4, default=0)  # itemsaleprice_tax
    sale_tax_pct        = models.DecimalField(max_digits=6, decimal_places=2, default=0)   # itemsalestaxp
    cust_discp          = models.DecimalField(max_digits=6, decimal_places=2, default=0,
                                              verbose_name='خصم %')                          # custdiscp (INPUT)
    # computed (pricing.py)
    trans_price        = models.DecimalField(max_digits=12, decimal_places=4, default=0)   # transprice
    trans_price_total  = models.DecimalField(max_digits=12, decimal_places=2, default=0)   # transprice_total
    item_sale_tax      = models.DecimalField(max_digits=12, decimal_places=4, default=0)   # itemsalestax
    new_cost_price     = models.DecimalField(max_digits=12, decimal_places=4, default=0)   # newcostprice (stkbal at push)
    item_expiry        = models.DateField(null=True, blank=True)                            # itemexpirydate (display)
    return_of_invoice  = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)  # r_docnumber
    # Full native stktrans5 row when this line was cloned from a real order — copied
    # back VERBATIM at write time (incl. itemexpirydate, newqty, bonusqty, dblitemflag,
    # suppliercode…) so the duplicate is byte-faithful and therefore RETURNABLE.
    # datetime values are stored as {'__dt__': 'YYYY-MM-DD HH:MM:SS'}.
    source_raw         = models.JSONField(default=dict, blank=True)
    # SOFTECH screen extras: bonus_qty → stktrans.bonusqty (flows); the rest are
    # display/audit (no stktrans column): barcode, pack price, chosen batch number.
    barcode    = models.CharField(max_length=30, blank=True)                              # الباركود
    bonus_qty  = models.DecimalField(max_digits=12, decimal_places=3, default=0)          # العبوة → bonusqty
    pkg_price  = models.DecimalField(max_digits=12, decimal_places=4, default=0)          # سعر العبوة (display)
    batchno    = models.CharField(max_length=20, blank=True)                              # رقم الباتش (display)
    # per-line out-of-stock reservation (حجز 80): item unavailable at sale time, held so the
    # sale can be saved before it arrives; the real batch is chosen later at dispense (180).
    is_reservation = models.BooleanField(default=False, verbose_name='حجز (غير متوفر)')

    class Meta:
        ordering = ['id']
        verbose_name = 'سطر أمر بيع'

    def __str__(self):
        return f'{self.softech_itemcode} × {self.qty}'


class SoftechSalesOrderPayment(models.Model):
    """One payment tender → branchesales5 row (split payments = multiple rows)."""
    PAY_CHOICES = [('cash', 'نقدى'), ('credit', 'آجل'), ('card', 'بطاقة')]

    order   = models.ForeignKey(SoftechSalesOrder, on_delete=models.CASCADE, related_name='payments')
    pay_type = models.CharField(max_length=8, choices=PAY_CHOICES, default='cash', verbose_name='طريقة السداد')
    amount  = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='المبلغ')
    softech_paymentsno = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)
    card_brand  = models.PositiveSmallIntegerField(null=True, blank=True)   # creditcardtype
    cheque_date = models.DateField(null=True, blank=True)                    # cheqdate
    ref_invoice = models.DecimalField(max_digits=12, decimal_places=0, null=True, blank=True)  # ref_docnumber
    # SOFTECH branchesales5 extras
    currency        = models.CharField(max_length=10, default='L.E')                       # bcurrency label
    exchange_rate   = models.DecimalField(max_digits=12, decimal_places=4, default=1)      # bcrate
    cheque_card_no  = models.CharField(max_length=40, blank=True)                          # cheque/card/points no → comment
    internal_payserial = models.CharField(max_length=20, blank=True)                       # localpayment_sno

    class Meta:
        ordering = ['id']
        verbose_name = 'سداد أمر بيع'

    @property
    def softech_paymenttype(self):
        return PAYTYPE_TO_SOFTECH.get(self.pay_type, '30')

    def __str__(self):
        return f'{self.get_pay_type_display()} {self.amount}'
