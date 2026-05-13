"""
apps/callcenter/models.py

Phase 8: Call Center Module

CallLog         — every inbound/outbound call logged with auto-match to customer
CallOutcome     — structured outcome of each call
AddressUpdate   — address/location updates collected during calls

Features:
  - Auto-match caller by phone to Customer + LocalCustomer
  - Log reservations / demands / follow-ups touched during call
  - Address updates feed into CustomerLocation
  - WhatsApp message generation for delivery
  - Full chatter-style history per customer
"""
from django.db import models


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
