"""
sync_stock_expiry
=================
Sweep SOFTECH `stkbalexpiry` (current on-hand per-batch expiry) from every
operational node — HQ/central + each branch's own Sybase — into the local
StockExpiryBalance mirror. Resilient per node; replace-per-branch snapshot.

Usage:
  python manage.py sync_stock_expiry
  python manage.py sync_stock_expiry --branch 130     # one node only
  python manage.py sync_stock_expiry --timeout 300
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Mirror stkbalexpiry from all operational nodes into StockExpiryBalance.'

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='', help='Sync one branch node only (softech_branch_id).')
        parser.add_argument('--timeout', type=int, default=180, help='Per-node query timeout (s).')

    def handle(self, *args, **opts):
        from apps.batches.models import StockExpirySyncRun
        from apps.batches.stock_expiry import sync_stock_expiry_all

        run = StockExpirySyncRun.objects.create(triggered_by='sync_stock_expiry')
        try:
            s = sync_stock_expiry_all(run=run, only_branch=(opts['branch'] or None),
                                      timeout=opts['timeout'])
        except Exception as e:
            run.status = 'failed'
            run.detail = {'fatal': str(e)[:300]}
            run.finish('failed')
            self.stderr.write(self.style.ERROR(f'Fatal: {e}'))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Done. nodes={s['nodes']} ok={s['ok']} failed={s['failed']} rows={s['rows']:,}"))
        for bc, d in sorted(s['detail'].items()):
            if d.get('ok'):
                self.stdout.write(f"  branch {bc}: {d['rows']:,} rows")
            else:
                self.stdout.write(self.style.WARNING(f"  branch {bc}: FAILED — {d.get('error')}"))
