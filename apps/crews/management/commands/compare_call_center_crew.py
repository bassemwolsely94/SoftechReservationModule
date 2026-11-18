"""
compare_call_center_crew  (crews piece 2b, Task 3)
==================================================
The old-vs-crew call-center comparison the owner signs off before any figure moves from the
fake «CC» branch to the call-center crew (money gate). Reads only.

  python manage.py compare_call_center_crew --out cc.xlsx --md cc.md
  python manage.py compare_call_center_crew --from 2024-08 --to 2026-10 --no-returns
  python manage.py compare_call_center_crew --seed-in-transaction --out cc.xlsx
  python manage.py compare_call_center_crew --from 2026-05 --to 2026-05 --cdr-csv cdr_may.csv

--from defaults to the earliest month with a CC rollup, --to to the current month.
--seed-in-transaction seeds the crew inside a transaction and rolls it back after computing
(for a DB where the seed must not persist yet); it holds one DB transaction open for the whole
run. Without it the live call-center crew is used.
SOFTECH (returns) and the CDR (call_count) are read when reachable; what cannot be read is
reported «غير محسوب», never 0. Without --out / --md the markdown summary goes to stdout.
"""
import csv
from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.crews import cc_comparison as C
from apps.crews import cc_seed
from apps.crews.models import Crew


def _ym(text, flag):
    try:
        y, m = (int(x) for x in text.split('-'))
        date(y, m, 1)
    except (ValueError, AttributeError):
        raise CommandError(f'{flag} must be YYYY-MM')
    return y, m


class Command(BaseCommand):
    help = 'Old CC rollups vs the call-center crew, per month x KPI, person, target (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='start', help='YYYY-MM (default: first CC rollup month)')
        parser.add_argument('--to', dest='end', help='YYYY-MM (default: current month)')
        parser.add_argument('--out', help='write the workbook (.xlsx) here')
        parser.add_argument('--md', help='write the markdown summary here')
        parser.add_argument('--no-returns', action='store_true', help='skip SOFTECH returns (gross)')
        parser.add_argument('--seed-in-transaction', action='store_true',
                            help='seed the crew, compare, roll the seed back; holds ONE database '
                                 'transaction open for the whole run (SOFTECH/CDR reads included), '
                                 'so prefer a short --from/--to on a busy DB')
        parser.add_argument('--cdr-csv', help='Issabel CDR CSV export for a single month')

    def handle(self, *args, **o):
        if o.get('start'):
            start = _ym(o['start'], '--from')
        else:
            s = cc_seed.seed_start()
            start = (s.year, s.month)
        today = timezone.localdate()
        end = _ym(o['end'], '--to') if o.get('end') else (today.year, today.month)
        if start > end:
            raise CommandError('--from is after --to')
        kw = {'returns': not o.get('no_returns')}
        if o.get('cdr_csv'):
            if start != end:
                raise CommandError('--cdr-csv needs exactly one month (--from = --to).')
            with open(o['cdr_csv'], encoding='utf-8', errors='replace', newline='') as f:
                kw['cdr_rows_by_month'] = {start: list(csv.DictReader(f))}
            kw['cdr_from_csv'] = True

        if o.get('seed_in_transaction'):
            result = C.compare_seeded_in_transaction(start, end, **kw)
        else:
            crew = Crew.objects.filter(name=cc_seed.CC_CREW_NAME, type='call_center',
                                       is_archived=False).first()
            if crew is None:
                raise CommandError('No call-center crew yet: run seed_call_center_crew, or pass '
                                   '--seed-in-transaction.')
            result = C.compare(crew, start, end, **kw)

        md = C.markdown_summary(result)
        if o.get('out'):
            C.build_workbook(result).save(o['out'])
            self.stdout.write(f"workbook → {o['out']}")
        if o.get('md'):
            with open(o['md'], 'w', encoding='utf-8') as f:
                f.write(md)
            self.stdout.write(f"markdown → {o['md']}")
        if not o.get('out') and not o.get('md'):
            self.stdout.write(md)
        reasons = ', '.join(f'{k}={v}' for k, v in sorted(result['totals']['reasons'].items()))
        self.stdout.write(self.style.SUCCESS(
            f'Compared {len(result["months"]) // len(C.METRICS)} month(s): {reasons}. Nothing written.'))
