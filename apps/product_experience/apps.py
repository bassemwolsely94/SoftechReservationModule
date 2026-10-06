from django.apps import AppConfig


class ProductExperienceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.product_experience'
    verbose_name = 'تجربة المنتج'

    def ready(self):
        import apps.product_experience.signals  # noqa: F401
