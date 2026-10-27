"""
python manage.py capture_dbcc_sqltext --spid 42 [--seconds 90] [--profile prod]

Capture the SQL batch(es) a SofTech client runs on Save — WITHOUT the MDA mon*
tables (which aren't installed on this ASE 12.5). Uses the classic
`dbcc traceon(3604)` + `dbcc sqltext(<spid>)`, which prints the target SPID's
current/last SQL batch to this connection's MESSAGE stream. We poll it fast and
accumulate the distinct batches seen while you do ONE Save.

Needs sa_role/sso_role (SYBASE_USER). READ-ONLY: dbcc sqltext only reads; no config
or data is changed.

Output -> docs/architecture/softech_save_dbcc_capture.txt
"""
import os
import time
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..',
                           'docs', 'architecture', 'softech_save_dbcc_capture.txt')

_BOILER = ('dbcc execution completed', 'if dbcc printed error')


class Command(BaseCommand):
    help = 'Capture a client SPID Save-time SQL via dbcc sqltext (no MDA needed).'

    def add_arguments(self, parser):
        parser.add_argument('--spid', type=int, default=0,
                            help='specific SPID to watch; 0 = ALL active SofTech clients (robust)')
        parser.add_argument('--seconds', type=int, default=120)
        parser.add_argument('--profile', default='prod')
        parser.add_argument('--poll', type=float, default=0.1)

    def handle(self, *args, **o):
        from config.sybase import SoftechConnector
        lines = []

        def log(t=''):
            self.stdout.write(t); lines.append(t)

        spid = o['spid']
        log(f'dbcc sqltext capture: {datetime.datetime.now().isoformat()} spid={spid} profile={o["profile"]}')

        conn = SoftechConnector(profile=o['profile']).connect()
        jconn = conn._conn._conn   # SoftechConnector → ConnectionWrapper → java.sql.Connection
        st = jconn.createStatement()

        def run_msgs(sql):
            """Execute a statement and return its message-stream text (SQLWarning chain)."""
            st.clearWarnings()
            try:
                st.execute(sql)
            except Exception as e:
                return f'[exec error] {e}'
            parts = []
            w = st.getWarnings()
            while w is not None:
                try:
                    parts.append(str(w.getMessage()))
                except Exception:
                    pass
                w = w.getNextWarning()
            st.clearWarnings()
            return '\n'.join(parts)

        my_spid = None
        try:
            _, r = None, None
            cur = conn._cursor(); cur.execute('SELECT @@spid')
            my_spid = int(cur.fetchone()[0])
        except Exception:
            pass

        def active_spids():
            """ALL SofTech client SPIDs (any state) except our own — identified by the
            LOGIN 'SofTech9' (program_name holds the employee display name, not the app).
            dbcc sqltext shows each one's LAST batch even when idle, so we catch a fast
            Save on whatever persistent connection ran it, regardless of timing."""
            try:
                cur = conn._cursor()
                cur.execute("SELECT p.spid FROM master..sysprocesses p "
                            "JOIN master..syslogins l ON p.suid = l.suid "
                            "WHERE l.name = 'SofTech9' AND p.spid != ?", [my_spid or -1])
                return [int(x[0]) for x in cur.fetchall()]
            except Exception:
                return []

        # route dbcc output to this connection's message stream
        run_msgs('dbcc traceon(3604)')

        watch = f'spid {spid}' if spid else 'ALL active SofTech clients'
        log(f'\n>>> Do ONE Save in SofTech now — recording {watch} for {o["seconds"]}s <<<\n')
        seen = []          # ordered distinct (spid, batch text)
        seen_set = set()
        end = time.time() + o['seconds']
        polls = 0
        while time.time() < end:
            polls += 1
            targets = [spid] if spid else active_spids()
            for sp in targets:
                txt = run_msgs(f'dbcc sqltext({sp})')
                clean = '\n'.join(l for l in txt.splitlines()
                                  if l.strip() and not any(b in l.lower() for b in _BOILER))
                # ignore the idle heartbeat + empty
                if not clean or 'sp_serverdate' in clean.lower():
                    continue
                if clean not in seen_set:
                    seen_set.add(clean)
                    seen.append(f'[spid {sp}] {clean}')
                    log(f'[poll {polls} @ {time.strftime("%H:%M:%S")} spid {sp}] NEW:\n{clean}\n{"-"*60}')
            time.sleep(o['poll'])

        run_msgs('dbcc traceoff(3604)')
        try:
            st.close()
        except Exception:
            pass
        conn.close()

        log(f'\n=== SUMMARY: {len(seen)} distinct batch(es) captured over {polls} polls ===')
        for i, b in enumerate(seen, 1):
            log(f'\n----- batch {i} -----\n{b}')
        log(f'\nComplete: {datetime.datetime.now().isoformat()}')
        path = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        self.stdout.write(self.style.SUCCESS(f'\nSaved -> {path}'))
