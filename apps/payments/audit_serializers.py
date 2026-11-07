from rest_framework import serializers
from .models import BankStatementImport, BankStatementLine, PaymentException
from .statement_parser import ALLOWED_EXTENSIONS, MAX_STATEMENT_BYTES, file_extension
from apps.data_lifecycle.display import RetentionNoteMixin


class BankStatementImportSerializer(RetentionNoteMixin, serializers.ModelSerializer):
    retention_fields = ('raw_file',)
    imported_by_name = serializers.CharField(source='imported_by.full_name', read_only=True, default='')
    branch_name      = serializers.CharField(source='branch.name',           read_only=True)
    status_label     = serializers.CharField(source='get_status_display',    read_only=True)
    payment_method_label = serializers.CharField(source='get_payment_method_display', read_only=True)
    match_rate       = serializers.SerializerMethodField()   # percent 0–100

    class Meta:
        model  = BankStatementImport
        fields = [
            'id', 'branch', 'branch_name', 'bank_name', 'account_number',
            'payment_method', 'payment_method_label', 'statement_from', 'statement_to', 'raw_file',
            'status', 'status_label', 'total_lines', 'matched_lines', 'unmatched_lines',
            'match_rate', 'error_message',
            'imported_by', 'imported_by_name', 'imported_at', 'completed_at',
        ]
        read_only_fields = [
            'status', 'total_lines', 'matched_lines', 'unmatched_lines',
            'error_message', 'imported_at', 'completed_at',
            'imported_by',          # set on upload (Batch 4, Z-10c — a PATCH rewrote it)
        ]

    def validate_raw_file(self, f):
        if file_extension(f.name) not in ALLOWED_EXTENSIONS:
            raise serializers.ValidationError('نوع الملف غير مدعوم — ارفع ملف csv أو xlsx.')
        if f.size and f.size > MAX_STATEMENT_BYTES:
            raise serializers.ValidationError('الملف أكبر من 10 ميجابايت.')
        return f

    def validate(self, attrs):
        start = attrs.get('statement_from', getattr(self.instance, 'statement_from', None))
        end   = attrs.get('statement_to',   getattr(self.instance, 'statement_to', None))
        if start and end and start > end:
            raise serializers.ValidationError({'statement_to': ['«إلى تاريخ» يجب أن يكون بعد «من تاريخ» أو مساوياً له.']})
        return attrs

    def get_match_rate(self, obj) -> float:
        if obj.total_lines:
            return round(obj.matched_lines / obj.total_lines * 100, 1)
        return 0.0


class BankStatementLineSerializer(serializers.ModelSerializer):
    matched_payment_ref = serializers.CharField(
        source='matched_payment.reference_number', read_only=True, default=''
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
        source='payment.reference_number', read_only=True, default=''
    )
    exception_type_label = serializers.CharField(source='get_exception_type_display', read_only=True)
    status_label         = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model  = PaymentException
        fields = [
            'id', 'payment', 'payment_ref', 'payment_amount',
            'statement_line', 'exception_type', 'exception_type_label', 'severity', 'anomaly_score',
            'detail', 'status', 'status_label', 'assigned_to', 'assigned_to_name',
            'resolved_by', 'resolved_by_name', 'resolved_at', 'resolution_notes',
            'abuse_flag_id', 'created_at',
        ]
        read_only_fields = ['anomaly_score', 'abuse_flag_id', 'created_at', 'resolved_at']


class ManualMatchSerializer(serializers.Serializer):
    payment_id = serializers.IntegerField()
