"""
python manage.py investigate_britems

Deep investigation of britems / r3britems — the tables that
tr_items_update depends on (from sysdepends). These are the key
to SOFTECH's HQ->branch item replication mechanism.

Also checks on EACH branch server to find the counterpart tables
and how they consume the queue.
"""
import datetime
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Investigate britems/r3britems replication tables'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection, get_branch_connection
        from apps.branches.models import Branch

        def out(text=''):
            safe = str(text).encode('ascii', 'replace').decode('ascii')
            self.stdout.write(safe)

        def section(title):
            out(''); out('=' * 70); out('  ' + title); out('=' * 70)

        conn = get_sybase_connection()
        out(f'Started: {datetime.datetime.now().isoformat()}')

        # ── SCHEMAS ───────────────────────────────────────────────────────────
        section('SCHEMA: britems')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.name, t.name AS type, c.length, c.colid
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.name = 'britems'
                ORDER  BY c.colid
            """)
            for r in cur.fetchall():
                out(f'  [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        section('SCHEMA: r3britems')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.name, t.name AS type, c.length, c.colid
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.name = 'r3britems'
                ORDER  BY c.colid
            """)
            for r in cur.fetchall():
                out(f'  [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        section('SCHEMA: branchstores')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.name, t.name AS type, c.length, c.colid
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.name = 'branchstores'
                ORDER  BY c.colid
            """)
            for r in cur.fetchall():
                out(f'  [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── SAMPLE ROWS ───────────────────────────────────────────────────────
        section('SAMPLE: britems (TOP 5)')
        try:
            cur = conn.cursor()
            cur.execute('SET ROWCOUNT 5')
            cur.execute('SELECT * FROM SOFTECHDB9.dbo.britems ORDER BY 1 DESC')
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out('  ' + ' | '.join(str(c) for c in r))
            else:
                out('  (empty)')
            cur.execute('SET ROWCOUNT 0')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        section('SAMPLE: r3britems (TOP 5, most recent)')
        try:
            cur = conn.cursor()
            cur.execute('SET ROWCOUNT 5')
            cur.execute('SELECT * FROM SOFTECHDB9.dbo.r3britems ORDER BY 1 DESC')
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out('  ' + ' | '.join(str(c) for c in r))
            else:
                out('  (empty)')
            cur.execute('SET ROWCOUNT 0')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        section('COUNT: britems and r3britems')
        for tbl in ['britems', 'r3britems']:
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT COUNT(*) FROM SOFTECHDB9.dbo.{tbl}')
                out(f'  {tbl}: {cur.fetchone()[0]} rows')
                cur.close()
            except Exception as e:
                out(f'  {tbl}: ERROR {e}')

        # ── TRIGGERS AND OBJECTS THAT WRITE TO britems / r3britems ────────────
        section('Objects that WRITE to britems / r3britems (sysdepends)')
        for target in ['britems', 'r3britems']:
            out(f'\n  References to {target}:')
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT DISTINCT o.name, o.type
                    FROM SOFTECHDB9.dbo.sysdepends d
                    JOIN SOFTECHDB9.dbo.sysobjects dep ON dep.id = d.depid
                    JOIN SOFTECHDB9.dbo.sysobjects o   ON o.id   = d.id
                    WHERE dep.name = ?
                    ORDER BY o.type, o.name
                """, [target])
                rows = cur.fetchall()
                for r in rows:
                    out(f'    {r[1]}: {r[0]}')
                if not rows:
                    out('    (none in sysdepends)')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {e}')

        # ── TRIGGERS on britems ────────────────────────────────────────────────
        section('Triggers on britems table')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT o.name AS table_name,
                       t1.name AS insert_trigger,
                       t2.name AS update_trigger,
                       t3.name AS delete_trigger
                FROM   SOFTECHDB9.dbo.sysobjects o
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t1 ON t1.id = o.instrig
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t2 ON t2.id = o.updtrig
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t3 ON t3.id = o.deltrig
                WHERE  o.name = 'britems'
            """)
            rows = cur.fetchall()
            for r in rows:
                out('  ' + ' | '.join(str(c) for c in r))
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── NOW MAKE A WRITE AND CHECK britems/r3britems IMMEDIATELY ──────────
        section('WRITE TEST: Check britems/r3britems before and after UPDATE items')

        # Get counts before
        counts_before = {}
        for tbl in ['britems', 'r3britems']:
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT COUNT(*) FROM SOFTECHDB9.dbo.{tbl}')
                counts_before[tbl] = int(cur.fetchone()[0] or 0)
                cur.close()
            except Exception:
                counts_before[tbl] = -1
        out(f'  BEFORE: britems={counts_before.get("britems")} r3britems={counts_before.get("r3britems")}')

        # Make write
        try:
            cur = conn.cursor()
            cur.execute('SELECT posdiscp FROM SOFTECHDB9.dbo.items WHERE itemcode = ?', ['127397'])
            r = cur.fetchone()
            cur.close()
            orig = float(r[0] or 0)
            test = orig + 1
            cur = conn.cursor()
            cur.execute('UPDATE SOFTECHDB9.dbo.items SET posdiscp = ?, usercode = ? WHERE itemcode = ?',
                        [test, '00099', '127397'])
            conn.close()
            out(f'  Wrote: posdiscp {orig} -> {test}')
        except Exception as e:
            out(f'  Write ERROR: {e}')
            orig = None; test = None
            conn.close()

        import time; time.sleep(1)
        conn = get_sybase_connection()

        # Check counts AFTER
        for tbl in ['britems', 'r3britems']:
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT COUNT(*) FROM SOFTECHDB9.dbo.{tbl}')
                after = int(cur.fetchone()[0] or 0)
                cur.close()
                diff = after - counts_before.get(tbl, 0)
                out(f'  AFTER  {tbl}: {after} (diff={diff:+d})')
            except Exception as e:
                out(f'  {tbl}: ERROR {e}')

        # Show any rows for itemcode=127397 in britems / r3britems
        for tbl in ['britems', 'r3britems']:
            out(f'\n  Rows for itemcode=127397 in {tbl}:')
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT * FROM SOFTECHDB9.dbo.{tbl} WHERE itemcode = ?', ['127397'])
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        out('    ' + ' | '.join(str(c) for c in r))
                else:
                    out('    (none)')
                cur.close()
            except Exception as e:
                out(f'    ERROR: {e}')

        # Show ALL recent rows
        for tbl in ['britems', 'r3britems']:
            out(f'\n  ALL recent rows in {tbl}:')
            try:
                cur = conn.cursor()
                cur.execute('SET ROWCOUNT 10')
                cur.execute(f'SELECT * FROM SOFTECHDB9.dbo.{tbl} ORDER BY 1 DESC')
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        out('    ' + ' | '.join(str(c) for c in r))
                else:
                    out('    (empty)')
                cur.execute('SET ROWCOUNT 0')
                cur.close()
            except Exception as e:
                out(f'    ERROR: {e}')

        # ── BRANCH SIDE: check r3britems / britems on branches ────────────────
        section('BRANCH SIDE: Counterpart tables on branch servers')
        branches = Branch.objects.filter(
            is_operational=True, db_host__isnull=False
        ).exclude(softech_branch_id='100').exclude(db_host='')

        for b in list(branches)[:2]:  # Check first 2 branches
            out(f'\n  Branch {b.softech_branch_id} ({b.db_host}):')
            try:
                bc = get_branch_connection(b.db_host, b.db_port or 5000)
                cur = bc.cursor()
                # Check what tables exist
                cur.execute("""
                    SELECT o.name
                    FROM sysobjects o
                    WHERE o.type = 'U'
                      AND (LOWER(o.name) LIKE '%britem%'
                           OR LOWER(o.name) LIKE '%r3brit%'
                           OR LOWER(o.name) LIKE '%britems%')
                    ORDER BY o.name
                """)
                tbls = cur.fetchall()
                out(f'    Tables (britems-like): ' + str([r[0] for r in tbls]))

                # Check triggers on items at this branch
                cur.execute("""
                    SELECT o.name AS table_name,
                           t2.name AS update_trigger
                    FROM   sysobjects o
                    LEFT JOIN sysobjects t2 ON t2.id = o.updtrig
                    WHERE  o.name = 'items'
                """)
                rows = cur.fetchall()
                out(f'    items UPDATE trigger: ' + str([(r[0], r[1]) for r in rows]))

                # Current posdiscp on branch
                cur.execute('SELECT posdiscp, usercode FROM items WHERE itemcode = ?', ['127397'])
                r = cur.fetchone()
                if r:
                    out(f'    items.posdiscp={"%.1f" % float(r[0] or 0)} user={r[1]}')

                # Check r3britems equivalent
                for tbl in ['britems', 'r3britems']:
                    try:
                        cur.execute(f'SELECT COUNT(*) FROM {tbl}')
                        cnt = cur.fetchone()[0]
                        out(f'    {tbl}: {cnt} rows')
                        if cnt and int(cnt) > 0:
                            cur.execute('SET ROWCOUNT 3')
                            cur.execute(f'SELECT * FROM {tbl} ORDER BY 1 DESC')
                            for rr in cur.fetchall():
                                out('      ' + ' | '.join(str(c) for c in rr))
                            cur.execute('SET ROWCOUNT 0')
                    except Exception as e:
                        out(f'    {tbl}: {str(e)[:50]}')

                bc.close()
            except Exception as e:
                out(f'    ERROR: {str(e)[:80]}')

        # ── REVERT ────────────────────────────────────────────────────────────
        if orig is not None:
            try:
                cur = conn.cursor()
                cur.execute('UPDATE SOFTECHDB9.dbo.items SET posdiscp = ? WHERE itemcode = ?',
                            [orig, '127397'])
                conn.close()
                out(f'\n  Reverted posdiscp to {orig}')
            except Exception as e:
                out(f'\n  Revert ERROR: {e}')
        else:
            conn.close()

        out(f'\nComplete: {datetime.datetime.now().isoformat()}')
