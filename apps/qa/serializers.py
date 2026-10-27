from rest_framework import serializers
from .models import QAChecklistTemplate, QAInspection


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
