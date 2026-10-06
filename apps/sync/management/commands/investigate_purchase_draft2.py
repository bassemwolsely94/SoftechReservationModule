"""
python manage.py investigate_purchase_draft2 [--profile prod]

READ-ONLY: the "Temporarily Save On-Screen Data" purchase draft is NOT in
stktransm5 (confirmed). Hunt it in the temp_* candidates and, failing that, by
brute-search every user table that has a 'docnumber2' column for the supplier
invoice no 1124578 (the draft we just saved: supplier PHARMA OVER SEAS, total
371.25, items 404 UROSOLVINE & 2138 TOBRIN).

ABSOLUTE RULE: SELECT only.
Output -> docs/architecture/softech_purchase_draft_investigation2.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'architecture',
    'softech_purchase_draft_investigation2.txt',
)
NULLABLE_BIT = 8
TEMP_CANDIDATES = ['temp_invoices', 'temp_inv5', 'temp_inv6', 'temp_snos', 'temp_sitems']


class Command(BaseCommand):
    help = 'READ-ONLY hunt for the purchase draft in temp_* tables'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod')

    def handle(self, *args, **options):
        from config.sybase import SoftechConnector
        lines = []

        def log(t=''):
            self.stdout.write(t); lines.append(t)

        def section(title):
            log(''); log('=' * 80); log(f'  {title}'); log('=' * 80)

        log(f'Purchase-draft hunt: {datetime.datetime.now().isoformat()}  (READ-ONLY)')
        try:
            conn = SoftechConnector(profile=options['profile']).connect()
        except Exception as e:
            log(f'[FATAL] connect: {e}'); self._save(lines); return

        def set_rowcount(n):
            try:
                conn._cursor().execute(f'SET ROWCOUNT {n}')
            except Exception:
                pass

        def run(label, sql, params=None):
            log(f'\n--- {label} ---')
            try:
                cur = conn._cursor(); cur.execute(sql, params)
                cols = [d[0] for d in cur.description]; rows = cur.fetchall()
                if not rows:
                    log('  (no rows)'); return []
                log('  COLS: ' + ' | '.join(cols))
                for r in rows:
                    log('  ' + ' | '.join('NULL' if c is None else str(c) for c in r))
                return rows
            except Exception as e:
                log(f'  [ERROR] {e}'); return []

        def schema(tbl):
            log(f'\n  SCHEMA: {tbl}')
            try:
                cur = conn._cursor()
                cur.execute(f"""
                    SELECT c.colid, c.name, t.name AS type, c.length
                    FROM SOFTECHDB9.dbo.syscolumns c
                    JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id
                    JOIN SOFTECHDB9.dbo.systypes   t ON c.usertype=t.usertype
                    WHERE o.name='{tbl}' ORDER BY c.colid
                """)
                rows = cur.fetchall()
                if not rows:
                    log('    (not found)'); return []
                names = []
                for r in rows:
                    names.append(str(r[1]).strip())
                    log(f'    [{str(r[0]):>3}] {str(r[1]):<26} {str(r[2]):<12} len={r[3]}')
                return names
            except Exception as e:
                log(f'    [ERROR] {e}'); return []

        # ── 1. temp_* candidate tables: schema + row count + recent sample ────
        section('1: temp_* candidate tables (schema, count, sample)')
        for tbl in TEMP_CANDIDATES:
            cols = schema(tbl)
            if not cols:
                continue
            run(f'{tbl} row count', f"SELECT COUNT(*) AS cnt FROM SOFTECHDB9.dbo.{tbl}")
            set_rowcount(3)
            run(f'{tbl} sample (3 rows)', f"SELECT * FROM SOFTECHDB9.dbo.{tbl}")
            set_rowcount(0)
            # If it has docnumber2, search for our draft directly
            if any(c.lower() == 'docnumber2' for c in cols):
                run(f'{tbl} WHERE docnumber2=1124578', f"""
                    SELECT * FROM SOFTECHDB9.dbo.{tbl} WHERE docnumber2=1124578
                """)
            if any(c.lower() in ('itemcode',) for c in cols):
                run(f'{tbl} WHERE itemcode IN (404,2138)', f"""
                    SELECT * FROM SOFTECHDB9.dbo.{tbl} WHERE itemcode IN ('404','2138')
                """)

        # ── 2. brute search: every user table with a docnumber2 column ────────
        section('2: every user table that HAS a docnumber2 column')
        run('tables with docnumber2', """
            SELECT o.name FROM SOFTECHDB9.dbo.syscolumns c
            JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id
            WHERE o.type='U' AND LOWER(c.name)='docnumber2' ORDER BY o.name
        """)

        # ── 3. user tables modified/likely holding the draft: name LIKE temp/screen/grid ─
        section('3: more candidate names (screen/grid/onscreen/save/buff)')
        for pat in ('%screen%', '%grid%', '%onscreen%', '%save%', '%buff%', '%import%', '%recv%', '%recl%'):
            run(f"name LIKE '{pat}'", f"""
                SELECT o.name FROM SOFTECHDB9.dbo.sysobjects o
                WHERE o.type='U' AND LOWER(o.name) LIKE '{pat}' ORDER BY o.name
            """)

        conn.close()
        log(f'\nComplete: {datetime.datetime.now().isoformat()}')
        self._save(lines)

    def _save(self, lines):
        path = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            self.stdout.write(self.style.SUCCESS(f'\nSaved -> {path}'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'\nCould not save: {e}'))
