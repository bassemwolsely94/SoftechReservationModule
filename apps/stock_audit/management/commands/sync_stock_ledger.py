"""
sync_stock_ledger
=================
Doc 32 Phase 1 — mirror SOFTECH `stktrans` (all doccodes) from HQ into StockLedgerLine.
READ-ONLY against SOFTECH. Replaces whole docdate days, so re-runs are idempotent.

Usage:
  python manage.py sync_stock_ledger                    # last 3 days (default incremental)
  python manage.py sync_stock_ledger --days 7           # catch-up
  python manage.py sync_stock_ledger --backfill         # the whole window (STOCK_AUDIT_WINDOW_DAYS)
  python manage.py sync_stock_ledger --from 2026-01-01 --to 2026-02-01   # [from, to)
"""
import datetime as _dt

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Mirror stktrans (all doccodes) from SOFTECH HQ into StockLedgerLine.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=3, help='Docdate days ending today.')
        parser.add_argument('--backfill', action='store_true', help='Sync the whole rolling window.')
        parser.add_argument('--from', dest='date_from', default='', help='YYYY-MM-DD (inclusive).')
        parser.add_argument('--to', dest='date_to', default='', help='YYYY-MM-DD (exclusive).')
        parser.add_argument('--chunk-days', type=int, default=7)
        parser.add_argument('--timeout', type=int, default=600, help='Per-chunk query timeout (s).')
        parser.add_argument('--triggered-by', default='sync_stock_ledger')

    def handle(self, *args, **opts):
        from apps.stock_audit.ledger import recent_range, sync_ledger, window_days
        from apps.stock_audit.models import StockLedgerSyncRun

        if opts['date_from'] or opts['date_to']:
            try:
                d1 = _dt.date.fromisoformat(opts['date_from'])
                d2 = _dt.date.fromisoformat(opts['date_to'])
            except ValueError:
                raise CommandError('--from and --to are both required, as YYYY-MM-DD.')
            if d2 <= d1:
                raise CommandError('--to must be after --from.')
        else:
            d1, d2 = recent_range(window_days() if opts['backfill'] else opts['days'])

        run = StockLedgerSyncRun.objects.create(triggered_by=opts['triggered_by'][:50])
        try:
            s = sync_ledger(d1, d2, run=run, chunk_days=opts['chunk_days'], timeout=opts['timeout'])
        except Exception as e:
            run.detail = {'fatal': str(e)[:300]}
            run.finish('failed')
            self.stderr.write(self.style.ERROR(f'Fatal: {e}'))
            return

        style = self.style.SUCCESS if s['status'] == 'success' else self.style.WARNING
        self.stdout.write(style(
            f"{s['status']}: {d1} → {d2} · rows={s['rows']:,} chunks ok={s['chunks_ok']} "
            f"failed={s['chunks_failed']} pruned={s['pruned']:,}"))
        for k, d in sorted(s['detail'].items()):
            if not d.get('ok'):
                self.stdout.write(self.style.WARNING(f"  {k} → {d['to']}: FAILED — {d.get('error')}"))
