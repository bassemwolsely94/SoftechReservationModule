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
        ('self_service', 'تسجيل ذاتي (QR/رابط)'),
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

    @property
    def potential_value(self):
        """Total potential revenue at stake = Σ line_value over priced items.
        Free-text / unpriced lines contribute 0."""
        return float(sum(
            (i.quantity * i.unit_price_snapshot)
            for i in self.items.all()
            if i.unit_price_snapshot is not None
        ))

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

class DemandItemQuerySet(models.QuerySet):
    """Single source of truth for the Phase 1 recovery eligibility rule (§5.2).

    A line is recovery-eligible iff it has a real catalog item, is not
    disqualified, the customer has not opted out, the parent record is within
    the 12-month recovery window, and its status is one we can still win back.
    Detection, the recovery queue, and the monthly reminder ALL filter on this.
    """
    def recovery_eligible(self):
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=DemandItem.RECOVERY_WINDOW_DAYS)
        return self.filter(
            item__isnull=False,
            disqualified=False,
            contact_opt_out=False,
            demand__created_at__gte=cutoff,
        ).filter(
            models.Q(item_status__in=['pending', 'sourcing', 'available_again']) |
            models.Q(item_status='lost', demand__lost_reason='no_stock')
        )

    def awaiting_winback(self):
        """Recovery-eligible lines already flagged back-in-stock (the work queue)."""
        return self.recovery_eligible().filter(item_status='available_again')


