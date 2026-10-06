from django.contrib import admin
from .models import Customer, CustomerHealthProfile, CustomerNote


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
