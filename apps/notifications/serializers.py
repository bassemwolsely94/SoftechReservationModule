from rest_framework import serializers
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    type_icon = serializers.CharField(read_only=True)
    type_label = serializers.SerializerMethodField()
    time_ago = serializers.SerializerMethodField()

    def get_type_label(self, obj):
        label = dict(Notification.NOTIFICATION_TYPES).get(obj.notification_type, '')
        # Strip emoji prefix
        parts = label.split(' ', 1)
        return parts[1] if len(parts) > 1 else label

    def get_time_ago(self, obj):
        from django.utils import timezone
        from django.utils.timesince import timesince
        now = timezone.now()
        diff = now - obj.created_at
        if diff.total_seconds() < 60:
            return 'الآن'
        return f'منذ {timesince(obj.created_at, now)}'

    class Meta:
        model = Notification
        fields = [
            'id',
            'notification_type', 'type_icon', 'type_label',
            'title', 'body',
            'is_read',
            'reservation',
            'transfer_request_id_ref',
            'created_at', 'time_ago',
        ]
        read_only_fields = ['created_at']
