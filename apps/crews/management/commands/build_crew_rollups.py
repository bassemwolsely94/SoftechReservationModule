"""
build_crew_rollups  (crews piece 2b)
====================================
Shadow monthly KPIs for every live call-center crew (spec §6.8: rollups only for call-center
crews) into CrewKpiRollup — the same figures build_call_center_rollups writes for the fake «CC»
branch, but resolved from the crew's dated identities. Writes nothing else (money gate): the
legacy KpiActualRollup rows stay the live source until the owner signs the comparison off.

  python manage.py build_crew_rollups --year 2026 --month 6
  python manage.py build_crew_rollups --months 12               # last 12 completed months
  python manage.py build_crew_rollups --since 2024-08            # through the current month
  python manage.py build_crew_rollups --year 2026 --month 5 --cdr-csv path/to/cdr_may.csv
  python manage.py build_crew_rollups --crew 3 --no-returns

Each row stores the month's notes (returns_unreachable, cdr_unavailable, ...). A metric that
could not be computed is not written. The run is logged to stdout only.
"""
import csv
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.crews.kpi import compute_crew_month
from apps.crews.models import Crew, CrewKpiRollup


def _shift(y, m, delta):
    i = y * 12 + (m - 1) + delta
    return i // 12, i % 12 + 1


class Command(BaseCommand):
    help = 'Build shadow call-center crew KPI rollups (CrewKpiRollup only).'

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
                with transaction.atomic():
                    for metric, value in res.kpis.items():
                        CrewKpiRollup.objects.update_or_create(
                            crew=crew, year=year, month=month, metric=metric,
                            defaults={'value': value, 'notes': list(res.notes)})
                k = res.kpis
                self.stdout.write(
                    f"  crew {crew.pk} {year}-{month:02d}: "
                    f"net_sales={float(k.get('cash_delivery', 0)):,.0f} "
                    f"profit={float(k.get('gross_profit', 0)):,.0f} "
                    f"beauty={float(k.get('beauty', 0)):,.0f} "
                    f"orders={int(k.get('customer_count', 0))} "
                    f"calls={int(k['call_count']) if 'call_count' in k else '—'} "
                    f"notes={','.join(res.notes) or '-'}")
        self.stdout.write(self.style.SUCCESS(
            f'Done: {crews.count()} crew(s) x {len(periods)} month(s) → CrewKpiRollup only.'))

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
