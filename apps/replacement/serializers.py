from rest_framework import serializers

from .graph import _doc, build_tree
from .models import (CaseDocument, CaseException, EntitlementLedgerEntry, PostingOperation,
                     ReconstructionRun, ReplacementCalculation, ReplacementCase, ReplacementGrant,
                     ReplacementItem, ReplacementRule)


class CaseListSerializer(serializers.ModelSerializer):
    source_label = serializers.CharField(source='get_source_type_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    mode_label   = serializers.CharField(source='get_settlement_mode_display', read_only=True)
    branch_name  = serializers.SerializerMethodField()
    purchase_docnumber = serializers.SerializerMethodField()

    class Meta:
        model = ReplacementCase
        fields = ['id', 'number', 'source_type', 'source_label', 'status', 'status_label',
                  'settlement_mode', 'mode_label', 'origin', 'branchcode', 'branch_name',
                  'softech_pic', 'patient_name', 'contract_personcode', 'supplier_personcode',
                  'supplier_name', 'purchase_docnumber', 'purchase_date', 'public_value',
                  'contract_value', 'entitlement', 'applied_deduction_pct', 'supplier_tier_pct',
                  'redeemed_products', 'redeemed_cash', 'redeemed_unclassified', 'reversed_by_return',
                  'absorbed', 'customer_topup', 'outstanding', 'native_outstanding',
                  'link_confidence', 'open_exceptions', 'max_severity', 'reconstructed_at']

    def get_branch_name(self, obj):
        return (obj.branch.name_ar or obj.branch.name) if obj.branch_id else obj.branchcode

    def get_purchase_docnumber(self, obj):
        return obj.purchase_ref.docnumber if obj.purchase_ref_id else ''


class ItemSerializer(serializers.ModelSerializer):
    disposition_label = serializers.CharField(source='get_disposition_display', read_only=True)
    eligible_public_value = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = ReplacementItem
        fields = ['id', 'itemcode', 'item_name', 'disposition', 'disposition_label', 'qty_prescribed',
                  'qty_replaced', 'public_unit_price', 'contract_unit_price', 'purchase_unit_price',
                  'applied_deduction_pct', 'eligible_public_value']


class CaseDocumentSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source='get_role_display', read_only=True)
    doc = serializers.SerializerMethodField()

    class Meta:
        model = CaseDocument
        fields = ['id', 'role', 'role_label', 'status', 'origin', 'confidence', 'evidence',
                  'parent', 'amount', 'doc']

    def get_doc(self, obj):
        return _doc(obj.document)


class LedgerSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source='get_entry_type_display', read_only=True)
    document_label = serializers.SerializerMethodField()
    reverses = serializers.UUIDField(source='reverses_id', read_only=True)

    class Meta:
        model = EntitlementLedgerEntry
        fields = ['id', 'entry_type', 'type_label', 'amount', 'document_label', 'reverses',
                  'origin', 'note', 'created_at']

    def get_document_label(self, obj):
        return str(obj.document) if obj.document_id else ''


