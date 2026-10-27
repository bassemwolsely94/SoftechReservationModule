"""
python manage.py probe_isr                       # HQ: dump ISR/طلب-توريد candidate tables' structure
python manage.py probe_isr --isr 26100574        # locate + dump one ISR (header + lines) wherever it lives
python manage.py probe_isr --host 192.168.30.12 --isr 26100574

READ-ONLY discovery probe for FEATURE 2 (طلب توريد أصناف / ISR → إذن الصرف).

Reverse-engineers the tables behind «ISR for Branch» (طلب توريد, e.g. #26100574).
Prime candidates from the schema scan: stockisr, stockorders, stockordersm,
stockordersmtext, items_req, lastorderno. With --isr it AUTO-DISCOVERS which
table+column holds the number (tries every order/req/doc/no-ish column) and dumps
the matching rows raw — header + lines + the مصدر الطلب (Report vs User Entry) and
qty columns visible on screen. Never writes.

Run on HQ (the ISR is «إنشاء بفرع الرئيسي» and syncs to HQ on إعتماد); use --host
for a branch node if it lives there pre-approval.
"""
from django.core.management.base import BaseCommand

# ISR / طلب-توريد candidate tables (dump structure for all; search these for --isr).
ISR_TABLES = ['stockisr', 'stockorders', 'stockordersm', 'stockordersmtext',
              'items_req', 'lastorderno']

# Column-name fragments that could hold the ISR serial number.
KEY_FRAGMENTS = ['isr', 'orderno', 'ordernumber', 'docnumber', 'reqsno', 'reqno',
                 'receiveorder', 'srno', 'sno', 'order_no', 'doc_number']


