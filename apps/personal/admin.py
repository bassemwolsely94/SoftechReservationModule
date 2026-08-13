from django.contrib import admin

from .models import SoftechIdentityClaim, PersonalWidget


@admin.register(SoftechIdentityClaim)
class SoftechIdentityClaimAdmin(admin.ModelAdmin):
    list_display = ('id', 'staff', 'kind', 'person_code', 'label', 'status',
                    'reviewed_by', 'created_at')
    list_filter = ('kind', 'status')
    search_fields = ('person_code', 'label', 'staff__user__username')
    autocomplete_fields = ()
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PersonalWidget)
class PersonalWidgetAdmin(admin.ModelAdmin):
    list_display = ('id', 'staff', 'widget_type', 'identity', 'column',
                    'position', 'size', 'enabled')
    list_filter = ('widget_type', 'size', 'enabled')
    search_fields = ('staff__user__username', 'title')
    readonly_fields = ('created_at', 'updated_at')
