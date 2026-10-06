from rest_framework import serializers
from .models import (
    ItemEnrichment, EnrichmentSuggestion, EnrichmentBatch,
    EnrichmentApprovalLog, FIELD_LABELS_AR,
)


class ItemEnrichmentSerializer(serializers.ModelSerializer):
    item_id       = serializers.IntegerField(source='item.id',        read_only=True)
    item_name     = serializers.CharField(source='item.name',         read_only=True)
    item_code     = serializers.CharField(source='item.softech_id',   read_only=True)
    item_category = serializers.SerializerMethodField()
    pending_count = serializers.SerializerMethodField()

    class Meta:
        model  = ItemEnrichment
        fields = [
            'id', 'item', 'item_id', 'item_name', 'item_code', 'item_category',
            # Bilingual
            'name_ar', 'brand_name',
            # Manufacturer / country
            'manufacturer_ar', 'manufacturer_en', 'country_ar', 'country_en',
            # Dosage form
            'dosage_form_ar', 'dosage_form_en',
            # Drug details
            'atc_code', 'strength', 'volume', 'pack_size_label',
            # Clinical
            'indication_ar', 'indication_en', 'contraindication_ar', 'warning_ar',
            'pregnancy_category', 'age_range',
            # Storage / admin
            'storage_condition', 'administration_route_ar',
            # Regimen
            'dosage_ar', 'frequency_ar', 'duration_ar',
            # Safety
            'side_effects_ar', 'side_effects_en', 'drug_interactions_ar',
            # Classification
            'rx_otc',
            # Media
            'image_url', 'image_secondary_url',
            # SEO
            'seo_desc_ar', 'seo_desc_en', 'medical_keywords_ar', 'medical_keywords_en',
            # Quality
            'completeness_score', 'is_published', 'last_enriched_at',
            'created_at', 'updated_at',
            # Computed
            'pending_count',
        ]
        read_only_fields = [
            'id', 'item', 'item_id', 'item_name', 'item_code', 'item_category',
            'completeness_score', 'last_enriched_at', 'created_at', 'updated_at',
            'pending_count',
        ]

    def get_item_category(self, obj):
        cat = obj.item.category
        return (cat.name_ar or cat.name) if cat else ''

    def get_pending_count(self, obj):
        # Prefer the annotated value added by the list view
        if hasattr(obj, 'pending_count_ann'):
            return obj.pending_count_ann
        if hasattr(obj, '_pending_count'):
            return obj._pending_count
        return obj.suggestions.filter(status='pending').count()


class EnrichmentSuggestionSerializer(serializers.ModelSerializer):
    item_name     = serializers.CharField(source='item.name',       read_only=True)
    item_code     = serializers.CharField(source='item.softech_id', read_only=True)
    field_label   = serializers.SerializerMethodField()
    reviewer_name = serializers.SerializerMethodField()
    source_label  = serializers.SerializerMethodField()

    class Meta:
        model  = EnrichmentSuggestion
        fields = [
            'id', 'item', 'item_name', 'item_code',
            'field_name', 'field_label',
            'suggested_value', 'current_value', 'approved_value',
            'source', 'source_label', 'confidence', 'status', 'notes',
            'reviewed_by', 'reviewer_name', 'reviewed_at', 'batch',
            'created_at',
        ]
        read_only_fields = [
            'id', 'item', 'item_name', 'item_code', 'field_label',
            'source_label', 'reviewer_name', 'reviewed_by', 'reviewed_at', 'created_at',
        ]

    def get_field_label(self, obj):
        return FIELD_LABELS_AR.get(obj.field_name, obj.field_name)

    def get_reviewer_name(self, obj):
        if obj.reviewed_by:
            return obj.reviewed_by.get_full_name() or obj.reviewed_by.username
        return None

    def get_source_label(self, obj):
        labels = dict(obj._meta.get_field('source').choices) if hasattr(obj._meta.get_field('source'), 'choices') else {}
        from .models import SOURCE_CHOICES
        labels = dict(SOURCE_CHOICES)
        return labels.get(obj.source, obj.source)


class EnrichmentBatchSerializer(serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    progress_pct    = serializers.FloatField(read_only=True)

    class Meta:
        model  = EnrichmentBatch
        fields = [
            'id', 'name', 'status', 'scope_type', 'scope_params',
            'auto_publish_threshold',
            'total_items', 'processed_items', 'suggestions_generated',
            'auto_published', 'error_count',
            'created_by', 'created_by_name',
            'started_at', 'finished_at', 'created_at',
            'progress_pct',
        ]
        read_only_fields = [
            'id', 'status', 'total_items', 'processed_items', 'suggestions_generated',
            'auto_published', 'error_count', 'created_by', 'created_by_name',
            'started_at', 'finished_at', 'created_at', 'progress_pct',
        ]

    def get_created_by_name(self, obj):
        if obj.created_by:
            return obj.created_by.get_full_name() or obj.created_by.username
        return None


# Lightweight list serializer for the item queue (left panel)
class EnrichmentQueueItemSerializer(serializers.ModelSerializer):
    item_id       = serializers.IntegerField(source='item.id',        read_only=True)
    item_name     = serializers.CharField(source='item.name',         read_only=True)
    item_code     = serializers.CharField(source='item.softech_id',   read_only=True)
    item_category = serializers.SerializerMethodField()
    pending_count = serializers.SerializerMethodField()

    class Meta:
        model  = ItemEnrichment
        fields = [
            'id', 'item', 'item_id', 'item_name', 'item_code', 'item_category',
            'completeness_score', 'is_published', 'pending_count',
        ]
        read_only_fields = fields

    def get_item_category(self, obj):
        cat = obj.item.category
        return (cat.name_ar or cat.name) if cat else ''

    def get_pending_count(self, obj):
        # Prefer the annotated value injected by the list view queryset
        if hasattr(obj, 'pending_count_ann'):
            return obj.pending_count_ann
        if hasattr(obj, '_pending_count'):
            return obj._pending_count
        return obj.suggestions.filter(status='pending').count()
