from django.contrib import admin
from .models import SoftechSalesOrder, SoftechSalesOrderLine, SoftechSalesOrderPayment, ContractEntryConfig


class LineInline(admin.TabularInline):
    model = SoftechSalesOrderLine
    extra = 0


class PaymentInline(admin.TabularInline):
    model = SoftechSalesOrderPayment
    extra = 0


@admin.register(SoftechSalesOrder)
class SoftechSalesOrderAdmin(admin.ModelAdmin):
    list_display  = ('id', 'status', 'channel', 'doc_kind', 'softech_branchcode',
                     'softech_pic', 'doc_value', 'softech_docnumber', 'created_at')
    list_filter   = ('status', 'channel', 'doc_kind', 'softech_branchcode')
    search_fields = ('softech_pic', 'customer_name', 'softech_docnumber', 'softech_final_docnumber')
    readonly_fields = ('erp_payload', 'erp_readback', 'erp_executed_at', 'client_token')
    inlines = [LineInline, PaymentInline]


@admin.register(ContractEntryConfig)
class ContractEntryConfigAdmin(admin.ModelAdmin):
    list_display = ('personcode', 'per_visit_columns', 'approval_column', 'updated_by', 'updated_at')
    search_fields = ('personcode',)
    readonly_fields = ('updated_by', 'updated_at')

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
