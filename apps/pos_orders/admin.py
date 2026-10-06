from django.contrib import admin
from .models import SoftechSalesOrder, SoftechSalesOrderLine, SoftechSalesOrderPayment


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
