from rest_framework import serializers
from .models import Branch, BranchSettings


class BranchSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model  = BranchSettings
        fields = [
            'id', 'branch',
            'allow_reservations', 'allow_transfers',
            'allow_vouchers', 'allow_stockcount', 'allow_shortage', 'daily_count_enabled',
            'notifications_enabled', 'is_24h', 'working_hours',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'branch', 'created_at', 'updated_at']

    def validate_working_hours(self, value):
        from .hours import HoursError, validate_windows
        try:
            return validate_windows(value)
        except HoursError as e:
            raise serializers.ValidationError(str(e))


class BranchSerializer(serializers.ModelSerializer):
    settings     = BranchSettingsSerializer(read_only=True)
    display_name = serializers.CharField(read_only=True)
    can_transact = serializers.BooleanField(read_only=True)
    is_hq        = serializers.BooleanField(read_only=True)
    is_live      = serializers.BooleanField(read_only=True)
    kind_label   = serializers.CharField(source='get_kind_display', read_only=True)

    class Meta:
        model  = Branch
        fields = [
            'id', 'softech_branch_id', 'code',
            'name', 'name_ar', 'display_name',
            'address', 'phone',
            'latitude', 'longitude',
            'kind', 'kind_label', 'is_live', 'display_order', 'pos_enabled', 'is_hq',
            'is_active', 'is_operational', 'can_transact',
            'created_at',
            'settings',
        ]
        read_only_fields = ['id', 'softech_branch_id', 'code', 'name', 'display_name', 'can_transact', 'is_hq', 'created_at']

    def validate_kind(self, value):
        """Exactly one HQ, always: hq_code() raises on every HQ path (ISR, distribution, finance
        GL, portal) when there are zero or two. Moving HQ is not done from this screen."""
        inst = self.instance
        others = Branch.objects.filter(kind=Branch.KIND_HQ)
        if inst is not None:
            others = others.exclude(pk=inst.pk)
        if value == Branch.KIND_HQ and others.exists():
            raise serializers.ValidationError('يوجد مركز رئيسي بالفعل — لا يمكن تعيين مركز رئيسي ثانٍ.')
        if inst is not None and inst.kind == Branch.KIND_HQ and value != Branch.KIND_HQ and not others.exists():
            raise serializers.ValidationError('لا يمكن تغيير تصنيف المركز الرئيسي الوحيد.')
        return value
