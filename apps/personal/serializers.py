"""apps/personal/serializers.py"""
from rest_framework import serializers

from .models import SoftechIdentityClaim, PersonalWidget
from .providers import WIDGET_REGISTRY


class IdentityClaimSerializer(serializers.ModelSerializer):
    kind_label   = serializers.CharField(source='get_kind_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    staff_name   = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SoftechIdentityClaim
        fields = [
            'id', 'kind', 'kind_label', 'person_code', 'label', 'meta',
            'status', 'status_label', 'note',
            'staff', 'staff_name',
            'reviewed_by', 'reviewed_by_name', 'reviewed_at', 'review_note',
            'created_at', 'updated_at',
        ]
        read_only_fields = [
            'status', 'meta', 'staff', 'reviewed_by', 'reviewed_at',
            'review_note', 'created_at', 'updated_at',
        ]

    def get_staff_name(self, obj):
        return obj.staff.full_name if obj.staff_id else None

    def get_reviewed_by_name(self, obj):
        return obj.reviewed_by.full_name if obj.reviewed_by_id else None


class PersonalWidgetSerializer(serializers.ModelSerializer):
    catalog_label = serializers.SerializerMethodField()
    catalog_icon  = serializers.SerializerMethodField()
    kind          = serializers.SerializerMethodField()
    identity_label = serializers.SerializerMethodField()
    identity_status = serializers.SerializerMethodField()

    class Meta:
        model = PersonalWidget
        fields = [
            'id', 'widget_type', 'catalog_label', 'catalog_icon', 'kind',
            'identity', 'identity_label', 'identity_status',
            'title', 'config', 'position', 'column', 'size', 'enabled',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def _meta(self, obj):
        return WIDGET_REGISTRY.get(obj.widget_type, {})

    def get_catalog_label(self, obj):
        return self._meta(obj).get('label', obj.widget_type)

    def get_catalog_icon(self, obj):
        return self._meta(obj).get('icon', '🧩')

    def get_kind(self, obj):
        return self._meta(obj).get('kind')

    def get_identity_label(self, obj):
        return obj.identity.label or obj.identity.person_code if obj.identity_id else None

    def get_identity_status(self, obj):
        return obj.identity.status if obj.identity_id else None

    def validate_widget_type(self, value):
        if value not in WIDGET_REGISTRY:
            raise serializers.ValidationError('نوع لوحة غير معروف')
        return value
