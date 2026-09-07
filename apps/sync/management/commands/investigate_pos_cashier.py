"""
python manage.py investigate_pos_cashier [--profile prod] [--dump-samples]

READ-ONLY discovery of the SOFTECH **In-Direct Point of Sale -> Cashier** pathway.

Context (from live SOFTECH client screens):
  - "In-Direct Point of Sale" lets a seller build an order (cash / home-delivery /
    contract) and SEND it to a separate "SofTech Cashier" screen for payment.
    This is the pending-sales-order hand-off we must mimic (NOT a finalized
    stktrans/stktransm transaction, and broader than piccrmorders which is
    home-delivery only).
  - The serial of interest is "مسلسل صرف" (dispense serial) — the `م صرف`
    column in the Call Center Orders grid.

We do NOT yet know the table(s) those two screens read/write. This probe finds
candidates by name + column patterns, dumps their structure + a tiny sample, and
locates the procedures/triggers that drive the screens.

ABSOLUTE RULE: SELECT only. No writes are ever issued.

Output -> docs/architecture/softech_pos_cashier_investigation.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__),
    '..', '..', '..', '..', 'docs', 'architecture',
    'softech_pos_cashier_investigation.txt',
)

# Table-name patterns that plausibly back the indirect-POS / cashier / pending flow.
TABLE_NAME_PATTERNS = [
    '%trans5%', '%transm5%',          # the "5" staging variant pattern (cf. piccrmorders5)
    '%pos%', '%cashier%', '%cash%',
    '%sarf%', '%srf%', '%dispens%',
    '%pend%', '%hold%', '%queue%',
    '%indirect%', '%preinv%', '%pre_inv%', '%staging%',
    '%order%',
]

# Column-name patterns that likely encode the dispense serial / pending linkage.
COLUMN_NAME_PATTERNS = ['%sarf%', '%srf%', '%dispens%', 'docnumber5', '%posno%', '%cashno%']

# Patterns we auto-dump schema + sample for (high-confidence subset)
HIGH_PRIORITY = ('trans5', 'transm5', 'sarf', 'srf', 'cashier', 'pend', 'hold',
                 'indirect', 'preinv', 'staging', 'pos')

NULLABLE_BIT = 8


class Command(BaseCommand):
    help = 'READ-ONLY discovery of SOFTECH indirect-POS -> cashier tables'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod', help='SOFTECH profile (default: prod)')
        parser.add_argument('--dump-samples', action='store_true',
                            help='Also dump TOP 5 rows for high-priority candidates')

    def handle(self, *args, **options):
        from django.conf import settings
        from config.sybase import SoftechConnector

        profile = options['profile']
        dump_samples = options['dump_samples']
        lines = []

        def log(t=''):
            self.stdout.write(t)
            lines.append(t)

        def section(title):
            bar = '=' * 80
            log(''); log(bar); log(f'  {title}'); log(bar)

        log(f'POS/Cashier discovery started: {datetime.datetime.now().isoformat()}')
        log(f'Profile: {profile} | effective host: '
            f'{os.environ.get("SOFTECH_%s_HOST" % profile.upper()) or getattr(settings, "SYBASE_HOST", "?")}')
        log('Mode: READ-ONLY (SELECT only)')

        try:
            conn = SoftechConnector(profile=profile).connect()
        except Exception as e:
            log(f'[FATAL] connect failed: {e}')
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
                    log('    (not found)')
                    return
                for r in rows:
                    nullable = 'NULL' if (int(r[4] or 0) & NULLABLE_BIT) else 'NOT NULL'
                    log(f'    [{str(r[0]):>3}] {str(r[1]):<28} {str(r[2]):<14} len={str(r[3]):<5} {nullable}')
            except Exception as e:
                log(f'    [ERROR] {e}')

        # ── A: candidate tables by NAME pattern ───────────────────────────────
        section('A: Candidate Tables by NAME pattern')
        candidates = set()
        for pat in TABLE_NAME_PATTERNS:
            rows = run(f"name LIKE '{pat}'", f"""
                SELECT o.name
                FROM   SOFTECHDB9.dbo.sysobjects o
                WHERE  o.type = 'U' AND LOWER(o.name) LIKE '{pat}'
                ORDER  BY o.name
            """)
            for r in rows:
                candidates.add(str(r[0]).strip())

        # ── B: tables whose NAME ends in '5' (the staging-variant pattern) ────
        section("B: User tables ending in '5'")
        rows = run("name LIKE '%5'", """
            SELECT o.name
            FROM   SOFTECHDB9.dbo.sysobjects o
            WHERE  o.type = 'U' AND o.name LIKE '%5'
            ORDER  BY o.name
        """)
        for r in rows:
            candidates.add(str(r[0]).strip())

        # ── C: columns that look like a dispense serial / pending linkage ─────
        section('C: Columns matching dispense-serial / pending patterns')
        for pat in COLUMN_NAME_PATTERNS:
            rows = run(f"column LIKE '{pat}'", f"""
                SELECT o.name AS tbl, c.name AS col, t.name AS type
                FROM   SOFTECHDB9.dbo.syscolumns c
                JOIN   SOFTECHDB9.dbo.sysobjects o ON c.id = o.id
                JOIN   SOFTECHDB9.dbo.systypes   t ON c.usertype = t.usertype
                WHERE  o.type = 'U' AND LOWER(c.name) LIKE '{pat}'
                ORDER  BY o.name, c.name
            """)
            for r in rows:
                candidates.add(str(r[0]).strip())

        # ── D: procedures/triggers that look like the POS/cashier screen logic ─
        section('D: Procedures/triggers referencing likely screen logic')
        run('Procs/triggers mentioning "cashier"/"sarf"/"trans5"', """
            SELECT DISTINCT o.name, o.type
            FROM   SOFTECHDB9.dbo.syscomments sc
            JOIN   SOFTECHDB9.dbo.sysobjects  o ON sc.id = o.id
            WHERE  o.type IN ('P','TR')
              AND (LOWER(sc.text) LIKE '%cashier%'
                OR LOWER(sc.text) LIKE '%transm5%'
                OR LOWER(sc.text) LIKE '%trans5%'
                OR LOWER(sc.text) LIKE '%indirect%')
            ORDER BY o.name
        """)

        # ── E: schema (+ optional sample) for high-priority candidates ────────
        section('E: Structure of high-priority candidates')
        log(f'\n  All candidates discovered ({len(candidates)}):')
        for c in sorted(candidates):
            log(f'    - {c}')

        hp = sorted(c for c in candidates
                    if any(k in c.lower() for k in HIGH_PRIORITY))
        log(f'\n  High-priority subset ({len(hp)}):')
        for c in hp:
            log(f'    * {c}')

        for tbl in hp:
            schema(tbl)
            if dump_samples:
                run(f'{tbl} — TOP 5 sample', f"SELECT TOP 5 * FROM SOFTECHDB9.dbo.{tbl}")

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
