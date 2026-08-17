"""
python manage.py capture_save_sql [--seconds 90] [--profile prod] [--enable-monitoring]

READ-ONLY (unless --enable-monitoring): capture the exact SQL the native SofTech
client sends when you click **Save** on a purchase — to learn what the final
stktransm/stktrans insert really needs (a stored proc? session temp-table setup?)
now that a direct insert is rejected by tr_stktrans (err 2732).

Uses ASE MDA monitoring tables (master..monSysSQLText — the SQL-text pipe — plus
monProcessSQLText). Flow:
  1. PREFLIGHT: print the monitoring config + candidate client SPIDs (from
     master..sysprocesses: hostname / program_name / login).
  2. If monitoring is OFF: print the exact sp_configure commands to enable it and
     stop (enabling is a server config write — pass --enable-monitoring to let this
     command turn it on, and it will offer to restore the prior values afterwards).
  3. CAPTURE: poll monSysSQLText for --seconds, accumulate every batch (per SPID),
     while you do ONE Save. Everything is saved verbatim.

Output -> docs/architecture/softech_save_sql_capture.txt

⚠️ Enabling monitoring (--enable-monitoring) writes server-wide sp_configure values
(dynamic, reversible). Reading the tables is harmless. No SOFTECH business data is
ever modified.
"""
import os
import time
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..',
                           'docs', 'architecture', 'softech_save_sql_capture.txt')

# sp_configure knobs that must be > 0 for monSysSQLText to capture text.
_MON_CONFIGS = [
    'enable monitoring',
    'sql text pipe active',
    'sql text pipe max messages',
    'max SQL text monitored',
]


