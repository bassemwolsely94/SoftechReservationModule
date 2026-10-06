"""
python manage.py investigate_purchase_draft [--profile prod]

READ-ONLY: locate the purchase DRAFT just created by the native "Temporarily Save
On-Screen Data" button (supplier PHARMA OVER SEAS, supplier-doc 1124578, total
371.25) and capture the exact PENDING golden template — the surface-A target.

Checks:
  1. lastdocnumbers['000'] *_supp counters (did lastdocnumberin_supp advance from 0?)
  2. stktransm5 doccode=10 rows (the draft header) — full vertical dump
  3. stktrans5 lines for it
  4. by docnumber2=1124578 (the supplier invoice no) as a cross-check

ABSOLUTE RULE: SELECT only.
Output -> docs/architecture/softech_purchase_draft_investigation.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'architecture',
    'softech_purchase_draft_investigation.txt',
)


class Command(BaseCommand):
    help = 'READ-ONLY capture of a saved purchase DRAFT in stktransm5 (doccode 10)'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod')

    def handle(self, *args, **options):
        from config.sybase import SoftechConnector
        lines = []

        def log(t=''):
            self.stdout.write(t); lines.append(t)

        def section(title):
            log(''); log('=' * 80); log(f'  {title}'); log('=' * 80)

        log(f'Purchase-draft probe: {datetime.datetime.now().isoformat()}  (READ-ONLY)')
        try:
            conn = SoftechConnector(profile=options['profile']).connect()
        except Exception as e:
            log(f'[FATAL] connect: {e}'); self._save(lines); return

        def set_rowcount(n):
            try:
                conn._cursor().execute(f'SET ROWCOUNT {n}')
            except Exception as e:
                log(f'  [ERROR rowcount] {e}')

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

        def vrow(label, sql, params=None):
            log(f'\n--- {label} (vertical) ---')
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

        section('1: lastdocnumbers *_supp counters (did the draft bump in_supp?)')
        run('lastdocnumbers all rows', """
            SELECT branchcode, ver_branch, lastdocnumberin_supp, lastdocnumberout_supp
            FROM SOFTECHDB9.dbo.lastdocnumbers ORDER BY branchcode
        """)

        section('2: stktransm5 doccode=10 (the saved draft header)')
        run('stktransm5 doccode=10 — key cols', """
            SELECT branchcode, doccode, docnumber, docnumber2, docvalue, cust_branch_code,
                   ptcode, ptclassifcode, supp_main_code, usercode, trans_time, docdate
            FROM SOFTECHDB9.dbo.stktransm5 WHERE doccode='10'
        """)
        hdr = vrow('stktransm5 doccode=10 — FULL header (golden draft template)', """
            SELECT * FROM SOFTECHDB9.dbo.stktransm5 WHERE doccode='10'
        """)

        section('3: stktrans5 lines for the draft')
        if hdr:
            run('stktrans5 lines (all cols)', """
                SELECT * FROM SOFTECHDB9.dbo.stktrans5
                WHERE branchcode=? AND doccode='10' AND docnumber=?
            """, [str(hdr.get('branchcode')).strip(), hdr.get('docnumber')])

        section('4: cross-check by supplier doc no docnumber2=1124578')
        run('stktransm5 where docnumber2=1124578', """
            SELECT branchcode, doccode, docnumber, docnumber2, docvalue
            FROM SOFTECHDB9.dbo.stktransm5 WHERE docnumber2=1124578
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
            self.stdout.write(self.style.SUCCESS(f'\nSaved -> {path}'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'\nCould not save: {e}'))
