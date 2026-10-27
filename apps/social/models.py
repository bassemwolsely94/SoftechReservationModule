"""
apps/social/models.py

Social messaging channels (doc 15 Phase 3): Facebook Messenger, Instagram DM,
Telegram — and TikTok once API access is approved.

One generic model pair serves all social channels (the channel comes from the
owning omni.ChannelAccount) — deliberately NOT one model set per network.

Models:
  SocialThread     — one thread per (company account, external user)
  SocialMessage    — individual message (system of record for the channel)
  SocialWebhookLog — raw inbound payloads (immutable audit, same as WA/PBX)

Social identities have no phone number, so umbrella conversations are linked
through SocialThread.omni_conversation (never phone matching); an agent can
later attach the Customer manually from the inbox.
"""
from django.db import models
from django.utils import timezone


class SocialThread(models.Model):

    account = models.ForeignKey(
        'omni.ChannelAccount',
        on_delete=models.CASCADE,
        related_name='social_threads',
        verbose_name='حساب القناة',
    )
    # PSID (Messenger) / IGSID (Instagram) / chat_id (Telegram) / TikTok user id
    external_user_id = models.CharField(
        max_length=100, db_index=True,
        verbose_name='معرف المستخدم الخارجي',
    )
    display_name = models.CharField(max_length=255, blank=True, verbose_name='الاسم الظاهر')

    omni_conversation = models.ForeignKey(
        'omni.Conversation',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='social_threads',
        verbose_name='المحادثة الموحدة',
    )

    last_message_preview = models.CharField(max_length=255, blank=True)
    last_message_at      = models.DateTimeField(null=True, blank=True, db_index=True)
    # Messenger/Instagram enforce a 24-hour standard messaging window
    last_inbound_at      = models.DateTimeField(null=True, blank=True)
    unread_count         = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_message_at']
        verbose_name        = 'محادثة اجتماعية'
        verbose_name_plural = 'المحادثات الاجتماعية'
        constraints = [
            models.UniqueConstraint(
                fields=['account', 'external_user_id'],
                name='uniq_social_thread_per_account',
            ),
        ]

    def __str__(self):
        return f'[{self.account.get_channel_display()}] {self.display_name or self.external_user_id}'

    @property
    def window_open(self) -> bool:
        """Meta channels: 24h since last inbound. Telegram: always open."""
        if self.account.channel == 'telegram':
            return True
        if not self.last_inbound_at:
            return False
        return (timezone.now() - self.last_inbound_at).total_seconds() < 24 * 3600


class SocialMessage(models.Model):

    DIRECTION_CHOICES = [
        ('inbound',  'وارد'),
        ('outbound', 'صادر'),
    ]

    TYPE_CHOICES = [
        ('text',    'نص'),
        ('image',   'صورة'),
        ('audio',   'صوت'),
        ('video',   'فيديو'),
        ('file',    'ملف'),
        ('sticker', 'ملصق'),
        ('other',   'أخرى'),
    ]

    STATUS_CHOICES = [
        ('received', 'مُستلم'),
        ('sent',     'أُرسل'),
        ('failed',   'فشل'),
    ]

    thread = models.ForeignKey(
        SocialThread,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='المحادثة',
    )
    direction    = models.CharField(max_length=10, choices=DIRECTION_CHOICES, db_index=True)
    message_type = models.CharField(max_length=8, choices=TYPE_CHOICES, default='text')
    status       = models.CharField(max_length=10, choices=STATUS_CHOICES, default='received')

    body           = models.TextField(blank=True, verbose_name='النص')
    # Provider message id (Messenger mid / Telegram message_id) — dedup key
    external_id    = models.CharField(max_length=200, blank=True, db_index=True)
    attachment_url = models.URLField(max_length=1000, blank=True)

    sent_by = models.ForeignKey(
        'users.StaffProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='social_messages_sent',
    )
    error_message = models.TextField(blank=True)
    created_at    = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at']
        verbose_name        = 'رسالة اجتماعية'
        verbose_name_plural = 'الرسائل الاجتماعية'
        indexes = [
            models.Index(fields=['thread', 'created_at']),
            models.Index(fields=['external_id']),
        ]

    def __str__(self):
        return f'[{self.get_direction_display()}] {self.body[:50] or self.message_type}'


class SocialWebhookLog(models.Model):
    """Raw inbound webhook payload — IMMUTABLE audit (same pattern as WA/PBX)."""

    source      = models.CharField(
        max_length=12, db_index=True,
        choices=[('meta', 'Meta Graph'), ('telegram', 'Telegram'), ('tiktok', 'TikTok')],
    )
    payload     = models.JSONField()
    processed   = models.BooleanField(default=False, db_index=True)
    processing_error = models.TextField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-received_at']
        verbose_name        = 'سجل Webhook اجتماعي'
        verbose_name_plural = 'سجلات Webhook الاجتماعية'

    def save(self, *args, **kwargs):
        if self.pk:
            kwargs.setdefault('update_fields', ['processed', 'processing_error'])
        super().save(*args, **kwargs)