class Command(BaseCommand):
    help = 'Capture the native client Save-time SQL via ASE MDA monitoring (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--seconds', type=int, default=90, help='capture window (default 90)')
        parser.add_argument('--profile', default='prod')
        parser.add_argument('--enable-monitoring', action='store_true',
                            help='turn monitoring ON for the capture (server config write; restored after)')
        parser.add_argument('--spid', type=int, default=0, help='capture ONLY this SPID (e.g. 42 = the client)')
        parser.add_argument('--poll', type=float, default=0.3, help='poll interval seconds')

    def handle(self, *args, **o):
        from config.sybase import SoftechConnector
        lines = []

        def log(t=''):
            self.stdout.write(t); lines.append(t)

        def section(t):
            log(''); log('=' * 78); log(f'  {t}'); log('=' * 78)

        log(f'Save-SQL capture: {datetime.datetime.now().isoformat()} (profile={o["profile"]})')
        conn = SoftechConnector(profile=o['profile']).connect()

        def q(sql, params=None):
            cur = conn._cursor(); cur.execute(sql, params or [])
            cols = [d[0] for d in cur.description] if cur.description else []
            return cols, cur.fetchall()

        def q_safe(label, sql, params=None):
            log(f'\n--- {label} ---')
            try:
                cols, rows = q(sql, params)
                if not rows:
                    log('  (no rows)'); return [], []
                log('  ' + ' | '.join(cols))
                for r in rows:
                    log('  ' + ' | '.join('NULL' if c is None else str(c) for c in r))
                return cols, rows
            except Exception as e:
                log(f'  [ERROR] {e}'); return [], []

        my_spid = None
        try:
            _, r = q('SELECT @@spid')
            my_spid = int(r[0][0])
            log(f'my SPID (excluded from capture) = {my_spid}')
        except Exception as e:
            log(f'could not read @@spid: {e}')

        # ── 1. PREFLIGHT — monitoring config (read from syscurconfigs; sp_configure's
        #      result set isn't surfaced through jConnect on this ASE) ───────────
        section('1: monitoring config (master..syscurconfigs run values)')
        mon_on = {}
        try:
            names_in = ', '.join(f"'{n}'" for n in _MON_CONFIGS)
            _, rows = q(f"""
                SELECT c.name, r.value
                FROM master..syscurconfigs r, master..sysconfigures c
                WHERE r.config = c.config AND c.name IN ({names_in})""")
            for r in rows:
                mon_on[str(r[0]).strip()] = r[1]
                log(f'  {str(r[0]).strip():<30} run_value={r[1]}')
        except Exception as e:
            log(f'  [ERROR reading syscurconfigs] {e}')

        def _num(v):
            try:
                return int(str(v).strip())
            except Exception:
                return 0

        # monSysSQLText (the pipe we read) needs enable monitoring + sql text pipe active.
        # 'max SQL text monitored' only governs monProcessSQLText (unused here), so it is
        # NOT required — and it's static, so requiring it would wrongly block us.
        monitoring_ready = _num(mon_on.get('enable monitoring')) > 0 and \
            _num(mon_on.get('sql text pipe active')) > 0
        log(f'  → monitoring_ready = {monitoring_ready}')

        # ── 2. candidate client SPIDs ──────────────────────────────────────────
        section('2: candidate client connections (master..sysprocesses)')
        q_safe('active user connections', """
            SELECT p.spid, p.hostname, p.program_name, p.hostprocess, p.cmd, l.name
            FROM master..sysprocesses p
            LEFT JOIN master..syslogins l ON p.suid = l.suid
            WHERE p.hostname IS NOT NULL AND p.hostname != ''
              AND p.program_name NOT LIKE 'Adaptive%'
            ORDER BY p.spid""")

        # ── optionally enable monitoring for the capture ───────────────────────
        prior = {}
        if not monitoring_ready and o['enable_monitoring']:
            section('2b: enabling monitoring (temporary server config write)')
            for name, want in (('enable monitoring', 1), ('sql text pipe active', 1),
                               ('sql text pipe max messages', 20000), ('max SQL text monitored', 16384)):
                prior[name] = mon_on.get(name)
                try:
                    q(f"EXEC sp_configure '{name}', {want}")
                    log(f'  set {name} = {want} (was {prior[name]})')
                except Exception as e:
                    log(f'  [ERROR enabling {name}] {e}')
            monitoring_ready = True

        if not monitoring_ready:
            section('MONITORING IS OFF — cannot capture SQL text')
            log('Run these on the SOFTECH server (sa), then re-run this command; OR re-run with')
            log('--enable-monitoring to let this command toggle them for the capture window:')
            log("  sp_configure 'enable monitoring', 1")
            log("  sp_configure 'max SQL text monitored', 4096")
            log("  sp_configure 'sql text pipe active', 1")
            log("  sp_configure 'sql text pipe max messages', 2000")
            conn.close(); self._save(lines); return

        # ── 3. CAPTURE window (restore ALWAYS runs, even on error) ─────────────
        batches = {}
        spid_host = {}
        try:
            section(f'3: CAPTURING for {o["seconds"]}s — go click SAVE on ONE purchase now')
            self.stdout.write(self.style.WARNING(
                f'  >>> Do ONE Save in SofTech within the next {o["seconds"]} seconds <<<'))
            target = o['spid'] or None
            text_sql = self._pick_text_query(q, log, target)
            filt = [target] if target else [my_spid or -1]
            end = time.time() + o['seconds']
            polls = 0
            while time.time() < end:
                polls += 1
                try:
                    cols, rows = q(text_sql, filt)
                    idx = {c.lower(): i for i, c in enumerate(cols)}
                    for r in rows:
                        spid = r[idx.get('spid', 0)]
                        batchid = r[idx.get('batchid', 1)] if 'batchid' in idx else 0
                        seq = r[idx.get('sequenceinbatch', 2)] if 'sequenceinbatch' in idx else 0
                        txt = r[idx.get('sqltext', len(cols) - 1)]
                        key = (int(spid), int(batchid or 0))
                        batches.setdefault(key, {})[int(seq or 0)] = txt
                except Exception as e:
                    if polls == 1:
                        log(f'  [capture query error] {e}')
                time.sleep(o['poll'])
            log(f'  polled {polls} times; captured {len(batches)} batch(es)')

            try:
                _, rows = q("SELECT p.spid, p.hostname, p.program_name, l.name FROM master..sysprocesses p "
                            "LEFT JOIN master..syslogins l ON p.suid = l.suid")
                for r in rows:
                    spid_host[int(r[0])] = f'{r[1]} / {r[2]} / {r[3]}'
            except Exception:
                pass
        finally:
            # ── 4. ALWAYS restore config we changed ────────────────────────────
            if prior:
                section('4: restoring monitoring config')
                for name, val in prior.items():
                    if val is None:
                        continue
                    try:
                        q(f"EXEC sp_configure '{name}', {_num(val)}")
                        log(f'  restored {name} = {val}')
                    except Exception as e:
                        log(f'  [ERROR restoring {name}] {e}')

        # ── 5. dump captured batches ───────────────────────────────────────────
        section('5: CAPTURED SQL (per batch, in order)')
        # sort by spid then batchid
        for (spid, batchid) in sorted(batches.keys()):
            seqs = batches[(spid, batchid)]
            full = ''.join(seqs[k] for k in sorted(seqs) if seqs[k])
            if not full or not full.strip():
                continue
            host = spid_host.get(spid, '?')
            log(f'\n----- SPID {spid} batch {batchid}  [{host}] -----')
            log(full.strip())

        conn.close()
        log(f'\nComplete: {datetime.datetime.now().isoformat()}')
        self._save(lines)

    def _pick_text_query(self, q, log, target=None):
        """Return the best available SQL-text query (monSysSQLText preferred,
        monProcessSQLText fallback). When `target` is set we filter to that SPID
        (=, cleaner); otherwise we exclude our own SPID (!=)."""
        op = '=' if target else '!='
        candidates = [
            f"SELECT SPID, BatchID, SequenceInBatch, SQLText FROM master..monSysSQLText WHERE SPID {op} ?",
            f"SELECT SPID, SequenceInBatch, SQLText FROM master..monSysSQLText WHERE SPID {op} ?",
            f"SELECT SPID, LineNumber, SQLText FROM master..monProcessSQLText WHERE SPID {op} ?",
            f"SELECT * FROM master..monSysSQLText WHERE SPID {op} ?",
        ]
        for sql in candidates:
            try:
                q(sql, [-1])   # smoke test
                log(f'  using text source: {sql.split("FROM")[1].strip().split()[0]}')
                return sql
            except Exception:
                continue
        log('  [WARN] no monSysSQLText/monProcessSQLText available — capture may be empty')
        return candidates[0]

    def _save(self, lines):
        path = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        self.stdout.write(self.style.SUCCESS(f'\nSaved -> {path}'))
