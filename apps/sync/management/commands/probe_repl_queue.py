"""
python manage.py probe_repl_queue

1. Remote-server topology (master.dbo.sysservers / sysremotelogins) on HQ + branch
2. RepAgent status (syslogshold) on HQ
3. Live test: change HQ items.itemsaleprice to a NEW value and observe whether
   the trigger populates r3britems / updates britems (the replication queue).
   Reverts afterward.
"""
import time
from django.core.management.base import BaseCommand

ITEM = '127397'


class Command(BaseCommand):
    help = 'Probe remote topology + replication queue behavior'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection, get_branch_connection
        from apps.branches.models import Branch

        def out(t=''):
            self.stdout.write(str(t).encode('ascii', 'replace').decode('ascii'))

        def sec(t):
            out(''); out('=' * 70); out('  ' + t); out('=' * 70)

        # ── 1. Remote topology on HQ ──────────────────────────────────────────
        sec('1. master.dbo.sysservers on HQ')
        conn = get_sybase_connection()
        for q, lbl in [
            ("SELECT srvid, srvname, srvnetname, srvstatus FROM master.dbo.sysservers ORDER BY srvid", "sysservers"),
            ("SELECT remoteserverid, remoteusername, suid FROM master.dbo.sysremotelogins", "sysremotelogins"),
        ]:
            out(f'\n  --- {lbl} ---')
            try:
                cur = conn.cursor(); cur.execute(q)
                rows = cur.fetchall(); cur.close()
                if rows:
                    for r in rows:
                        out('    ' + ' | '.join(str(c) for c in r))
                else:
                    out('    (none)')
            except Exception as e:
                out(f'    ERROR: {str(e)[:90]}')

        # ── 2. RepAgent / log markers on HQ ──────────────────────────────────
        sec('2. RepAgent status on HQ')
        for q, lbl in [
            ("SELECT name, dbid FROM master.dbo.sysdatabases WHERE name LIKE '%SOFTECH%'", "databases"),
            ("SELECT * FROM master.dbo.syslogshold WHERE name NOT LIKE '%dummy%'", "syslogshold (RepAgent secondary trunc point)"),
        ]:
            out(f'\n  --- {lbl} ---')
            try:
                cur = conn.cursor(); cur.execute(q)
                rows = cur.fetchall(); cur.close()
                if rows:
                    for r in rows:
                        out('    ' + ' | '.join(str(c) for c in r))
                else:
                    out('    (none)')
            except Exception as e:
                out(f'    ERROR: {str(e)[:90]}')

        # Is RepAgent configured on the DB?
        out('\n  --- sp_config_rep_agent SOFTECHDB9 ---')
        try:
            cur = conn.cursor()
            cur.execute("sp_config_rep_agent SOFTECHDB9")
            rows = cur.fetchall(); cur.close()
            if rows:
                for r in rows:
                    out('    ' + ' | '.join(str(c) for c in r))
            else:
                out('    (no config / not enabled)')
        except Exception as e:
            out(f'    ERROR: {str(e)[:90]}')
        conn.close()

        # ── 3. LIVE QUEUE TEST: change itemsaleprice, watch r3britems/britems ─
        sec('3. Live queue test — change HQ items.itemsaleprice (real change)')
        conn = get_sybase_connection(); cur = conn.cursor()

        # snapshot
        cur.execute('SELECT itemsaleprice, posdiscp, pharmacydiscp FROM SOFTECHDB9.dbo.items WHERE itemcode=?', [ITEM])
        orig = cur.fetchone()
        orig_price = float(orig[0] or 0)
        out(f'  HQ items orig: pack={orig[0]} pos={orig[1]} pharm={orig[2]}')

        cur.execute('SELECT COUNT(*) FROM SOFTECHDB9.dbo.r3britems WHERE itemcode=?', [ITEM])
        r3_before = int(cur.fetchone()[0] or 0)
        cur.execute('SELECT COUNT(*) FROM SOFTECHDB9.dbo.r3britems')
        r3_total_before = int(cur.fetchone()[0] or 0)
        cur.execute('SELECT branchcode, itemsaleprice, trans_time FROM SOFTECHDB9.dbo.britems WHERE itemcode=? ORDER BY branchcode', [ITEM])
        bri_before = {r[0]: (float(r[1] or 0), str(r[2])[:19]) for r in cur.fetchall()}
        out(f'  r3britems rows for item: {r3_before} (total: {r3_total_before})')
        out(f'  britems trans_times: ' + ', '.join(f'{k}={v[1]}' for k, v in bri_before.items()))

        # change itemsaleprice to a genuinely new value
        new_price = orig_price + 7 if orig_price else 50
        out(f'\n  >>> UPDATE HQ items.itemsaleprice {orig_price} -> {new_price}')
        cur.execute('UPDATE SOFTECHDB9.dbo.items SET itemsaleprice=?, usercode=? WHERE itemcode=?',
                    [new_price, '00099', ITEM])
        conn.close()

        time.sleep(2)
        conn = get_sybase_connection(); cur = conn.cursor()

        cur.execute('SELECT COUNT(*) FROM SOFTECHDB9.dbo.r3britems WHERE itemcode=?', [ITEM])
        r3_after = int(cur.fetchone()[0] or 0)
        cur.execute('SELECT COUNT(*) FROM SOFTECHDB9.dbo.r3britems')
        r3_total_after = int(cur.fetchone()[0] or 0)
        cur.execute('SELECT branchcode, itemsaleprice, trans_time FROM SOFTECHDB9.dbo.britems WHERE itemcode=? ORDER BY branchcode', [ITEM])
        bri_after = {r[0]: (float(r[1] or 0), str(r[2])[:19]) for r in cur.fetchall()}

        out(f'  r3britems rows for item AFTER: {r3_after} (total: {r3_total_after}, diff={r3_total_after-r3_total_before:+d})')
        out(f'  britems AFTER:')
        for k in sorted(bri_after):
            before = bri_before.get(k, (0, '?'))
            changed_price = abs(bri_after[k][0] - before[0]) > 0.01
            changed_time  = bri_after[k][1] != before[1]
            out(f'    BR{k}: price={bri_after[k][0]} (changed={changed_price}) trans_time={bri_after[k][1]} (changed={changed_time})')

        # show any r3britems rows for this item
        if r3_after > 0:
            out('\n  r3britems rows for item:')
            cur.execute('SELECT * FROM SOFTECHDB9.dbo.r3britems WHERE itemcode=?', [ITEM])
            for r in cur.fetchall():
                out('    ' + ' | '.join(str(c) for c in r))

        # verdict
        out('\n  VERDICT:')
        if r3_total_after > r3_total_before:
            out('    -> itemsaleprice change POPULATED r3britems queue (this is the replication trigger!)')
        elif any(bri_after[k][1] != bri_before.get(k, (0,'?'))[1] for k in bri_after):
            out('    -> itemsaleprice change UPDATED britems trans_time (britems is the queue, drained externally)')
        else:
            out('    -> Neither r3britems nor britems changed; replication queue is elsewhere/external')

        # revert
        cur.execute('UPDATE SOFTECHDB9.dbo.items SET itemsaleprice=? WHERE itemcode=?', [orig_price, ITEM])
        conn.close()
        out(f'\n  Reverted itemsaleprice to {orig_price}')
        out('\nDONE.')
