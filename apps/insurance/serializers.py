"""apps/insurance/serializers.py"""
from decimal import Decimal
from rest_framework import serializers
from .models import (
    InsuranceClient, InsuranceSubClient, InsuranceContract,
    InsuranceClaim, InsuranceClaimPrescription, InsuranceClaimLine,
    InsuranceClaimAdjustment, InsuranceClaimManualRx,
    InsuranceClaimExclusion, InsuranceClaimSupplement,
    InsurancePayment, InsuranceDeduction,
)


# ── Contract Setup ─────────────────────────────────────────────────────────────

class InsuranceContractSerializer(serializers.ModelSerializer):
    class Meta:
        model  = InsuranceContract
        fields = '__all__'


class InsuranceSubClientSerializer(serializers.ModelSerializer):
    contracts    = InsuranceContractSerializer(many=True, read_only=True)
    client_name  = serializers.CharField(source='client.name', read_only=True)
    client_id    = serializers.IntegerField(source='client.id', read_only=True)

    class Meta:
        model  = InsuranceSubClient
        fields = '__all__'


class InsuranceClientSerializer(serializers.ModelSerializer):
    subclients = InsuranceSubClientSerializer(many=True, read_only=True)

    class Meta:
        model  = InsuranceClient
        fields = '__all__'


class InsuranceClientListSerializer(serializers.ModelSerializer):
    """Lightweight list — no nested subclients."""
    subclient_count = serializers.IntegerField(source='subclients.count', read_only=True)

    class Meta:
        model  = InsuranceClient
        fields = ['id', 'name', 'name_short', 'softech_personcode', 'is_active', 'subclient_count']


# ── Claim ──────────────────────────────────────────────────────────────────────

class InsuranceClaimLineSerializer(serializers.ModelSerializer):
    item_category_display = serializers.CharField(source='get_item_category_display', read_only=True)

    class Meta:
        model  = InsuranceClaimLine
        fields = '__all__'


class InsuranceClaimAdjustmentSerializer(serializers.ModelSerializer):
    adjusted_by_name = serializers.CharField(source='adjusted_by.__str__', read_only=True)

    class Meta:
        model  = InsuranceClaimAdjustment
        fields = '__all__'
        read_only_fields = ['adjusted_at']


class InsuranceClaimExclusionSerializer(serializers.ModelSerializer):
    excluded_by_name = serializers.CharField(source='excluded_by.__str__', read_only=True)

    class Meta:
        model  = InsuranceClaimExclusion
        fields = '__all__'
        read_only_fields = ['excluded_at']


class InsuranceClaimPrescriptionSerializer(serializers.ModelSerializer):
    # Lines are omitted by default — fetched lazily via /prescriptions/<id>/lines/
    # Include them only when context['include_lines'] = True
    lines       = serializers.SerializerMethodField()
    adjustment  = InsuranceClaimAdjustmentSerializer(read_only=True)
    is_excluded = serializers.SerializerMethodField()
    is_adjusted = serializers.SerializerMethodField()

    # Effective values (adjusted if override exists, else snapshot)
    effective_local_before    = serializers.SerializerMethodField()
    effective_imported_before = serializers.SerializerMethodField()
    effective_tarsia_before   = serializers.SerializerMethodField()
    effective_net_after       = serializers.SerializerMethodField()

    # SOFTECH reference flag — net_after vs softech_net (Power-Query deviates by design)
    softech_net_diff  = serializers.SerializerMethodField()
    softech_mismatch  = serializers.SerializerMethodField()

    class Meta:
        model  = InsuranceClaimPrescription
        fields = '__all__'

    def get_softech_net_diff(self, obj):
        d = obj.softech_net_diff
        return float(d) if d is not None else None

    def get_softech_mismatch(self, obj):
        return obj.softech_mismatch

    def get_lines(self, obj):
        if self.context.get('include_lines'):
            return InsuranceClaimLineSerializer(obj.lines.all(), many=True).data
        return None

    def get_is_excluded(self, obj):
        return hasattr(obj, 'exclusion')

    def get_is_adjusted(self, obj):
        try:
            return obj.adjustment is not None
        except InsuranceClaimAdjustment.DoesNotExist:
            return False

    def _eff(self, obj, snap_field, adj_field):
        try:
            val = getattr(obj.adjustment, adj_field)
            if val is not None:
                return float(val)
        except InsuranceClaimAdjustment.DoesNotExist:
            pass
        return float(getattr(obj, snap_field))

    def get_effective_local_before(self, obj):
        return self._eff(obj, 'local_before', 'local_before')

    def get_effective_imported_before(self, obj):
        return self._eff(obj, 'imported_before', 'imported_before')

    def get_effective_tarsia_before(self, obj):
        return self._eff(obj, 'tarsia_before', 'tarsia_before')

    def get_effective_net_after(self, obj):
        try:
            adj = obj.adjustment
            if adj.net_override is not None:
                return float(adj.net_override)
        except InsuranceClaimAdjustment.DoesNotExist:
            pass
        return float(obj.net_after)


