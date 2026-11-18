"""
build_crew_rollups  (crews piece 2b)
====================================
Monthly KPIs for every live call-center crew (spec §6.8: rollups only for call-center crews)
into forecasting.KpiActualRollup with crew set and branch NULL (Part B, owner ruling A: every month
is rebuilt from the crew rule). Figures from apps.crews.kpi.compute_crew_month (dated identities,
the owner's returns rule). Only the crew's own rows are touched; branch rows are never written.

  python manage.py build_crew_rollups --year 2026 --month 6
  python manage.py build_crew_rollups --months 12               # last 12 completed months
  python manage.py build_crew_rollups --since 2024-08            # through the current month
  python manage.py build_crew_rollups --year 2026 --month 5 --cdr-csv path/to/cdr_may.csv
  python manage.py build_crew_rollups --crew 3 --no-returns

The month's notes (returns_unreachable, cdr_unavailable, ...) are printed — KpiActualRollup has
no notes column. A metric the notes mark as not computable this run (apps.crews.kpi.unavailable_metrics:
SOFTECH returns / CDR unreachable, no members / sellers) keeps its stored row untouched — never
deleted, never overwritten with a gross or partial figure — so an unattended refresh cannot lose
or degrade a number. A stored metric that is neither computed nor unavailable is deleted (no stale
figure). Logged to stdout only.
"""
import csv
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.crews.kpi import compute_crew_month, unavailable_metrics
from apps.crews.models import Crew
from apps.forecasting.models import KpiActualRollup


def _shift(y, m, delta):
    i = y * 12 + (m - 1) + delta
    return i // 12, i % 12 + 1


class Command(BaseCommand):
    help = 'Build call-center crew KPI rollups (KpiActualRollup rows with crew set, branch NULL).'

    def add_arguments(self, parser):
        parser.add_argument('--crew', type=int, help='one crew id (default: every live call-center crew)')
        parser.add_argument('--year', type=int)
        parser.add_argument('--month', type=int)
        parser.add_argument('--months', type=int, help='last N completed months')
        parser.add_argument('--since', help='YYYY-MM .. the current month')
        parser.add_argument('--cdr-csv', help='Issabel CDR CSV export for a single month')
        parser.add_argument('--no-returns', action='store_true', help='skip SOFTECH returns (gross)')

    def handle(self, *args, **o):
        periods = self._periods(o)
        cdr_rows = None
        if o.get('cdr_csv'):
            if len(periods) != 1:
                raise CommandError('--cdr-csv needs exactly one month (--year & --month).')
            with open(o['cdr_csv'], encoding='utf-8', errors='replace', newline='') as f:
                cdr_rows = list(csv.DictReader(f))
        crews = Crew.objects.filter(type='call_center', is_archived=False)
        if o.get('crew'):
            crews = crews.filter(pk=o['crew'])
            if not crews.exists():
                raise CommandError(f"No live call-center crew with id {o['crew']}.")
        for crew in crews:
            for year, month in periods:
                res = compute_crew_month(crew, year, month, returns=not o.get('no_returns'),
                                         cdr_rows=cdr_rows, per_member=False)
                unavailable = unavailable_metrics(res.notes)
                write = {m: v for m, v in res.kpis.items() if m not in unavailable}
                with transaction.atomic():
                    rows = KpiActualRollup.objects.filter(crew=crew, year=year, month=month)
                    kept = sorted(rows.filter(metric__in=list(unavailable))
                                  .values_list('metric', flat=True))
                    # a metric neither computed nor unavailable must not survive from an earlier run
                    stale = rows.exclude(metric__in=list(write) + list(unavailable)).delete()[0]
                    for metric, value in write.items():
                        KpiActualRollup.objects.update_or_create(
                            crew=crew, branch=None, year=year, month=month, metric=metric,
                            defaults={'value': value})
                if kept:
                    self.stdout.write(
                        f"  crew {crew.pk} {year}-{month:02d}: kept stored {', '.join(kept)} "
                        f"(not computable: {','.join(res.notes)})")
                if not write:
                    self.stdout.write(self.style.WARNING(
                        f"  crew {crew.pk} {year}-{month:02d}: nothing computed, nothing written, "
                        f"{stale} old row(s) removed (notes={','.join(res.notes) or '-'})"))
                    continue
                k = write
                self.stdout.write(
                    f"  crew {crew.pk} {year}-{month:02d}: "
                    f"net_sales={float(k.get('cash_delivery', 0)):,.0f} "
                    f"profit={float(k.get('gross_profit', 0)):,.0f} "
                    f"beauty={float(k.get('beauty', 0)):,.0f} "
                    f"orders={int(k.get('customer_count', 0))} "
                    f"calls={int(k['call_count']) if 'call_count' in k else '—'} "
                    f"notes={','.join(res.notes) or '-'}")
        self.stdout.write(self.style.SUCCESS(
            f'Done: {crews.count()} crew(s) x {len(periods)} month(s) → KpiActualRollup (crew rows).'))

    def _periods(self, o):
        today = timezone.localdate()
        if o.get('year') and o.get('month'):
            return [(o['year'], o['month'])]
        if o.get('months'):
            return [_shift(today.year, today.month, -n) for n in range(o['months'], 0, -1)]
        if o.get('since'):
            try:
                y, m = (int(x) for x in o['since'].split('-'))
                date(y, m, 1)
            except ValueError:
                raise CommandError('--since must be YYYY-MM')
            out = []
            while (y, m) <= (today.year, today.month):
                out.append((y, m))
                y, m = _shift(y, m, 1)
            return out
        raise CommandError('Provide --year & --month, --months N, or --since YYYY-MM')
