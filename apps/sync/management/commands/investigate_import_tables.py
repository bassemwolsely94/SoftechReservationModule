"""
python manage.py investigate_import_tables [--profile prod]

READ-ONLY: the purchasing screen offers ">> Import From 'Receival of Stock Items'".
Direct final stktrans inserts are blocked by tr_stktrans (err 2732). This import path
is the likely trigger-safe channel. Dump the schema of imports/importsm/itemsimports/
itemsimportsm (+ any %recl%/%receiv% tables) and search procs/triggers that reference
them (the import routine).
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..',
                           'docs', 'architecture', 'softech_import_tables_investigation.txt')
TABLES = ['imports', 'importsm', 'itemsimports', 'itemsimportsm']
NULLABLE_BIT = 8


class Command(BaseCommand):
    help = 'READ-ONLY schema+usage of the SOFTECH import (receival) tables'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod')

    def handle(self, *args, **o):
        from config.sybase import SoftechConnector
        lines = []

        def log(t=''):
            self.stdout.write(t); lines.append(t)

        log(f'Import-tables probe: {datetime.datetime.now().isoformat()} (READ-ONLY)')
        conn = SoftechConnector(profile=o['profile']).connect()

        def run(label, sql, params=None):
            log(f'\n--- {label} ---')
            try:
                cur = conn._cursor(); cur.execute(sql, params)
                cols = [d[0] for d in cur.description]; rows = cur.fetchall()
                if not rows:
                    log('  (no rows)'); return
                log('  COLS: ' + ' | '.join(cols))
                for r in rows:
                    log('  ' + ' | '.join('NULL' if c is None else str(c) for c in r))
            except Exception as e:
                log(f'  [ERROR] {e}')

        def schema(tbl):
            log(f'\n  SCHEMA: {tbl}')
            try:
                cur = conn._cursor()
                cur.execute(f"""
                    SELECT c.colid, c.name, t.name, c.length, c.status
                    FROM SOFTECHDB9.dbo.syscolumns c
                    JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id
                    JOIN SOFTECHDB9.dbo.systypes t ON c.usertype=t.usertype
                    WHERE o.name='{tbl}' ORDER BY c.colid""")
                rows = cur.fetchall()
                if not rows:
                    log('    (not found)'); return
                for r in rows:
                    nn = 'NULL' if (int(r[4] or 0) & NULLABLE_BIT) else 'NOT NULL'
                    log(f'    [{str(r[0]):>3}] {str(r[1]):<26} {str(r[2]):<12} len={str(r[3]):<4} {nn}')
            except Exception as e:
                log(f'    [ERROR] {e}')

        for t in TABLES:
            schema(t)
            run(f'{t} COUNT(*)', f"SELECT COUNT(*) AS cnt FROM SOFTECHDB9.dbo.{t}")

        run("other %recl%/%receiv%/%import% tables", """
            SELECT name FROM SOFTECHDB9.dbo.sysobjects
            WHERE type='U' AND (LOWER(name) LIKE '%import%' OR LOWER(name) LIKE '%recl%'
                                OR LOWER(name) LIKE '%receiv%') ORDER BY name""")

        run("procs/triggers referencing the import tables", """
            SELECT DISTINCT o.name, o.type FROM SOFTECHDB9.dbo.syscomments sc
            JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id=o.id
            WHERE o.type IN ('P','TR')
              AND (LOWER(sc.text) LIKE '%itemsimports%' OR LOWER(sc.text) LIKE '%importsm%'
                   OR LOWER(sc.text) LIKE '% imports %') ORDER BY o.name""")

        # Also: what does tr_stktrans / tr_stktransm reference (is body readable?)
        run("tr_stktrans / tr_stktransm readable?", """
            SELECT o.name, CASE WHEN sc.text IS NULL THEN 'HIDDEN' ELSE 'readable' END
            FROM SOFTECHDB9.dbo.sysobjects o
            LEFT JOIN SOFTECHDB9.dbo.syscomments sc ON sc.id=o.id
            WHERE o.name IN ('tr_stktrans','tr_stktransm')""")

        conn.close()
        log(f'\nComplete: {datetime.datetime.now().isoformat()}')
        path = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        self.stdout.write(self.style.SUCCESS(f'\nSaved -> {path}'))
