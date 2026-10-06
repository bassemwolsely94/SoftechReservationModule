"""
python manage.py investigate_purchase_invoice2 [--profile prod] [--branch-host IP]

READ-ONLY follow-up probe — captures the supplier-PURCHASE golden template (the
finalized stktransm/stktrans doccode-10 row VALUES the native purchasing screen
sets) with date-bounded queries (no full-table sort → no timeout), plus:
  - doccode distribution in the stktransm5 VARIANTS (_revise/_ext/_ot) to see if
    purchase drafts live in a variant rather than the base staging twin;
  - supplier sub-type distribution (personsdata ptcode='20' ptclassifcode);
  - optional branch-server probe (purchase staging is suspected to live at the
    branch ASE, since HQ stktransm5 holds no doccode 10/120).

ABSOLUTE RULE: SELECT only.
Output -> docs/architecture/softech_purchase_invoice_investigation2.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'architecture',
    'softech_purchase_invoice_investigation2.txt',
)


class Command(BaseCommand):
    help = 'READ-ONLY supplier-purchase golden template + staging-variant probe'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod')
        parser.add_argument('--branch-host', default='')
        parser.add_argument('--branch-port', type=int, default=5000)
        parser.add_argument('--branch-db', default='SOFTECHDB9')

    def handle(self, *args, **options):
        from config.sybase import SoftechConnector, get_branch_connection
        lines = []

        def log(t=''):
            self.stdout.write(t); lines.append(t)

        def section(title):
            log(''); log('=' * 80); log(f'  {title}'); log('=' * 80)

        log(f'Purchase golden-template probe: {datetime.datetime.now().isoformat()}')
        log('Mode: READ-ONLY')

        try:
            conn = SoftechConnector(profile=options['profile']).connect()
        except Exception as e:
            log(f'[FATAL] connect: {e}'); self._save(lines); return

        def set_rowcount(n, c=None):
            try:
                (c or conn)._cursor().execute(f'SET ROWCOUNT {n}') if c is None \
                    else c.cursor().execute(f'SET ROWCOUNT {n}')
            except Exception as e:
                log(f'  [ERROR rowcount] {e}')

        def vrow(label, sql, params=None):
            log(f'\n--- {label} (one row vertical) ---')
            set_rowcount(1)
            try:
                cur = conn._cursor(); cur.execute(sql, params)
                cols = [d[0] for d in cur.description]; row = cur.fetchone()
                if not row:
                    log('  (no rows)'); return None
                for n, v in zip(cols, row):
                    log(f'    {n:<28} = {"NULL" if v is None else v}')
                return dict(zip(cols, row))
            except Exception as e:
                log(f'  [ERROR] {e}'); return None
            finally:
                set_rowcount(0)

        def run(label, sql, params=None):
            log(f'\n--- {label} ---')
            try:
                cur = conn._cursor(); cur.execute(sql, params)
                cols = [d[0] for d in cur.description]; rows = cur.fetchall()
                if not rows:
                    log('  (no rows)'); return []
                log('  COLS: ' + ' | '.join(cols))
                for r in rows:
                    log('  ' + ' | '.join('NULL' if c is None else str(c) for c in r))
                return rows
            except Exception as e:
                log(f'  [ERROR] {e}'); return []

        # ── 1. GOLDEN TEMPLATE — finalized purchase (doccode 10), date-bounded ─
        section('1: GOLDEN TEMPLATE — finalized supplier purchase (stktransm doccode 10)')
        # No ORDER BY (avoids a full sort → timeout); ROWCOUNT 1 + recent date = fast.
        hdr = vrow('stktransm doccode=10 (a recent finalized purchase header)', """
            SELECT * FROM SOFTECHDB9.dbo.stktransm
            WHERE doccode='10' AND docdate >= DATEADD(day, -3, GETDATE())
        """)
        if hdr:
            run('its stktrans lines (all columns)', """
                SELECT * FROM SOFTECHDB9.dbo.stktrans
                WHERE branchcode=? AND doccode='10' AND docnumber=?
            """, [str(hdr.get('branchcode')).strip(), hdr.get('docnumber')])
            # is this purchase paid via branchesales (supplier tender) or pure account credit?
            run('any branchesales rows for this purchase doc?', """
                SELECT paymenttype, paymentvalue, ref_docnumber FROM SOFTECHDB9.dbo.branchesales
                WHERE branchcode=? AND doccode='10' AND docnumber=?
            """, [str(hdr.get('branchcode')).strip(), hdr.get('docnumber')])

        # ── 2. Do purchase DRAFTS live in a stktransm5 variant? ───────────────
        section('2: doccode distribution in stktransm5 VARIANTS (purchase-draft hunt)')
        for tbl in ('stktransm5_revise', 'stktransm5_ext', 'stktransm5_ot', 'dm_stktransm5'):
            run(f'{tbl} doccode counts', f"""
                SELECT doccode, COUNT(*) AS cnt FROM SOFTECHDB9.dbo.{tbl}
                GROUP BY doccode ORDER BY doccode
            """)

        # ── 3. Supplier sub-types (personsdata ptcode='20') ───────────────────
        section('3: supplier sub-types — personsdata ptcode=20 ptclassifcode distribution')
        run('ptclassifcode distribution for suppliers', """
            SELECT ptclassifcode, COUNT(*) AS cnt FROM SOFTECHDB9.dbo.personsdata
            WHERE ptcode='20' GROUP BY ptclassifcode ORDER BY ptclassifcode
        """)
        run('sample supplier rows (ptcode=20)', """
            SELECT personcode, personname, ptcode, ptclassifcode
            FROM SOFTECHDB9.dbo.personsdata WHERE ptcode='20' AND personname IS NOT NULL
        """)

        # ── 4. optional branch probe (purchase staging suspected at branches) ─
        bh = options['branch_host']
        if bh:
            section(f'4: BRANCH {bh} — stktransm5 doccode distribution + *_supp counters')
            try:
                bconn = get_branch_connection(bh, options['branch_port'], options['branch_db'])
                c = bconn.cursor()
                c.execute("SELECT doccode, COUNT(*) AS cnt FROM stktransm5 GROUP BY doccode ORDER BY doccode")
                for r in c.fetchall():
                    log('  stktransm5: ' + ' | '.join('NULL' if x is None else str(x) for x in r))
                c2 = bconn.cursor()
                c2.execute("SELECT branchcode, ver_branch, lastdocnumberin_supp, lastdocnumberout_supp "
                           "FROM lastdocnumbers ORDER BY branchcode")
                for r in c2.fetchall():
                    log('  lastdocnumbers: ' + ' | '.join('NULL' if x is None else str(x) for x in r))
                bconn.close()
            except Exception as e:
                log(f'  [ERROR branch] {e}')

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
