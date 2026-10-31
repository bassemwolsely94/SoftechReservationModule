from django.apps import AppConfig


class AccessConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.access'
    verbose_name = 'الوصول والشبكات'

    def ready(self):
        from django.db.models.signals import post_delete, post_save
        from .models import TrustedNetwork
        from .network import invalidate_cache

        post_save.connect(invalidate_cache, sender=TrustedNetwork, dispatch_uid='access_tn_save')
        post_delete.connect(invalidate_cache, sender=TrustedNetwork, dispatch_uid='access_tn_delete')
