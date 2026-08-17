"""
apps/callcenter/models.py

Call Center Module — v2

Models:
  CallLog             — every inbound/outbound call with auto customer-match
  CallLogAttachment   — prescription images, voice notes, documents per call
  AddressUpdate       — address updates collected during calls → apply to Customer
  CustomerCase        — groups multiple interactions into a unified case
  CallQualityScore    — QA scoring (supervisor or AI)

Features:
  - Auto-match caller by phone → Customer
  - Full call documentation: notes, attachments, AI summary, transcript
  - Case management with state machine (open→working→escalated→resolved→closed)
  - Quality scoring per call (AHT, FCR, CSAT, custom rubric)
  - SOFTECH read-only: zero writes to Sybase
"""
from django.db import models
from django.utils import timezone


class CallLog(models.Model):
    """One log entry per call — inbound or outbound."""

    DIRECTION_CHOICES = [
        ('inbound',  '📲 واردة'),
        ('outbound', '📞 صادرة'),
        ('whatsapp', '💬 واتساب'),
    ]

    STATUS_CHOICES = [
        ('answered',  '✅ تمت الإجابة'),
        ('no_answer', '📵 لا رد'),
        ('busy',      '📶 مشغول'),
        ('voicemail', '📬 بريد صوتي'),
        ('callback',  '🔄 طلب معاودة اتصال'),
    ]

    PURPOSE_CHOICES = [
        ('reservation',  '📋 استفسار حجز'),
        ('delivery',     '🚚 متابعة توصيل'),
        ('refill',       '💊 إعادة صرف'),
        ('complaint',    '⚠️ شكوى'),
        ('new_order',    '🛒 طلب جديد'),
        ('address',      '📍 تحديث عنوان'),
        ('followup',     '🔔 متابعة مزمن'),
        ('demand',       '🔍 صنف غير متوفر'),
        ('general',      '💬 استفسار عام'),
    ]

    # ── Caller identity ───────────────────────────────────────────────────────
    phone_number = models.CharField(
        max_length=50, db_index=True,
        verbose_name='رقم الهاتف',
    )

    # Auto-matched on save (non-blocking)
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='call_logs',
        verbose_name='العميل',
    )
    caller_name = models.CharField(
        max_length=255, blank=True,
        verbose_name='اسم المتصل',
        help_text='من يتصل — إذا مختلف عن اسم العميل في النظام',
    )

    # ── Call metadata ─────────────────────────────────────────────────────────
    direction = models.CharField(
        max_length=10,
        choices=DIRECTION_CHOICES,
        default='inbound',
        verbose_name='اتجاه المكالمة',
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='answered',
        verbose_name='حالة المكالمة',
    )
    purpose = models.CharField(
        max_length=15,
        choices=PURPOSE_CHOICES,
        default='general',
        db_index=True,
        verbose_name='الغرض',
    )
    duration_seconds = models.PositiveIntegerField(
        default=0,
        verbose_name='مدة المكالمة (ثانية)',
    )

    # ── Staff ─────────────────────────────────────────────────────────────────
    handled_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='call_logs',
        verbose_name='تولّى المكالمة',
    )
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='call_logs',
        verbose_name='الفرع',
    )

    # ── Content ───────────────────────────────────────────────────────────────
    notes = models.TextField(blank=True, verbose_name='ملاحظات المكالمة')
    summary = models.CharField(
        max_length=255, blank=True,
        verbose_name='ملخص سريع',
    )

    # ── Linked domain objects (what was discussed) ────────────────────────────
    reservation = models.ForeignKey(
        'reservations.Reservation',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='call_logs',
        verbose_name='الحجز المرتبط',
    )
    followup_task = models.ForeignKey(
        'followups.FollowUpTask',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='call_logs',
        verbose_name='مهمة المتابعة المرتبطة',
    )

    # ── Payment info (collected during call) ──────────────────────────────────
    payment_method = models.CharField(
        max_length=30, blank=True,
        verbose_name='طريقة الدفع',
        help_text='كاش / فيزا / محفظة / تأمين',
    )

    # ── Case linkage ──────────────────────────────────────────────────────────
    case = models.ForeignKey(
        'callcenter.CustomerCase',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='calls',
        verbose_name='الحالة المرتبطة',
    )

    # ── Recording & transcript ─────────────────────────────────────────────────
    recording_url = models.URLField(
        blank=True,
        verbose_name='رابط التسجيل',
    )
    voice_transcript = models.TextField(
        blank=True,
        verbose_name='النص الصوتي',
        help_text='نص المكالمة بعد التعرف على الصوت',
    )
    prescription_image = models.ImageField(
        upload_to='callcenter/prescriptions/%Y/%m/',
        null=True, blank=True,
        verbose_name='صورة الروشتة',
    )

    # ── AI fields (populated asynchronously by Gemini) ────────────────────────
    ai_summary   = models.TextField(blank=True, verbose_name='ملخص الذكاء الاصطناعي')
    ai_intent    = models.CharField(
        max_length=50, blank=True,
        verbose_name='نية المكالمة (AI)',
        help_text='purchase / complaint / inquiry / refill / delivery …',
    )
    ai_sentiment = models.CharField(
        max_length=15, blank=True,
        choices=[
            ('positive', 'إيجابي 😊'),
            ('neutral',  'محايد 😐'),
            ('negative', 'سلبي 😟'),
        ],
        verbose_name='مشاعر العميل (AI)',
    )
    ai_urgency = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name='درجة الإلحاح (AI)',
        help_text='1 = منخفض … 5 = عاجل جداً',
    )
    ai_next_action = models.CharField(
        max_length=255, blank=True,
        verbose_name='الإجراء المقترح (AI)',
    )
    ai_processed_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت معالجة AI')

    # ── Quality score (set by supervisor or AI scoring) ───────────────────────
    quality_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name='نقاط الجودة (1-100)',
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    called_at  = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Callback scheduling
    callback_due = models.DateTimeField(
        null=True, blank=True,
        verbose_name='موعد معاودة الاتصال',
    )

    class Meta:
        ordering = ['-called_at']
        verbose_name = 'سجل مكالمة'
        verbose_name_plural = 'سجلات المكالمات'
        indexes = [
            models.Index(fields=['phone_number', 'called_at']),
            models.Index(fields=['customer', 'called_at']),
            models.Index(fields=['purpose', 'called_at']),
            models.Index(fields=['handled_by', 'called_at']),
            models.Index(fields=['status', 'called_at']),
            models.Index(fields=['callback_due']),
        ]

    def __str__(self):
        name = self.caller_name or (self.customer.name if self.customer else self.phone_number)
        return f'[{self.get_direction_display()}] {name} — {self.called_at:%Y-%m-%d %H:%M}'

    def save(self, *args, **kwargs):
        # Auto-match customer on first save
        if not self.customer and self.phone_number:
            self._try_match_customer()
        super().save(*args, **kwargs)

    def _try_match_customer(self):
        """Non-blocking phone → Customer + LocalCustomer match."""
        try:
            from apps.customers.models import Customer
            tail = self.phone_number.strip().replace(' ', '')[-9:]

            customer = Customer.objects.filter(
                phone__endswith=tail
            ).first()
            if not customer:
                customer = Customer.objects.filter(
                    phone_alt__endswith=tail
                ).first()

            if customer:
                self.customer = customer
                if not self.caller_name:
                    self.caller_name = customer.name
        except Exception:
            pass

        # LocalCustomer (erp app) lookup removed — use Customer only

    @property
    def duration_label(self):
        if not self.duration_seconds:
            return '—'
        m, s = divmod(self.duration_seconds, 60)
        return f'{m}د {s}ث' if m else f'{s}ث'

    @property
    def whatsapp_url(self):
        phone = self.phone_number
        if not phone:
            return None
        clean = phone.strip().replace(' ', '').replace('-', '')
        if clean.startswith('0'):
            clean = '20' + clean[1:]
        return f'https://wa.me/{clean}'

    @property
    def needs_callback(self):
        from django.utils import timezone
        return (
            self.status == 'callback' and
            self.callback_due and
            self.callback_due > timezone.now()
        )


