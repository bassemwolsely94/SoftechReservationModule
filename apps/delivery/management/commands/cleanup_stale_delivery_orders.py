"""
python manage.py cleanup_stale_delivery_orders [options]

Remove the stale, never-progressed delivery orders that were created by a
one-time historical back-fill of SOFTECH `piccrmorders`. Those rows have
SOFTECH orderstatus = NULL (which the importer mapped to status='created'),
no driver, and an `ordered_at` years in the past. They are completed historical
sales, not actionable pending deliveries.

Root cause (fixed separately in sync_crm_orders + sybase_queries): the --full
sync pulled the entire branch piccrmorders history with no date/status floor,
and STATUS_MAP[None] = 'created'. This command cleans up the rows that were
already created before that fix landed.

Scope (the confirmed artifact signature — cannot match a real pending order):
    status                = 'created'
    assigned_driver       IS NULL
    softech_order_status  IS NULL
    ordered_at            < now - <cutoff-days>   (default 365)

Modes:
    (default)          Dry-run. Report the scope and exit. Writes nothing.
    --apply            Back up matched rows (+ their status logs) to JSON, then
                       DELETE them in batches. The JSON backups are Django
                       fixtures — restore with `manage.py loaddata <file>`.
    --apply --soft-close
                       Instead of deleting, bulk-update the rows to status
                       'closed' (closed_at=now). Reversible, keeps the rows, but
                       removes them from every active/SLA query.

Examples:
    python manage.py cleanup_stale_delivery_orders
    python manage.py cleanup_stale_delivery_orders --apply
    python manage.py cleanup_stale_delivery_orders --apply --soft-close
    python manage.py cleanup_stale_delivery_orders --apply --cutoff-days 365 --batch-size 5000
"""
import os
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core import serializers
from django.db import transaction
from django.db.models import Count, Min, Max
from django.utils import timezone


