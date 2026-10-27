"""
python manage.py probe_stock_audit [--days 180] [--nodes] [--section A,B,C,D,E]

Doc 32 Phase 0 — READ-ONLY probe for the Stock Transactions Audit design.
Forces SOFTECH_READ_ONLY for this process, so every statement goes through the
SELECT-only guard in config/sybase.py. Nothing is written to SOFTECH or Postgres.

Sections:
  A  ledger volume: stktrans rows per branchcode x doccode over --days (HQ);
     --nodes also counts each branch node's own stktrans for comparison
  B  VAT basis for check 1: taxed vs untaxed sales lines, price vs newcostprice,
     and purchase (10) lines: transprice vs newcostprice
  C  return references: how 30 lines fill r_doccode / r_docnumber / r_docdate,
     and whether the referenced 115 invoice exists
  D  free-pack candidates: customers whose sales lines are mostly below cost
  E  rough finding volumes for checks 1 and 8 at the default thresholds

Output -> docs/architecture/stock_audit_phase0_probe.txt
"""
import datetime
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..',
                           'docs', 'architecture', 'stock_audit_phase0_probe.txt')

DB = 'SOFTECHDB9.dbo'


def _since(days):
    return f"DATEADD(day, -{int(days)}, CONVERT(datetime, CONVERT(char(8), GETDATE(), 112)))"


