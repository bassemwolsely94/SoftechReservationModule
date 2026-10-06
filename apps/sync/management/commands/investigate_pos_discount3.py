"""
python manage.py investigate_pos_discount3
Gets full text of all items triggers and candidate sp_* procedures.
ASCII-only output to avoid Windows codepage crash.
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__),
    '..', '..', '..', '..', '..', 'docs',
    'softech_pos_discount_investigation.txt'
)

TRIGGERS = [
    'tr_items',
    'tr_items_update',
    'item_etax_vat_trigger',
    'tr_einv_itemslog',
    'tr_dm_stktrans',
    'tr_dm_stktransm',
    'tr_dm_stktransm5_updt',
]

SP_PROCS = [
    'sp_11973119731',
    'sp_24797247979',
    'sp_26905269051',
    'sp_28047280471',
    'sp_29378293789',
    'sp_610961091',
]


class Command(BaseCommand):
    help = 'Get trigger + procedure texts for POS discount investigation'

    def handle(self, *args, **options):
        from config.sybase import get_sybase_connection
        lines = []

        def out(text=''):
            safe = text.encode('ascii', 'replace').decode('ascii')
            self.stdout.write(safe)
            lines.append(text)

        def section(title):
            out('')
            out('=' * 70)
            out('  ' + title)
            out('=' * 70)

        conn = get_sybase_connection()
        out(f'Started: {datetime.datetime.now().isoformat()}')

        # ── offers / offersm schema ───────────────────────────────────────────
        section('offers TABLE SCHEMA')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.name, t.name AS type, c.length, c.colid
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.name = 'offers'
                ORDER  BY c.colid
            """)
            for r in cur.fetchall():
                out(f'  [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        section('offersm TABLE SCHEMA')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.name, t.name AS type, c.length, c.colid
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.name = 'offersm'
                ORDER  BY c.colid
            """)
            for r in cur.fetchall():
                out(f'  [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        section('mitemshist TABLE SCHEMA')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.name, t.name AS type, c.length, c.colid
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.name = 'mitemshist'
                ORDER  BY c.colid
            """)
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out(f'  [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
            else:
                out('  (table not found)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        section('mitems TABLE SCHEMA')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.name, t.name AS type, c.length, c.colid
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.name = 'mitems'
                ORDER  BY c.colid
            """)
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out(f'  [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
            else:
                out('  (table not found)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── mitemshist sample ─────────────────────────────────────────────────
        section('mitemshist SAMPLE ROWS')
        try:
            cur = conn.cursor()
            cur.execute('SELECT TOP 5 * FROM SOFTECHDB9.dbo.mitemshist ORDER BY 1 DESC')
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out('  ' + ' | '.join(str(c) for c in r))
            else:
                out('  (no rows)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── mitems sample ─────────────────────────────────────────────────────
        section('mitems SAMPLE ROWS')
        try:
            cur = conn.cursor()
            cur.execute('SELECT TOP 5 * FROM SOFTECHDB9.dbo.mitems ORDER BY 1 DESC')
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out('  ' + ' | '.join(str(c) for c in r))
            else:
                out('  (no rows)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── offers sample ─────────────────────────────────────────────────────
        section('offers SAMPLE ROWS')
        try:
            cur = conn.cursor()
            cur.execute('SELECT TOP 5 * FROM SOFTECHDB9.dbo.offers ORDER BY 1 DESC')
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out('  ' + ' | '.join(str(c) for c in r))
            else:
                out('  (no rows)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        section('offersm SAMPLE ROWS')
        try:
            cur = conn.cursor()
            cur.execute('SELECT TOP 5 * FROM SOFTECHDB9.dbo.offersm ORDER BY 1 DESC')
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out('  ' + ' | '.join(str(c) for c in r))
            else:
                out('  (no rows)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── Full text of triggers ─────────────────────────────────────────────
        section('TRIGGER FULL TEXTS')
        for tname in TRIGGERS:
            out('')
            out(f'--- TRIGGER: {tname} ---')
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT sc.colid, sc.text
                    FROM   SOFTECHDB9.dbo.syscomments sc
                    JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
                    WHERE  o.name = ? AND o.type = 'TR'
                    ORDER BY sc.colid
                """, [tname])
                rows = cur.fetchall()
                if rows:
                    full = ''.join(str(r[1]) for r in rows)
                    out(full.encode('ascii', 'replace').decode('ascii'))
                else:
                    out('  (no text -- may be encrypted or not found)')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {e}')

        # ── Full text of sp_* procedures ──────────────────────────────────────
        section('sp_* PROCEDURE TEXTS (UPDATE items candidates)')
        for pname in SP_PROCS:
            out('')
            out(f'--- PROCEDURE: {pname} ---')
            try:
                cur = conn.cursor()
                cur.execute("""
                    SELECT sc.colid, sc.text
                    FROM   SOFTECHDB9.dbo.syscomments sc
                    JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
                    WHERE  o.name = ? AND o.type = 'P'
                    ORDER BY sc.colid
                """, [pname])
                rows = cur.fetchall()
                if rows:
                    full = ''.join(str(r[1]) for r in rows)
                    out(full.encode('ascii', 'replace').decode('ascii'))
                else:
                    out('  (no text -- may be encrypted or not found)')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {e}')

        # ── replication: check sysrepdescs / RSSD / agent tables ─────────────
        section('REPLICATION TABLES CHECK')
        for tbl in ['sysrepdescs', 'syssrvroles', 'rs_lastcommit', 'rs_marker', 'rs_info']:
            out(f'\n--- {tbl} ---')
            try:
                cur = conn.cursor()
                cur.execute(f'SELECT TOP 3 * FROM SOFTECHDB9.dbo.{tbl}')
                rows = cur.fetchall()
                if rows:
                    for r in rows:
                        out('  ' + ' | '.join(str(c) for c in r))
                else:
                    out('  (no rows)')
                cur.close()
            except Exception as e:
                out(f'  ERROR: {e}')

        # ── branch sync tables ────────────────────────────────────────────────
        section('BRANCH SYNC / PENDING TABLES')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT o.name, o.type
                FROM   SOFTECHDB9.dbo.sysobjects o
                WHERE  o.type = 'U'
                  AND (
                      LOWER(o.name) LIKE '%send%'
                      OR LOWER(o.name) LIKE '%branch%items%'
                      OR LOWER(o.name) LIKE '%items%branch%'
                      OR LOWER(o.name) LIKE '%items%update%'
                      OR LOWER(o.name) LIKE '%items%change%'
                      OR LOWER(o.name) LIKE '%dispatch%'
                      OR LOWER(o.name) LIKE '%broadcast%'
                  )
                ORDER BY o.name
            """)
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out(f'  {r[0]} ({r[1]})')
            else:
                out('  (none found)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── Check what einv_itemslog table looks like ─────────────────────────
        section('einv_itemslog TABLE (referenced by tr_einv_itemslog)')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.name, t.name AS type, c.length, c.colid
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.name = 'einv_itemslog'
                ORDER  BY c.colid
            """)
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out(f'  [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
            else:
                out('  (table not found)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        # ── nepton_fusionlog (referenced by nepton tables found earlier) ──────
        section('nepton_fusionlog TABLE')
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT c.name, t.name AS type, c.length, c.colid
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.name = 'nepton_fusionlog'
                ORDER  BY c.colid
            """)
            rows = cur.fetchall()
            if rows:
                for r in rows:
                    out(f'  [{r[3]:>3}] {str(r[0]):<35} {str(r[1]):<15} len={r[2]}')
            else:
                out('  (table not found)')
            cur.close()
        except Exception as e:
            out(f'  ERROR: {e}')

        conn.close()
        out(f'\nComplete: {datetime.datetime.now().isoformat()}')

        # Save output
        dest = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        self.stdout.write(f'\nSaved -> {dest}')
