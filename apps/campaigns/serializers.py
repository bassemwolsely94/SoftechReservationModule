"""
apps/campaigns/serializers.py
"""
from rest_framework import serializers
from .models import WhatsAppCampaign, CampaignMessage


class CampaignMessageSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = CampaignMessage
        fields = [
            'id', 'phone_number', 'customer_name', 'message_text',
            'whatsapp_url', 'status', 'status_label',
            'sent_at', 'delivered_at', 'failed_at', 'error_message',
            'created_at',
        ]
        read_only_fields = fields


class WhatsAppCampaignListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    status_label       = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name    = serializers.SerializerMethodField()
    approved_by_name   = serializers.SerializerMethodField()
    delivery_rate      = serializers.FloatField(read_only=True)
    featured_item_name = serializers.SerializerMethodField()

    class Meta:
        model = WhatsAppCampaign
        fields = [
            'id', 'name', 'description', 'status', 'status_label',
            'scheduled_at', 'estimated_reach',
            'messages_queued', 'messages_sent', 'messages_delivered', 'messages_failed',
            'delivery_rate',
            'featured_item', 'featured_item_name',
            'created_by_name', 'approved_by_name',
            'created_at', 'updated_at', 'approved_at', 'completed_at',
        ]

    def get_created_by_name(self, obj):
        return obj.created_by.user.get_full_name() if obj.created_by_id else ''

    def get_approved_by_name(self, obj):
        return obj.approved_by.user.get_full_name() if obj.approved_by_id else ''

    def get_featured_item_name(self, obj):
        return obj.featured_item.name if obj.featured_item_id else ''


class WhatsAppCampaignDetailSerializer(serializers.ModelSerializer):
    """Full serializer for create / detail / edit."""
    status_label       = serializers.CharField(source='get_status_display', read_only=True)
    created_by_name    = serializers.SerializerMethodField()
    approved_by_name   = serializers.SerializerMethodField()
    rejected_by_name   = serializers.SerializerMethodField()
    delivery_rate      = serializers.FloatField(read_only=True)
    featured_item_name = serializers.SerializerMethodField()
    can_request_approval = serializers.BooleanField(read_only=True)
    can_approve          = serializers.BooleanField(read_only=True)
    can_queue            = serializers.BooleanField(read_only=True)
    can_cancel           = serializers.BooleanField(read_only=True)

    class Meta:
        model = WhatsAppCampaign
        fields = [
            'id', 'name', 'description', 'status', 'status_label',
            'message_template', 'target_filter',
            'featured_item', 'featured_item_name',
            'scheduled_at', 'estimated_reach',
            'messages_queued', 'messages_sent', 'messages_delivered', 'messages_failed',
            'delivery_rate',
            'created_by', 'created_by_name',
            'approved_by', 'approved_by_name',
            'rejected_by', 'rejected_by_name',
            'rejection_reason',
            'can_request_approval', 'can_approve', 'can_queue', 'can_cancel',
            'created_at', 'updated_at', 'approved_at', 'queued_at', 'completed_at',
        ]
        read_only_fields = [
            'id', 'status', 'status_label',
            'estimated_reach', 'messages_queued', 'messages_sent',
            'messages_delivered', 'messages_failed', 'delivery_rate',
            'created_by', 'created_by_name',
            'approved_by', 'approved_by_name',
            'rejected_by', 'rejected_by_name',
            'can_request_approval', 'can_approve', 'can_queue', 'can_cancel',
            'created_at', 'updated_at', 'approved_at', 'queued_at', 'completed_at',
        ]

    def get_created_by_name(self, obj):
        return obj.created_by.user.get_full_name() if obj.created_by_id else ''

    def get_approved_by_name(self, obj):
        return obj.approved_by.user.get_full_name() if obj.approved_by_id else ''

    def get_rejected_by_name(self, obj):
        return obj.rejected_by.user.get_full_name() if obj.rejected_by_id else ''

    def get_featured_item_name(self, obj):
        return obj.featured_item.name if obj.featured_item_id else ''


class AudiencePreviewSerializer(serializers.Serializer):
    """Used to return audience preview counts without a model."""
    total_customers  = serializers.IntegerField()
    has_phone        = serializers.IntegerField()
    sample_names     = serializers.ListField(child=serializers.CharField())
    filter_summary   = serializers.DictField()


class ApproveSerializer(serializers.Serializer):
    pass


class RejectSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True, max_length=1000)


class QueueSerializer(serializers.Serializer):
    scheduled_at = serializers.DateTimeField(required=False, allow_null=True)


class MessageStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=['sent', 'delivered', 'failed', 'skipped', 'opted_out'])
    error_message = serializers.CharField(required=False, default='')
