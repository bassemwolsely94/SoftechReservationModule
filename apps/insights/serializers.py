from rest_framework import serializers
from .models import InsightRun, InsightFinding, InsightRule


class InsightFindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsightFinding
        fields = ['id', 'rule_code', 'category', 'severity', 'scope_type', 'scope_key',
                  'scope_label', 'value', 'baseline', 'threshold', 'message_ar', 'message_en']


class InsightRunSerializer(serializers.ModelSerializer):
    findings = InsightFindingSerializer(many=True, read_only=True)
    period_label = serializers.CharField(source='get_period_type_display', read_only=True)

    class Meta:
        model = InsightRun
        fields = ['id', 'domain', 'period_type', 'period_label', 'period_start', 'period_end',
                  'findings_count', 'narrative_ar', 'narrative_en', 'created_at',
                  'sent_at', 'sent_to', 'findings']


class InsightRunListSerializer(serializers.ModelSerializer):
    period_label = serializers.CharField(source='get_period_type_display', read_only=True)

    class Meta:
        model = InsightRun
        fields = ['id', 'domain', 'period_type', 'period_label', 'period_start', 'period_end',
                  'findings_count', 'created_at', 'sent_at', 'sent_to']


class InsightRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = InsightRule
        fields = ['id', 'code', 'name_ar', 'name_en', 'category', 'severity',
                  'threshold', 'enabled', 'periods']
        read_only_fields = ['code']
