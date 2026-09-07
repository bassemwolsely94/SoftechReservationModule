"""
python manage.py probe_softech_task

Pull full definitions of the 'SofTech Start' and 'SSB8' scheduled tasks on HQ
(the likely ~30-min replication driver), and locate the SofTech program dir.
READ ONLY.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Get SofTech scheduled task details from HQ via xp_cmdshell'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection

        def out(t=''):
            self.stdout.write(str(t).encode('ascii', 'replace').decode('ascii'))

        def sec(t):
            out(''); out('=' * 70); out('  ' + t); out('=' * 70)

        def xp(conn, command):
            out(f'\n  $ {command}')
            try:
                cur = conn.cursor()
                cur.execute("xp_cmdshell ?", [command])
                rows = cur.fetchall()
                for r in rows:
                    if r and r[0] is not None:
                        out('    ' + str(r[0]))
                cur.close()
            except Exception as e:
                # Fallback: inline (no param)
                try:
                    cur = conn.cursor()
                    cur.execute(f"xp_cmdshell '{command}'")
                    for r in cur.fetchall():
                        if r and r[0] is not None:
                            out('    ' + str(r[0]))
                    cur.close()
                except Exception as e2:
                    out(f'    ERROR: {str(e2)[:120]}')

        conn = get_sybase_connection()

        sec("Full detail: 'SofTech Start' task")
        xp(conn, 'schtasks /query /tn "SofTech Start" /v /fo LIST')

        sec("Full detail: 'SSB8' task")
        xp(conn, 'schtasks /query /tn "SSB8" /v /fo LIST')

        sec('Locate SofTech program directory (single-backslash paths)')
        xp(conn, 'if exist C:\\Softech (echo FOUND C:\\Softech) else (echo no C:\\Softech)')
        xp(conn, 'dir C:\\Softech')
        xp(conn, 'dir D:\\Softech')
        xp(conn, 'dir C:\\SSB8')
        xp(conn, 'dir D:\\SSB8')

        sec('Search C: and D: for SofTech/SSB executables')
        xp(conn, 'dir C:\\*.exe /s /b | findstr /i "ssb softech branch"')
        xp(conn, 'dir D:\\*.exe /s /b | findstr /i "ssb softech branch"')

        conn.close()
        out('\nDONE.')
