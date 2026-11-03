from rest_framework import serializers

from .models import CONTENT_FIELDS, CounsellingContent, CounsellingContentVersion


def _name(p):
    return p.full_name if p else ''


class CounsellingContentSerializer(serializers.ModelSerializer):
    """Read shape. Writes go through services.py (views pass validated dicts), never .save()."""
    items = serializers.SerializerMethodField()
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    source_label = serializers.CharField(source='get_source_display', read_only=True)
    approved_by_name = serializers.SerializerMethodField()
    updated_by_name = serializers.SerializerMethodField()
    has_unapproved_changes = serializers.SerializerMethodField()

    class Meta:
        model = CounsellingContent
        fields = ('id', 'title', *CONTENT_FIELDS, 'status', 'status_label', 'source', 'source_label',
                  'ai_model', 'version', 'retired_reason', 'items', 'approved_by_name', 'approved_at',
                  'updated_by_name', 'updated_at', 'created_at', 'has_unapproved_changes')
        read_only_fields = fields

    def get_items(self, obj):
        return [{'item_id': l.item_id, 'name': l.item.name, 'softech_id': l.item.softech_id}
                for l in obj.links.select_related('item').order_by('linked_at')]

    def get_approved_by_name(self, obj):
        return _name(obj.approved_by)

    def get_updated_by_name(self, obj):
        return _name(obj.updated_by)

    def get_has_unapproved_changes(self, obj):
        return obj.status in ('draft', 'pending_review') and obj.approved_version_id is not None


class CounsellingVersionSerializer(serializers.ModelSerializer):
    approved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CounsellingContentVersion
        fields = ('id', 'version', 'data', 'approved_by_name', 'approved_at')
        read_only_fields = fields

    def get_approved_by_name(self, obj):
        return _name(obj.approved_by)
