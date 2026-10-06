from django.contrib import admin
from .models import InsightRule, InsightRun, InsightFinding, InsightRecipient


@admin.register(InsightRule)
class InsightRuleAdmin(admin.ModelAdmin):
    list_display  = ['code', 'name_ar', 'category', 'severity', 'threshold', 'enabled', 'periods']
    list_filter   = ['category', 'severity', 'enabled']
    list_editable = ['threshold', 'enabled']


class InsightFindingInline(admin.TabularInline):
    model = InsightFinding
    extra = 0
    readonly_fields = ['rule_code', 'severity', 'scope_label', 'value', 'message_ar']


@admin.register(InsightRun)
class InsightRunAdmin(admin.ModelAdmin):
    list_display  = ['id', 'period_type', 'period_start', 'period_end', 'findings_count', 'sent_at', 'sent_to']
    list_filter   = ['period_type']
    inlines       = [InsightFindingInline]
    readonly_fields = ['narrative_ar', 'narrative_en', 'created_at']


@admin.register(InsightRecipient)
class InsightRecipientAdmin(admin.ModelAdmin):
    list_display  = ['name', 'wa_number', 'branch', 'salesperson_usercode', 'period_types', 'active']
    list_filter   = ['active', 'branch']
    search_fields = ['name', 'wa_number', 'salesperson_usercode']
