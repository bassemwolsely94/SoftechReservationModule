"""
apps/finance/management/commands/confirm_finance_tables.py

Auto-confirm the most important financial tables discovered in Phase 0.
Run AFTER discover_finance_schema.

Usage:
    python manage.py confirm_finance_tables          # confirm & show columns
    python manage.py confirm_finance_tables --enable-sync  # also set sync_enabled=True
    python manage.py confirm_finance_tables --dry-run      # show only, don't save

This command:
- Marks the highest-confidence financial tables as is_confirmed=True.
- Optionally marks sync_enabled=True on tables we can actually query.
- Prints detailed column lists so you can plan the sync queries.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.finance.models import FinanceSchemaTable

# ── Tables to auto-confirm ───────────────────────────────────────────────────
#
# Format:  table_name → (confirmed, sync_enabled, override_category, note)
#
# sync_enabled=True only for tables we have working queries for.
# Tables starting with 'acctrans' = real double-entry GL — highest priority.

CONFIRM_MAP: dict[str, dict] = {
    # ── Core journal / ledger ────────────────────────────────────────────
    'acctrans':             {'confirmed': True, 'sync': True,  'category': 'journal',
                             'note': 'Main double-entry journal — debit/credit transactions'},
    'acctrans2':            {'confirmed': True, 'sync': True,  'category': 'journal',
                             'note': 'Secondary acctrans (possibly historical/archive)'},
    'acctrans3':            {'confirmed': True, 'sync': False, 'category': 'journal',
                             'note': 'Third acctrans variant — inspect before enabling'},
    'sacctrans':            {'confirmed': True, 'sync': False, 'category': 'journal',
                             'note': 'Possibly sub-ledger acctrans'},

    # ── stktrans (primary transaction source — already used in sync) ─────
    'stktrans':             {'confirmed': True, 'sync': True,  'category': 'journal',
                             'note': 'Core stock transactions — purchases/sales (already syncing via demand engine)'},
    'stktransm':            {'confirmed': True, 'sync': True,  'category': 'journal',
                             'note': 'Header of stktrans documents'},
    'stktrans5':            {'confirmed': True, 'sync': False, 'category': 'journal',
                             'note': 'Branch-5 stktrans variant'},
    'stktransm5':           {'confirmed': True, 'sync': False, 'category': 'journal',
                             'note': 'Branch-5 stktransm variant'},

    # ── Branch sales aggregates (faster than raw stktrans) ───────────────
    'branchesales':         {'confirmed': True, 'sync': True,  'category': 'revenue',
                             'note': 'Pre-aggregated branch-level sales — ideal for monthly snapshots'},
    'branchesales5':        {'confirmed': True, 'sync': False, 'category': 'revenue',
                             'note': 'Branch-5 sales aggregate'},

    # ── Accounts / COA ───────────────────────────────────────────────────
    'accitems':             {'confirmed': True, 'sync': True,  'category': 'accounts',
                             'note': 'Chart of accounts master — likely code/name/type/parent'},
    'accfinalaccounts':     {'confirmed': True, 'sync': False, 'category': 'accounts',
                             'note': 'Final accounts summary — inspect structure'},
    'saccitems':            {'confirmed': True, 'sync': False, 'category': 'accounts',
                             'note': 'Sub-accounts items'},

    # ── Cheques / Bank ───────────────────────────────────────────────────
    'cheques':              {'confirmed': True, 'sync': True,  'category': 'bank',
                             'note': 'Main cheque register'},
    'cheques5':             {'confirmed': True, 'sync': False, 'category': 'bank',
                             'note': 'Branch-5 cheques'},
    'bankstrans':           {'confirmed': True, 'sync': True,  'category': 'bank',
                             'note': 'Bank transaction movements'},
    'bankcurrenciestrans':  {'confirmed': True, 'sync': False, 'category': 'bank',
                             'note': 'Multi-currency bank transactions'},
    'banks':                {'confirmed': True, 'sync': True,  'category': 'bank',
                             'note': 'Bank master data'},
    'banksopenbal':         {'confirmed': True, 'sync': False, 'category': 'bank',
                             'note': 'Bank opening balances'},
    'bankcurrencies':       {'confirmed': True, 'sync': False, 'category': 'bank',
                             'note': 'Bank currency rates/balances'},
    'branchescash':         {'confirmed': True, 'sync': True,  'category': 'cash',
                             'note': 'Cash balance per branch — very useful for treasury'},

    # ── Expenses ─────────────────────────────────────────────────────────
    'expenses':             {'confirmed': True, 'sync': True,  'category': 'expense',
                             'note': 'Main expense records'},
    'expensesclassif':      {'confirmed': True, 'sync': True,  'category': 'expense',
                             'note': 'Expense classification / categories'},
    'dailyexpenses':        {'confirmed': True, 'sync': True,  'category': 'expense',
                             'note': 'Daily operational expenses'},
    'dailyexpenses5':       {'confirmed': True, 'sync': False, 'category': 'expense',
                             'note': 'Branch-5 daily expenses'},
    'advancedexpenses':     {'confirmed': True, 'sync': False, 'category': 'expense',
                             'note': 'Advanced / pre-paid expenses'},
    'expensesopenbal':      {'confirmed': True, 'sync': False, 'category': 'expense',
                             'note': 'Expense opening balances'},
    'costcenters':          {'confirmed': True, 'sync': True,  'category': 'expense',
                             'note': 'Cost center master data'},
    'costcenterstrans':     {'confirmed': True, 'sync': True,  'category': 'expense',
                             'note': 'Cost center transaction allocation'},

    # ── Payments (customer-facing) ────────────────────────────────────────
    'custpayments':         {'confirmed': True, 'sync': True,  'category': 'payment',
                             'note': 'Customer payment records'},
    'salespay':             {'confirmed': True, 'sync': False, 'category': 'payment',
                             'note': 'Sales payment records'},
    'patientpayments':      {'confirmed': True, 'sync': False, 'category': 'payment',
                             'note': 'Patient/customer payments (clinic context)'},

    # ── Payroll ───────────────────────────────────────────────────────────
    'empsalaries':          {'confirmed': True, 'sync': True,  'category': 'payroll',
                             'note': 'Employee salary records'},

    # ── Invoices ─────────────────────────────────────────────────────────
    'invoices':             {'confirmed': True, 'sync': True,  'category': 'invoice',
                             'note': 'Invoice master records'},

    # ── Receivables ──────────────────────────────────────────────────────
    'localcustomers':       {'confirmed': True, 'sync': True,  'category': 'receivable',
                             'note': 'Local customer master — includes balance/credit info'},
    'localcustomersdatesd': {'confirmed': True, 'sync': False, 'category': 'receivable',
                             'note': 'Customer date-based data'},

    # ── Inventory ─────────────────────────────────────────────────────────
    'stockorders':          {'confirmed': True, 'sync': False, 'category': 'inventory',
                             'note': 'Stock purchase orders'},
    'stockordersm':         {'confirmed': True, 'sync': False, 'category': 'inventory',
                             'note': 'Stock order headers'},
    'stocktaking':          {'confirmed': True, 'sync': False, 'category': 'inventory',
                             'note': 'Physical stock count records'},

    # ── Tax ───────────────────────────────────────────────────────────────
    'personsdatatax':       {'confirmed': True, 'sync': False, 'category': 'tax',
                             'note': 'Tax records per person/customer'},

    # ── Fixed Assets ─────────────────────────────────────────────────────
    'fa_fixedassets':       {'confirmed': True, 'sync': False, 'category': 'expense',
                             'note': 'Fixed assets register'},
    'fa_fixedassets_trans': {'confirmed': True, 'sync': False, 'category': 'expense',
                             'note': 'Fixed asset transactions'},
    'fa_monthlydep':        {'confirmed': True, 'sync': False, 'category': 'expense',
                             'note': 'Monthly depreciation records'},
}


class Command(BaseCommand):
    help = "Auto-confirm high-confidence financial tables from Phase-0 discovery"

    def add_arguments(self, parser):
        parser.add_argument('--enable-sync', action='store_true', default=False,
                            help='Also set sync_enabled=True on tables we have queries for')
        parser.add_argument('--dry-run', action='store_true', default=False,
                            help='Show what would be confirmed without saving')
        parser.add_argument('--show-columns', action='store_true', default=False,
                            help='Print column list for each confirmed table')

    def handle(self, *args, **options):
        enable_sync  = options['enable_sync']
        dry_run      = options['dry_run']
        show_columns = options['show_columns']

        self.stdout.write(self.style.HTTP_INFO(
            '\n  Auto-confirming high-confidence financial tables\n'
        ))
        if dry_run:
            self.stdout.write(self.style.WARNING('  [DRY RUN]\n'))

        not_found    = []
        confirmed    = 0
        sync_enabled = 0

        for table_name, cfg in CONFIRM_MAP.items():
            try:
                obj = FinanceSchemaTable.objects.get(table_name=table_name)
            except FinanceSchemaTable.DoesNotExist:
                not_found.append(table_name)
                continue

            changed = False

            if not obj.is_confirmed:
                if not dry_run:
                    obj.is_confirmed = True
                confirmed += 1
                changed = True

            if enable_sync and cfg['sync'] and not obj.sync_enabled:
                if not dry_run:
                    obj.sync_enabled = True
                sync_enabled += 1
                changed = True

            if cfg.get('category') and not obj.category:
                if not dry_run:
                    obj.category = cfg['category']

            if cfg.get('note') and not obj.notes:
                if not dry_run:
                    obj.notes = cfg['note']

            if changed and not dry_run:
                obj.save(update_fields=['is_confirmed', 'sync_enabled', 'category', 'notes'])

            # Print
            sync_flag = '[S]' if (enable_sync and cfg['sync']) else '   '
            mark = '[OK]' if cfg['confirmed'] else '[  ]'
            self.stdout.write(
                f"  {mark} {sync_flag}  "
                f"{table_name:<40}  {cfg.get('note', '')}"
            )

            if show_columns and obj.columns:
                col_names = [c['name'] for c in obj.columns]
                self.stdout.write(
                    f"        cols: {', '.join(col_names[:15])}"
                    + (' …' if len(col_names) > 15 else '')
                )

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'  Confirmed: {confirmed}  |  Sync-enabled: {sync_enabled}'
        ))

        if not_found:
            self.stdout.write(self.style.WARNING(
                f'\n  Not found in DB (run discover_finance_schema first): '
                f'{", ".join(not_found)}'
            ))

        if not enable_sync:
            self.stdout.write(self.style.HTTP_INFO(
                '\n  Tip: re-run with --enable-sync to also set sync_enabled=True on the core tables.'
            ))

        self.stdout.write(self.style.HTTP_INFO(
            '\n  Next: python manage.py sync_finance --months 3\n'
        ))
