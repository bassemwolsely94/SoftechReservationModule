"""
sync_pos_cancel — mirror SOFTECH pos_cancel (lost-sale / «المبيعات غير المخزنة») into the
PosCancelDaily rollup for every operational node. Read-only against SOFTECH; window-replace.

Usage:
  python manage.py sync_pos_cancel                 # last 30 days, all nodes
  python manage.py sync_pos_cancel --days 90       # wider backfill window
  python manage.py sync_pos_cancel --branch 170    # one node only
  python manage.py sync_pos_cancel --timeout 300
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Mirror SOFTECH pos_cancel into PosCancelDaily (lost-sale rollup) for all nodes.'

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='', help='One branch node only (softech_branch_id).')
        parser.add_argument('--days', type=int, default=30, help='Window to refresh (default 30).')
        parser.add_argument('--timeout', type=int, default=180, help='Per-node query timeout (s).')

    def handle(self, *args, **opts):
        from apps.pos_orders.pos_cancel_sync import sync_pos_cancel_all
        s = sync_pos_cancel_all(only_branch=(opts['branch'] or None),
                                days=opts['days'], timeout=opts['timeout'])
        self.stdout.write(self.style.SUCCESS(
            f"Done. nodes={s['nodes']} ok={s['ok']} failed={s['failed']} "
            f"rows={s['rows']:,} since={s['window_start']}"))
        for bc, d in sorted(s['detail'].items()):
            if d.get('ok'):
                self.stdout.write(f"  branch {bc}: {d['rows']:,} daily rows")
            else:
                self.stdout.write(self.style.WARNING(f"  branch {bc}: FAILED — {d.get('error')}"))
