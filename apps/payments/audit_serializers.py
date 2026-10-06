from rest_framework import serializers
from .models import BankStatementImport, BankStatementLine, PaymentException


class BankStatementImportSerializer(serializers.ModelSerializer):
    imported_by_name = serializers.CharField(source='imported_by.full_name', read_only=True, default='')
    branch_name      = serializers.CharField(source='branch.name',           read_only=True)
    match_rate       = serializers.SerializerMethodField()

    class Meta:
        model  = BankStatementImport
        fields = [
            'id', 'branch', 'branch_name', 'bank_name', 'account_number',
            'payment_method', 'statement_from', 'statement_to', 'raw_file',
            'status', 'total_lines', 'matched_lines', 'unmatched_lines',
            'match_rate', 'error_message',
            'imported_by', 'imported_by_name', 'imported_at', 'completed_at',
        ]
        read_only_fields = [
            'status', 'total_lines', 'matched_lines', 'unmatched_lines',
            'error_message', 'imported_at', 'completed_at',
        ]

    def get_match_rate(self, obj) -> float:
        if obj.total_lines:
            return round(obj.matched_lines / obj.total_lines * 100, 1)
        return 0.0


class BankStatementLineSerializer(serializers.ModelSerializer):
    matched_payment_ref = serializers.CharField(
        source='matched_payment.transaction_ref', read_only=True, default=''
    )
    matched_by_name = serializers.CharField(
        source='matched_by.full_name', read_only=True, default=''
    )

    class Meta:
        model  = BankStatementLine
        fields = [
            'id', 'statement_import', 'transaction_date', 'value_date',
            'reference', 'description', 'debit', 'credit', 'balance',
            'matched_payment', 'matched_payment_ref',
            'match_confidence', 'match_method',
            'matched_by', 'matched_by_name', 'matched_at',
        ]
        read_only_fields = [
            'match_confidence', 'match_method', 'matched_at',
        ]


class PaymentExceptionSerializer(serializers.ModelSerializer):
    assigned_to_name = serializers.CharField(
        source='assigned_to.full_name', read_only=True, default=''
    )
    resolved_by_name = serializers.CharField(
        source='resolved_by.full_name', read_only=True, default=''
    )
    payment_amount = serializers.DecimalField(
        source='payment.amount', max_digits=12, decimal_places=2,
        read_only=True, default=None,
    )
    payment_ref = serializers.CharField(
        source='payment.transaction_ref', read_only=True, default=''
    )

    class Meta:
        model  = PaymentException
        fields = [
            'id', 'payment', 'payment_ref', 'payment_amount',
            'statement_line', 'exception_type', 'severity', 'anomaly_score',
            'detail', 'status', 'assigned_to', 'assigned_to_name',
            'resolved_by', 'resolved_by_name', 'resolved_at', 'resolution_notes',
            'abuse_flag_id', 'created_at',
        ]
        read_only_fields = ['anomaly_score', 'abuse_flag_id', 'created_at', 'resolved_at']


class ManualMatchSerializer(serializers.Serializer):
    payment_id = serializers.IntegerField()
