from django.apps import AppConfig


class ReplacementConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.replacement'
    verbose_name = 'بدل الروشتة / شراء الأدوية من العملاء'

    def ready(self):
        # Case approvals ride apps.approvals (existing inbox); its outcome moves the case.
        from apps.approvals.signals import register_outcome_handler
        from .workflow import on_approval_outcome
        register_outcome_handler('replacement.replacementcase', on_approval_outcome)
