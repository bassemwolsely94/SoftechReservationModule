from rest_framework import serializers
from .models import RecommendationEngineRun, FrequentlyBoughtTogether, CustomerRecommendation


class EngineRunSerializer(serializers.ModelSerializer):
    class Meta:
        model  = RecommendationEngineRun
        fields = [
            'id', 'started_at', 'finished_at', 'status',
            'pairs_generated', 'invoices_scanned', 'customers_scored',
            'min_support', 'min_confidence', 'lookback_days', 'error_message',
        ]


class FBTPairSerializer(serializers.ModelSerializer):
    item_a_name   = serializers.CharField(source='item_a.name',       read_only=True)
    item_a_code   = serializers.CharField(source='item_a.softech_id', read_only=True)
    item_b_name   = serializers.CharField(source='item_b.name',       read_only=True)
    item_b_code   = serializers.CharField(source='item_b.softech_id', read_only=True)

    class Meta:
        model  = FrequentlyBoughtTogether
        fields = [
            'id', 'item_a', 'item_a_name', 'item_a_code',
            'item_b', 'item_b_name', 'item_b_code',
            'co_occurrences', 'item_a_occurrences',
            'confidence', 'support', 'lift', 'score',
        ]


class CustomerRecSerializer(serializers.ModelSerializer):
    item_name   = serializers.CharField(source='item.name',       read_only=True)
    item_code   = serializers.CharField(source='item.softech_id', read_only=True)
    customer_name = serializers.CharField(source='customer.name', read_only=True, default=None)

    class Meta:
        model  = CustomerRecommendation
        fields = [
            'id', 'customer', 'customer_name',
            'item', 'item_name', 'item_code',
            'score', 'reason', 'is_chronic_related',
        ]