class Command(BaseCommand):
    help = 'Clean up stale historical-backfill delivery orders (status=created, no driver, NULL SOFTECH status, ancient).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Actually perform the cleanup. Without this flag the command is a dry-run report.',
        )
        parser.add_argument(
            '--soft-close', action='store_true',
            help="Transition matched rows to status='closed' instead of deleting them.",
        )
        parser.add_argument(
            '--cutoff-days', type=int, default=365,
            help='Only match orders older than this many days (default 365).',
        )
        parser.add_argument(
            '--batch-size', type=int, default=5000,
            help='Rows per delete/update batch (default 5000).',
        )
        parser.add_argument(
            '--backup-dir', type=str, default='',
            help='Directory for JSON fixture backups (default <BASE_DIR>/backups/delivery_cleanup).',
        )
        parser.add_argument(
            '--no-backup', action='store_true',
            help='Skip the JSON backup before deleting (NOT recommended). Ignored with --soft-close.',
        )

    def handle(self, *args, **options):
        from apps.delivery.models import DeliveryOrder, DeliveryStatusLog

        apply       = options['apply']
        soft_close  = options['soft_close']
        cutoff_days = options['cutoff_days']
        batch_size  = options['batch_size']
        no_backup   = options['no_backup']

        if cutoff_days < 1:
            raise CommandError('--cutoff-days must be >= 1 (refusing to touch recent orders).')
        if batch_size < 1:
            raise CommandError('--batch-size must be >= 1.')

        now    = timezone.now()
        cutoff = now - timedelta(days=cutoff_days)

        qs = DeliveryOrder.objects.filter(
            status=DeliveryOrder.STATUS_CREATED,
            assigned_driver__isnull=True,
            softech_order_status__isnull=True,
            ordered_at__lt=cutoff,
        )

        total = qs.count()

        # ── Report ────────────────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING('Stale delivery order cleanup'))
        self.stdout.write(f'  scope: status=created, no driver, SOFTECH status NULL, ordered_at < {cutoff.date()} ({cutoff_days}d)')
        self.stdout.write(f'  matched rows: {total}')

        if total == 0:
            self.stdout.write(self.style.SUCCESS('  Nothing to clean. Exiting.'))
            return

        agg = qs.aggregate(mn=Min('ordered_at'), mx=Max('ordered_at'))
        self.stdout.write(f'  ordered_at range: {agg["mn"]} .. {agg["mx"]}')
        self.stdout.write('  by source_type:')
        for r in qs.values('source_type').annotate(n=Count('id')).order_by('-n'):
            self.stdout.write(f'      {r["source_type"] or "—":<15} {r["n"]}')
        self.stdout.write('  by branch (top 10):')
        for r in qs.values('softech_branch_code').annotate(n=Count('id')).order_by('-n')[:10]:
            self.stdout.write(f'      br={r["softech_branch_code"] or "—":<8} {r["n"]}')

        log_count = DeliveryStatusLog.objects.filter(order__in=qs.values('id')).count()
        self.stdout.write(f'  attached status logs (also removed on delete): {log_count}')

        # ── Dry-run stops here ──────────────────────────────────────────────────
        if not apply:
            self.stdout.write(self.style.WARNING(
                '\n  DRY-RUN — no changes made. Re-run with --apply to execute'
                + (' (--soft-close to close instead of delete).' if not soft_close else '.')
            ))
            return

        # ── Soft-close path ─────────────────────────────────────────────────────
        if soft_close:
            self.stdout.write(self.style.MIGRATE_HEADING('\n  Applying --soft-close (bulk update to closed)…'))
            updated = 0
            # Iterate PK windows so we do bounded UPDATEs rather than one giant lock.
            pks = list(qs.values_list('id', flat=True))
            for i in range(0, len(pks), batch_size):
                chunk = pks[i:i + batch_size]
                with transaction.atomic():
                    n = DeliveryOrder.objects.filter(id__in=chunk).update(
                        status=DeliveryOrder.STATUS_CLOSED,
                        closed_at=now,
                        updated_at=now,
                    )
                updated += n
                self.stdout.write(f'    closed {updated}/{total}')
            self.stdout.write(self.style.SUCCESS(f'  Done. {updated} orders set to closed.'))
            return

        # ── Delete path (with backup) ───────────────────────────────────────────
        backup_dir = None
        if not no_backup:
            base = options['backup_dir'] or os.path.join(str(settings.BASE_DIR), 'backups', 'delivery_cleanup')
            stamp = now.strftime('%Y%m%d_%H%M%S')
            backup_dir = os.path.join(base, f'cleanup_{stamp}')
            os.makedirs(backup_dir, exist_ok=True)
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n  Backing up to: {backup_dir}'))
            self.stdout.write('  (restore any batch with: manage.py loaddata <file>)')

        self.stdout.write(self.style.MIGRATE_HEADING('\n  Applying delete in batches…'))
        deleted = 0
        batch_no = 0
        pks = list(qs.values_list('id', flat=True))

        for i in range(0, len(pks), batch_size):
            chunk = pks[i:i + batch_size]
            batch_no += 1

            with transaction.atomic():
                orders = DeliveryOrder.objects.filter(id__in=chunk)
                logs   = DeliveryStatusLog.objects.filter(order__in=chunk)

                if backup_dir is not None:
                    path = os.path.join(backup_dir, f'batch_{batch_no:05d}.json')
                    with open(path, 'w', encoding='utf-8') as fh:
                        # Serialize logs first, then orders — but loaddata handles
                        # FK order via natural insert; both included so the batch
                        # is self-contained for restore.
                        serializers.serialize(
                            'json',
                            list(orders) + list(logs),
                            stream=fh,
                            indent=1,
                        )

                # Deleting orders cascades their DeliveryStatusLog rows.
                n, _ = orders.delete()

            deleted += len(chunk)
            self.stdout.write(f'    batch {batch_no}: deleted {deleted}/{total}')

        self.stdout.write(self.style.SUCCESS(
            f'  Done. Deleted {deleted} stale delivery orders'
            + (f' (backups in {backup_dir}).' if backup_dir else ' (no backup).')
        ))
