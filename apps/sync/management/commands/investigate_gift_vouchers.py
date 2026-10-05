"""
python manage.py investigate_gift_vouchers [--profile prod] [--supplier 1268]
                                           [--items CODE1,CODE2] [--since 2015-01-01]

READ-ONLY probe — reverse-engineers how ElRezeiky STOCKS gift coupons / vouchers in
SOFTECH by purchasing them from the internal supplier
"هدايا الاداره لخدمة العملاء" (personcode 1268, ptcode 20, ptclassif 10).

Today an RPA robot reads an Excel of randomly generated voucher numbers + random
expiry dates and keys EACH voucher as its OWN line on a supplier purchase (doccode 10)
in the native `مشتريات من الموردين` screen. This probe captures everything needed to
replicate that through `apps/invoices/writer.py` (no new write channel):

  1. supplier master row (personsdata)                       — header sentinels
  2. every doccode-10 purchase header from the supplier       — archive / cadence
  3. every line of those purchases (all columns)             — line template:
       where the voucher NUMBER lives (item_partno? docnumber2? expiry encoding?),
       how the random EXPIRY is used, qty-per-line, price, dblitemflag, newqty
  4. the voucher item codes (auto-discovered from 3 + --items) — item master
  5. returns to supplier (doccode 120)                       — reversal behaviour
  6. how a voucher LEAVES stock: every doccode that moved those items, with
     sample rows (does the cashier pick a specific expiry/batch = voucher?)
  7. current on-hand per voucher (stkbal + stkbalexpiry incl. batchno)
  8. itemssuppliers links + any OTHER supplier that sold these items
  9. name-based search for other coupon/voucher items (sanity net)
 10. lastdocnumbers *_supp counters for the branches involved

ABSOLUTE RULE: SELECT only. Nothing is written to SOFTECH.
Output -> docs/architecture/softech_gift_vouchers_investigation.txt
          docs/architecture/softech_gift_vouchers_lines.csv   (full line archive)
"""
import csv
import datetime
import os

from django.core.management.base import BaseCommand

_DOCS = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'architecture')
OUTPUT_FILE = os.path.join(_DOCS, 'softech_gift_vouchers_investigation.txt')
CSV_FILE = os.path.join(_DOCS, 'softech_gift_vouchers_lines.csv')

DB = 'SOFTECHDB9.dbo'


