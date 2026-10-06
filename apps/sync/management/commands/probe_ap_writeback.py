"""
python manage.py probe_ap_writeback
    [--branch 130] [--personcode 4471]
    [--rehearse --confirm-rollback-rehearsal]   # opt-in, real INSERT then ROLLBACK

Phase-G step 1 — investigate HOW SOFTECH records a سداد so we can eventually
reproduce it safely. The reconciliation write surface is (from doc 23 §1):
  cheques (voucher header) + chequestrans (allocation) + stktransm.docvaluepay↑.

Two phases:

  DISCOVERY (default, PURE READ — zero DML):
    A. lastdocnumbers columns — is there a cheque serial counter? (scout said NO)
    B. triggers on cheques / chequestrans + whether their bodies are readable
       (tr_cheques_insert exists but its syscomments text is NULL ⇒ ENCRYPTED,
        like tr_stktrans — so side-effects must be learned empirically).
    C. sysdepends — procs/triggers that reference cheques / chequestrans (works
       even when the body is encrypted) → is there a save PROC we must call?
    D. per-branch MAX(cheqsno)/MAX(ourcheqsno) — the "+1" serial pattern.
    E. full schema of cheques + chequestrans (NOT-NULL sentinels for a writer).
    F. golden voucher + its allocation dump (the write template).

  REHEARSAL (--rehearse, DOUBLE-GATED, always ROLLBACK — zero residue):
    Opens ONE transaction, allocates cheqsno = MAX+1, INSERTs a minimal cheques
    row (inline-literal, cp1256), reads it back to observe what the ENCRYPTED
    trigger set (personnewbal / banknewbal / any counter bump), optionally INSERTs
    a chequestrans row for a real invoice and checks whether stktransm.docvaluepay
    moved, captures @@error/@@rowcount at each step, then ROLLS BACK and verifies
    nothing persisted. This mirrors clone_purchase / pos_probe. It NEVER commits.
    It runs ONLY with BOTH --rehearse and --confirm-rollback-rehearsal.

ABSOLUTE RULE: no COMMIT ever. Discovery is SELECT-only; the rehearsal always
rolls back. This is the AP mirror of investigate_purchase_invoice + clone_purchase.

Output -> docs/architecture/softech_ap_writeback_investigation.txt
"""
import os
import datetime
from django.core.management.base import BaseCommand

OUTPUT_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', '..', 'docs', 'architecture',
    'softech_ap_writeback_investigation.txt',
)
DB = 'SOFTECHDB9.dbo'
NULLABLE_BIT = 8


