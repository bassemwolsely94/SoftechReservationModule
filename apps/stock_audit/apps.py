from django.apps import AppConfig


class StockAuditConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.stock_audit'
    verbose_name = 'تدقيق حركات المخزون'
