"""
python manage.py run_sync           # incremental (last 10 min)
python manage.py run_sync --full    # full backfill (last 90 days)
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Run a SOFTECH → PostgreSQL sync manually'

    def add_arguments(self, parser):
        parser.add_argument(
            '--full', action='store_true',
            help='Full backfill: sync last 90 days of sales history'
        )

    def handle(self, *args, **options):
        from apps.sync.tasks import run_full_sync
        full = options['full']
        mode = 'FULL (90-day backfill)' if full else 'INCREMENTAL (last 10 min)'
        self.stdout.write(f"Starting {mode} sync...")

        sync_run = run_full_sync(full_history=full)

        if sync_run.status == 'success':
            self.stdout.write(self.style.SUCCESS(
                f"✅ Sync complete — {sync_run.records_synced} records "
                f"in {sync_run.duration_seconds}s"
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f"❌ Sync failed: {sync_run.error_message}"
            ))
