"""
python manage.py find_points_proc
python manage.py find_points_proc --inspect sp_YourProcName

Step 1 (no args):
    Lists every stored procedure whose name contains 'point', 'pic',
    'loyal', 'reward', or 'redeem'. Run this first to find the right name.

Step 2 (--inspect <name>):
    Prints the full source of that procedure so you can read its parameters.

After identifying name + params, set in .env:
    SOFTECH_POINTS_PROC=<proc_name>
    SOFTECH_POINTS_PROC_HAS_REASON=True   # if the proc takes a reason/note param
"""
from django.core.management.base import BaseCommand
from config.sybase import get_sybase_connection, _safe_str


class Command(BaseCommand):
    help = 'Find and inspect the SOFTECH stored procedure for PIC points'

    def add_arguments(self, parser):
        parser.add_argument(
            '--inspect',
            metavar='PROC_NAME',
            help='Print the full source of this procedure',
        )
        parser.add_argument(
            '--search',
            metavar='KEYWORD',
            default='',
            help='Extra keyword to include in the name search (default searches point/pic/loyal)',
        )

    def handle(self, *args, **options):
        inspect_name = options.get('inspect')
        extra        = options.get('search', '').strip()

        self.stdout.write('\nConnecting to SOFTECH...')
        conn = get_sybase_connection()

        if inspect_name:
            self._show_proc_source(conn, inspect_name)
        else:
            self._list_procs(conn, extra)

        conn.close()

    # ── List matching procedures ───────────────────────────────────────────────

    def _list_procs(self, conn, extra_keyword):
        keywords = ['point', 'pic', 'loyal', 'reward', 'redeem']
        if extra_keyword:
            keywords.append(extra_keyword.lower())

        like_clauses = " OR ".join([f"LOWER(name) LIKE '%{kw}%'" for kw in keywords])
        sql = f"""
            SELECT name, crdate
            FROM SOFTECHDB9.dbo.sysobjects
            WHERE type = 'P'
              AND ({like_clauses})
            ORDER BY name
        """

        cursor = conn.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()

        if not rows:
            self.stdout.write(self.style.WARNING(
                '\nNo matching procedures found.\n'
                'Try broadening the search:\n'
                '  python manage.py find_points_proc --search <keyword>\n\n'
                'Or list ALL procedures:\n'
                '  python manage.py find_points_proc --search ""'
            ))
            # Fall back to listing all procedures
            self._list_all_procs(conn)
            return

        self.stdout.write(self.style.SUCCESS(f'\n{"Procedure Name":<50} Created'))
        self.stdout.write('─' * 70)
        for row in rows:
            name    = _safe_str(row[0]) or str(row[0])
            created = str(row[1]) if row[1] else '—'
            self.stdout.write(f'{name:<50} {created}')

        self.stdout.write(self.style.WARNING(
            '\nTo inspect a procedure\'s parameters:\n'
            '  python manage.py find_points_proc --inspect <proc_name>'
        ))

    def _list_all_procs(self, conn):
        self.stdout.write('\nListing ALL stored procedures instead:')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM SOFTECHDB9.dbo.sysobjects WHERE type = 'P' ORDER BY name"
        )
        rows = cursor.fetchall()
        for row in rows:
            self.stdout.write(f'  {_safe_str(row[0]) or row[0]}')

    # ── Show procedure source ─────────────────────────────────────────────────

    def _show_proc_source(self, conn, proc_name):
        self.stdout.write(f'\nFetching source of: {proc_name}\n')
        self.stdout.write('─' * 70)

        cursor = conn.cursor()
        try:
            cursor.execute(f'EXEC sp_helptext \'{proc_name}\'')
            rows = cursor.fetchall()
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'Failed: {exc}'))
            return

        if not rows:
            self.stdout.write(self.style.ERROR('No source returned — procedure may not exist.'))
            return

        for row in rows:
            text = _safe_str(row[0]) if row[0] else ''
            self.stdout.write(text, ending='')

        self.stdout.write('\n' + '─' * 70)
        self.stdout.write(self.style.SUCCESS('\nOnce you know the parameters, set in .env:'))
        self.stdout.write('  SOFTECH_POINTS_PROC=' + proc_name)
        self.stdout.write('  SOFTECH_POINTS_PROC_HAS_REASON=True   # if proc accepts a reason/note param')
        self.stdout.write('  SOFTECH_POINTS_OPERATOR=CRM            # operator code passed to the proc')
