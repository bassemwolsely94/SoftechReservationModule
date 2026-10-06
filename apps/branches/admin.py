from django.contrib import admin
from .models import Branch, BranchSettings


class BranchSettingsInline(admin.StackedInline):
    model  = BranchSettings
    extra  = 0
    fields = (
        'allow_reservations', 'allow_transfers',
        'allow_vouchers', 'allow_stockcount', 'allow_shortage',
        'notifications_enabled',
    )
    verbose_name        = 'إعدادات الفرع'
    verbose_name_plural = 'إعدادات الفرع'
    can_delete          = False


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display  = ('name_ar', 'name', 'softech_branch_id', 'kind', 'pos_enabled',
                     'is_active', 'is_operational', 'can_transact')
    list_filter   = ('kind', 'pos_enabled', 'is_active', 'is_operational')
    list_editable = ('kind', 'pos_enabled')
    search_fields = ('name', 'name_ar', 'softech_branch_id', 'code')
    ordering      = ('name',)
    inlines       = [BranchSettingsInline]

    @admin.display(boolean=True, description='يمكن التعامل')
    def can_transact(self, obj):
        return obj.can_transact


@admin.register(BranchSettings)
class BranchSettingsAdmin(admin.ModelAdmin):
    list_display  = (
        'branch', 'notifications_enabled',
        'allow_reservations', 'allow_transfers',
        'allow_vouchers', 'allow_stockcount', 'allow_shortage',
    )
    list_filter   = ('notifications_enabled',)
    search_fields = ('branch__name', 'branch__name_ar')
