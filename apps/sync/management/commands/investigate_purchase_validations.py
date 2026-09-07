"""
python manage.py investigate_purchase_validations [--profile prod]

READ-ONLY discovery of the data validations SofTech enforces when saving a supplier
purchase/return — so our module can replicate them. Sources:
  1. items master  — purchase/price/block flags (item allowed to buy, max price, public price…)
  2. personsdata   — supplier credit balance + limit + blocked
  3. cfarmasetup   — the config/setup table toggling validations (client read cfsetupcode=2010)
  4. itemssuppliers— allowed supplier(s) per item
  5. procs/triggers referencing credit/price/purchase validation

Output -> docs/architecture/softech_purchase_validations.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..',
                           'docs', 'architecture', 'softech_purchase_validations.txt')
NULLABLE_BIT = 8


class Command(BaseCommand):
    help = 'READ-ONLY discovery of SofTech purchase-save data validations'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod')

    def handle(self, *args, **o):
        from config.sybase import SoftechConnector
        lines = []

        def log(t=''):
            self.stdout.write(t); lines.append(t)

        def section(t):
            log(''); log('=' * 80); log(f'  {t}'); log('=' * 80)

        log(f'Purchase-validation discovery: {datetime.datetime.now().isoformat()} (READ-ONLY)')
        conn = SoftechConnector(profile=o['profile']).connect()

        def rc(n):
            try:
                conn._cursor().execute(f'SET ROWCOUNT {n}')
            except Exception:
                pass

        def run(label, sql, params=None):
            log(f'\n--- {label} ---')
            try:
                cur = conn._cursor(); cur.execute(sql, params)
                cols = [d[0] for d in cur.description]; rows = cur.fetchall()
                if not rows:
                    log('  (no rows)'); return []
                log('  ' + ' | '.join(cols))
                for r in rows:
                    log('  ' + ' | '.join('NULL' if c is None else str(c) for c in r))
                return rows
            except Exception as e:
                log(f'  [ERROR] {e}'); return []

        def schema(tbl, like=None):
            log(f'\n  SCHEMA {tbl}' + (f' (cols LIKE {like})' if like else ''))
            try:
                cur = conn._cursor()
                cond = f" AND LOWER(c.name) LIKE '{like}'" if like else ''
                cur.execute(f"""
                    SELECT c.name, t.name, c.length, c.status
                    FROM SOFTECHDB9.dbo.syscolumns c
                    JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id
                    JOIN SOFTECHDB9.dbo.systypes t ON c.usertype=t.usertype
                    WHERE o.name='{tbl}'{cond} ORDER BY c.colid""")
                for r in cur.fetchall():
                    nn = 'NULL' if (int(r[3] or 0) & NULLABLE_BIT) else 'NOT NULL'
                    log(f'    {str(r[0]):<28} {str(r[1]):<12} len={str(r[2]):<5} {nn}')
            except Exception as e:
                log(f'    [ERROR] {e}')

        # ── 1. items master — purchase/price/block relevant columns ───────────
        section('1: items master — purchase/price/block/allow columns')
        for like in ('%buy%', '%purch%', '%cost%', '%price%', '%block%', '%nomore%',
                     '%archive%', '%allow%', '%max%', '%min%', '%tax%', '%expiry%', '%nosale%'):
            schema('items', like)

        # ── 2. personsdata (supplier) — credit/limit/block ────────────────────
        section('2: personsdata (supplier) — credit / limit / blocked columns')
        for like in ('%credit%', '%limit%', '%block%', '%debit%', '%balance%', '%max%', '%pt%'):
            schema('personsdata', like)

        # ── 3. cfarmasetup — the config/validation toggle table ───────────────
        section('3: cfarmasetup — config/setup rows (validation toggles)')
        schema('cfarmasetup')
        rc(0)
        run('cfarmasetup ALL rows', "SELECT * FROM SOFTECHDB9.dbo.cfarmasetup ORDER BY cfsetupcode")

        # ── 4. itemssuppliers — allowed supplier(s) per item ──────────────────
        section('4: itemssuppliers — allowed supplier per item')
        schema('itemssuppliers')
        rc(3)
        run('itemssuppliers sample', "SELECT * FROM SOFTECHDB9.dbo.itemssuppliers")
        rc(0)

        # ── 5. validation procs/triggers ──────────────────────────────────────
        section('5: procs/triggers referencing credit / price / purchase validation')
        run('procs/triggers by name', """
            SELECT name, type FROM SOFTECHDB9.dbo.sysobjects
            WHERE type IN ('P','TR') AND (LOWER(name) LIKE '%valid%' OR LOWER(name) LIKE '%check%'
              OR LOWER(name) LIKE '%credit%' OR LOWER(name) LIKE '%purch%'
              OR LOWER(name) LIKE '%expiry%' OR LOWER(name) LIKE '%price%') ORDER BY name""")
        run('readable procs mentioning personcredit / creditlimit', """
            SELECT DISTINCT o.name, o.type FROM SOFTECHDB9.dbo.syscomments sc
            JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id=o.id
            WHERE o.type IN ('P','TR') AND (LOWER(sc.text) LIKE '%creditlimit%'
              OR LOWER(sc.text) LIKE '%personcredit%' OR LOWER(sc.text) LIKE '%credit limit%') ORDER BY o.name""")

        conn.close()
        log(f'\nComplete: {datetime.datetime.now().isoformat()}')
        path = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        self.stdout.write(self.style.SUCCESS(f'\nSaved -> {path}'))
