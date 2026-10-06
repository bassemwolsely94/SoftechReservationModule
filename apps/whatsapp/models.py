"""
apps/whatsapp/models.py

WhatsApp Business Platform integration layer.

Models:
  WATemplate          — approved Meta message templates
  WAConversation      — one thread per customer (keyed by wa_id / phone)
  WAMessage           — individual message (inbound or outbound)
  WAMediaFile         — uploaded media (image, PDF, voice, video)
  WAWebhookLog        — raw webhook payloads (immutable audit)
  WAMessageQueue      — outbound retry queue

Design rules:
  - wa_id is the WhatsApp-assigned phone number ID (e.g. "201001234567")
  - Plain phone numbers are normalised to international format on save
  - WAWebhookLog is IMMUTABLE — never edit, only create
  - All conversations are linked to a Customer when a phone match exists
  - 24-hour conversation window tracked on WAConversation.window_expires_at
  - Template messages are the only valid outbound type outside the window
"""
from django.db import models
from django.utils import timezone


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WATemplate — approved Meta message templates
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WATemplate(models.Model):

    CATEGORY_CHOICES = [
        ('marketing',       'تسويق'),
        ('utility',         'خدمة'),
        ('authentication',  'مصادقة / OTP'),
    ]

    STATUS_CHOICES = [
        ('pending',  'بانتظار الموافقة'),
        ('approved', 'معتمد'),
        ('rejected', 'مرفوض'),
        ('paused',   'موقوف'),
    ]

    name        = models.CharField(
        max_length=100, unique=True,
        verbose_name='اسم القالب',
        help_text='حروف صغيرة وشرطات فقط — يطابق اسم القالب في Meta',
    )
    language    = models.CharField(max_length=10, default='ar', verbose_name='اللغة')
    category    = models.CharField(
        max_length=20, choices=CATEGORY_CHOICES, default='utility',
        verbose_name='التصنيف',
    )
    status      = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='pending',
        verbose_name='الحالة',
    )

    # Template body — use {{1}}, {{2}} for variables (Meta format)
    body_text   = models.TextField(verbose_name='نص القالب')

    # Header (optional)
    header_type = models.CharField(
        max_length=10, blank=True,
        choices=[('text', 'نص'), ('image', 'صورة'), ('document', 'مستند'), ('video', 'فيديو')],
        verbose_name='نوع الرأس',
    )
    header_text = models.CharField(max_length=255, blank=True, verbose_name='نص الرأس')

    # Footer (optional)
    footer_text = models.CharField(max_length=255, blank=True, verbose_name='نص التذييل')

    # Variable mapping hint — JSON: {"1": "customer_name", "2": "item_name"}
    variable_map = models.JSONField(
        default=dict, blank=True,
        verbose_name='خريطة المتغيرات',
    )

    # Meta template ID returned after approval
    meta_template_id = models.CharField(max_length=100, blank=True, verbose_name='معرف Meta')

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name        = 'قالب واتساب'
        verbose_name_plural = 'قوالب واتساب'

    def __str__(self):
        return f'{self.name} [{self.language}] — {self.get_status_display()}'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WAConversation — one thread per customer / phone
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WAConversation(models.Model):

    STATUS_CHOICES = [
        ('open',     'مفتوحة'),
        ('pending',  'بانتظار رد'),
        ('resolved', 'محلولة'),
        ('closed',   'مغلقة'),
    ]

    # WhatsApp phone (international, no +, e.g. "201001234567")
    # Uniqueness is per company number: (account, wa_id) — the same customer
    # can hold separate threads with the call-center number and a branch number.
    wa_id       = models.CharField(
        max_length=30, db_index=True,
        verbose_name='رقم واتساب',
    )
    customer    = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='wa_conversations',
        verbose_name='العميل',
    )
    status      = models.CharField(
        max_length=10, choices=STATUS_CHOICES,
        default='open', db_index=True,
        verbose_name='الحالة',
    )

    # 24-hour service window — updated on every inbound message
    window_expires_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='انتهاء نافذة المحادثة',
    )

    # Assigned agent
    assigned_to = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='wa_conversations',
        verbose_name='موكل إلى',
    )

    # ── Omni unification layer (doc 15, Phase 0 — additive) ─────────────────
    # Which company WhatsApp number this thread belongs to.
    # Nullable: legacy single-number threads are backfilled by backfill_omni.
    account = models.ForeignKey(
        'omni.ChannelAccount',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='wa_conversations',
        verbose_name='حساب واتساب',
    )
    # The customer-grouped umbrella conversation this thread feeds into.
    omni_conversation = models.ForeignKey(
        'omni.Conversation',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='wa_threads',
        verbose_name='المحادثة الموحدة',
    )

    # Quick summary of last message (for list views)
    last_message_preview = models.CharField(max_length=255, blank=True)
    last_message_at      = models.DateTimeField(null=True, blank=True, db_index=True)
    unread_count         = models.PositiveSmallIntegerField(default=0)

    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_message_at']
        verbose_name        = 'محادثة واتساب'
        verbose_name_plural = 'محادثات واتساب'
        indexes = [
            models.Index(fields=['status', 'last_message_at']),
            models.Index(fields=['customer', 'status']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'wa_id'],
                name='uniq_wa_thread_per_account',
            ),
        ]

    def __str__(self):
        name = self.customer.name if self.customer else self.wa_id
        return f'[واتساب] {name} — {self.get_status_display()}'

    @property
    def window_open(self) -> bool:
        """True if the 24-hour customer service window is still valid."""
        if not self.window_expires_at:
            return False
        return timezone.now() < self.window_expires_at

    def refresh_window(self):
        """Called on every inbound message — extends the 24-hour window."""
        from datetime import timedelta
        self.window_expires_at = timezone.now() + timedelta(hours=24)
        self.save(update_fields=['window_expires_at', 'updated_at'])

    def _try_match_customer(self):
        if self.customer_id or not self.wa_id:
            return
        try:
            from apps.customers.models import Customer
            tail = self.wa_id.strip()[-9:]
            c = (
                Customer.objects.filter(phone__endswith=tail).first()
                or Customer.objects.filter(phone_alt__endswith=tail).first()
            )
            if c:
                self.customer = c
        except Exception:
            pass

    def save(self, *args, **kwargs):
        if not self.customer_id:
            self._try_match_customer()
        super().save(*args, **kwargs)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WAMessage — individual message in a conversation
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WAMessage(models.Model):

    DIRECTION_CHOICES = [
        ('inbound',  'وارد'),
        ('outbound', 'صادر'),
    ]

    TYPE_CHOICES = [
        ('text',      'نص'),
        ('image',     'صورة'),
        ('document',  'مستند'),
        ('audio',     'صوت'),
        ('video',     'فيديو'),
        ('location',  'موقع'),
        ('template',  'قالب'),
        ('otp',       'OTP'),
        ('sticker',   'ملصق'),
        ('reaction',  'تفاعل'),
        ('order',     'طلب'),
    ]

    STATUS_CHOICES = [
        ('pending',    'قيد الإرسال'),
        ('sent',       'أُرسل'),
        ('delivered',  'وصل'),
        ('read',       'قُرئ'),
        ('failed',     'فشل'),
    ]

    conversation = models.ForeignKey(
        WAConversation,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='المحادثة',
    )
    direction    = models.CharField(
        max_length=10, choices=DIRECTION_CHOICES, db_index=True,
        verbose_name='الاتجاه',
    )
    message_type = models.CharField(
        max_length=10, choices=TYPE_CHOICES, default='text',
        verbose_name='نوع الرسالة',
    )
    status       = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='pending',
        verbose_name='الحالة',
    )

    # Meta message ID (wamid) — returned by Cloud API / webhook
    wamid        = models.CharField(
        max_length=200, blank=True, db_index=True,
        verbose_name='معرف الرسالة (Meta)',
    )

    # Content
    body         = models.TextField(blank=True, verbose_name='نص الرسالة')

    # Media reference (for image/document/audio/video)
    media        = models.ForeignKey(
        'WAMediaFile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='messages',
        verbose_name='الوسائط',
    )

    # For template messages
    template     = models.ForeignKey(
        WATemplate,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='messages',
        verbose_name='القالب المستخدم',
    )
    template_variables = models.JSONField(
        default=list, blank=True,
        verbose_name='متغيرات القالب',
        help_text='[{"type":"text","text":"قيمة"}]',
    )

    # Location payload
    location_lat = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    location_lng = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    location_name = models.CharField(max_length=255, blank=True)

    # Error details for failed sends
    error_code    = models.CharField(max_length=20, blank=True)
    error_message = models.TextField(blank=True)
    retry_count   = models.PositiveSmallIntegerField(default=0)

    # Who sent it (for outbound)
    sent_by       = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='wa_messages_sent',
        verbose_name='أُرسل بواسطة',
    )

    # Timestamps
    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)
    sent_at       = models.DateTimeField(null=True, blank=True)
    delivered_at  = models.DateTimeField(null=True, blank=True)
    read_at       = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        verbose_name        = 'رسالة واتساب'
        verbose_name_plural = 'رسائل واتساب'
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['wamid']),
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        preview = self.body[:60] or f'[{self.get_message_type_display()}]'
        return f'[{self.get_direction_display()}] {preview}'

    def mark_delivered(self):
        if self.status not in ('delivered', 'read'):
            self.status = 'delivered'
            self.delivered_at = timezone.now()
            self.save(update_fields=['status', 'delivered_at'])

    def mark_read(self):
        if self.status != 'read':
            self.status = 'read'
            self.read_at = timezone.now()
            self.save(update_fields=['status', 'read_at'])

    def mark_failed(self, code='', message=''):
        self.status = 'failed'
        self.error_code = code
        self.error_message = message
        self.save(update_fields=['status', 'error_code', 'error_message'])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WAMediaFile — uploaded media reference
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WAMediaFile(models.Model):

    TYPE_CHOICES = [
        ('image',    'صورة'),
        ('document', 'مستند'),
        ('audio',    'صوت'),
        ('video',    'فيديو'),
        ('sticker',  'ملصق'),
    ]

    # Meta media ID — used to send the media again without re-uploading
    meta_media_id = models.CharField(
        max_length=200, blank=True, db_index=True,
        verbose_name='معرف الوسائط (Meta)',
    )
    file_type     = models.CharField(max_length=10, choices=TYPE_CHOICES, verbose_name='النوع')
    mime_type     = models.CharField(max_length=100, blank=True, verbose_name='MIME')
    file_name     = models.CharField(max_length=255, blank=True)
    file_size     = models.PositiveIntegerField(default=0, verbose_name='الحجم (بايت)')

    # Local storage (optional — inbound media downloaded from Meta)
    local_file    = models.FileField(
        upload_to='whatsapp/media/%Y/%m/',
        null=True, blank=True,
        verbose_name='الملف المحلي',
    )

    # SHA256 of file content (deduplication)
    sha256        = models.CharField(max_length=64, blank=True, db_index=True)

    uploaded_by   = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        verbose_name='رُفع بواسطة',
    )
    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name        = 'ملف وسائط واتساب'
        verbose_name_plural = 'ملفات وسائط واتساب'

    def __str__(self):
        return f'{self.get_file_type_display()} — {self.file_name or self.meta_media_id}'


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WAWebhookLog — raw Meta webhook payload (IMMUTABLE audit)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WAWebhookLog(models.Model):

    OBJECT_CHOICES = [
        ('whatsapp_business_account', 'WhatsApp Business Account'),
        ('other', 'أخرى'),
    ]

    received_at  = models.DateTimeField(auto_now_add=True, db_index=True)
    object_type  = models.CharField(max_length=50, blank=True, verbose_name='نوع الكائن')
    entry_id     = models.CharField(max_length=100, blank=True, db_index=True, verbose_name='معرف Entry')
    phone_number_id = models.CharField(max_length=50, blank=True, verbose_name='Phone Number ID')

    # Raw payload exactly as received from Meta
    payload      = models.JSONField(verbose_name='البيانات الخام')

    # Processing result
    processed    = models.BooleanField(default=False, db_index=True, verbose_name='تمت المعالجة')
    processing_error = models.TextField(blank=True, verbose_name='خطأ المعالجة')

    # Linked message (set after processing)
    wa_message   = models.ForeignKey(
        WAMessage,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='webhook_logs',
        verbose_name='الرسالة المرتبطة',
    )

    class Meta:
        ordering = ['-received_at']
        verbose_name        = 'سجل Webhook واتساب'
        verbose_name_plural = 'سجلات Webhook واتساب'

    def __str__(self):
        return f'Webhook {self.received_at:%Y-%m-%d %H:%M:%S} — processed={self.processed}'

    # Immutability guard
    def save(self, *args, **kwargs):
        if self.pk:
            # Only allow flipping processed flag and linking wa_message
            kwargs.setdefault('update_fields', ['processed', 'processing_error', 'wa_message'])
        super().save(*args, **kwargs)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WAMessageQueue — outbound retry queue
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class WAMessageQueue(models.Model):

    PRIORITY_CHOICES = [
        (1, 'عاجل (OTP / تأكيد توصيل)'),
        (2, 'مرتفع (إشعار حجز)'),
        (3, 'عادي (حملة تسويقية)'),
    ]

    STATUS_CHOICES = [
        ('pending',    'بانتظار الإرسال'),
        ('processing', 'قيد المعالجة'),
        ('sent',       'أُرسل'),
        ('failed',     'فشل نهائي'),
    ]

    conversation   = models.ForeignKey(
        WAConversation,
        on_delete=models.CASCADE,
        related_name='queue_items',
        verbose_name='المحادثة',
    )
    priority       = models.PositiveSmallIntegerField(
        choices=PRIORITY_CHOICES, default=3, db_index=True,
        verbose_name='الأولوية',
    )
    status         = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default='pending', db_index=True,
    )

    # Message payload — same structure as WAMessage fields
    message_type   = models.CharField(max_length=10, default='text')
    body           = models.TextField(blank=True)
    template_name  = models.CharField(max_length=100, blank=True)
    template_vars  = models.JSONField(default=list, blank=True)
    media_id       = models.ForeignKey(
        WAMediaFile, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='queue_items',
    )

    # Retry tracking
    attempts       = models.PositiveSmallIntegerField(default=0)
    max_attempts   = models.PositiveSmallIntegerField(default=3)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_error     = models.TextField(blank=True)

    # Result
    wa_message     = models.OneToOneField(
        WAMessage,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='queue_item',
        verbose_name='الرسالة المُنشأة',
    )

    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'next_attempt_at']
        verbose_name        = 'عنصر قائمة الإرسال'
        verbose_name_plural = 'قائمة الإرسال'
        indexes = [
            models.Index(fields=['status', 'next_attempt_at']),
        ]

    def __str__(self):
        return f'Queue [{self.get_priority_display()}] {self.conversation.wa_id} — {self.status}'
