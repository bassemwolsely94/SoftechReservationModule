"""
apps/notifications/serializers.py

NotificationSerializer     — full notification payload (used in REST + WS push)
ChatterMessageSerializer   — chatter message payload (used in REST + WS push)
NotificationLogSerializer  — delivery / read audit row
"""
from rest_framework import serializers
from .models import Notification, NotificationLog, ChatterMessage, PersonalReminder


# ── Notification ──────────────────────────────────────────────────────────────

class NotificationSerializer(serializers.ModelSerializer):
    type_icon  = serializers.CharField(read_only=True)
    type_label = serializers.SerializerMethodField()
    time_ago   = serializers.SerializerMethodField()
    alarm_tier = serializers.CharField(read_only=True)

    def get_type_label(self, obj):
        label = dict(Notification.NOTIFICATION_TYPES).get(obj.notification_type, '')
        parts = label.split(' ', 1)
        return parts[1] if len(parts) > 1 else label

    def get_time_ago(self, obj):
        from django.utils import timezone
        from django.utils.timesince import timesince
        now  = timezone.now()
        diff = now - obj.created_at
        if diff.total_seconds() < 60:
            return 'الآن'
        return f'منذ {timesince(obj.created_at, now)}'

    class Meta:
        model  = Notification
        fields = [
            'id',
            'notification_type', 'type_icon', 'type_label',
            'category', 'alarm_tier',
            'priority',
            'title', 'body',
            'is_read',
            'reservation',
            'transfer_request_id_ref',
            'demand_id_ref',
            'chatter_message_id_ref',
            'created_at', 'time_ago',
        ]
        read_only_fields = ['created_at', 'category']


# ── Chatter ───────────────────────────────────────────────────────────────────

class ChatterMessageSerializer(serializers.ModelSerializer):
    author_name    = serializers.SerializerMethodField()
    author_avatar  = serializers.SerializerMethodField()
    time_ago       = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()
    voice_note_url = serializers.SerializerMethodField()

    def get_author_name(self, obj):
        return obj.author.full_name if obj.author_id else 'مجهول'

    def get_author_avatar(self, obj):
        """Return initials — front-end renders them as a coloured avatar."""
        name = self.get_author_name(obj)
        parts = name.split()
        if len(parts) >= 2:
            return parts[0][0] + parts[-1][0]
        return name[:2] if name else '??'

    def get_time_ago(self, obj):
        from django.utils import timezone
        from django.utils.timesince import timesince
        now  = timezone.now()
        diff = now - obj.created_at
        if diff.total_seconds() < 60:
            return 'الآن'
        return f'منذ {timesince(obj.created_at, now)}'

    def get_attachment_url(self, obj):
        """Return absolute URL for attachment, or None."""
        if not obj.attachment:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.attachment.url)
        return obj.attachment.url

    def get_voice_note_url(self, obj):
        """Return absolute URL for the dedicated voice note, or None."""
        if not obj.voice_note:
            return None
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(obj.voice_note.url)
        return obj.voice_note.url

    class Meta:
        model  = ChatterMessage
        fields = [
            'id',
            'model_name', 'record_id',
            'author', 'author_name', 'author_avatar',
            'message',
            'attachment', 'attachment_url', 'file_type',
            'voice_note', 'voice_note_url',
            'created_at', 'time_ago',
        ]
        read_only_fields = ['created_at', 'author', 'attachment_url', 'voice_note_url']


# ── Notification Log ──────────────────────────────────────────────────────────

class NotificationLogSerializer(serializers.ModelSerializer):
    notification_title = serializers.CharField(
        source='notification.title', read_only=True
    )
    notification_type = serializers.CharField(
        source='notification.notification_type', read_only=True
    )
    recipient_name = serializers.SerializerMethodField()

    def get_recipient_name(self, obj):
        return obj.recipient.full_name if obj.recipient_id else '—'

    class Meta:
        model  = NotificationLog
        fields = [
            'id',
            'notification', 'notification_title', 'notification_type',
            'recipient', 'recipient_name',
            'delivered_at', 'read_at',
        ]
        read_only_fields = ['delivered_at']


# ── Personal reminders ──────────────────────────────────────────────────────────

class PersonalReminderSerializer(serializers.ModelSerializer):
    time_until = serializers.SerializerMethodField()

    def get_time_until(self, obj):
        from django.utils import timezone
        from django.utils.timesince import timeuntil
        if obj.is_fired or not obj.remind_at:
            return ''
        now = timezone.now()
        if obj.remind_at <= now:
            return 'الآن'
        return f'بعد {timeuntil(obj.remind_at, now)}'

    class Meta:
        model  = PersonalReminder
        fields = [
            'id', 'title', 'note', 'remind_at', 'time_until',
            'is_fired', 'fired_at',
            'reservation', 'demand_id_ref', 'transfer_request_id_ref',
            'created_at',
        ]
        read_only_fields = ['is_fired', 'fired_at', 'created_at']


# ── Announcements ───────────────────────────────────────────────────────────────

from .models import Announcement   # noqa: E402

class AnnouncementSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    time_ago    = serializers.SerializerMethodField()
    # Per-request reader context (set by the view)
    is_read     = serializers.SerializerMethodField()
    read_count  = serializers.SerializerMethodField()
    audience_count = serializers.SerializerMethodField()

    def get_author_name(self, obj):
        return obj.author.full_name if obj.author_id else 'النظام'

    def get_time_ago(self, obj):
        from django.utils import timezone
        from django.utils.timesince import timesince
        diff = timezone.now() - obj.created_at
        return 'الآن' if diff.total_seconds() < 60 else f'منذ {timesince(obj.created_at, timezone.now())}'

    def get_is_read(self, obj):
        ids = self.context.get('read_ids')
        return obj.id in ids if ids is not None else None

    def get_read_count(self, obj):
        # Only meaningful for the author/admin stats view.
        return getattr(obj, '_read_count', None)

    def get_audience_count(self, obj):
        return getattr(obj, '_audience_count', None)

    class Meta:
        model  = Announcement
        fields = [
            'id', 'title', 'body', 'author', 'author_name',
            'audience_roles', 'audience_branch_ids',
            'priority', 'is_pinned', 'expires_at', 'created_at',
            'time_ago', 'is_read', 'read_count', 'audience_count',
        ]
        read_only_fields = ['author', 'created_at']
