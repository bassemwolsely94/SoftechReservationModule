"""
Accounting sign-off sheet for the SOFTECH price rewrites — every re-price run with
old→new price/gross/net/VAT, run id, date, receipt, branch, claim, net Δ, status.

    python manage.py export_reprice_reconciliation --out reconciliation.xlsx
    python manage.py export_reprice_reconciliation --out x.xlsx --include-reverted
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Export the SOFTECH re-price reconciliation sheet (for accounting sign-off).'

    def add_arguments(self, parser):
        parser.add_argument('--out', required=True, help='output .xlsx path')
        parser.add_argument('--include-reverted', action='store_true',
                            help='also include reverted runs')
        parser.add_argument('--include-backfill', action='store_true',
                            help='also include bonusqty-backfill runs (display-only fixes)')

    def handle(self, *args, **opts):
        from apps.insurance.models import SoftechRepriceRun
        from apps.insurance.export import generate_reprice_reconciliation_excel

        statuses = ['applied'] + (['reverted'] if opts['include_reverted'] else [])
        runs = (SoftechRepriceRun.objects.filter(status__in=statuses)
                .select_related('claim', 'applied_by').order_by('claim_id', 'docnumber'))
        if not opts['include_backfill']:
            runs = runs.exclude(new_prices__has_key='_bonusqty_backfill')

        path = generate_reprice_reconciliation_excel(runs, save_path=opts['out'])
        self.stdout.write(self.style.SUCCESS(f'✓ {runs.count()} عملية — حُفظ الكشف فى {path}'))