class AddressUpdate(models.Model):
    """
    Address update collected during a call.
    After validation, creates/updates a CustomerLocation.
    """

    STATUS_CHOICES = [
        ('pending',   '⏳ بانتظار التطبيق'),
        ('applied',   '✅ تم التطبيق'),
        ('rejected',  '❌ مرفوض'),
    ]

    call_log = models.ForeignKey(
        CallLog,
        on_delete=models.CASCADE,
        related_name='address_updates',
        verbose_name='سجل المكالمة',
    )
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='address_updates',
        verbose_name='العميل',
    )

    # ── New address data ──────────────────────────────────────────────────────
    label = models.CharField(
        max_length=15, default='home',
        verbose_name='نوع العنوان',
    )
    label_custom = models.CharField(max_length=50, blank=True)
    address_text = models.TextField(verbose_name='العنوان الجديد')
    area = models.CharField(max_length=100, blank=True)
    floor = models.CharField(max_length=10, blank=True)
    apartment = models.CharField(max_length=20, blank=True)
    landmark = models.CharField(max_length=200, blank=True)
    google_maps_link = models.URLField(blank=True)
    delivery_phone = models.CharField(max_length=50, blank=True)
    delivery_notes = models.TextField(blank=True)
    set_as_default = models.BooleanField(default=True)

    # ── Application ───────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='الحالة',
    )
    applied_location_ref = models.CharField(
        max_length=100, blank=True,
        verbose_name='مرجع العنوان المُنشأ',
        help_text='يُحفظ هنا تلقائياً بعد تطبيق التحديث',
    )
    applied_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='طبّقه',
    )
    applied_at = models.DateTimeField(null=True, blank=True)

    collected_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='collected_address_updates',
        verbose_name='جُمع بواسطة',
    )
    collected_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-collected_at']
        verbose_name = 'تحديث عنوان'
        verbose_name_plural = 'تحديثات العناوين'

    def __str__(self):
        return f'{self.customer.name} — {self.address_text[:60]}'

    def apply(self, applied_by=None):
        """
        Marks this address update as applied and stores a reference string.
        Customer address is updated directly on the Customer record.
        Non-fatal — returns True on success.
        """
        from django.utils import timezone as tz
        try:
            # Update the customer's primary address directly
            if self.customer:
                full_address = ' '.join(filter(None, [
                    self.area, self.address_text, self.floor, self.apartment,
                    self.landmark,
                ]))
                self.customer.address = full_address
                self.customer.save(update_fields=['address'])

            self.status              = 'applied'
            self.applied_location_ref = f'address updated for customer #{self.customer_id}'
            self.applied_by          = applied_by
            self.applied_at          = tz.now()
            self.save(update_fields=[
                'status', 'applied_location_ref', 'applied_by', 'applied_at'
            ])
            return True
        except Exception:
            return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CallLogAttachment — files/media attached to a call
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CallLogAttachment(models.Model):
    """Prescription images, voice notes, documents attached to a call log."""

    TYPE_CHOICES = [
        ('prescription', '💊 روشتة'),
        ('image',        '🖼️ صورة'),
        ('voice',        '🎙️ مقطع صوتي'),
        ('document',     '📄 مستند'),
    ]

    call_log    = models.ForeignKey(
        CallLog,
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name='سجل المكالمة',
    )
    file        = models.FileField(
        upload_to='callcenter/attachments/%Y/%m/',
        verbose_name='الملف',
    )
    file_type   = models.CharField(
        max_length=15,
        choices=TYPE_CHOICES,
        default='image',
        verbose_name='نوع الملف',
    )
    description = models.CharField(max_length=255, blank=True, verbose_name='الوصف')
    file_size   = models.PositiveIntegerField(default=0, verbose_name='الحجم (بايت)')
    uploaded_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='رُفع بواسطة',
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        verbose_name = 'مرفق مكالمة'
        verbose_name_plural = 'مرفقات المكالمات'

    def __str__(self):
        return f'{self.get_file_type_display()} — {self.call_log_id}'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CustomerCase — unified case grouping multiple interactions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CustomerCase(models.Model):
    """
    Groups multiple interactions (calls, demands, complaints) per customer
    into a unified case for root-cause tracking and resolution.

    Lifecycle: open → working → waiting → escalated → resolved → closed
    """

    CATEGORY_CHOICES = [
        ('complaint',   '⚠️ شكوى'),
        ('inquiry',     '❓ استفسار'),
        ('request',     '📋 طلب'),
        ('lost_sale',   '❌ بيعة مفقودة'),
        ('delivery',    '🚚 توصيل'),
        ('support',     '🛠️ دعم'),
        ('refund',      '↩️ إرجاع/استبدال'),
        ('other',       '💬 أخرى'),
    ]

    STATUS_CHOICES = [
        ('open',       '🆕 مفتوحة'),
        ('working',    '⚙️ قيد المعالجة'),
        ('waiting',    '⏳ انتظار العميل'),
        ('escalated',  '🔴 مُصعَّدة'),
        ('resolved',   '✅ محلولة'),
        ('closed',     '🔒 مغلقة'),
    ]

    PRIORITY_CHOICES = [
        ('low',    'منخفضة'),
        ('normal', 'عادية'),
        ('high',   'مرتفعة'),
        ('urgent', 'عاجلة 🔴'),
    ]

    case_number = models.CharField(
        max_length=20, unique=True, blank=True,
        verbose_name='رقم الحالة',
    )
    customer = models.ForeignKey(
        'customers.Customer',
        on_delete=models.CASCADE,
        related_name='cases',
        verbose_name='العميل',
    )
    category = models.CharField(
        max_length=15, choices=CATEGORY_CHOICES,
        db_index=True, verbose_name='تصنيف الحالة',
    )
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES,
        default='normal', verbose_name='الأولوية',
    )
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES,
        default='open', db_index=True, verbose_name='الحالة',
    )
    title       = models.CharField(max_length=255, verbose_name='عنوان الحالة')
    description = models.TextField(blank=True, verbose_name='الوصف التفصيلي')
    root_cause  = models.TextField(blank=True, verbose_name='السبب الجذري')
    resolution  = models.TextField(blank=True, verbose_name='طريقة الحل')

    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='customer_cases',
        verbose_name='الفرع',
    )

    # ── Linked domain objects ─────────────────────────────────────────────────
    demand = models.ForeignKey(
        'demand.DemandRecord',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cases',
        verbose_name='الطلب المرتبط',
    )
    reservation = models.ForeignKey(
        'reservations.Reservation',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cases',
        verbose_name='الحجز المرتبط',
    )
    delivery = models.ForeignKey(
        'delivery.DeliveryOrder',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='cases',
        verbose_name='التوصيل المرتبط',
    )

    # ── Ownership ─────────────────────────────────────────────────────────────
    opened_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True,
        related_name='opened_cases',
        verbose_name='فُتح بواسطة',
    )
    assigned_to = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assigned_cases',
        verbose_name='مُعيَّن لـ',
    )

    # ── SLA ───────────────────────────────────────────────────────────────────
    sla_due     = models.DateTimeField(null=True, blank=True, verbose_name='موعد SLA')
    resolved_at = models.DateTimeField(null=True, blank=True, verbose_name='وقت الحل')
    closed_at   = models.DateTimeField(null=True, blank=True, verbose_name='وقت الإغلاق')

    # ── CSAT (customer satisfaction score) ────────────────────────────────────
    csat_score = models.PositiveSmallIntegerField(
        null=True, blank=True,
        verbose_name='تقييم العميل (1-5)',
    )
    csat_note = models.TextField(blank=True, verbose_name='تعليق التقييم')

    # ── Escalation ────────────────────────────────────────────────────────────
    escalated_to = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='escalated_cases',
        verbose_name='صُعِّدت لـ',
    )
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalation_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'حالة عميل'
        verbose_name_plural = 'حالات العملاء'
        indexes = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['status', 'branch']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['category', 'status']),
        ]

    def __str__(self):
        return f'{self.case_number} | {self.customer.name} | {self.get_status_display()}'

    def save(self, *args, **kwargs):
        if not self.case_number:
            super().save(*args, **kwargs)
            self.case_number = f'CASE-{self.pk:06d}'
            kwargs['force_insert'] = False
        super().save(*args, **kwargs)

    # ── State machine helpers ─────────────────────────────────────────────────

    def assign(self, staff, note=''):
        self.assigned_to = staff
        if self.status == 'open':
            self.status = 'working'
        self.save(update_fields=['assigned_to', 'status', 'updated_at'])
        self._log_event(f'تم التعيين لـ {staff.full_name}' + (f' — {note}' if note else ''), staff)

    def escalate(self, to_staff, reason, by_staff):
        self.status         = 'escalated'
        self.escalated_to   = to_staff
        self.escalated_at   = timezone.now()
        self.escalation_reason = reason
        self.save(update_fields=['status', 'escalated_to', 'escalated_at', 'escalation_reason', 'updated_at'])
        self._log_event(f'تصعيد إلى {to_staff.full_name}: {reason}', by_staff)

    def resolve(self, resolution, root_cause='', by_staff=None):
        self.status      = 'resolved'
        self.resolution  = resolution
        self.root_cause  = root_cause
        self.resolved_at = timezone.now()
        self.save(update_fields=['status', 'resolution', 'root_cause', 'resolved_at', 'updated_at'])
        self._log_event(f'تم الحل: {resolution}', by_staff)

    def close(self, by_staff=None):
        self.status    = 'closed'
        self.closed_at = timezone.now()
        self.save(update_fields=['status', 'closed_at', 'updated_at'])
        self._log_event('الحالة مُغلقة', by_staff)

    def set_csat(self, score, note=''):
        self.csat_score = max(1, min(5, int(score)))
        self.csat_note  = note
        self.save(update_fields=['csat_score', 'csat_note', 'updated_at'])

    @property
    def is_sla_breached(self):
        if not self.sla_due or self.status in ('resolved', 'closed'):
            return False
        return timezone.now() > self.sla_due

    @property
    def age_hours(self):
        delta = timezone.now() - self.created_at
        return round(delta.total_seconds() / 3600, 1)

    @property
    def resolution_time_hours(self):
        if not self.resolved_at:
            return None
        delta = self.resolved_at - self.created_at
        return round(delta.total_seconds() / 3600, 1)

    def _log_event(self, message, staff=None):
        """Internal: log a CaseEvent for audit trail."""
        try:
            CaseEvent.objects.create(
                case=self,
                event_type='system',
                message=message,
                created_by=staff,
            )
        except Exception:
            pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CaseEvent — chatter / audit trail per case
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CaseEvent(models.Model):
    """One log entry per event on a CustomerCase (status change, note, call, system)."""

    EVENT_TYPES = [
        ('note',   '📝 ملاحظة'),
        ('call',   '📞 مكالمة'),
        ('status', '🔄 تغيير حالة'),
        ('system', '⚙️ نظام'),
    ]

    case       = models.ForeignKey(
        CustomerCase, on_delete=models.CASCADE,
        related_name='events', verbose_name='الحالة',
    )
    event_type = models.CharField(max_length=10, choices=EVENT_TYPES, default='note')
    message    = models.TextField(verbose_name='الرسالة')
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='بواسطة',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    ATTACHMENT_TYPE_CHOICES = [
        ('image',    '🖼️ صورة'),
        ('voice',    '🎙️ صوت'),
        ('document', '📄 مستند'),
    ]
    attachment = models.FileField(
        upload_to='callcenter/case_events/%Y/%m/',
        blank=True, null=True,
        verbose_name='المرفق',
    )
    attachment_type = models.CharField(
        max_length=10, blank=True,
        choices=ATTACHMENT_TYPE_CHOICES,
        verbose_name='نوع المرفق',
    )

    class Meta:
        ordering = ['created_at']
        verbose_name = 'حدث حالة'
        verbose_name_plural = 'أحداث الحالة'

    def __str__(self):
        return f'[{self.get_event_type_display()}] {self.case_id}: {self.message[:60]}'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CallQualityScore — supervisor / AI quality scoring per call
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CallQualityScore(models.Model):
    """QA evaluation of a call log. One score per call."""

    SOURCE_CHOICES = [
        ('supervisor', '👤 مشرف'),
        ('ai',         '🤖 ذكاء اصطناعي'),
    ]

    call_log     = models.OneToOneField(
        CallLog,
        on_delete=models.CASCADE,
        related_name='quality',
        verbose_name='سجل المكالمة',
    )
    scored_by    = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='quality_scores_given',
        verbose_name='المقيِّم',
    )
    source       = models.CharField(
        max_length=12, choices=SOURCE_CHOICES, default='supervisor',
        verbose_name='مصدر التقييم',
    )

    # ── Rubric (0-100 total) ──────────────────────────────────────────────────
    greeting      = models.PositiveSmallIntegerField(default=0, verbose_name='الترحيب والتعريف (0-20)')
    resolution    = models.PositiveSmallIntegerField(default=0, verbose_name='حل المشكلة (0-30)')
    communication = models.PositiveSmallIntegerField(default=0, verbose_name='وضوح التواصل (0-25)')
    accuracy      = models.PositiveSmallIntegerField(default=0, verbose_name='دقة المعلومات (0-25)')
    total_score   = models.PositiveSmallIntegerField(default=0, verbose_name='الدرجة الإجمالية (0-100)')

    notes    = models.TextField(blank=True, verbose_name='ملاحظات التقييم')
    scored_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scored_at']
        verbose_name = 'تقييم جودة مكالمة'
        verbose_name_plural = 'تقييمات جودة المكالمات'

    def __str__(self):
        return f'تقييم مكالمة {self.call_log_id}: {self.total_score}/100'

    def save(self, *args, **kwargs):
        self.total_score = self.greeting + self.resolution + self.communication + self.accuracy
        # Sync quality_score on the parent CallLog
        super().save(*args, **kwargs)
        CallLog.objects.filter(pk=self.call_log_id).update(quality_score=self.total_score)