class ExceptionSerializer(serializers.ModelSerializer):
    type_label = serializers.CharField(source='get_exception_type_display', read_only=True)
    severity_label = serializers.CharField(source='get_severity_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    case_number = serializers.CharField(source='case.number', read_only=True)
    resolved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CaseException
        fields = ['id', 'case', 'case_number', 'exception_type', 'type_label', 'key', 'severity',
                  'severity_label', 'status', 'status_label', 'amount', 'detail', 'evidence',
                  'resolution', 'resolved_by_name', 'resolved_at', 'created_at', 'updated_at']

    def get_resolved_by_name(self, obj):
        return obj.resolved_by.full_name if obj.resolved_by_id else ''


class RuleSerializer(serializers.ModelSerializer):
    source_label = serializers.CharField(source='get_source_type_display', read_only=True)

    class Meta:
        model = ReplacementRule
        fields = ['id', 'rule_key', 'version', 'name', 'source_type', 'source_label', 'settlement_mode',
                  'shortage_only', 'contract_personcode', 'branchcode', 'deduction_pct', 'supplier_personcode',
                  'rounding', 'priority', 'effective_from', 'effective_until', 'is_active', 'created_at']


class GrantSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.full_name', read_only=True)
    staff_role = serializers.CharField(source='staff.role', read_only=True)

    class Meta:
        model = ReplacementGrant
        fields = ['id', 'staff', 'staff_name', 'staff_role', 'is_active', 'can_create', 'can_approve', 'can_post',
                  'allowed_sources', 'allowed_modes', 'max_case_entitlement', 'approve_limit', 'max_override_pp',
                  'notes', 'updated_at']


class CalculationSerializer(serializers.ModelSerializer):
    rule_label = serializers.SerializerMethodField()

    class Meta:
        model = ReplacementCalculation
        fields = ['id', 'seq', 'rule', 'rule_label', 'rule_deduction_pct', 'applied_deduction_pct',
                  'override_reason', 'lines', 'public_value', 'entitlement_raw', 'rounding_adj', 'entitlement',
                  'fingerprint', 'created_at']

    def get_rule_label(self, obj):
        return f'{obj.rule.name} (v{obj.rule.version})'


class OperationSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source='get_kind_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    target = serializers.SerializerMethodField()

    class Meta:
        model = PostingOperation
        fields = ['op_id', 'kind', 'kind_label', 'status', 'status_label', 'expected_value', 'result_docnumber',
                  'result', 'error', 'target', 'created_at', 'updated_at']

    def get_target(self, obj):
        if obj.supplier_invoice_id:
            i = obj.supplier_invoice
            return {'type': 'supplier_invoice', 'id': i.pk, 'number': i.invoice_number, 'status': i.status,
                    'softech_docnumber': str(i.softech_docnumber or '')}
        if obj.sales_order_id:
            o = obj.sales_order
            return {'type': 'pos_order', 'id': o.pk, 'channel': o.channel, 'status': o.status,
                    'softech_docnumber': str(o.softech_docnumber or ''),
                    'final_docnumber': str(o.softech_final_docnumber or '')}
        return None


class CaseDetailSerializer(CaseListSerializer):
    items = ItemSerializer(many=True, read_only=True)
    documents = CaseDocumentSerializer(many=True, read_only=True)
    ledger = LedgerSerializer(many=True, read_only=True)
    exceptions = ExceptionSerializer(many=True, read_only=True)
    operations = OperationSerializer(many=True, read_only=True)
    current_calc = CalculationSerializer(read_only=True)
    tree = serializers.SerializerMethodField()
    reconciliation = serializers.SerializerMethodField()
    workflow = serializers.SerializerMethodField()

    class Meta(CaseListSerializer.Meta):
        fields = CaseListSerializer.Meta.fields + ['correlation_id', 'rules_version', 'items',
                                                   'documents', 'ledger', 'exceptions', 'tree',
                                                   'reconciliation', 'operations', 'current_calc',
                                                   'workflow', 'version', 'locked_at', 'is_shortage_item',
                                                   'prescription_no', 'approval_no', 'notes']

    def get_workflow(self, obj):
        """Live-workflow state for the UI. `can` only HIDES buttons — every action is re-checked
        server-side (authz.require)."""
        from . import authz, legs
        from .workflow import approval_route
        staff = self.context.get('staff')
        live = obj.origin == ReplacementCase.ORIGIN_LIVE
        out = {'live': live, 'posting_enabled': legs.posting_enabled(),
               'created_by': obj.created_by.full_name if obj.created_by_id else '',
               'approved_by': obj.approved_by.full_name if obj.approved_by_id else '',
               'approved_at': obj.approved_at, 'locked': bool(obj.locked_at)}
        if obj.approval_request_id:
            r = obj.approval_request
            out['approval'] = {'id': r.pk, 'status': r.status, 'step': r.current_step_order,
                               'workflow': r.workflow.name_ar, 'reasons': r.context_data.get('reasons', [])}
        if live and obj.current_calc_id and obj.status == ReplacementCase.STATUS_CALCULATED:
            wf, reasons = approval_route(obj)
            out['route_preview'] = {'workflow': wf, 'reasons': reasons}
        if live:
            out['available'] = {k: str(v) for k, v in legs.available(obj).items()}
            out['voucher_instruction'] = legs.voucher_instruction(obj)
        own = staff is not None and obj.created_by_id == staff.pk
        out['can'] = {a: bool(staff) and authz.allows(staff, a) for a in ('create', 'edit', 'approve', 'post')}
        out['can']['approve'] = out['can']['approve'] and not own          # maker-checker
        return out

    def get_tree(self, obj):
        return build_tree(obj)

    def get_reconciliation(self, obj):
        """Expected vs posted per leg (doc 25 §9) — all figures are already on the case."""
        return [
            {'leg': 'الرصيد (الشراء)', 'expected': str(obj.entitlement),
             'actual': str(obj.entitlement), 'ok': True},
            {'leg': 'دفتر الرصيد مقابل SOFTECH', 'expected': str(obj.native_outstanding),
             'actual': str(obj.outstanding), 'ok': abs(obj.outstanding - obj.native_outstanding) <= 0.01},
            {'leg': 'صرف منتجات', 'expected': '', 'actual': str(obj.redeemed_products), 'ok': True},
            {'leg': 'صرف نقدي', 'expected': '', 'actual': str(obj.redeemed_cash), 'ok': True},
            {'leg': 'صرف غير مصنّف', 'expected': '0.00', 'actual': str(obj.redeemed_unclassified),
             'ok': obj.redeemed_unclassified == 0},
            {'leg': 'فروق مستوعبة', 'expected': '', 'actual': str(obj.absorbed), 'ok': True},
            {'leg': 'دفعة إضافية من المريض', 'expected': '', 'actual': str(obj.customer_topup), 'ok': True},
        ]


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReconstructionRun
        fields = ['id', 'started_at', 'finished_at', 'status', 'params', 'counts', 'rules_version',
                  'triggered_by', 'notes']
