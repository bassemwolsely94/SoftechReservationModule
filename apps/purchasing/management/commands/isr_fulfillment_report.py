"""
python manage.py isr_fulfillment_report --isr 261609 --isr 2615043
python manage.py isr_fulfillment_report --isr 261609 --coverage 2

READ-ONLY. Same report as /supply «تلبية طلبات الفروع» (apps/purchasing/isr_fulfillment.py):
for SOFTECH ISRs raised by branches, an Excel workbook showing — per requested item — the
requesting branch, every other branch and HQ (live stock, sales rate, engine need, max-stock
ceiling, excess) plus the fulfilment plan (other branches' excess → HQ → shortage). Every
derived number is an Excel formula driven by the coverage cell on the summary sheet.

Output: media/reports/isr_fulfillment_<isrs>_<date>.xlsx. Never writes to SOFTECH.
"""
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.purchasing import isr_fulfillment as F


class Command(BaseCommand):
    help = 'READ-ONLY Excel: ISR items vs every branch stock/rate/excess + reallocation plan'

    def add_arguments(self, parser):
        parser.add_argument('--isr', action='append', required=True, help='SOFTECH isrdocnumber (repeatable)')
        parser.add_argument('--fill', type=float, default=1.5,
                            help='months the requesting branch is filled up to (default 1.5)')
        parser.add_argument('--basis', choices=['min', 'recommended', 'requested'], default='min',
                            help='which quantity the plan ships (default: smaller of requested / recommended)')
        parser.add_argument('--coverage', type=float, default=1.0,
                            help='months each donor branch keeps (default 1) — editable in the workbook')


    def handle(self, *a, **o):
        try:
            snap = F.collect(o['isr'])
        except ValueError as exc:
            raise CommandError(str(exc))
        plan = F.compute(snap, o['coverage'], o['fill'], o['basis'])
        wb = F.build_workbook(snap, o['coverage'], o['fill'], o['basis'])
        out_dir = os.path.join(settings.MEDIA_ROOT, 'reports')
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, F.workbook_filename(snap))
        wb.save(path)

        self.stdout.write(self.style.MIGRATE_HEADING('\n═══ ISR fulfilment plan ═══'))
        for r in plan['isrs']:
            t = r['totals']
            self.stdout.write(
                f'  ISR {r["isr"]} (branch {r["branch"]}, {t["items"]} items): requested {t["requested"]:.0f} | '
                f'from branches {t["from_branches"]:.0f} '
                f'({", ".join(f"{b}:{v:.0f}" for b, v in r["from_by_donor"].items())}) | from HQ '
                f'{t["from_hq"]:.0f} | shortage {t["shortage"]:.0f} | fully by branches '
                f'{t["full_branches"]}/{t["items"]} | fully overall {t["full_all"]}/{t["items"]} | '
                f'over ceiling after supply {t["over_ceiling"]} | value from branches '
                f'{t["value_branches"]:,.0f} | shortage value {t["value_shortage"]:,.0f}')
        for msg in plan['notices']:
            self.stdout.write(self.style.WARNING('  ' + msg))
        self.stdout.write(self.style.SUCCESS(f'\n  Excel: {path}'))
