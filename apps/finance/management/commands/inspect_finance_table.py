"""
apps/finance/management/commands/inspect_finance_table.py

Inspect any SOFTECH table: show columns + sample rows.
Use this to understand a newly discovered table before writing sync queries.

Usage:
    python manage.py inspect_finance_table acctrans
    python manage.py inspect_finance_table branchesales --rows 5
    python manage.py inspect_finance_table expenses --rows 3
"""

from django.core.management.base import BaseCommand

from apps.finance.queries.sybase_accounting import inspect_table


class Command(BaseCommand):
    help = "Inspect columns and sample rows of a SOFTECH table (SELECT-only)"

    def add_arguments(self, parser):
        parser.add_argument('table', help='Table name in SOFTECHDB9')
        parser.add_argument('--rows', type=int, default=3,
                            help='Number of sample rows to show (default: 3)')

    def handle(self, *args, **options):
        table_name = options['table']
        n_rows     = options['rows']

        self.stdout.write(self.style.HTTP_INFO(
            f'\n  Inspecting SOFTECHDB9.dbo.{table_name}\n'
        ))

        result = inspect_table(table_name, sample_rows=n_rows)

        if 'error' in result:
            self.stderr.write(self.style.ERROR(f"  Error: {result['error']}"))
            return

        cols = result.get('columns', [])
        self.stdout.write(f"  Columns ({len(cols)}):\n")
        for c in cols:
            self.stdout.write(f"    • {c}")

        sample = result.get('sample', [])
        if sample:
            self.stdout.write(f"\n  Sample rows ({len(sample)}):\n")
            for i, row in enumerate(sample, 1):
                self.stdout.write(f"\n  Row {i}:")
                for k, v in row.items():
                    if v is not None and str(v).strip():
                        self.stdout.write(f"    {k:<30} = {v}")
        else:
            self.stdout.write('\n  (no rows found)')

        self.stdout.write('')