class Command(BaseCommand):
    help = 'READ-ONLY probe of gift-voucher stocking via supplier 1268 (هدايا الاداره لخدمة العملاء)'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod')
        parser.add_argument('--supplier', default='1268', help='supplier personcode')
        parser.add_argument('--items', default='', help='extra voucher itemcodes, comma-separated')
        parser.add_argument('--since', default='2015-01-01', help='lower docdate bound (YYYY-MM-DD)')
        parser.add_argument('--sample', type=int, default=40, help='rows shown per sample section')

    def handle(self, *args, **options):
        from config.sybase import SoftechConnector
        lines = []
        supp = str(options['supplier']).strip()
        since = options['since']
        sample = options['sample']

        def log(t=''):
            self.stdout.write(t)
            lines.append(t)

        def section(title):
            log('')
            log('=' * 80)
            log(f'  {title}')
            log('=' * 80)

        log(f'Gift-voucher stocking probe: {datetime.datetime.now().isoformat()}')
        log(f'Mode: READ-ONLY   supplier={supp}   since={since}')

        try:
            conn = SoftechConnector(profile=options['profile']).connect()
        except Exception as e:
            log(f'[FATAL] connect: {e}')
            self._save(lines)
            return

        def fetch(sql, params=None):
            cur = conn._cursor()
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return cols, cur.fetchall()

        def run(label, sql, params=None, limit=None):
            log(f'\n--- {label} ---')
            try:
                cols, rows = fetch(sql, params)
            except Exception as e:
                log(f'  [ERROR] {e}')
                return [], []
            if not rows:
                log('  (no rows)')
                return cols, []
            log('  COLS: ' + ' | '.join(cols))
            shown = rows if limit is None else rows[:limit]
            for r in shown:
                log('  ' + ' | '.join('NULL' if c is None else str(c).strip() for c in r))
            if limit is not None and len(rows) > limit:
                log(f'  ... ({len(rows) - limit} more rows not shown; total {len(rows)})')
            return cols, rows

        def vrow(label, sql, params=None):
            log(f'\n--- {label} (vertical) ---')
            try:
                cols, rows = fetch(sql, params)
            except Exception as e:
                log(f'  [ERROR] {e}')
                return None
            if not rows:
                log('  (no rows)')
                return None
            for n, v in zip(cols, rows[0]):
                log(f'    {n:<28} = {"NULL" if v is None else str(v).strip()}')
            return dict(zip(cols, rows[0]))

        # ── 1. Supplier master ─────────────────────────────────────────────────
        section(f'1: SUPPLIER MASTER — personsdata personcode={supp}')
        vrow('personsdata', f"SELECT * FROM {DB}.personsdata WHERE personcode=?", [supp])

        # ── 2. Purchase headers from the supplier ──────────────────────────────
        section(f'2: PURCHASE HEADERS — stktransm doccode=10 cust_branch_code={supp}')
        hcols, hdrs = run('per-branch summary', f"""
            SELECT branchcode, COUNT(*) AS docs, MIN(docdate) AS first_doc, MAX(docdate) AS last_doc,
                   SUM(docvalue) AS total_value
            FROM {DB}.stktransm
            WHERE doccode='10' AND cust_branch_code=? AND docdate >= ?
            GROUP BY branchcode ORDER BY branchcode
        """, [supp, since])
        _, headers = run('all headers', f"""
            SELECT branchcode, docnumber, docdate, docwritedate, docnumber2, docvalue, storecode,
                   usercode, ptclassifcode, supp_main_code, comments
            FROM {DB}.stktransm
            WHERE doccode='10' AND cust_branch_code=? AND docdate >= ?
        """, [supp, since])
        if headers:
            last = max(headers, key=lambda r: str(r[2] or ''))
            vrow('most recent header (all columns)', f"""
                SELECT * FROM {DB}.stktransm WHERE branchcode=? AND doccode='10' AND docnumber=?
            """, [str(last[0]).strip(), last[1]])

        # ── 3. Every line of those purchases → archive CSV ─────────────────────
        section('3: PURCHASE LINES — every stktrans row of the headers above')
        all_cols, all_rows = None, []
        for h in headers:
            try:
                cols, rows = fetch(f"""
                    SELECT * FROM {DB}.stktrans WHERE branchcode=? AND doccode='10' AND docnumber=?
                """, [str(h[0]).strip(), h[1]])
            except Exception as e:
                log(f'  [ERROR] lines {h[0]}/{h[1]}: {e}')
                continue
            all_cols = all_cols or cols
            all_rows.extend(rows)
        log(f'  total lines: {len(all_rows)} across {len(headers)} purchase docs')
        voucher_items = set(x.strip() for x in options['items'].split(',') if x.strip())
        if all_cols:
            ix = {c: i for i, c in enumerate(all_cols)}
            self._write_csv(all_cols, all_rows)

            def col(r, name):
                i = ix.get(name)
                return None if i is None else r[i]

            for r in all_rows:
                voucher_items.add(str(col(r, 'itemcode')).strip())
            log(f'  distinct itemcodes on these purchases: {sorted(voucher_items)}')

            # Shape questions the RPA replication depends on
            def distinct(name):
                return {str(col(r, name)).strip() for r in all_rows if col(r, name) is not None}
            for name in ('transqty', 'transprice', 'itemsaleprice', 'pharmacydiscp', 'custdiscp',
                         'bonusqty', 'promtype', 'storecode2', 'dblitemflag'):
                vals = distinct(name)
                log(f'  {name:<16} distinct={len(vals):<6} sample={sorted(vals)[:12]}')
            exps = [col(r, 'itemexpirydate') for r in all_rows]
            nn = [e for e in exps if e is not None]
            log(f'  itemexpirydate   non-null={len(nn)}/{len(exps)}  distinct={len(set(nn))}  '
                f'min={min(nn) if nn else None}  max={max(nn) if nn else None}')
            for name in ('item_partno', 'vf1', 'vf2', 'vf3', 'vf4', 'comments'):
                if name in ix:
                    vals = distinct(name)
                    log(f'  {name:<16} non-null-distinct={len(vals):<6} sample={sorted(vals)[:12]}')
            # uniqueness of (item, expiry) per doc — is expiry the per-voucher key?
            per_doc = {}
            for r in all_rows:
                k = (str(col(r, 'branchcode')).strip(), col(r, 'docnumber'))
                per_doc.setdefault(k, []).append((str(col(r, 'itemcode')).strip(), col(r, 'itemexpirydate')))
            dup_docs = sum(1 for v in per_doc.values() if len(v) != len(set(v)))
            log(f'  docs with a repeated (itemcode, expiry) pair: {dup_docs}/{len(per_doc)}')
            log(f'  lines per doc: min={min(map(len, per_doc.values()))} '
                f'max={max(map(len, per_doc.values()))}')
            # Vertical dump of the first 3 lines of the most recent doc
            if headers:
                run('most recent doc — lines (all columns)', f"""
                    SELECT * FROM {DB}.stktrans WHERE branchcode=? AND doccode='10' AND docnumber=?
                """, [str(last[0]).strip(), last[1]], limit=sample)

        # ── 4. Item master for the voucher items ───────────────────────────────
        section('4: VOUCHER ITEMS — items master')
        for code in sorted(voucher_items):
            vrow(f'items itemcode={code}', f"SELECT * FROM {DB}.items WHERE itemcode=?", [code])

        # ── 5. Returns to supplier ─────────────────────────────────────────────
        section(f'5: RETURNS — stktransm doccode=120 cust_branch_code={supp}')
        run('return headers', f"""
            SELECT branchcode, docnumber, docdate, docnumber2, patientpayment, docvalue
            FROM {DB}.stktransm WHERE doccode='120' AND cust_branch_code=? AND docdate >= ?
        """, [supp, since], limit=sample)

        # ── 6. How vouchers leave stock ────────────────────────────────────────
        section('6: MOVEMENTS — every doccode that moved the voucher items')
        for code in sorted(voucher_items):
            run(f'itemcode={code}: doccode distribution', f"""
                SELECT doccode, COUNT(*) AS line_cnt, SUM(transqty) AS qty,
                       MIN(docdate) AS first_dt, MAX(docdate) AS last_dt
                FROM {DB}.stktrans WHERE itemcode=? AND docdate >= ?
                GROUP BY doccode ORDER BY doccode
            """, [code, since])
            run(f'itemcode={code}: recent NON-purchase lines (sales/transfers/adjustments)', f"""
                SELECT branchcode, doccode, docnumber, docdate, storecode, transqty, newqty,
                       itemexpirydate, item_partno, transprice, itemsaleprice, custdiscp, personcode
                FROM {DB}.stktrans
                WHERE itemcode=? AND doccode <> '10' AND docdate >= DATEADD(day, -180, GETDATE())
            """, [code], limit=sample)

        # ── 7. Current on-hand per voucher ─────────────────────────────────────
        section('7: ON-HAND — stkbal + stkbalexpiry')
        for code in sorted(voucher_items):
            run(f'stkbal itemcode={code}', f"""
                SELECT branchcode, storecode, nowqty, nowcostprice FROM {DB}.stkbal WHERE itemcode=?
            """, [code])
            run(f'stkbalexpiry itemcode={code} (qty<>0)', f"""
                SELECT storecode, itemexpirydate, batchno, itemqty FROM {DB}.stkbalexpiry
                WHERE itemcode=? AND itemqty <> 0
            """, [code], limit=sample)
            run(f'stkbalexpiry itemcode={code} — row/qty totals', f"""
                SELECT storecode, COUNT(*) AS rows_cnt, SUM(itemqty) AS qty,
                       SUM(CASE WHEN itemqty = 0 THEN 1 ELSE 0 END) AS zero_rows
                FROM {DB}.stkbalexpiry WHERE itemcode=? GROUP BY storecode
            """, [code])

        # ── 8. Supplier links ──────────────────────────────────────────────────
        section('8: SUPPLIER LINKS — itemssuppliers + other suppliers of these items')
        for code in sorted(voucher_items):
            run(f'itemssuppliers itemcode={code}', f"SELECT * FROM {DB}.itemssuppliers WHERE itemcode=?", [code])
            run(f'doccode-10 suppliers of itemcode={code}', f"""
                SELECT personcode, COUNT(*) AS lines, MIN(docdate) AS first_dt, MAX(docdate) AS last_dt
                FROM {DB}.stktrans WHERE itemcode=? AND doccode='10' AND docdate >= ?
                GROUP BY personcode
            """, [code, since])

        # ── 9. Name-based safety net ───────────────────────────────────────────
        section('9: NAME SEARCH — other coupon/voucher/gift items')
        run('items matching coupon/voucher/gift keywords', f"""
            SELECT itemcode, itemname, itemmedicine, itemexpiry, itemsaleprice, itemcostprice,
                   itemtrans1, itemtrans2, itemtrans3, itemnomoreuse, itemarchive
            FROM {DB}.items
            WHERE itemname LIKE '%COUPON%' OR itemname LIKE '%VOUCHER%' OR itemname LIKE '%GIFT%'
               OR itemname LIKE '%كوبون%' OR itemname LIKE '%قسيم%' OR itemname LIKE '%هدي%'
               OR itemname LIKE '%فاوتشر%' OR itemmedicine = '60'
        """, limit=200)

        # ── 10. Counters ───────────────────────────────────────────────────────
        section('10: COUNTERS — lastdocnumbers (*_supp)')
        run('lastdocnumbers', f"""
            SELECT branchcode, ver_branch, lastdocnumberin_supp, lastdocnumberout_supp
            FROM {DB}.lastdocnumbers ORDER BY branchcode
        """)

        self._save(lines)

    def _write_csv(self, cols, rows):
        path = os.path.abspath(CSV_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                w = csv.writer(f)
                w.writerow(cols)
                for r in rows:
                    w.writerow(['' if v is None else str(v).strip() for v in r])
            self.stdout.write(self.style.SUCCESS(f'Line archive -> {path} ({len(rows)} rows)'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'Could not write CSV: {e}'))

    def _save(self, lines):
        path = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            self.stdout.write(self.style.SUCCESS(f'\nSaved -> {path}'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'\nCould not save: {e}'))
