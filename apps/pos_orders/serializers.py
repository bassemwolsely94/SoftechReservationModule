from rest_framework import serializers

from apps.catalog.models import Item
from apps.branches.models import Branch
from .models import (
    SoftechSalesOrder, SoftechSalesOrderLine, SoftechSalesOrderPayment,
    CHANNEL_TO_PTCLASSIF,
)


class LineSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(read_only=True)

    class Meta:
        model = SoftechSalesOrderLine
        fields = [
            'id', 'item', 'softech_itemcode', 'item_name', 'qty',
            'item_sale_price', 'sale_tax_pct', 'cust_discp',
            'trans_price', 'trans_price_total', 'item_sale_tax',
            'item_sale_price_tax', 'new_cost_price', 'item_expiry', 'return_of_invoice',
            'barcode', 'bonus_qty', 'pkg_price', 'batchno', 'is_reservation',
        ]
        read_only_fields = ['trans_price', 'trans_price_total', 'item_sale_tax',
                            'item_sale_price_tax', 'item_name']


class PaymentSerializer(serializers.ModelSerializer):
    softech_paymenttype = serializers.CharField(read_only=True)

    class Meta:
        model = SoftechSalesOrderPayment
        fields = ['id', 'pay_type', 'amount', 'softech_paymenttype',
                  'card_brand', 'cheque_date', 'ref_invoice', 'softech_paymentsno',
                  'currency', 'exchange_rate', 'cheque_card_no', 'internal_payserial']
        read_only_fields = ['softech_paymentsno']


class OrderSerializer(serializers.ModelSerializer):
    lines    = LineSerializer(many=True, required=False)
    payments = PaymentSerializer(many=True, required=False)
    # entered patient/claim (fresh contract orders) → stored in source_companies_raw so the
    # writer creates a companiesitems record (same path validated for cloned orders).
    claim    = serializers.DictField(write_only=True, required=False)
    softech_doccode      = serializers.CharField(read_only=True)
    softech_ptclassifcode = serializers.CharField(read_only=True)

    class Meta:
        model = SoftechSalesOrder
        fields = [
            'id', 'status', 'channel', 'doc_kind', 'client_token',
            'branch', 'softech_branchcode', 'store_code',
            'customer', 'softech_pic', 'customer_name', 'cust_branch_code',
            'softech_docnumber', 'softech_final_docnumber', 'return_of_invoice',
            'doc_value', 'doc_value_gross', 'doc_value_cogs', 'doc_value_tax',
            'doc_value_pay', 'patient_payment',
            'referral_doctor_name', 'referral_doctor_code', 'prescription_image',
            'source_call', 'source_call_item', 'notes',
            'seller_usercode', 'cashier_usercode',
            'doc_date', 'change_discount', 'payment_method',
            'alt_price', 'sell_at_cost', 'print_receipt', 'items_reservation', 'claim',
            'softech_doccode', 'softech_ptclassifcode',
            'erp_executed_at', 'erp_error', 'created_at', 'updated_at',
            'lines', 'payments',
        ]
        read_only_fields = [
            'status', 'client_token', 'softech_docnumber', 'softech_final_docnumber',
            'doc_value', 'doc_value_gross', 'doc_value_cogs', 'doc_value_tax',
            'doc_value_pay', 'patient_payment', 'erp_executed_at', 'erp_error',
        ]
        # Derived from the branch in create() — optional on input (store_code may
        # be passed to override the per-branch default).
        extra_kwargs = {
            'softech_branchcode': {'required': False},
            'store_code':         {'required': False},
        }

    def create(self, validated):
        lines = validated.pop('lines', [])
        payments = validated.pop('payments', [])
        claim = validated.pop('claim', None)
        # Map the entered patient/claim into source_companies_raw (companiesitems columns)
        # so the writer creates the contract claim record for fresh orders too.
        if claim:
            # the 12 emp-data slot columns (motalba_fields → companiesitems); comment=slot10 (التشخيص),
            # patientnationality=slot8, hi_typecode=slot12. examdate=slot11 (date). See contract_fields.py.
            keep = ('patientname', 'patientno', 'financialno', 'fileno', 'roshettano',
                    'membershipno', 'deptname', 'patientnationality', 'relativedegree',
                    'comment', 'hi_typecode')
            raw = {k: claim[k] for k in keep if claim.get(k)}
            if claim.get('examdate'):
                raw['examdate'] = {'__dt__': f"{claim['examdate']} 00:00:00"}
            if raw:
                validated['source_companies_raw'] = raw
        # default the SOFTECH branchcode/store from the Branch if not given
        branch = validated.get('branch')
        if branch and not validated.get('softech_branchcode'):
            validated['softech_branchcode'] = branch.softech_branch_id
        if branch and not validated.get('store_code'):
            # DEFAULT only: observed storecode == branchcode (e.g. '130'). storecode
            # can differ from branchcode at some installs — the client may pass an
            # explicit store_code to override. Confirm per branch on the test instance.
            bc = branch.softech_branch_id or ''
            validated['store_code'] = bc if len(bc) <= 3 else bc[:3]
        order = SoftechSalesOrder.objects.create(**validated)
        for ln in lines:
            item = ln.get('item')
            ln.setdefault('softech_itemcode', item.softech_id if item else '')
            ln['item_name'] = item.name if item else ln.get('item_name', '')
            SoftechSalesOrderLine.objects.create(order=order, **ln)
        for p in payments:
            SoftechSalesOrderPayment.objects.create(order=order, **p)
        return order
