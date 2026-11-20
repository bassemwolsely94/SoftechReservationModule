from rest_framework import serializers
from .models import FridgeReading, FridgeUnit, QAChecklistTemplate, QAInspection


class QAChecklistTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = QAChecklistTemplate
        fields = ['id', 'name', 'name_ar', 'items', 'is_active']


class QAInspectionListSerializer(serializers.ModelSerializer):
    template_name  = serializers.CharField(source='template.name_ar', read_only=True)
    branch_name    = serializers.CharField(source='branch.name_ar', read_only=True)
    inspector_name = serializers.CharField(source='inspector.full_name', read_only=True)
    status_label   = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = QAInspection
        fields = [
            'id', 'template', 'template_name', 'branch', 'branch_name',
            'inspector_name', 'status', 'status_label', 'score',
            'created_at', 'submitted_at',
        ]


class QAInspectionDetailSerializer(QAInspectionListSerializer):
    class Meta(QAInspectionListSerializer.Meta):
        fields = QAInspectionListSerializer.Meta.fields + ['results', 'notes']


class QAInspectionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = QAInspection
        fields = ['template', 'branch']


# ── C31 fridge log ─────────────────────────────────────────────────────────────────────────────


class FridgeUnitSerializer(serializers.ModelSerializer):
    branch_name = serializers.CharField(source='branch.name_ar', read_only=True)

    class Meta:
        model  = FridgeUnit
        fields = ['id', 'branch', 'branch_name', 'name', 'min_c', 'max_c', 'is_active', 'created_at']
        read_only_fields = ['created_at']

    def validate(self, attrs):
        lo = attrs.get('min_c', getattr(self.instance, 'min_c', 2))
        hi = attrs.get('max_c', getattr(self.instance, 'max_c', 8))
        if lo >= hi:
            raise serializers.ValidationError({'max_c': 'أعلى درجة لازم تكون أكبر من أقل درجة'})
        return attrs


class FridgeReadingSerializer(serializers.ModelSerializer):
    slot_label = serializers.CharField(source='get_slot_display', read_only=True)
    recorded_by_name = serializers.CharField(source='recorded_by.full_name', read_only=True, default='')

    class Meta:
        model  = FridgeReading
        fields = ['id', 'fridge', 'day', 'slot', 'slot_label', 'temp_c', 'min_seen_c', 'max_seen_c',
                  'initials', 'note', 'out_of_range', 'recorded_by_name', 'recorded_at']
        read_only_fields = ['out_of_range', 'recorded_at']
        validators = []   # the slot-unique check below gives an Arabic message instead of DRF's

    def validate(self, attrs):
        from . import fridge as F
        if attrs['day'] not in F.allowed_days():
            raise serializers.ValidationError({'day': 'القراءة لليوم أو أمس بس'})
        if not attrs['fridge'].is_active:
            raise serializers.ValidationError({'fridge': 'الثلاجة متوقفة'})
        lo, hi = attrs.get('min_seen_c'), attrs.get('max_seen_c')
        if lo is not None and hi is not None and lo > hi:
            raise serializers.ValidationError({'min_seen_c': 'أقل درجة أكبر من أعلى درجة'})
        if FridgeReading.objects.filter(fridge=attrs['fridge'], day=attrs['day'], slot=attrs['slot']).exists():
            raise serializers.ValidationError({'slot': 'القراءة دي متسجلة بالفعل — اكتب أي تصحيح في ملاحظة القراءة الجاية'})
        for k in ('temp_c', 'min_seen_c', 'max_seen_c'):
            v = attrs.get(k)
            if v is not None and not (-30 <= v <= 40):
                raise serializers.ValidationError({k: 'قيمة غير منطقية لثلاجة'})
        return attrs
