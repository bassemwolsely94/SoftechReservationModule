"""
apps/followups/models.py

Phase 5: Follow-up Engine

Two models:
  ChronicMedicationProfile  — tracks chronic medications with refill timing
  FollowUpTask              — scheduled tasks to contact patients for refills

Logic:
  - Get last sale from ERPTransaction (doccode=115, Phase 1 required)
  - Calculate expected refill date = last_sale_date + expected_duration_days
  - Create FollowUpTask due on refill date
  - Auto-close task if a new ERP sale is found after the follow-up was created

HARD RULES:
  ❌ No stock mutations
  ❌ No ERP writes
  ✅ ERP READ ONLY
"""
from django.db import models
from django.utils import timezone
from datetime import timedelta


class ChronicMedicationProfile(models.Model):
    """
    Profile for a chronic medication — defines expected usage duration
    so the system can predict when a patient needs a refill.

    Can be populated manually by pharmacists or inferred from ERP history.
    """

    SOURCE_CHOICES = [
        ('manual',    '✍️ إدخال يدوي'),
        ('erp_infer', '🤖 استنتاج من الـ ERP'),
    ]

    # ── Item link ─────────────────────────────────────────────────────────────
    item = models.OneToOneField(
        'catalog.Item',
        on_delete=models.CASCADE,
        related_name='chronic_profile',
        verbose_name='الصنف',
    )

    # ── Chronic classification ────────────────────────────────────────────────
    is_chronic = models.BooleanField(
        default=True,
        verbose_name='دواء مزمن',
        db_index=True,
    )

    # ── Usage parameters ──────────────────────────────────────────────────────
    avg_daily_usage = models.DecimalField(
        max_digits=8, decimal_places=3,
        default=1,
        verbose_name='متوسط الاستخدام اليومي (وحدة/يوم)',
        help_text='مثال: 1 قرص/يوم = 1.0, نصف قرص/يوم = 0.5',
    )
    pack_size = models.DecimalField(
        max_digits=8, decimal_places=3,
        default=30,
        verbose_name='حجم العبوة (وحدة)',
        help_text='عدد الأقراص/الكبسولات/الجرعات في العبوة الواحدة',
    )
    expected_duration_days = models.PositiveIntegerField(
        default=30,
        verbose_name='مدة العبوة المتوقعة (يوم)',
        help_text='يُحسب تلقائياً: حجم_العبوة ÷ الاستخدام_اليومي',
    )

    # ── Follow-up timing ──────────────────────────────────────────────────────
    followup_before_days = models.PositiveIntegerField(
        default=5,
        verbose_name='أيام التذكير قبل النفاد',
        help_text='يُنشأ التذكير قبل نفاد الدواء بهذا العدد من الأيام',
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = models.TextField(blank=True, verbose_name='ملاحظات')
    source = models.CharField(
        max_length=12,
        choices=SOURCE_CHOICES,
        default='manual',
        verbose_name='مصدر البيانات',
    )

    # ── Audit ──────────────────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='أنشئ بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['item__name']
        verbose_name = 'بروفايل دواء مزمن'
        verbose_name_plural = 'بروفايلات الأدوية المزمنة'

    def __str__(self):
        return f'{self.item.name} — {self.expected_duration_days} يوم'

    def save(self, *args, **kwargs):
        # Auto-calculate duration from pack_size / avg_daily_usage
        if self.avg_daily_usage and self.avg_daily_usage > 0:
            self.expected_duration_days = max(
                1,
                int(float(self.pack_size) / float(self.avg_daily_usage))
            )
        super().save(*args, **kwargs)

    @property
    def followup_trigger_day(self):
        """
        Day offset from last sale date when a follow-up should be created.
        e.g. duration=30, before=5 → trigger on day 25
        """
        return max(1, self.expected_duration_days - self.followup_before_days)


class FollowUpTask(models.Model):
    """
    A scheduled follow-up task for a chronic patient.

    Lifecycle:
      pending  → assigned to call center / branch staff
      called   → staff attempted contact
      done     → patient confirmed / purchased
      missed   → no response after multiple attempts
      auto_closed → ERP confirmed a new sale automatically
      cancelled
    """

    STATUS_CHOICES = [
        ('pending',     'معلق — لم يُتواصل بعد'),
        ('called',      'تم الاتصال — لا رد'),
        ('done',        'مكتمل — تم الشراء'),
        ('missed',      'فائت — لا استجابة'),
        ('auto_closed', 'أُغلق تلقائياً — الـ ERP أكّد البيع'),
        ('cancelled',   'ملغي'),
    ]

    TYPE_CHOICES = [
        ('refill',    '💊 تذكير إعادة صرف'),
        ('chronic',   '🏥 متابعة مريض مزمن'),
        ('demand',    '📋 متابعة طلب عميل'),
        ('custom',    '📝 مخصص'),
    ]

    # ── Links ─────────────────────────────────────────────────────────────────
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='followup_tasks',
        verbose_name='العميل',
    )
    # LocalCustomer (erp.LocalCustomer) — set when customer is None (unlinked PIC customer).
    # Provides name + phone even before the customer is matched to personsdata.
    local_customer = models.ForeignKey(
        'erp.LocalCustomer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='followup_tasks',
        verbose_name='عميل محلي (PIC)',
    )
    # phcode stored directly for fast lookup / display without joining LocalCustomer
    phcode = models.CharField(
        max_length=30, blank=True, default='', db_index=True,
        verbose_name='كود ERP (phcode)',
    )
    item = models.ForeignKey(
        'catalog.Item',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='followup_tasks',
        verbose_name='الصنف',
    )
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='chronic_followup_tasks',
        verbose_name='الفرع',
    )
    chronic_profile = models.ForeignKey(
        ChronicMedicationProfile,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='followup_tasks',
        verbose_name='بروفايل الدواء المزمن',
    )
    assigned_to = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='chronic_followup_tasks',
        verbose_name='مُعيَّن لـ',
    )

    # ── Task type & dates ─────────────────────────────────────────────────────
    task_type = models.CharField(
        max_length=10,
        choices=TYPE_CHOICES,
        default='refill',
        verbose_name='نوع المهمة',
        db_index=True,
    )
    due_date = models.DateField(
        db_index=True,
        verbose_name='تاريخ الاستحقاق',
    )
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        verbose_name='الحالة',
    )

    # ── ERP anchor — triggering sale ──────────────────────────────────────────
    # source_erp_transaction: docnumber from stktransm (human-readable ERP ref)
    source_erp_transaction = models.CharField(
        max_length=50, blank=True,
        verbose_name='رقم المستند في ERP',
        help_text='stktransm.docnumber — للبحث المباشر في SOFTECH',
    )
    source_sale_date = models.DateField(
        null=True, blank=True,
        verbose_name='تاريخ آخر بيع في الـ ERP',
    )
    # Raw ERP branch code (e.g. "08") — stays stable even if Branch FK changes
    source_softech_branch_code = models.CharField(
        max_length=10, blank=True,
        verbose_name='كود الفرع في ERP',
        help_text='stktransm.branchcode — الكود الخام للفرع في SOFTECH',
    )
    # Invoice total (full document total, not just this item)
    source_total_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        verbose_name='إجمالي الفاتورة',
        help_text='stktransm.totalamount — إجمالي الفاتورة المصدر',
    )
    # Item-level detail from the triggering sale line
    source_item_qty = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True,
        verbose_name='الكمية المباعة',
        help_text='stktrans.qty — كمية هذا الصنف في الفاتورة المصدر',
    )
    source_item_price = models.DecimalField(
        max_digits=10, decimal_places=3, null=True, blank=True,
        verbose_name='سعر الوحدة عند البيع',
        help_text='stktrans.unitprice — سعر البيع الفعلي في الفاتورة المصدر',
    )

    # Auto-close anchor — the sale that closed this task
    closing_erp_transaction = models.CharField(
        max_length=50, blank=True,
        verbose_name='رقم مستند ERP الإغلاق',
    )

    # ── Notes & result ────────────────────────────────────────────────────────
    notes       = models.TextField(blank=True, verbose_name='ملاحظات')
    result_note = models.TextField(blank=True, verbose_name='ملاحظة النتيجة')
    attempts    = models.PositiveIntegerField(default=0, verbose_name='عدد محاولات الاتصال')

    # ── Sales channel (copied from customer at task creation for fast filtering)
    sales_channel = models.CharField(
        max_length=10, blank=True, default='', db_index=True,
        verbose_name='قناة البيع',
        help_text='softech_ptclassifcode: 91=كاش, 90=توصيل, 13=عميل دائم, 15=تأمين',
    )

    # ── Smart priority score ──────────────────────────────────────────────────
    # Composite score: high LTV + high churn risk + overdue + favoured channel
    # Updated nightly by update_priority_scores() service.
    # Higher = more urgent. Used as the default sort order.
    priority_score = models.FloatField(
        default=0.0, db_index=True,
        verbose_name='درجة الأولوية',
        help_text='درجة مركّبة: LTV + خطر الانقطاع + التأخير + قناة البيع. تُحدَّث يومياً.',
    )
    priority_score_updated = models.DateTimeField(
        null=True, blank=True,
        verbose_name='آخر تحديث للأولوية',
    )

    # ── Phone validity ────────────────────────────────────────────────────────
    phone_invalid = models.BooleanField(
        default=False, db_index=True,
        verbose_name='الرقم غير صالح',
        help_text='يُرفع تلقائياً بعد 3 محاولات فاشلة متتالية أو يدوياً من الموظف',
    )
    phone_invalid_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='وقت تأكيد عدم صلاحية الرقم',
    )

    # ── Module links (cross-module bridges) ───────────────────────────────────
    demand_record = models.ForeignKey(
        'demand.DemandRecord',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='followup_tasks',
        verbose_name='طلب مرتبط',
        help_text='طلب طلب تم إنشاؤه تلقائياً من هذه المهمة (إعادة طلب أو صنف غير متوفر)',
    )
    source_campaign = models.ForeignKey(
        'campaigns.WhatsAppCampaign',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='followup_tasks',
        verbose_name='حملة المصدر',
        help_text='الحملة التي أُنشئت منها هذه المهمة',
    )

    # ── Pin / manual watch ────────────────────────────────────────────────────
    # Staff can manually "pin" a task to indicate they are personally tracking it.
    # ONLY pinned tasks (or tasks with assigned_to set) generate notifications.
    # Auto-generated tasks start un-pinned — no notification until a human acts.
    is_pinned = models.BooleanField(
        default=False, db_index=True,
        verbose_name='مثبتة / متابعة يدوية',
        help_text='مثبت من قِبَل موظف — يفعّل الإشعارات لهذه المهمة',
    )
    pinned_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pinned_followup_tasks',
        verbose_name='ثبّتها',
    )
    pinned_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت التثبيت')

    # ── Reminder ──────────────────────────────────────────────────────────────
    reminder_at   = models.DateTimeField(
        null=True, blank=True, db_index=True,
        verbose_name='موعد التذكير',
        help_text='إذا حُدِّد، تُرسَل إشعار للمعيَّن له في هذا الوقت',
    )
    reminder_sent = models.BooleanField(
        default=False,
        verbose_name='تم إرسال التذكير',
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_by   = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_followup_tasks',
        verbose_name='أنشئ بواسطة',
    )
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='completed_followup_tasks',
        verbose_name='أُنجز بواسطة',
    )

    class Meta:
        ordering = ['due_date', '-created_at']
        verbose_name = 'مهمة متابعة'
        verbose_name_plural = 'مهام المتابعة'
        indexes = [
            models.Index(fields=['status', 'due_date']),
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['item', 'status']),
            models.Index(fields=['branch', 'status', 'due_date']),
        ]

    def __str__(self):
        return (
            f'[{self.get_task_type_display()}] '
            f'{self.customer.name} — '
            f'{self.item.name if self.item else "—"} '
            f'@ {self.due_date}'
        )

    # ── Sales channel helpers ─────────────────────────────────────────────────
    # Codes come from stktransm.ptclassifcode (invoice-level, SOFTECH authoritative).
    # Do NOT use personsdata.ptclassifcode — that field is blank for all customers.
    # Format: code → (Arabic label, is_favoured, priority 1=highest)
    _CHANNEL_MAP = {
        '91': ('كاش / مشي',       True,  1),   # walk-in cash — largest segment
        '90': ('توصيل',           True,  1),   # home delivery
        '13': ('عميل دائم',      True,  2),   # permanent customer account
        '10': ('بيع عام',         True,  2),   # general retail (2nd largest in data)
        '11': ('شركات',           False, 3),   # corporate
        '12': ('جملة',            False, 3),   # wholesale
        '30': ('أخرى',            False, 3),   # other / mixed
        '15': ('تأمين',           False, 4),   # insurance — least favoured
        '16': ('تأمين طبي',       False, 4),   # medical insurance
        '17': ('تأمين تكميلي',    False, 4),   # supplementary insurance
    }

    # Codes considered "favoured" for targeting (walk-in + delivery + permanent)
    FAVOURED_CHANNEL_CODES = {'91', '90', '13', '10'}

    @property
    def sales_channel_label(self) -> str:
        entry = self._CHANNEL_MAP.get(self.sales_channel)
        if entry:
            return entry[0]
        if self.sales_channel:
            return f'قناة {self.sales_channel}'
        return '—'

    @property
    def channel_is_favoured(self) -> bool:
        return self.sales_channel in self.FAVOURED_CHANNEL_CODES

    @property
    def channel_priority(self) -> int:
        return self._CHANNEL_MAP.get(self.sales_channel, ('', False, 3))[2]

    # ── Status helpers ────────────────────────────────────────────────────────
    @property
    def is_overdue(self):
        from datetime import date
        return self.status in ('pending', 'called') and self.due_date < date.today()

    @property
    def is_active(self):
        return self.status in ('pending', 'called')

    @property
    def days_until_due(self) -> int:
        from datetime import date
        if not self.due_date:
            return 0
        return (self.due_date - date.today()).days

    @property
    def days_overdue(self) -> int:
        d = self.days_until_due
        return max(0, -d) if d < 0 else 0

    # ── Contact helpers ───────────────────────────────────────────────────────
    @property
    def customer_name(self) -> str:
        """Best available name: Customer → LocalCustomer → phcode."""
        if self.customer_id and self.customer:
            return self.customer.name or ''
        if self.local_customer_id and self.local_customer:
            return self.local_customer.name or ''
        return self.phcode or ''

    @property
    def customer_phone(self) -> str:
        if self.customer_id and self.customer:
            return self.customer.phone or ''
        if self.local_customer_id and self.local_customer:
            return self.local_customer.phone or ''
        return ''

    @property
    def best_phone(self) -> str:
        """WhatsApp phone first, then regular phone. Falls back to LocalCustomer."""
        if self.customer_id and self.customer:
            return self.customer.whatsapp_phone or self.customer.phone or ''
        if self.local_customer_id and self.local_customer:
            return self.local_customer.phone or self.local_customer.phone_alt or ''
        return ''

    def _normalise_phone(self, phone: str) -> str:
        clean = phone.strip().replace(' ', '').replace('-', '').replace('+', '')
        if clean.startswith('0'):
            clean = '20' + clean[1:]
        return clean

    @property
    def whatsapp_url(self):
        phone = self.best_phone or self.customer_phone
        if not phone:
            return None
        return f'https://wa.me/{self._normalise_phone(phone)}'

    def render_whatsapp_message(self) -> str:
        """Pre-filled Arabic WhatsApp refill message."""
        customer_name = self.customer_name or 'عزيزنا'
        item_name     = self.item.name if self.item_id and self.item else 'الدواء'
        prof          = self.chronic_profile

        # Customer code: prefer softech_pic, fall back to phcode field
        customer_code = ''
        if self.customer_id and self.customer:
            customer_code = self.customer.softech_pic or self.customer.softech_id or self.phcode or ''
        elif self.local_customer_id and self.local_customer:
            customer_code = self.local_customer.phcode or self.phcode or ''
        else:
            customer_code = self.phcode or ''

        duration_note = f' ({prof.expected_duration_days} يوم)' if prof else ''

        lines = [
            'أهلا بحضرتك يا فندم،',
            f'{customer_name} 🌿',
        ]
        if customer_code:
            lines.append(f'كود حضرتك {customer_code}')
        lines += [
            '',
            f'نتواصل معكم من صيدلية الرزيقي للتذكير بأن دواء/منتج (*{item_name}*){duration_note} يقترب موعد نفاده.',
            '',
            'نحرص دائماً على متابعتكم لضمان استمرارية علاجكم. 💊',
            'يسعدنا خدمتكم في أقرب فرع أو عبر التوصيل لباب بيتكم 🏠',
            '',
            'صيدليات الرزيقي — نهتم بصحتكم 💙',
        ]
        return '\n'.join(lines)

    @property
    def whatsapp_url_with_message(self):
        import urllib.parse
        url = self.whatsapp_url
        if not url:
            return None
        msg = self.render_whatsapp_message()
        return f'{url}?text={urllib.parse.quote(msg)}'


