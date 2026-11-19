from importlib import import_module

from django.apps import AppConfig


class ReservationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.reservations"

    def ready(self):
        # ActivityLog (the per-reservation call log, /api/reservations/<id>/activity/) lives in
        # activity_models.py, which only urls.py imported. Load it with the app, so `makemigrations`
        # never sees the model as gone and proposes dropping a live table (UAT housekeeping, 2026-11-19).
        import_module(f'{self.name}.activity_models')
