"""
apps/omni/serializers.py
"""
from rest_framework import serializers

from apps.omni.models import (
    AutomationRule, AutomationRun, ChannelAccount, Conversation, TimelineEvent,
)


class ChannelAccountSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    supervisor_name = serializers.CharField(source='supervisor.full_name', read_only=True, default=None)

    # Credentials: write-only in, never out. has_credentials tells the UI
    # whether per-account credentials exist (vs env fallback).
    credentials_input = serializers.DictField(
        write_only=True, required=False,
        help_text="{'token': '...', 'phone_number_id': '...'} — تُشفَّر عند الحفظ",
    )
    has_credentials = serializers.SerializerMethodField()

    # Live thread/message stats — per-object queries (account list is small;
    # avoids the multi-join aggregation inflation trap)
    stats = serializers.SerializerMethodField()

    class Meta:
        model = ChannelAccount
        # the raw credentials field is deliberately excluded — never serialized
        fields = [
            'id', 'channel', 'name', 'phone_or_handle', 'provider_ref', 'is_default',
            'branch', 'branch_name', 'department', 'provider', 'status',
            'last_heartbeat_at', 'health', 'working_hours',
            'supervisor', 'supervisor_name', 'is_active',
            'credentials_input', 'has_credentials', 'stats',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_has_credentials(self, obj):
        return bool(obj.credentials)

    def get_stats(self, obj):
        if obj.channel != 'whatsapp':
            return {'threads': 0, 'messages_today': 0, 'inbound_today': 0, 'unread': 0}
        from django.db.models import Sum
        from django.utils import timezone as tz
        from apps.whatsapp.models import WAMessage

        today = tz.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        threads = obj.wa_conversations.all()
        msgs_today = WAMessage.objects.filter(
            conversation__account=obj, created_at__gte=today)
        return {
            'threads': threads.count(),
            'messages_today': msgs_today.count(),
            'inbound_today': msgs_today.filter(direction='inbound').count(),
            'unread': threads.aggregate(t=Sum('unread_count'))['t'] or 0,
        }

    def create(self, validated_data):
        creds = validated_data.pop('credentials_input', None)
        account = super().create(validated_data)
        if creds:
            account.set_credentials(creds)
            account.save(update_fields=['credentials', 'updated_at'])
        return account

    def update(self, instance, validated_data):
        creds = validated_data.pop('credentials_input', None)
        account = super().update(instance, validated_data)
        if creds is not None:
            # Empty dict clears credentials (back to env fallback)
            account.set_credentials(creds)
            account.save(update_fields=['credentials', 'updated_at'])
        return account


class ConversationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source='customer.name', read_only=True, default=None)
    customer_phone = serializers.CharField(source='customer.phone', read_only=True, default=None)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True, default=None)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default=None)
    # Channel thread info (for reply routing + 24h window indicators)
    wa_thread = serializers.SerializerMethodField()
    social_thread = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'customer', 'customer_name', 'customer_phone', 'contact_phone',
            'status', 'priority', 'branch', 'branch_name',
            'assigned_to', 'assigned_to_name', 'subject', 'created_from_channel',
            'first_inbound_at', 'last_activity_at', 'last_event_preview',
            'wa_thread', 'social_thread', 'created_at',
        ]
        read_only_fields = [
            'customer_name', 'customer_phone', 'first_inbound_at',
            'last_activity_at', 'last_event_preview', 'created_at',
        ]

    def get_wa_thread(self, obj):
        thread = obj.wa_threads.order_by('-last_message_at').first()
        if thread is None:
            return None
        return {
            'id': thread.pk,
            'wa_id': thread.wa_id,
            'window_open': thread.window_open,
            'window_expires_at': thread.window_expires_at,
        }

    def get_social_thread(self, obj):
        thread = (
            obj.social_threads.select_related('account')
            .order_by('-last_message_at').first()
        )
        if thread is None:
            return None
        return {
            'id': thread.pk,
            'channel': thread.account.channel,
            'display_name': thread.display_name,
            'window_open': thread.window_open,
        }


class TimelineEventSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source='actor.full_name', read_only=True, default=None)
    native_model = serializers.SerializerMethodField()
    recording = serializers.SerializerMethodField()

    class Meta:
        model = TimelineEvent
        fields = [
            'id', 'event_type', 'channel', 'account', 'summary',
            'actor', 'actor_name', 'occurred_at', 'payload',
            'native_model', 'object_id', 'recording',
        ]

    def get_native_model(self, obj):
        # e.g. "whatsapp.wamessage" — lets the UI deep-link to the native record
        if obj.content_type_id is None:
            return None
        return f'{obj.content_type.app_label}.{obj.content_type.model}'

    def get_recording(self, obj):
        """
        Playback URL for call events — resolved at serialization time
        (tokenized proxy for Asterisk files; <audio> tags cannot send JWT).
        """
        if obj.event_type not in ('call', 'call_missed'):
            return None
        # External URL captured at ingestion time wins
        url = (obj.payload or {}).get('recording_url')
        if url:
            return url
        try:
            log = obj.native  # callcenter.CallLog
            session = getattr(log, 'pbx_session', None)
            if session is None:
                return None
            from apps.pbx import recordings
            if not recordings.session_has_recording(session):
                return None
            return recordings.signed_recording_url(session.pk)
        except Exception:
            return None


class ReplySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4096)


class AutomationRuleSerializer(serializers.ModelSerializer):
    trigger_display = serializers.CharField(source='get_trigger_display', read_only=True)

    class Meta:
        model = AutomationRule
        fields = [
            'id', 'name', 'trigger', 'trigger_display', 'conditions', 'actions',
            'is_active', 'stop_processing', 'order', 'run_count', 'last_run_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['run_count', 'last_run_at', 'created_at', 'updated_at']


class AutomationRunSerializer(serializers.ModelSerializer):
    rule_name = serializers.CharField(source='rule.name', read_only=True)

    class Meta:
        model = AutomationRun
        fields = ['id', 'rule', 'rule_name', 'conversation', 'matched',
                  'actions_run', 'error', 'created_at']