# ── Call Items ─────────────────────────────────────────────────────────────────

class CallItem(models.Model):
    """
    An item discussed during a call — may or may not exist in the catalog.
    Can later be converted to a Reservation or TransferRequest (tracked here).
    """

    CONVERTED_TO_CHOICES = [
        ('none',        'لم يُحوَّل'),
        ('reservation', 'حجز'),
        ('transfer',    'طلب نقل'),
    ]

    call_log = models.ForeignKey(
        CallLog,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='المكالمة',
    )

    # ── Item reference (catalog or free-text) ─────────────────────────────────
    item = models.ForeignKey(
        'catalog.Item',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='call_items',
        verbose_name='الصنف من الكتالوج',
    )
    manual_item_name = models.CharField(
        max_length=255, blank=True,
        verbose_name='اسم الصنف (يدوي)',
        help_text='يُستخدم عندما لا يوجد الصنف في الكتالوج',
    )
    manual_item_code = models.CharField(
        max_length=20, blank=True,
        verbose_name='كود SOFTECH (يدوي)',
    )

    # ── Quantity & notes ──────────────────────────────────────────────────────
    quantity = models.DecimalField(
        max_digits=10, decimal_places=2,
        default=1,
        verbose_name='الكمية',
    )
    notes = models.TextField(blank=True, verbose_name='ملاحظات')

    # ── Conversion tracking ───────────────────────────────────────────────────
    converted_to = models.CharField(
        max_length=15,
        choices=CONVERTED_TO_CHOICES,
        default='none',
        db_index=True,
        verbose_name='حُوِّل إلى',
    )
    converted_reservation = models.ForeignKey(
        'reservations.Reservation',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='source_call_items',
        verbose_name='الحجز المُنشأ',
    )
    converted_transfer = models.ForeignKey(
        'transfers.TransferRequest',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='source_call_items',
        verbose_name='طلب النقل المُنشأ',
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'صنف مكالمة'
        verbose_name_plural = 'أصناف المكالمات'

    def __str__(self):
        label = self.item.name if self.item else self.manual_item_name
        return f'{label} × {self.quantity} — مكالمة {self.call_log_id}'

    @property
    def display_name(self):
        if self.item:
            return self.item.name
        return self.manual_item_name or '—'

    @property
    def display_code(self):
        if self.item:
            return self.item.softech_id or ''
        return self.manual_item_code
