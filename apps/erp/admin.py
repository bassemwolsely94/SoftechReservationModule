from django.contrib import admin
from .models import ERPTransaction, ERPTransactionLine, LocalCustomer


# ── ERPTransactionLine inline ──────────────────────────────────────────────────

class ERPTransactionLineInline(admin.TabularInline):
    model         = ERPTransactionLine
    extra         = 0
    readonly_fields = ['item', 'item_code', 'item_name', 'quantity', 'unit_price', 'line_total', 'store_code']
    fields        = ['item_code', 'item_name', 'quantity', 'unit_price', 'line_total']
    can_delete    = False

    def has_add_permission(self, request, obj=None):
        return False


# ── ERPTransaction admin ───────────────────────────────────────────────────────

@admin.register(ERPTransaction)
class ERPTransactionAdmin(admin.ModelAdmin):
    list_display  = [
        'transaction_id', 'doccode', 'softech_branch_code',
        'phcode', 'transaction_date', 'total_amount', 'synced_at',
    ]
    list_filter   = ['doccode', 'branch', 'transaction_date']
    search_fields = ['transaction_id', 'phcode', 'reference_number']
    readonly_fields = [
        'transaction_id', 'doccode', 'reference_number',
        'softech_branch_code', 'branch', 'phcode',
        'local_customer', 'personsdata_customer',
        'transaction_date', 'total_amount', 'synced_at',
    ]
    ordering      = ['-transaction_date']
    inlines       = [ERPTransactionLineInline]
    date_hierarchy = 'transaction_date'

    def has_add_permission(self, request):
        return False  # Read-only — ERP is source of truth

    def has_delete_permission(self, request, obj=None):
        return False


# ── LocalCustomer admin ────────────────────────────────────────────────────────

@admin.register(LocalCustomer)
class LocalCustomerAdmin(admin.ModelAdmin):
    list_display  = [
        'phcode', 'name', 'phone', 'erp_branch_code',
        'customer_type', 'is_active', 'linked_customer', 'synced_at',
    ]
    list_filter   = ['is_active', 'customer_type', 'branch']
    search_fields = ['phcode', 'name', 'phone', 'phone_alt']
    readonly_fields = [
        'phcode', 'name', 'phone', 'phone_alt',
        'erp_branch_code', 'branch', 'address', 'area',
        'customer_type', 'is_active', 'synced_at',
    ]
    ordering      = ['name']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