class Command(BaseCommand):
    help = 'Phase-G step 1: READ-ONLY discovery of the SOFTECH سداد write path (+ opt-in rollback rehearsal)'

    def add_arguments(self, parser):
        parser.add_argument('--profile', default='prod')
        parser.add_argument('--branch', default='130')
        parser.add_argument('--personcode', default='4471')
        parser.add_argument('--rehearse', action='store_true',
                            help='run the rollback INSERT rehearsal (still requires --confirm-rollback-rehearsal)')
        parser.add_argument('--confirm-rollback-rehearsal', action='store_true',
                            help='second gate — acknowledges real INSERTs (always rolled back) will run')

    def handle(self, *args, **o):
        from config.sybase import SoftechConnector

        lines = []

        def log(t=''):
            self.stdout.write(t)
            lines.append(t)

        def section(t):
            bar = '=' * 80
            log(''); log(bar); log(f'  {t}'); log(bar)

        def checkpoint():
            self._save(lines)

        log(f'AP write-back discovery: {datetime.datetime.now().isoformat()}')
        log('Mode: DISCOVERY = SELECT-only. REHEARSAL (opt-in) = INSERT then ROLLBACK, never COMMIT.')

        try:
            conn = SoftechConnector(profile=o['profile']).connect()
        except Exception as e:
            log(f'[FATAL] connect failed: {e}')
            self._save(lines)
            return

        def run(label, sql, cap=None):
            log(f'\n--- {label} ---')
            if cap:
                try:
                    conn._cursor().execute(f'SET ROWCOUNT {cap}')
                except Exception:
                    pass
            try:
                cur = conn._cursor()
                cur.execute(sql)
                cols = [d[0] for d in cur.description] if cur.description else []
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
                    try:
                        conn._cursor().execute('SET ROWCOUNT 0')
                    except Exception:
                        pass

        def schema(tbl):
            log(f'\n  SCHEMA: {tbl}  (colid | name | type | len | NULL?)')
            try:
                cur = conn._cursor()
                cur.execute(f"""
                    SELECT c.colid, c.name, t.name, c.length, c.status
                    FROM {DB}.syscolumns c
                    JOIN {DB}.sysobjects o ON c.id=o.id
                    JOIN {DB}.systypes  t ON c.usertype=t.usertype
                    WHERE o.name='{tbl}' ORDER BY c.colid
                """)
                for r in cur.fetchall():
                    nul = 'NULL' if (int(r[4] or 0) & NULLABLE_BIT) else 'NOT NULL'
                    log(f'    [{str(r[0]):>3}] {str(r[1]):<26} {str(r[2]):<12} len={str(r[3]):<5} {nul}')
            except Exception as e:
                log(f'    [ERROR] {e}')

        br, pc = o['branch'], o['personcode']

        # ── A: serial counter? ───────────────────────────────────────────────
        section('A: lastdocnumbers — is there a cheque serial counter?')
        run('all lastdocnumbers column names', f"""
            SELECT c.name FROM {DB}.syscolumns c JOIN {DB}.sysobjects o ON c.id=o.id
            WHERE o.name='lastdocnumbers' ORDER BY c.colid
        """)

        # ── B: triggers + readability ────────────────────────────────────────
        section('B: triggers on cheques / chequestrans + body readability')
        for tbl in ('cheques', 'chequestrans'):
            run(f'{tbl}: named triggers + text-row count', f"""
                SELECT tr.name,
                       (SELECT COUNT(*) FROM {DB}.syscomments sc WHERE sc.id=tr.id) AS nrows,
                       (SELECT COUNT(*) FROM {DB}.syscomments sc WHERE sc.id=tr.id AND sc.text IS NOT NULL) AS ntext
                FROM {DB}.sysobjects tr
                WHERE tr.type='TR' AND LOWER(tr.name) LIKE '%{tbl}%'
            """)

        # ── C: sysdepends — procs/triggers referencing the tables ────────────
        section('C: objects that reference cheques / chequestrans (sysdepends)')
        run('procs/triggers depending on the two tables', f"""
            SELECT DISTINCT o.name, o.type
            FROM {DB}.sysdepends d
            JOIN {DB}.sysobjects o ON d.id = o.id
            JOIN {DB}.sysobjects t ON d.depid = t.id
            WHERE t.name IN ('cheques','chequestrans') AND o.type IN ('P','TR')
            ORDER BY o.type, o.name
        """, cap=200)

        # ── D: per-branch serial "+1" pattern ────────────────────────────────
        section('D: per-branch MAX serials vs lastdocnumbers counters (the +1 pattern)')
        run(f'branch {br}: max cheqsno / ourcheqsno', f"""
            SELECT MAX(cheqsno) AS max_cheqsno, MAX(ourcheqsno) AS max_ourcheqsno,
                   COUNT(*) AS n
            FROM {DB}.cheques WHERE branchcode='{br}'
        """)
        run(f'branch {br}: lastdocnumbers candidate counters', f"""
            SELECT branchcode, ver_branch, paymentsno, localpayment_sno,
                   accsno, accsno2, accsno3
            FROM {DB}.lastdocnumbers WHERE branchcode='{br}'
        """)
        run('HQ (000) staging counters row', f"""
            SELECT branchcode, ver_branch, paymentsno, localpayment_sno,
                   accsno, accsno2, accsno3
            FROM {DB}.lastdocnumbers WHERE branchcode='000'
        """)

        # ── E: schemas ───────────────────────────────────────────────────────
        section('E: schema of cheques + chequestrans (writer NOT-NULL sentinels)')
        schema('cheques')
        schema('chequestrans')

        # ── F: golden voucher + allocation template ──────────────────────────
        section('F: golden voucher + its allocation (the write template)')
        run(f'a recent cheques voucher for supplier {pc} @ branch {br}', f"""
            SELECT * FROM {DB}.cheques
            WHERE branchcode='{br}' AND personcode='{pc}' AND cheqvalue>0
            ORDER BY cheqdate DESC
        """, cap=1)
        run(f'a recent chequestrans allocation @ branch {br}', f"""
            SELECT ct.* FROM {DB}.chequestrans ct
            JOIN {DB}.cheques c ON c.cheqsno=ct.cheqsno AND c.branchcode=ct.cheqbranchcode
            WHERE c.branchcode='{br}' AND c.personcode='{pc}'
            ORDER BY ct.docdate DESC
        """, cap=3)
        checkpoint()

        # ── REHEARSAL (opt-in, always ROLLBACK) ──────────────────────────────
        if o['rehearse'] and o['confirm_rollback_rehearsal']:
            section('G: ROLLBACK INSERT REHEARSAL (real INSERT → observe → ROLLBACK)')
            self._rehearse(conn, log, run, br, pc)
            checkpoint()
        elif o['rehearse']:
            section('G: REHEARSAL SKIPPED — pass --confirm-rollback-rehearsal to run it')
            log('  The rehearsal does REAL INSERTs (always rolled back) on the financial')
            log('  payment path. It is intentionally double-gated. Not run.')
        else:
            section('G: REHEARSAL NOT REQUESTED (discovery only)')
            log('  Re-run with --rehearse --confirm-rollback-rehearsal to learn, with zero')
            log('  residue, whether the encrypted trigger auto-sets serial/personnewbal/')
            log('  banknewbal and whether chequestrans drives stktransm.docvaluepay.')

        conn.close()
        log(f'\nComplete: {datetime.datetime.now().isoformat()}')
        self._save(lines)

    # ------------------------------------------------------------------ rehearse
    def _rehearse(self, conn, log, run, br, pc):
        """
        Real INSERT rehearsal, ALWAYS rolled back. Learns the encrypted trigger's
        behaviour with zero residue. Every step is inside ONE transaction that ends
        in ROLLBACK; any error also rolls back. NEVER commits.
        """
        import time
        marker = f'APPROBE{int(time.time())}'
        log(f'  marker note = {marker}  (unique tag to find the row & detect serial reassignment)')

        def q1(sql):
            cur = conn._cursor(); cur.execute(sql)
            row = cur.fetchone()
            return row

        try:
            # allocate next per-branch serials (dense sequence, MAX+1)
            row = q1(f"SELECT ISNULL(MAX(cheqsno),0)+1, ISNULL(MAX(ourcheqsno),0)+1 FROM {DB}.cheques WHERE branchcode='{br}'")
            next_cheqsno, next_our = int(row[0]), int(row[1])
            log(f'  allocated cheqsno={next_cheqsno} ourcheqsno={next_our} (branch {br})')

            # a real, recent purchase invoice for this supplier (for the chequestrans/stktransm test)
            inv = q1(f"""SELECT docnumber, docdate, docvalue, docvaluepay FROM {DB}.stktransm
                         WHERE doccode='10' AND branchcode='{br}' AND cust_branch_code='{pc}'
                         ORDER BY docdate DESC""")
            if inv:
                inv_no, inv_date, inv_val, inv_pay_before = inv
                log(f'  target invoice: docnumber={inv_no} docdate={inv_date} docvalue={inv_val} docvaluepay(before)={inv_pay_before}')

            conn.begin_transaction()
            log('  BEGIN TRAN')

            # ── INSERT the cheques voucher (inline literals; personnewbal/banknewbal = 0 sentinels)
            cols = ('cheqsno,financialdoccode,cheqtype,cheqno,cheqdate,bankcode,personcode,cheqvalue,'
                    'cheqregisterdate,ourcheqsno,usercode,chequenote,wentto_bankstrans,branchcode,'
                    'personnewbal,banknewbal,cheqcashfees,open_trans,ptcode,bcurrency,bcrate,'
                    'banknewbal_lc,cheqvalue_lc,bcrate_std,cheqvalueother,blockinv')
            vals = (f"{next_cheqsno},'10','20','{next_our}',getdate(),'40','{pc}',1.00,"
                    f"getdate(),{next_our},'1309','{marker}','0','{br}',"
                    f"0.0,0.0,0.0,0,'20',1,1.0,"
                    f"0.0,1.00,1.0,0.0,0")
            ins_sql = f"INSERT INTO {DB}.cheques ({cols}) VALUES ({vals})"
            insert_ok = True
            try:
                conn._cursor().execute(ins_sql)
                log('  cheques INSERT executed (no exception)')
            except Exception as e:
                insert_ok = False
                log(f'  [cheques INSERT REJECTED] {e}')

            # ── read the row BACK by marker (survives any trigger serial reassignment)
            got = None
            if insert_ok:
                got = q1(f"""SELECT cheqsno, ourcheqsno, personnewbal, banknewbal, cheqvalue, branchcode
                             FROM {DB}.cheques WHERE chequenote='{marker}'""")
                if got:
                    actual_cheqsno = int(got[0])
                    log(f'  READBACK: cheqsno={got[0]} (we sent {next_cheqsno} → '
                        f'{"REASSIGNED by trigger" if actual_cheqsno != next_cheqsno else "kept ours"}) '
                        f'ourcheqsno={got[1]}')
                    log(f'           personnewbal={got[2]} banknewbal={got[3]}  '
                        f'(we sent 0/0 → {"TRIGGER POSTED balances" if (got[2] not in (0,0.0) or got[3] not in (0,0.0)) else "unchanged, client must compute"})')
                    log(f'           cheqvalue={got[4]} branchcode={got[5]}')

                    # ── chequestrans + stktransm.docvaluepay test
                    if inv:
                        ct_cols = ('cheqsno,branchcode,doccode,docnumber,docdate,'
                                   'docvaluepaid,docvaluepaynow,usercode,cheqbranchcode')
                        ct_vals = (f"{actual_cheqsno},'{br}','10',{inv_no},'{inv_date}',"
                                   f"1.00,1.00,'1309','{br}'")
                        try:
                            conn._cursor().execute(
                                f"INSERT INTO {DB}.chequestrans ({ct_cols}) VALUES ({ct_vals})")
                            log('  chequestrans INSERT executed')
                            after = q1(f"""SELECT docvaluepay FROM {DB}.stktransm
                                           WHERE doccode='10' AND branchcode='{br}' AND docnumber={inv_no} AND docdate='{inv_date}'""")
                            log(f'  stktransm.docvaluepay: before={inv_pay_before} after={after[0] if after else "?"} '
                                f'→ {"CASCADED (unexpected — chequestrans has no trigger)" if after and after[0] != inv_pay_before else "UNCHANGED → writer must UPDATE stktransm itself"}')
                        except Exception as e:
                            log(f'  [chequestrans INSERT REJECTED] {e}')
                else:
                    log('  READBACK: no row found by marker — insert did not persist in-txn '
                        '(trigger may have rolled it back, like tr_stktrans).')

            conn.rollback()
            log('  ROLLBACK issued')
        except Exception as e:
            try:
                conn.rollback()
                log('  ROLLBACK after error')
            except Exception:
                pass
            log(f'  [REHEARSAL ERROR] {e}')

        # ── verify zero residue (autocommit restored after rollback)
        try:
            chk = q1(f"SELECT COUNT(*) FROM {DB}.cheques WHERE chequenote='{marker}'")
            log(f'  RESIDUE CHECK: rows with marker after rollback = {chk[0]} (must be 0)')
        except Exception as e:
            log(f'  [residue check error] {e}')

    def _save(self, lines):
        path = os.path.abspath(OUTPUT_FILE)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            self.stdout.write(self.style.SUCCESS(f'\nSaved -> {path}'))
        except Exception as e:
            self.stdout.write(self.style.WARNING(f'\nCould not save: {e}'))
