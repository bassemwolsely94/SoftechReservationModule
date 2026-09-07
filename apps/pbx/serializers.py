from rest_framework import serializers
from apps.pbx.models import AgentExtension, PBXQueue, CallSession, PBXEvent


def _staff_display_name(staff):
    """Return best available display name for a StaffProfile."""
    if not staff:
        return None
    full = staff.user.get_full_name() if staff.user_id else ''
    return full or staff.user.username if staff.user_id else str(staff.pk)


class AgentExtensionSerializer(serializers.ModelSerializer):
    staff_name = serializers.SerializerMethodField()

    class Meta:
        model = AgentExtension
        fields = ['id', 'staff', 'staff_name', 'extension', 'sip_peer', 'queue_name', 'is_active']

    def get_staff_name(self, obj):
        return _staff_display_name(obj.staff) if obj.staff_id else None


class PBXQueueSerializer(serializers.ModelSerializer):
    branch_name = serializers.SerializerMethodField()

    class Meta:
        model = PBXQueue
        fields = ['id', 'name', 'description', 'branch', 'branch_name', 'is_active']

    def get_branch_name(self, obj):
        return obj.branch.name_ar if obj.branch_id else None


class CallSessionSerializer(serializers.ModelSerializer):
    direction_display = serializers.CharField(source='get_direction_display', read_only=True)
    state_display     = serializers.CharField(source='get_state_display', read_only=True)
    customer_name     = serializers.SerializerMethodField()
    agent_name        = serializers.SerializerMethodField()
    queue_name        = serializers.SerializerMethodField()
    total_seconds     = serializers.IntegerField(read_only=True)

    class Meta:
        model = CallSession
        fields = [
            'id', 'unique_id', 'direction', 'direction_display',
            'state', 'state_display',
            'caller_number', 'caller_name', 'destination_ext',
            'queue', 'queue_name',
            'agent', 'agent_name',
            'customer', 'customer_name',
            'started_at', 'answered_at', 'ended_at',
            'wait_seconds', 'talk_seconds', 'total_seconds',
            'recording_url', 'call_log',
        ]

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer_id else None

    def get_agent_name(self, obj):
        if not obj.agent_id:
            return None
        return _staff_display_name(obj.agent.staff)

    def get_queue_name(self, obj):
        return obj.queue.name if obj.queue_id else None


class PBXEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = PBXEvent
        fields = ['id', 'event_type', 'unique_id', 'caller_id_num',
                  'extension', 'queue_name', 'received_at']
