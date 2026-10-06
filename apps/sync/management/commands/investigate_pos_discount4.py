"""
python manage.py investigate_pos_discount4
Final targeted queries: branch-sync tables, items_etax_vat, items_changefollow schema.
"""
import os
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Final targeted investigation queries'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection
        conn = get_sybase_connection()

        def out(text=''):
            safe = str(text).encode('ascii', 'replace').decode('ascii')
            self.stdout.write(safe)

        def schema(tbl):
            out(f'\n=== SCHEMA: {tbl} ===')
            try:
                cur = conn.cursor()
                cur.execute(f"""
                    SELECT c.name, t.name AS type, c.length, c.colid
                    FROM   SOFTECHDB9.dbo.syscolumns c
                    JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                    JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                    WHERE  o.name = '{tbl}'
                    ORDER  BY c.colid
                """)
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        out(f'  [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
                else:
                    out('  (not found)')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {e}')

        def sample(tbl, order='1'):
            out(f'\n=== SAMPLE: {tbl} ===')
            try:
                cur = conn.cursor()
                # Use SET ROWCOUNT instead of TOP for Sybase compatibility
                cur.execute('SET ROWCOUNT 5')
                cur.execute(f'SELECT * FROM SOFTECHDB9.dbo.{tbl} ORDER BY {order}')
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        out('  ' + ' | '.join(str(c) for c in r))
                else:
                    out('  (no rows)')
                cur.execute('SET ROWCOUNT 0')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {e}')

        # Branch sync tables
        schema('cars_itemschanges')
        sample('cars_itemschanges')
        schema('items_changefollow')
        sample('items_changefollow')

        # items_etax_vat — e-invoicing replica (populated by item_etax_vat_trigger)
        schema('items_etax_vat')
        sample('items_etax_vat')

        # Check if items_etax_vat has any posdiscp column
        out('\n=== items_etax_vat.posdiscp exists? ===')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.name FROM SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                WHERE  o.name = 'items_etax_vat' AND c.name = 'posdiscp'
            """)
            r = cur.fetchone()
            out(f'  {"YES — posdiscp column found" if r else "NO — not found"}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # Check r3dm_stktrans (branch replication queue for deliveries)
        schema('r3dm_stktrans')
        schema('r3dm_stktransm')

        # Check lastdocnumbers (used in tr_items to determine HQ vs branch)
        schema('lastdocnumbers')
        out('\n=== SAMPLE: lastdocnumbers (ver_branch=1 row) ===')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT * FROM SOFTECHDB9.dbo.lastdocnumbers
                WHERE ver_branch = '1'
            """)
            rows = cur.fetchall()
            for r in rows:
                out('  ' + ' | '.join(str(c) for c in r))
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # Check tr_items_update encryption status
        out('\n=== tr_items_update ENCRYPTION STATUS ===')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT o.name, o.sysstat, o.sysstat2,
                       (CASE WHEN (o.sysstat & 0x2000) = 0x2000 THEN 'ENCRYPTED' ELSE 'PLAIN' END) AS enc_status
                FROM SOFTECHDB9.dbo.sysobjects o
                WHERE o.name = 'tr_items_update' AND o.type = 'TR'
            """)
            rows = cur.fetchall()
            for r in rows:
                out('  ' + ' | '.join(str(c) for c in r))
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # Count syscomments rows for tr_items_update
        out('\n=== syscomments row count for tr_items_update ===')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(*), MIN(sc.text), MAX(sc.colid)
                FROM SOFTECHDB9.dbo.syscomments sc
                JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id = o.id
                WHERE o.name = 'tr_items_update' AND o.type = 'TR'
            """)
            r = cur.fetchone()
            out(f'  count={r[0]}, sample_text={r[1]}, max_colid={r[2]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # Check custdiscpclassifcomm (interesting table found)
        schema('custdiscpclassifcomm')
        sample('custdiscpclassifcomm')

        # nepton_fusion table (branch sync?)
        schema('nepton_fusion')
        out('\n=== SAMPLE: nepton_fusion ===')
        try:
            cur = conn.cursor()
            cur.execute('SET ROWCOUNT 3')
            cur.execute('SELECT * FROM SOFTECHDB9.dbo.nepton_fusion ORDER BY 1 DESC')
            rows = cur.fetchall()
            for r in rows:
                out('  ' + ' | '.join(str(c) for c in r))
            cur.execute('SET ROWCOUNT 0')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # Check items_etax_vat latest row to see posdiscp value
        out('\n=== items_etax_vat most recent rows ===')
        try:
            cur = conn.cursor()
            cur.execute('SET ROWCOUNT 3')
            cur.execute('SELECT itemcode, itemname, itemsaleprice, posdiscp, pharmacydiscp, itemlastupdate FROM SOFTECHDB9.dbo.items_etax_vat ORDER BY itemlastupdate DESC')
            rows = cur.fetchall()
            for r in rows:
                out('  ' + ' | '.join(str(c) for c in r))
            cur.execute('SET ROWCOUNT 0')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # One real items row to see posdiscp live value
        out('\n=== items with non-zero posdiscp (sample) ===')
        try:
            cur = conn.cursor()
            cur.execute('SET ROWCOUNT 5')
            cur.execute("""
                SELECT itemcode, itemname, itemsaleprice, pharmacydiscp,
                       additionaldiscp, specialdiscp, posdiscp, itemlastupdate
                FROM SOFTECHDB9.dbo.items
                WHERE posdiscp > 0
                ORDER BY itemlastupdate DESC
            """)
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out('  ' + ' | '.join(str(c) for c in r))
            else:
                out('  (no items with posdiscp > 0)')
            cur.execute('SET ROWCOUNT 0')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # All items discount fields distribution
        out('\n=== Discount field statistics ===')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    COUNT(*) AS total_items,
                    SUM(CASE WHEN posdiscp > 0 THEN 1 ELSE 0 END) AS has_posdiscp,
                    SUM(CASE WHEN pharmacydiscp > 0 THEN 1 ELSE 0 END) AS has_pharmacydiscp,
                    SUM(CASE WHEN additionaldiscp > 0 THEN 1 ELSE 0 END) AS has_additionaldiscp,
                    SUM(CASE WHEN specialdiscp > 0 THEN 1 ELSE 0 END) AS has_specialdiscp
                FROM SOFTECHDB9.dbo.items
                WHERE itemnomoreuse != '1' AND itemarchive = 0
            """)
            r = cur.fetchone()
            out(f'  total_items={r[0]} | posdiscp>0={r[1]} | pharmacydiscp>0={r[2]} | additionaldiscp>0={r[3]} | specialdiscp>0={r[4]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        conn.close()
        out('\nDone.')
