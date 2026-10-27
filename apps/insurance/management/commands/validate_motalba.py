"""
management command: validate_motalba

Imports a motalba into a TEMPORARY InsuranceClaim (then rolls back),
prints the financial totals, and optionally compares against expected values.

Usage:
    python manage.py validate_motalba --motalbano 117 --subclient_id 1
    python manage.py validate_motalba --motalbano 117 --subclient_id 1 \
        --expected_net 696438.27 --expected_rx 546

Always rolls back — never saves to the database.
"""
from decimal import Decimal
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Dry-run import a Softech motalba and print financial totals (no DB write)'

    def add_arguments(self, parser):
        parser.add_argument('--motalbano', type=int, required=True)
        parser.add_argument('--subclient_id', type=int, required=True)
        parser.add_argument('--expected_net',   type=float, default=None)
        parser.add_argument('--expected_rx',    type=int,   default=None)
        parser.add_argument('--expected_gross',  type=float, default=None)
        parser.add_argument('--expected_local',  type=float, default=None)
        parser.add_argument('--expected_imported', type=float, default=None)

    def handle(self, *args, **opts):
        from apps.insurance.models import InsuranceClaim, InsuranceSubClient, InsuranceContract
        from apps.insurance.importer import import_claim_by_motalbano_batch, InsuranceImportError

        motalbano   = opts['motalbano']
        subclient_id = opts['subclient_id']

        try:
            subclient = InsuranceSubClient.objects.get(pk=subclient_id)
        except InsuranceSubClient.DoesNotExist:
            self.stderr.write(f'SubClient {subclient_id} not found')
            return

        personcodes = subclient.get_all_personcodes()
        self.stdout.write(f'SubClient : {subclient}')
        self.stdout.write(f'Personcodes: {personcodes}')
        self.stdout.write(f'Motalba   : {motalbano}')
        self.stdout.write('')

        # Find most recent contract for discount rates
        contract = subclient.contracts.order_by('-effective_from').first()
        local_disc    = contract.local_discount_pct    if contract else Decimal('0')
        imported_disc = contract.imported_discount_pct if contract else Decimal('0')
        tarsia_disc   = contract.tarsia_discount_pct   if contract else Decimal('0')

        self.stdout.write(f'Contract  : {contract or "none — using 0% discounts"}')
        self.stdout.write(f'Discounts : local={local_disc}%, imported={imported_disc}%, tarsia={tarsia_disc}%')
        self.stdout.write('')

        # Create a temporary in-memory claim (not saved yet)
        # We'll use a transaction and roll back
        from django.db import transaction
        try:
            with transaction.atomic():
                # Create a temporary claim
                claim = InsuranceClaim(
                    claim_number              = f'VALIDATE-{motalbano}',
                    subclient                 = subclient,
                    contract                  = contract,
                    period_from               = '2000-01-01',
                    period_to                 = '2099-12-31',
                    softech_motalba_no        = str(motalbano),
                    applied_local_disc_pct    = local_disc,
                    applied_imported_disc_pct = imported_disc,
                    applied_tarsia_disc_pct   = tarsia_disc,
                )
                claim.save()

                try:
                    summary = import_claim_by_motalbano_batch(
                        claim=claim,
                        motalbano=motalbano,
                        user=None,
                    )
                except InsuranceImportError as e:
                    self.stderr.write(f'Import error: {e}')
                    raise  # triggers rollback

                # Reload fresh from DB
                claim.refresh_from_db()

                self.stdout.write('=' * 60)
                self.stdout.write('IMPORT RESULTS (DRY RUN — will be rolled back)')
                self.stdout.write('=' * 60)
                self.stdout.write(f'  Prescriptions  : {claim.final_rx_count}')
                self.stdout.write(f'  Period         : {claim.period_from} → {claim.period_to}')
                self.stdout.write(f'  محلى           : {claim.final_local_before:,.2f}')
                self.stdout.write(f'  مستورد         : {claim.final_imported_before:,.2f}')
                self.stdout.write(f'  ترسية          : {claim.final_tarsia_before:,.2f}')
                self.stdout.write(f'  Gross          : {claim.final_gross_before:,.2f}')
                self.stdout.write(f'  Discount       : {claim.final_total_discount:,.2f}')
                self.stdout.write(f'  Net            : {claim.final_net_after:,.2f}')
                self.stdout.write('')

                # Comparison against expected
                ok = True
                if opts['expected_rx'] is not None:
                    diff = claim.final_rx_count - opts['expected_rx']
                    status = '✓' if diff == 0 else f'✗ diff={diff:+d}'
                    self.stdout.write(f'  Prescriptions  expected={opts["expected_rx"]}  got={claim.final_rx_count}  {status}')
                    ok = ok and (diff == 0)

                for field, key in [
                    ('Net',      'expected_net'),
                    ('Gross',    'expected_gross'),
                    ('Local',    'expected_local'),
                    ('Imported', 'expected_imported'),
                ]:
                    expected = opts.get(key)
                    if expected is not None:
                        attr_map = {
                            'expected_net':      'final_net_after',
                            'expected_gross':    'final_gross_before',
                            'expected_local':    'final_local_before',
                            'expected_imported': 'final_imported_before',
                        }
                        got   = float(getattr(claim, attr_map[key]))
                        diff  = abs(got - expected)
                        status = '✓' if diff < 1.0 else f'✗ diff={diff:+.2f}'
                        self.stdout.write(f'  {field:<12}   expected={expected:,.2f}  got={got:,.2f}  {status}')
                        ok = ok and (diff < 1.0)

                if opts['expected_rx'] or opts['expected_net']:
                    self.stdout.write('')
                    self.stdout.write('OVERALL: ' + ('PASS ✓' if ok else 'FAIL ✗'))

                # Rollback everything
                raise _Rollback()

        except _Rollback:
            self.stdout.write('')
            self.stdout.write('(Database rolled back — no changes saved)')
        except InsuranceImportError:
            pass  # already logged above


class _Rollback(Exception):
    """Sentinel to trigger transaction rollback after reading results."""
