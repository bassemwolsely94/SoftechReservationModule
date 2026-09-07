"""
python manage.py investigate_pos_discount2

Focused phase-2 investigation based on Phase-1 findings:
  - items.posdiscp confirmed as the POS discount column
  - Target tables: custdiscounts, managerdiscount, offers, offersm, mitemshist, mitems
  - Stored procedures referencing posdiscp
  - Triggers on items table
  - items_hist / mitemshist schema
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__),
    '..', '..', '..', '..', '..', 'docs',
    'softech_pos_discount_investigation.txt'
)


class Command(BaseCommand):
    help = 'Focused POS discount investigation (phase 2)'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection
        lines = []

        def log(text=''):
            self.stdout.write(text)
            lines.append(text)

        def section(title):
            bar = '=' * 80
            log(''); log(bar); log(f'  {title}'); log(bar)

        def schema(conn, tbl):
            log(f'\n  SCHEMA: {tbl}')
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT c.name, t.name AS type, c.length, c.colid
                    FROM   SOFTECHDB9.dbo.syscolumns c
                    JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                    JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                    WHERE  o.name = '{tbl}'
                    ORDER  BY c.colid
                """)
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        log(f'    [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
                else:
                    log('    (table not found or no columns)')
                cur.close()
            except Exception as e:
                log(f'    [ERROR] {e}')

        def proc_text(conn, proc_name):
            log(f'\n{"─"*70}')
            log(f'  PROCEDURE: {proc_name}')
            log(f'{"─"*70}')
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT sc.colid, sc.text
                    FROM   SOFTECHDB9.dbo.syscomments sc
                    JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
                    WHERE  o.name = ? AND o.type = 'P'
                    ORDER BY sc.colid
                """, [proc_name])
                rows = cur.fetchall()
                if rows:
                    log(''.join(str(r[1]) for r in rows))
                else:
                    log('  (no text found — may be encrypted)')
                cur.close()
            except Exception as e:
                log(f'  [ERROR] {e}')

        def trig_text(conn, trig_name):
            log(f'\n{"─"*70}')
            log(f'  TRIGGER: {trig_name}')
            log(f'{"─"*70}')
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT sc.colid, sc.text
                    FROM   SOFTECHDB9.dbo.syscomments sc
                    JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
                    WHERE  o.name = ? AND o.type = 'TR'
                    ORDER BY sc.colid
                """, [trig_name])
                rows = cur.fetchall()
                if rows:
                    log(''.join(str(r[1]) for r in rows))
                else:
                    log('  (no text found — may be encrypted)')
                cur.close()
            except Exception as e:
                log(f'  [ERROR] {e}')

        def run(conn, label, sql, params=None):
            log(f'\n--- {label} ---')
            try:
                cur = conn.cursor()
                if params:
                    cur.execute(sql, params)
                else:
                    cur.execute(sql)
                rows = cur.fetchall()
                if not rows:
                    log('  (no rows)')
                else:
                    for r in rows:
                        log('  ' + ' | '.join(str(c) for c in r))
                cur.close()
                return rows
            except Exception as e:
                log(f'  [ERROR] {e}')
                return []

        log(f'Investigation started: {datetime.datetime.now().isoformat()}')
        conn = get_sybase_connection()

        # ── A: Triggers on items table ────────────────────────────────────────
        section('A: Triggers Attached to items Table')
        run(conn, 'items table instrig/updtrig/deltrig', """
            SELECT o.name AS table_name,
                   t1.name AS insert_trigger,
                   t2.name AS update_trigger,
                   t3.name AS delete_trigger
            FROM   SOFTECHDB9.dbo.sysobjects o
            LEFT JOIN SOFTECHDB9.dbo.sysobjects t1 ON t1.id = o.instrig
            LEFT JOIN SOFTECHDB9.dbo.sysobjects t2 ON t2.id = o.updtrig
            LEFT JOIN SOFTECHDB9.dbo.sysobjects t3 ON t3.id = o.deltrig
            WHERE  o.name = 'items'
        """)

        run(conn, 'All triggers whose text mentions posdiscp', """
            SELECT DISTINCT o.name AS trigger_name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'TR'
              AND  LOWER(sc.text) LIKE '%posdiscp%'
            ORDER BY o.name
        """)

        run(conn, 'All triggers whose text mentions items', """
            SELECT DISTINCT o.name AS trigger_name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'TR'
              AND  LOWER(sc.text) LIKE '%items%'
            ORDER BY o.name
        """)

        # ── B: Stored procedures referencing posdiscp ─────────────────────────
        section('B: Stored Procedures Referencing posdiscp / Discount Fields')
        procs_posdiscp = run(conn, 'Procs mentioning posdiscp', """
            SELECT DISTINCT o.name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND  LOWER(sc.text) LIKE '%posdiscp%'
            ORDER BY o.name
        """)

        procs_pharmacydisc = run(conn, 'Procs mentioning pharmacydiscp', """
            SELECT DISTINCT o.name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND  LOWER(sc.text) LIKE '%pharmacydiscp%'
            ORDER BY o.name
        """)

        procs_additionaldisc = run(conn, 'Procs mentioning additionaldiscp', """
            SELECT DISTINCT o.name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND  LOWER(sc.text) LIKE '%additionaldiscp%'
            ORDER BY o.name
        """)

        run(conn, 'Procs mentioning specialdiscp', """
            SELECT DISTINCT o.name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND  LOWER(sc.text) LIKE '%specialdiscp%'
            ORDER BY o.name
        """)

        run(conn, 'Procs with UPDATE items in text', """
            SELECT DISTINCT o.name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND  LOWER(sc.text) LIKE '%update%items%'
            ORDER BY o.name
        """)

        # ── C: Schemas of key discount tables ────────────────────────────────
        section('C: Schema of Key Discount / History Tables')
        for tbl in [
            'custdiscounts', 'custdiscounts_hist', 'custdiscountstrans',
            'managerdiscount', 'offers', 'offersm',
            'mitemshist', 'mitems', 'mitemssys',
            'items_hist', 'itemshist', 'itemslog', 'itemshistory',
            'itemsupdate', 'items_update',
        ]:
            schema(conn, tbl)

        # ── D: Sample rows from mitemshist (item history) ─────────────────────
        section('D: Sample Rows from mitemshist (Item History Table)')
        run(conn, 'mitemshist — 10 most recent rows', """
            SELECT TOP 10 *
            FROM SOFTECHDB9.dbo.mitemshist
            ORDER BY 1 DESC
        """)

        run(conn, 'mitemshist — rows with posdiscp field value', """
            SELECT TOP 10 *
            FROM SOFTECHDB9.dbo.mitemshist
            WHERE colchanged LIKE '%posdiscp%'
              OR  fieldname   LIKE '%posdiscp%'
              OR  colname     LIKE '%posdiscp%'
        """)

        # ── E: custdiscounts sample ───────────────────────────────────────────
        section('E: custdiscounts Schema and Sample')
        run(conn, 'custdiscounts TOP 5', """
            SELECT TOP 5 * FROM SOFTECHDB9.dbo.custdiscounts
        """)
        run(conn, 'custdiscounts_hist TOP 5', """
            SELECT TOP 5 * FROM SOFTECHDB9.dbo.custdiscounts_hist
        """)
        run(conn, 'managerdiscount TOP 5', """
            SELECT TOP 5 * FROM SOFTECHDB9.dbo.managerdiscount
        """)

        # ── F: offers / offersm schema ────────────────────────────────────────
        section('F: offers / offersm Schema and Sample')
        schema(conn, 'offers')
        schema(conn, 'offersm')
        run(conn, 'offers TOP 5', """
            SELECT TOP 5 * FROM SOFTECHDB9.dbo.offers
        """)
        run(conn, 'offersm TOP 5', """
            SELECT TOP 5 * FROM SOFTECHDB9.dbo.offersm
        """)

        # ── G: replication markers ────────────────────────────────────────────
        section('G: Replication Markers and Queue Tables')
        run(conn, 'rs_lastcommit', """
            SELECT * FROM SOFTECHDB9.dbo.rs_lastcommit
        """)
        run(conn, 'Tables named *repl* or *rs_*', """
            SELECT o.name, o.type
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  (LOWER(o.name) LIKE 'rs_%' OR LOWER(o.name) LIKE '%repl%')
              AND  o.type = 'U'
            ORDER BY o.name
        """)

        # ── H: All trigger names (for full audit) ─────────────────────────────
        section('H: All Trigger Names in Database')
        all_trigs = run(conn, 'All triggers', """
            SELECT o.name, o.crdate
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  o.type = 'TR'
            ORDER BY o.name
        """)

        # ── I: Full text of posdiscp procedures ──────────────────────────────
        section('I: Full Text of posdiscp Procedures')
        for row in procs_posdiscp:
            proc_text(conn, row[0])

        section('I2: Full Text of pharmacydiscp Procedures')
        for row in procs_pharmacydisc:
            proc_text(conn, row[0])

        section('I3: Full Text of additionaldiscp Procedures')
        for row in procs_additionaldisc:
            proc_text(conn, row[0])

        # ── J: Full text of ALL triggers ─────────────────────────────────────
        section('J: Full Text of ALL Triggers')
        for row in all_trigs:
            trig_text(conn, row[0])

        # ── K: syscomments encryption check ──────────────────────────────────
        section('K: Encrypted Objects (status bit 0x2000)')
        run(conn, 'Encrypted procedures', """
            SELECT o.name, o.type
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  o.type IN ('P', 'TR')
              AND  (o.sysstat & 0x2000) = 0x2000
            ORDER BY o.name
        """)

        conn.close()
        log(f'\nComplete: {datetime.datetime.now().isoformat()}')

        os.makedirs(os.path.dirname(os.path.abspath(OUTPUT_FILE)), exist_ok=True)
        try:
            with open(os.path.abspath(OUTPUT_FILE), 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            self.stdout.write(self.style.SUCCESS(f'\nSaved → {os.path.abspath(OUTPUT_FILE)}'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'\nCould not save: {e}'))
