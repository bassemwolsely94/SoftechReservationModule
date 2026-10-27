from django.apps import AppConfig


class ApprovalsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.approvals'
    verbose_name = 'محرك الموافقات'

    def ready(self):
        # Connect the post_save signal that dispatches approval outcomes
        import apps.approvals.signals  # noqa: F401  — registers @receiver
