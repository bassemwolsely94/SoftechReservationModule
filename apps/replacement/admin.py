from django.contrib import admin

from .models import (CaseDocument, CaseException, EntitlementLedgerEntry, ReconstructionRun,
                     ReplacementCase, ReplacementItem)


class ItemInline(admin.TabularInline):
    model = ReplacementItem
    extra = 0
    can_delete = False


class DocInline(admin.TabularInline):
    model = CaseDocument
    extra = 0
    raw_id_fields = ('document', 'parent')


@admin.register(ReplacementCase)
class ReplacementCaseAdmin(admin.ModelAdmin):
    list_display = ('number', 'source_type', 'status', 'branchcode', 'softech_pic', 'supplier_personcode',
                    'entitlement', 'outstanding', 'open_exceptions')
    list_filter = ('status', 'source_type', 'supplier_personcode', 'branchcode', 'origin')
    search_fields = ('number', 'softech_pic', 'patient_name')
    raw_id_fields = ('branch', 'customer', 'purchase_ref', 'purchase_invoice')
    inlines = [ItemInline, DocInline]


@admin.register(EntitlementLedgerEntry)
class LedgerAdmin(admin.ModelAdmin):
    """Read-only: the ledger is append-only and written only by apps.replacement.ledger."""
    list_display = ('case', 'entry_type', 'amount', 'document', 'origin', 'created_at')
    list_filter = ('entry_type', 'origin')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CaseException)
class CaseExceptionAdmin(admin.ModelAdmin):
    list_display = ('case', 'exception_type', 'severity', 'status', 'amount', 'created_at')
    list_filter = ('exception_type', 'severity', 'status')


@admin.register(ReconstructionRun)
class RunAdmin(admin.ModelAdmin):
    list_display = ('id', 'started_at', 'finished_at', 'status', 'rules_version')
