from rest_framework import serializers
from .models import ItemPriceChangeRequest, FIELD_TO_SOFTECH, USER_EDITABLE_FIELDS
from decimal import Decimal, InvalidOperation


class ItemPriceChangeRequestSerializer(serializers.ModelSerializer):
    item_name         = serializers.CharField(source='item.name', read_only=True)
    item_softech_id   = serializers.CharField(source='item.softech_id', read_only=True)
    item_pack_qty     = serializers.IntegerField(source='item.pack_qty', read_only=True)
    item_sale_tax_pct = serializers.DecimalField(
        source='item.sale_tax_pct', read_only=True, max_digits=5, decimal_places=2
    )
    requested_by_name  = serializers.SerializerMethodField()
    reviewed_by_name   = serializers.SerializerMethodField()
    status_display     = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = ItemPriceChangeRequest
        fields = [
            'id', 'item', 'item_name', 'item_softech_id', 'item_pack_qty', 'item_sale_tax_pct',
            'requested_by', 'requested_by_name', 'requested_at',
            'old_values', 'new_values', 'executed_values', 'reason',
            'status', 'status_display', 'source', 'rolled_back_from',
            'reviewed_by', 'reviewed_by_name', 'reviewed_at', 'review_notes',
            'erp_executed_at', 'erp_usercode', 'erp_username', 'erp_error',
        ]
        read_only_fields = [
            'requested_by', 'requested_at', 'status', 'source', 'rolled_back_from',
            'old_values', 'executed_values',
            'reviewed_by', 'reviewed_at',
            'erp_executed_at', 'erp_usercode', 'erp_username', 'erp_error',
        ]

    def get_requested_by_name(self, obj):
        u = obj.requested_by
        return u.get_full_name() or u.username

    def get_reviewed_by_name(self, obj):
        if obj.reviewed_by:
            u = obj.reviewed_by
            return u.get_full_name() or u.username
        return None

    def validate_new_values(self, value):
        allowed = {f[0] for f in USER_EDITABLE_FIELDS}
        for key, val in value.items():
            if key not in allowed:
                raise serializers.ValidationError(
                    f"حقل غير مسموح به: '{key}'. المسموح: {sorted(allowed)}"
                )
            try:
                d = Decimal(str(val))
                if d < 0:
                    raise serializers.ValidationError(f"القيمة يجب أن تكون >= 0 للحقل '{key}'")
            except InvalidOperation:
                raise serializers.ValidationError(f"قيمة غير صالحة للحقل '{key}': {val}")
        if not value:
            raise serializers.ValidationError("يجب تحديد حقل واحد على الأقل للتعديل")
        return value


class ReviewSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default='')


# ── Replication audit serializers ────────────────────────────────────────────

from .models import ReplicationScan, ReplicationGap  # noqa: E402


class ReplicationGapSerializer(serializers.ModelSerializer):
    status_display  = serializers.CharField(source='get_status_display', read_only=True)
    source_display  = serializers.CharField(source='get_source_channel_display', read_only=True)
    repaired_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ReplicationGap
        fields = [
            'id', 'item_softech_id', 'item_name', 'branch_code', 'branch_name',
            'hq_itemlastupdate', 'branch_itemlastupdate', 'hq_usercode',
            'source_user', 'source_channel', 'source_display',
            'diff_summary', 'status', 'status_display',
            'repaired_at', 'repaired_by_name', 'repair_note',
        ]

    def get_repaired_by_name(self, obj):
        if obj.repaired_by:
            return obj.repaired_by.get_full_name() or obj.repaired_by.username
        return None


class ReplicationScanSerializer(serializers.ModelSerializer):
    status_display    = serializers.CharField(source='get_status_display', read_only=True)
    triggered_by_name = serializers.SerializerMethodField()
    gap_branches      = serializers.SerializerMethodField()

    class Meta:
        model = ReplicationScan
        fields = [
            'id', 'started_at', 'finished_at', 'days_window', 'status', 'status_display',
            'triggered_by_name', 'is_scheduled',
            'items_checked', 'items_ok', 'items_with_gaps', 'branches_down',
            'gap_branches', 'error',
        ]

    def get_triggered_by_name(self, obj):
        if obj.triggered_by:
            return obj.triggered_by.get_full_name() or obj.triggered_by.username
        return 'مجدول' if obj.is_scheduled else None

    def get_gap_branches(self, obj):
        from collections import Counter
        c = Counter(obj.gaps.exclude(status='repaired').values_list('branch_code', flat=True))
        return dict(c)
