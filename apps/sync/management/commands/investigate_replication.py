"""
python manage.py investigate_replication [itemcode]

Deep investigation of the SOFTECH HQ→Branch replication mechanism.
Runs 8 phases to identify exactly how item master changes propagate.

Phase 1: Nepton Fusion tables (SOFTECH's known sync engine)
Phase 2: tr_items_update trigger — decrypt attempt + sysstat analysis
Phase 3: Sybase RepAgent / RepServer markers
Phase 4: Sybase scheduled jobs (sysschedules / sysjobs)
Phase 5: Queue / pending tables written by trigger chain
Phase 6: Capture state BEFORE a write, make the write, capture AFTER
Phase 7: Compare a branch item state pre/post our write
Phase 8: Check if SOFTECH has a "broadcast" stored procedure
"""
import datetime
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Investigate SOFTECH HQ→Branch replication for item master changes'

    def add_arguments(self, parser):
        parser.add_argument('itemcode', nargs='?', default='127397')

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection, get_branch_connection
        from apps.branches.models import Branch

        itemcode = options['itemcode'].strip()

        def out(text=''):
            safe = str(text).encode('ascii', 'replace').decode('ascii')
            self.stdout.write(safe)

        def section(title):
            out(''); out('=' * 70); out('  ' + title); out('=' * 70)

        def run(conn, label, sql, params=None):
            out(f'\n--- {label} ---')
            try:
                cur = conn.cursor()
                if params:
                    cur.execute(sql, params)
                else:
                    cur.execute(sql)
                rows = cur.fetchall()
                if not rows:
                    out('  (no rows)')
                else:
                    for r in rows:
                        out('  ' + ' | '.join(str(c) for c in r))
                cur.close()
                return rows
            except Exception as e:
                out(f'  ERROR: {e}')
                return []

        conn = get_sybase_connection()
        out(f'Investigation started: {datetime.datetime.now().isoformat()}')
        out(f'Target itemcode: {itemcode}')

        # ── PHASE 1: Nepton Fusion ────────────────────────────────────────────
        section('PHASE 1: Nepton Fusion tables (SOFTECH sync engine)')

        run(conn, 'nepton_fusion TOP 5', """
            SET ROWCOUNT 5
            SELECT * FROM SOFTECHDB9.dbo.nepton_fusion ORDER BY lasttrans_time DESC
        """)
        run(conn, 'nepton_fusionlog TOP 10', """
            SET ROWCOUNT 10
            SELECT * FROM SOFTECHDB9.dbo.nepton_fusionlog ORDER BY trans_time DESC
        """)

        # Check nepton_fusion schema in detail
        run(conn, 'nepton_fusion full schema', """
            SELECT c.name, t.name AS type, c.length, c.colid
            FROM   SOFTECHDB9.dbo.syscolumns c
            JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
            JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
            WHERE  o.name = 'nepton_fusion'
            ORDER  BY c.colid
        """)

        # Any table with 'nepton' in name
        run(conn, 'All nepton tables', """
            SELECT o.name, o.type, o.crdate
            FROM SOFTECHDB9.dbo.sysobjects o
            WHERE LOWER(o.name) LIKE '%nepton%'
            ORDER BY o.name
        """)

        # ── PHASE 2: tr_items_update — status analysis ────────────────────────
        section('PHASE 2: tr_items_update Trigger Deep Analysis')

        run(conn, 'tr_items_update sysstat / sysstat2 / type', """
            SELECT o.name, o.type, o.sysstat, o.sysstat2,
                   o.instrig, o.updtrig, o.deltrig, o.seltrig,
                   o.crdate
            FROM SOFTECHDB9.dbo.sysobjects o
            WHERE o.name = 'tr_items_update'
        """)

        run(conn, 'tr_items_update syscomments row count + first text byte', """
            SELECT sc.colid, sc.number, sc.texttype,
                   DATALENGTH(sc.text) AS text_len,
                   SUBSTRING(CAST(sc.text AS varchar(100)), 1, 50) AS text_prefix
            FROM SOFTECHDB9.dbo.syscomments sc
            JOIN SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE o.name = 'tr_items_update'
            ORDER BY sc.colid
        """)

        # What tables does tr_items_update depend on?
        run(conn, 'tr_items_update dependencies (sysdepends)', """
            SELECT DISTINCT dep_obj.name AS referenced_table,
                            dep_obj.type AS obj_type
            FROM SOFTECHDB9.dbo.sysdepends d
            JOIN SOFTECHDB9.dbo.sysobjects  trig    ON trig.name = 'tr_items_update'
            JOIN SOFTECHDB9.dbo.sysobjects  dep_obj ON dep_obj.id = d.depid
            WHERE d.id = trig.id
            ORDER BY dep_obj.name
        """)

        # ── PHASE 3: Sybase RepAgent / RepServer ──────────────────────────────
        section('PHASE 3: Sybase RepAgent / RepServer Markers')

        for tbl in ['rs_lastcommit', 'rs_marker', 'rs_info', 'rs_threads',
                    'sysrepdescs', 'syslogs', 'syslogshold']:
            try:
                cur = conn.cursor()
                cur.execute('SET ROWCOUNT 3')
                cur.execute(f'SELECT * FROM SOFTECHDB9.dbo.{tbl}')
                rows = cur.fetchall()
                if rows:
                    out(f'\n  TABLE {tbl}:')
                    for r in rows:
                        out('    ' + ' | '.join(str(c) for c in r))
                else:
                    out(f'\n  TABLE {tbl}: (empty)')
                cur.execute('SET ROWCOUNT 0')
                cur.close()
            except Exception as e:
                out(f'\n  TABLE {tbl}: ERROR - {str(e)[:60]}')

        # ── PHASE 4: Sybase scheduled jobs ────────────────────────────────────
        section('PHASE 4: Sybase Scheduled Jobs / Tasks')

        for tbl in ['systasks', 'sysjobs', 'syscrontabs', 'sysschedules',
                    'systasklog', 'sysprocesses']:
            run(conn, f'{tbl} TOP 5', f"""
                SET ROWCOUNT 5
                SELECT * FROM SOFTECHDB9.dbo.{tbl}
            """)

        # ── PHASE 5: All queue/pending tables (items-related) ─────────────────
        section('PHASE 5: Queue / Pending / Change Tables (items-related)')

        # All tables that the trigger chain might write to
        queue_candidates = []
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT o.name
                FROM SOFTECHDB9.dbo.sysobjects o
                WHERE o.type = 'U'
                  AND (
                    LOWER(o.name) LIKE '%item%'
                    OR LOWER(o.name) LIKE '%send%'
                    OR LOWER(o.name) LIKE '%queue%'
                    OR LOWER(o.name) LIKE '%pend%'
                    OR LOWER(o.name) LIKE '%change%'
                    OR LOWER(o.name) LIKE '%update%'
                    OR LOWER(o.name) LIKE '%broad%'
                    OR LOWER(o.name) LIKE '%dist%'
                    OR LOWER(o.name) LIKE '%repl%'
                    OR LOWER(o.name) LIKE '%sync%'
                    OR LOWER(o.name) LIKE '%stage%'
                    OR LOWER(o.name) LIKE '%tmp%'
                    OR LOWER(o.name) LIKE '%temp%'
                  )
                ORDER BY o.name
            """)
            rows = cur.fetchall()
            queue_candidates = [r[0] for r in rows]
            out('\n  Candidate tables:')
            for name in queue_candidates:
                out(f'    {name}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # Row counts for all candidates
        out('\n  Row counts:')
        for tbl in queue_candidates:
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT COUNT(*) FROM SOFTECHDB9.dbo.{tbl}')
                count = cur.fetchone()[0]
                if count and count > 0:
                    out(f'    {tbl}: {count} rows')
                cur.close()
            except Exception:
                pass

        # ── PHASE 6: State capture before/after a fresh item write ────────────
        section('PHASE 6: State Capture Before / After a Fresh Write')

        # Snapshot all tables with content before write
        before_counts = {}
        for tbl in queue_candidates:
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT COUNT(*) FROM SOFTECHDB9.dbo.{tbl}')
                c = cur.fetchone()[0]
                before_counts[tbl] = int(c or 0)
                cur.close()
            except Exception:
                before_counts[tbl] = -1

        # Also snapshot nepton tables
        for tbl in ['nepton_fusion', 'nepton_fusionlog']:
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT COUNT(*) FROM SOFTECHDB9.dbo.{tbl}')
                c = cur.fetchone()[0]
                before_counts[tbl] = int(c or 0)
                cur.close()
            except Exception:
                before_counts[tbl] = -1

        out(f'\n  Baseline row counts captured for {len(before_counts)} tables')

        # Read current item state
        out(f'\n  Item {itemcode} BEFORE write:')
        try:
            cur = conn.cursor()
            cur.execute('SELECT posdiscp, pharmacydiscp, itemsaleprice, itemlastupdate, usercode FROM SOFTECHDB9.dbo.items WHERE itemcode = ?', [itemcode])
            r = cur.fetchone()
            cur.close()
            if r:
                out(f'    pos={r[0]} pharm={r[1]} pack={r[2]} lastupdate={str(r[3])[:19]} user={r[4]}')
        except Exception as e:
            out(f'  ERROR: {e}')

        # Make a test write (increment posdiscp by 1, then revert)
        try:
            cur = conn.cursor()
            cur.execute('SELECT posdiscp FROM SOFTECHDB9.dbo.items WHERE itemcode = ?', [itemcode])
            row = cur.fetchone()
            cur.close()
            orig_val = float(row[0] or 0) if row else 0
            test_val = orig_val + 1

            out(f'\n  Writing test value: posdiscp {orig_val} -> {test_val}')
            cur = conn.cursor()
            cur.execute('UPDATE SOFTECHDB9.dbo.items SET posdiscp = ?, usercode = ? WHERE itemcode = ?',
                        [test_val, '00099', itemcode])
            conn.close()
            out('  Write executed')
        except Exception as e:
            out(f'  Write ERROR: {e}')
            orig_val = None
            test_val = None

        # Re-connect and capture AFTER state
        import time; time.sleep(2)
        conn = get_sybase_connection()

        out('\n  Checking for NEW/CHANGED rows in candidate tables after write:')
        changed_tables = []
        for tbl, before in before_counts.items():
            try:
                cur = conn.cursor()
                qual = 'SOFTECHDB9.dbo.' + tbl if tbl not in ('nepton_fusion', 'nepton_fusionlog') else 'SOFTECHDB9.dbo.' + tbl
                cur.execute(f'SELECT COUNT(*) FROM {qual}')
                after = int(cur.fetchone()[0] or 0)
                cur.close()
                if after != before:
                    diff = after - before
                    out(f'    CHANGED: {tbl}  before={before} after={after} diff={diff:+d}')
                    changed_tables.append(tbl)
            except Exception:
                pass

        if not changed_tables:
            out('    (no row count changes detected in any candidate table)')

        # Show the new rows in changed tables
        for tbl in changed_tables:
            out(f'\n  NEW rows in {tbl}:')
            try:
                cur = conn.cursor()
                cur.execute(f'SET ROWCOUNT 5')
                cur.execute(f'SELECT * FROM SOFTECHDB9.dbo.{tbl} ORDER BY 1 DESC')
                rows = cur.fetchall()
                for r in rows:
                    out('    ' + ' | '.join(str(c) for c in r))
                cur.execute('SET ROWCOUNT 0')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {e}')

        # Verify item state AFTER
        out(f'\n  Item {itemcode} AFTER write:')
        try:
            cur = conn.cursor()
            cur.execute('SELECT posdiscp, pharmacydiscp, itemsaleprice, itemlastupdate, usercode FROM SOFTECHDB9.dbo.items WHERE itemcode = ?', [itemcode])
            r = cur.fetchone()
            cur.close()
            if r:
                out(f'    pos={r[0]} pharm={r[1]} pack={r[2]} lastupdate={str(r[3])[:19]} user={r[4]}')
                # Was itemlastupdate updated by trigger?
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── PHASE 7: Branch comparison immediately after write ────────────────
        section('PHASE 7: Branch item State After HQ Write (immediate)')

        branches = Branch.objects.filter(
            is_operational=True, db_host__isnull=False
        ).exclude(softech_branch_id='100').exclude(db_host='')

        for b in branches:
            try:
                bc = get_branch_connection(b.db_host, b.db_port or 5000)
                cur = bc.cursor()
                cur.execute('SELECT posdiscp, itemsaleprice, usercode FROM items WHERE itemcode = ?', [itemcode])
                r = cur.fetchone()
                bc.close()
                if r:
                    expected = abs(float(r[0] or 0) - float(test_val or 0)) < 0.01 if test_val else False
                    match = 'REPLICATED' if expected else 'NOT-YET'
                    out(f'  BR{b.softech_branch_id} ({b.db_host}): {match} pos_discp={r[0]} pack={r[1]} user={r[2]}')
            except Exception as e:
                out(f'  BR{b.softech_branch_id}: ERROR {str(e)[:60]}')

        # ── PHASE 8: Stored procedures for broadcast / sync ───────────────────
        section('PHASE 8: Stored Procedures for Broadcast / Item Sync')

        run(conn, 'Procs with broadcast/send/dist/nepton/sync in name', """
            SELECT o.name, o.crdate
            FROM SOFTECHDB9.dbo.sysobjects o
            WHERE o.type = 'P'
              AND (
                  LOWER(o.name) LIKE '%broad%'
                  OR LOWER(o.name) LIKE '%send%'
                  OR LOWER(o.name) LIKE '%dist%'
                  OR LOWER(o.name) LIKE '%nepton%'
                  OR LOWER(o.name) LIKE '%sync%'
                  OR LOWER(o.name) LIKE '%item%update%'
                  OR LOWER(o.name) LIKE '%update%item%'
                  OR LOWER(o.name) LIKE '%repl%'
              )
            ORDER BY o.name
        """)

        run(conn, 'Procs mentioning nepton in text', """
            SELECT DISTINCT o.name
            FROM SOFTECHDB9.dbo.syscomments sc
            JOIN SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE o.type = 'P'
              AND LOWER(sc.text) LIKE '%nepton%'
            ORDER BY o.name
        """)

        run(conn, 'All objects referencing nepton_fusion', """
            SELECT DISTINCT o.name, o.type
            FROM SOFTECHDB9.dbo.sysdepends d
            JOIN SOFTECHDB9.dbo.sysobjects dep_obj ON dep_obj.id = d.depid
            JOIN SOFTECHDB9.dbo.sysobjects o        ON o.id       = d.id
            WHERE dep_obj.name IN ('nepton_fusion', 'nepton_fusionlog')
            ORDER BY o.type, o.name
        """)

        # Full text of any proc referencing nepton
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT o.name
                FROM SOFTECHDB9.dbo.syscomments sc
                JOIN SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
                WHERE o.type IN ('P', 'TR')
                  AND LOWER(sc.text) LIKE '%nepton%'
            """)
            objs = cur.fetchall()
            cur.close()
            for row in objs:
                name = row[0]
                out(f'\n--- OBJECT: {name} ---')
                try:
                    cur = conn.cursor()
                    cur.execute("""
                        SELECT sc.colid, sc.text
                        FROM SOFTECHDB9.dbo.syscomments sc
                        JOIN SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
                        WHERE o.name = ?
                        ORDER BY sc.colid
                    """, [name])
                    texts = cur.fetchall()
                    full = ''.join(str(r[1]) for r in texts)
                    out(full.encode('ascii', 'replace').decode('ascii'))
                    cur.close()
                except Exception as e:
                    out(f'  ERROR reading text: {e}')
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── Revert test write ─────────────────────────────────────────────────
        section('Reverting test write')
        if orig_val is not None:
            try:
                cur = conn.cursor()
                cur.execute('UPDATE SOFTECHDB9.dbo.items SET posdiscp = ?, usercode = ? WHERE itemcode = ?',
                            [orig_val, '00099', itemcode])
                conn.close()
                out(f'  Reverted posdiscp back to {orig_val}')
            except Exception as e:
                out(f'  Revert ERROR: {e}')
        else:
            conn.close()

        out(f'\nInvestigation complete: {datetime.datetime.now().isoformat()}')
