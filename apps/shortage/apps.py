from django.apps import AppConfig


class ShortageConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.shortage'
    verbose_name = 'إدخال النواقص'

    def ready(self):
        # refresh the Arabic→Latin sound index when catalog items change (phonetic.py)
        from .phonetic import _connect_signals
        _connect_signals()

        self._warm_sound_index()

    @staticmethod
    def _warm_sound_index():
        """Build the in-memory sound index at process start (first build ~2.4 s cold) so the
        first search is not the one that pays for it. Same skip rules as apps.sync. The thread
        waits for the app registry to be ready before it touches the DB (phonetic.warm_after_init)."""
        import os
        import sys
        from apps.sync.apps import SKIP_COMMANDS
        from core.threads import start_thread
        from .phonetic import warm_after_init

        cmd = sys.argv[1] if len(sys.argv) > 1 else ""
        if cmd in SKIP_COMMANDS or cmd == "run_scheduler":
            return
        if cmd == "runserver" and os.environ.get("RUN_MAIN") != "true":
            return  # autoreload parent: the worker child warms its own index
        start_thread(warm_after_init, name="warm-sound-index")
