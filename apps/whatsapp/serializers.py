from rest_framework import serializers
from apps.whatsapp.models import WAConversation, WAMessage, WATemplate, WAMediaFile


class WATemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = WATemplate
        fields = ['id', 'name', 'language', 'category', 'status', 'body_text',
                  'header_type', 'header_text', 'footer_text', 'variable_map']


class WAMediaFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = WAMediaFile
        fields = ['id', 'file_type', 'mime_type', 'file_name', 'file_size', 'meta_media_id']


class WAMessageSerializer(serializers.ModelSerializer):
    media = WAMediaFileSerializer(read_only=True)
    template_name = serializers.SerializerMethodField()

    class Meta:
        model = WAMessage
        fields = [
            'id', 'direction', 'message_type', 'status', 'wamid',
            'body', 'media', 'template_name',
            'location_lat', 'location_lng', 'location_name',
            'created_at', 'sent_at', 'delivered_at', 'read_at',
        ]

    def get_template_name(self, obj):
        return obj.template.name if obj.template else None


class WAConversationSerializer(serializers.ModelSerializer):
    customer_name   = serializers.SerializerMethodField()
    customer_phone  = serializers.SerializerMethodField()
    window_open     = serializers.BooleanField(read_only=True)
    assigned_to_name = serializers.SerializerMethodField()

    class Meta:
        model = WAConversation
        fields = [
            'id', 'wa_id', 'status', 'customer', 'customer_name', 'customer_phone',
            'window_open', 'window_expires_at',
            'assigned_to', 'assigned_to_name',
            'last_message_preview', 'last_message_at', 'unread_count',
            'created_at', 'updated_at',
        ]

    def get_customer_name(self, obj):
        return obj.customer.name if obj.customer else None

    def get_customer_phone(self, obj):
        return obj.customer.phone if obj.customer else obj.wa_id

    def get_assigned_to_name(self, obj):
        if not obj.assigned_to:
            return None
        sp = obj.assigned_to
        full = sp.user.get_full_name() if sp.user_id else ''
        return full or (sp.user.username if sp.user_id else None)


class SendTextSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4096)


class SendTemplateSerializer(serializers.Serializer):
    template_name = serializers.CharField(max_length=100)
    language      = serializers.CharField(max_length=10, default='ar')
    variables     = serializers.ListField(child=serializers.DictField(), default=list)
