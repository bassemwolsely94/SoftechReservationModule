from django.apps import AppConfig


class OmniConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.omni'
    verbose_name = 'منصة التواصل الموحدة'

    def ready(self):
        from apps.omni import signals  # noqa: F401
