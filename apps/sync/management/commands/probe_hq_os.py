"""
python manage.py probe_hq_os

Use Sybase xp_cmdshell (if enabled) to inspect the HQ SERVER's OS — READ ONLY —
to locate the external replication agent driving the ~30-min HQ->branch sync.

Runs only non-destructive commands: dir, schtasks /query, sc query, tasklist.
Does NOT execute any replication binary.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Inspect HQ server OS via xp_cmdshell (read-only) to find the replication agent'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection

        def out(t=''):
            self.stdout.write(str(t).encode('ascii', 'replace').decode('ascii'))

        def sec(t):
            out(''); out('=' * 70); out('  ' + t); out('=' * 70)

        def xp(conn, label, command):
            out(f'\n--- {label} ---')
            out(f'  $ {command}')
            try:
                cur = conn.cursor()
                cur.execute(f"xp_cmdshell '{command}'")
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        line = r[0] if r and r[0] is not None else ''
                        out('    ' + str(line))
                else:
                    out('    (no output)')
                cur.close()
            except Exception as e:
                out(f'    ERROR: {str(e)[:120]}')

        conn = get_sybase_connection()

        # ── Is xp_cmdshell available? harmless test ──────────────────────────
        sec('xp_cmdshell availability test')
        xp(conn, 'whoami / hostname', 'hostname')

        # ── Scheduled tasks on HQ (the 30-min job is most likely here) ───────
        sec('HQ scheduled tasks (filtered)')
        xp(conn, 'schtasks list', 'schtasks /query /fo LIST')

        # ── Windows services on HQ ────────────────────────────────────────────
        sec('HQ services (running)')
        xp(conn, 'sc query state=all (running filter via findstr)',
           'sc query state= all')

        # ── Look for SOFTECH program directory ───────────────────────────────
        sec('HQ SOFTECH install directory')
        for path in [r'C:\\Softech', r'C:\\SOFTECH', r'C:\\Program Files\\Softech',
                     r'C:\\Program Files (x86)\\Softech', r'D:\\Softech',
                     r'C:\\Sybase']:
            xp(conn, f'dir {path}', f'dir "{path}"')

        # ── Search for replication-like executables on C: and D: ─────────────
        sec('Search for replication/sync executables')
        xp(conn, 'where /R C: repl exe (top)',
           'dir C:\\ /s /b ^| findstr /i "replic" 2>nul')
        xp(conn, 'search common names',
           'dir C:\\ /s /b 2^>nul ^| findstr /i "branch sync replic transfer post price"')

        conn.close()
        out('\nDONE.')
