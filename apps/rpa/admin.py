from django.contrib import admin

from . import models


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.RpaScreen)
class RpaScreenAdmin(ReadOnlyAdmin):
    list_display = ('key', 'title_ar', 'enabled', 'live')


@admin.register(models.RpaRecipe)
class RpaRecipeAdmin(ReadOnlyAdmin):
    list_display = ('screen', 'version', 'status', 'approved_by', 'approved_at')


@admin.register(models.RpaJob)
class RpaJobAdmin(ReadOnlyAdmin):
    list_display = ('id', 'screen', 'branch', 'status', 'dry_run', 'created_at')


@admin.register(models.RpaDocument)
class RpaDocumentAdmin(ReadOnlyAdmin):
    list_display = ('id', 'job', 'seq', 'status')


@admin.register(models.RpaLine)
class RpaLineAdmin(ReadOnlyAdmin):
    list_display = ('id', 'document', 'row_no', 'itemcode', 'qty', 'status')


@admin.register(models.RpaDevice)
class RpaDeviceAdmin(ReadOnlyAdmin):
    # token_hash is never shown.
    list_display = ('id', 'label', 'staff', 'last_seen_at', 'revoked_at')
    fields = ('label', 'staff', 'created_by', 'created_at', 'last_seen_at', 'revoked_at')
    readonly_fields = fields


@admin.register(models.RpaRun)
class RpaRunAdmin(ReadOnlyAdmin):
    list_display = ('id', 'document', 'mode', 'outcome', 'started_at', 'finished_at')


@admin.register(models.RpaScreenshot)
class RpaScreenshotAdmin(ReadOnlyAdmin):
    list_display = ('id', 'run', 'step_index', 'created_at')


from .portal import models as portal_models  # noqa: E402 — portal models live in a sub-module

for _m in (portal_models.SupplierPortal, portal_models.PortalAccount, portal_models.BuyList,
           portal_models.BuyListLine, portal_models.PortalJob, portal_models.PortalBasket,
           portal_models.PortalLine, portal_models.PortalRun):
    admin.site.register(_m, ReadOnlyAdmin)
