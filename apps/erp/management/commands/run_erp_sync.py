"""
apps/erp/management/commands/run_erp_sync.py

Standalone management command to trigger just the Phase 1 ERP sync
without running the full sync pipeline.

Usage:
    python manage.py run_erp_sync              # incremental (last 12 min)
    python manage.py run_erp_sync --full       # full backfill (90 days)
    python manage.py run_erp_sync --local-only # only localcustomers
    python manage.py run_erp_sync --tx-only    # only ERP transactions
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Sync ERP transactions and localcustomers from Sybase (Phase 1)'

    def add_arguments(self, parser):
        parser.add_argument('--full',       action='store_true', help='Full 90-day backfill')
        parser.add_argument('--local-only', action='store_true', help='Sync localcustomers only')
        parser.add_argument('--tx-only',    action='store_true', help='Sync ERP transactions only')

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection
        from apps.sync.models import SyncRun
        from apps.sync.tasks import sync_local_customers, sync_erp_transactions
        from django.utils import timezone

        full       = options['full']
        local_only = options['local_only']
        tx_only    = options['tx_only']

        self.stdout.write(f'🔄 Phase 1 ERP sync — {"FULL 90-day" if full else "incremental"} mode')

        sync_run = SyncRun.objects.create(status='running')
        total = 0

        try:
            conn = get_sybase_connection()

            if not tx_only:
                self.stdout.write('  → Syncing localcustomers...')
                n = sync_local_customers(conn, sync_run)
                self.stdout.write(self.style.SUCCESS(f'     ✓ {n} local customers synced'))
                total += n

            if not local_only:
                mode = 'FULL (90 days)' if full else 'incremental (12 min)'
                self.stdout.write(f'  → Syncing ERP transactions [{mode}]...')
                n = sync_erp_transactions(conn, sync_run, full=full)
                self.stdout.write(self.style.SUCCESS(f'     ✓ {n} transactions synced'))
                total += n

            conn.close()

            sync_run.status = 'success'
            sync_run.records_synced = total
            sync_run.completed_at = timezone.now()
            sync_run.save()

            self.stdout.write(self.style.SUCCESS(f'\n✅ Phase 1 sync complete — {total} records'))

        except Exception as e:
            sync_run.status = 'failed'
            sync_run.error_message = str(e)
            sync_run.completed_at = timezone.now()
            sync_run.save()
            self.stdout.write(self.style.ERROR(f'❌ Sync failed: {e}'))
            raise
