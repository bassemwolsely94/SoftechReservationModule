"""
python manage.py find_points_column

Prints every column in localcustomers with a sample value so you can
identify the one that stores the PIC points balance.

Set SOFTECH_POINTS_COLUMN in .env to whatever column name you find here.
"""
from django.core.management.base import BaseCommand
from config.sybase import get_sybase_connection


class Command(BaseCommand):
    help = 'List all localcustomers columns with a sample row value'

    def handle(self, *args, **options):
        self.stdout.write('\nConnecting to SOFTECH...')
        conn = get_sybase_connection()

        # SET ROWCOUNT 1 to limit the result to one row
        c1 = conn.cursor()
        c1.execute('SET ROWCOUNT 1')

        c2 = conn.cursor()
        c2.execute(
            'SELECT * FROM SOFTECHDB9.dbo.localcustomers '
            'WHERE phcode IS NOT NULL'
        )

        cols = [d[0] for d in c2.description]
        row  = c2.fetchone()

        c3 = conn.cursor()
        c3.execute('SET ROWCOUNT 0')
        conn.close()

        if not row:
            self.stdout.write(self.style.ERROR('No rows returned — check the connection or table name.'))
            return

        self.stdout.write(self.style.SUCCESS(f'\n{"Column":<35} Value'))
        self.stdout.write('─' * 70)
        for col, val in zip(cols, row):
            self.stdout.write(f'{col:<35} {val}')

        self.stdout.write('\n')
        self.stdout.write(self.style.WARNING(
            'Look for the column holding the numeric points balance.\n'
            'Then set in .env:  SOFTECH_POINTS_COLUMN=<column_name>'
        ))
