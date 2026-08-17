"""
apps/procurement/management/commands/run_procurement_engine.py

Management command: python manage.py run_procurement_engine [--days N]

Runs the full procurement intelligence engine pipeline:
  Stage 1: Sync purchase lines from SOFTECH (doccode 10/120)
  Stage 2: Sync supplier master from personsdata
  Stage 3: Compute supplier performance metrics + scores
  Stage 4: Build/update supplier-item mapping (OCR learning table)
  Stage 5: Compute daily ProcurementSnapshot
  Stage 6: Compute BuyerPerformance metrics
  Stage 7: Generate ProcurementAlert records

ABSOLUTE RULE: SELECT ONLY on Sybase. No writes to SOFTECHDB9 ever.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.procurement.engine import run_procurement_engine


class Command(BaseCommand):
    help = 'Run the Procurement Intelligence Engine pipeline'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=365,
            help='Lookback window in days (default: 365)',
        )
        parser.add_argument(
            '--triggered-by',
            type=str,
            default='management_command',
            help='Identifier for who triggered this run',
        )

    def handle(self, *args, **options):
        days         = options['days']
        triggered_by = options['triggered_by']

        self.stdout.write(
            self.style.NOTICE(
                f'[ProcurementEngine] Starting run: lookback={days}d, triggered_by={triggered_by}'
            )
        )

        try:
            run = run_procurement_engine(lookback_days=days, triggered_by=triggered_by)
        except Exception as e:
            raise CommandError(f'Engine failed with exception: {e}') from e

        if run.status == 'success':
            self.stdout.write(self.style.SUCCESS(
                f'[ProcurementEngine] Run #{run.pk} completed successfully.\n'
                f'  Lines synced:      {run.lines_synced}\n'
                f'  Lines upserted:    {run.lines_upserted}\n'
                f'  Suppliers updated: {run.suppliers_updated}\n'
                f'  Mappings updated:  {run.mappings_updated}\n'
                f'  Alerts generated:  {run.alerts_generated}'
            ))
        else:
            self.stdout.write(self.style.ERROR(
                f'[ProcurementEngine] Run #{run.pk} FAILED.\n'
                f'  Error: {run.error_message}'
            ))
            raise CommandError(f'Procurement engine run #{run.pk} failed.')
