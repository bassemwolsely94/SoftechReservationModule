from django.contrib import admin

from .models import SoftechIdentityClaim, PersonalWidget, DocumentCommentEdit, DocumentRevision


@admin.register(DocumentRevision)
class DocumentRevisionAdmin(admin.ModelAdmin):
    list_display = ('code', 'staff', 'kind', 'branchcode', 'doccode', 'docnumber',
                    'status', 'hq_result', 'branch_result', 'updated_at')
    list_filter = ('kind', 'status', 'hq_result')
    search_fields = ('code', 'docnumber', 'staff__user__username')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(DocumentCommentEdit)
class DocumentCommentEditAdmin(admin.ModelAdmin):
    list_display = ('id', 'staff', 'branchcode', 'doccode', 'docnumber',
                    'new_comment', 'hq_result', 'branch_result', 'created_at')
    list_filter = ('hq_result', 'branch_result', 'doccode')
    search_fields = ('docnumber', 'new_comment', 'old_comment', 'staff__user__username')
    readonly_fields = [f.name for f in DocumentCommentEdit._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False   # immutable audit trail


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
