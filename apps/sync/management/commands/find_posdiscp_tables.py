"""
python manage.py find_posdiscp_tables

Find EVERY table that carries a posdiscp column (HQ + branch), plus any
per-branch item staging tables and change-tracking tables the SSB9 service
bus could poll. This pins down how posdiscp actually replicates.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Locate every table carrying posdiscp + item change-tracking tables'

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='160')

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection, get_branch_connection
        from apps.branches.models import Branch

        def out(t=''):
            self.stdout.write(str(t).encode('ascii', 'replace').decode('ascii'))

        def sec(t):
            out(''); out('=' * 70); out('  ' + t); out('=' * 70)

        def scan(conn, label, dbq):
            # 1. every column named posdiscp
            out(f'\n--- {label}: ALL tables with a posdiscp column ---')
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT o.name AS table_name, o.type, c.length
                    FROM {dbq}syscolumns c
                    JOIN {dbq}sysobjects o ON c.id = o.id
                    WHERE c.name = 'posdiscp' AND o.type IN ('U','V')
                    ORDER BY o.name
                """)
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        out(f'    {r[0]}  (type={r[1]} len={r[2]})')
                else:
                    out('    (none)')
                cur.close()
            except Exception as e:
                out(f'    ERROR: {str(e)[:90]}')

            # 2. per-branch item tables (itemcode + branchcode) — list & check posdiscp
            out(f'\n--- {label}: tables having BOTH itemcode AND branchcode ---')
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT o.name,
                           MAX(CASE WHEN c.name='posdiscp' THEN 1 ELSE 0 END) AS has_pos,
                           MAX(CASE WHEN c.name='itemsaleprice' THEN 1 ELSE 0 END) AS has_price,
                           MAX(CASE WHEN c.name='pharmacydiscp' THEN 1 ELSE 0 END) AS has_pharm
                    FROM {dbq}sysobjects o
                    JOIN {dbq}syscolumns c ON c.id = o.id
                    WHERE o.type='U'
                      AND o.id IN (SELECT id FROM {dbq}syscolumns WHERE name='itemcode')
                      AND o.id IN (SELECT id FROM {dbq}syscolumns WHERE name='branchcode')
                    GROUP BY o.name
                    ORDER BY o.name
                """)
                rows = cur.fetchall()
                for r in rows:
                    flags = []
                    if r[1]: flags.append('posdiscp')
                    if r[2]: flags.append('itemsaleprice')
                    if r[3]: flags.append('pharmacydiscp')
                    out(f'    {r[0]:<28} -> {", ".join(flags) if flags else "(no price cols)"}')
                cur.close()
            except Exception as e:
                out(f'    ERROR: {str(e)[:90]}')

            # 3. all tables whose name starts with 'br' or contains 'item' (price-ish)
            out(f'\n--- {label}: br*/item* tables (names) ---')
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT o.name FROM {dbq}sysobjects o
                    WHERE o.type='U'
                      AND (LOWER(o.name) LIKE 'br%' OR LOWER(o.name) LIKE '%britem%'
                           OR LOWER(o.name) LIKE 'r3%')
                    ORDER BY o.name
                """)
                names = [r[0] for r in cur.fetchall()]
                out('    ' + ', '.join(names))
                cur.close()
            except Exception as e:
                out(f'    ERROR: {str(e)[:90]}')

        # HQ
        sec('HQ (SOFTECHDB9)')
        conn = get_sybase_connection()
        scan(conn, 'HQ', 'SOFTECHDB9.dbo.')
        conn.close()

        # Branch
        b = Branch.objects.get(softech_branch_id=options['branch'])
        sec(f'BRANCH {options["branch"]} ({b.db_host})')
        try:
            bc = get_branch_connection(b.db_host, b.db_port or 5000)
            scan(bc, f'BR{options["branch"]}', 'dbo.')
            bc.close()
        except Exception as e:
            out(f'  branch connect ERROR: {str(e)[:80]}')

        out('\nDONE.')
