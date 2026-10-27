"""
backfill_sales_history  (doc 16, Phase 3.5)
===========================================
One-time historical backfill of customers.PurchaseHistory(+Line) from SOFTECH,
so the branch-KPI forecast engine has same-month-last-year + recent months.

Marches MONTH BY MONTH (bounded memory, resumable) over a window, using the
windowed sales query, then rebuilds KpiActualRollup for each completed month.

Usage:
  python manage.py backfill_sales_history --months 24
  python manage.py backfill_sales_history --months 14 --no-rollups
  python manage.py backfill_sales_history --start 2024-08 --end 2026-07

Notes:
  • Reads SOFTECH (read-only mirror source) — no writeback.
  • Invoices whose personcode is not in the customer mirror are skipped by
    sync_sales (walk-ins 1500/1510 + regulars persist, so coverage is high).
  • Run during off-hours: a 24-month scan of stktrans is heavy on the live ERP.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError


def _month_iter(start_y, start_m, end_y, end_m):
    y, m = start_y, start_m
    while (y, m) <= (end_y, end_m):
        yield y, m
        m += 1
        if m == 13:
            m = 1; y += 1


def _next_month(y, m):
    return (y + 1, 1) if m == 12 else (y, m + 1)


class Command(BaseCommand):
    help = 'Backfill historical PurchaseHistory from SOFTECH month-by-month + rebuild KPI rollups'

    def add_arguments(self, parser):
        parser.add_argument('--months', type=int, default=24,
                            help='Number of completed months back from today (default 24)')
        parser.add_argument('--start', help='Start month YYYY-MM (overrides --months)')
        parser.add_argument('--end', help='End month YYYY-MM inclusive (default: last completed month)')
        parser.add_argument('--no-rollups', action='store_true', help='Skip KpiActualRollup rebuild')

    def handle(self, *args, **opts):
        from config.sybase import get_sybase_connection
        from apps.sync.models import SyncRun
        from apps.sync.tasks import sync_sales
        from apps.sync.sybase_queries import QUERY_CUSTOMER_SALES_LINES_WINDOW

        # resolve window
        today = date.today()
        end_y, end_m = (today.year, today.month)
        if opts.get('end'):
            end_y, end_m = self._parse_ym(opts['end'])
        if opts.get('start'):
            start_y, start_m = self._parse_ym(opts['start'])
        else:
            # months back from end
            idx = end_y * 12 + (end_m - 1) - opts['months']
            start_y, start_m = idx // 12, idx % 12 + 1

        months = list(_month_iter(start_y, start_m, end_y, end_m))
        if not months:
            raise CommandError('Empty month range')
        self.stdout.write(self.style.NOTICE(
            f'Backfilling {len(months)} months: {start_y}-{start_m:02d} → {end_y}-{end_m:02d}'))

        conn = get_sybase_connection()
        sync_run = SyncRun.objects.create(status='running')
        grand = 0
        try:
            for (y, m) in months:
                ny, nm = _next_month(y, m)
                q = QUERY_CUSTOMER_SALES_LINES_WINDOW.format(
                    start=f'{y}{m:02d}01', end=f'{ny}{nm:02d}01')
                n = sync_sales(conn, sync_run, query=q)
                grand += n
                self.stdout.write(f'  {y}-{m:02d}: {n:,} invoices')
                if not opts['no_rollups']:
                    from django.core import management
                    management.call_command('build_kpi_rollups', year=y, month=m, verbosity=0)
            sync_run.status = 'success'
            sync_run.records_synced = grand
        except Exception as e:
            sync_run.status = 'failed'
            sync_run.error_message = str(e)
            raise
        finally:
            from django.utils import timezone
            sync_run.completed_at = timezone.now()
            sync_run.save()
            conn.close()

        self.stdout.write(self.style.SUCCESS(
            f'Backfill done: {grand:,} invoices across {len(months)} months.'))

    @staticmethod
    def _parse_ym(s):
        try:
            y, m = s.split('-')
            return int(y), int(m)
        except Exception:
            raise CommandError(f'Bad month {s!r} — use YYYY-MM')
