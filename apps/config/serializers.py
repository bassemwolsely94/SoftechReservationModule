from rest_framework import serializers
from .models import SystemSetting, DropdownOption


class SystemSettingSerializer(serializers.ModelSerializer):
    typed_value = serializers.SerializerMethodField()

    def get_typed_value(self, obj):
        return obj.typed_value()

    class Meta:
        model  = SystemSetting
        fields = [
            'id', 'key', 'label', 'description',
            'value', 'value_type', 'typed_value',
            'category', 'is_public', 'updated_at',
        ]
        read_only_fields = ['updated_at']


class SystemSettingUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SystemSetting
        fields = ['value']


class DropdownOptionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DropdownOption
        fields = [
            'id', 'dropdown_key', 'label', 'label_en',
            'value', 'icon', 'color', 'order',
            'is_active', 'is_system',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']


class DropdownOptionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = DropdownOption
        fields = ['dropdown_key', 'label', 'label_en', 'value', 'icon', 'color', 'order', 'is_active']

    def validate_value(self, v):
        return v.strip().lower().replace(' ', '_')
