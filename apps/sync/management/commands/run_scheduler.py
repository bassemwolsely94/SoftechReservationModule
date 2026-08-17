"""
python manage.py run_scheduler

Runs the APScheduler background scheduler in its OWN dedicated process,
separate from the web/ASGI server.

Why a separate process?
  Running APScheduler inside the Daphne/Channels web process means Django's
  autoreloader (and any half-clean shutdown) can leave a "zombie" worker whose
  thread pools are dead but whose scheduler keeps ticking — permanently wedging
  every job ("maximum number of running instances reached") and breaking
  sync_to_async.  Isolating the scheduler removes that entire class of problem:
  the web process just serves requests; this process just runs the jobs.

Usage (run alongside the web server, e.g. in a second terminal / service):
    python manage.py run_scheduler

Stop with Ctrl+C (SIGINT) or SIGTERM — the scheduler shuts down cleanly.
"""
import signal
import threading

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run the background sync/jobs scheduler in a dedicated process.'

    def handle(self, *args, **options):
        from apps.sync.tasks import start_scheduler, stop_scheduler

        start_scheduler()
        self.stdout.write(self.style.SUCCESS(
            '✓ Scheduler running in dedicated process. Press Ctrl+C to stop.'
        ))

        stop_event = threading.Event()

        def _graceful(signum, _frame):
            self.stdout.write(self.style.WARNING(
                f'\nReceived signal {signum} — stopping scheduler…'
            ))
            stop_event.set()

        signal.signal(signal.SIGINT, _graceful)
        try:
            signal.signal(signal.SIGTERM, _graceful)
        except (ValueError, AttributeError):
            pass  # SIGTERM not settable on some platforms/threads

        # Block the main thread until a stop signal arrives.
        stop_event.wait()

        stop_scheduler()
        self.stdout.write(self.style.SUCCESS('Scheduler stopped cleanly.'))
