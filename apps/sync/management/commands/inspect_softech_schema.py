"""
python manage.py inspect_softech_schema [table_name]

Queries SOFTECHDB9 syscolumns to print the real column names for a table.
Use this whenever a sync query errors with 'Invalid column name'.

Examples:
    python manage.py inspect_softech_schema localcustomers
    python manage.py inspect_softech_schema items
    python manage.py inspect_softech_schema stktrans
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Print real SOFTECH column names for a given table'

    def add_arguments(self, parser):
        parser.add_argument('table', nargs='?', default='localcustomers',
                            help='Table name in SOFTECHDB9.dbo (default: localcustomers)')

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection
        table = options['table']
        self.stdout.write(f"Fetching columns for SOFTECHDB9.dbo.{table} ...\n")
        try:
            conn = get_sybase_connection()
            cursor = conn.cursor()
            # Sybase ASE — syscolumns + sysobjects (database-qualified)
            cursor.execute(f"""
                SELECT c.name, t.name AS type, c.length
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.name = '{table}'
                ORDER  BY c.colid
            """)
            rows = cursor.fetchall()
            if not rows:
                self.stdout.write(self.style.WARNING(
                    f"No columns found — check table name (case-sensitive in Sybase)."
                ))
                return
            self.stdout.write(f"{'Col':>4}  {'Name':<30}  {'Type':<15}  Len\n")
            self.stdout.write('-' * 60 + '\n')
            for i, row in enumerate(rows):
                self.stdout.write(f"{i:>4}  {str(row[0]):<30}  {str(row[1]):<15}  {row[2]}\n")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[FAIL] {e}"))
