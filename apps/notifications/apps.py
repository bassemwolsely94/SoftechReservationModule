from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.notifications'
    verbose_name = 'الإشعارات والتذكيرات'

    def ready(self):
        from apps.whatsapp import button_registry
        from .phone_alerts import inbound
        button_registry.register('alert:', inbound.handle_alert_tap)
