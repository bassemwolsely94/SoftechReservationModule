"""
apps/stockcount/serializers.py  — v2
"""
from rest_framework import serializers
from .models import StockCountSession, StockCountSnapshot, DOCCODE_LABELS


# ── Snapshot ──────────────────────────────────────────────────────────────────

class StockCountSnapshotSerializer(serializers.ModelSerializer):
    variance_label = serializers.CharField(
        source='get_variance_type_display', read_only=True
    )

    class Meta:
        model  = StockCountSnapshot
        fields = [
            'id', 'item_code', 'item_name', 'item_medicine', 'category_name',
            'branch_code', 'expected_qty', 'snapshot_time',
            'counted_qty', 'difference', 'variance_type', 'variance_label',
            'entered_expiry_hint', 'physical_expiry',
        ]
        read_only_fields = fields   # Everything is read-only from API perspective


# ── Session list ─────────────────────────────────────────────────────────────

class StockCountSessionListSerializer(serializers.ModelSerializer):
    created_by_name  = serializers.CharField(
        source='created_by.full_name', read_only=True, default='',
    )
    snapshot_by_name = serializers.CharField(
        source='snapshot_by.full_name', read_only=True, default='',
    )
    uploaded_by_name = serializers.CharField(
        source='uploaded_by.full_name', read_only=True, default='',
    )
    status_label     = serializers.CharField(
        source='get_status_display', read_only=True,
    )
    mode_label       = serializers.CharField(
        source='get_mode_display', read_only=True,
    )
    doccode_labels   = serializers.SerializerMethodField()

    def get_doccode_labels(self, obj):
        return [
            {'code': dc, 'label': DOCCODE_LABELS.get(dc, dc)}
            for dc in (obj.doccodes or [])
        ]

    class Meta:
        model  = StockCountSession
        fields = [
            'id', 'name', 'mode', 'mode_label', 'status', 'status_label',
            'branch_code',
            'date_from', 'date_to',
            'doccodes', 'doccode_labels',
            'user_code_filter', 'category_filter',
            'item_count', 'surplus_count', 'deficit_count', 'ok_count',
            'created_by_name', 'snapshot_by_name', 'uploaded_by_name',
            'created_at', 'snapshot_at', 'exported_at', 'uploaded_at', 'variance_at',
            'updated_at', 'notes',
        ]


# ── Session detail (includes snapshots) ──────────────────────────────────────

class StockCountSessionDetailSerializer(StockCountSessionListSerializer):
    snapshots = StockCountSnapshotSerializer(many=True, read_only=True)

    class Meta(StockCountSessionListSerializer.Meta):
        fields = StockCountSessionListSerializer.Meta.fields + ['snapshots']


# ── Session create ────────────────────────────────────────────────────────────

class StockCountSessionCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = StockCountSession
        fields = [
            'name', 'mode', 'branch_code',
            'date_from', 'date_to',
            'doccodes', 'user_code_filter',
            'category_filter', 'item_codes_filter',
            'notes',
        ]

    def validate(self, data):
        mode = data.get('mode', 'transaction')
        if mode == 'transaction':
            if not data.get('doccodes'):
                raise serializers.ValidationError(
                    'يجب تحديد كود مستند واحد على الأقل في النوع المبني على الحركات'
                )
            if not data.get('date_from') or not data.get('date_to'):
                raise serializers.ValidationError(
                    'يجب تحديد نطاق التاريخ في النوع المبني على الحركات'
                )
        if not data.get('branch_code'):
            raise serializers.ValidationError('كود الفرع مطلوب')
        return data
