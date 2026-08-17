from django.apps import AppConfig


class SyncConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sync"

    def ready(self):
        """
        Auto-start the background sync scheduler when Django boots.

        Guard rules:
          • runserver (with autoreload): ready() fires twice — once in the
            reloader parent and once in the worker child.  Only the worker
            sets RUN_MAIN='true'; we skip the parent to avoid duplicate jobs.
          • runserver --noreload / gunicorn / waitress: RUN_MAIN is absent,
            so we start unconditionally.
          • Management commands that don't need a live scheduler
            (migrate, shell, collectstatic, etc.) are skipped by name.
        """
        import os
        import sys
        import logging

        log = logging.getLogger("elrezeiky.sync")

        cmd = sys.argv[1] if len(sys.argv) > 1 else ""

        # The dedicated `run_scheduler` process starts the scheduler itself in
        # handle() — ready() must NOT also start it (would double-start).  The
        # asgiref patch below is web-only, so skip the rest for this command too.
        if cmd == "run_scheduler":
            return

        # Skip commands that don't need any of this.
        _skip = {
            "migrate", "makemigrations", "collectstatic", "compress",
            "shell", "dbshell", "createsuperuser", "check", "test",
            "inspectdb", "dumpdata", "loaddata",
            "run_sync", "sync_finance",
        }
        if cmd in _skip:
            return

        # Prevent running in Django's dev-server reloader parent.
        in_runserver = cmd == "runserver"
        if in_runserver and os.environ.get("RUN_MAIN") != "true":
            return  # reloader parent — the worker handles it

        # ── Python 3.12+ / asgiref executor patch ─────────────────────────────
        # On Python 3.12+ (especially 3.14) the interpreter registers an
        # internal atexit finaliser that marks ALL ThreadPoolExecutors as
        # _shutdown=True before user atexit callbacks fire.  asgiref's
        # SyncToAsync uses a class-level ThreadPoolExecutor created at import
        # time; once that's marked shutdown any sync_to_async call raises:
        #   RuntimeError: cannot schedule new futures after interpreter shutdown
        # Workaround: replace the shut-down executor with a fresh one when the
        # error is about to be raised.  This only fires during the short window
        # of hot-reload teardown; normal operation is unaffected.
        try:
            from asgiref.sync import SyncToAsync, AsyncToSync
            from concurrent.futures import ThreadPoolExecutor as _TPE

            _orig_call = SyncToAsync.__call__

            def _heal_executors():
                """Recreate any asgiref thread executor that has been shut down."""
                ste = getattr(SyncToAsync, 'single_thread_executor', None)
                if ste is not None and getattr(ste, '_shutdown', False):
                    SyncToAsync.single_thread_executor = _TPE(max_workers=1)
                # Per-loop thread-sensitive executors (the common path under Daphne)
                try:
                    pool = getattr(AsyncToSync, 'loop_thread_executors', None)
                    if isinstance(pool, dict):
                        for loop, ex in list(pool.items()):
                            if getattr(ex, '_shutdown', False):
                                pool[loop] = _TPE(max_workers=1)
                except Exception:
                    pass

            async def _resilient_call(self, *args, **kwargs):
                _heal_executors()
                try:
                    return await _orig_call(self, *args, **kwargs)
                except RuntimeError as exc:
                    # A torn-down pool (dev autoreload zombie) → heal + retry once.
                    if 'shutdown' not in str(exc).lower():
                        raise
                    _heal_executors()
                    return await _orig_call(self, *args, **kwargs)

            SyncToAsync.__call__ = _resilient_call
            log.debug("[SyncConfig] asgiref SyncToAsync executor-resilience patch applied.")
        except Exception as patch_exc:
            log.debug(f"[SyncConfig] asgiref patch skipped: {patch_exc}")

        # ── Scheduler autostart (OFF by default) ───────────────────────────────
        # The scheduler now runs in its own process:  python manage.py run_scheduler
        # This keeps APScheduler OUT of the web/ASGI process, which eliminates the
        # dev-autoreload "zombie" that wedged jobs and broke sync_to_async.
        # To restore the legacy in-web behaviour, set SCHEDULER_AUTOSTART=True.
        from django.conf import settings
        if getattr(settings, "SCHEDULER_AUTOSTART", False):
            # Hard reject: running the scheduler inside the ASGI/web process is
            # never safe.  Under autoreload the thread pool gets torn down on every
            # file change, leaving APScheduler jobs stuck and breaking sync_to_async
            # for ALL subsequent requests.  Under multi-worker Gunicorn/Daphne every
            # worker spawns its own scheduler instance, multiplying job executions.
            # The correct pattern is always a SEPARATE process:
            #   python manage.py run_scheduler
            log.error(
                "[SyncConfig] SCHEDULER_AUTOSTART=True is set but the scheduler "
                "will NOT start inside the web process — this causes thread-pool "
                "crashes.  Run `python manage.py run_scheduler` in a separate "
                "terminal / systemd service instead.  Set SCHEDULER_AUTOSTART=False "
                "in your .env to silence this warning."
            )
        else:
            log.info("[SyncConfig] Scheduler NOT started in web process — "
                     "run `python manage.py run_scheduler` in a separate process.")
