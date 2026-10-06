"""
apps/campaigns/models.py

WhatsApp Campaign system with approval queue.

  WhatsAppCampaign  — campaign definition, target filter, message template
  CampaignMessage   — per-customer message with delivery tracking

State machine:
  draft → pending_approval → approved → scheduled → running → completed
                          ↓
                       rejected  (back to draft for editing)
"""
import re
from django.db import models
from django.utils import timezone


class WhatsAppCampaign(models.Model):

    STATUS_CHOICES = [
        ('draft',            'مسودة'),
        ('pending_approval', 'بانتظار الموافقة'),
        ('approved',         'معتمدة'),
        ('scheduled',        'مجدولة'),
        ('running',          'جارية'),
        ('paused',           'موقوفة'),
        ('completed',        'مكتملة'),
        ('cancelled',        'ملغاة'),
        ('rejected',         'مرفوضة'),
    ]

    name        = models.CharField(max_length=255, verbose_name='اسم الحملة')
    description = models.TextField(blank=True, verbose_name='وصف')
    status      = models.CharField(
        max_length=20, choices=STATUS_CHOICES,
        default='draft', db_index=True,
        verbose_name='الحالة',
    )

    # ── Message template ──────────────────────────────────────────────────────
    # Supports: {{customer_name}}, {{item_name}}, {{branch_name}}, {{phone}}
    message_template = models.TextField(
        verbose_name='نص الرسالة',
        help_text='متغيرات: {{customer_name}}, {{item_name}}, {{branch_name}}',
    )

    # ── Target audience filter ────────────────────────────────────────────────
    # JSON object — keys (all optional):
    #   segment: list[str]                e.g. ["vip","loyal"]
    #   chronic_category: str             e.g. "ضغط الدم"
    #   last_purchase_days_max: int       e.g. 90  (bought in last N days)
    #   last_purchase_days_min: int       e.g. 30  (not bought in last N days)
    #   item_id: int                      customers who ever bought this item
    #   branch_id: int                    preferred branch filter
    #   min_ltv: float                    minimum lifetime value
    target_filter = models.JSONField(
        default=dict, blank=True,
        verbose_name='فلتر الجمهور',
    )

    # ── Optional linked item (for personalised messages) ─────────────────────
    featured_item = models.ForeignKey(
        'catalog.Item',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='campaigns',
        verbose_name='الصنف المميز',
    )

    # ── Schedule ──────────────────────────────────────────────────────────────
    scheduled_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name='موعد الإرسال',
        help_text='فارغ = إرسال يدوي فور الموافقة',
    )

    # ── Counters (denormalised for perf) ─────────────────────────────────────
    estimated_reach      = models.PositiveIntegerField(default=0, verbose_name='الوصول المقدَّر')
    messages_queued      = models.PositiveIntegerField(default=0, verbose_name='رسائل في الانتظار')
    messages_sent        = models.PositiveIntegerField(default=0, verbose_name='رسائل مُرسَلة')
    messages_delivered   = models.PositiveIntegerField(default=0, verbose_name='رسائل مُسلَّمة')
    messages_failed      = models.PositiveIntegerField(default=0, verbose_name='رسائل فاشلة')

    # ── People ────────────────────────────────────────────────────────────────
    created_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='campaigns_created',
        verbose_name='أنشئ بواسطة',
    )
    approved_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='campaigns_approved',
        verbose_name='اعتمد بواسطة',
    )
    rejected_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='campaigns_rejected',
        verbose_name='رفض بواسطة',
    )
    rejection_reason = models.TextField(blank=True, verbose_name='سبب الرفض')

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    approved_at  = models.DateTimeField(null=True, blank=True)
    queued_at    = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'حملة واتساب'
        verbose_name_plural = 'حملات واتساب'

    def __str__(self):
        return f'{self.name} [{self.get_status_display()}]'

    # ── Helpers ───────────────────────────────────────────────────────────────

    def render_message(self, customer, item=None):
        """Render template variables for a specific customer."""
        branch_name = (
            customer.preferred_branch.name_ar
            if customer.preferred_branch_id else ''
        )
        item_obj = item or self.featured_item
        msg = self.message_template
        msg = msg.replace('{{customer_name}}', customer.name or '')
        msg = msg.replace('{{item_name}}',     item_obj.name if item_obj else '')
        msg = msg.replace('{{branch_name}}',   branch_name)
        msg = msg.replace('{{phone}}',         customer.phone or '')
        return msg.strip()

    @staticmethod
    def build_whatsapp_url(phone: str, message: str) -> str:
        """Build wa.me URL with URL-encoded message."""
        import urllib.parse
        clean = re.sub(r'[^\d+]', '', phone)
        if clean.startswith('0'):
            clean = '20' + clean[1:]
        return f'https://wa.me/{clean}?text={urllib.parse.quote(message)}'

    def can_request_approval(self):
        return self.status == 'draft' and bool(self.message_template.strip())

    def can_approve(self):
        return self.status == 'pending_approval'

    def can_queue(self):
        return self.status == 'approved'

    def can_cancel(self):
        return self.status in ('draft', 'pending_approval', 'approved', 'scheduled', 'paused')

    @property
    def delivery_rate(self):
        if not self.messages_sent:
            return None
        return round(self.messages_delivered / self.messages_sent * 100, 1)


class CampaignMessage(models.Model):
    """One outbound WhatsApp message for a specific customer within a campaign."""

    STATUS_CHOICES = [
        ('pending',   'في الانتظار'),
        ('sent',      'مُرسَلة'),
        ('delivered', 'مُسلَّمة'),
        ('failed',    'فاشلة'),
        ('opted_out', 'مرفوضة من العميل'),
        ('skipped',   'تم التخطي'),
    ]

    campaign     = models.ForeignKey(
        WhatsAppCampaign,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='الحملة',
    )
    customer     = models.ForeignKey(
        'customers.Customer',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='campaign_messages',
        verbose_name='العميل',
    )
    phone_number  = models.CharField(max_length=30, verbose_name='رقم الهاتف')
    customer_name = models.CharField(max_length=255, blank=True, verbose_name='اسم العميل')
    message_text  = models.TextField(verbose_name='نص الرسالة المُخصَّص')
    whatsapp_url  = models.TextField(blank=True, verbose_name='رابط واتساب')

    status       = models.CharField(
        max_length=10, choices=STATUS_CHOICES,
        default='pending', db_index=True,
        verbose_name='حالة التسليم',
    )

    sent_at      = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at    = models.DateTimeField(null=True, blank=True)
    error_message = models.CharField(max_length=500, blank=True)

    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'رسالة حملة'
        verbose_name_plural = 'رسائل الحملات'
        indexes = [
            models.Index(fields=['campaign', 'status']),
            models.Index(fields=['campaign', 'customer']),
        ]

    def __str__(self):
        return f'{self.campaign.name} → {self.phone_number} [{self.get_status_display()}]'

    def mark_sent(self):
        self.status  = 'sent'
        self.sent_at = timezone.now()
        self.save(update_fields=['status', 'sent_at'])

    def mark_delivered(self):
        self.status       = 'delivered'
        self.delivered_at = timezone.now()
        self.save(update_fields=['status', 'delivered_at'])

    def mark_failed(self, reason=''):
        self.status        = 'failed'
        self.failed_at     = timezone.now()
        self.error_message = reason[:500]
        self.save(update_fields=['status', 'failed_at', 'error_message'])
