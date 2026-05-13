from django.contrib import admin
from .models import (
    MedicationTag, ActiveIngredient, IngredientTag,
    ItemIngredientMap, FollowUpProtocol,
)


@admin.register(MedicationTag)
class MedicationTagAdmin(admin.ModelAdmin):
    list_display  = ('name', 'name_ar', 'tag_type', 'color', 'is_active', 'created_at')
    list_filter   = ('tag_type', 'is_active')
    search_fields = ('name', 'name_ar')
    ordering      = ('tag_type', 'name')


class IngredientTagInline(admin.TabularInline):
    model  = IngredientTag
    extra  = 1
    fields = ('tag', 'added_by', 'added_at')
    readonly_fields = ('added_at',)


class ItemIngredientMapInline(admin.TabularInline):
    model  = ItemIngredientMap
    extra  = 1
    fields = ('item', 'concentration', 'is_primary', 'mapped_by', 'mapped_at')
    readonly_fields = ('mapped_at',)
    autocomplete_fields = ('item',)


class FollowUpProtocolInline(admin.TabularInline):
    model  = FollowUpProtocol
    extra  = 1
    fields = ('name', 'frequency_type', 'days', 'task_type', 'priority',
              'customer_type_filter', 'trigger_condition', 'is_active', 'sort_order')


@admin.register(ActiveIngredient)
class ActiveIngredientAdmin(admin.ModelAdmin):
    list_display  = ('name', 'name_ar', 'atc_code', 'atc_level4_name',
                     'is_chronic', 'chronic_class', 'item_count_display', 'updated_at')
    list_filter   = ('is_chronic', 'chronic_class')
    search_fields = ('name', 'name_ar', 'atc_code', 'atc_level2_name',
                     'atc_level3_name', 'atc_level4_name')
    readonly_fields = ('created_at', 'updated_at')
    inlines = [IngredientTagInline, ItemIngredientMapInline, FollowUpProtocolInline]
    fieldsets = (
        ('الهوية', {
            'fields': ('name', 'name_ar', 'name_scientific', 'notes'),
        }),
        ('تصنيف ATC', {
            'fields': (
                'atc_code',
                ('atc_level1', 'atc_level1_name'),
                ('atc_level2', 'atc_level2_name'),
                ('atc_level3', 'atc_level3_name'),
                ('atc_level4', 'atc_level4_name'),
            ),
        }),
        ('تصنيف المرض المزمن', {
            'fields': ('is_chronic', 'chronic_class'),
        }),
        ('معلومات النظام', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='عدد الأصناف')
    def item_count_display(self, obj):
        return obj.item_maps.count()


@admin.register(ItemIngredientMap)
class ItemIngredientMapAdmin(admin.ModelAdmin):
    list_display  = ('item', 'active_ingredient', 'concentration', 'is_primary', 'mapped_at')
    list_filter   = ('is_primary',)
    search_fields = ('item__name', 'item__softech_id', 'active_ingredient__name')
    autocomplete_fields = ('item',)


@admin.register(FollowUpProtocol)
class FollowUpProtocolAdmin(admin.ModelAdmin):
    list_display  = ('active_ingredient', 'name', 'frequency_type', 'days',
                     'task_type', 'priority', 'customer_type_filter',
                     'trigger_condition', 'is_active', 'sort_order')
    list_filter   = ('is_active', 'task_type', 'priority',
                     'frequency_type', 'customer_type_filter', 'trigger_condition')
    search_fields = ('name', 'active_ingredient__name', 'active_ingredient__name_ar')
    ordering      = ('active_ingredient', 'sort_order')
