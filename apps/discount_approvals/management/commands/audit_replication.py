"""
python manage.py audit_replication [--days 30] [--repair] [--mode restamp|push|both]

Scans HQ↔branch item replication over the last N days (covers BOTH module
changes and direct SOFTECH Items-Master edits), persists a ReplicationScan,
and optionally auto-repairs gaps for branches that are reachable again.

Designed to run on a schedule (registered in apps/sync/tasks.py).
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Audit HQ→branch replication and optionally repair gaps'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--repair', action='store_true',
                            help='Force re-replication for detected gaps')
        parser.add_argument('--mode', default='restamp',
                            choices=['restamp', 'push', 'both'])

    def handle(self, *args, **opts):
        from apps.discount_approvals.replication import scan_recent, force_replication
        from apps.discount_approvals.models import ReplicationGap
        from apps.discount_approvals.notify import notify_admins_replication_gaps
        from django.conf import settings

        days = opts['days']
        self.stdout.write(f'Scanning last {days} days …')
        scan = scan_recent(days=days, persist=True, is_scheduled=True)
        self.stdout.write(
            f'Scan #{scan.pk}: checked={scan.items_checked} ok={scan.items_ok} '
            f'gaps={scan.items_with_gaps} branches_down={scan.branches_down}'
        )
        notify_admins_replication_gaps(scan)

        if opts['repair'] and scan.items_with_gaps:
            # Repair preserves each item's original editor — no service user needed.
            codes = sorted(set(
                ReplicationGap.objects.filter(scan=scan)
                .exclude(status=ReplicationGap.STATUS_REPAIRED)
                .values_list('item_softech_id', flat=True)
            ))
            self.stdout.write(f'Repairing {len(codes)} items via mode={opts["mode"]} …')
            for code in codes:
                out = force_replication(code, mode=opts['mode'])
                self.stdout.write(f'  {code}: {out.get("restamped") and "restamped" or ""} {out.get("pushed", "")}')
            self.stdout.write(self.style.SUCCESS(
                'Repair queued. Offline branches catch up on the next ~30-min cycle; '
                're-run the scan afterwards to confirm.'
            ))
