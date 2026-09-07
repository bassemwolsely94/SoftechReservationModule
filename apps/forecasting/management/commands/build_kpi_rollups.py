"""
build_kpi_rollups  (doc 16, Phase 1)
====================================
Materialise KpiActualRollup (branch × year × month × metric) from PurchaseHistory
via KpiResolver. Idempotent upsert.

Usage:
  python manage.py build_kpi_rollups --year 2026 --month 5
  python manage.py build_kpi_rollups --year 2026 --month 5 --branch 160
  python manage.py build_kpi_rollups --months 12        # last 12 completed months, all branches

Schedule: daily (recompute current + previous month), or monthly close.
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Build monthly branch KPI rollups from PurchaseHistory'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int)
        parser.add_argument('--month', type=int)
        parser.add_argument('--months', type=int, help='Backfill last N completed months (overrides year/month)')
        parser.add_argument('--branch', nargs='*', help='Branch code(s) or softech_branch_id(s); default all active')

    def handle(self, *args, **opts):
        from apps.branches.models import Branch
        from apps.forecasting.kpi import KpiResolver
        from apps.forecasting.models import KpiActualRollup

        # resolve branches
        branches = Branch.objects.filter(is_active=True)
        if opts.get('branch'):
            keys = set(map(str, opts['branch']))
            branches = branches.filter(code__in=keys) | branches.filter(softech_branch_id__in=keys)
            branches = branches.distinct()
        branches = list(branches)
        if not branches:
            raise CommandError('No matching branches')

        # resolve periods
        periods = self._periods(opts)
        resolver = KpiResolver()
        total = 0
        for (year, month) in periods:
            for b in branches:
                metrics = resolver.compute_branch_month(b.id, year, month)
                with transaction.atomic():
                    for key, val in metrics.items():
                        KpiActualRollup.objects.update_or_create(
                            branch=b, year=year, month=month, metric=key,
                            defaults={'value': val},
                        )
                    total += len(metrics)
                self.stdout.write(
                    f'  {b.code or b.softech_branch_id} {year}-{month:02d}: '
                    f"cash+del={metrics['cash_delivery']:,.0f} credit={metrics['credit']:,.0f} "
                    f"profit={metrics['gross_profit']:,.0f} cust={metrics['customer_count']:,.0f}")

        self.stdout.write(self.style.SUCCESS(
            f'Done: {total} rollup rows across {len(branches)} branches × {len(periods)} months.'))

    def _periods(self, opts):
        if opts.get('months'):
            today = date.today()
            y, m = today.year, today.month
            out = []
            for _ in range(opts['months']):
                m -= 1
                if m == 0:
                    m = 12; y -= 1
                out.append((y, m))
            return list(reversed(out))
        if opts.get('year') and opts.get('month'):
            return [(opts['year'], opts['month'])]
        raise CommandError('Provide --year & --month, or --months N')
