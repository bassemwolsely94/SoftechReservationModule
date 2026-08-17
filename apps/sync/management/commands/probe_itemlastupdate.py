"""
python manage.py probe_itemlastupdate

Investigate the itemlastupdate TABLE — prime suspect for the posdiscp
replication queue that the SSB9 service bus polls.

  - full schema (does it carry posdiscp + all pricing?)
  - recent rows (is it actively written?)
  - does a HQ items UPDATE insert a row here? (live test, reverted)
  - which trigger/object writes to it
"""
import time
from django.core.management.base import BaseCommand

ITEM = '127397'


class Command(BaseCommand):
    help = 'Investigate itemlastupdate replication-queue table'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection

        def out(t=''):
            self.stdout.write(str(t).encode('ascii', 'replace').decode('ascii'))

        def sec(t):
            out(''); out('=' * 70); out('  ' + t); out('=' * 70)

        conn = get_sybase_connection()

        # ── schema ────────────────────────────────────────────────────────────
        sec('itemlastupdate — full schema')
        cur = conn.cursor()
        cur.execute("""
            SELECT c.name, t.name AS type, c.length, c.colid
            FROM SOFTECHDB9.dbo.syscolumns c
            JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id
            JOIN SOFTECHDB9.dbo.systypes t ON c.usertype=t.usertype
            WHERE o.name='itemlastupdate'
            ORDER BY c.colid
        """)
        cols = cur.fetchall()
        for r in cols:
            out(f'  [{r[3]:>3}] {str(r[0]):<28} {str(r[1]):<12} len={r[2]}')
        cur.close()

        # ── row count + recent rows ──────────────────────────────────────────
        sec('itemlastupdate — count + recent rows')
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM SOFTECHDB9.dbo.itemlastupdate')
        out(f'  total rows: {cur.fetchone()[0]}')
        cur.close()

        # try to find a timestamp column to order by
        ts_col = None
        for r in cols:
            if str(r[1]).lower() in ('datetime', 'smalldatetime'):
                ts_col = r[0]; break
        order = f'ORDER BY {ts_col} DESC' if ts_col else 'ORDER BY 1 DESC'
        out(f'  (ordering by {ts_col or "col1"})')
        cur = conn.cursor()
        cur.execute('SET ROWCOUNT 8')
        cur.execute(f'SELECT * FROM SOFTECHDB9.dbo.itemlastupdate {order}')
        colnames = [d[0] for d in cur.description]
        out('  cols: ' + ', '.join(colnames))
        for r in cur.fetchall():
            out('  ' + ' | '.join(str(c) for c in r))
        cur.execute('SET ROWCOUNT 0')
        cur.close()

        # ── any existing row for our item ────────────────────────────────────
        sec(f'itemlastupdate — rows for item {ITEM}')
        cur = conn.cursor()
        cur.execute('SELECT * FROM SOFTECHDB9.dbo.itemlastupdate WHERE itemcode=?', [ITEM])
        rows = cur.fetchall()
        if rows:
            for r in rows:
                out('  ' + ' | '.join(str(c) for c in r))
        else:
            out('  (no row currently)')
        cur.close()

        # ── LIVE TEST: change HQ items.posdiscp, watch itemlastupdate ────────
        sec('LIVE TEST: change items.posdiscp -> does itemlastupdate get a row?')
        cur = conn.cursor()
        cur.execute('SELECT posdiscp FROM SOFTECHDB9.dbo.items WHERE itemcode=?', [ITEM])
        orig = float(cur.fetchone()[0] or 0)
        cur.execute('SELECT COUNT(*) FROM SOFTECHDB9.dbo.itemlastupdate')
        cnt_before = int(cur.fetchone()[0] or 0)
        cur.execute('SELECT COUNT(*) FROM SOFTECHDB9.dbo.itemlastupdate WHERE itemcode=?', [ITEM])
        item_before = int(cur.fetchone()[0] or 0)
        cur.close()
        out(f'  before: posdiscp={orig} | itemlastupdate total={cnt_before} for-item={item_before}')

        new = orig + 1
        cur = conn.cursor()
        cur.execute('UPDATE SOFTECHDB9.dbo.items SET posdiscp=?, usercode=? WHERE itemcode=?',
                    [new, '00099', ITEM])
        conn.close()
        out(f'  >>> UPDATE items.posdiscp {orig} -> {new}')

        time.sleep(2)
        conn = get_sybase_connection()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM SOFTECHDB9.dbo.itemlastupdate')
        cnt_after = int(cur.fetchone()[0] or 0)
        cur.execute('SELECT * FROM SOFTECHDB9.dbo.itemlastupdate WHERE itemcode=?', [ITEM])
        item_rows = cur.fetchall()
        out(f'  after: itemlastupdate total={cnt_after} (diff={cnt_after-cnt_before:+d})')
        out(f'  rows for item {ITEM} now:')
        if item_rows:
            cur2 = conn.cursor()
            cur2.execute("SELECT c.name FROM SOFTECHDB9.dbo.syscolumns c JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id WHERE o.name='itemlastupdate' ORDER BY c.colid")
            cn = [r[0] for r in cur2.fetchall()]; cur2.close()
            out('    cols: ' + ', '.join(cn))
            for r in item_rows:
                out('    ' + ' | '.join(str(c) for c in r))
        else:
            out('    (still none)')
        cur.close()

        # ── what writes to itemlastupdate? ────────────────────────────────────
        sec('Objects referencing itemlastupdate (sysdepends)')
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT o.name, o.type
            FROM SOFTECHDB9.dbo.sysdepends d
            JOIN SOFTECHDB9.dbo.sysobjects dep ON dep.id=d.depid
            JOIN SOFTECHDB9.dbo.sysobjects o ON o.id=d.id
            WHERE dep.name='itemlastupdate'
            ORDER BY o.type, o.name
        """)
        for r in cur.fetchall():
            out(f'  {r[1]}: {r[0]}')
        cur.close()

        # revert
        cur = conn.cursor()
        cur.execute('UPDATE SOFTECHDB9.dbo.items SET posdiscp=? WHERE itemcode=?', [orig, ITEM])
        cur.close()
        conn.close()
        out(f'\n  reverted posdiscp to {orig}')
        out('\nDONE.')
