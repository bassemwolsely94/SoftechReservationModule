"""
python manage.py probe_replication_source

DEFINITIVE experiment to determine SOFTECH's item replication mechanism.

Strategy: plant DISTINCT marker values in HQ items vs HQ britems, then fire a
branch items update and observe which source (if any) the branch trigger pulls
from — or whether it rolls our write back entirely.

Markers:
  HQ items.pharmacydiscp   = 33   (marker A — "from items")
  HQ britems.pharmacydiscp = 44   (marker B — "from britems")
  HQ items.posdiscp        = 22   (posdiscp is NOT in britems)
  branch local write        = 55   (marker C — "my local write stuck")

Outcome interpretation for branch pharmacydiscp after a local trigger fire:
  == 55  -> local write stuck, NO pull from HQ
  == 33  -> branch pulled from HQ items
  == 44  -> branch pulled from HQ britems
  == old -> trigger errored and ROLLED BACK my write

And for branch posdiscp:
  == 22  -> branch pulled posdiscp from HQ items
  == 99  -> my local posdiscp write stuck (britems can't carry it)
  == old -> rolled back

Everything is reverted at the end.
"""
import time
from django.core.management.base import BaseCommand


ITEM = '127397'


class Command(BaseCommand):
    help = 'Determine SOFTECH item replication source (items vs britems)'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection, get_branch_connection
        from apps.branches.models import Branch

        def out(t=''):
            self.stdout.write(str(t).encode('ascii', 'replace').decode('ascii'))

        def sec(t):
            out(''); out('=' * 68); out('  ' + t); out('=' * 68)

        # Save originals so we can revert
        sec('STEP 0: Capture originals')
        conn = get_sybase_connection(); cur = conn.cursor()
        cur.execute('SELECT itemsaleprice, pharmacydiscp, posdiscp, usercode '
                    'FROM SOFTECHDB9.dbo.items WHERE itemcode=?', [ITEM])
        hq_orig = cur.fetchone()
        out(f'  HQ items orig: pack={hq_orig[0]} pharm={hq_orig[1]} pos={hq_orig[2]} user={hq_orig[3]}')

        cur.execute('SELECT branchcode, pharmacydiscp, itemsaleprice, trans_time '
                    'FROM SOFTECHDB9.dbo.britems WHERE itemcode=? ORDER BY branchcode', [ITEM])
        britems_orig = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}
        for bc, vals in britems_orig.items():
            out(f'  HQ britems[{bc}] orig: pharm={vals[0]} pack={vals[1]}')
        conn.close()

        # Test on two branches: one that "worked" before (160) and one that "rolled back" (140)
        test_branches = ['160', '140']
        branch_objs = {b.softech_branch_id: b for b in Branch.objects.filter(
            softech_branch_id__in=test_branches)}

        branch_orig = {}
        for bc in test_branches:
            b = branch_objs.get(bc)
            if not b:
                continue
            try:
                conn = get_branch_connection(b.db_host, b.db_port or 5000)
                cur = conn.cursor()
                cur.execute('SELECT itemsaleprice, pharmacydiscp, posdiscp FROM items WHERE itemcode=?', [ITEM])
                r = cur.fetchone()
                branch_orig[bc] = (float(r[0] or 0), float(r[1] or 0), float(r[2] or 0))
                out(f'  BR{bc} items orig: pack={r[0]} pharm={r[1]} pos={r[2]}')
                conn.close()
            except Exception as e:
                out(f'  BR{bc} read error: {str(e)[:60]}')

        # ── STEP 1: plant distinct markers at HQ ──────────────────────────────
        sec('STEP 1: Plant markers — HQ items pharm=33/pos=22, HQ britems pharm=44')
        conn = get_sybase_connection(); cur = conn.cursor()
        cur.execute('UPDATE SOFTECHDB9.dbo.items SET pharmacydiscp=33, posdiscp=22, usercode=? '
                    'WHERE itemcode=?', ['00099', ITEM])
        for bc in test_branches:
            cur.execute('UPDATE SOFTECHDB9.dbo.britems SET pharmacydiscp=44, trans_time=GETDATE() '
                        'WHERE itemcode=? AND branchcode=?', [ITEM, bc])
        conn.close()
        out('  Markers planted.')

        # verify
        conn = get_sybase_connection(); cur = conn.cursor()
        cur.execute('SELECT pharmacydiscp, posdiscp FROM SOFTECHDB9.dbo.items WHERE itemcode=?', [ITEM])
        r = cur.fetchone(); out(f'  HQ items now: pharm={r[0]} pos={r[1]}')
        for bc in test_branches:
            cur.execute('SELECT pharmacydiscp FROM SOFTECHDB9.dbo.britems WHERE itemcode=? AND branchcode=?', [ITEM, bc])
            r = cur.fetchone(); out(f'  HQ britems[{bc}] now: pharm={r[0] if r else "?"}')
        conn.close()

        # ── STEP 2: fire branch local price update (marker C = 55 / 99) ───────
        sec('STEP 2: Fire branch items update (local pharm=55, pos=99) and observe')
        for bc in test_branches:
            b = branch_objs.get(bc)
            if not b:
                continue
            out(f'\n  --- Branch {bc} ({b.db_host}) ---')
            try:
                conn = get_branch_connection(b.db_host, b.db_port or 5000)
                cur = conn.cursor()
                # local write with distinct markers
                cur.execute('UPDATE items SET pharmacydiscp=55, posdiscp=99, usercode=? WHERE itemcode=?',
                            ['00099', ITEM])
                # readback immediately
                cur.execute('SELECT pharmacydiscp, posdiscp FROM items WHERE itemcode=?', [ITEM])
                r = cur.fetchone()
                pharm = float(r[0] or 0); pos = float(r[1] or 0)
                conn.close()

                # interpret pharmacydiscp
                if abs(pharm - 55) < 0.01:
                    p_verdict = 'LOCAL WRITE STUCK (no pull, no rollback)'
                elif abs(pharm - 33) < 0.01:
                    p_verdict = 'PULLED FROM HQ items'
                elif abs(pharm - 44) < 0.01:
                    p_verdict = 'PULLED FROM HQ britems'
                elif abs(pharm - branch_orig.get(bc, (0,0,0))[1]) < 0.01:
                    p_verdict = 'ROLLED BACK (trigger error)'
                else:
                    p_verdict = f'UNKNOWN ({pharm})'

                if abs(pos - 99) < 0.01:
                    pos_verdict = 'LOCAL posdiscp STUCK'
                elif abs(pos - 22) < 0.01:
                    pos_verdict = 'PULLED posdiscp FROM HQ items'
                elif abs(pos - branch_orig.get(bc, (0,0,0))[2]) < 0.01:
                    pos_verdict = 'posdiscp ROLLED BACK/unchanged'
                else:
                    pos_verdict = f'UNKNOWN ({pos})'

                out(f'  RESULT pharmacydiscp={pharm}: {p_verdict}')
                out(f'  RESULT posdiscp={pos}: {pos_verdict}')
            except Exception as e:
                out(f'  ERROR: {str(e)[:80]}')

        # ── STEP 3: revert everything ─────────────────────────────────────────
        sec('STEP 3: Revert all changes')
        conn = get_sybase_connection(); cur = conn.cursor()
        cur.execute('UPDATE SOFTECHDB9.dbo.items SET itemsaleprice=?, pharmacydiscp=?, posdiscp=?, usercode=? '
                    'WHERE itemcode=?',
                    [float(hq_orig[0] or 0), float(hq_orig[1] or 0), float(hq_orig[2] or 0),
                     hq_orig[3], ITEM])
        for bc, vals in britems_orig.items():
            try:
                cur.execute('UPDATE SOFTECHDB9.dbo.britems SET pharmacydiscp=?, itemsaleprice=?, trans_time=? '
                            'WHERE itemcode=? AND branchcode=?',
                            [float(vals[0] or 0), float(vals[1] or 0), vals[2], ITEM, bc])
            except Exception as e:
                out(f'  britems[{bc}] revert error: {str(e)[:50]}')
        conn.close()
        out('  HQ items + britems reverted.')

        for bc in test_branches:
            b = branch_objs.get(bc)
            orig = branch_orig.get(bc)
            if not b or not orig:
                continue
            try:
                conn = get_branch_connection(b.db_host, b.db_port or 5000)
                cur = conn.cursor()
                cur.execute('UPDATE items SET pharmacydiscp=?, posdiscp=? WHERE itemcode=?',
                            [orig[1], orig[2], ITEM])
                conn.close()
                out(f'  BR{bc} reverted to pharm={orig[1]} pos={orig[2]}')
            except Exception as e:
                out(f'  BR{bc} revert error: {str(e)[:50]}')

        out('\nDONE.')
