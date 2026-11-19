"""
manage.py run_export_jobs — the jobs service (deploy/elrezeiky-jobs.service, performance Stage 4).

Claims queued export jobs one at a time with SELECT … FOR UPDATE SKIP LOCKED and builds them in
this process, away from the web workers. No JVM: kinds that read SOFTECH live never come here
(they stay on the web process's thread, design §10). The web processes only leave jobs queued for
it when EXPORT_JOBS_RUNNER=service is set for them too.

At start, jobs this service was running when it stopped are reported failed. Every 10 minutes
it runs the same housekeeping as a start (stale -> failed, > 48 h -> deleted).
"""
import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection

from apps.export_jobs import runner

logger = logging.getLogger(__name__)
CLEANUP_EVERY = 600


class Command(BaseCommand):
    help = 'Run queued export jobs (the elrezeiky-jobs service).'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='run what is queued now, then exit')
        parser.add_argument('--idle', type=float, default=2.0, help='seconds to wait when nothing is queued')

    def handle(self, *args, once=False, idle=2.0, **opts):
        self._stop = False
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self._on_signal)
            except (ValueError, AttributeError):        # not the main thread / not on this OS
                pass
        orphans = runner.fail_orphans('service')
        if orphans:
            logger.warning('export jobs: %s job(s) cut off by the last stop reported failed', orphans)
        last_cleanup = 0.0
        done = 0
        while not self._stop:
            if not connection.in_atomic_block:      # never inside a test's transaction
                close_old_connections()
            if time.monotonic() - last_cleanup > CLEANUP_EVERY:
                try:
                    runner.cleanup()
                except Exception:                       # housekeeping never stops the service
                    logger.exception('export jobs cleanup failed')
                last_cleanup = time.monotonic()
            pk = runner.claim_next('service')
            if pk is not None:
                runner.execute(pk)
                done += 1
                continue
            if once:
                break
            time.sleep(idle)
        self.stdout.write(f'export jobs: {done} run')

    def _on_signal(self, *_):
        self._stop = True          # finish the current job's bookkeeping, then exit
