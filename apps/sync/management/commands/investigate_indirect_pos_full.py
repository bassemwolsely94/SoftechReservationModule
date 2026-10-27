"""
python manage.py investigate_indirect_pos_full [--profile prod]

READ-ONLY full census of the SOFTECH Indirect-POS -> Cashier subsystem: every
table, every bound trigger (with readable/hidden status + full body when readable),
and every related stored procedure (readable/encrypted), so the module can be
replicated exactly in our extended system.

ABSOLUTE RULE: SELECT only.
Output -> docs/architecture/softech_indirect_pos_full_census.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'architecture',
    'softech_indirect_pos_full_census.txt',
)

# The whole Indirect-POS domain — pending + final + side-effect + serial + channel
DOMAIN_TABLES = [
    # pending order (the indirect-POS Save target)
    'stktransm5', 'stktrans5', 'stktransmcomm5', 'stktransmclassif5',
    'stktransm5_ext', 'stktransm5_revise', 'stktransm5_ot', 'stktrans5_ot',
    # pending payment
    'branchesales5', 'branchesalescc5', 'branchesalesres',
    # final order + payment (cashier finalization target)
    'stktransm', 'stktrans', 'stktransmcomm', 'stktransmclassif',
    'branchesales', 'stktransm_inv',
    # stock / cost
    'stkbal', 'stkbalexpiry', 'itemstrans',
    # points
    'picpoints', 'localcustomers', 'localcustomerspoints', 'lcpointstrans',
    # serials / accounting / e-invoice
    'lastdocnumbers', 'lastdocnumbers_inv', 'lastdocnumberstt',
    'acctrans', 'acctrans3', 'sacctrans3',
    # home-delivery CRM path
    'piccrmorders', 'piccrmorders5', 'piccrmitems', 'piccrmorderstatus',
    'piccrmordersnos', 'piccrmorderstrans',
    # referral doctor
    'picdoctors', 'custrefdoctors',
]

# procedure-name keywords worth flagging even if encrypted (text unreadable)
PROC_NAME_KEYS = ('stk', 'sale', 'pos', 'order', 'cash', 'branchesale', 'point',
                  'acc', 'inv', 'fat', 'doc', 'pic', 'cust', 'pay')


class Command(BaseCommand):
    help = 'READ-ONLY full trigger/procedure census of the Indirect-POS subsystem'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod')

    def handle(self, *args, **options):
        from config.sybase import SoftechConnector
        lines = []

        def log(t=''):
            self.stdout.write(t); lines.append(t)

        def section(title):
            bar = '=' * 80
            log(''); log(bar); log(f'  {title}'); log(bar)

        try:
            conn = SoftechConnector(profile=options['profile']).connect()
        except Exception as e:
            log(f'[FATAL] connect: {e}'); self._save(lines); return

        def q(sql, params=None):
            try:
                return conn.execute_query(sql, params)
            except Exception as e:
                log(f'  [ERROR] {e}'); return []

        def body(name, otype):
            rows = q("""
                SELECT sc.text FROM SOFTECHDB9.dbo.syscomments sc
                JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id=o.id
                WHERE o.name=? AND o.type=? ORDER BY sc.colid
            """, [name, otype])
            return ''.join(str(r[0]) for r in rows if r[0] is not None)

        log(f'Indirect-POS full census: {datetime.datetime.now().isoformat()}')
        log('Mode: READ-ONLY (SELECT only)')

        # ── A: bound triggers per domain table (+ readable/hidden) ────────────
        section('A: Bound triggers per domain table')
        trig_set = {}   # name -> readable bool
        for tbl in DOMAIN_TABLES:
            rows = q("""
                SELECT t1.name, t2.name, t3.name
                FROM SOFTECHDB9.dbo.sysobjects o
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t1 ON t1.id=o.instrig
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t2 ON t2.id=o.updtrig
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t3 ON t3.id=o.deltrig
                WHERE o.name=?
            """, [tbl])
            if not rows:
                log(f'  {tbl:<22} (table not found)'); continue
            r = rows[0]
            cells = []
            for ev, tn in zip(('INS','UPD','DEL'), r):
                tn = str(tn) if tn and str(tn) not in ('None','NULL') else ''
                if tn:
                    if tn not in trig_set:
                        trig_set[tn] = bool(body(tn, 'TR').strip())
                    cells.append(f'{ev}={tn}{"" if trig_set[tn] else " [HIDDEN]"}')
            log(f'  {tbl:<22} {"  ".join(cells) if cells else "(no triggers)"}')

        # ── B: any trigger whose text references a domain table ────────────────
        section('B: Other triggers referencing domain tables (text scan)')
        keys = ('stktrans5','stktransm5','branchesales5','stktransm_inv','picpoints',
                'piccrmorders','lastdocnumber','stkbal')
        like = ' OR '.join(f"LOWER(sc.text) LIKE '%{k}%'" for k in keys)
        for r in q(f"""
            SELECT DISTINCT o.name FROM SOFTECHDB9.dbo.syscomments sc
            JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id=o.id
            WHERE o.type='TR' AND ({like}) ORDER BY o.name
        """):
            nm = str(r[0])
            if nm not in trig_set:
                trig_set[nm] = bool(body(nm, 'TR').strip())
            log(f'  {nm}{"" if trig_set[nm] else " [HIDDEN]"}')

        # ── C: full text of every READABLE domain trigger ─────────────────────
        section('C: FULL TEXT — readable domain triggers')
        for nm in sorted(trig_set):
            if trig_set[nm]:
                log(f'\n{"-"*72}\n  TRIGGER: {nm}\n{"-"*72}')
                log(body(nm, 'TR'))
        section('C2: HIDDEN (vendor-protected) domain triggers')
        for nm in sorted(trig_set):
            if not trig_set[nm]:
                log(f'  {nm}')

        # ── D: stored procedures — readable/encrypted census ──────────────────
        section('D: Stored procedures referencing domain tables (readable bodies)')
        plike = ' OR '.join(f"LOWER(sc.text) LIKE '%{k}%'" for k in
                            ('stktransm5','stktrans5','branchesales5','stktransm_inv',
                             'piccrmorders','picpoints'))
        proc_hits = [str(r[0]) for r in q(f"""
            SELECT DISTINCT o.name FROM SOFTECHDB9.dbo.syscomments sc
            JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id=o.id
            WHERE o.type='P' AND ({plike}) ORDER BY o.name
        """)]
        if not proc_hits:
            log('  (no readable procedure references these tables — confirms bare-DML pattern)')
        for pn in proc_hits:
            log(f'\n{"-"*72}\n  PROCEDURE: {pn}\n{"-"*72}')
            log(body(pn, 'P'))

        section('D2: ALL procedures with a domain-ish NAME (+ readable/encrypted)')
        nlike = ' OR '.join(f"LOWER(o.name) LIKE '%{k}%'" for k in PROC_NAME_KEYS)
        for r in q(f"""
            SELECT o.name FROM SOFTECHDB9.dbo.sysobjects o
            WHERE o.type='P' AND ({nlike}) ORDER BY o.name
        """):
            nm = str(r[0])
            log(f'  {nm:<46} {"readable" if body(nm,"P").strip() else "ENCRYPTED"}')

        # ── E: schemas of the 5-staging family (order Save companions) ─────────
        section('E: Schemas — 5-staging family (indirect-POS Save companions)')
        for tbl in ('stktransmcomm5', 'stktransmclassif5', 'stktransm5_ext',
                    'stktransm5_revise', 'branchesalescc5'):
            log(f'\n  SCHEMA: {tbl}')
            rows = q(f"""
                SELECT c.colid,c.name,t.name,c.length,c.status
                FROM SOFTECHDB9.dbo.syscolumns c
                JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id
                JOIN SOFTECHDB9.dbo.systypes t ON c.usertype=t.usertype
                WHERE o.name='{tbl}' ORDER BY c.colid
            """)
            if not rows:
                log('    (not found)')
            for r in rows:
                nn = 'NULL' if (int(r[4] or 0) & 8) else 'NOT NULL'
                log(f'    [{str(r[0]):>3}] {str(r[1]):<24} {str(r[2]):<12} len={str(r[3]):<5} {nn}')

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