class Command(BaseCommand):
    help = 'Doc 32 Phase 0: read-only probe of stktrans for the stock-transactions audit.'

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=180)
        parser.add_argument('--nodes', action='store_true', help='also count rows on each branch node')
        parser.add_argument('--section', default='A,B,C,D,E')
        parser.add_argument('--timeout', type=int, default=900)

    def handle(self, *args, **opts):
        settings.SOFTECH_READ_ONLY = True          # SELECT-only guard for this process
        from config.sybase import get_sybase_connection

        self.lines = []
        self.timeout = opts['timeout']
        days = opts['days']
        sections = {s.strip().upper() for s in opts['section'].split(',')}
        self.log(f'# Stock Transactions Audit — Phase 0 probe  ({datetime.datetime.now():%Y-%m-%d %H:%M})')
        self.log(f'# window: last {days} days · read-only: {settings.SOFTECH_READ_ONLY}')

        conn = get_sybase_connection()
        try:
            if 'A' in sections:
                self.section_a(conn, days)
                if opts['nodes']:
                    self.section_a_nodes(days)
            if 'B' in sections:
                self.section_b(conn)
            if 'C' in sections:
                self.section_c(conn, days)
            if 'D' in sections:
                self.section_d(conn, days)
            if 'E' in sections:
                self.section_e(conn, days)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        path = os.path.abspath(OUTPUT_FILE)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(self.lines) + '\n')
        self.stdout.write(self.style.SUCCESS(f'written: {path}'))

    # ── helpers ──────────────────────────────────────────────────────────────
    def log(self, text=''):
        self.lines.append(str(text))
        self.stdout.write(str(text))

    def q(self, conn, sql, label='', rowcount=0):
        t0 = time.time()
        cur = conn.cursor()
        if rowcount:
            cur.execute(f'SET ROWCOUNT {int(rowcount)}')
        try:
            cur.execute(sql, timeout=self.timeout)
            rows = cur.fetchall()
        finally:
            if rowcount:
                conn.cursor().execute('SET ROWCOUNT 0')
        cols = [d[0] for d in (cur.description or [])]
        self.log(f'  ({label} {len(rows)} rows, {time.time() - t0:.1f}s)')
        return cols, rows

    def table(self, cols, rows, limit=None):
        self.log('  ' + ' | '.join(cols))
        for r in rows[:limit] if limit else rows:
            self.log('  ' + ' | '.join('' if v is None else str(v) for v in r))

    # ── A: volume ────────────────────────────────────────────────────────────
    def section_a(self, conn, days):
        self.log('\n## A. Ledger volume at HQ (rows per branchcode x doccode)')
        cols, rows = self.q(conn, f"""
            SELECT st.branchcode, st.doccode, COUNT(*) AS n
            FROM {DB}.stktrans st
            WHERE st.docdate >= {_since(days)}
            GROUP BY st.branchcode, st.doccode
            ORDER BY st.branchcode, st.doccode""", 'A')
        self.table(cols, rows)
        total = sum(int(r[2] or 0) for r in rows)
        by_code = {}
        for bc, dc, n in rows:
            by_code[str(dc).strip()] = by_code.get(str(dc).strip(), 0) + int(n or 0)
        self.log(f'  TOTAL {days}d: {total:,}  ·  per day ≈ {total / max(days, 1):,.0f}')
        self.log('  per doccode: ' + ', '.join(f'{k}={v:,}' for k, v in sorted(by_code.items(), key=lambda x: -x[1])))

    def section_a_nodes(self, days):
        from apps.branches.models import Branch
        from config.sybase import get_branch_connection
        self.log('\n## A2. Each node\'s own stktrans (rows per branchcode) — is HQ consolidated?')
        for b in Branch.objects.operational().with_local_db().order_by('softech_branch_id'):
            try:
                c = get_branch_connection(b.db_host.strip(), b.effective_db_port, b.db_name or 'SOFTECHDB9')
                try:
                    self.log(f'  node {b.softech_branch_id} ({b.db_host})')
                    cols, rows = self.q(c, f"""
                        SELECT st.branchcode, COUNT(*) AS n, MAX(st.trans_time) AS last_time
                        FROM {DB}.stktrans st
                        WHERE st.docdate >= {_since(days)}
                        GROUP BY st.branchcode ORDER BY st.branchcode""", f'node {b.softech_branch_id}')
                    self.table(cols, rows)
                finally:
                    c.close()
            except Exception as exc:
                self.log(f'  node {b.softech_branch_id}: FAILED {exc}')

    # ── B: VAT basis ─────────────────────────────────────────────────────────
    def section_b(self, conn):
        self.log('\n## B. VAT basis for check 1 (last 30 days)')
        self.log('  B1. sales (115) lines: taxed vs untaxed — avg price / cost ratio')
        cols, rows = self.q(conn, f"""
            SELECT CASE WHEN st.itemsalestax > 0 THEN 'taxed' ELSE 'untaxed' END AS kind,
                   COUNT(*) AS n,
                   AVG(st.transprice / st.newcostprice) AS avg_price_over_cost,
                   AVG(st.itemsaleprice_tax / st.newcostprice) AS avg_list_tax_over_cost,
                   AVG(st.itemsaleprice / st.newcostprice) AS avg_list_over_cost,
                   SUM(CASE WHEN st.transprice < st.newcostprice THEN 1 ELSE 0 END) AS below_cost
            FROM {DB}.stktrans st
            WHERE st.docdate >= {_since(30)} AND st.doccode = '115'
              AND st.newcostprice > 0 AND st.transprice > 0
            GROUP BY CASE WHEN st.itemsalestax > 0 THEN 'taxed' ELSE 'untaxed' END""", 'B1')
        self.table(cols, rows)

        self.log('  B2. sample taxed sales lines (what itemsalestax holds: % or amount?)')
        cols, rows = self.q(conn, rowcount=25, sql=f"""
            SELECT st.branchcode, st.docnumber, st.itemcode, st.transqty, st.transprice,
                   st.itemsaleprice, st.itemsalestax, st.itemsaleprice_tax, st.additionaldiscp,
                   st.custdiscp, st.newcostprice
            FROM {DB}.stktrans st
            WHERE st.docdate >= {_since(7)} AND st.doccode = '115' AND st.itemsalestax > 0
            ORDER BY st.trans_time DESC""", label='B2')
        self.table(cols, rows)

        self.log('  B3. purchase (10) lines on taxed items: transprice vs newcostprice')
        cols, rows = self.q(conn, rowcount=25, sql=f"""
            SELECT st.branchcode, st.docnumber, st.itemcode, st.transqty, st.bonusqty,
                   st.transprice, st.itemsaleprice, st.itemsalestax, st.itemsaleprice_tax,
                   st.pharmacydiscp, st.additionaldiscp, st.newcostprice
            FROM {DB}.stktrans st
            WHERE st.docdate >= {_since(30)} AND st.doccode = '10' AND st.itemsalestax > 0
            ORDER BY st.trans_time DESC""", label='B3')
        self.table(cols, rows)

    # ── C: return references ─────────────────────────────────────────────────
    def section_c(self, conn, days):
        self.log(f'\n## C. Return (30) references over {days} days')
        cols, rows = self.q(conn, f"""
            SELECT CASE WHEN st.r_docnumber IS NULL THEN 'null'
                        WHEN LTRIM(RTRIM(CONVERT(varchar(30), st.r_docnumber))) IN ('', '0') THEN 'empty/0'
                        ELSE 'filled' END AS r_docnumber_state,
                   CONVERT(varchar(10), st.r_doccode) AS r_doccode,
                   COUNT(*) AS n
            FROM {DB}.stktrans st
            WHERE st.docdate >= {_since(days)} AND st.doccode = '30'
            GROUP BY CASE WHEN st.r_docnumber IS NULL THEN 'null'
                          WHEN LTRIM(RTRIM(CONVERT(varchar(30), st.r_docnumber))) IN ('', '0') THEN 'empty/0'
                          ELSE 'filled' END,
                     CONVERT(varchar(10), st.r_doccode)
            ORDER BY 3 DESC""", 'C1')
        self.table(cols, rows)

        self.log('  C2. sample filled returns: does the referenced 115 line exist? (same branch + docnumber + item)')
        cols, rows = self.q(conn, rowcount=30, sql=f"""
            SELECT r.branchcode, r.docnumber, r.docdate, r.itemcode, r.transqty AS ret_qty,
                   r.r_doccode, r.r_docnumber, r.r_docdate
            FROM {DB}.stktrans r
            WHERE r.docdate >= {_since(3)} AND r.doccode = '30'
              AND r.r_docnumber IS NOT NULL
              AND LTRIM(RTRIM(CONVERT(varchar(30), r.r_docnumber))) NOT IN ('', '0')""", label='C2')
        # one indexed lookup per sampled return (branch + doccode + docnumber + docdate)
        cols = cols + ['sold_qty_same_date', 'sold_qty_any_date_in_30d']
        out = []
        for r in rows:
            bc, _dn, _dd, item, _rq, _rdc, rdn, rdd = r
            same = any_ = None
            if rdd is not None:
                _, s = self.q(conn, f"""
                    SELECT SUM(s.transqty) FROM {DB}.stktrans s
                    WHERE s.branchcode = '{bc}' AND s.doccode = '115'
                      AND s.docnumber = {int(rdn)} AND s.docdate = '{rdd:%Y%m%d}'
                      AND s.itemcode = '{item}'""", 'C2 same-date')
                same = s[0][0] if s else None
            _, s = self.q(conn, f"""
                SELECT SUM(s.transqty) FROM {DB}.stktrans s
                WHERE s.branchcode = '{bc}' AND s.doccode = '115'
                  AND s.docdate >= {_since(30)}
                  AND s.docnumber = {int(rdn)} AND s.itemcode = '{item}'""", 'C2 any-date')
            any_ = s[0][0] if s else None
            out.append(list(r) + [same, any_])
        self.table(cols, out)

    # ── D: free-pack candidates ──────────────────────────────────────────────
    def section_d(self, conn, days):
        self.log(f'\n## D. Free-pack / contract candidates: customers with mostly below-cost sales ({days}d)')
        cols, rows = self.q(conn, f"""
            SELECT st.personcode, MAX(p.personname) AS personname, COUNT(*) AS lines,
                   SUM(CASE WHEN st.transprice < st.newcostprice THEN 1 ELSE 0 END) AS below_lines,
                   SUM(CASE WHEN st.transprice < st.newcostprice
                            THEN (st.newcostprice - st.transprice) * st.transqty ELSE 0 END) AS loss_egp
            FROM {DB}.stktrans st
            LEFT JOIN {DB}.personsdata p ON p.personcode = st.personcode
            WHERE st.docdate >= {_since(days)} AND st.doccode = '115'
              AND st.newcostprice > 0 AND st.transqty > 0
            GROUP BY st.personcode
            HAVING COUNT(*) >= 5
               AND SUM(CASE WHEN st.transprice < st.newcostprice THEN 1 ELSE 0 END) * 100 >= 80 * COUNT(*)
            ORDER BY 5 DESC""", 'D')
        self.table(cols, rows, limit=60)

    # ── E: finding volumes ───────────────────────────────────────────────────
    def section_e(self, conn, days):
        self.log('\n## E. Rough finding volumes at default thresholds (last 30 days, before exclusions)')
        cols, rows = self.q(conn, f"""
            SELECT st.branchcode,
                   SUM(CASE WHEN st.transprice < st.newcostprice
                             AND (st.newcostprice - st.transprice) * 100 >= 5 * st.newcostprice
                             AND (st.newcostprice - st.transprice) * st.transqty >= 20 THEN 1 ELSE 0 END) AS chk1_below_cost,
                   SUM(CASE WHEN st.transprice < st.newcostprice
                             AND ((st.newcostprice - st.transprice) * 100 >= 30 * st.newcostprice
                                  OR (st.newcostprice - st.transprice) * st.transqty >= 500) THEN 1 ELSE 0 END) AS chk1_critical,
                   COUNT(*) AS sales_lines
            FROM {DB}.stktrans st
            WHERE st.docdate >= {_since(30)} AND st.doccode = '115'
              AND st.newcostprice > 0 AND st.transqty > 0
            GROUP BY st.branchcode ORDER BY st.branchcode""", 'E1')
        self.table(cols, rows)

        cols, rows = self.q(conn, f"""
            SELECT st.branchcode, st.doccode,
                   SUM(CASE WHEN DATEDIFF(day, st.docdate, st.trans_time) > 1 THEN 1 ELSE 0 END) AS chk8_backdated,
                   SUM(CASE WHEN DATEDIFF(day, st.docdate, st.trans_time) > 7 THEN 1 ELSE 0 END) AS chk8_critical,
                   SUM(CASE WHEN DATEDIFF(day, st.docdate, st.trans_time) < 0 THEN 1 ELSE 0 END) AS future_dated,
                   COUNT(*) AS n
            FROM {DB}.stktrans st
            WHERE st.docdate >= {_since(30)}
            GROUP BY st.branchcode, st.doccode
            HAVING SUM(CASE WHEN DATEDIFF(day, st.docdate, st.trans_time) > 1 THEN 1 ELSE 0 END) > 0
                OR SUM(CASE WHEN DATEDIFF(day, st.docdate, st.trans_time) < 0 THEN 1 ELSE 0 END) > 0
            ORDER BY 3 DESC""", 'E2')
        self.table(cols, rows, limit=60)
