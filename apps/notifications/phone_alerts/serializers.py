"""Admin API for phone alerts: output shapes and input validation (Arabic messages)."""
from rest_framework import serializers

from apps.users.models import StaffProfile
from core.sms import sms_number

from .events import EVENTS
from .models import PhoneAlert, PhoneAlertAttempt, PhoneAlertPolicy, WorkOwner
from .recipients import is_plausible_phone

BAD_PHONE = 'رقم الموبايل غير صحيح — اكتب رقماً مصرياً من 11 رقماً مثل 01012345678'


def mask_phone(phone):
    phone = str(phone or '')
    return ('…' + phone[-4:]) if phone else ''


def clean_phone(raw):
    """Normalised international digits, or raise a 400-ready ValidationError. Blank -> ''."""
    if not str(raw or '').strip():
        return ''
    phone = sms_number(raw)
    if not is_plausible_phone(phone):
        raise serializers.ValidationError(BAD_PHONE)
    return phone


class PolicySerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()
    escalate_to = serializers.PrimaryKeyRelatedField(
        many=True, required=False, queryset=StaffProfile.objects.all())
    escalate_to_names = serializers.SerializerMethodField()

    class Meta:
        model = PhoneAlertPolicy
        fields = ['id', 'event', 'label', 'mode', 'remind_after_min', 'escalate_after_min',
                  'max_reminders', 'escalate_to', 'escalate_to_names', 'updated_at']
        read_only_fields = ['id', 'event', 'updated_at']

    def get_label(self, obj):
        e = EVENTS.get(obj.event)
        return e.label_ar if e else obj.event

    def get_escalate_to_names(self, obj):
        return [s.full_name for s in obj.escalate_to.all()]

    def validate(self, attrs):
        cur = self.instance
        remind = attrs.get('remind_after_min', getattr(cur, 'remind_after_min', 15))
        esc = attrs.get('escalate_after_min', getattr(cur, 'escalate_after_min', 30))
        mx = attrs.get('max_reminders', getattr(cur, 'max_reminders', 2))
        if remind < 1:
            raise serializers.ValidationError({'remind_after_min': 'مدة التذكير يجب أن تكون دقيقة واحدة على الأقل'})
        if esc < 1:
            raise serializers.ValidationError({'escalate_after_min': 'مدة التصعيد يجب أن تكون دقيقة واحدة على الأقل'})
        if esc <= remind:
            raise serializers.ValidationError({'escalate_after_min': 'مدة التصعيد يجب أن تكون أكبر من مدة التذكير'})
        if not 0 <= mx <= 5:
            raise serializers.ValidationError({'max_reminders': 'عدد التذكيرات من 0 إلى 5'})
        return attrs


class OwnerSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.full_name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True, default='')
    kind_label = serializers.CharField(source='get_kind_display', read_only=True)

    class Meta:
        model = WorkOwner
        fields = ['id', 'kind', 'kind_label', 'staff', 'staff_name', 'branch', 'branch_name',
                  'is_escalation', 'active']


class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = PhoneAlertAttempt
        fields = ['id', 'channel', 'result', 'error', 'created_at']


class AlertLogSerializer(serializers.ModelSerializer):
    event_label = serializers.SerializerMethodField()
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    phone = serializers.SerializerMethodField()
    recipient_name = serializers.SerializerMethodField()
    source_text = serializers.SerializerMethodField()

    class Meta:
        model = PhoneAlert
        fields = ['id', 'event', 'event_label', 'kind', 'status', 'status_label', 'phone',
                  'recipient_staff', 'recipient_name', 'source_text', 'reminders_sent', 'ack_at',
                  'remark', 'escalated_at', 'created_at', 'last_sent_at']

    def get_event_label(self, obj):
        e = EVENTS.get(obj.event)
        return e.label_ar if e else ('تنبيه تجريبي' if obj.event == 'test' else obj.event)

    def get_phone(self, obj):
        return mask_phone(obj.phone) if self.context.get('mask_phone') else obj.phone

    def get_recipient_name(self, obj):
        return obj.recipient_staff.full_name if obj.recipient_staff_id else ''

    def get_source_text(self, obj):
        try:
            return str(obj.source)[:80] if obj.source is not None else ''
        except Exception:
            return ''


class AlertDetailSerializer(AlertLogSerializer):
    attempts = AttemptSerializer(many=True, read_only=True)

    class Meta(AlertLogSerializer.Meta):
        fields = AlertLogSerializer.Meta.fields + ['attempts', 'wa_message_id', 'escalation_of']
