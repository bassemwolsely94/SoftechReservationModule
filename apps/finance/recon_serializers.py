"""
apps/finance/recon_serializers.py — DRF serializers for the A/P–A/R reconciliation
module (Phase-C batch 4). Read-only presentation of the mirror + engine output.
See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
from rest_framework import serializers

from .models import (
    ReconParty, APInvoice, Payment, Allocation, ReconciliationRun,
    MatchCandidate, MatchEvidence, ReconException,
)
from . import recon_labels as L


class _WhoWhereMixin(serializers.Serializer):
    """Branch name + the SOFTECH user who created the document (code and name)."""
    branch_name = serializers.SerializerMethodField()
    user_name   = serializers.SerializerMethodField()

    def get_branch_name(self, obj):
        return L.branch_name(obj.branchcode)

    def get_user_name(self, obj):
        return L.user_name(obj.usercode)


class ReconPartySerializer(serializers.ModelSerializer):
    party_type_display = serializers.CharField(source='get_party_type_display', read_only=True)

    class Meta:
        model  = ReconParty
        fields = ['id', 'party_type', 'party_type_display', 'softech_personcode',
                  'name', 'ptclassifcode', 'opening_balance', 'opening_balance_date',
                  'softech_balance', 'softech_balance_at', 'is_active', 'synced_at']


class _InvoiceBindingsMixin(serializers.Serializer):
    """Returns bound to a purchase (ReturnLink) + receipts that name it (recon_bindings)."""
    open_return_credit = serializers.DecimalField(max_digits=18, decimal_places=3, read_only=True)
    net_remaining      = serializers.DecimalField(max_digits=18, decimal_places=3, read_only=True)
    returns_bound      = serializers.ReadOnlyField()
    bound_receipts     = serializers.SerializerMethodField()

    def get_bound_receipts(self, obj):
        return [f'{r.branchcode}/{r.cheqsno} ({r.voucher_date}, {r.amount})' for r in obj.bound_receipts.all()]


class _PaymentBindingsMixin(serializers.Serializer):
    """Refunds bound to a payment (matched NET) + correction-chain partners."""
    net_amount = serializers.DecimalField(max_digits=18, decimal_places=3, read_only=True)


class APInvoiceSerializer(_InvoiceBindingsMixin, _WhoWhereMixin, serializers.ModelSerializer):
    outstanding      = serializers.ReadOnlyField()
    remaining_calc   = serializers.DecimalField(max_digits=18, decimal_places=3, read_only=True)
    is_fully_settled = serializers.ReadOnlyField()
    party_code       = serializers.CharField(source='party.softech_personcode', read_only=True)
    party_name       = serializers.CharField(source='party.name', read_only=True)

    class Meta:
        model  = APInvoice
        fields = ['id', 'party', 'party_code', 'party_name', 'party_type',
                  'branchcode', 'branch_name', 'doccode', 'docnumber', 'docdate', 'docnumber2',
                  'doc_value', 'doc_value_pay', 'outstanding', 'is_fully_settled',
                  'is_return', 'fat_status', 'due_date', 'usercode', 'user_name', 'comments',
                  'trans_time', 'remaining_calc', 'open_return_credit', 'net_remaining', 'returns_bound', 'bound_receipts', 'source_hash', 'synced_at']


class PaymentSerializer(_PaymentBindingsMixin, _WhoWhereMixin, serializers.ModelSerializer):
    allocated_amount   = serializers.ReadOnlyField()
    unallocated_amount = serializers.ReadOnlyField()
    direction_display  = serializers.CharField(source='get_direction_display', read_only=True)
    party_code         = serializers.CharField(source='party.softech_personcode', read_only=True)
    party_name         = serializers.CharField(source='party.name', read_only=True)

    class Meta:
        model  = Payment
        fields = ['id', 'party', 'party_code', 'party_name', 'party_type',
                  'branchcode', 'branch_name', 'cheqsno', 'cheqno', 'ourcheqsno',
                  'usercode', 'user_name',
                  'financial_doc_code', 'cheqtype', 'direction', 'direction_display',
                  'voucher_date', 'bankcode', 'amount', 'note', 'person_new_bal',
                  'bank_new_bal', 'block_inv', 'is_unallocated',
                  'allocated_amount', 'unallocated_amount', 'trans_time', 'net_amount', 'refunded_amount', 'bind_note', 'chain_partners', 'bound_payment', 'bound_invoice', 'chain_role', 'chain_note', 'source_hash', 'synced_at']


class AllocationSerializer(serializers.ModelSerializer):
    origin_display = serializers.CharField(source='get_origin_display', read_only=True)

    class Meta:
        model  = Allocation
        fields = ['id', 'payment', 'invoice', 'amount', 'cumulative_paid',
                  'origin', 'origin_display', 'candidate', 'created_at']


class MatchEvidenceSerializer(serializers.ModelSerializer):
    signal_display  = serializers.CharField(source='get_signal_display', read_only=True)
    outcome_display = serializers.CharField(source='get_outcome_display', read_only=True)

    class Meta:
        model  = MatchEvidence
        fields = ['id', 'signal', 'signal_display', 'outcome', 'outcome_display',
                  'weight', 'contribution', 'detail']


class _InvoiceMiniSerializer(_InvoiceBindingsMixin, _WhoWhereMixin, serializers.ModelSerializer):
    outstanding = serializers.ReadOnlyField()
    remaining_calc = serializers.DecimalField(max_digits=18, decimal_places=3, read_only=True)

    class Meta:
        model  = APInvoice
        fields = ['id', 'branchcode', 'branch_name', 'doccode', 'docnumber', 'docdate',
                  'docnumber2', 'doc_value', 'doc_value_pay', 'outstanding',
                  'usercode', 'user_name', 'comments', 'is_return', 'trans_time', 'remaining_calc', 'open_return_credit', 'net_remaining', 'returns_bound', 'bound_receipts']


class _PaymentMiniSerializer(_PaymentBindingsMixin, _WhoWhereMixin, serializers.ModelSerializer):
    unallocated_amount = serializers.ReadOnlyField()

    class Meta:
        model  = Payment
        fields = ['id', 'branchcode', 'branch_name', 'cheqsno', 'cheqno', 'ourcheqsno',
                  'voucher_date', 'amount', 'note', 'financial_doc_code',
                  'unallocated_amount', 'usercode', 'user_name', 'cheqtype',
                  'chain_role', 'chain_note', 'trans_time', 'net_amount', 'refunded_amount', 'bind_note', 'chain_partners', 'bound_payment', 'bound_invoice']


class MatchCandidateSerializer(serializers.ModelSerializer):
    confidence_class_display = serializers.CharField(source='get_confidence_class_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    invoice_detail = _InvoiceMiniSerializer(source='invoice', read_only=True)
    payment_detail = _PaymentMiniSerializer(source='payment', read_only=True)
    evidence       = MatchEvidenceSerializer(many=True, read_only=True)
    party_code     = serializers.CharField(source='party.softech_personcode', read_only=True)
    party_name     = serializers.CharField(source='party.name', read_only=True)
    strategy_display = serializers.CharField(source='get_strategy_display', read_only=True)
    allocation     = serializers.SerializerMethodField()
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model  = MatchCandidate
        fields = ['id', 'run', 'party', 'party_code', 'invoice', 'payment',
                  'invoice_detail', 'payment_detail', 'proposed_amount',
                  'confidence_score', 'confidence_class', 'confidence_class_display',
                  'status', 'status_display', 'rules_version', 'evidence', 'allocation',
                  'strategy', 'strategy_display', 'group_key', 'party_name',
                  'decided_by', 'decided_by_name', 'decided_at', 'decision_note', 'created_at']

    def get_decided_by_name(self, obj):
        return obj.decided_by.full_name if obj.decided_by_id and obj.decided_by else ''

    def get_allocation(self, obj):
        """The allocation this candidate produced (for the write-to-SOFTECH action)."""
        a = obj.allocations.all().first() if obj.pk else None
        if not a:
            return None
        return {'id': a.id, 'origin': a.origin, 'amount': str(a.amount)}


class ReconExceptionSerializer(serializers.ModelSerializer):
    exception_type_display = serializers.CharField(source='get_exception_type_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    status_display   = serializers.CharField(source='get_status_display', read_only=True)
    party_code       = serializers.CharField(source='party.softech_personcode', read_only=True, default='')
    party_name       = serializers.CharField(source='party.name', read_only=True, default='')
    invoice_detail   = _InvoiceMiniSerializer(source='invoice', read_only=True)
    payment_detail   = _PaymentMiniSerializer(source='payment', read_only=True)

    class Meta:
        model  = ReconException
        fields = ['id', 'run', 'party', 'party_code', 'party_name', 'invoice', 'payment',
                  'invoice_detail', 'payment_detail',
                  'exception_type', 'exception_type_display', 'severity',
                  'severity_display', 'anomaly_score', 'detail', 'status',
                  'status_display', 'created_at']


class ReconciliationRunSerializer(serializers.ModelSerializer):
    mode_display   = serializers.CharField(source='get_mode_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = ReconciliationRun
        fields = ['id', 'mode', 'mode_display', 'status', 'status_display',
                  'party_type', 'party', 'date_from', 'date_to', 'rules_version',
                  'params', 'counts', 'started_at', 'finished_at', 'triggered_by', 'notes']
