from django.contrib import admin
from .models import Customer, CustomerHealthProfile, CustomerNote, CustomerStatusDrift


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
