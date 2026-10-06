"""
management command: sync_motalbas

Discovers and imports all Softech motalbas for every configured subclient.

For each subclient → for each motalbano in Softech:
  - If not yet imported: create claim + import
  - If already imported but rx_count differs from Softech: re-import
  - If already imported and rx_count matches: skip

Usage:
    python manage.py sync_motalbas
    python manage.py sync_motalbas --subclient_id 1
    python manage.py sync_motalbas --subclient_id 1 --motalbano 117
    python manage.py sync_motalbas --dry_run          # list only, no writes
    python manage.py sync_motalbas --reimport_all     # re-import even if counts match
"""
import logging
from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger('elrezeiky.insurance')


class Command(BaseCommand):
    help = 'Sync all Softech motalbas into InsuranceClaim records'

    def add_arguments(self, parser):
        parser.add_argument('--subclient_id', type=int, default=None,
                            help='Limit to one subclient (default: all)')
        parser.add_argument('--motalbano', type=int, default=None,
                            help='Limit to one specific motalbano')
        parser.add_argument('--dry_run', action='store_true',
                            help='List motalbas without importing')
        parser.add_argument('--reimport_all', action='store_true',
                            help='Re-import even if rx_count already matches')

    def handle(self, *args, **opts):
        from apps.insurance.models import (
            InsuranceClient, InsuranceSubClient, InsuranceClaim,
        )
        from apps.insurance.sybase_queries import QUERY_MOTALBAS_BY_PERSONCODE
        from apps.insurance.importer import (
            import_claim_by_motalbano_batch, InsuranceImportError,
        )

        try:
            from config.sybase import get_sybase_connection
            conn = get_sybase_connection()
        except Exception as e:
            self.stderr.write(f'Cannot connect to Softech: {e}')
            return

        # Build subclient list
        sc_qs = InsuranceSubClient.objects.select_related('client').prefetch_related('contracts')
        if opts['subclient_id']:
            sc_qs = sc_qs.filter(pk=opts['subclient_id'])
        sc_qs = sc_qs.filter(is_active=True)

        subclients = list(sc_qs)
        if not subclients:
            self.stderr.write('No active subclients found.')
            return

        self.stdout.write(f'Found {len(subclients)} subclient(s) to process.\n')

        grand_imported = 0
        grand_skipped  = 0
        grand_reimported = 0
        grand_errors   = 0

        for sc in subclients:
            personcodes = sc.get_all_personcodes()
            if not personcodes:
                self.stdout.write(f'  [{sc.id}] {sc} — no personcodes configured, skipping.')
                continue

            # Find best contract (most recent)
            contract = sc.contracts.order_by('-effective_from').first()
            from decimal import Decimal
            local_disc    = contract.local_discount_pct    if contract else Decimal('0')
            imported_disc = contract.imported_discount_pct if contract else Decimal('0')
            tarsia_disc   = contract.tarsia_discount_pct   if contract else Decimal('0')

            self.stdout.write(f'--- {sc} ---')
            self.stdout.write(f'    personcodes : {personcodes}')
            self.stdout.write(f'    contract    : {contract or "none"} '
                              f'(local={local_disc}%, imported={imported_disc}%, tarsia={tarsia_disc}%)')

            # Query Softech for all motalbas of this subclient
            seen_motalbanos = {}  # motalbano → {rxcount, motfromdate, mottodate}
            for personcode in personcodes:
                try:
                    cursor = conn.cursor()
                    cursor.execute(QUERY_MOTALBAS_BY_PERSONCODE, [personcode])
                    rows = cursor.fetchall()
                    for r in rows:
                        motno = int(str(r[0]).split('.')[0]) if r[0] else None
                        if motno and motno not in seen_motalbanos:
                            seen_motalbanos[motno] = {
                                'motalbano':  motno,
                                'motfrom':    str(r[1])[:10] if r[1] else None,
                                'motto':      str(r[2])[:10] if r[2] else None,
                                'rxcount':    int(r[3] or 0),
                                'gross':      float(r[4] or 0),
                                'personcode': personcode,
                            }
                except Exception as e:
                    self.stderr.write(f'    ERROR querying motalbas for {personcode}: {e}')
                    conn = get_sybase_connection()  # fresh connection after error

            if not seen_motalbanos:
                self.stdout.write('    No motalbas found in Softech.\n')
                continue

            # Filter to specific motalbano if requested
            if opts['motalbano']:
                if opts['motalbano'] not in seen_motalbanos:
                    self.stdout.write(f'    Motalba {opts["motalbano"]} not found for this subclient.\n')
                    continue
                seen_motalbanos = {opts['motalbano']: seen_motalbanos[opts['motalbano']]}

            self.stdout.write(f'    Found {len(seen_motalbanos)} motalba(s) in Softech:')

            for motno, info in sorted(seen_motalbanos.items(), reverse=True):
                sfx_rx    = info['rxcount']
                sfx_from  = info['motfrom']
                sfx_to    = info['motto']
                sfx_gross = info['gross']
                personcode = info['personcode']

                # Check if already imported
                existing = InsuranceClaim.objects.filter(
                    subclient=sc,
                    softech_motalba_no=str(motno),
                ).first()

                if existing:
                    rx_match = existing.snapshot_rx_count == sfx_rx
                    if rx_match and not opts['reimport_all']:
                        self.stdout.write(
                            f'    [{motno:>5}] {sfx_from} → {sfx_to}  '
                            f'rx={sfx_rx:>4}  gross={sfx_gross:>12,.2f}  '
                            f'→ SKIP (already imported as {existing.claim_number}, rx={existing.snapshot_rx_count})'
                        )
                        grand_skipped += 1
                        continue
                    else:
                        action = 'RE-IMPORT' if not opts['dry_run'] else 'WOULD RE-IMPORT'
                        reason = 'rx mismatch' if not rx_match else '--reimport_all'
                        self.stdout.write(
                            f'    [{motno:>5}] {sfx_from} → {sfx_to}  '
                            f'rx={sfx_rx:>4}  gross={sfx_gross:>12,.2f}  '
                            f'→ {action} ({existing.claim_number}, stored_rx={existing.snapshot_rx_count}, {reason})'
                        )
                        if opts['dry_run']:
                            grand_reimported += 1
                            continue
                        # Re-import: wipe prescriptions and re-run
                        existing.applied_local_disc_pct    = local_disc
                        existing.applied_imported_disc_pct = imported_disc
                        existing.applied_tarsia_disc_pct   = tarsia_disc
                        existing.contract = contract
                        existing.imported_personcodes = personcode
                        existing.save()
                        try:
                            summary = import_claim_by_motalbano_batch(
                                claim=existing, motalbano=motno, user=None,
                            )
                            existing.refresh_from_db()
                            self.stdout.write(
                                f'           → done: rx={existing.snapshot_rx_count} '
                                f'net={existing.final_net_after:,.2f}'
                            )
                            grand_reimported += 1
                        except InsuranceImportError as e:
                            self.stderr.write(f'           → ERROR: {e}')
                            grand_errors += 1
                        continue

                # New motalba — not yet imported
                action = 'IMPORT' if not opts['dry_run'] else 'WOULD IMPORT'
                self.stdout.write(
                    f'    [{motno:>5}] {sfx_from} → {sfx_to}  '
                    f'rx={sfx_rx:>4}  gross={sfx_gross:>12,.2f}  → {action}'
                )
                if opts['dry_run']:
                    grand_imported += 1
                    continue

                # Generate claim number
                import datetime
                year   = datetime.date.today().year
                prefix = f'MT-{year}-'
                last   = (
                    InsuranceClaim.objects
                    .filter(claim_number__startswith=prefix)
                    .order_by('-claim_number')
                    .values_list('claim_number', flat=True)
                    .first()
                )
                try:
                    n = int(last.split('-')[-1]) + 1 if last else 1
                except (ValueError, AttributeError):
                    n = 1
                claim_number = f'{prefix}{n:05d}'

                # Period dates come from Softech — use placeholders, importer overwrites
                claim = InsuranceClaim.objects.create(
                    claim_number              = claim_number,
                    subclient                 = sc,
                    contract                  = contract,
                    period_from               = sfx_from or '2000-01-01',
                    period_to                 = sfx_to   or '2099-12-31',
                    softech_motalba_no        = str(motno),
                    imported_personcodes      = personcode,
                    applied_local_disc_pct    = local_disc,
                    applied_imported_disc_pct = imported_disc,
                    applied_tarsia_disc_pct   = tarsia_disc,
                    status                    = InsuranceClaim.STATUS_DRAFT,
                )

                try:
                    summary = import_claim_by_motalbano_batch(
                        claim=claim, motalbano=motno, user=None,
                    )
                    claim.refresh_from_db()
                    self.stdout.write(
                        f'           → created {claim_number}: '
                        f'rx={claim.snapshot_rx_count} net={claim.final_net_after:,.2f}'
                    )
                    grand_imported += 1
                except InsuranceImportError as e:
                    self.stderr.write(f'           → ERROR (claim deleted): {e}')
                    claim.delete()
                    grand_errors += 1
                except Exception as e:
                    self.stderr.write(f'           → UNEXPECTED ERROR (claim deleted): {e}')
                    logger.exception('sync_motalbas unexpected error motalbano=%d', motno)
                    claim.delete()
                    grand_errors += 1

            self.stdout.write('')

        # Summary
        prefix = '[DRY RUN] ' if opts['dry_run'] else ''
        self.stdout.write('-' * 60)
        self.stdout.write(f'{prefix}SYNC COMPLETE')
        self.stdout.write(f'  Imported   : {grand_imported}')
        self.stdout.write(f'  Re-imported: {grand_reimported}')
        self.stdout.write(f'  Skipped    : {grand_skipped}')
        self.stdout.write(f'  Errors     : {grand_errors}')
