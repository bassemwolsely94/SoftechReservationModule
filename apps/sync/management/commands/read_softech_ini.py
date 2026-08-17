"""
python manage.py read_softech_ini
Read D:\\SSB9\\SofTech\\SOFTECH9.INI via xp_cmdshell (HQ).
Credential-bearing lines are redacted before printing.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Read SOFTECH9.INI replication config (redacted)'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection

        SECRET_HINTS = ('pass', 'pwd', 'key', 'secret', 'token', 'connectionstring', 'conn')

        def out(t=''):
            self.stdout.write(str(t).encode('ascii', 'replace').decode('ascii'))

        conn = get_sybase_connection()
        out('=== SOFTECH9.INI (redacted) ===')
        try:
            cur = conn.cursor()
            cur.execute("xp_cmdshell 'type \"D:\\SSB9\\SofTech\\SOFTECH9.INI\"'")
            for r in cur.fetchall():
                if not r or r[0] is None:
                    continue
                line = str(r[0])
                low = line.lower()
                if any(h in low for h in SECRET_HINTS) and '=' in line:
                    key = line.split('=', 1)[0]
                    out(f'{key}=<redacted>')
                else:
                    out(line)
            cur.close()
        except Exception as e:
            out(f'ERROR: {str(e)[:120]}')
        conn.close()
        out('\nDONE.')
