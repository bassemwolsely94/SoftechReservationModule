"""
python manage.py probe_sales_rate                       # HQ server, schema search + candidate dumps
python manage.py probe_sales_rate --host 192.168.1.8    # a specific branch/HQ node
python manage.py probe_sales_rate --item 12345          # + dump every stkbal/items value for one item
python manage.py probe_sales_rate --branch 130 --item 12345

READ-ONLY discovery probe for FEATURE 1 (معدلات البيع writeback).

Goal: locate the exact SOFTECH table + column that the «معدلات البيع» screen
edits — the per-branch sales rate, and the per-warehouse HQ rate — WITHOUT
guessing. It only SELECTs (schema catalog + sample rows); it never writes.

What it does:
  1. Scans syscolumns for columns whose NAME looks rate-ish (rate/avg/req/min/
     max/reorder/month/period/sale...) across all user tables → shortlist of
     "where could the rate live".
  2. Dumps the full column list of the prime candidate tables (stkbal, items,
     and any table the scan flags) so a rate column with a non-obvious name is
     still visible.
  3. With --item, dumps SELECT * for that itemcode from stkbal (per branch/store)
     and the items master row, so you can eyeball which column equals the number
     shown on the معدلات البيع screen for that item.

Run it against HQ (default) AND against a branch node (--host) — the rate may be
stored per-branch-server, and HQ warehouse rates may live only on the HQ server.
Cross-check the printed values against a screenshot of the same item on screen.
"""
from django.core.management.base import BaseCommand, CommandError

# Column-name fragments that commonly denote a sales-rate / reorder field in
# SOFTECH-style schemas. Case-insensitive LIKE patterns.
RATE_PATTERNS = [
    'rate', 'avg', 'aver', 'req', 'reorder', 'reord', 'order',
    'minqty', 'maxqty', 'min_qty', 'max_qty', 'monthly', 'month',
    'period', 'consum', 'demand', 'sale', 'sell', 'mean', 'daily',
]

# Tables we always dump column lists for, even if the name-scan misses them.
ALWAYS_DUMP = ['stkbal', 'items', 'itemsbranch', 'stkbalexpiry']


