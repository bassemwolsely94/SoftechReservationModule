"""
python manage.py investigate_purchase_invoice [--profile prod] [--branch-host 192.168.30.12]

READ-ONLY discovery of the SOFTECH **supplier purchase invoice** pathway — the
purchase-side mirror of investigate_pos_cashier (which mapped the customer-sale
pending order in stktransm5/stktrans5).

Goal — answer, with live evidence:
  1. WHERE is an in-progress ("save on screen, retrieve & finalize later")
     supplier invoice staged?  Hypothesis: the SAME "5"-suffix staging twins
     stktransm5 / stktrans5, keyed by doccode 10 (purchase) / 120 (return to
     supplier) — because tr_stktransm5 already routes those doccodes to the
     *_supp counters, and stktransm5/stktrans5 carry supplier columns
     (supp_main_code / suppliercode / s_doccode).  This probe confirms or refutes
     by enumerating purchase-named tables and counting staged doccode 10/120 rows.
  2. The GOLDEN TEMPLATE: every column value the native purchasing screen sets on
     a real doccode-10 document — captured from a FINALIZED stktransm/stktrans row
     (always available) and, if present, a PENDING stktransm5/stktrans5 row.
  3. The serial counters for purchases:
     lastdocnumbers.lastdocnumberin_supp (doccode 10) /
     lastdocnumberout_supp (doccode 120), on branchcode='000' (pending) and the
     branch's own ver_branch=1 row (final).
  4. Any stored procedure / trigger on the purchase create/save path.

doccode reference (confirmed in apps/procurement/queries.py):
    '10'  = purchase from supplier
    '120' = return to supplier

ABSOLUTE RULE: SELECT only. No writes are ever issued.

Output -> docs/architecture/softech_purchase_invoice_investigation.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__),
    '..', '..', '..', '..', 'docs', 'architecture',
    'softech_purchase_invoice_investigation.txt',
)

# User-table name patterns that might back a dedicated purchase/receiving staging
# area (if it ISN'T the shared stktransm5/stktrans5 twins).
TABLE_NAME_PATTERNS = [
    '%purch%', '%supp%', '%receiv%', '%grn%', '%buy%', '%waredm%', '%mokhzon%',
    '%trans5%', '%transm5%',          # the shared "5" staging-twin hypothesis
    '%pend%', '%hold%', '%draft%', '%staging%', '%temp%',
]

NULLABLE_BIT = 8

# Tables whose full schema we always dump (header + lines, staging + final).
SCHEMA_TABLES = ['stktransm5', 'stktrans5', 'stktransm', 'stktrans', 'branchesales5']


class Command(BaseCommand):
    help = 'READ-ONLY discovery of the SOFTECH supplier purchase-invoice tables (doccode 10/120)'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod', help='SOFTECH profile (default: prod = HQ)')
        parser.add_argument('--branch-host', default='',
                            help='Optional branch Sybase IP to also probe for live pending purchase rows')
        parser.add_argument('--branch-port', type=int, default=5000)
        parser.add_argument('--branch-db', default='SOFTECHDB9')

    def handle(self, *args, **options):
        from django.conf import settings
        from config.sybase import SoftechConnector, get_branch_connection

        profile = options['profile']
        lines = []

        def log(t=''):
            self.stdout.write(t)
            lines.append(t)

        def section(title):
            bar = '=' * 80
            log(''); log(bar); log(f'  {title}'); log(bar)

        log(f'Purchase-invoice discovery started: {datetime.datetime.now().isoformat()}')
        log(f'Profile: {profile} | effective host: '
            f'{os.environ.get("SOFTECH_%s_HOST" % profile.upper()) or getattr(settings, "SYBASE_HOST", "?")}')
        log('Mode: READ-ONLY (SELECT only)  | doccode 10=purchase, 120=return-to-supplier')

        try:
            conn = SoftechConnector(profile=profile).connect()
        except Exception as e:
            log(f'[FATAL] connect failed: {e}')
            self._save(lines)
            return

        # ── generic helpers ──────────────────────────────────────────────────
        def run(label, sql, params=None):
            log(f'\n--- {label} ---')
            try:
                cur = conn._cursor()
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                if not rows:
                    log('  (no rows)')
                    return []
                log('  COLS: ' + ' | '.join(cols))
                for r in rows:
                    log('  ' + ' | '.join('NULL' if c is None else str(c) for c in r))
                return rows
            except Exception as e:
                log(f'  [ERROR] {e}')
                return []

        def set_rowcount(n):
            # ASE 12.5 / jConnect 3 has NO `SELECT TOP n` — use SET ROWCOUNT
            # (connection-scoped; SoftechConnector cursors share one java conn).
            try:
                conn._cursor().execute(f'SET ROWCOUNT {n}')
            except Exception as e:
                log(f'  [ERROR set rowcount] {e}')

        def dump_row_vertical(label, sql, params=None):
            """Dump the FIRST row as col=value pairs (the golden template).
            Caller must pass a NON-TOP query; we cap it with SET ROWCOUNT 1."""
            log(f'\n--- {label} (golden template, one row vertical) ---')
            set_rowcount(1)
            try:
                cur = conn._cursor()
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                if not row:
                    log('  (no rows)')
                    return None
                for name, val in zip(cols, row):
                    log(f'    {name:<28} = {"NULL" if val is None else val}')
                return dict(zip(cols, row))
            except Exception as e:
                log(f'  [ERROR] {e}')
                return None
            finally:
                set_rowcount(0)

        def schema(tbl):
            log(f'\n  SCHEMA: {tbl}  (colid | name | type | len | NULL?)')
            try:
                cur = conn._cursor()
                cur.execute(f"""
                    SELECT c.colid, c.name, t.name AS type, c.length, c.status
                    FROM   SOFTECHDB9.dbo.syscolumns c
                    JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                    JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                    WHERE  o.name = '{tbl}'
                    ORDER  BY c.colid
                """)
                rows = cur.fetchall()
                if not rows:
                    log('    (not found)')
                    return
                for r in rows:
                    nullable = 'NULL' if (int(r[4] or 0) & NULLABLE_BIT) else 'NOT NULL'
                    log(f'    [{str(r[0]):>3}] {str(r[1]):<28} {str(r[2]):<14} len={str(r[3]):<5} {nullable}')
            except Exception as e:
                log(f'    [ERROR] {e}')

        # ── A: candidate purchase/receiving tables by NAME ───────────────────
        section('A: Candidate purchase / receiving / staging tables by NAME')
        for pat in TABLE_NAME_PATTERNS:
            run(f"name LIKE '{pat}'", f"""
                SELECT o.name
                FROM   SOFTECHDB9.dbo.sysobjects o
                WHERE  o.type = 'U' AND LOWER(o.name) LIKE '{pat}'
                ORDER  BY o.name
            """)

        # ── B: is the shared staging twin used for purchases? ────────────────
        section('B: doccode distribution in staging (stktransm5) vs final (stktransm)')
        run('stktransm5 row counts by doccode (HQ staging)', """
            SELECT doccode, COUNT(*) AS cnt, MIN(docnumber) AS min_no, MAX(docnumber) AS max_no
            FROM   SOFTECHDB9.dbo.stktransm5
            GROUP  BY doccode ORDER BY doccode
        """)
        run('stktransm row counts by doccode (last 30d, final)', """
            SELECT doccode, COUNT(*) AS cnt
            FROM   SOFTECHDB9.dbo.stktransm
            WHERE  docdate >= DATEADD(day, -30, GETDATE())
            GROUP  BY doccode ORDER BY doccode
        """)

        # ── C: GOLDEN TEMPLATE — finalized supplier purchase (doccode 10) ────
        section('C: GOLDEN TEMPLATE — finalized purchase (stktransm/stktrans doccode 10)')
        hdr = dump_row_vertical(
            'stktransm doccode=10 (most recent finalized purchase header)', """
            SELECT * FROM SOFTECHDB9.dbo.stktransm
            WHERE doccode='10' ORDER BY docdate DESC, docnumber DESC
        """)
        if hdr:
            key = (hdr.get('branchcode'), hdr.get('docnumber'), hdr.get('docdate'))
            run('its stktrans lines (all columns)', """
                SELECT * FROM SOFTECHDB9.dbo.stktrans
                WHERE branchcode=? AND doccode='10' AND docnumber=?
                ORDER BY itemcode
            """, [str(key[0]).strip(), key[1]])

        # ── C2: return-to-supplier (doccode 120) golden header ───────────────
        dump_row_vertical(
            'stktransm doccode=120 (most recent return-to-supplier header)', """
            SELECT * FROM SOFTECHDB9.dbo.stktransm
            WHERE doccode='120' ORDER BY docdate DESC, docnumber DESC
        """)

        # ── D: PENDING purchase template if any exists in staging ────────────
        section('D: PENDING purchase template (stktransm5/stktrans5 doccode 10/120) — may be empty')
        phdr = dump_row_vertical(
            'stktransm5 doccode IN (10,120) (a live pending purchase, if any)', """
            SELECT * FROM SOFTECHDB9.dbo.stktransm5
            WHERE doccode IN ('10','120') ORDER BY docnumber DESC
        """)
        if phdr:
            run('its stktrans5 lines (all columns)', """
                SELECT * FROM SOFTECHDB9.dbo.stktrans5
                WHERE branchcode=? AND doccode=? AND docnumber=?
            """, [str(phdr.get('branchcode')).strip(), str(phdr.get('doccode')).strip(),
                  phdr.get('docnumber')])

        # ── E: serial counters for purchases ─────────────────────────────────
        section('E: lastdocnumbers — purchase counters (*_supp)')
        run('lastdocnumbers (all rows) — *_supp columns', """
            SELECT branchcode, ver_branch, lastdocnumberin_supp, lastdocnumberout_supp
            FROM   SOFTECHDB9.dbo.lastdocnumbers ORDER BY branchcode
        """)

        # ── F: triggers / procs on the purchase path ─────────────────────────
        section('F: procedures/triggers referencing the purchase create/save path')
        run('procs/triggers mentioning stktransm5 / purchase / supplier', """
            SELECT DISTINCT o.name, o.type
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type IN ('P','TR')
              AND (LOWER(sc.text) LIKE '%stktransm5%'
                OR LOWER(sc.text) LIKE '%purch%'
                OR LOWER(sc.text) LIKE '%supplier%'
                OR LOWER(sc.text) LIKE '%lastdocnumberin_supp%')
            ORDER BY o.name
        """)
        # The tr_stktransm5 body confirms the doccode->counter routing (readable).
        run('tr_stktransm5 trigger body (doccode->counter routing)', """
            SELECT sc.text
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects o ON sc.id = o.id
            WHERE  o.name = 'tr_stktransm5' ORDER BY sc.colid2
        """)

        # ── G: schema of the staging + final tables ──────────────────────────
        section('G: Schema of staging + final header/line tables')
        for tbl in SCHEMA_TABLES:
            schema(tbl)

        # ── H: optional live branch probe (where purchases are entered) ───────
        bh = options['branch_host']
        if bh:
            section(f'H: BRANCH probe {bh} — live pending purchase staging')
            try:
                bconn = get_branch_connection(bh, options['branch_port'], options['branch_db'])
                bcur = bconn.cursor()
                bcur.execute("SELECT doccode, COUNT(*) FROM stktransm5 GROUP BY doccode ORDER BY doccode")
                rows = bcur.fetchall()
                log('  stktransm5 doccode distribution @ branch:')
                for r in rows:
                    log('    ' + ' | '.join('NULL' if c is None else str(c) for c in r))
                bcur2 = bconn.cursor()
                bcur2.execute("SELECT branchcode, ver_branch, lastdocnumberin_supp, lastdocnumberout_supp "
                              "FROM lastdocnumbers ORDER BY branchcode")
                log('  lastdocnumbers *_supp @ branch:')
                for r in bcur2.fetchall():
                    log('    ' + ' | '.join('NULL' if c is None else str(c) for c in r))
                bconn.close()
            except Exception as e:
                log(f'  [ERROR] branch probe: {e}')

        conn.close()
        log(f'\nComplete: {datetime.datetime.now().isoformat()}')
        self._save(lines)

    def _save(self, lines):
        path = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            self.stdout.write(self.style.SUCCESS(f'\nSaved -> {path}'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'\nCould not save: {e}'))
