from django.apps import AppConfig


class AccessConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.access'
    verbose_name = 'الوصول والشبكات'

    def ready(self):
        from . import checks  # noqa: F401  (registers the system checks)
        from django.db.models.signals import post_delete, post_save
        from .devices import invalidate_signal
        from .models import Device, TrustedNetwork, ZonePolicy
        from .policy import invalidate_cache as invalidate_policy
        from .network import invalidate_cache

        post_save.connect(invalidate_signal, sender=Device, dispatch_uid='access_device_save')

        post_save.connect(invalidate_cache, sender=TrustedNetwork, dispatch_uid='access_tn_save')
        post_delete.connect(invalidate_cache, sender=TrustedNetwork, dispatch_uid='access_tn_delete')

        post_save.connect(invalidate_policy, sender=ZonePolicy, dispatch_uid='access_zp_save')
        post_delete.connect(invalidate_policy, sender=ZonePolicy, dispatch_uid='access_zp_delete')
