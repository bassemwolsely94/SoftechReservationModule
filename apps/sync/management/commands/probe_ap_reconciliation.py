"""
python manage.py probe_ap_reconciliation
    [--profile prod]
    [--voucher-serial 51703] [--receipt-no 31789] [--inner-serial 451]
    [--invoice-serial 12207] [--supplier-docno 5213] [--amount 743.40]
    [--branch 130] [--invoice-date 2026-08-15] [--supplier-personcode ...]

READ-ONLY Phase-A discovery of the SOFTECH **Supplier A/P settlement** pathway —
the "المدفوعات و المقبوضات / سداد فواتير" (Payments & Receipts → invoice
settlement) screen. This is the reconciliation-side mirror of
investigate_purchase_invoice (which mapped the purchase document, doccode 10/120).

Goal — answer, with live evidence, the ONE open question from
SOFTECH_SUPPLIER_INVOICE_WRITEBACK.md §3 and the AP-reconciliation brief:

  Q1. WHICH TABLE stores a supplier PAYMENT VOUCHER (the صرف/استلام receipt)?
      Anchors from a real voucher (screenshot 2026-09-18, branch 130):
        top مسلسل = 51703 | inner مسلسل = 451 | receipt no (رقم إيصال الصرف) = 31789
        net paid صافي مبلغ مسدد = 743.40 | نقدي-كاش (cash, box "خزينة علياء")
        beneficiary = supplier "مورد شركات 30% Contact Supplier 30"
      Hypothesis: a cash voucher lands in `cheques` with cheqtype='10'
      (verified elsewhere: cheqtype 10 = cash/box entry, NOT a real cheque),
      financialdoccode = a supplier-payment code, personcode = supplier,
      cheqvalue = 743.40 — OR in a dedicated payments/financial-voucher table.

  Q2. **THE CRITICAL UNKNOWN** — WHICH TABLE records the invoice↔payment
      ALLOCATION (the سداد فواتير grid)? The screen proves SOFTECH DOES store
      an explicit link: this voucher settles supplier invoice
        مسلسل 12207 (رقم مستند المورد 5213, dated 2026-08-15),
        مبلغ مستحق 743.40 → المسدد الآن 743.40 → مغلق ✓.
      Find the row that ties voucher(51703/31789) ↔ invoice(12207) with
      paid_now = 743.40. Discover its table + columns → this is the
      ReconciliationAllocation ground truth.

  Q3. HOW is partial / oldest-first (FIFO) / distribute-amount settlement
      represented (three native buttons on the tab)? → the allocation table's
      columns (amount_due vs amount_paid vs closed-flag) answer this.

  Q4. Does the payment voucher post to the supplier running balance the same way
      a purchase does (personsdata debit/credit buckets → personnewbal snapshot)?

Discovery strategy (no table-name guessing where avoidable):
  A. TABLE-name census (payment/receipt/settlement patterns).
  B. **COLUMN-name census** across ALL user tables — find every table that
     carries a settlement/paid/invoice-link column. This points straight at the
     allocation table without guessing its name.
  C. ANCHOR hunt — locate 51703 / 31789 / 12207 / 5213 / 743.40 in the likely
     voucher tables (cheques, bankstrans, custpayments, + any discovered table).
  D. SCHEMA dumps of every confirmed candidate.
  E. PROC/TRIGGER text hunt for the settlement save path (tables it names).
  F. SUPPLIER balance snapshot (personsdata buckets + personnewbal on the voucher).

ABSOLUTE RULE: SELECT only. No INSERT/UPDATE/DELETE is ever issued.
Sybase ASE 12.5 quirks: no SELECT TOP (SET ROWCOUNT), CONVERT() casts, ISNULL(),
string concat with '+'.  syscomments.text is NULL for vendor-encrypted objects.

Output -> docs/architecture/softech_ap_reconciliation_investigation.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__),
    '..', '..', '..', '..', 'docs', 'architecture',
    'softech_ap_reconciliation_investigation.txt',
)

DB = 'SOFTECHDB9.dbo'
NULLABLE_BIT = 8

# User-table name patterns that might back the payment voucher / settlement link.
TABLE_NAME_PATTERNS = [
    '%pay%', '%recei%', '%receipt%', '%sadad%', '%sanad%', '%sarf%', '%dafe%',
    '%madfo%', '%mokbod%', '%kabd%', '%voucher%', '%settle%', '%alloc%',
    '%financ%', '%treasur%', '%khazn%', '%cash%', '%cheq%', '%bank%',
    '%openinv%', '%invpay%', '%docpay%', '%paid%', '%opentrans%',
]

# COLUMN-name patterns that would appear on an invoice↔payment allocation row.
COLUMN_NAME_PATTERNS = [
    '%paid%', '%paynow%', '%paidnow%', '%paidvalue%', '%settle%', '%sadad%',
    '%invno%', '%invnumber%', '%invoiceno%', '%refdoc%', '%paydoc%',
    '%docpay%', '%openinv%', '%opentrans%', '%blockinv%', '%docpaydue%',
    '%amountdue%', '%duevalue%', '%remain%', '%allocat%', '%financialdoc%',
    '%receiptno%', '%esalno%', '%serial%', '%mokbod%',
]

# Tables we always dump full schema for (known + likely).
SCHEMA_TABLES = ['cheques', 'bankstrans', 'custpayments', 'branchesales', 'banks',
                 'paymentstypes', 'personsdata', 'lastdocnumbers']


class Command(BaseCommand):
    help = 'READ-ONLY discovery of the SOFTECH supplier A/P settlement tables (المدفوعات والمقبوضات / سداد فواتير)'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod', help='SOFTECH profile (default: prod = HQ)')
        # Anchors from the ground-truth screenshot (2026-09-18, branch 130).
        parser.add_argument('--voucher-serial', default='51703', help='top مسلسل on the payment voucher')
        parser.add_argument('--receipt-no', default='31789', help='رقم إيصال الصرف/الإستلام (disbursement receipt no)')
        parser.add_argument('--inner-serial', default='451', help='inner مسلسل on the voucher')
        parser.add_argument('--invoice-serial', default='12207', help='settled invoice مسلسل (grid) — also ملاحظات مورد')
        parser.add_argument('--supplier-docno', default='5213', help='رقم مستند المورد (supplier printed doc no)')
        parser.add_argument('--amount', default='743.40', help='net settled amount المسدد الآن')
        parser.add_argument('--branch', default='130', help='voucher branch')
        parser.add_argument('--invoice-date', default='2026-08-15', help='settled invoice date (yyyy-mm-dd)')
        parser.add_argument('--supplier-personcode', default='', help='supplier personcode (optional; else read from voucher)')

    def handle(self, *args, **options):
        from django.conf import settings
        from config.sybase import SoftechConnector

        profile = options['profile']
        A = options  # anchors
        lines = []

        def log(t=''):
            self.stdout.write(t)
            lines.append(t)

        def section(title):
            bar = '=' * 80
            log(''); log(bar); log(f'  {title}'); log(bar)

        def checkpoint():
            # Incremental save — a later socket timeout must never lose earlier output.
            self._save(lines)

        log(f'AP-reconciliation discovery started: {datetime.datetime.now().isoformat()}')
        log(f'Profile: {profile} | effective host: '
            f'{os.environ.get("SOFTECH_%s_HOST" % profile.upper()) or getattr(settings, "SYBASE_HOST", "?")}')
        log('Mode: READ-ONLY (SELECT only)')
        log(f'ANCHORS  voucher_serial={A["voucher_serial"]} receipt_no={A["receipt_no"]} '
            f'inner_serial={A["inner_serial"]} invoice_serial={A["invoice_serial"]} '
            f'supplier_docno={A["supplier_docno"]} amount={A["amount"]} '
            f'branch={A["branch"]} invoice_date={A["invoice_date"]}')

        try:
            conn = SoftechConnector(profile=profile).connect()
        except Exception as e:
            log(f'[FATAL] connect failed: {e}')
            log('SOFTECH not reachable from here — run this command on a box that can '
                'reach the HQ Sybase (192.168.1.8) and commit the output file.')
            self._save(lines)
            return

        # ── generic helpers ──────────────────────────────────────────────────
        def run(label, sql, params=None, cap=None):
            log(f'\n--- {label} ---')
            if cap:
                set_rowcount(cap)
            try:
                cur = conn._cursor()
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                if not rows:
                    log('  (no rows)')
                    return []
                log('  COLS: ' + ' | '.join(cols))
                for r in rows:
                    log('  ' + ' | '.join('NULL' if c is None else str(c) for c in r))
                return rows
            except Exception as e:
                log(f'  [ERROR] {e}')
                return []
            finally:
                if cap:
                    set_rowcount(0)

        def set_rowcount(n):
            try:
                conn._cursor().execute(f'SET ROWCOUNT {n}')
            except Exception as e:
                log(f'  [ERROR set rowcount] {e}')

        def dump_row_vertical(label, sql, params=None):
            log(f'\n--- {label} (one row, vertical) ---')
            set_rowcount(1)
            try:
                cur = conn._cursor()
                cur.execute(sql, params)
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                if not row:
                    log('  (no rows)')
                    return None
                for name, val in zip(cols, row):
                    log(f'    {name:<28} = {"NULL" if val is None else val}')
                return dict(zip(cols, row))
            except Exception as e:
                log(f'  [ERROR] {e}')
                return None
            finally:
                set_rowcount(0)

        def schema(tbl):
            log(f'\n  SCHEMA: {tbl}  (colid | name | type | len | NULL?)')
            try:
                cur = conn._cursor()
                cur.execute(f"""
                    SELECT c.colid, c.name, t.name AS type, c.length, c.status
                    FROM   {DB}.syscolumns c
                    JOIN   {DB}.sysobjects o ON c.id = o.id
                    JOIN   {DB}.systypes   t ON c.usertype = t.usertype
                    WHERE  o.name = '{tbl}'
                    ORDER  BY c.colid
                """)
                rows = cur.fetchall()
                if not rows:
                    log('    (not found)')
                    return
                for r in rows:
                    nullable = 'NULL' if (int(r[4] or 0) & NULLABLE_BIT) else 'NOT NULL'
                    log(f'    [{str(r[0]):>3}] {str(r[1]):<28} {str(r[2]):<14} len={str(r[3]):<5} {nullable}')
            except Exception as e:
                log(f'    [ERROR] {e}')

        def col_exists(tbl, col):
            try:
                cur = conn._cursor()
                cur.execute(f"""
                    SELECT COUNT(*) FROM {DB}.syscolumns c
                    JOIN {DB}.sysobjects o ON c.id=o.id
                    WHERE o.name='{tbl}' AND c.name='{col}'
                """)
                return (cur.fetchone() or [0])[0] > 0
            except Exception:
                return False

        # ── A: table-name census ─────────────────────────────────────────────
        section('A: Candidate payment / receipt / settlement tables by NAME')
        for pat in TABLE_NAME_PATTERNS:
            run(f"name LIKE '{pat}'", f"""
                SELECT o.name AS table_name
                FROM   {DB}.sysobjects o
                WHERE  o.type = 'U' AND LOWER(o.name) LIKE '{pat}'
                ORDER  BY o.name
            """)
        checkpoint()

        # ── B: COLUMN-name census — the settlement table finder ──────────────
        section('B: COLUMN-name census — tables carrying settlement / paid / invoice-link columns')
        log('  (This is the key discovery: whichever table holds the invoice↔voucher')
        log('   allocation must expose columns like paid/paidnow/invno/refdoc/docpay/amountdue.)')
        for pat in COLUMN_NAME_PATTERNS:
            run(f"column LIKE '{pat}'", f"""
                SELECT o.name AS table_name, c.name AS column_name, t.name AS type
                FROM   {DB}.syscolumns c
                JOIN   {DB}.sysobjects o ON c.id = o.id
                JOIN   {DB}.systypes   t ON c.usertype = t.usertype
                WHERE  o.type = 'U' AND LOWER(c.name) LIKE '{pat}'
                ORDER  BY o.name, c.name
            """, cap=60)
        checkpoint()

        # ── C: ANCHOR hunt — find the voucher + the allocation link ──────────
        section('C: ANCHOR hunt — locate the voucher and its invoice allocation')

        amt = A['amount']
        vser = A['voucher_serial']
        rcpt = A['receipt_no']
        invser = A['invoice_serial']
        suppdoc = A['supplier_docno']
        branch = A['branch']

        # C1 — cheques hypothesis (cash box voucher). Try the strongest anchors.
        log('\n  [C1] cheques — cash/box voucher hypothesis (cheqtype=10)')
        run('cheques WHERE cheqvalue = amount (recent)', f"""
            SELECT cheqsno, cheqno, ourcheqsno, financialdoccode, cheqtype, cheqdate,
                   cheqvalue, bankcode, personcode, branchcode, chequenote,
                   personnewbal, banknewbal, open_trans, blockinv, handedto
            FROM   {DB}.cheques
            WHERE  cheqvalue = {amt}
              AND  cheqdate >= DATEADD(day, -90, GETDATE())
            ORDER  BY cheqdate DESC
        """, cap=40)
        for col, val in (('cheqsno', vser), ('cheqno', rcpt), ('ourcheqsno', rcpt),
                         ('cheqsno', rcpt), ('ourcheqsno', vser)):
            if col_exists('cheques', col):
                run(f'cheques WHERE {col} = {val}', f"""
                    SELECT cheqsno, cheqno, ourcheqsno, financialdoccode, cheqtype,
                           cheqdate, cheqvalue, personcode, branchcode, chequenote,
                           personnewbal, open_trans, blockinv
                    FROM {DB}.cheques WHERE {col} = {val}
                """, cap=20)

        checkpoint()

        # C2 — dedicated payments tables, if they exist (discovered in §A).
        log('\n  [C2] custpayments / bankstrans anchor probes')
        run('custpayments WHERE custpayvalue = amount (recent)', f"""
            SELECT * FROM {DB}.custpayments
            WHERE custpayvalue = {amt} AND custpaydate >= DATEADD(day,-90,GETDATE())
        """, cap=20)
        run('bankstrans recent rows (bounded)', f"""
            SELECT * FROM {DB}.bankstrans
            WHERE transdate >= DATEADD(day,-14,GETDATE())
        """, cap=15)
        checkpoint()

        # C3 — the settled invoice (stktransm doccode 10). docnumber2 is UNINDEXED,
        # so bound the scan hard by branch + a tight date window around the invoice.
        log('\n  [C3] the settled supplier invoice (stktransm doccode 10)')
        inv = dump_row_vertical('stktransm doccode=10 WHERE docnumber = invoice_serial (branch, dated)', f"""
            SELECT * FROM {DB}.stktransm
            WHERE doccode='10' AND docnumber = {invser} AND branchcode = '{branch}'
              AND docdate >= DATEADD(day,-1,'{A['invoice_date']}')
              AND docdate <= DATEADD(day, 1,'{A['invoice_date']}')
            ORDER BY docdate DESC
        """)
        if not inv:
            inv = dump_row_vertical('stktransm doccode=10 WHERE docnumber2 = supplier_docno (branch, bounded)', f"""
                SELECT * FROM {DB}.stktransm
                WHERE doccode='10' AND docnumber2 = {suppdoc} AND branchcode = '{branch}'
                  AND docdate >= DATEADD(day,-15,'{A['invoice_date']}')
                  AND docdate <= DATEADD(day, 15,'{A['invoice_date']}')
                ORDER BY docdate DESC
            """)
        checkpoint()
        supplier_pc = A['supplier_personcode'] or (str(inv.get('cust_branch_code')).strip() if inv else '')
        log(f'\n  >> resolved supplier personcode = {supplier_pc or "(unknown — pass --supplier-personcode)"}')

        # C4 — GLOBAL needle scan: which user table has a row equal to invoice_serial
        #      AND to the amount? Scans numeric/decimal columns table-by-table.
        section('C4: GLOBAL needle scan — table+column holding invoice_serial and amount')
        log('  Enumerating user tables with BOTH an integer-ish column = invoice_serial')
        log('  and a decimal column = amount would need dynamic SQL; instead we list every')
        log('  table that has a column matching a settlement pattern (from §B) and, for the')
        log('  top candidates, dump recent rows so the link row is visible. Prioritise any')
        log('  table whose §B column census flagged paid/paidnow/invno/refdoc/docpay.')
        # Cheap existence census (one query) for the classic SOFTECH detail-table
        # name shapes; only dump the ones that actually exist (avoids dead-table
        # timeouts once the socket is under load).
        cands = ['financialdocs', 'financialdocsm', 'financialdocsdetail', 'financialtrans',
                 'paymentsdetail', 'paymentsdetails', 'paidinvoices', 'invoicespayment',
                 'docpayments', 'sadadfawater', 'openinvoices', 'cheqinvoices',
                 'cheqdetails', 'chequesdetail', 'cheqsadad', 'invsettle']
        namelist = ','.join(f"'{c}'" for c in cands)
        existing = run('which candidate detail tables exist', f"""
            SELECT o.name FROM {DB}.sysobjects o
            WHERE o.type='U' AND o.name IN ({namelist})
            ORDER BY o.name
        """)
        for row in (existing or []):
            tbl = str(row[0]).strip()
            schema(tbl)
            run(f'{tbl}: recent rows', f'SELECT * FROM {DB}.{tbl}', cap=8)
        checkpoint()

        # ── D: schema of confirmed candidates ────────────────────────────────
        section('D: Schema of known + candidate tables')
        for tbl in SCHEMA_TABLES:
            schema(tbl)
        checkpoint()

        # ── E: proc/trigger text hunt for the settlement save path ───────────
        section('E: procedures/triggers referencing the settlement / voucher save path')
        run('procs/triggers mentioning cheques / settlement / open_trans / financialdoc', f"""
            SELECT DISTINCT o.name, o.type
            FROM   {DB}.syscomments sc
            JOIN   {DB}.sysobjects  o ON sc.id = o.id
            WHERE  o.type IN ('P','TR')
              AND (LOWER(sc.text) LIKE '%open_trans%'
                OR LOWER(sc.text) LIKE '%blockinv%'
                OR LOWER(sc.text) LIKE '%financialdoc%'
                OR LOWER(sc.text) LIKE '%docpaydue%'
                OR LOWER(sc.text) LIKE '%paidinv%'
                OR LOWER(sc.text) LIKE '%sadad%')
            ORDER BY o.name
        """, cap=80)
        run('tr_cheques trigger body (if readable — personnewbal/bank balance math)', f"""
            SELECT sc.text FROM {DB}.syscomments sc
            JOIN {DB}.sysobjects o ON sc.id = o.id
            WHERE o.name = 'tr_cheques' ORDER BY sc.colid2
        """)
        checkpoint()

        # ── F: supplier balance + running personnewbal ───────────────────────
        section('F: supplier A/P balance snapshot')
        if supplier_pc:
            run('personsdata debit/credit buckets for the supplier', f"""
                SELECT personcode, ptcode, ptclassifcode,
                       persondebit, persondebit1, persondebit2,
                       personcredit, personcredit1, personcredit2,
                       (persondebit+persondebit1+persondebit2
                        - personcredit-personcredit1-personcredit2) AS net_balance
                FROM {DB}.personsdata WHERE personcode = '{supplier_pc}'
            """)
            run('recent docs for supplier (stktransm 10/120 + personnewbal trail)', f"""
                SELECT doccode, docnumber, docdate, branchcode, docvalue, docvaluepay,
                       docpaydue, personnewbal
                FROM {DB}.stktransm
                WHERE cust_branch_code = '{supplier_pc}' AND doccode IN ('10','120')
                  AND docdate >= DATEADD(day, -120, GETDATE())
                ORDER BY docdate DESC
            """, cap=30)
            run('supplier cheques/payments trail (personnewbal after each)', f"""
                SELECT cheqsno, cheqno, cheqdate, cheqvalue, cheqtype, financialdoccode,
                       branchcode, personnewbal, open_trans, blockinv, chequenote
                FROM {DB}.cheques
                WHERE personcode = '{supplier_pc}'
                  AND cheqdate >= DATEADD(day, -120, GETDATE())
                ORDER BY cheqdate DESC
            """, cap=30)
        else:
            log('  (supplier personcode not resolved — pass --supplier-personcode to enable §F)')

        conn.close()
        log(f'\nComplete: {datetime.datetime.now().isoformat()}')
        log('\nNEXT: from §B/§C4 identify the ALLOCATION table (voucher↔invoice, paid_now),')
        log('      then re-run with its name to dump the exact link row for invoice 12207.')
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
