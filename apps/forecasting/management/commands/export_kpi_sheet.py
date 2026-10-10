"""
export_kpi_sheet  (doc 16, Phase 7)
===================================
Export the owner's legacy-format monthly target workbook FROM the new system:
per-branch KPI rows + weighted scoring + chain totals + call-center + management
block, with targets forecast by the engine (Model A / B / avg) and achieved from
KpiActualRollup. Read-only; never touches SOFTECH.

Usage:
  python manage.py export_kpi_sheet --year 2026 --month 10
  python manage.py export_kpi_sheet --year 2026 --month 10 --models avg
  python manage.py export_kpi_sheet --year 2026 --month 9 \
        --recon "path/to/تارجت شهر سبتمبر2026.xlsx" --out sept_check.xlsx
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Export the legacy-format KPI target workbook from the new system.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True)
        parser.add_argument('--month', type=int, required=True)
        parser.add_argument('--models', default='a,b,avg',
                            help="comma list of a,b,avg (default all three)")
        parser.add_argument('--out', help='output .xlsx path (default ./kpi_target_<Y>_<M>.xlsx)')
        parser.add_argument('--days-elapsed', type=int,
                            help='day-of-month to compute achieved-to (default: today if current month, else full month)')
        parser.add_argument('--recon', action='append', default=[],
                            help='legacy xlsx path(s) for a reconciliation sheet (same month)')
        parser.add_argument('--threshold', type=float, default=0.90)
        parser.add_argument('--benchmark', type=float, default=0.30)

    def handle(self, *args, **o):
        from apps.forecasting.kpi_export import build_target_workbook
        models = tuple(m.strip() for m in o['models'].split(',') if m.strip() in ('a', 'b', 'avg'))
        if not models:
            raise CommandError('No valid models (use a,b,avg).')
        out = o.get('out') or f"kpi_target_{o['year']}_{o['month']:02d}.xlsx"
        wb = build_target_workbook(
            o['year'], o['month'], models=models,
            days_elapsed=o.get('days_elapsed'),
            recon_legacy=o.get('recon') or None,
            incentive_threshold=Decimal(str(o['threshold'])),
            benchmark_growth=Decimal(str(o['benchmark'])),
        )
        wb.save(out)
        self.stdout.write(self.style.SUCCESS(
            f"Wrote {out}  (sheets: {', '.join(wb.sheetnames)})"))