class Command(BaseCommand):
    help = 'READ-ONLY: reverse-engineer the SOFTECH ISR / طلب-توريد tables (Feature 2 probe)'

    def add_arguments(self, parser):
        parser.add_argument('--host', default=None,
                            help='branch/HQ node db_host; omit to use HQ (SYBASE_HOST)')
        parser.add_argument('--port', type=int, default=5000)
        parser.add_argument('--dbname', default='SOFTECHDB9')
        parser.add_argument('--isr', default=None, help='ISR / طلب توريد number to locate + dump')
        parser.add_argument('--serials', action='store_true',
                            help='reverse-engineer isrdocnumber / docnumber allocation (recent numbers, '
                                 'lastorderno counters, recent طلب-توريد headers)')
        parser.add_argument('--anatomy', default=None,
                            help='ISR number: dump FULL stockisr rows (all cols), distinct itemsource '
                                 '(Report vs User-Entry), + trace an ISR→طلب-توريد conversion (target branch)')
        parser.add_argument('--converted', default=None,
                            help='ISR number: after a native اعتماد, dump the RESULTING طلب-توريد '
                                 '(stockordersm header + stockorders lines, all cols) = golden template for Stage B')
        parser.add_argument('--branch', default=None,
                            help='requesting/creating branchcode (with --converted, to scope the ref lookup)')
        parser.add_argument('--max-rows', type=int, default=60, dest='max_rows')

    def handle(self, *a, **o):
        from config.sybase import get_sybase_connection, get_branch_connection
        host = o.get('host')
        if host:
            conn = get_branch_connection(host, o['port'], o['dbname'])
            self._pfx = ''
            where = f'branch node {host}:{o["port"]}/{o["dbname"]}'
        else:
            conn = get_sybase_connection()
            self._pfx = f'{o["dbname"]}.dbo.'
            where = f'HQ ({o["dbname"]}.dbo)'

        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\n═══ probe_isr — READ-ONLY — {where} ═══\n'))
        try:
            cols_by_table = self._dump_structures(conn)
            if o.get('serials'):
                self._serials(conn, o['max_rows'])
            if o.get('anatomy'):
                self._anatomy(conn, o['anatomy'], o['max_rows'])
            if o.get('converted'):
                self._converted(conn, o['converted'], o.get('branch'), o['max_rows'])
            if o.get('isr'):
                self._locate_isr(conn, o['isr'], cols_by_table, o['max_rows'])
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _q(self, conn, sql, params=None):
        cur = conn.cursor()
        try:
            cur.execute(sql, params or [])
            cols = [d[0] for d in cur.description] if cur.description else []
            return cols, cur.fetchall()
        finally:
            cur.close()

    def _columns(self, conn, tbl):
        sql = (f"SELECT c.name, t.name AS typ, c.length "
               f"FROM {self._pfx}syscolumns c "
               f"JOIN {self._pfx}sysobjects o ON c.id = o.id "
               f"JOIN {self._pfx}systypes  t ON c.usertype = t.usertype "
               f"WHERE o.type='U' AND o.name='{tbl}' ORDER BY c.colid")
        try:
            _, rows = self._q(conn, sql)
        except Exception:
            return []
        return [(str(n).strip(), str(tp).strip(), ln) for n, tp, ln in rows]

    def _dump_structures(self, conn):
        self.stdout.write(self.style.HTTP_INFO('■ ISR / طلب-توريد candidate tables:'))
        out = {}
        for tbl in ISR_TABLES:
            cols = self._columns(conn, tbl)
            out[tbl] = cols
            if not cols:
                self.stdout.write(f'  {tbl}: (not present on this node)')
                continue
            self.stdout.write(self.style.WARNING(f'  {tbl}  ({len(cols)} cols)'))
            line = '      '
            for name, typ, length in cols:
                cell = f'{name}:{typ}({length})'
                if len(line) + len(cell) > 110:
                    self.stdout.write(line)
                    line = '      '
                line += cell + '   '
            if line.strip():
                self.stdout.write(line)
        return out

    def _locate_isr(self, conn, isr, cols_by_table, max_rows):
        self.stdout.write(self.style.HTTP_INFO(f'\n■ Locating ISR #{isr} across candidate tables:'))
        # Inline numeric literal — jConnect binding a str to a decimal column silently
        # fails to match (the invoice-writer lesson); build the predicate as a literal.
        lit = str(isr) if str(isr).isdigit() else "'" + str(isr).replace("'", "''") + "'"
        found_any = False
        for tbl, cols in cols_by_table.items():
            if not cols:
                continue
            key_cols = [n for (n, _t, _l) in cols
                        if any(f in n.lower() for f in KEY_FRAGMENTS)]
            for kc in key_cols:
                try:
                    _, cnt = self._q(conn, f"SELECT count(*) FROM {self._pfx}{tbl} WHERE {kc} = {lit}")
                    n = int(cnt[0][0]) if cnt else 0
                except Exception:
                    continue
                if n <= 0:
                    continue
                found_any = True
                self.stdout.write(self.style.SUCCESS(f'  ✔ {tbl}.{kc} = {isr} → {n} row(s):'))
                self._dump_where(conn, tbl, f'{kc} = {lit}', max_rows)
        if not found_any:
            self.stdout.write(self.style.WARNING(
                '  Not found by key search — dumping the MOST RECENT rows of the header/line '
                'tables so we can see where the number actually appears:'))
            for tbl in ('stockordersm', 'stockisr', 'stockorders'):
                if cols_by_table.get(tbl):
                    self.stdout.write(self.style.SUCCESS(f'  ▸ {tbl} (latest {min(max_rows, 20)} by trans_time):'))
                    self._dump_where(conn, tbl, None, min(max_rows, 20), order='trans_time DESC')

    def _serials(self, conn, max_rows):
        """Reverse-engineer how isrdocnumber / طلب-توريد docnumber are allocated."""
        self.stdout.write(self.style.HTTP_INFO('\n■ Serial allocation investigation:'))

        # 1a) CHEAP high-water aggregate first (one pass) — yielded even in a brief
        #     connection window. NB: 'rows' is a reserved word in ASE → alias n_rows.
        self.stdout.write(self.style.SUCCESS('  ▸ stockisr — high-water (max/min/count):'))
        try:
            _, r = self._q(conn, f"SELECT max(isrdocnumber) AS mx, min(isrdocnumber) AS mn, "
                                 f"count(*) AS n_rows FROM {self._pfx}stockisr")
            if r:
                self.stdout.write(f'      max_isrdocnumber={self._fmt(r[0][0])}  '
                                  f'min={self._fmt(r[0][1])}  total_rows={self._fmt(r[0][2])}')
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'      failed: {exc}'))

        # 1a2) Serial high-water scoped to THIS year's HQ prefix ({YY}100) — the
        #      number the ISR writer would increment. Concatenation, not fixed width.
        from django.utils import timezone as _tz
        prefix = f'{_tz.now():%y}100'
        self.stdout.write(self.style.SUCCESS(f'  ▸ stockisr — max for prefix {prefix} (this-year HQ serial):'))
        try:
            _, r = self._q(conn, f"SELECT max(isrdocnumber) FROM {self._pfx}stockisr "
                                 f"WHERE convert(varchar(14), isrdocnumber) LIKE '{prefix}%'")
            mx = r[0][0] if r else None
            if mx is not None:
                s = str(int(mx))
                serial = s[len(prefix):] if s.startswith(prefix) else '?'
                self.stdout.write(f'      max={self._fmt(mx)}  → serial={serial}  next={prefix}{int(serial)+1 if serial.isdigit() else "?"}')
            else:
                self.stdout.write(f'      (none yet this year — first would be {prefix}1)')
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'      failed: {exc}'))

        # 1b) Distinct ISR numbers (is stockisr a live/staging table or a log?) + owners.
        self.stdout.write(self.style.SUCCESS('  ▸ stockisr — distinct isrdocnumber (recent):'))
        try:
            cur = conn.cursor()
            cur.execute(f'SET ROWCOUNT {min(max_rows, 25)}')
            cur.execute(f"SELECT isrdocnumber, count(*) AS lines, max(usercode) AS usr, "
                        f"max(trans_time) AS ts FROM {self._pfx}stockisr "
                        f"GROUP BY isrdocnumber ORDER BY isrdocnumber DESC")
            names = [d[0].strip() for d in cur.description]
            rows = cur.fetchall()
            cur.execute('SET ROWCOUNT 0'); cur.close()
            for r in rows:
                self.stdout.write('      ' + '  '.join(f'{c}={self._fmt(v)}' for c, v in zip(names, r)))
            self.stdout.write(f'      → {len(rows)} distinct ISR(s) in stockisr'
                              + (' (looks like a live/staging table)' if len(rows) <= 2 else ''))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'      failed: {exc}'))

        # 2) lastorderno — the per-branch serial counters (which column tracks ISR?).
        self.stdout.write(self.style.SUCCESS('  ▸ lastorderno — per-branch serial counters (all rows):'))
        self._dump_where(conn, 'lastorderno', None, 40)

        # 3) Recent طلب-توريد headers — to see the 6-digit docnumber sequence + branch fields.
        self.stdout.write(self.style.SUCCESS('  ▸ stockordersm — recent headers (docnumber sequence):'))
        try:
            cur = conn.cursor()
            cur.execute(f'SET ROWCOUNT {min(max_rows, 20)}')
            cur.execute(f"SELECT branchcode, docnumber, forbranchcode, tobranchcode, storecode, "
                        f"docdate, trans_time, docstatuscode, usercode, purapp, whapp "
                        f"FROM {self._pfx}stockordersm ORDER BY trans_time DESC")
            names = [d[0].strip() for d in cur.description]
            rows = cur.fetchall()
            cur.execute('SET ROWCOUNT 0'); cur.close()
            for r in rows:
                self.stdout.write('      ' + '  '.join(f'{c}={self._fmt(v)}' for c, v in zip(names, r)
                                                       if v is not None))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'      failed: {exc}'))

    # ── golden template: the native طلب-توريد produced by اعتماد of an ISR ──────
    def _converted(self, conn, isr, branchcode, max_rows):
        isr = str(isr).strip()
        self.stdout.write(self.style.HTTP_INFO(
            f'\n■ Golden template — طلب-توريد converted from ISR #{isr}'
            + (f' (branch {branchcode})' if branchcode else '') + ':'))

        # refdocnumber may be the FULL isrdocnumber (modern) or the trailing SERIAL
        # (older branch-era). Try both.
        candidates = [isr]
        if branchcode and isr[:2].isdigit() and isr[2:2 + len(str(branchcode))] == str(branchcode):
            serial = isr[2 + len(str(branchcode)):]
            if serial.isdigit():
                candidates.append(str(int(serial)))
        cand_lits = ', '.join(candidates)
        rb = f" AND refbranchcode = '{branchcode}'" if branchcode else ''

        try:
            _, rows = self._q(conn,
                f"SELECT DISTINCT branchcode, docnumber, refdocnumber FROM {self._pfx}stockorders "
                f"WHERE refdocnumber IN ({cand_lits}){rb}")
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'  lookup failed: {exc}'))
            return
        if not rows:
            self.stdout.write(self.style.WARNING(
                f'  No stockorders linked by refdocnumber IN [{cand_lits}] — the اعتماد conversion '
                f'may not have run yet, use a different link, or live on the branch node.'))
            # Fallback 1: the ISR's CURRENT state (did اعتماد stamp table_dumped / change it?).
            self.stdout.write(self.style.SUCCESS(f'  ▸ stockisr #{isr} current state (row 1):'))
            self._dump_where(conn, 'stockisr', f'isrdocnumber = {isr}', 1, all_cols=True)
            # Fallback 2: the branch's most-recent طلب-توريد headers — the newly-approved
            #             order shows here regardless of the ref link field.
            if branchcode:
                self.stdout.write(self.style.SUCCESS(
                    f'  ▸ latest stockordersm headers for branch {branchcode} (top 5 by trans_time):'))
                self._dump_where(conn, 'stockordersm', f"branchcode='{branchcode}'", 5,
                                 order='trans_time DESC', all_cols=True)
            return

        for bc, dn, rdn in rows:
            bc, dn = str(bc).strip(), self._fmt(dn)
            self.stdout.write(self.style.SUCCESS(
                f'  ✔ طلب-توريد branch={bc} docnumber={dn} (refdocnumber={self._fmt(rdn)}):'))
            self.stdout.write('    header (stockordersm, ALL cols):')
            self._dump_where(conn, 'stockordersm', f"branchcode='{bc}' AND docnumber={dn}", 1, all_cols=True)
            self.stdout.write('    lines (stockorders, ALL cols):')
            self._dump_where(conn, 'stockorders', f"branchcode='{bc}' AND docnumber={dn}",
                             min(max_rows, 30), all_cols=True)
            self.stdout.write('    free-text (stockordersmtext):')
            self._dump_where(conn, 'stockordersmtext', f"branchcode='{bc}' AND docnumber={dn}", 10, all_cols=True)

    def _dump_where(self, conn, tbl, where, limit, order=None, all_cols=False):
        try:
            cur = conn.cursor()
            cur.execute(f'SET ROWCOUNT {int(limit)}')      # ASE: no TOP n
            sql = f"SELECT * FROM {self._pfx}{tbl}"
            if where:
                sql += f" WHERE {where}"
            if order:
                sql += f" ORDER BY {order}"
            cur.execute(sql)
            names = [d[0].strip() for d in cur.description]
            rows = cur.fetchall()
            cur.execute('SET ROWCOUNT 0')
            cur.close()
            for r in rows:
                # all_cols=True keeps zeros/nulls (full anatomy); else hide empties for brevity
                pairs = [f'{c}={self._fmt(v)}' for c, v in zip(names, r)
                         if all_cols or (v is not None and str(v).strip() not in ('', '0', '0.0', '0.000'))]
                self.stdout.write('      · ' + '  '.join(pairs))
            if len(rows) >= limit:
                self.stdout.write(f'      … capped at {limit} (raise --max-rows)')
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f'      dump failed: {exc}'))

    # ── full anatomy: all stockisr cols, itemsource enum, ISR→طلب-توريد conversion ──
    def _anatomy(self, conn, isr, max_rows):
        lit = str(isr) if str(isr).isdigit() else "'" + str(isr).replace("'", "''") + "'"
        self.stdout.write(self.style.HTTP_INFO(f'\n■ ISR #{isr} anatomy:'))

        # (1) FULL stockisr rows — every column incl. zeros/nulls (item_topo, itemqty_tobr, ash_sff…)
        self.stdout.write(self.style.SUCCESS('  ▸ stockisr — full rows (all columns):'))
        self._dump_where(conn, 'stockisr', f'isrdocnumber = {lit}', min(max_rows, 8), all_cols=True)

        # (2) itemsource enum — Report(4) vs User-Entry(?) — across stockisr AND stockorders
        for tbl in ('stockisr', 'stockorders'):
            self.stdout.write(self.style.SUCCESS(f'  ▸ {tbl} — distinct itemsource (counts):'))
            try:
                _, r = self._q(conn, f"SELECT itemsource, count(*) AS n FROM {self._pfx}{tbl} "
                                     f"GROUP BY itemsource ORDER BY itemsource")
                for src, cnt in r:
                    self.stdout.write(f'      itemsource={self._fmt(src)} → {self._fmt(cnt)} rows')
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'      failed: {exc}'))

        # (3) trace an ISR→طلب-توريد conversion: a stockorders line linked back to an ISR
        #     (refdocnumber>0) reveals the target branch (stockordersm.forbranchcode) + line source.
        self.stdout.write(self.style.SUCCESS('  ▸ ISR→طلب-توريد conversion (stockorders.refdocnumber links):'))
        try:
            cur = conn.cursor()
            cur.execute('SET ROWCOUNT 5')
            cur.execute(f"SELECT branchcode, docnumber, refbranchcode, refdocnumber "
                        f"FROM {self._pfx}stockorders WHERE refdocnumber > 0 "
                        f"ORDER BY trans_time DESC")
            links = cur.fetchall()
            cur.execute('SET ROWCOUNT 0'); cur.close()
        except Exception as exc:
            links = []
            self.stdout.write(self.style.ERROR(f'      link scan failed: {exc}'))
        seen = set()
        for bc, dn, rbc, rdn in links:
            key = (str(bc).strip(), str(dn).strip())
            if key in seen:
                continue
            seen.add(key)
            self.stdout.write(f'      ⇒ طلب-توريد branch={self._fmt(bc)} docnumber={self._fmt(dn)} '
                              f'← ISR refbranch={self._fmt(rbc)} refdoc={self._fmt(rdn)}')
            self.stdout.write('        header (stockordersm):')
            self._dump_where(conn, 'stockordersm', f"branchcode='{str(bc).strip()}' AND docnumber={self._fmt(dn)}",
                             1, all_cols=True)
            self.stdout.write('        lines (stockorders, sample):')
            self._dump_where(conn, 'stockorders',
                             f"branchcode='{str(bc).strip()}' AND docnumber={self._fmt(dn)}", 6)
            break   # one worked example is enough

    @staticmethod
    def _fmt(v):
        import datetime
        from decimal import Decimal
        if isinstance(v, (datetime.datetime, datetime.date)):
            return v.isoformat()[:19]
        if isinstance(v, Decimal):
            return str(float(v))
        s = str(v).strip()
        return s if len(s) <= 34 else s[:33] + '…'