class Command(BaseCommand):
    help = 'READ-ONLY: locate the SOFTECH معدلات البيع (sales-rate) table/column (Feature 1 probe)'

    def add_arguments(self, parser):
        parser.add_argument('--host', default=None,
                            help='branch/HQ node db_host; omit to use the configured HQ (SYBASE_HOST)')
        parser.add_argument('--port', type=int, default=5000)
        parser.add_argument('--dbname', default='SOFTECHDB9')
        parser.add_argument('--item', default=None, help='itemcode to dump sample rows for')
        parser.add_argument('--branch', default=None, help='branchcode filter for the sample dump')
        parser.add_argument('--max-rows', type=int, default=40, dest='max_rows')
        parser.add_argument('--fingerprint', action='store_true',
                            help='reverse-engineer the native «تحديث معدل الإستهلاك» write from EXISTING '
                                 'monthlyqty values (no button-press needed): which (branch,store) hold '
                                 'rates + a raw sample incl. usercode_mq/trans_time_mq')
        parser.add_argument('--fp-limit', type=int, default=30, dest='fp_limit')

    # ── connection ────────────────────────────────────────────────────────────
    def handle(self, *args, **o):
        from config.sybase import get_sybase_connection, get_branch_connection

        host = o.get('host')
        if host:
            conn = get_branch_connection(host, o['port'], o['dbname'])
            self._pfx = ''          # branch node: unqualified table names
            where = f'branch node {host}:{o["port"]}/{o["dbname"]}'
        else:
            conn = get_sybase_connection()
            self._pfx = f'{o["dbname"]}.dbo.'   # HQ: qualify with DB
            where = f'HQ ({o["dbname"]}.dbo)'

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n═══ probe_sales_rate — READ-ONLY — {where} ═══\n'))
        try:
            if o.get('fingerprint'):
                self._fingerprint(conn, o.get('branch'), o['fp_limit'])
            else:
                self._scan_columns(conn)
                self._dump_candidate_tables(conn)
            if o.get('item'):
                self._dump_item(conn, o['item'], o.get('branch'), o['max_rows'])
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # ── helpers ───────────────────────────────────────────────────────────────
    def _q(self, conn, sql, params=None):
        cur = conn.cursor()
        try:
            cur.execute(sql, params or [])
            cols = [d[0] for d in cur.description] if cur.description else []
            return cols, cur.fetchall()
        finally:
            cur.close()

    # ── 1. name-based schema scan ──────────────────────────────────────────────
    def _scan_columns(self, conn):
        self.stdout.write(self.style.HTTP_INFO('■ Columns whose name looks rate/reorder-ish:'))
        like = ' OR '.join(f"lower(c.name) LIKE '%{p}%'" for p in RATE_PATTERNS)
        sql = (
            f"SELECT o.name AS tbl, c.name AS col, t.name AS typ, c.length "
            f"FROM {self._pfx}syscolumns c "
            f"JOIN {self._pfx}sysobjects o ON c.id = o.id "
            f"JOIN {self._pfx}systypes  t ON c.usertype = t.usertype "
            f"WHERE o.type = 'U' AND ({like}) "
            f"ORDER BY o.name, c.name"
        )
        try:
            _, rows = self._q(conn, sql)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  schema scan failed: {exc}'))
            return
        if not rows:
            self.stdout.write('  (none matched — the rate column has an unexpected name; '
                              'rely on the SELECT * dumps below)')
            return
        cur_tbl = None
        for tbl, col, typ, length in rows:
            tbl = str(tbl).strip()
            if tbl != cur_tbl:
                self.stdout.write(self.style.WARNING(f'  {tbl}'))
                cur_tbl = tbl
            self.stdout.write(f'      {str(col).strip():<28} {str(typ).strip()}({length})')

    # ── 2. full column list of candidate tables ────────────────────────────────
    def _dump_candidate_tables(self, conn):
        self.stdout.write(self.style.HTTP_INFO('\n■ Full column list of prime candidate tables:'))
        for tbl in ALWAYS_DUMP:
            sql = (
                f"SELECT c.name, t.name AS typ, c.length "
                f"FROM {self._pfx}syscolumns c "
                f"JOIN {self._pfx}sysobjects o ON c.id = o.id "
                f"JOIN {self._pfx}systypes  t ON c.usertype = t.usertype "
                f"WHERE o.type = 'U' AND o.name = '{tbl}' ORDER BY c.colid"
            )
            try:
                _, rows = self._q(conn, sql)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  {tbl}: {exc}'))
                continue
            if not rows:
                self.stdout.write(f'  {tbl}: (table not present on this node)')
                continue
            self.stdout.write(self.style.WARNING(f'  {tbl}  ({len(rows)} cols)'))
            line = '      '
            for name, typ, length in rows:
                cell = f'{str(name).strip()}:{str(typ).strip()}({length})'
                if len(line) + len(cell) > 110:
                    self.stdout.write(line)
                    line = '      '
                line += cell + '   '
            if line.strip():
                self.stdout.write(line)

    # ── 3. sample rows for one item (values to match against the screen) ────────
    def _dump_item(self, conn, itemcode, branchcode, max_rows):
        self.stdout.write(self.style.HTTP_INFO(
            f'\n■ Sample rows for itemcode={itemcode}'
            + (f' branchcode={branchcode}' if branchcode else '') + ':'))

        # Rate columns printed RAW (incl. zeros/nulls) — this is the before/after
        # snapshot for confirming what «تحديث معدل الإستهلاك» writes. monthlyqty is
        # the target; usercode_mq/trans_time_mq is who/when it last changed.
        self._dump_rate_cols(conn, itemcode, branchcode)

        # stkbal — per branch/store: the per-branch rate most likely lives here.
        bfilter = f" AND branchcode = '{branchcode}'" if branchcode else ''
        for tbl in ('stkbal', 'items'):
            where_item = 'itemcode' if tbl in ('stkbal', 'items') else 'itemcode'
            extra = bfilter if tbl == 'stkbal' else ''
            sql = (f"SELECT * FROM {self._pfx}{tbl} "
                   f"WHERE {where_item} = '{itemcode}'{extra}")
            try:
                cols, rows = self._q(conn, sql)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'  {tbl}: {exc}'))
                continue
            self.stdout.write(self.style.WARNING(f'  {tbl}: {len(rows)} row(s)'))
            for r in rows[:max_rows]:
                pairs = [f'{c.strip()}={self._fmt(v)}' for c, v in zip(cols, r)
                         if v is not None and str(v).strip() not in ('', '0', '0.0', '0.000')]
                self.stdout.write('    · ' + '  '.join(pairs))
            if len(rows) > max_rows:
                self.stdout.write(f'    … {len(rows) - max_rows} more (raise --max-rows)')

    # ── fingerprint: reverse-engineer the native write from EXISTING data ───────
    def _fingerprint(self, conn, branchcode, limit):
        """No button-press needed: rows already carrying monthlyqty were written by
        real «تحديث معدل الإستهلاك» presses. Show WHERE rates live (which branch/store)
        and a raw sample incl. the native audit stamp — reveals store convention,
        stored precision, and which usercode SOFTECH records."""
        bflt = f" AND branchcode = '{branchcode}'" if branchcode else ''

        self.stdout.write(self.style.HTTP_INFO(
            '■ Where monthlyqty is set — (branchcode, storecode) → count of rated items:'))
        try:
            _, rows = self._q(conn,
                f"SELECT branchcode, storecode, count(*) AS n FROM {self._pfx}stkbal "
                f"WHERE monthlyqty <> 0{bflt} GROUP BY branchcode, storecode "
                f"ORDER BY branchcode, storecode")
            for bc, sc, n in rows:
                same = '  ← store==branch' if str(bc).strip() == str(sc).strip() else ''
                self.stdout.write(f'      branch {str(bc).strip():<6} store {str(sc).strip():<6} {n:>7} items{same}')
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  distribution failed: {exc}'))

        self.stdout.write(self.style.HTTP_INFO(
            f'\n■ Sample of natively-written rate rows (raw; ASE SET ROWCOUNT {limit}):'))
        cols = ', '.join(self.RATE_COLS)
        try:
            cur = conn.cursor()
            cur.execute(f'SET ROWCOUNT {int(limit)}')          # ASE: no TOP n
            cur.execute(f"SELECT {cols} FROM {self._pfx}stkbal "
                        f"WHERE monthlyqty <> 0{bflt} ORDER BY branchcode, storecode, itemcode")
            names = [d[0] for d in cur.description]
            fetched = cur.fetchall()
            cur.execute('SET ROWCOUNT 0')
            cur.close()
            self.stdout.write('    ' + '  '.join(names))
            for r in fetched:
                self.stdout.write('    ' + '  '.join(self._fmt(v) for v in r))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  sample failed: {exc}'))

    # rate columns shown raw (zeros/nulls included) for the before/after diff
    RATE_COLS = ['branchcode', 'storecode', 'nowqty', 'monthlyqty',
                 'usercode_mq', 'trans_time_mq', 'maxnowqty', 'maxnowqtymonths',
                 'usercode_xq', 'trans_time_xq', 'onorderqty', 'onorderqtymonths']

    def _dump_rate_cols(self, conn, itemcode, branchcode):
        cols = ', '.join(self.RATE_COLS)
        where = f"itemcode = '{itemcode}'"
        if branchcode:
            where += f" AND branchcode = '{branchcode}'"
        sql = f"SELECT {cols} FROM {self._pfx}stkbal WHERE {where} ORDER BY branchcode, storecode"
        try:
            names, rows = self._q(conn, sql)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  rate-cols: {exc}'))
            return
        self.stdout.write(self.style.WARNING(
            f'  stkbal rate columns ({len(rows)} row(s)) — RAW, press «تحديث معدل الإستهلاك» then re-run to diff:'))
        self.stdout.write('    ' + '  '.join(f'{n}' for n in names))
        for r in rows:
            self.stdout.write('    ' + '  '.join(f'{self._fmt(v)}' for v in r))

    @staticmethod
    def _fmt(v):
        import datetime
        from decimal import Decimal
        if isinstance(v, (datetime.datetime, datetime.date)):
            return v.isoformat()[:19]
        if isinstance(v, Decimal):
            return str(float(v))
        s = str(v).strip()
        return s if len(s) <= 30 else s[:29] + '…'
