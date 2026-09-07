"""
apps/omni/models.py

Omnichannel Communication Platform (CEP) — Phase 0 unification core.
Design: docs/architecture/15_CEP_OMNICHANNEL_DESIGN.md

Models:
  ChannelAccount — one row per company communication endpoint
                   (a WhatsApp number, a PBX trunk, a social page…)
  Conversation   — the customer-grouped umbrella: one customer, many
                   channels, ONE timeline
  TimelineEvent  — append-only envelope; GenericFK to the native record
                   (WAMessage, CallLog, Reservation, …)

Design rules:
  - Channel-native models (WAMessage, CallSession, …) remain the system
    of record. This app never duplicates message content — only envelopes.
  - TimelineEvent is IMMUTABLE (append-only) — same guard as PBXEvent.
  - Conversations for unidentified contacts are grouped by contact_phone
    until a Customer match is found.
"""
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ChannelAccount — company communication endpoint registry
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ChannelAccount(models.Model):

    CHANNEL_CHOICES = [
        ('whatsapp',  'واتساب'),
        ('voice',     'مكالمات'),
        ('messenger', 'فيسبوك ماسنجر'),
        ('instagram', 'إنستجرام'),
        ('telegram',  'تيليجرام'),
        ('tiktok',    'تيك توك'),
        ('sms',       'رسائل SMS'),
        ('email',     'بريد إلكتروني'),
    ]

    PROVIDER_CHOICES = [
        ('meta_cloud',     'Meta Cloud API'),
        ('d360',           '360dialog'),
        ('twilio',         'Twilio'),
        ('android_bridge', 'جسر أندرويد (مرحلي)'),
        ('ami',            'Issabel / Asterisk AMI'),
        ('meta_graph',     'Meta Graph (ماسنجر/إنستجرام)'),
        ('telegram_bot',   'Telegram Bot API'),
        ('other',          'أخرى'),
    ]

    STATUS_CHOICES = [
        ('connected',    'متصل'),
        ('disconnected', 'منقطع'),
        ('degraded',     'متدهور'),
        ('pending_qr',   'بانتظار QR'),
    ]

    channel        = models.CharField(
        max_length=12, choices=CHANNEL_CHOICES, db_index=True,
        verbose_name='القناة',
    )
    name           = models.CharField(max_length=100, verbose_name='اسم الحساب')
    # Phone number (international, no +) or page/bot handle
    phone_or_handle = models.CharField(
        max_length=100, verbose_name='الرقم / المعرف',
    )
    branch         = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='omni_accounts',
        verbose_name='الفرع',
    )
    department     = models.CharField(
        max_length=50, blank=True,
        verbose_name='القسم',
        help_text='مثل: مركز الاتصالات، التوصيل، التأمين',
    )
    provider       = models.CharField(
        max_length=15, choices=PROVIDER_CHOICES, default='meta_cloud',
        verbose_name='المزوّد',
    )
    # Provider credentials (token, phone_number_id, …) — encrypted at rest
    # via apps/omni/crypto.py, stored as {"_enc": "<fernet token>"}.
    # NEVER serialized in any API response — use set_credentials()/get_credentials().
    # The legacy default WhatsApp account may keep credentials in env instead
    # (empty here → provider falls back to WHATSAPP_TOKEN / _PHONE_NUMBER_ID).
    credentials    = models.JSONField(default=dict, blank=True, verbose_name='بيانات الاعتماد')

    # Public provider-side identifier used to route inbound webhooks —
    # for Meta Cloud API this is the phone_number_id. Not secret, queryable.
    provider_ref   = models.CharField(
        max_length=100, blank=True, db_index=True,
        verbose_name='معرف المزوّد',
        help_text='Meta phone_number_id — يوجّه Webhooks الواردة لهذا الحساب',
    )
    # Default sending account per channel (OTP, campaigns, portal links…)
    is_default     = models.BooleanField(
        default=False, verbose_name='الحساب الافتراضي',
        help_text='حساب الإرسال الافتراضي للقناة عندما لا يُحدَّد حساب',
    )

    status         = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default='connected',
        db_index=True, verbose_name='الحالة',
    )
    last_heartbeat_at = models.DateTimeField(null=True, blank=True, verbose_name='آخر نبضة')
    # Free-form health metrics: battery, device, api_quota, error_rate…
    health         = models.JSONField(default=dict, blank=True, verbose_name='الصحة')
    working_hours  = models.JSONField(
        default=dict, blank=True,
        verbose_name='ساعات العمل',
        help_text='{"sat": ["09:00","23:00"], ...} — فارغ = دائماً',
    )
    supervisor     = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='supervised_omni_accounts',
        verbose_name='المشرف',
    )
    is_active      = models.BooleanField(default=True, verbose_name='نشط')

    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['channel', 'name']
        verbose_name        = 'حساب قناة'
        verbose_name_plural = 'حسابات القنوات'
        constraints = [
            models.UniqueConstraint(
                fields=['channel', 'phone_or_handle'],
                name='uniq_omni_account_channel_handle',
            ),
        ]

    def __str__(self):
        return f'[{self.get_channel_display()}] {self.name} ({self.phone_or_handle})'

    # ── Credential access (encryption boundary) ──────────────────────────────

    def set_credentials(self, data: dict):
        """Encrypt and store provider credentials. Call save() afterwards."""
        from apps.omni.crypto import encrypt_credentials
        self.credentials = encrypt_credentials(data or {})

    def get_credentials(self) -> dict:
        """Decrypted provider credentials ({} when unset or key mismatch)."""
        from apps.omni.crypto import decrypt_credentials
        return decrypt_credentials(self.credentials)

    def touch_heartbeat(self, status: str = 'connected'):
        """Record provider liveness (webhook received / send succeeded)."""
        self.last_heartbeat_at = timezone.now()
        self.status = status
        self.save(update_fields=['last_heartbeat_at', 'status', 'updated_at'])

    @classmethod
    def default_for(cls, channel: str):
        """The default sending account for a channel (None when unconfigured)."""
        return (
            cls.objects.filter(channel=channel, is_active=True)
            .order_by('-is_default', 'id')
            .first()
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Conversation — customer-grouped umbrella (one customer, one timeline)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class Conversation(models.Model):

    STATUS_CHOICES = [
        ('open',     'مفتوحة'),
        ('pending',  'بانتظار رد'),
        ('snoozed',  'مؤجلة'),
        ('resolved', 'محلولة'),
        ('closed',   'مغلقة'),
    ]
    ACTIVE_STATUSES = ('open', 'pending', 'snoozed')

    PRIORITY_CHOICES = [
        ('normal', 'عادية'),
        ('high',   'مرتفعة'),
        ('urgent', 'عاجلة'),
    ]

    customer       = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='omni_conversations',
        verbose_name='العميل',
    )
    # Grouping key for contacts not yet matched to a Customer
    contact_phone  = models.CharField(
        max_length=50, blank=True, db_index=True,
        verbose_name='هاتف جهة الاتصال',
    )
    status         = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='open',
        db_index=True, verbose_name='الحالة',
    )
    priority       = models.CharField(
        max_length=8, choices=PRIORITY_CHOICES, default='normal',
        verbose_name='الأولوية',
    )
    branch         = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='omni_conversations',
        verbose_name='الفرع',
    )
    assigned_to    = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='omni_conversations',
        verbose_name='موكلة إلى',
    )
    subject        = models.CharField(max_length=255, blank=True, verbose_name='الموضوع')
    # Channel of the event that opened the conversation
    created_from_channel = models.CharField(
        max_length=12, blank=True, db_index=True,
        verbose_name='قناة الإنشاء',
    )

    first_inbound_at   = models.DateTimeField(null=True, blank=True)
    last_activity_at   = models.DateTimeField(null=True, blank=True, db_index=True)
    last_event_preview = models.CharField(max_length=255, blank=True)

    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_activity_at']
        verbose_name        = 'محادثة موحدة'
        verbose_name_plural = 'المحادثات الموحدة'
        indexes = [
            models.Index(fields=['status', 'last_activity_at']),
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['assigned_to', 'status']),
        ]

    def __str__(self):
        who = self.customer.name if self.customer else (self.contact_phone or 'مجهول')
        return f'محادثة #{self.pk} — {who} [{self.get_status_display()}]'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TimelineEvent — append-only envelope over native records (IMMUTABLE)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TimelineEvent(models.Model):

    EVENT_TYPE_CHOICES = [
        ('message_in',        'رسالة واردة'),
        ('message_out',       'رسالة صادرة'),
        ('call',              'مكالمة'),
        ('call_missed',       'مكالمة فائتة'),
        ('note',              'ملاحظة داخلية'),
        ('assignment',        'إسناد'),
        ('status_change',     'تغيير حالة'),
        ('erp_reservation',   'حجز'),
        ('erp_delivery',      'توصيل'),
        ('erp_invoice',       'فاتورة'),
        ('erp_case',          'حالة خدمة'),
        ('erp_demand',        'طلب غير متوفر'),
        ('erp_payment',       'دفعة'),
        ('ai_insight',        'تحليل ذكي'),
        ('automation_action', 'إجراء آلي'),
        ('sla_breach',        'تجاوز SLA'),
    ]

    conversation   = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='events',
        verbose_name='المحادثة',
    )
    event_type     = models.CharField(
        max_length=20, choices=EVENT_TYPE_CHOICES, db_index=True,
        verbose_name='نوع الحدث',
    )
    channel        = models.CharField(
        max_length=12, blank=True,
        verbose_name='القناة',
    )
    account        = models.ForeignKey(
        ChannelAccount,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='events',
        verbose_name='حساب القناة',
    )

    # Link to the native record (WAMessage, CallLog, Reservation, …)
    content_type   = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True,
    )
    object_id      = models.PositiveBigIntegerField(null=True, blank=True)
    native         = GenericForeignKey('content_type', 'object_id')

    # Denormalized preview so list rendering never touches native tables
    summary        = models.CharField(max_length=255, blank=True, verbose_name='الملخص')
    actor          = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='omni_events',
        verbose_name='الموظف',
    )
    occurred_at    = models.DateTimeField(default=timezone.now, db_index=True)
    # Snapshot payload for fast rendering (message body preview, call duration…)
    payload        = models.JSONField(default=dict, blank=True)

    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['occurred_at']
        verbose_name        = 'حدث محادثة'
        verbose_name_plural = 'أحداث المحادثات'
        indexes = [
            models.Index(fields=['conversation', 'occurred_at']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['event_type', 'occurred_at']),
        ]

    def __str__(self):
        return f'[{self.get_event_type_display()}] {self.summary[:60]} @ {self.occurred_at:%Y-%m-%d %H:%M}'

    # Immutability guard — same pattern as pbx.PBXEvent
    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('TimelineEvent is append-only — cannot edit')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError('TimelineEvent is append-only — cannot delete')


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# AutomationRule — no-code trigger → conditions → actions (doc 15 Phase 4)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class AutomationRule(models.Model):

    # Triggers are TimelineEvent event_types the engine reacts to
    TRIGGER_CHOICES = [
        ('message_in',      'رسالة واردة'),
        ('call',            'مكالمة'),
        ('call_missed',     'مكالمة فائتة'),
        ('erp_reservation', 'حجز'),
        ('ai_insight',      'تحليل ذكي'),
    ]

    name        = models.CharField(max_length=120, verbose_name='اسم القاعدة')
    trigger     = models.CharField(
        max_length=20, choices=TRIGGER_CHOICES, db_index=True,
        verbose_name='المُحفِّز',
    )
    # Conditions (ALL must match). Supported keys:
    #   channel: 'whatsapp'|'voice'|'messenger'|...
    #   text_contains: [keywords]  → matches event.summary
    #   customer_vip: true         → customer.is_vip (guarded)
    #   priority: 'urgent'|'high'|'normal'
    #   unassigned: true
    #   sentiment: 'negative'      → payload.sentiment
    conditions  = models.JSONField(default=dict, blank=True, verbose_name='الشروط')

    # Actions (executed in order). Each: {'type': ..., ...params}
    #   set_priority   {'priority': 'urgent'}
    #   set_status     {'status': 'pending'}
    #   add_tag        {'tag': 'شكوى'}  (stored in conversation subject prefix)
    #   assign_role    {'role': 'supervisor'}  (first available)
    #   notify_role    {'role': 'supervisor', 'text': '...'}
    #   add_note       {'text': '...'}
    #   auto_reply     {'text': '...'}   (WhatsApp/social, window permitting)
    actions     = models.JSONField(default=list, blank=True, verbose_name='الإجراءات')

    is_active   = models.BooleanField(default=True, db_index=True, verbose_name='مفعّلة')
    # Stop evaluating later rules on the same event when this one matches
    stop_processing = models.BooleanField(default=False, verbose_name='إيقاف القواعد التالية')
    order       = models.PositiveSmallIntegerField(default=100, verbose_name='الترتيب')

    run_count   = models.PositiveIntegerField(default=0, verbose_name='مرات التنفيذ')
    last_run_at = models.DateTimeField(null=True, blank=True)
    created_by  = models.ForeignKey(
        'users.StaffProfile', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='omni_automations',
    )
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['order', 'id']
        verbose_name        = 'قاعدة أتمتة'
        verbose_name_plural = 'قواعد الأتمتة'
        indexes = [models.Index(fields=['trigger', 'is_active'])]

    def __str__(self):
        return f'{self.name} [{self.get_trigger_display()}]'


class AutomationRun(models.Model):
    """Immutable execution log — one row per rule firing on an event."""

    rule        = models.ForeignKey(
        AutomationRule, on_delete=models.CASCADE, related_name='runs')
    event       = models.ForeignKey(
        TimelineEvent, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='automation_runs')
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name='automation_runs')
    matched     = models.BooleanField(default=False)
    actions_run = models.JSONField(default=list, blank=True)
    error       = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'تنفيذ أتمتة'
        verbose_name_plural = 'تنفيذات الأتمتة'

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('AutomationRun is immutable')
        super().save(*args, **kwargs)
