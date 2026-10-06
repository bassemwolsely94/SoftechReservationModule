"""
Phase 0 (doc 25): rebuild replacement / buy-back cases from the Postgres mirrors.

READ-ONLY vs SOFTECH — inputs are finance (A/P) + procurement.PurchaseLine + customers
PurchaseHistory mirrors only. Idempotent; safe to re-run (refreshes snapshots, appends only
new ledger facts, never overrides a person's decision).

  python manage.py reconstruct_replacement_cases --from 2025-06-01
  python manage.py reconstruct_replacement_cases --branch 130 --supplier 4472 --limit 50
  python manage.py reconstruct_replacement_cases --doc 130/12095/2026-07-21
"""
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from apps.replacement import config as C
from apps.replacement import reconstruct as R

# The sales-line mirror (PurchaseHistoryLine) starts 2024-08 and procurement.PurchaseLine
# covers the virtual suppliers from 2025-05 → contract matching is only meaningful after that.
DEFAULT_FROM = date(2025, 6, 1)


class Command(BaseCommand):
    help = 'Rebuild بدل الروشتة cases from the A/P, purchase-line and sales mirrors (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--from', dest='date_from', type=date.fromisoformat, default=DEFAULT_FROM)
        parser.add_argument('--to', dest='date_to', type=date.fromisoformat)
        parser.add_argument('--supplier', action='append', help='personcode (repeatable)')
        parser.add_argument('--branch')
        parser.add_argument('--limit', type=int)
        parser.add_argument('--doc', help='one invoice: BRANCH/DOCNUMBER/YYYY-MM-DD')
        parser.add_argument('--reset-reconstructed', action='store_true',
                            help='wipe DERIVED reconstruction output first (refused if any human '
                                 'decision or live case exists); requires --confirm')
        parser.add_argument('--confirm', action='store_true')

    def handle(self, *args, **o):
        if o['reset_reconstructed']:
            if not o['confirm']:
                raise CommandError('--reset-reconstructed requires --confirm')
            try:
                counts = R.reset_reconstructed()
            except RuntimeError as e:
                raise CommandError(str(e))
            self.stdout.write(self.style.WARNING(f'Reset reconstructed data: {counts}'))
        if o['doc']:
            from apps.finance.recon_models import APInvoice
            try:
                br, dn, dd = o['doc'].split('/')
                inv = APInvoice.objects.select_related('party').get(
                    branchcode=br, doccode='10', docnumber=dn, docdate=date.fromisoformat(dd))
            except (ValueError, APInvoice.DoesNotExist) as e:
                raise CommandError(f'invoice not found: {e}')
            out = R.reconstruct_invoice(inv, tabdeel=R.tabdeel_pics())
            c = out['case']
            self.stdout.write(self.style.SUCCESS(
                f'{c.number} {"created" if out["created"] else "updated"} — pic={c.softech_pic or "—"} '
                f'entitlement={c.entitlement} products={c.redeemed_products} cash={c.redeemed_cash} '
                f'unclassified={c.redeemed_unclassified} outstanding={c.outstanding} '
                f'status={c.status} exceptions={c.open_exceptions}'))
            return

        suppliers = o['supplier'] or C.supplier_codes()
        self.stdout.write(f'Reconstructing suppliers={suppliers} from={o["date_from"]} to={o["date_to"] or "—"} '
                          f'branch={o["branch"] or "all"} (rules {C.RULES_VERSION}) …')
        run = R.run(date_from=o['date_from'], date_to=o['date_to'], suppliers=suppliers,
                    branch=o['branch'], limit=o['limit'], triggered_by='command',
                    progress=lambda c: self.stdout.write(f'  … {c}'))
        style = self.style.SUCCESS if run.status == 'success' else self.style.WARNING
        self.stdout.write(style(f'Run #{run.pk} {run.status}: {run.counts}'))
        if run.notes:
            self.stdout.write(run.notes)
