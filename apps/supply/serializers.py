"""Serializers for the supply orchestration API (Phase 2 — availability inbox)."""
from rest_framework import serializers

from apps.invoices.models import VendorProfile
from .models import AvailabilityBatch, AvailabilityLine, SupplyCase, SupplyDecision


class AvailabilityLineSerializer(serializers.ModelSerializer):
    item_name      = serializers.CharField(source='item.name', read_only=True, default='')
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True, default='')

    class Meta:
        model = AvailabilityLine
        fields = [
            'id', 'raw_text', 'item', 'item_name', 'item_softech_id',
            'match_score', 'match_reason', 'is_confirmed', 'is_unmatched',
            'supplier_qty', 'price', 'discount_pct', 'foc_qty', 'expiry',
            'supplier_item_code', 'bonus_buy', 'bonus_tiers', 'quota', 'promo', 'signals',
            'source', 'notes', 'split_from', 'created_at',
        ]
        read_only_fields = ['match_reason', 'split_from', 'created_at']


class AvailabilityLineUpdateSerializer(serializers.ModelSerializer):
    """Operator corrections: pick/clear the item, tweak economics. Confirmation +
    alias-learning are handled in the view (so the corpus is taught vendor-scoped)."""
    class Meta:
        model = AvailabilityLine
        fields = ['item', 'supplier_qty', 'price', 'discount_pct', 'foc_qty', 'bonus_buy',
                  'quota', 'expiry', 'supplier_item_code', 'notes', 'is_confirmed']


class AvailabilityBatchSerializer(serializers.ModelSerializer):
    supplier_display = serializers.SerializerMethodField()
    operator_name    = serializers.CharField(source='operator.user.get_full_name',
                                             read_only=True, default='')
    line_count       = serializers.IntegerField(read_only=True)
    matched_count    = serializers.IntegerField(read_only=True)
    confirmed_count  = serializers.IntegerField(read_only=True)
    is_locked        = serializers.BooleanField(read_only=True)
    locked_by_name   = serializers.CharField(source='locked_by.full_name', read_only=True, default='')

    class Meta:
        model = AvailabilityBatch
        fields = [
            'id', 'supplier', 'supplier_name', 'supplier_display', 'source', 'status',
            'raw_fingerprint', 'operator', 'operator_name', 'notes',
            'line_count', 'matched_count', 'confirmed_count', 'created_at', 'updated_at',
            'branch_scope', 'is_locked', 'locked_at', 'locked_by_name', 'lock_note',
        ]
        # scope / lock change only through their audited actions (scope / lock / unlock)
        read_only_fields = ['branch_scope', 'locked_at', 'lock_note']

    def get_supplier_display(self, obj):
        if obj.supplier_id and obj.supplier:
            return obj.supplier.name
        return obj.supplier_name


class AvailabilityBatchDetailSerializer(AvailabilityBatchSerializer):
    lines       = AvailabilityLineSerializer(many=True, read_only=True)
    raw_content = serializers.CharField(read_only=True)

    class Meta(AvailabilityBatchSerializer.Meta):
        fields = AvailabilityBatchSerializer.Meta.fields + ['raw_content', 'lines']


class AvailabilityBatchCreateSerializer(serializers.Serializer):
    supplier_name = serializers.CharField(required=False, allow_blank=True, default='')
    supplier      = serializers.PrimaryKeyRelatedField(
        queryset=VendorProfile.objects.all(), required=False, allow_null=True)
    source        = serializers.ChoiceField(choices=AvailabilityBatch.SOURCE_CHOICES,
                                            default=AvailabilityBatch.SOURCE_WHATSAPP)
    raw_content   = serializers.CharField(required=False, allow_blank=True, default='')
    notes         = serializers.CharField(required=False, allow_blank=True, default='')


class SupplyCaseSerializer(serializers.ModelSerializer):
    """A follow-up case: identity, snapshot figures, and what a human may do next."""
    item_name       = serializers.CharField(source='item.name', read_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True)
    branch_name     = serializers.SerializerMethodField()
    status_display  = serializers.CharField(source='get_status_display', read_only=True)
    days_open       = serializers.IntegerField(read_only=True)
    assigned_name   = serializers.CharField(source='assigned_to.user.get_full_name',
                                            read_only=True, default='')
    allowed_transitions = serializers.SerializerMethodField()
    availability_line_ids = serializers.PrimaryKeyRelatedField(
        source='availability_lines', many=True, read_only=True)
    # Live status of the draft transfers this case created — so a draft the transfers team
    # rejected / cancelled is visible on the case instead of it sitting in transfer_pending.
    transfer_requests = serializers.SerializerMethodField()

    class Meta:
        model = SupplyCase
        fields = [
            'id', 'item', 'item_name', 'item_softech_id', 'branch', 'branch_name',
            'status', 'status_display', 'allowed_transitions',
            'required_qty', 'residual_gap', 'internal_cover', 'customer_demand',
            'current_stock', 'scarcity_score', 'is_urgent', 'has_availability',
            'availability_line_ids', 'last_ledger', 'last_reasons', 'execution_refs',
            'transfer_requests',
            'assigned_to', 'assigned_name', 'close_reason', 'notes',
            'days_open', 'first_detected_at', 'last_evaluated_at', 'status_changed_at',
            'closed_at',
        ]
        read_only_fields = fields

    def get_branch_name(self, obj):
        if obj.branch_id:
            return obj.branch.name_ar or obj.branch.name
        return 'الشبكة'

    def get_allowed_transitions(self, obj):
        from .cases import allowed_targets
        return allowed_targets(obj)

    def get_transfer_requests(self, obj):
        ids = (obj.execution_refs or {}).get('transfer_requests') or []
        if not ids:
            return []
        from apps.transfers.models import TransferRequest
        return [{'id': t.pk, 'request_number': t.request_number, 'status': t.status,
                 'status_label': t.status_label_ar,
                 'supplying_branch': (t.supplying_branch.name_ar or t.supplying_branch.name)
                                     if t.supplying_branch_id else ''}
                for t in TransferRequest.objects.filter(pk__in=ids).select_related('supplying_branch')]


class SupplyDecisionSerializer(serializers.ModelSerializer):
    """Recommended vs decided vs outcome for one consequential action (§40)."""
    item_name       = serializers.CharField(source='item.name', read_only=True)
    item_softech_id = serializers.CharField(source='item.softech_id', read_only=True)
    kind_display    = serializers.CharField(source='get_kind_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.user.get_full_name',
                                            read_only=True, default='')

    class Meta:
        model = SupplyDecision
        fields = [
            'id', 'kind', 'kind_display', 'case', 'item', 'item_name', 'item_softech_id',
            'branch', 'recommended_qty', 'decided_qty', 'is_override', 'override_reason',
            'supplier', 'supplier_name', 'availability_line', 'unit_price', 'foc_qty',
            'effective_cost', 'receipt_status', 'received_qty', 'recommendation_snapshot',
            'revalidation', 'result_refs', 'order_ref', 'created_by', 'created_by_name',
            'created_at',
        ]
        read_only_fields = fields
