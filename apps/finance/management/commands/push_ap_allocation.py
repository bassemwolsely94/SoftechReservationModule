"""
python manage.py push_ap_allocation --allocation <id> [--commit]

Phase-G — write ONE approved reconstructed allocation to SOFTECH (records the
missing chequestrans link + syncs stktransm.docvaluepay for an EXISTING voucher).

DRY-RUN by default: prints the plan, writes nothing. --commit attempts the live
write, which additionally requires settings.AP_RECONCILE_WRITER_ENABLED=True
(otherwise it stays a dry-run). Idempotent + verify-readback; no cheques row is
ever created.

See docs/architecture/23_SOFTECH_AP_RECONCILIATION.md.
"""
import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'GATED: write one approved A/P allocation to SOFTECH (dry-run unless --commit + flag)'

    def add_arguments(self, parser):
        parser.add_argument('--allocation', type=int, required=True)
        parser.add_argument('--commit', action='store_true',
                            help='attempt live write (still needs AP_RECONCILE_WRITER_ENABLED=True)')

    def handle(self, *args, **o):
        from apps.finance.models import Allocation
        from apps.finance import recon_writer

        try:
            alloc = Allocation.objects.select_related('payment', 'invoice').get(pk=o['allocation'])
        except Allocation.DoesNotExist:
            raise CommandError(f'allocation {o["allocation"]} not found')

        try:
            res = recon_writer.push_allocation(alloc, dry_run=not o['commit'])
        except recon_writer.ReconWriteError as e:
            raise CommandError(str(e))

        self.stdout.write(json.dumps(res, indent=2, ensure_ascii=False, default=str))
        if res.get('written'):
            self.stdout.write(self.style.SUCCESS(
                f'WRITTEN allocation {alloc.id}'
                + (' (already present)' if res.get('already_present') else '')))
        else:
            self.stdout.write(self.style.WARNING(
                f'DRY-RUN only (enabled={res.get("enabled")}). '
                f'Set AP_RECONCILE_WRITER_ENABLED=True and pass --commit to write.'))
