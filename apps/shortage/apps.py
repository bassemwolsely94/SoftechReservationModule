from django.apps import AppConfig


class ShortageConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.shortage'
    verbose_name = 'إدخال النواقص'

    def ready(self):
        # refresh the Arabic→Latin sound index when catalog items change (phonetic.py)
        from .phonetic import _connect_signals
        _connect_signals()
