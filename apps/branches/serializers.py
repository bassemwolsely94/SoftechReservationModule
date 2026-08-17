from rest_framework import serializers
from .models import Branch, BranchSettings


class BranchSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model  = BranchSettings
        fields = [
            'id', 'branch',
            'allow_reservations', 'allow_transfers',
            'allow_vouchers', 'allow_stockcount', 'allow_shortage',
            'notifications_enabled',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'branch', 'created_at', 'updated_at']


class BranchSerializer(serializers.ModelSerializer):
    settings     = BranchSettingsSerializer(read_only=True)
    display_name = serializers.CharField(read_only=True)
    can_transact = serializers.BooleanField(read_only=True)
    is_hq        = serializers.BooleanField(read_only=True)

    class Meta:
        model  = Branch
        fields = [
            'id', 'softech_branch_id', 'code',
            'name', 'name_ar', 'display_name',
            'address', 'phone',
            'latitude', 'longitude',
            'kind', 'pos_enabled', 'is_hq',
            'is_active', 'is_operational', 'can_transact',
            'created_at',
            'settings',
        ]
        read_only_fields = ['id', 'softech_branch_id', 'code', 'name', 'display_name', 'can_transact', 'is_hq', 'created_at']
