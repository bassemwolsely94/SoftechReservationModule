from django.apps import AppConfig


class GamificationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.gamification'
    verbose_name = 'التحفيز (النقاط والمستويات)'

    def ready(self):
        # Reward redemptions ride apps.approvals (existing inbox); its outcome moves them.
        from apps.approvals.signals import register_outcome_handler
        from .rewards import on_approval_outcome
        register_outcome_handler('gamification.redemption', on_approval_outcome)
