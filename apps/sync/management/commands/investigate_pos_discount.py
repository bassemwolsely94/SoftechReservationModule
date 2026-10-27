"""
python manage.py investigate_pos_discount

Reverse-engineers the SOFTECH ERP POS Discount workflow.

Runs 10 investigation phases against the live Sybase catalog:
  1.  Discount-related columns in items + known discount tables
  2.  All discount/promotion/pricing tables in sysobjects
  3.  All stored procedures (names + text fragments)
  4.  Procedures referencing items, discount, promo, POS keywords
  5.  Triggers on items and related tables
  6.  Object dependency graph for items table
  7.  Replication objects (subscriptions, articles, queue tables)
  8.  Audit / history tables related to items or prices
  9.  Branch-sync tables (replication queues, pending changes)
  10. Full text of every identified candidate procedure

Output is written to stdout AND saved to:
    docs/softech_pos_discount_investigation.txt
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
    help = 'Reverse-engineer SOFTECH POS Discount workflow'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection
        lines = []

        def log(text=''):
            self.stdout.write(text)
            lines.append(text)

        def section(title):
            bar = '=' * 80
            log('')
            log(bar)
            log(f'  {title}')
            log(bar)

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
        log('Target: SOFTECHDB9.dbo — POS Discount reverse engineering')

        conn = get_sybase_connection()

        # ── PHASE 1: Discount columns in items table ──────────────────────────
        section('PHASE 1: Discount-Related Columns in items Table')
        run(conn, 'All columns in items table', """
            SELECT c.name, t.name AS type, c.length, c.colid
            FROM   SOFTECHDB9.dbo.syscolumns c
            JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
            JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
            WHERE  o.name = 'items'
            ORDER  BY c.colid
        """)

        run(conn, 'Columns with discount/promo/price in name (items)', """
            SELECT c.name, t.name AS type, c.length
            FROM   SOFTECHDB9.dbo.syscolumns c
            JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
            JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
            WHERE  o.name = 'items'
              AND (
                  LOWER(c.name) LIKE '%disc%'
                  OR LOWER(c.name) LIKE '%promo%'
                  OR LOWER(c.name) LIKE '%price%'
                  OR LOWER(c.name) LIKE '%sale%'
                  OR LOWER(c.name) LIKE '%pos%'
                  OR LOWER(c.name) LIKE '%offer%'
                  OR LOWER(c.name) LIKE '%rebate%'
                  OR LOWER(c.name) LIKE '%pct%'
                  OR LOWER(c.name) LIKE '%perc%'
              )
            ORDER BY c.colid
        """)

        # ── PHASE 2: Discount / promotion / pricing tables ────────────────────
        section('PHASE 2: All Discount / Promotion / Pricing Tables in Database')
        run(conn, 'Tables with discount/promo/price/offer in name', """
            SELECT o.name, o.type, o.crdate
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  o.type IN ('U', 'V')
              AND (
                  LOWER(o.name) LIKE '%disc%'
                  OR LOWER(o.name) LIKE '%promo%'
                  OR LOWER(o.name) LIKE '%offer%'
                  OR LOWER(o.name) LIKE '%rebate%'
                  OR LOWER(o.name) LIKE '%price%'
                  OR LOWER(o.name) LIKE '%pric%'
                  OR LOWER(o.name) LIKE '%pos%'
                  OR LOWER(o.name) LIKE '%sale%'
              )
            ORDER BY o.name
        """)

        run(conn, 'All user tables (U) - full list for manual review', """
            SELECT o.name, o.type, o.crdate
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  o.type = 'U'
            ORDER BY o.name
        """)

        # ── PHASE 3: All stored procedures ────────────────────────────────────
        section('PHASE 3: All Stored Procedures (Names)')
        procs = run(conn, 'All stored procedures in SOFTECHDB9', """
            SELECT o.name, o.id, o.crdate
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  o.type = 'P'
            ORDER BY o.name
        """)

        # ── PHASE 4: Procedures referencing discount / items / POS keywords ──
        section('PHASE 4: Procedures Referencing Discount / Items / POS Keywords')

        # Sybase stores procedure text in syscomments
        run(conn, 'Procedures mentioning disc/promo/offer keywords in text', """
            SELECT DISTINCT o.name, o.id
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND (
                  LOWER(sc.text) LIKE '%disc%'
                  OR LOWER(sc.text) LIKE '%promo%'
                  OR LOWER(sc.text) LIKE '%offer%'
              )
            ORDER BY o.name
        """)

        run(conn, 'Procedures mentioning items table in text', """
            SELECT DISTINCT o.name, o.id
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND LOWER(sc.text) LIKE '%items%'
            ORDER BY o.name
        """)

        run(conn, 'Procedures mentioning pos in text', """
            SELECT DISTINCT o.name, o.id
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND LOWER(sc.text) LIKE '%pos%'
            ORDER BY o.name
        """)

        run(conn, 'Procedures mentioning replicat/sync/branch in text', """
            SELECT DISTINCT o.name, o.id
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND (
                  LOWER(sc.text) LIKE '%replicat%'
                  OR LOWER(sc.text) LIKE '%branch%'
                  OR LOWER(sc.text) LIKE '%branchcode%'
              )
            ORDER BY o.name
        """)

        # ── PHASE 5: Triggers on items and related tables ─────────────────────
        section('PHASE 5: All Triggers (All Tables)')
        triggers = run(conn, 'All triggers in database', """
            SELECT o.name AS trigger_name, o2.name AS table_name,
                   o.crdate
            FROM   SOFTECHDB9.dbo.sysobjects o
            JOIN   SOFTECHDB9.dbo.sysobjects o2 ON o2.id = o.deltrig
                                                 OR o2.id = o.instrig
                                                 OR o2.id = o.updtrig
            WHERE  o.type = 'TR'
            ORDER BY o2.name, o.name
        """)

        # Alternative trigger query using sysindexes / deltrig/instrig/updtrig
        run(conn, 'Triggers via sysobjects deltrig/instrig/updtrig columns', """
            SELECT o.name AS table_name,
                   t1.name AS insert_trigger,
                   t2.name AS update_trigger,
                   t3.name AS delete_trigger
            FROM   SOFTECHDB9.dbo.sysobjects o
            LEFT JOIN SOFTECHDB9.dbo.sysobjects t1 ON t1.id = o.instrig
            LEFT JOIN SOFTECHDB9.dbo.sysobjects t2 ON t2.id = o.updtrig
            LEFT JOIN SOFTECHDB9.dbo.sysobjects t3 ON t3.id = o.deltrig
            WHERE  o.type = 'U'
              AND (o.instrig IS NOT NULL OR o.updtrig IS NOT NULL OR o.deltrig IS NOT NULL)
            ORDER BY o.name
        """)

        run(conn, 'Trigger text for triggers on items-related tables', """
            SELECT DISTINCT o.name AS trigger_name, sc.text
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'TR'
              AND (
                  LOWER(sc.text) LIKE '%items%'
                  OR LOWER(sc.text) LIKE '%disc%'
                  OR LOWER(sc.text) LIKE '%price%'
              )
            ORDER BY o.name
        """)

        # ── PHASE 6: Dependency graph for items table ─────────────────────────
        section('PHASE 6: Objects That Reference the items Table (sysdepends)')
        run(conn, 'Objects referencing items table', """
            SELECT DISTINCT o.name AS referencing_object,
                            o.type AS obj_type
            FROM   SOFTECHDB9.dbo.sysdepends d
            JOIN   SOFTECHDB9.dbo.sysobjects  dep_obj ON dep_obj.id = d.depid
            JOIN   SOFTECHDB9.dbo.sysobjects  o       ON o.id       = d.id
            WHERE  dep_obj.name = 'items'
            ORDER BY o.type, o.name
        """)

        # ── PHASE 7: Replication objects ──────────────────────────────────────
        section('PHASE 7: Replication / Queue / Sync Objects')
        run(conn, 'Tables with repl/queue/sync/pending/log in name', """
            SELECT o.name, o.type, o.crdate
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  o.type IN ('U', 'P')
              AND (
                  LOWER(o.name) LIKE '%repl%'
                  OR LOWER(o.name) LIKE '%queue%'
                  OR LOWER(o.name) LIKE '%sync%'
                  OR LOWER(o.name) LIKE '%pending%'
                  OR LOWER(o.name) LIKE '%change%'
                  OR LOWER(o.name) LIKE '%log%'
                  OR LOWER(o.name) LIKE '%shadow%'
                  OR LOWER(o.name) LIKE '%stage%'
                  OR LOWER(o.name) LIKE '%update%'
              )
            ORDER BY o.name
        """)

        # Check Sybase Replication Server system tables
        run(conn, 'Sybase replication: rs_lastcommit, rs_marker, rs_info', """
            SELECT o.name, o.type
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  LOWER(o.name) LIKE 'rs_%'
              OR   LOWER(o.name) LIKE '%replic%'
            ORDER BY o.name
        """)

        # Check for Sybase RepAgent / LTM markers
        run(conn, 'syslogshold — RepAgent log position', """
            SELECT * FROM SOFTECHDB9.dbo.syslogshold
        """)

        # ── PHASE 8: Audit / history tables ───────────────────────────────────
        section('PHASE 8: Audit / History Tables')
        run(conn, 'Tables with hist/audit/trail/log/archive in name', """
            SELECT o.name, o.type, o.crdate
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  o.type = 'U'
              AND (
                  LOWER(o.name) LIKE '%hist%'
                  OR LOWER(o.name) LIKE '%audit%'
                  OR LOWER(o.name) LIKE '%trail%'
                  OR LOWER(o.name) LIKE '%logchang%'
                  OR LOWER(o.name) LIKE '%archive%'
                  OR LOWER(o.name) LIKE '%old%'
                  OR LOWER(o.name) LIKE '%backup%'
              )
            ORDER BY o.name
        """)

        # ── PHASE 9: Columns of discovered discount tables ────────────────────
        section('PHASE 9: Schema of Discount / Promotion Tables Found')
        # We'll query itemsdiscounts, itemspromotions, and any others found
        discount_tables = [
            'itemsdiscount', 'itemsdiscounts', 'itemspromo', 'itemspromotion',
            'itemspromotions', 'itemoffer', 'itemoffers',
            'posdiscount', 'pos_discount', 'pospromo', 'salespromo',
            'itemspos', 'custdiscp', 'custdiscpclassif',
            'discountmaster', 'promohead', 'promodetail',
        ]
        for tbl in discount_tables:
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT c.name, t.name AS type, c.length
                    FROM   SOFTECHDB9.dbo.syscolumns c
                    JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                    JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                    WHERE  o.name = '{tbl}'
                    ORDER  BY c.colid
                """)
                rows = cur.fetchall()
                if rows:
                    log(f'\n  TABLE: {tbl}')
                    for r in rows:
                        log('    ' + ' | '.join(str(c) for c in r))
                cur.close()
            except Exception:
                pass

        # ── PHASE 10: Full text of candidate procedures ───────────────────────
        section('PHASE 10: Full Text of All Candidate Procedures')

        # Get list of procs that mention items AND (disc OR price OR sale)
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT o.name, o.id
                FROM   SOFTECHDB9.dbo.syscomments sc
                JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
                WHERE  o.type = 'P'
                  AND (
                      LOWER(sc.text) LIKE '%itemsaleprice%'
                      OR LOWER(sc.text) LIKE '%unitsaleprice%'
                      OR LOWER(sc.text) LIKE '%posdiscount%'
                      OR LOWER(sc.text) LIKE '%pos_disc%'
                      OR LOWER(sc.text) LIKE '%itemdisc%'
                      OR LOWER(sc.text) LIKE '%custdiscp%'
                      OR LOWER(sc.text) LIKE '%itempromo%'
                      OR LOWER(sc.text) LIKE '%discprice%'
                  )
                ORDER BY o.name
            """)
            candidate_procs = cur.fetchall()
            cur.close()
        except Exception as e:
            log(f'  [ERROR fetching candidate procs] {e}')
            candidate_procs = []

        if not candidate_procs:
            log('  No direct price/discount procedure candidates found via syscomments.')
            log('  Falling back: printing text of ALL procedures mentioning items.')
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT DISTINCT o.name, o.id
                    FROM   SOFTECHDB9.dbo.syscomments sc
                    JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
                    WHERE  o.type = 'P'
                      AND LOWER(sc.text) LIKE '%items%'
                    ORDER BY o.name
                """)
                candidate_procs = cur.fetchall()
                cur.close()
            except Exception as e:
                log(f'  [ERROR] {e}')
                candidate_procs = []

        for row in candidate_procs:
            proc_name = row[0]
            proc_id   = row[1]
            log(f'\n{"─"*70}')
            log(f'  PROCEDURE: {proc_name}  (id={proc_id})')
            log(f'{"─"*70}')
            try:
                cur = conn.cursor()
                # syscomments may split procedure text across multiple rows
                cur.execute("""
                    SELECT sc.colid, sc.text
                    FROM   SOFTECHDB9.dbo.syscomments sc
                    WHERE  sc.id = ?
                    ORDER BY sc.colid
                """, [int(proc_id)])
                text_rows = cur.fetchall()
                full_text = ''.join(str(r[1]) for r in text_rows)
                log(full_text)
                cur.close()
            except Exception as e:
                log(f'  [ERROR reading proc text] {e}')

        # ── PHASE 11: Trigger full text ───────────────────────────────────────
        section('PHASE 11: Full Text of All Triggers')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT o.name, o.id
                FROM   SOFTECHDB9.dbo.sysobjects o
                WHERE  o.type = 'TR'
                ORDER BY o.name
            """)
            all_triggers = cur.fetchall()
            cur.close()
        except Exception as e:
            log(f'  [ERROR] {e}')
            all_triggers = []

        for row in all_triggers:
            trig_name = row[0]
            trig_id   = row[1]
            log(f'\n{"─"*70}')
            log(f'  TRIGGER: {trig_name}  (id={trig_id})')
            log(f'{"─"*70}')
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT sc.colid, sc.text
                    FROM   SOFTECHDB9.dbo.syscomments sc
                    WHERE  sc.id = ?
                    ORDER BY sc.colid
                """, [int(trig_id)])
                text_rows = cur.fetchall()
                full_text = ''.join(str(r[1]) for r in text_rows)
                log(full_text)
                cur.close()
            except Exception as e:
                log(f'  [ERROR reading trigger text] {e}')

        # ── PHASE 12: Sample rows from discount tables ────────────────────────
        section('PHASE 12: Sample Rows from Discovered Discount/Promo Tables')
        for tbl in discount_tables:
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT TOP 5 * FROM SOFTECHDB9.dbo.{tbl}')
                rows = cur.fetchall()
                if rows:
                    log(f'\n  TABLE {tbl} — sample:')
                    for r in rows:
                        log('    ' + ' | '.join(str(c) for c in r))
                cur.close()
            except Exception:
                pass

        # ── Save output ───────────────────────────────────────────────────────
        conn.close()
        log(f'\nInvestigation complete: {datetime.datetime.now().isoformat()}')

        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
        try:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            self.stdout.write(self.style.SUCCESS(f'\nReport saved → {OUTPUT_FILE}'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'\nCould not save file: {e}'))