# ── Outcome presets ───────────────────────────────────────────────────────────
# Used by both backend (validation) and frontend (one-tap logging UI).
# Format: (id, label_ar, result_status, side_action)
#   result_status : the FollowUpTask.status to set
#   side_action   : None | 'create_demand' | 'flag_phone'
OUTCOME_PRESETS = [
    # id                    label                           status    side_action
    ('confirmed_visit',    '✅ أكّد الحضور للفرع',          'done',   None),
    ('confirmed_delivery', '🚚 تأكيد طلب توصيل',            'done',   'create_demand'),
    ('requested_delivery', '🚚 طلب توصيل (جديد)',            'done',   'create_demand'),
    ('call_later',         '📅 سيتصل لاحقاً',               'called', None),
    ('item_unavailable',   '❌ الصنف غير متوفر',             'called', 'create_demand'),
    ('bought_elsewhere',   '🏪 اشترى من مكان آخر',           'done',   None),
    ('substitute_found',   '💊 اشترى بديلاً',               'done',   None),
    ('doctor_changed',     '🏥 طبيبه غيّر الدواء',          'done',   None),
    ('no_answer_week',     '🔇 لا يرد منذ أسبوع',           'missed', None),
    ('wrong_number',       '📵 الرقم خاطئ / غير فعّال',     'missed', 'flag_phone'),
    ('hospitalised',       '🏥 متوجد بالمستشفى',             'called', None),
    ('refused',            '🚫 رفض',                        'missed', None),
]

