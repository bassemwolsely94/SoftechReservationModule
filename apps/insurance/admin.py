from django.contrib import admin
from .models import (
    InsuranceClient, InsuranceSubClient, InsuranceContract,
    InsuranceClaim, InsuranceClaimPrescription, InsuranceClaimLine,
    InsuranceClaimAdjustment, InsuranceClaimManualRx,
    InsuranceClaimExclusion, InsuranceClaimSupplement,
    InsurancePayment, InsuranceDeduction,
    InsuranceParentClient, InsuranceClaimBillingGroup,
    MotalbaCache, CompaniesItemsCache,
    InsuranceApplyMasterRun, InsuranceClaimLineBackup,
    InsuranceExportProfile, InsurancePivotTemplate,
)

admin.site.register(InsuranceExportProfile)
admin.site.register(InsurancePivotTemplate)


class InsuranceSubClientInline(admin.TabularInline):
    model = InsuranceSubClient
    extra = 1


@admin.register(InsuranceClient)
class InsuranceClientAdmin(admin.ModelAdmin):
    list_display  = ['name', 'softech_personcode', 'is_active']
    search_fields = ['name', 'softech_personcode']
    inlines       = [InsuranceSubClientInline]


@admin.register(InsuranceContract)
class InsuranceContractAdmin(admin.ModelAdmin):
    list_display  = ['subclient', 'effective_from', 'effective_to',
                     'local_discount_pct', 'imported_discount_pct', 'tarsia_discount_pct']
    list_filter   = ['subclient__client']


class InsuranceClaimPrescriptionInline(admin.TabularInline):
    model  = InsuranceClaimPrescription
    extra  = 0
    fields = ['sequence', 'softech_docnumber', 'softech_docdate', 'patient_name',
              'local_before', 'imported_before', 'tarsia_before', 'net_after']
    readonly_fields = fields


@admin.register(InsuranceClaim)
class InsuranceClaimAdmin(admin.ModelAdmin):
    list_display  = ['claim_number', 'subclient', 'period_from', 'period_to',
                     'final_rx_count', 'final_net_after', 'status']
    list_filter   = ['status', 'subclient__client']
    search_fields = ['claim_number', 'softech_motalba_no']
    readonly_fields = ['snapshot_rx_count', 'snapshot_net_after',
                       'final_rx_count', 'final_net_after', 'imported_at']
    inlines       = [InsuranceClaimPrescriptionInline]


@admin.register(InsurancePayment)
class InsurancePaymentAdmin(admin.ModelAdmin):
    list_display = ['claim', 'payment_date', 'amount', 'reference']


@admin.register(InsuranceDeduction)
class InsuranceDeductionAdmin(admin.ModelAdmin):
    list_display = ['claim', 'prescription', 'reason_code', 'amount']


@admin.register(InsuranceParentClient)
class InsuranceParentClientAdmin(admin.ModelAdmin):
    list_display  = ['name', 'softech_personcode', 'is_active']
    search_fields = ['name', 'softech_personcode']


@admin.register(InsuranceClaimBillingGroup)
class InsuranceClaimBillingGroupAdmin(admin.ModelAdmin):
    list_display  = ['claim', 'code', 'name', 'rx_count', 'net_after']
    list_filter   = ['claim__subclient__client']
    search_fields = ['code', 'name', 'claim__claim_number']


@admin.register(MotalbaCache)
class MotalbaCacheAdmin(admin.ModelAdmin):
    list_display  = ['motalbano', 'personcode', 'docnumber', 'docdate',
                     'doccode', 'docvalue_grandtotal', 'docvaluerequired', 'synced_at']
    list_filter   = ['doccode', 'personcode']
    search_fields = ['motalbano', 'docnumber', 'personcode']
    date_hierarchy = 'docdate'


@admin.register(CompaniesItemsCache)
class CompaniesItemsCacheAdmin(admin.ModelAdmin):
    list_display  = ['docnumber', 'branchcode', 'patientname', 'roshettano',
                     'deptname', 'relativedegree', 'docdate', 'synced_at']
    search_fields = ['docnumber', 'patientname', 'roshettano', 'membershipno']
    date_hierarchy = 'docdate'


@admin.register(InsuranceApplyMasterRun)
class InsuranceApplyMasterRunAdmin(admin.ModelAdmin):
    list_display  = ['id', 'claim', 'applied_at', 'lines_updated',
                     'prescriptions_updated', 'net_before', 'net_after', 'reverted']
    list_filter   = ['reverted', 'apply_price', 'apply_category']
    search_fields = ['claim__claim_number']
    readonly_fields = ['applied_at', 'reverted_at']


from .models import InsuranceItemClassificationOverride


@admin.register(InsuranceItemClassificationOverride)
class InsuranceItemClassificationOverrideAdmin(admin.ModelAdmin):
    list_display  = ['item_code', 'item_name', 'mode', 'forced_category', 'is_active',
                     'reason', 'created_by', 'updated_at']
    list_filter   = ['is_active', 'mode', 'forced_category']
    search_fields = ['item_code', 'item_name']
    readonly_fields = ['created_at', 'updated_at']
