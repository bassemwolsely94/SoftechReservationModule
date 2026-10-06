"""
python manage.py investigate_crm_orders [--profile test|prod|dev] [--branch 100]

READ-ONLY investigation of the SOFTECH call-center / CRM pending-order subsystem.
Goal: reverse-engineer EXACTLY how the native ERP client creates a *pending sales
order* (not a finalized stktrans/stktransm transaction) so our platform can mimic it
byte-for-byte — including the crmorderno serial allocation and any trigger chain.

ABSOLUTE RULE: SELECT only. This command never issues INSERT/UPDATE/DELETE.

Targets (default profile = test, per the agreed plan — set SOFTECH_TEST_HOST in .env):
  piccrmorders        — CC/delivery order header (crmbranchcode='100' = call center)
  piccrmorders5       — LIVE pending queue (docnumber=0, removed once invoiced)
  piccrmitems         — order line items
  piccrmordersnos     — order-serial registry (+ r3piccrmordersnos replication queue)
  piccrmorderstatus   — status history
  piccrmorderdel      — cancellations
  lastdocnumbers      — global document-number generator (referenced by tr_items)
  picdoctors          — referral-doctor table (refdoctorcode / maindoctor / comment)

The four questions this must answer:
  Q1 SERIAL  — how is the next crmorderno allocated? (piccrmordersnos? lastdocnumbers?
               max()+1? a stored proc under a lock?) — and is it concurrency-safe.
  Q2 TRIGGERS— what fires on INSERT into piccrmorders/5/items/nos (replication to r3*?).
  Q3 PROC    — is there a creation stored procedure the client calls, or bare DML?
  Q4 EXAMPLE — a full real order across every table = the golden template to mimic.

Output → docs/architecture/softech_crm_order_investigation.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__),
    '..', '..', '..', '..', 'docs', 'architecture',
    'softech_crm_order_investigation.txt',
)

# Tables central to CRM pending-order creation
CRM_TABLES = [
    'piccrmorders', 'piccrmorders5', 'piccrmitems',
    'piccrmordersnos', 'r3piccrmordersnos',
    'piccrmorderstatus', 'piccrmorderdel', 'piccrmorderstrans',
    'lastdocnumbers', 'picdoctors',
]

# syscolumns.status & 8 == 8  → column is NULLable (Sybase ASE)
NULLABLE_BIT = 8


class Command(BaseCommand):
    help = 'READ-ONLY reverse-engineering of SOFTECH CRM pending-order creation'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='test',
                            help="SOFTECH connection profile: test|prod|dev (default: test)")
        parser.add_argument('--branch', default='100',
                            help="crmbranchcode to sample the golden example from (default: 100 = call center)")

    def handle(self, *args, **options):
        from django.conf import settings
        from config.sybase import SoftechConnector

        profile = options['profile']
        crm_branch = str(options['branch'])
        lines = []

        def log(text=''):
            self.stdout.write(text)
            lines.append(text)

        def section(title):
            bar = '=' * 80
            log(''); log(bar); log(f'  {title}'); log(bar)

        # ── Profile / safety banner ───────────────────────────────────────────
        prefix = {'dev': 'SOFTECH_DEV_', 'test': 'SOFTECH_TEST_', 'prod': 'SOFTECH_PROD_'}.get(profile, 'SOFTECH_PROD_')
        configured_host = os.environ.get(f'{prefix}HOST')
        effective_host = configured_host or getattr(settings, 'SYBASE_HOST', '(unset)')
        log(f'CRM-order investigation started: {datetime.datetime.now().isoformat()}')
        log(f'Profile requested: {profile}  ({prefix}HOST={"set" if configured_host else "NOT set"})')
        log(f'Effective host: {effective_host}')
        if not configured_host:
            log(f'  ⚠️  {prefix}HOST is not configured — falling back to SYBASE_HOST. '
                f'If that is PRODUCTION, abort and set the test host first.')
        log('Mode: READ-ONLY (SELECT only — no writes will be issued)')

        try:
            conn = SoftechConnector(profile=profile).connect()
        except Exception as e:
            log(f'[FATAL] could not connect on profile={profile}: {e}')
            self._save(lines)
            return

        def run(label, sql, params=None):
            log(f'\n--- {label} ---')
            try:
                rows = conn.execute_query(sql, params)
                if not rows:
                    log('  (no rows)')
                else:
                    for r in rows:
                        log('  ' + ' | '.join('NULL' if c is None else str(c) for c in r))
                return rows
            except Exception as e:
                log(f'  [ERROR] {e}')
                return []

        def schema(tbl):
            log(f'\n  SCHEMA: {tbl}  (colid | name | type | len | NULL?)')
            try:
                rows = conn.execute_query(f"""
                    SELECT c.colid, c.name, t.name AS type, c.length, c.status
                    FROM   SOFTECHDB9.dbo.syscolumns c
                    JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                    JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                    WHERE  o.name = '{tbl}'
                    ORDER  BY c.colid
                """)
                if not rows:
                    log('    (table not found or no columns)')
                    return
                for r in rows:
                    nullable = 'NULL' if (int(r[4] or 0) & NULLABLE_BIT) else 'NOT NULL'
                    log(f'    [{str(r[0]):>3}] {str(r[1]):<28} {str(r[2]):<14} len={str(r[3]):<5} {nullable}')
            except Exception as e:
                log(f'    [ERROR] {e}')

        def obj_text(name, otype, label):
            log(f'\n{"-"*70}\n  {label}: {name}\n{"-"*70}')
            try:
                rows = conn.execute_query("""
                    SELECT sc.colid, sc.text
                    FROM   SOFTECHDB9.dbo.syscomments sc
                    JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
                    WHERE  o.name = ? AND o.type = ?
                    ORDER BY sc.colid
                """, [name, otype])
                if rows:
                    log(''.join(str(r[1]) for r in rows if r[1] is not None) or '  (text is NULL — ENCRYPTED)')
                else:
                    log('  (no text found — encrypted or not present)')
            except Exception as e:
                log(f'  [ERROR] {e}')

        # ── A: schemas (with nullability — drives the INSERT column list) ──────
        section('A: Table Schemas + Nullability (required INSERT columns)')
        for tbl in CRM_TABLES:
            schema(tbl)

        # ── B: column defaults (which columns the client may omit) ────────────
        section('B: Column DEFAULT bindings')
        for tbl in CRM_TABLES:
            run(f'{tbl} — columns with a bound default', f"""
                SELECT c.name, m.text
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects  o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.syscomments m ON c.cdefault = m.id
                WHERE  o.name = '{tbl}' AND c.cdefault > 0
                ORDER BY c.colid
            """)

        # ── C: triggers attached to each CRM table (instrig/updtrig/deltrig) ──
        section('C: Triggers Bound to CRM Tables')
        trig_names = set()
        for tbl in CRM_TABLES:
            rows = run(f'{tbl} — bound triggers', f"""
                SELECT o.name AS tbl,
                       t1.name AS insert_trigger,
                       t2.name AS update_trigger,
                       t3.name AS delete_trigger
                FROM   SOFTECHDB9.dbo.sysobjects o
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t1 ON t1.id = o.instrig
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t2 ON t2.id = o.updtrig
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t3 ON t3.id = o.deltrig
                WHERE  o.name = '{tbl}'
            """)
            for r in rows:
                for tn in (r[1], r[2], r[3]):
                    if tn and str(tn) not in ('None', 'NULL'):
                        trig_names.add(str(tn))

        run('All triggers whose text mentions a CRM-order table', """
            SELECT DISTINCT o.name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'TR'
              AND (LOWER(sc.text) LIKE '%piccrmorders%'
                OR LOWER(sc.text) LIKE '%crmorderno%')
            ORDER BY o.name
        """)

        # ── D: stored procedures that create / number CRM orders ──────────────
        section('D: Stored Procedures Referencing CRM Orders / crmorderno')
        proc_rows = run('Procs mentioning piccrmorders or crmorderno', """
            SELECT DISTINCT o.name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND (LOWER(sc.text) LIKE '%piccrmorders%'
                OR LOWER(sc.text) LIKE '%crmorderno%')
            ORDER BY o.name
        """)
        run('Procs that INSERT into a piccrmorders* table', """
            SELECT DISTINCT o.name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND  LOWER(sc.text) LIKE '%insert%piccrmorders%'
            ORDER BY o.name
        """)
        run('Procs mentioning lastdocnumbers (doc-number allocation)', """
            SELECT DISTINCT o.name
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type = 'P'
              AND  LOWER(sc.text) LIKE '%lastdocnumbers%'
            ORDER BY o.name
        """)

        # ── E: SERIAL ALLOCATION — the #1 question ────────────────────────────
        section('E: crmorderno Serial Allocation Evidence')
        run('lastdocnumbers — full contents (small ref table)', """
            SELECT * FROM SOFTECHDB9.dbo.lastdocnumbers
        """)
        run('piccrmordersnos — 20 most recent registry rows', """
            SELECT TOP 20 crmbranchcode, crmorderno, branchcode, snoflag, docnumber, docdate, trans_time
            FROM SOFTECHDB9.dbo.piccrmordersnos
            ORDER BY trans_time DESC
        """)
        run('piccrmordersnos — distinct snoflag values', """
            SELECT snoflag, COUNT(*) AS n
            FROM SOFTECHDB9.dbo.piccrmordersnos
            GROUP BY snoflag
        """)
        run('Max crmorderno per crmbranchcode (header table)', """
            SELECT crmbranchcode, MAX(crmorderno) AS max_no, COUNT(*) AS n
            FROM SOFTECHDB9.dbo.piccrmorders
            GROUP BY crmbranchcode
        """)
        run('Max crmorderno per crmbranchcode (registry table)', """
            SELECT crmbranchcode, MAX(crmorderno) AS max_no, COUNT(*) AS n
            FROM SOFTECHDB9.dbo.piccrmordersnos
            GROUP BY crmbranchcode
        """)

        # ── F: GOLDEN EXAMPLE — one real order across every table ──────────────
        section(f'F: Golden Example — newest real order (crmbranchcode={crm_branch})')
        newest = run('Newest header row', f"""
            SELECT TOP 1 crmbranchcode, crmorderno, branchcode, doccode,
                   docnumber5, docdate5, docnumber, docdate,
                   orderdatetime, orderusercode, ordervalue, phcode, orderstatus
            FROM SOFTECHDB9.dbo.piccrmorders
            WHERE crmbranchcode = '{crm_branch}'
            ORDER BY orderdatetime DESC
        """)
        if newest:
            ex_branch = str(newest[0][0]).strip()
            ex_no = newest[0][1]
            log(f'\n  >>> Tracing crmbranchcode={ex_branch} crmorderno={ex_no} across all tables <<<')
            run('Full header (piccrmorders)', f"""
                SELECT * FROM SOFTECHDB9.dbo.piccrmorders
                WHERE crmbranchcode = '{ex_branch}' AND crmorderno = {ex_no}
            """)
            run('Same order in live queue? (piccrmorders5)', f"""
                SELECT * FROM SOFTECHDB9.dbo.piccrmorders5
                WHERE crmbranchcode = '{ex_branch}' AND crmorderno = {ex_no}
            """)
            run('Line items (piccrmitems)', f"""
                SELECT * FROM SOFTECHDB9.dbo.piccrmitems
                WHERE crmorderno = {ex_no}
                ORDER BY trans_time
            """)
            run('Status history (piccrmorderstatus)', f"""
                SELECT * FROM SOFTECHDB9.dbo.piccrmorderstatus
                WHERE crmbranchcode = '{ex_branch}' AND crmorderno = {ex_no}
                ORDER BY trans_time
            """)
            run('Serial registry row (piccrmordersnos)', f"""
                SELECT * FROM SOFTECHDB9.dbo.piccrmordersnos
                WHERE crmbranchcode = '{ex_branch}' AND crmorderno = {ex_no}
            """)

        # ── G: referral doctor (picdoctors) ───────────────────────────────────
        section('G: Referral Doctor (picdoctors) sample')
        run('picdoctors — 10 sample rows', """
            SELECT TOP 10 * FROM SOFTECHDB9.dbo.picdoctors
        """)

        # ── H: full text of relevant procs + triggers ─────────────────────────
        section('H: Full Text — CRM Order Procedures')
        for r in proc_rows:
            obj_text(str(r[0]), 'P', 'PROCEDURE')

        section('I: Full Text — Triggers Bound to CRM Tables')
        for tn in sorted(trig_names):
            obj_text(tn, 'TR', 'TRIGGER')

        # ── J: encryption check ────────────────────────────────────────────────
        section('J: Encrypted Objects Touching CRM Orders')
        run('Encrypted procs/triggers mentioning crmorderno/piccrmorders', """
            SELECT DISTINCT o.name, o.type
            FROM   SOFTECHDB9.dbo.sysobjects o
            JOIN   SOFTECHDB9.dbo.syscomments sc ON sc.id = o.id
            WHERE  o.type IN ('P', 'TR')
              AND  (o.sysstat & 0x2000) = 0x2000
              AND  (LOWER(sc.text) LIKE '%piccrmorders%' OR LOWER(sc.text) LIKE '%crmorderno%')
            ORDER BY o.name
        """)

        conn.close()
        log(f'\nComplete: {datetime.datetime.now().isoformat()}')
        self._save(lines)

    def _save(self, lines):
        path = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            self.stdout.write(self.style.SUCCESS(f'\nSaved → {path}'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'\nCould not save: {e}'))
