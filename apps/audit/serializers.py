from rest_framework import serializers
from .models import AuditLog, AbuseFlag


class AuditLogSerializer(serializers.ModelSerializer):
    action_label    = serializers.CharField(source='get_action_display', read_only=True)
    user_display    = serializers.SerializerMethodField()

    def get_user_display(self, obj):
        return obj.user_name or (obj.user.full_name if obj.user else 'النظام')

    class Meta:
        model  = AuditLog
        fields = [
            'id', 'action', 'action_label',
            'user', 'user_display', 'user_name', 'user_role', 'ip_address',
            'model_name', 'object_id', 'object_repr',
            'old_data', 'new_data', 'changes', 'extra',
            'note', 'created_at',
        ]


class AbuseFlagListSerializer(serializers.ModelSerializer):
    staff_name   = serializers.CharField(source='staff.full_name',        read_only=True)
    staff_branch = serializers.CharField(source='staff.branch_name',      read_only=True)
    flag_label   = serializers.CharField(source='get_flag_type_display',  read_only=True)
    severity_label = serializers.CharField(source='get_severity_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display',     read_only=True)

    class Meta:
        model  = AbuseFlag
        fields = [
            'id', 'staff', 'staff_name', 'staff_branch',
            'flag_type', 'flag_label', 'severity', 'severity_label',
            'status', 'status_label', 'count', 'description', 'detected_at',
        ]


class AbuseFlagSerializer(AbuseFlagListSerializer):
    reviewed_by_name = serializers.CharField(source='reviewed_by.full_name', read_only=True)

    class Meta(AbuseFlagListSerializer.Meta):
        fields = AbuseFlagListSerializer.Meta.fields + [
            'window_hours', 'evidence',
            'reviewed_by_name', 'review_note', 'reviewed_at',
        ]
