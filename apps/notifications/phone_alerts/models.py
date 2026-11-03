import secrets

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .events import EVENT_CHOICES


def _new_token():
    return secrets.token_urlsafe(16)


class PhoneAlertPolicy(models.Model):
    """Per-event switch: never / optional (requester ticks the box) / always."""
    MODE_CHOICES = [('never', 'لا'), ('optional', 'اختياري'), ('always', 'دائماً')]

    event = models.CharField(max_length=40, unique=True, choices=EVENT_CHOICES)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default='optional')
    remind_after_min = models.PositiveIntegerField(default=15)
    escalate_after_min = models.PositiveIntegerField(default=30)
    max_reminders = models.PositiveIntegerField(default=2)
    escalate_to = models.ManyToManyField('users.StaffProfile', blank=True,
                                         related_name='phone_alert_escalations')
    updated_by = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'سياسة تنبيه الموبايل'
        verbose_name_plural = 'سياسات تنبيه الموبايل'

    def __str__(self):
        return f'{self.event}: {self.mode}'

    @classmethod
    def for_event(cls, key):
        return cls.objects.filter(event=key).first()


class WorkOwner(models.Model):
    """Who owns a piece of work (e.g. sourcing reservations, dispatching HQ transfers)."""
    KIND_CHOICES = [('reservation_sourcing', 'توفير الحجوزات'),
                    ('hq_transfer_dispatch', 'صرف تحويلات المخزن الرئيسي')]

    kind = models.CharField(max_length=30, choices=KIND_CHOICES)
    staff = models.ForeignKey('users.StaffProfile', on_delete=models.CASCADE, related_name='work_owner_rows')
    branch = models.ForeignKey('branches.Branch', null=True, blank=True, on_delete=models.CASCADE,
                               related_name='+')
    is_escalation = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'مسؤول عمل'
        verbose_name_plural = 'مسؤولو العمل'

    def __str__(self):
        return f'{self.kind} → {self.staff_id}'


class PhoneAlert(models.Model):
    STATUS_CHOICES = [('queued', 'في الانتظار'), ('sent', 'أُرسل'), ('delivered', 'وصل'),
                      ('read', 'قُرئ'), ('acknowledged', 'تم الاستلام'), ('escalated', 'تم التصعيد'),
                      ('expired', 'انتهى'), ('failed', 'فشل')]
    KIND_CHOICES = [('alert', 'تنبيه'), ('brief', 'ملخص')]

    # Plain CharField on purpose: brief/expiry rows need keys that are not policy events.
    event = models.CharField(max_length=40)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default='alert')
    notification = models.ForeignKey('notifications.Notification', null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name='phone_alerts')
    source_ct = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL,
                                  related_name='+')
    source_id = models.PositiveIntegerField(null=True, blank=True)
    source = GenericForeignKey('source_ct', 'source_id')
    recipient_staff = models.ForeignKey('users.StaffProfile', null=True, blank=True,
                                        on_delete=models.SET_NULL, related_name='phone_alerts')
    phone = models.CharField(max_length=20)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='queued')
    token = models.CharField(max_length=32, unique=True, default=_new_token)
    wa_message_id = models.CharField(max_length=100, blank=True, default='')
    ack_at = models.DateTimeField(null=True, blank=True)
    remark = models.TextField(blank=True, default='')
    reminders_sent = models.PositiveIntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalation_of = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL,
                                      related_name='escalations')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'last_sent_at'], name='pa_status_lastsent_idx'),
            models.Index(fields=['source_ct', 'source_id'], name='pa_source_idx'),
        ]
        verbose_name = 'تنبيه موبايل'
        verbose_name_plural = 'تنبيهات الموبايل'

    def __str__(self):
        return f'{self.event} → {self.phone} [{self.status}]'


class PhoneAlertAttempt(models.Model):
    CHANNEL_CHOICES = [('whatsapp', 'واتساب'), ('sms', 'SMS')]
    RESULT_CHOICES = [('sent', 'sent'), ('dry_run', 'dry_run'), ('failed', 'failed'),
                      ('delivered', 'delivered'), ('read', 'read')]

    alert = models.ForeignKey(PhoneAlert, on_delete=models.CASCADE, related_name='attempts')
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES, default='whatsapp')
    result = models.CharField(max_length=10, choices=RESULT_CHOICES)
    provider_message_id = models.CharField(max_length=100, blank=True, default='')
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
