from django.apps import AppConfig


class LineageConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.lineage'
    verbose_name = 'تتبع المستندات (Transaction Lineage)'