OUTCOME_PRESET_MAP = {p[0]: p for p in OUTCOME_PRESETS}


class FollowUpTaskAssignment(models.Model):
    """
    Many-to-many through table: which staff members are assigned to a FollowUpTask.

    Why a through model instead of plain M2M:
      - Stores WHO assigned each person (assigned_by) and WHEN (assigned_at)
      - Lets us query efficiently: "tasks assigned to me"
      - Each (task, staff) pair is unique — no duplicate assignments

    Relationship with FollowUpTask.assigned_to (single FK):
      - assigned_to = the PRIMARY / lead assignee (preserved for backward compat
        with existing filters and the "my_tasks" tab)
      - FollowUpTaskAssignment = the FULL list (lead + all additional)
      When only one person is assigned → assigned_to = that person, one Assignment row.
      When multiple are assigned → assigned_to = first resolved (or None), multiple Assignment rows.
    """

    task = models.ForeignKey(
        FollowUpTask,
        on_delete=models.CASCADE,
        related_name='assignments',
        verbose_name='المهمة',
    )
    staff = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.CASCADE,
        related_name='followup_assignments',
        verbose_name='الموظف',
    )
    assigned_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_followup_tasks',
        verbose_name='عيّنها',
    )
    # Snapshot reason: why was this person added?
    # 'direct' | 'role' | 'branch' | 'role_branch'
    assignment_reason = models.CharField(
        max_length=20, default='direct',
        verbose_name='سبب الإسناد',
    )
    assigned_at = models.DateTimeField(auto_now_add=True, verbose_name='وقت الإسناد')

    class Meta:
        unique_together = [('task', 'staff')]
        ordering        = ['assigned_at']
        verbose_name        = 'إسناد مهمة'
        verbose_name_plural = 'إسنادات المهام'

    def __str__(self):
        return f'{self.task_id} → {self.staff.full_name}'
