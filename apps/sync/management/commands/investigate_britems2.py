"""
python manage.py investigate_britems2

Confirms whether writing to HQ britems causes the branch items table to update.
Also checks: how the branch reads britems, and what triggers fire on branch items.
"""
import datetime, time
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Confirm britems pull mechanism on branches'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection, get_branch_connection
        from apps.branches.models import Branch

        def out(text=''):
            safe = str(text).encode('ascii', 'replace').decode('ascii')
            self.stdout.write(safe)

        def section(t):
            out(''); out('=' * 65); out('  ' + t); out('=' * 65)

        conn_hq = get_sybase_connection()
        # Use branch 160 (192.168.1.5) — closest to HQ network
        br160 = Branch.objects.get(softech_branch_id='160')
        ITEM = '127397'

        # ── 1. Read current state ─────────────────────────────────────────────
        section('1. Current state HQ vs Branch 160')

        cur = conn_hq.cursor()
        cur.execute('SELECT pharmacydiscp, posdiscp, itemsaleprice FROM SOFTECHDB9.dbo.items WHERE itemcode = ?', [ITEM])
        hq_item = cur.fetchone(); cur.close()

        cur = conn_hq.cursor()
        cur.execute('SELECT branchcode, pharmacydiscp, itemsaleprice, trans_time FROM SOFTECHDB9.dbo.britems WHERE itemcode = ? AND branchcode = ?', [ITEM, '160'])
        hq_britems = cur.fetchone(); cur.close()

        conn_br = get_branch_connection(br160.db_host, br160.db_port or 5000)
        cur = conn_br.cursor()
        cur.execute('SELECT pharmacydiscp, posdiscp, itemsaleprice FROM items WHERE itemcode = ?', [ITEM])
        br_item = cur.fetchone()

        out(f'  HQ items:    pharmacydiscp={hq_item[0]}  posdiscp={hq_item[1]}  pack_price={hq_item[2]}')
        out(f'  HQ britems:  pharmacydiscp={hq_britems[1] if hq_britems else "NO ROW"}  pack_price={hq_britems[2] if hq_britems else "N/A"}  trans_time={str(hq_britems[3])[:19] if hq_britems else "N/A"}')
        out(f'  BR160 items: pharmacydiscp={br_item[0]}  posdiscp={br_item[1]}  pack_price={br_item[2]}')

        # ── 2. Write to HQ britems only (not to HQ items) ─────────────────────
        section('2. Write a DISTINCTIVE value to HQ britems only (not items)')

        TEST_PHARM = 77.0  # distinctive test value

        cur = conn_hq.cursor()
        cur.execute("""
            UPDATE SOFTECHDB9.dbo.britems
            SET pharmacydiscp = ?, trans_time = GETDATE()
            WHERE itemcode = ? AND branchcode = ?
        """, [TEST_PHARM, ITEM, '160'])
        conn_hq.close()
        out(f'  Wrote pharmacydiscp={TEST_PHARM} to HQ britems for branch 160')

        # Wait 3 seconds for any async pull
        out('  Waiting 3 seconds...')
        time.sleep(3)

        # Re-open and check
        conn_hq = get_sybase_connection()
        cur = conn_hq.cursor()
        cur.execute('SELECT pharmacydiscp, trans_time FROM SOFTECHDB9.dbo.britems WHERE itemcode = ? AND branchcode = ?', [ITEM, '160'])
        bri = cur.fetchone(); cur.close()
        out(f'  HQ britems now: pharmacydiscp={bri[0]}  trans_time={str(bri[1])[:19]}')

        cur = conn_br.cursor()
        cur.execute('SELECT pharmacydiscp, posdiscp FROM items WHERE itemcode = ?', [ITEM])
        br2 = cur.fetchone()
        out(f'  BR160 items now: pharmacydiscp={br2[0]}  posdiscp={br2[1]}')

        if abs(float(br2[0] or 0) - TEST_PHARM) < 0.01:
            out('  RESULT: Branch DID pull from britems (pharmacydiscp updated)')
        else:
            out('  RESULT: Branch DID NOT pull from britems within 3 seconds')

        # ── 3. Check branch triggers on its items table ───────────────────────
        section('3. Branch 160 triggers + sysdepends for tr_items_update')

        # Branch trigger dependencies
        try:
            cur = conn_br.cursor()
            cur.execute("""
                SELECT DISTINCT o.name AS obj, o.type
                FROM sysdepends d
                JOIN sysobjects trig ON trig.name = 'tr_items_update'
                JOIN sysobjects o    ON o.id = d.depid
                WHERE d.id = trig.id
                ORDER BY o.type, o.name
            """)
            rows = cur.fetchall()
            out('  tr_items_update sysdepends on branch 160:')
            for r in rows:
                out(f'    {r[1]}: {r[0]}')
        except Exception as e:
            out(f'  ERROR: {e}')

        # Check for britems on branch
        try:
            cur = conn_br.cursor()
            cur.execute('SELECT COUNT(*) FROM britems')
            cnt = cur.fetchone()[0]
            out(f'  branch britems count: {cnt}')
            if int(cnt or 0) > 0:
                cur.execute('SET ROWCOUNT 3')
                cur.execute('SELECT * FROM britems ORDER BY 1 DESC')
                for r in cur.fetchall():
                    out('    ' + ' | '.join(str(c) for c in r))
                cur.execute('SET ROWCOUNT 0')
        except Exception as e:
            out(f'  britems: {str(e)[:60]}')

        # ── 4. Check if branch tr_items_update reads from britems ─────────────
        section('4. Branch tr_items_update syscomments (encrypted?)')

        try:
            cur = conn_br.cursor()
            cur.execute("""
                SELECT sc.colid, DATALENGTH(sc.text) AS text_len,
                       SUBSTRING(CAST(sc.text AS varchar(100)), 1, 80) AS prefix
                FROM syscomments sc
                JOIN sysobjects o ON sc.id = o.id
                WHERE o.name = 'tr_items_update' AND o.type = 'TR'
                ORDER BY sc.colid
            """)
            rows = cur.fetchall()
            if rows:
                all_null = all(r[2] is None for r in rows)
                out(f'  {len(rows)} rows, all encrypted: {all_null}')
                for r in rows:
                    prefix = str(r[2] or 'NULL')[:80]
                    out(f'    colid={r[0]} len={r[1]} text={prefix}')
            else:
                out('  (no syscomments rows)')
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── 5. Try: write to HQ items directly + observe britems change ───────
        section('5. Write to HQ items — observe britems row change')

        conn_hq2 = get_sybase_connection()
        cur = conn_hq2.cursor()
        cur.execute('SELECT pharmacydiscp FROM SOFTECHDB9.dbo.items WHERE itemcode = ?', [ITEM])
        orig_pharm = float(cur.fetchone()[0] or 0); cur.close()

        # Get britems trans_time before
        cur = conn_hq2.cursor()
        cur.execute('SELECT trans_time, pharmacydiscp FROM SOFTECHDB9.dbo.britems WHERE itemcode = ? AND branchcode = ?', [ITEM, '160'])
        bri_before = cur.fetchone(); cur.close()
        out(f'  britems BEFORE: trans_time={str(bri_before[1])[:19] if bri_before else "N/A"} pharmacydiscp={bri_before[0] if bri_before else "N/A"}')

        # Write new pharmacydiscp to HQ items
        new_pharm = orig_pharm + 1 if orig_pharm != 55 else 56
        cur = conn_hq2.cursor()
        cur.execute('UPDATE SOFTECHDB9.dbo.items SET pharmacydiscp = ? WHERE itemcode = ?', [new_pharm, ITEM])
        conn_hq2.close()
        out(f'  Wrote pharmacydiscp {orig_pharm} -> {new_pharm} to HQ items')

        time.sleep(1)

        conn_hq3 = get_sybase_connection()
        cur = conn_hq3.cursor()
        cur.execute('SELECT trans_time, pharmacydiscp FROM SOFTECHDB9.dbo.britems WHERE itemcode = ? AND branchcode = ?', [ITEM, '160'])
        bri_after = cur.fetchone(); cur.close()
        out(f'  britems AFTER:  trans_time={str(bri_after[1])[:19] if bri_after else "N/A"} pharmacydiscp={bri_after[0] if bri_after else "N/A"}')

        if bri_after and bri_before:
            pharm_changed = abs(float(bri_after[0] or 0) - float(new_pharm)) < 0.01
            out(f'  britems.pharmacydiscp updated: {pharm_changed}  (expected {new_pharm}, got {bri_after[0]})')

        # Revert HQ items
        cur = conn_hq3.cursor()
        cur.execute('UPDATE SOFTECHDB9.dbo.items SET pharmacydiscp = ? WHERE itemcode = ?', [orig_pharm, ITEM])
        # Revert HQ britems
        cur.execute('UPDATE SOFTECHDB9.dbo.britems SET pharmacydiscp = ?, trans_time = ? WHERE itemcode = ? AND branchcode = ?',
                    [bri_before[0] if bri_before else orig_pharm,
                     bri_before[1] if bri_before else None,
                     ITEM, '160'])
        conn_hq3.close()
        conn_br.close()
        out('  Reverted HQ items and britems')
        out(f'\nComplete: {datetime.datetime.now().isoformat()}')
