from django.contrib import admin
from .models import BranchCopyWrite, Customer, CustomerHealthProfile, CustomerNote, CustomerStatusDrift, MergeCandidate, PointsRemoval


@admin.register(CustomerHealthProfile)
class CustomerHealthProfileAdmin(admin.ModelAdmin):
    list_display  = (
        'customer', 'is_chronic_display', 'has_diabetes', 'has_hypertension',
        'has_cardiovascular', 'polypharmacy_flag', 'manually_overridden', 'last_computed_at',
    )
    list_filter   = (
        'has_diabetes', 'has_hypertension', 'has_cardiovascular',
        'has_thyroid', 'has_cholesterol', 'has_asthma', 'has_psychiatric',
        'has_oncology', 'pregnancy_flag', 'polypharmacy_flag', 'manually_overridden',
    )
    search_fields = ('customer__name', 'customer__phone', 'customer__softech_pic')
    readonly_fields = ('last_computed_at', 'created_at', 'updated_at', 'condition_confidence')
    raw_id_fields   = ('customer',)

    fieldsets = (
        ('العميل', {
            'fields': ('customer',),
        }),
        ('الحالات المزمنة — محسوبة تلقائياً', {
            'fields': (
                ('has_diabetes', 'has_hypertension', 'has_cardiovascular'),
                ('has_thyroid', 'has_cholesterol', 'has_asthma'),
                ('has_psychiatric', 'has_epilepsy', 'has_osteoporosis'),
                ('has_renal', 'has_oncology', 'has_gerd'),
                ('has_anemia', 'has_anticoagulant', 'has_immunosuppressant'),
                'has_other_chronic',
                'condition_confidence',
            ),
        }),
        ('تنبيهات خاصة — يُعدَّل يدوياً بواسطة الصيدلاني', {
            'fields': (
                ('pregnancy_flag', 'lactation_flag', 'pediatric_patient', 'polypharmacy_flag'),
                'known_allergies', 'declared_allergies_text',
            ),
        }),
        ('الأدوية النشطة', {
            'fields': ('active_medications',),
            'classes': ('collapse',),
        }),
        ('تدقيق', {
            'fields': ('manually_overridden', 'updated_by',
                       'last_computed_at', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='مزمن', boolean=True)
    def is_chronic_display(self, obj):
        return obj.is_chronic


@admin.register(CustomerStatusDrift)
class CustomerStatusDriftAdmin(admin.ModelAdmin):
    """B7 step 2 — read-only view of HQ vs branch-node differences (filled by the daily check)."""
    list_display = ('pic', 'node_branch', 'field', 'hq_value', 'node_value', 'direction',
                    'first_seen', 'last_seen', 'resolved_at')
    list_filter = ('direction', 'field', 'node_branch', ('resolved_at', admin.EmptyFieldListFilter))
    search_fields = ('pic',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(BranchCopyWrite)
class BranchCopyWriteAdmin(admin.ModelAdmin):
    """B7 step 3 — every attempt to copy HQ flags onto a branch copy (read-only record)."""
    list_display = ('pic', 'node_branch', 'status', 'requested_by', 'created_at')
    list_filter = ('status', 'node_branch')
    search_fields = ('pic',)
    readonly_fields = ('pic', 'node_branch', 'before', 'target', 'after', 'status', 'error', 'requested_by', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PointsRemoval)
class PointsRemovalAdmin(admin.ModelAdmin):
    """B7 Option B — every removal from the points system at HQ (read-only record)."""
    list_display = ('pic', 'status', 'flag_before', 'balance_before', 'points_cleared', 'balance_after',
                    'requested_by', 'created_at')
    list_filter = ('status',)
    search_fields = ('pic',)
    readonly_fields = [f.name for f in PointsRemoval._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MergeCandidate)
class MergeCandidateAdmin(admin.ModelAdmin):
    """B7 duplicate-code merge queue — review happens in the app (/customers/merge, maker-checker)."""
    list_display = ('old_pic', 'main_pic', 'strength', 'status', 'main_swapped', 'marked_by', 'approved_by',
                    'updated_at')
    list_filter = ('status', 'strength', 'main_swapped')
    search_fields = ('old_pic', 'main_pic', 'cluster')
    readonly_fields = [f.name for f in MergeCandidate._meta.fields]

    def has_add_permission(self, request):
        return False
