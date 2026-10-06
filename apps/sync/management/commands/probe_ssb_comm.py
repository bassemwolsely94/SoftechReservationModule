"""
python manage.py probe_ssb_comm

Read-only inspection of the SOFTECH SSB9 replication engine:
  - D:\SSB9 top-level (exes, configs, logs)
  - COMM\dumpout + dumpin (archive timestamps reveal the ~30-min cycle)
  - Config + log files that reveal how ssbsb9_replicate.exe is invoked
NO execution of any replication binary.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Inspect SSB9 replication engine layout (read-only)'

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
                cur.execute(f"xp_cmdshell '{command}'")
                for r in cur.fetchall():
                    if r and r[0] is not None:
                        out('    ' + str(r[0]))
                cur.close()
            except Exception as e:
                out(f'    ERROR: {str(e)[:120]}')

        conn = get_sybase_connection()

        sec('D:\\SSB9 top level')
        xp(conn, 'dir D:\\SSB9')

        sec('COMM folder structure')
        xp(conn, 'dir D:\\SSB9\\SofTech\\COMM')

        sec('dumpout (HQ -> branches outbound archives, newest first)')
        xp(conn, 'dir D:\\SSB9\\SofTech\\COMM\\dumpout /o-d')

        sec('dumpin (inbound archives)')
        xp(conn, 'dir D:\\SSB9\\SofTech\\COMM\\dumpin /o-d')

        sec('Config folder')
        xp(conn, 'dir D:\\SSB9\\Config')
        xp(conn, 'dir D:\\SSB9\\SofTech\\Config')

        sec('Look for ini / config / log files in D:\\SSB9')
        xp(conn, 'dir D:\\SSB9\\*.ini /s /b')
        xp(conn, 'dir D:\\SSB9\\*.config /s /b')
        xp(conn, 'dir D:\\SSB9\\*.log /s /b')
        xp(conn, 'dir D:\\SSB9\\*.xml /s /b')

        sec('Replicate exe — version / help (safe, no-op flags)')
        # Many such tools print usage with /? — but to be safe we only stat the file
        xp(conn, 'dir D:\\SSB9\\ssbsb9_replicate.exe')

        conn.close()
        out('\nDONE.')
