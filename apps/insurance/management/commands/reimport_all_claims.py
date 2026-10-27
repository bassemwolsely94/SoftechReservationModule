"""
python manage.py reimport_all_claims [options]

Re-runs every insurance claim through the corrected totals math
(net-authoritative + local-balancing — see classifier.balance_local_before).

Existing claims keep totals computed with the OLD scaling logic until they are
re-imported, because the old code distorted the per-prescription
imported_before via proportional rescaling. This command re-pulls each claim
from Softech so every prescription is recomputed correctly, then re-applies any
adjustments/supplements via recalculate_claim_final_totals.

Import path per claim:
  • softech_motalba_no set  → import_claim_by_motalbano   (preferred)
  • otherwise               → import_claim_from_softech   (personcode + period)

Options:
  --claim MT-2026-00023   Re-import a single claim by number (repeatable)
  --status draft,ready    Only claims in these statuses (default: all)
  --skip-locked           Skip claims that are submitted/paid (safer default off)
  --dry-run               Show what would be re-imported, change nothing
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = 'Re-import all insurance claims through the corrected totals math'

    def add_arguments(self, parser):
        parser.add_argument('--claim', action='append', default=[],
                            help='Claim number to re-import (repeatable)')
        parser.add_argument('--status', type=str, default='',
                            help='Comma-separated statuses to include (default: all)')
        parser.add_argument('--skip-locked', action='store_true',
                            help='Skip submitted/under_review/paid/partially_paid claims')
        parser.add_argument('--dry-run', action='store_true',
                            help='List claims and old→new totals without saving')

    def handle(self, *args, **opts):
        from apps.insurance.models import InsuranceClaim
        from apps.insurance.importer import (
            import_claim_by_motalbano, import_claim_from_softech,
            recalculate_claim_final_totals, InsuranceImportError,
        )

        LOCKED = {'submitted', 'under_review', 'partially_paid', 'paid'}

        qs = InsuranceClaim.objects.select_related('subclient__client').order_by('claim_number')
        if opts['claim']:
            qs = qs.filter(claim_number__in=opts['claim'])
        if opts['status']:
            wanted = {s.strip() for s in opts['status'].split(',') if s.strip()}
            qs = qs.filter(status__in=wanted)
        if opts['skip_locked']:
            qs = qs.exclude(status__in=LOCKED)

        claims = list(qs)
        if not claims:
            self.stdout.write(self.style.WARNING('No matching claims found.'))
            return

        self.stdout.write(f'Re-importing {len(claims)} claim(s)'
                          f'{" (DRY RUN)" if opts["dry_run"] else ""}...\n')

        ok = failed = skipped = 0
        for claim in claims:
            tag = f'{claim.claim_number} [{claim.get_status_display()}] {claim.subclient}'
            old = (float(claim.final_local_before), float(claim.final_imported_before),
                   float(claim.final_gross_before), float(claim.final_net_after))

            personcodes = claim.subclient.get_all_personcodes()
            motalbano = None
            if (claim.softech_motalba_no or '').strip():
                try:
                    motalbano = int(claim.softech_motalba_no)
                except ValueError:
                    motalbano = None

            if not motalbano and not personcodes:
                self.stdout.write(self.style.WARNING(
                    f'  SKIP  {tag} — no motalba number and no personcode'))
                skipped += 1
                continue

            if opts['dry_run']:
                path = f'motalba={motalbano}' if motalbano else f'personcode={personcodes}'
                self.stdout.write(
                    f'  WOULD {tag} via {path} | '
                    f'old local={old[0]:.2f} imp={old[1]:.2f} gross={old[2]:.2f} net={old[3]:.2f}')
                continue

            try:
                with transaction.atomic():
                    if motalbano:
                        import_claim_by_motalbano(claim=claim, motalbano=motalbano)
                    else:
                        import_claim_from_softech(
                            claim=claim, personcodes=personcodes,
                            period_from=claim.period_from, period_to=claim.period_to,
                            branchcodes=([b for b in claim.imported_branches.split(',') if b]
                                         or None),
                        )
                    # Fold in any adjustments / supplements / manual Rx
                    recalculate_claim_final_totals(claim)
                claim.refresh_from_db()
                new = (float(claim.final_local_before), float(claim.final_imported_before),
                       float(claim.final_gross_before), float(claim.final_net_after))
                changed = any(abs(a - b) >= 0.01 for a, b in zip(old, new))
                mark = self.style.SUCCESS('OK   ') if not changed else self.style.SUCCESS('FIXED')
                self.stdout.write(
                    f'  {mark} {tag}\n'
                    f'        local {old[0]:.2f}→{new[0]:.2f}  '
                    f'imp {old[1]:.2f}→{new[1]:.2f}  '
                    f'gross {old[2]:.2f}→{new[2]:.2f}  '
                    f'net {old[3]:.2f}→{new[3]:.2f}')
                ok += 1
            except InsuranceImportError as e:
                self.stdout.write(self.style.ERROR(f'  FAIL  {tag} — {e}'))
                failed += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ERROR {tag} — {e}'))
                failed += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. ok={ok} failed={failed} skipped={skipped} '
            f'{"(dry run — nothing saved)" if opts["dry_run"] else ""}'))
