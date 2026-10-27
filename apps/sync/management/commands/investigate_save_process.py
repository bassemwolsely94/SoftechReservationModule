"""
python manage.py investigate_save_process [--profile prod]

READ-ONLY deep dig into the FULL SOFTECH "Save" process for an indirect-POS sale:
every trigger that fires and every stored procedure involved when an order +
payment is committed, plus the item-derived POINTS source.

The hypothesis (from prior findings): SOFTECH commits a sale via client-side bare
DML whose side-effects are produced by a CHAIN OF TRIGGERS on:
  stktransm5 / stktrans5            (pending order header + lines)
  branchesales5                     (payment split)
  stkbal                            (stock balance + weighted-avg cost)
  picpoints / localcustomers /
  localcustomerspoints              (loyalty points)
  lastdocnumbers                    (serial counters)
This probe dumps the bound triggers + their full text, the procedures that
reference each table, and finds the item->points table.

ABSOLUTE RULE: SELECT only.  Output -> docs/architecture/softech_save_process_investigation.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'architecture',
    'softech_save_process_investigation.txt',
)

# The full sale-commit chain (pending + final + side-effect tables)
CHAIN_TABLES = [
    'stktransm5', 'stktrans5', 'branchesales5',
    'stktransm', 'stktrans', 'branchesales',
    'stkbal', 'stkbalexpiry',
    'picpoints', 'localcustomers', 'localcustomerspoints', 'lcpointstrans',
    'lastdocnumbers',
]


class Command(BaseCommand):
    help = 'READ-ONLY dump of the SOFTECH sale Save process (triggers + procs + points)'

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

        def obj_text(name, otype, label):
            log(f'\n{"-"*72}\n  {label}: {name}\n{"-"*72}')
            rows = q("""
                SELECT sc.text FROM SOFTECHDB9.dbo.syscomments sc
                JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id=o.id
                WHERE o.name=? AND o.type=? ORDER BY sc.colid
            """, [name, otype])
            body = ''.join(str(r[0]) for r in rows if r[0] is not None)
            log(body if body.strip() else '  (no text — ENCRYPTED or absent)')

        log(f'Save-process investigation: {datetime.datetime.now().isoformat()}')
        log('Mode: READ-ONLY')

        # ── A: triggers bound to each chain table ─────────────────────────────
        section('A: Triggers bound to the sale-commit chain tables')
        trig_names = []
        for tbl in CHAIN_TABLES:
            rows = q("""
                SELECT o.name, t1.name, t2.name, t3.name
                FROM SOFTECHDB9.dbo.sysobjects o
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t1 ON t1.id=o.instrig
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t2 ON t2.id=o.updtrig
                LEFT JOIN SOFTECHDB9.dbo.sysobjects t3 ON t3.id=o.deltrig
                WHERE o.name=?
            """, [tbl])
            for r in rows:
                ins, upd, dele = (str(x) if x and str(x) not in ('None','NULL') else '' for x in (r[1], r[2], r[3]))
                log(f'  {tbl:<22} INS={ins or "-":<28} UPD={upd or "-":<28} DEL={dele or "-"}')
                for tn in (ins, upd, dele):
                    if tn and tn not in trig_names:
                        trig_names.append(tn)

        # ── B: ALL triggers whose TEXT references a chain table (catches extras) ─
        section('B: Any trigger whose text references a chain table')
        like = ' OR '.join(f"LOWER(sc.text) LIKE '%{t}%'" for t in
                           ('stktrans5','branchesales5','picpoints','stkbal','lastdocnumber'))
        for r in q(f"""
            SELECT DISTINCT o.name FROM SOFTECHDB9.dbo.syscomments sc
            JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id=o.id
            WHERE o.type='TR' AND ({like}) ORDER BY o.name
        """):
            nm = str(r[0])
            log(f'  {nm}')
            if nm not in trig_names:
                trig_names.append(nm)

        # ── C: item -> POINTS source table(s) ─────────────────────────────────
        section('C: Item-derived POINTS source')
        log('\n  Tables with a points-ish name:')
        for r in q("""
            SELECT o.name FROM SOFTECHDB9.dbo.sysobjects o
            WHERE o.type='U' AND (LOWER(o.name) LIKE '%point%' OR LOWER(o.name) LIKE '%nokat%')
            ORDER BY o.name
        """):
            log(f'    - {r[0]}')
        log('\n  Columns with a points-ish name (table.column):')
        for r in q("""
            SELECT o.name, c.name FROM SOFTECHDB9.dbo.syscolumns c
            JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id
            WHERE o.type='U' AND (LOWER(c.name) LIKE '%point%')
            ORDER BY o.name, c.name
        """):
            log(f'    - {r[0]}.{r[1]}')

        # items points-config columns + a sample
        section('C2: items points columns (sample)')
        for r in q("""
            SELECT c.name, t.name, c.length FROM SOFTECHDB9.dbo.syscolumns c
            JOIN SOFTECHDB9.dbo.sysobjects o ON c.id=o.id
            JOIN SOFTECHDB9.dbo.systypes t ON c.usertype=t.usertype
            WHERE o.name='items' AND LOWER(c.name) LIKE '%point%' ORDER BY c.colid
        """):
            log(f'  items.{r[0]:<22} {r[1]} len={r[2]}')

        # ── D: procedures referencing the chain / points ──────────────────────
        section('D: Procedures referencing chain/points tables')
        proc_names = []
        plike = ' OR '.join(f"LOWER(sc.text) LIKE '%{t}%'" for t in
                            ('stktransm5','stktrans5','branchesales5','picpoints','itempoints'))
        for r in q(f"""
            SELECT DISTINCT o.name FROM SOFTECHDB9.dbo.syscomments sc
            JOIN SOFTECHDB9.dbo.sysobjects o ON sc.id=o.id
            WHERE o.type='P' AND ({plike}) ORDER BY o.name
        """):
            log(f'  {r[0]}')
            proc_names.append(str(r[0]))

        # ── E: full text of every trigger in the chain ────────────────────────
        section('E: FULL TEXT — chain triggers')
        for tn in trig_names:
            obj_text(tn, 'TR', 'TRIGGER')

        # ── F: full text of referencing procedures ────────────────────────────
        section('F: FULL TEXT — referencing procedures')
        for pn in proc_names:
            obj_text(pn, 'P', 'PROCEDURE')

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
