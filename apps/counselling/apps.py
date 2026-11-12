from django.apps import AppConfig


class CounsellingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.counselling'

    def ready(self):
        from apps.counselling import checks  # noqa: F401  (registers the deploy check)
    verbose_name = 'إرشادات الاستخدام'
