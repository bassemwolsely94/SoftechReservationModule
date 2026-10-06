from django.apps import AppConfig


class ConfigAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.config'
    verbose_name = 'إعدادات النظام'

    def ready(self):
        # Connect the post_save signal that auto-invalidates the settings cache
        import apps.config.services  # noqa: F401 — registers @receiver decorators
