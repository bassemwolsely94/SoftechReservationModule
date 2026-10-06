"""
python manage.py probe_lib_db

Investigate SOFTECHDB9LIB — the second database (dbid 5), likely home of the
replication control / queue mechanism that drives the ~30-min HQ->branch sync.

Also scans BOTH databases for any 'control', 'sync', 'last', 'queue' tables and
for procedures referencing items across databases or via dynamic SQL.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Investigate SOFTECHDB9LIB replication database'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection

        def out(t=''):
            self.stdout.write(str(t).encode('ascii', 'replace').decode('ascii'))

        def sec(t):
            out(''); out('=' * 70); out('  ' + t); out('=' * 70)

        conn = get_sybase_connection()

        # ── All tables in SOFTECHDB9LIB ───────────────────────────────────────
        sec('SOFTECHDB9LIB — all user tables')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT o.name, o.crdate
                FROM SOFTECHDB9LIB.dbo.sysobjects o
                WHERE o.type = 'U'
                ORDER BY o.name
            """)
            rows = cur.fetchall()
            out(f'  ({len(rows)} tables)')
            for r in rows:
                out(f'  {r[0]}  (crdate={str(r[1])[:10]})')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {str(e)[:90]}')

        # ── Tables related to items / britems / sync / control ────────────────
        sec('SOFTECHDB9LIB — item/sync/control/queue tables')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT o.name
                FROM SOFTECHDB9LIB.dbo.sysobjects o
                WHERE o.type = 'U'
                  AND (LOWER(o.name) LIKE '%item%' OR LOWER(o.name) LIKE '%brit%'
                       OR LOWER(o.name) LIKE '%sync%' OR LOWER(o.name) LIKE '%control%'
                       OR LOWER(o.name) LIKE '%last%' OR LOWER(o.name) LIKE '%queue%'
                       OR LOWER(o.name) LIKE '%repl%' OR LOWER(o.name) LIKE '%r3%'
                       OR LOWER(o.name) LIKE '%price%' OR LOWER(o.name) LIKE '%send%'
                       OR LOWER(o.name) LIKE '%branch%')
                ORDER BY o.name
            """)
            for r in cur.fetchall():
                out(f'  {r[0]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {str(e)[:90]}')

        # ── All procedures in SOFTECHDB9LIB ───────────────────────────────────
        sec('SOFTECHDB9LIB — all procedures')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT o.name, o.crdate
                FROM SOFTECHDB9LIB.dbo.sysobjects o
                WHERE o.type = 'P'
                ORDER BY o.name
            """)
            rows = cur.fetchall()
            out(f'  ({len(rows)} procs)')
            for r in rows:
                out(f'  {r[0]}  (crdate={str(r[1])[:10]})')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {str(e)[:90]}')

        # ── Procs/triggers in SOFTECHDB9LIB referencing items/britems ─────────
        sec('SOFTECHDB9LIB — objects referencing items/britems in text')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT o.name, o.type
                FROM SOFTECHDB9LIB.dbo.syscomments sc
                JOIN SOFTECHDB9LIB.dbo.sysobjects o ON sc.id = o.id
                WHERE LOWER(sc.text) LIKE '%britems%'
                   OR LOWER(sc.text) LIKE '%.dbo.items%'
                   OR LOWER(sc.text) LIKE '%posdiscp%'
                   OR LOWER(sc.text) LIKE '%pharmacydiscp%'
                ORDER BY o.type, o.name
            """)
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out(f'  {r[1]}: {r[0]}')
            else:
                out('  (none)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {str(e)[:90]}')

        # ── Does SOFTECHDB9LIB have its own items/britems table? sample ───────
        sec('SOFTECHDB9LIB — britems / items presence + sample')
        for tbl in ['britems', 'items', 'r3britems', 'br_items', 'items_send']:
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT COUNT(*) FROM SOFTECHDB9LIB.dbo.{tbl}')
                cnt = cur.fetchone()[0]
                out(f'  {tbl}: {cnt} rows')
                cur.close()
            except Exception as e:
                pass  # table doesn't exist

        # ── Cross-DB: any object in SOFTECHDB9 referencing SOFTECHDB9LIB ──────
        sec('SOFTECHDB9 objects referencing SOFTECHDB9LIB')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT o.name, o.type
                FROM SOFTECHDB9.dbo.syscomments sc
                JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id = o.id
                WHERE LOWER(sc.text) LIKE '%softechdb9lib%'
                ORDER BY o.type, o.name
            """)
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out(f'  {r[1]}: {r[0]}')
            else:
                out('  (none)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {str(e)[:90]}')

        # ── Look for a control/timestamp table tracking last replication ──────
        sec('Candidate control tables — schema + sample')
        # We will discover names above; here probe common SOFTECH control names
        for db in ['SOFTECHDB9', 'SOFTECHDB9LIB']:
            for tbl in ['replication_control', 'sync_control', 'lastsync',
                        'last_sync', 'syscontrol', 'controltable', 'br_control',
                        'branchsync', 'branch_sync', 'sendcontrol']:
                try:
                    cur = conn.cursor()
                    cur.execute(f'SELECT COUNT(*) FROM {db}.dbo.{tbl}')
                    cnt = cur.fetchone()[0]
                    out(f'  {db}.{tbl}: {cnt} rows')
                    cur.execute(f'SET ROWCOUNT 3')
                    cur.execute(f'SELECT * FROM {db}.dbo.{tbl}')
                    for r in cur.fetchall():
                        out('    ' + ' | '.join(str(c) for c in r))
                    cur.execute('SET ROWCOUNT 0')
                    cur.close()
                except Exception:
                    pass

        conn.close()
        out('\nDONE.')