class DemandItem(models.Model):

    DEMAND_TYPE_CHOICES = [
        ('out_of_stock', 'نفد من المخزون'),
        ('low_stock',    'مخزون منخفض'),
        ('new_item',     'صنف جديد / غير مُخزَّن'),
        ('price_check',  'استفسار سعر'),
    ]

    ITEM_STATUS_CHOICES = [
        ('pending',         'قيد الانتظار'),
        ('sourcing',        'جارٍ التوفير'),
        ('available_again', 'عاد للمخزون 🔔'),   # Phase 1: restock detected, awaiting win-back
        ('recovered',       'تم الاسترداد 💰'),   # Phase 1: customer came back and bought
        ('fulfilled',       'تم التسليم ✅'),
        ('lost',            'ضاعت المبيعة ❌'),
        ('cancelled',       'ملغي'),
    ]

    # ── Recovery loop (Phase 1) ───────────────────────────────────────────────
    RECOVERY_WINDOW_DAYS = 365   # ignore demand older than this when an item restocks

    DISQUALIFY_REASONS = [
        ('not_in_egypt',    'غير متوفر في مصر'),
        ('discontinued',    'متوقف عن الإنتاج'),
        ('not_allowed',     'غير مسموح ببيعه في الصيدلية'),
        ('unknown_item',    'صنف غير معروف'),
        ('never_available', 'لن يتوفر مطلقاً'),
        ('other',           'أخرى'),
    ]

    OPT_OUT_REASONS = [
        ('not_needed',       'لم يعد بحاجته'),
        ('moved',            'انتقل / غادر'),
        ('for_other_person', 'كان يطلبه لشخص آخر'),
        ('other',            'أخرى'),
    ]

    objects = DemandItemQuerySet.as_manager()

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
        max_length=20,
        choices=ITEM_STATUS_CHOICES,
        default='pending',
        verbose_name='حالة الصنف',
        db_index=True,
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

    # ── Therapeutic substitution at capture (Phase 3) ─────────────────────────
    # When this line is an in-stock same-molecule alternative offered in place of
    # an out-of-stock item, this points at the original item. Makes substitution a
    # queryable signal (which molecules customers accept swaps for).
    substitute_for_item = models.ForeignKey(
        'catalog.Item', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='offered_as_substitute_in',
        verbose_name='بديل علمي لـ',
    )

    # ── Price snapshot (Phase 0) ──────────────────────────────────────────────
    # Frozen at capture time because ERP prices drift. Used to value lost demand
    # and to prioritise recovery. Null for free-text items (price unknowable).
    unit_price_snapshot = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='سعر الوحدة المُجمَّد',
        help_text='نسخة من سعر العبوة (item.pack_price) وقت التسجيل — للتقييم والاسترداد',
    )
    cost_price_snapshot = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='سعر التكلفة المُجمَّد',
        help_text='نسخة من سعر التكلفة (item.cost_price) وقت التسجيل — لحساب الهامش',
    )
    price_snapshot_at = models.DateTimeField(null=True, blank=True)
    # True when the price was typed by hand (uncoded item) rather than synced from
    # ERP. Surfaced in the UI so manual estimates are never mistaken for ERP data.
    price_is_manual = models.BooleanField(
        default=False, verbose_name='سعر مُدخَل يدوياً',
        help_text='القيمة تقديرية أُدخلت يدوياً ولم تُجلب من ERP',
    )

    # ── Recovery tracking (Phase 1) ───────────────────────────────────────────
    back_in_stock_at     = models.DateTimeField(null=True, blank=True, db_index=True,
        verbose_name='تاريخ عودته للمخزون')
    notified_customer_at = models.DateTimeField(null=True, blank=True,
        verbose_name='تاريخ آخر تواصل مع العميل')
    recovered_at         = models.DateTimeField(null=True, blank=True,
        verbose_name='تاريخ الاسترداد')
    recovered_revenue    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name='الإيراد المُسترَد (ج.م)')
    # Forward bridge target (Phase 1b): set when a recovery becomes a Reservation.
    reservation          = models.ForeignKey(
        'reservations.Reservation', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='source_demand_items',
        verbose_name='الحجز الناتج')

    # ── Item-level contact opt-out (Phase 1, §5.10) ───────────────────────────
    contact_opt_out        = models.BooleanField(default=False, db_index=True,
        verbose_name='رفض التواصل بخصوص هذا الصنف')
    contact_opt_out_reason = models.CharField(max_length=20, blank=True, choices=OPT_OUT_REASONS)
    contact_opt_out_at     = models.DateTimeField(null=True, blank=True)

    # ── Disqualification gate (Phase 1, §5.8 — approval-gated) ────────────────
    disqualified        = models.BooleanField(default=False, db_index=True,
        verbose_name='مُستبعَد من الاسترداد')
    disqualified_reason = models.CharField(max_length=20, blank=True, choices=DISQUALIFY_REASONS)
    disqualified_by     = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='disqualified_demand_items')
    disqualified_at     = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'صنف في الطلب'
        verbose_name_plural = 'أصناف الطلب'

    def __str__(self):
        name = self.item.name if self.item else self.item_name_free
        return f'{name} × {self.quantity}'

    def save(self, *args, **kwargs):
        # Freeze the item's price once, at first save, when an item is linked.
        # Never overwrites an existing snapshot; free-text items stay null.
        if self.unit_price_snapshot is None and self.item_id:
            item = self.item
            if item is not None:
                self.unit_price_snapshot = item.pack_price
                self.cost_price_snapshot = item.cost_price
                self.price_snapshot_at    = timezone.now()
        super().save(*args, **kwargs)

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

    @property
    def line_value(self):
        """Potential revenue of this line = quantity × frozen unit price.
        None when no price snapshot (free-text item)."""
        if self.unit_price_snapshot is None:
            return None
        return float(self.quantity * self.unit_price_snapshot)

    @property
    def line_margin(self):
        """Potential margin of this line = quantity × (unit price − cost).
        None when either snapshot is missing."""
        if self.unit_price_snapshot is None or self.cost_price_snapshot is None:
            return None
        return float(self.quantity * (self.unit_price_snapshot - self.cost_price_snapshot))

    # ── Recovery loop (Phase 1) ───────────────────────────────────────────────

    @property
    def is_recovery_eligible(self):
        """Per-instance mirror of DemandItemQuerySet.recovery_eligible (§5.2)."""
        from datetime import timedelta
        if not self.item_id or self.disqualified or self.contact_opt_out:
            return False
        if self.demand.created_at < timezone.now() - timedelta(days=self.RECOVERY_WINDOW_DAYS):
            return False
        if self.item_status in ('pending', 'sourcing', 'available_again'):
            return True
        return self.item_status == 'lost' and self.demand.lost_reason == 'no_stock'

    @property
    def days_waiting(self):
        """Whole days the customer has been waiting since the demand was created."""
        return (timezone.now() - self.demand.created_at).days

    @property
    def wa_link(self):
        """Operator-clickable wa.me deep link prefilled with a back-in-stock message.
        Human-in-the-loop: the operator decides to send. None if no phone."""
        from urllib.parse import quote
        phone = (self.demand.phone or '').strip()
        if not phone:
            return None
        # Normalise Egyptian local number (01XXXXXXXXX) to international (201XXXXXXXXX)
        digits = ''.join(c for c in phone if c.isdigit())
        if digits.startswith('0'):
            digits = '2' + digits
        elif not digits.startswith('20'):
            digits = '20' + digits
        branch = self.demand.branch
        branch_name = (branch.name_ar or branch.name) if branch else ''
        name = self.demand.customer_name or ''
        msg = (
            f'السلام عليكم {name}،\n'
            f'صنف "{self.item_display_name}" الذي طلبته أصبح متوفراً الآن'
            f'{" في فرع " + branch_name if branch_name else ""}.\n'
            f'هل ترغب في حجزه؟'
        )
        return f'https://wa.me/{digits}?text={quote(msg)}'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Follow-up Task
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class DemandFollowUp(models.Model):
    """Per-DemandRecord follow-up task (the demand workflow's own task list).

    DISTINCT from ``followups.FollowUpTask`` (DUP-004) — do not conflate:
      • ``demand.DemandFollowUp`` (this model) — a channel-typed micro-task
        (call / whatsapp / sms / visit / stock_check) bound to ONE DemandRecord
        (required FK, CASCADE). Auto-created with every demand, surfaced in the
        demand detail "المتابعات" tab. ``due_date`` carries a time.
      • ``followups.FollowUpTask`` — the customer-centric chronic-refill engine
        (priority scoring, multi-assignee, ERP sale anchors, pinning). It can
        *spawn* a DemandRecord via ``followups.services.create_demand_from_task``
        (one-directional bridge); it is NOT this per-record task list.

    Table name is pinned to the original ``demand_followuptask`` so the rename
    from ``FollowUpTask`` is purely a code-level de-collision (no data move).
    """

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
        db_table = 'demand_followuptask'   # preserve table across the FollowUpTask→DemandFollowUp rename
        ordering = ['due_date']
        verbose_name = 'متابعة طلب'
        verbose_name_plural = 'متابعات الطلبات'

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
    # Phase 2 — confirmed lost EGP (Σ quantity × frozen unit price of lost lines)
    lost_value_30d      = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    # Demand-driven reorder: open + lost demand units → suggested purchase qty
    suggested_order_qty = models.DecimalField(max_digits=12, decimal_places=2, default=0)

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
