"""
python manage.py find_replication_job

Hunt for the ~30-min scheduled job that propagates HQ britems -> branch items.

Because the job likely uses dynamic SQL or remote-server (CIS) calls, it won't
appear in sysdepends. So we scan:
  1. sysservers (remote server topology) on HQ + branch
  2. FULL syscomments text scan for 'britems' / 'r3britems' (HQ + branch)
  3. Procedures whose name suggests sync/post/price/send/transfer
  4. Full text of every candidate procedure
  5. ASE job-scheduler artifacts
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Find the britems -> branch replication job'

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='160', help='Branch code to probe')

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection, get_branch_connection
        from apps.branches.models import Branch

        branch_code = options['branch']

        def out(t=''):
            self.stdout.write(str(t).encode('ascii', 'replace').decode('ascii'))

        def sec(t):
            out(''); out('=' * 70); out('  ' + t); out('=' * 70)

        def scan(conn, label, where_db=''):
            """Run a full investigation pass on one server connection."""
            prefix = (where_db + '.dbo.') if where_db else 'dbo.'

            # ── sysservers ────────────────────────────────────────────────────
            out(f'\n--- {label}: sysservers (remote server topology) ---')
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT srvid, srvname, srvnetname, srvstatus FROM {prefix}sysservers ORDER BY srvid")
                for r in cur.fetchall():
                    out(f'  srvid={r[0]} name={r[1]} netname={r[2]} status={r[3]}')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {str(e)[:80]}')

            # ── procs referencing britems / r3britems (full text scan) ────────
            out(f'\n--- {label}: procedures referencing britems/r3britems in TEXT ---')
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT DISTINCT o.name, o.type
                    FROM {prefix}syscomments sc
                    JOIN {prefix}sysobjects o ON sc.id = o.id
                    WHERE o.type IN ('P','TR','V')
                      AND (LOWER(sc.text) LIKE '%britems%' OR LOWER(sc.text) LIKE '%r3britems%')
                    ORDER BY o.type, o.name
                """)
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        out(f'  {r[1]}: {r[0]}')
                else:
                    out('  (none found in readable text)')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {str(e)[:80]}')

            # ── procs referencing remote item sync patterns ───────────────────
            out(f'\n--- {label}: procedures referencing items + a server/dynamic pattern ---')
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT DISTINCT o.name
                    FROM {prefix}syscomments sc
                    JOIN {prefix}sysobjects o ON sc.id = o.id
                    WHERE o.type = 'P'
                      AND LOWER(sc.text) LIKE '%items%'
                      AND (
                          LOWER(sc.text) LIKE '%.dbo.items%'
                          OR LOWER(sc.text) LIKE '%exec(%'
                          OR LOWER(sc.text) LIKE '%execute(%'
                          OR LOWER(sc.text) LIKE '%srvname%'
                          OR LOWER(sc.text) LIKE '%remote%'
                      )
                    ORDER BY o.name
                """)
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        out(f'  {r[0]}')
                else:
                    out('  (none)')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {str(e)[:80]}')

            # ── procs by suggestive name ──────────────────────────────────────
            out(f'\n--- {label}: procedures by suggestive name ---')
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT o.name, o.crdate
                    FROM {prefix}sysobjects o
                    WHERE o.type = 'P'
                      AND (
                          LOWER(o.name) LIKE '%sync%'
                          OR LOWER(o.name) LIKE '%post%'
                          OR LOWER(o.name) LIKE '%send%'
                          OR LOWER(o.name) LIKE '%price%'
                          OR LOWER(o.name) LIKE '%tarhe%'
                          OR LOWER(o.name) LIKE '%tarhil%'
                          OR LOWER(o.name) LIKE '%branch%'
                          OR LOWER(o.name) LIKE '%br_%'
                          OR LOWER(o.name) LIKE '%_br%'
                          OR LOWER(o.name) LIKE '%dist%'
                          OR LOWER(o.name) LIKE '%repl%'
                          OR LOWER(o.name) LIKE '%fusion%'
                          OR LOWER(o.name) LIKE '%nepton%'
                          OR LOWER(o.name) LIKE '%update%item%'
                          OR LOWER(o.name) LIKE '%item%update%'
                      )
                    ORDER BY o.name
                """)
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        out(f'  {r[0]}  (crdate={str(r[1])[:10]})')
                else:
                    out('  (none)')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {str(e)[:80]}')

        # ── HQ scan ───────────────────────────────────────────────────────────
        sec('HQ (SOFTECHDB9)')
        conn = get_sybase_connection()
        scan(conn, 'HQ', 'SOFTECHDB9')
        conn.close()

        # ── Branch scan ───────────────────────────────────────────────────────
        b = Branch.objects.get(softech_branch_id=branch_code)
        sec(f'BRANCH {branch_code} ({b.db_host})')
        try:
            bconn = get_branch_connection(b.db_host, b.db_port or 5000)
            scan(bconn, f'BR{branch_code}', '')   # branch default db
            bconn.close()
        except Exception as e:
            out(f'  Branch connect ERROR: {str(e)[:80]}')

        # ── Dump full text of HQ candidate procs referencing britems ──────────
        sec('FULL TEXT: HQ procs referencing britems')
        conn = get_sybase_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT o.name
                FROM SOFTECHDB9.dbo.syscomments sc
                JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id = o.id
                WHERE o.type = 'P'
                  AND (LOWER(sc.text) LIKE '%britems%' OR LOWER(sc.text) LIKE '%r3britems%')
                ORDER BY o.name
            """)
            names = [r[0] for r in cur.fetchall()]
            cur.close()
            for name in names:
                out(f'\n----- PROC: {name} -----')
                cur = conn.cursor()
                cur.execute("""
                    SELECT sc.colid, sc.text
                    FROM SOFTECHDB9.dbo.syscomments sc
                    JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id = o.id
                    WHERE o.name = ? AND o.type = 'P'
                    ORDER BY sc.colid
                """, [name])
                full = ''.join(str(r[1]) for r in cur.fetchall())
                out(full.encode('ascii', 'replace').decode('ascii'))
                cur.close()
        except Exception as e:
            out(f'  ERROR: {str(e)[:80]}')
        conn.close()

        out('\nDONE.')
