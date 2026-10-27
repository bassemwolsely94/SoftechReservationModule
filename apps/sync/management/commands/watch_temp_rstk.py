"""
python manage.py watch_temp_rstk [--branch 100] [--doccode 10] [--seconds 600] [--poll 0.3]

Poll temp_r_stk (the on-screen "Temporarily Save" draft store) for changes to the
docnumber=0 draft row, capturing each DISTINCT doctext blob with a timestamp — so a
series of controlled temp-saves can be diffed to decode the encoding. Watches the
target (branch,doccode,0) row AND any other docnumber=0 row (in case the key differs).
Read-only. Writes each change immediately to the output file (readable live).

Output -> docs/architecture/temp_rstk_watch.txt
"""
import os
import time
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..',
                           'docs', 'architecture', 'temp_rstk_watch.txt')


class Command(BaseCommand):
    help = 'Watch temp_r_stk docnumber=0 draft blob for changes (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('--branch', default='100')
        parser.add_argument('--doccode', default='10')
        parser.add_argument('--seconds', type=int, default=600)
        parser.add_argument('--poll', type=float, default=0.3)

    def handle(self, *args, **o):
        from django.conf import settings
        from config.sybase import get_branch_connection

        bc, dc = str(o['branch']), str(o['doccode'])
        path = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = open(path, 'w', encoding='utf-8')

        def log(t=''):
            self.stdout.write(t)
            fh.write(t + '\n')
            fh.flush()

        log(f'temp_r_stk watcher: branch={bc} doccode={dc} '
            f'window={o["seconds"]}s  started {datetime.datetime.now().isoformat()}')
        log('>>> Do the controlled temp-saves now; each distinct draft blob is logged below.\n')

        conn = get_branch_connection(settings.SYBASE_HOST, 5000, 'SOFTECHDB9', charset='cp1256')

        def rows_now():
            """Return {(branchcode,doccode,docnumber): (docdate, datalen, blob)} for
            docnumber=0 rows on the target branch (any doccode)."""
            out = {}
            cur = conn.cursor()
            try:
                cur.execute("SELECT branchcode, doccode, docnumber, docdate, datalength(doctext), doctext "
                            "FROM temp_r_stk WHERE docnumber=0 AND branchcode=?", [bc])
                for r in cur.fetchall():
                    key = (str(r[0]).strip(), str(r[1]).strip(), int(r[2]))
                    out[key] = (str(r[3]), int(r[4] or 0), str(r[5] or ''))
            finally:
                cur.close()
            return out

        seen = {}
        seq = 0
        end = time.time() + o['seconds']
        last_beat = 0
        # capture the baseline first (mark it, don't count as a change)
        try:
            for k, v in rows_now().items():
                seen[k] = v[2]
                log(f'[baseline] {k}  docdate={v[0]}  bytes={v[1]}\n  {v[2]}\n')
        except Exception as e:
            log(f'[baseline error] {e}')

        while time.time() < end:
            try:
                cur = rows_now()
                for k, v in cur.items():
                    if seen.get(k) != v[2]:
                        seq += 1
                        seen[k] = v[2]
                        ts = time.strftime('%H:%M:%S')
                        log(f'===== CHANGE #{seq} @ {ts}  key={k}  docdate={v[0]}  bytes={v[1]} =====')
                        log(f'{v[2]}\n')
            except Exception as e:
                if int(time.time()) - last_beat > 10:
                    log(f'[poll error] {e}')
            if int(time.time()) - last_beat >= 30:
                last_beat = int(time.time())
                log(f'-- alive, {int(end - time.time())}s left, {seq} change(s) so far --')
            time.sleep(o['poll'])

        log(f'\nDone: {seq} change(s) captured. {datetime.datetime.now().isoformat()}')
        try:
            conn.close()
        except Exception:
            pass
        fh.close()
        self.stdout.write(self.style.SUCCESS(f'Saved -> {path}'))
