"""
python manage.py investigate_purchase_draft3 [--profile prod]

READ-ONLY: find which header table holds the "Temporarily Save On-Screen Data"
purchase draft (supplier doc no 1124578, total 371.25, items 404 & 2138).
Candidates (have a docnumber2 column or match the "Import From Receival" hint):
  stktransm_prep, stktransm_q, stktransm9, stktransm_hq, stktransmres,
  imports, importsm, itemsimports, itemsimportsm

For each: row count, search docnumber2=1124578, and a recent sample. Then dump the
full winning row + locate + dump its line twin.

ABSOLUTE RULE: SELECT only.
Output -> docs/architecture/softech_purchase_draft_investigation3.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'architecture',
    'softech_purchase_draft_investigation3.txt',
)
HEADER_CANDIDATES = ['stktransm_prep', 'stktransm_q', 'stktransm9', 'stktransm_hq',
                     'stktransmres', 'importsm', 'imports', 'itemsimportsm', 'itemsimports']


class Command(BaseCommand):
    help = 'READ-ONLY: locate the purchase draft header table'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod')

    def handle(self, *args, **options):
        from config.sybase import SoftechConnector
        lines = []

        def log(t=''):
            self.stdout.write(t); lines.append(t)

        def section(title):
            log(''); log('=' * 80); log(f'  {title}'); log('=' * 80)

        log(f'Purchase-draft hunt #3: {datetime.datetime.now().isoformat()}  (READ-ONLY)')
        try:
            conn = SoftechConnector(profile=options['profile']).connect()
        except Exception as e:
            log(f'[FATAL] connect: {e}'); self._save(lines); return

        def set_rowcount(n):
            try:
                conn._cursor().execute(f'SET ROWCOUNT {n}')
            except Exception:
                pass

        def cols_of(tbl):
            try:
                cur = conn._cursor()
                cur.execute(f"""
                    SELECT c.name FROM SOFTECHDB9.dbo.syscolumns c
                    JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id
                    WHERE o.name='{tbl}' ORDER BY c.colid
                """)
                return [str(r[0]).strip() for r in cur.fetchall()]
            except Exception:
                return []

        def run(label, sql, params=None):
            log(f'\n--- {label} ---')
            try:
                cur = conn._cursor(); cur.execute(sql, params)
                desc = [d[0] for d in cur.description]; rows = cur.fetchall()
                if not rows:
                    log('  (no rows)'); return []
                log('  COLS: ' + ' | '.join(desc))
                for r in rows:
                    log('  ' + ' | '.join('NULL' if c is None else str(c) for c in r))
                return rows
            except Exception as e:
                log(f'  [ERROR] {e}'); return []

        def vrow(label, sql):
            log(f'\n--- {label} (vertical) ---')
            set_rowcount(1)
            try:
                cur = conn._cursor(); cur.execute(sql)
                desc = [d[0] for d in cur.description]; row = cur.fetchone()
                if not row:
                    log('  (no rows)'); return None
                for n, v in zip(desc, row):
                    log(f'    {n:<28} = {"NULL" if v is None else v}')
                return dict(zip(desc, row))
            except Exception as e:
                log(f'  [ERROR] {e}'); return None
            finally:
                set_rowcount(0)

        winner = None
        section('1: scan candidate header tables for the draft (docnumber2=1124578)')
        for tbl in HEADER_CANDIDATES:
            cols = cols_of(tbl)
            if not cols:
                log(f'\n  {tbl}: (not found)'); continue
            log(f'\n  {tbl}: cols={len(cols)}  has docnumber2={"docnumber2" in cols}  has docvalue={"docvalue" in cols}')
            run(f'{tbl} COUNT(*)', f"SELECT COUNT(*) AS cnt FROM SOFTECHDB9.dbo.{tbl}")
            if 'docnumber2' in cols:
                hits = run(f'{tbl} WHERE docnumber2=1124578',
                           f"SELECT * FROM SOFTECHDB9.dbo.{tbl} WHERE docnumber2=1124578")
                if hits:
                    winner = tbl
            elif 'docvalue' in cols:
                run(f'{tbl} WHERE docvalue=371.25',
                    f"SELECT * FROM SOFTECHDB9.dbo.{tbl} WHERE docvalue=371.25")

        # ── 2. full dump of the winning draft header + its line twin ──────────
        if winner:
            section(f'2: WINNER = {winner} — full draft header + line twin')
            hdr = vrow(f'{winner} full draft row',
                       f"SELECT * FROM SOFTECHDB9.dbo.{winner} WHERE docnumber2=1124578")
            # guess the line-twin name
            base = winner.replace('transm', 'trans')   # stktransm_prep -> stktrans_prep, importsm -> imports? (handled below)
            twins = []
            if winner == 'importsm':
                twins = ['imports']
            elif winner == 'itemsimportsm':
                twins = ['itemsimports']
            else:
                twins = [base]
            if hdr:
                for tw in twins:
                    if not cols_of(tw):
                        log(f'\n  line twin {tw}: (not found)'); continue
                    run(f'{tw} lines for the draft', f"""
                        SELECT * FROM SOFTECHDB9.dbo.{tw}
                        WHERE branchcode=? AND docnumber=?
                    """, [str(hdr.get('branchcode')).strip(), hdr.get('docnumber')])
        else:
            section('2: NOT FOUND in any candidate — draft may be client-side/local')
            log('  The draft was not located in any server table searched.')

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
