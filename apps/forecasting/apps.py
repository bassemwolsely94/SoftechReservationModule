from django.apps import AppConfig


class ForecastingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name  = 'apps.forecasting'
    label = 'forecasting'
    verbose_name = 'محرك التنبؤ بالمبيعات'

    def ready(self):
        # Channel registry cache drops whenever the owner edits the map (piece 4).
        from django.db.models.signals import post_save, post_delete
        from .channels import invalidate_cache
        from .models import ChannelBucketMap
        post_save.connect(invalidate_cache, sender=ChannelBucketMap,
                          dispatch_uid='forecasting_channels_save')
        post_delete.connect(invalidate_cache, sender=ChannelBucketMap,
                            dispatch_uid='forecasting_channels_delete')
