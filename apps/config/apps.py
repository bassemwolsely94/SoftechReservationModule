from django.apps import AppConfig


class ConfigAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.config'
    verbose_name = 'إعدادات النظام'

    def ready(self):
        # Connect the post_save signal that auto-invalidates the settings cache
        import apps.config.services  # noqa: F401 — registers @receiver decorators

        # Item-category registry cache drops whenever the owner edits the map (piece 4).
        from django.db.models.signals import post_save, post_delete
        from .item_types import invalidate_cache
        from .models import MedicineTypeMap
        post_save.connect(invalidate_cache, sender=MedicineTypeMap,
                          dispatch_uid='config_item_types_save')
        post_delete.connect(invalidate_cache, sender=MedicineTypeMap,
                            dispatch_uid='config_item_types_delete')
