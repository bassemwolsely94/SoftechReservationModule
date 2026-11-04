from django.apps import AppConfig


class FollowupsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.followups'
    verbose_name = 'محرك المتابعة والأدوية المزمنة'

    def ready(self):
        # Registers the ``refill:`` WhatsApp button prefix.
        from . import refill_reminders  # noqa: F401
