"""
apps/demand/models.py

Customer Demand & Lost Sales Engine
────────────────────────────────────
This engine sits ABOVE the ERP and reservation layer.
It captures ALL unmet demand — whether stock exists or not.

Key design decisions:
  • DemandRecord is the central entity (replaces "Reservation" conceptually)
  • Customer identified by phone (primary) → auto-linked to ERP phcode
  • Items track shortage flags and demand classification
  • SLA tracking built into every stage
  • Full chatter (calls, notes, system logs)
  • Lost sales tracked with reasons

NO ERP mutations. NO stock changes. Read-only ERP integration.
"""
from django.db import models
from django.utils import timezone
from datetime import timedelta


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Demand Record — core entity
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DemandRecord(models.Model):

    STATUS_CHOICES = [
        ('new',           'جديد — لم يُعالَج'),
        ('assigned',      'مُعيَّن — جارٍ المتابعة'),
        ('follow_up',     'متابعة — في الانتظار'),
        ('stock_eta',     'في انتظار المخزون'),
        ('transfer_suggested', 'تم اقتراح تحويل'),
        ('purchasing_flagged', 'مُرسَل للمشتريات'),
        ('fulfilled',     'تم التسليم ✅'),
        ('lost',          'مبيعة ضائعة ❌'),
        ('cancelled',     'ملغي'),
    ]

    PRIORITY_CHOICES = [
        ('low',      'منخفضة'),
        ('normal',   'عادية'),
        ('high',     'مرتفعة'),
        ('urgent',   'عاجلة 🔴'),
        ('chronic',  'مريض مزمن 💊'),
    ]

    SOURCE_CHOICES = [
        ('walk_in',      'زيارة مباشرة'),
        ('phone',        'اتصال هاتفي'),
        ('whatsapp',     'واتساب'),
        ('delivery',     'توصيل'),
        ('online',       'أونلاين'),
        ('call_center',  'مركز الاتصالات'),
        ('other',        'أخرى'),
    ]

    # ── Identity ──────────────────────────────────────────────────────────────
    demand_number = models.CharField(
        max_length=20, unique=True, blank=True,
        verbose_name='رقم الطلب',
    )

    # ── Customer linkage ──────────────────────────────────────────────────────
    # Phone is MANDATORY — the primary identifier
    phone = models.CharField(
        max_length=50, db_index=True,
        verbose_name='رقم الهاتف',
    )
    customer_name = models.CharField(
        max_length=255,
        verbose_name='اسم العميل',
    )
    # Link to our Customer model (may be null if not yet found)
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='demand_records',
        verbose_name='العميل',
    )
    # ERP phcode — the master customer identifier (e.g. "140HD515")
    phcode = models.CharField(
        max_length=20, blank=True, db_index=True,
        verbose_name='كود PIC (ERP)',
        help_text='مثال: 140HD515 — يُجلب تلقائياً من ERP',
    )
    # ERP branch code embedded in phcode (e.g. "140")
    erp_branch_code = models.CharField(max_length=10, blank=True)

    # ── Branch & assignment ───────────────────────────────────────────────────
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.PROTECT,
        related_name='demand_records',
        verbose_name='الفرع',
    )
    assigned_to = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_demands',
        verbose_name='مُعيَّن لـ',
    )

    # ── Status & classification ───────────────────────────────────────────────
    status   = models.CharField(max_length=25, choices=STATUS_CHOICES, default='new', db_index=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    source   = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='walk_in')

    # ── Follow-up scheduling ──────────────────────────────────────────────────
    follow_up_date = models.DateField(null=True, blank=True, db_index=True)
    expected_stock_date = models.DateField(null=True, blank=True)

    # ── Resolution ────────────────────────────────────────────────────────────
    lost_reason = models.CharField(
        max_length=30, blank=True,
        choices=[
            ('no_stock',        'لا يوجد مخزون'),
            ('delayed',         'تأخر الوصول'),
            ('discontinued',    'متوقف عن الإنتاج'),
            ('no_response',     'لا استجابة من العميل'),
            ('price',           'السعر مرتفع'),
            ('competitor',      'ذهب لمنافس'),
            ('other',           'أخرى'),
        ],
        verbose_name='سبب الفقد',
    )

    # ── ERP verification of fulfillment ──────────────────────────────────────
    # When ERP confirms sale, we store the invoice reference
    erp_invoice_ref = models.CharField(max_length=100, blank=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)

    # ── General notes ─────────────────────────────────────────────────────────
    notes = models.TextField(blank=True)

    # ── SLA tracking ─────────────────────────────────────────────────────────
    # Populated automatically on status transitions
    assigned_at  = models.DateTimeField(null=True, blank=True)
    contacted_at = models.DateTimeField(null=True, blank=True)

    # ── People ────────────────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_demands',
        verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'طلب طلب'
        verbose_name_plural = 'طلبات الطلب'
        indexes = [
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['follow_up_date']),
            models.Index(fields=['phone']),
            models.Index(fields=['phcode']),
            models.Index(fields=['status', 'priority']),
        ]

    def __str__(self):
        return f'{self.demand_number} | {self.customer_name} | {self.get_status_display()}'

    def save(self, *args, **kwargs):
        if not self.demand_number:
            super().save(*args, **kwargs)
            self.demand_number = f'DEM-{self.pk:06d}'
            kwargs['force_insert'] = False
        super().save(*args, **kwargs)

    # ── SLA properties ────────────────────────────────────────────────────────

    SLA_MINUTES = {
        'new':      10,   # Must be assigned within 10 min
        'assigned': 20,   # Must be contacted within 20 min
    }

    @property
    def sla_deadline(self):
        """Returns the SLA deadline datetime for current status, or None."""
        minutes = self.SLA_MINUTES.get(self.status)
        if not minutes:
            return None
        ref = self.assigned_at if self.status == 'assigned' else self.created_at
        if ref:
            return ref + timedelta(minutes=minutes)
        return None

    @property
    def sla_breached(self):
        dl = self.sla_deadline
        if dl is None:
            return False
        return timezone.now() > dl

    @property
    def sla_minutes_remaining(self):
        dl = self.sla_deadline
        if dl is None:
            return None
        remaining = (dl - timezone.now()).total_seconds() / 60
        return round(remaining, 1)

    @property
    def is_active(self):
        return self.status not in ('fulfilled', 'lost', 'cancelled')

    @property
    def status_color(self):
        return {
            'new':                 'orange',
            'assigned':            'blue',
            'follow_up':           'indigo',
            'stock_eta':           'yellow',
            'transfer_suggested':  'purple',
            'purchasing_flagged':  'red',
            'fulfilled':           'green',
            'lost':                'red',
            'cancelled':           'gray',
        }.get(self.status, 'gray')

    @property
    def total_items(self):
        return self.items.count()

    def try_link_customer(self):
        """
        Try to find a Customer record matching this phone or phcode.
        Called after ERP sync or on save.
        """
        from apps.customers.models import Customer
        if self.customer_id:
            return self.customer

        qs = Customer.objects.none()
        if self.phcode:
            qs = Customer.objects.filter(softech_id__icontains=self.phcode)
        if not qs.exists() and self.phone:
            qs = Customer.objects.filter(
                models.Q(phone=self.phone) | models.Q(phone_alt=self.phone)
            )
        if qs.exists():
            self.customer = qs.first()
            self.save(update_fields=['customer'])
        return self.customer


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Demand Item — one item per line on a demand record
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DemandItem(models.Model):

    DEMAND_TYPE_CHOICES = [
        ('out_of_stock', 'نفد من المخزون'),
        ('low_stock',    'مخزون منخفض'),
        ('new_item',     'صنف جديد / غير مُخزَّن'),
        ('price_check',  'استفسار سعر'),
    ]

    ITEM_STATUS_CHOICES = [
        ('pending',     'قيد الانتظار'),
        ('sourcing',    'جارٍ التوفير'),
        ('fulfilled',   'تم التسليم ✅'),
        ('lost',        'ضاعت المبيعة ❌'),
        ('cancelled',   'ملغي'),
    ]

    demand = models.ForeignKey(
        DemandRecord,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='طلب الطلب',
    )
    item = models.ForeignKey(
        'catalog.Item',
        on_delete=models.PROTECT,
        related_name='demand_items',
        verbose_name='الصنف',
        null=True, blank=True,
    )
    # Free-text fallback if item not in catalog
    item_name_free = models.CharField(
        max_length=255, blank=True,
        verbose_name='اسم الصنف (حر)',
        help_text='يُستخدم إذا لم يكن الصنف في الكتالوج',
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, default=1,
        verbose_name='الكمية المطلوبة',
    )
    demand_type = models.CharField(
        max_length=15,
        choices=DEMAND_TYPE_CHOICES,
        default='out_of_stock',
        verbose_name='نوع الطلب',
    )
    item_status = models.CharField(
        max_length=15,
        choices=ITEM_STATUS_CHOICES,
        default='pending',
        verbose_name='حالة الصنف',
    )

    # ── Shortage intelligence ─────────────────────────────────────────────────
    is_long_shortage = models.BooleanField(
        default=False,
        verbose_name='نقص طويل الأمد',
        help_text='إذا كان الصنف غير متاح منذ فترة طويلة',
    )
    is_discontinued = models.BooleanField(
        default=False,
        verbose_name='متوقف عن الإنتاج',
        help_text='إذا كان الصنف متوقفاً من المصنع',
    )
    shortage_note = models.CharField(max_length=255, blank=True)

    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = 'صنف في الطلب'
        verbose_name_plural = 'أصناف الطلب'

    def __str__(self):
        name = self.item.name if self.item else self.item_name_free
        return f'{name} × {self.quantity}'

    @property
    def item_display_name(self):
        if self.item:
            return self.item.name
        return self.item_name_free or 'صنف غير محدد'

    @property
    def stock_at_branch(self):
        """Current stock at the demand record's branch."""
        if not self.item or not self.demand.branch_id:
            return None
        from apps.catalog.models import ItemStock
        stock = ItemStock.objects.filter(
            item=self.item,
            branch=self.demand.branch,
        ).first()
        return float(stock.quantity_on_hand) if stock else 0.0

    @property
    def stock_network_total(self):
        """Total stock across ALL branches."""
        if not self.item:
            return None
        from apps.catalog.models import ItemStock
        from django.db.models import Sum
        result = ItemStock.objects.filter(item=self.item).aggregate(
            total=Sum('quantity_on_hand')
        )
        return float(result['total'] or 0)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Follow-up Task
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class FollowUpTask(models.Model):

    STATUS_CHOICES = [
        ('pending',    'مجدولة'),
        ('done',       'تم التنفيذ'),
        ('missed',     'فائت'),
        ('cancelled',  'ملغي'),
    ]

    TYPE_CHOICES = [
        ('call',        'اتصال هاتفي'),
        ('whatsapp',    'واتساب'),
        ('sms',         'رسالة نصية'),
        ('visit',       'زيارة'),
        ('stock_check', 'فحص المخزون'),
        ('other',       'أخرى'),
    ]

    demand = models.ForeignKey(
        DemandRecord,
        on_delete=models.CASCADE,
        related_name='followups',
        verbose_name='الطلب',
    )
    task_type = models.CharField(max_length=15, choices=TYPE_CHOICES, default='call')
    due_date   = models.DateTimeField(db_index=True)
    status     = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    assigned_to = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='followup_tasks',
    )
    note        = models.TextField(blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='completed_followups',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date']
        verbose_name = 'مهمة متابعة'
        verbose_name_plural = 'مهام المتابعة'

    def __str__(self):
        return f'{self.get_task_type_display()} — {self.demand.demand_number} — {self.due_date:%Y-%m-%d %H:%M}'

    @property
    def is_overdue(self):
        return self.status == 'pending' and timezone.now() > self.due_date

    @property
    def overdue_hours(self):
        if not self.is_overdue:
            return 0
        return round((timezone.now() - self.due_date).total_seconds() / 3600, 1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Demand Log — chatter (calls, notes, system)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DemandLog(models.Model):

    LOG_TYPES = [
        ('note',     '📝 ملاحظة'),
        ('call',     '📞 مكالمة'),
        ('whatsapp', '💬 واتساب'),
        ('sms',      '📱 رسالة'),
        ('system',   '⚙️ نظام'),
        ('status',   '🔄 تغيير حالة'),
    ]

    CALL_OUTCOMES = [
        ('answered',       'رد'),
        ('no_answer',      'لم يرد'),
        ('busy',           'مشغول'),
        ('wrong_number',   'رقم خاطئ'),
        ('callback',       'طلب الاتصال لاحقاً'),
    ]

    demand = models.ForeignKey(
        DemandRecord,
        on_delete=models.CASCADE,
        related_name='logs',
        verbose_name='الطلب',
    )
    log_type     = models.CharField(max_length=10, choices=LOG_TYPES, default='note')
    message      = models.TextField(verbose_name='الرسالة')
    call_outcome = models.CharField(
        max_length=20, choices=CALL_OUTCOMES, blank=True,
        verbose_name='نتيجة المكالمة',
    )
    call_duration_seconds = models.PositiveIntegerField(
        null=True, blank=True,
        verbose_name='مدة المكالمة (ثانية)',
    )
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='demand_logs',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'سجل'
        verbose_name_plural = 'سجلات الطلب'

    def __str__(self):
        return f'[{self.get_log_type_display()}] {self.demand_id}: {self.message[:60]}'

    @classmethod
    def system(cls, demand, message):
        """Create a system log entry."""
        return cls.objects.create(
            demand=demand,
            log_type='system',
            message=message,
            created_by=None,
        )

    @classmethod
    def status_change(cls, demand, old_status, new_status, by=None, note=''):
        """Log a status change event."""
        status_labels = dict(DemandRecord.STATUS_CHOICES)
        msg = (
            f'تغيير الحالة: {status_labels.get(old_status, old_status)}'
            f' ← {status_labels.get(new_status, new_status)}'
        )
        if note:
            msg += f' — {note}'
        return cls.objects.create(
            demand=demand,
            log_type='status',
            message=msg,
            created_by=by,
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Item Demand Intelligence — aggregate view (updated via signals)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ItemDemandStat(models.Model):
    """
    Aggregated demand intelligence per item per branch.
    Updated via management command (run daily).
    Drives purchasing and transfer decisions.
    """
    item   = models.ForeignKey('catalog.Item', on_delete=models.CASCADE, related_name='demand_stats')
    branch = models.ForeignKey('branches.Branch', on_delete=models.CASCADE, null=True, blank=True)

    # Last 30 days
    demand_count_30d    = models.PositiveIntegerField(default=0)
    lost_count_30d      = models.PositiveIntegerField(default=0)
    fulfilled_count_30d = models.PositiveIntegerField(default=0)
    lost_qty_30d        = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Shortage flags (managed manually or via command)
    is_long_shortage  = models.BooleanField(default=False, db_index=True)
    is_discontinued   = models.BooleanField(default=False)
    shortage_start    = models.DateField(null=True, blank=True)

    # Purchasing suggestion
    suggest_order     = models.BooleanField(default=False)
    suggest_transfer  = models.BooleanField(default=False)

    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('item', 'branch')
        ordering = ['-demand_count_30d']
        verbose_name = 'إحصاء طلب الصنف'

    def __str__(self):
        branch_name = self.branch.name_ar if self.branch else 'كل الفروع'
        return f'{self.item.name} @ {branch_name}: {self.demand_count_30d} طلب'

    @property
    def fulfillment_rate(self):
        total = self.demand_count_30d
        if not total:
            return 0
        return round(self.fulfilled_count_30d / total * 100, 1)

    @property
    def lost_rate(self):
        total = self.demand_count_30d
        if not total:
            return 0
        return round(self.lost_count_30d / total * 100, 1)
