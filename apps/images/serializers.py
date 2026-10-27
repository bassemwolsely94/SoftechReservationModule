from rest_framework import serializers
from .models import ImageSearchJob, ImageCandidate, ProductNormalization


class ProductNormalizationSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    item_code = serializers.CharField(source='item.softech_id', read_only=True)

    class Meta:
        model  = ProductNormalization
        fields = [
            'id', 'item', 'item_name', 'item_code',
            'canonical_name', 'search_query_en', 'search_query_ar',
            'brand', 'strength', 'dosage_form', 'pack_size',
            'parse_confidence', 'updated_at',
        ]
        read_only_fields = fields


class ImageCandidateSerializer(serializers.ModelSerializer):
    image_url      = serializers.SerializerMethodField()
    dimensions     = serializers.CharField(read_only=True)
    item_name      = serializers.CharField(source='item.name',       read_only=True)
    item_code      = serializers.CharField(source='item.softech_id', read_only=True)
    watermark_score = serializers.SerializerMethodField()
    was_cleaned     = serializers.SerializerMethodField()

    class Meta:
        model  = ImageCandidate
        fields = [
            'id', 'job', 'item', 'item_name', 'item_code',
            'source_url', 'source_type', 'source_page_url', 'image_url',
            'width', 'height', 'dimensions', 'file_size_bytes', 'format',
            'quality_score', 'confidence_score', 'total_score',
            'watermark_score', 'was_cleaned',
            'score_breakdown',
            'phash', 'status',
            'reviewed_by', 'reviewed_at', 'review_note',
            'created_at',
        ]
        read_only_fields = [
            'id', 'job', 'item', 'item_name', 'item_code',
            'image_url', 'dimensions',
            'width', 'height', 'file_size_bytes', 'format', 'phash',
            'quality_score', 'confidence_score', 'total_score', 'score_breakdown',
            'reviewed_by', 'reviewed_at', 'created_at',
        ]

    def get_image_url(self, obj):
        request = self.context.get('request')
        if obj.local_file:
            return request.build_absolute_uri(obj.local_file.url) if request else obj.local_file.url
        return obj.source_url

    def get_watermark_score(self, obj):
        return round(obj.score_breakdown.get('watermark_score', 0), 3)

    def get_was_cleaned(self, obj):
        return bool(obj.score_breakdown.get('was_cleaned', False))


class ImageSearchJobSerializer(serializers.ModelSerializer):
    item_name         = serializers.CharField(source='item.name',       read_only=True)
    item_code         = serializers.CharField(source='item.softech_id', read_only=True)
    triggered_by_name = serializers.SerializerMethodField()
    duration_seconds  = serializers.SerializerMethodField()
    top_candidates    = serializers.SerializerMethodField()

    class Meta:
        model  = ImageSearchJob
        fields = [
            'id', 'item', 'item_name', 'item_code',
            'status', 'current_stage', 'priority',
            'attempt_count', 'max_attempts',
            'auto_approve_threshold', 'review_threshold',
            'candidates_found', 'candidates_scored', 'best_score',
            'triggered_by', 'triggered_by_name',
            'last_error', 'duration_seconds',
            'started_at', 'finished_at', 'created_at',
            'top_candidates',
        ]
        read_only_fields = [f for f in fields if f not in ('priority', 'auto_approve_threshold')]

    def get_triggered_by_name(self, obj):
        if obj.triggered_by:
            return obj.triggered_by.get_full_name() or obj.triggered_by.username
        return 'نظام تلقائي'

    def get_duration_seconds(self, obj):
        if obj.started_at and obj.finished_at:
            return round((obj.finished_at - obj.started_at).total_seconds(), 1)
        return None

    def get_top_candidates(self, obj):
        qs = obj.candidates.order_by('-total_score')[:3]
        return ImageCandidateSerializer(qs, many=True, context=self.context).data


class JobCreateSerializer(serializers.Serializer):
    item_id                 = serializers.IntegerField()
    priority                = serializers.IntegerField(default=2, min_value=1, max_value=4)
    auto_approve_threshold  = serializers.FloatField(default=0.78, min_value=0.0, max_value=1.0)
    force_rerun             = serializers.BooleanField(default=False)


class CandidateReviewSerializer(serializers.Serializer):
    action      = serializers.ChoiceField(choices=['approve', 'reject'])
    note        = serializers.CharField(required=False, allow_blank=True, default='')
    set_primary = serializers.BooleanField(default=True)