class InsuranceClaimSupplementSerializer(serializers.ModelSerializer):
    supplement_type_display = serializers.CharField(source='get_supplement_type_display', read_only=True)
    created_by_name = serializers.CharField(source='created_by.__str__', read_only=True)

    class Meta:
        model  = InsuranceClaimSupplement
        fields = '__all__'


class InsuranceClaimManualRxSerializer(serializers.ModelSerializer):
    position_display = serializers.CharField(source='get_position_display', read_only=True)

    class Meta:
        model  = InsuranceClaimManualRx
        fields = '__all__'


class InsurancePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model  = InsurancePayment
        fields = '__all__'
        read_only_fields = ['recorded_at']


class InsuranceDeductionSerializer(serializers.ModelSerializer):
    reason_display = serializers.CharField(source='get_reason_code_display', read_only=True)

    class Meta:
        model  = InsuranceDeduction
        fields = '__all__'
        read_only_fields = ['recorded_at']


class InsuranceClaimListSerializer(serializers.ModelSerializer):
    """Lightweight list — no nested prescriptions."""
    client_name    = serializers.CharField(source='subclient.client.name', read_only=True)
    subclient_name = serializers.CharField(source='subclient.name', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    total_paid     = serializers.SerializerMethodField()
    total_deducted = serializers.SerializerMethodField()
    balance        = serializers.SerializerMethodField()
    is_locked      = serializers.BooleanField(read_only=True)

    class Meta:
        model = InsuranceClaim
        fields = [
            'id', 'claim_number', 'client_name', 'subclient_name',
            'period_from', 'period_to', 'status', 'status_display',
            'softech_motalba_no',
            'final_rx_count',
            'final_local_before', 'final_imported_before', 'final_tarsia_before',
            'final_gross_before', 'final_total_discount', 'final_net_after',
            'applied_local_disc_pct', 'applied_imported_disc_pct', 'applied_tarsia_disc_pct',
            'submitted_at', 'expected_payment_date',
            'total_paid', 'total_deducted', 'balance', 'is_locked',
            'created_at',
        ]

    def get_total_paid(self, obj):
        return float(sum(p.amount for p in obj.payments.all()))

    def get_total_deducted(self, obj):
        return float(sum(d.amount for d in obj.deductions.all()))

    def get_balance(self, obj):
        paid     = sum(p.amount for p in obj.payments.all())
        deducted = sum(d.amount for d in obj.deductions.all())
        return float(obj.final_net_after - paid - deducted)


class InsuranceClaimBillingGroupSerializer(serializers.ModelSerializer):
    class Meta:
        from .models import InsuranceClaimBillingGroup
        model  = InsuranceClaimBillingGroup
        fields = [
            'id', 'code', 'name', 'description',
            'filter_relative_degree', 'filter_dept_name',
            'filter_hi_type_code', 'filter_patient_no_prefix',
            'rx_count', 'gross_before', 'total_discount', 'net_after',
            'sort_order', 'created_at',
        ]
        read_only_fields = ['rx_count', 'gross_before', 'total_discount', 'net_after']


class InsuranceClaimDetailSerializer(InsuranceClaimListSerializer):
    """Full detail — includes prescriptions, supplements, manual_rx, payments, deductions."""
    subclient         = InsuranceSubClientSerializer(read_only=True)
    prescriptions     = InsuranceClaimPrescriptionSerializer(many=True, read_only=True)
    supplements       = InsuranceClaimSupplementSerializer(many=True, read_only=True)
    manual_rx         = InsuranceClaimManualRxSerializer(many=True, read_only=True)
    payments          = InsurancePaymentSerializer(many=True, read_only=True)
    deductions        = InsuranceDeductionSerializer(many=True, read_only=True)
    billing_groups    = InsuranceClaimBillingGroupSerializer(many=True, read_only=True)

    class Meta(InsuranceClaimListSerializer.Meta):
        fields = InsuranceClaimListSerializer.Meta.fields + [
            'subclient', 'contract', 'softech_motalba_no',
            'imported_personcodes', 'imported_branches', 'imported_at',
            'snapshot_rx_count', 'snapshot_net_after',
            'prescriptions', 'supplements', 'manual_rx', 'payments', 'deductions',
            'billing_groups',
            'notes', 'updated_at',
        ]


# ── Action serializers ─────────────────────────────────────────────────────────

class ImportClaimSerializer(serializers.Serializer):
    subclient_id      = serializers.IntegerField()
    contract_id       = serializers.IntegerField(required=False, allow_null=True)
    period_from       = serializers.DateField()
    period_to         = serializers.DateField()
    softech_motalba_no = serializers.CharField(required=False, allow_blank=True)
    branchcodes       = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    notes             = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if data['period_from'] > data['period_to']:
            raise serializers.ValidationError('تاريخ البداية يجب أن يكون قبل تاريخ النهاية')
        return data


class AdjustPrescriptionSerializer(serializers.Serializer):
    local_before    = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    imported_before = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    tarsia_before   = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    net_override    = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    reason          = serializers.CharField()


class AddManualRxSerializer(serializers.Serializer):
    softech_docnumber = serializers.CharField()
    # position/print_date are optional — when omitted the server auto-derives
    # placement from the transaction date relative to the claim's period:
    #   in range   → merged into that day (position='date', print_date=docdate)
    #   before     → ملحق سابق at the very beginning
    #   after      → ملحق لاحق at the very end
    position          = serializers.ChoiceField(
        choices=InsuranceClaimManualRx.POSITION_CHOICES,
        required=False, allow_null=True,
    )
    print_date        = serializers.DateField(required=False, allow_null=True)
    branchcode        = serializers.CharField(required=False, allow_blank=True)
    reason            = serializers.CharField(required=False, allow_blank=True)


class ClaimStatusSerializer(serializers.Serializer):
    status             = serializers.ChoiceField(choices=InsuranceClaim.STATUS_CHOICES)
    submitted_at       = serializers.DateTimeField(required=False, allow_null=True)
    expected_payment_date = serializers.DateField(required=False, allow_null=True)
    notes              = serializers.CharField(required=False, allow_blank=True)


class InsuranceExportProfileSerializer(serializers.ModelSerializer):
    subclient_name = serializers.CharField(source='subclient.name', read_only=True)

    class Meta:
        from .models import InsuranceExportProfile
        model = InsuranceExportProfile
        fields = '__all__'


class InsuranceItemClassificationOverrideSerializer(serializers.ModelSerializer):
    forced_category_label = serializers.CharField(source='get_forced_category_display', read_only=True)
    mode_label            = serializers.CharField(source='get_mode_display', read_only=True)
    created_by_name       = serializers.CharField(source='created_by.__str__', read_only=True)

    class Meta:
        from .models import InsuranceItemClassificationOverride
        model  = InsuranceItemClassificationOverride
        fields = [
            'id', 'item_code', 'item_name', 'mode', 'mode_label',
            'forced_category', 'forced_category_label',
            'is_active', 'reason', 'created_by_name', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_item_code(self, value):
        return (value or '').strip()
