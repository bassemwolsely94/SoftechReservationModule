from django.apps import AppConfig


class DataLifecycleConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.data_lifecycle'
    verbose_name = 'دورة حياة البيانات'

    def ready(self):
        from . import follow, uploads
        uploads.connect()
        follow.connect()
