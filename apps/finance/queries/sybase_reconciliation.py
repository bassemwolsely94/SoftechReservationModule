"""
apps/finance/queries/sybase_reconciliation.py

SELECT-only SOFTECH reads for the A/P–A/R reconciliation ingest (Phase-C batch 2).
ABSOLUTE RULE: SELECT only. Never INSERT / UPDATE / DELETE on SOFTECHDB9.

Three feeds, all bounded by a date window (+ optional branch / personcode) so the
huge base tables are never scanned wholesale (see §25 of the brief):

  invoices    ← stktransm      (doccode 10/120 supplier, 115/30 customer)
  vouchers    ← cheques        (payment/receipt vouchers; party via personsdata.ptcode)
  allocations ← chequestrans   (voucher↔invoice links; joined to cheques for the window)

Party keys (VERIFIED, mirrors apps/personal/queries.py):
  • stktransm has NO personcode column — the counterparty is `cust_branch_code`,
    disambiguated by doccode (supplier 10/120 vs customer 115/30).
  • cheques.personcode is the party; personsdata.ptcode = '20' ⇒ supplier.
  • chequestrans links to its voucher by (cheqsno, cheqbranchcode) = (cheques.cheqsno, cheques.branchcode).

All functions are parameterised (jConnect bound params, never string-interpolated
dates/codes) and degrade to [{'_error': ...}] rather than raising.
"""
from __future__ import annotations

import datetime

from config.sybase import get_sybase_connection

DB = 'SOFTECHDB9.dbo'
SUPPLIER_PTCODE = '20'

DOCCODES = {
    'supplier': ('10', '120'),
    'customer': ('115', '30'),
}

_DEFAULT_TIMEOUT = 120


def _safe(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode('utf-8', errors='replace')
        except Exception:
            return repr(v)
    return v


def _rows(sql: str, params: list, rowcount: int | None = None,
          timeout: int = _DEFAULT_TIMEOUT) -> list[dict]:
    conn = None
    try:
        conn = get_sybase_connection()
        cur = conn.cursor()
        if rowcount:
            cur.execute(f'SET ROWCOUNT {int(rowcount)}')
        cur.execute(sql, params, timeout=timeout)
        cols = [d[0] for d in cur.description]
        out = [{c: _safe(v) for c, v in zip(cols, r)} for r in cur.fetchall()]
        if rowcount:
            try:
                cur.execute('SET ROWCOUNT 0')
            except Exception:
                pass
        return out
    except Exception as e:
        return [{'_error': str(e)[:300]}]
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _doccode_in(party_type: str) -> tuple[str, list[str]]:
    codes = DOCCODES.get(party_type, ())
    placeholders = ','.join(['?'] * len(codes))
    return placeholders, list(codes)


# ── 1. invoices (stktransm) ───────────────────────────────────────────────────

def get_invoices(party_type: str, date_from: str, date_to: str,
                 branch: str | None = None, personcode: str | None = None,
                 rowcount: int = 100_000) -> list[dict]:
    ph, codes = _doccode_in(party_type)
    where = [f'sm.doccode IN ({ph})', 'sm.docdate >= ?', 'sm.docdate <= ?']
    params = codes + [date_from, date_to]
    if branch:
        where.append('sm.branchcode = ?'); params.append(branch)
    if personcode:
        where.append('sm.cust_branch_code = ?'); params.append(personcode)
    sql = f"""
        SELECT sm.branchcode, sm.doccode, sm.docnumber, sm.docdate,
               sm.docnumber2, sm.cust_branch_code, sm.docvalue, sm.docvaluepay,
               sm.fatcurrentstatus, sm.docpaydue, sm.usercode,
               sm.personnewbal, sm.trans_time, sm.comments
        FROM   {DB}.stktransm sm
        WHERE  {' AND '.join(where)}
        ORDER  BY sm.docdate
    """
    return _rows(sql, params, rowcount=rowcount)


# ── 2. vouchers (cheques) ─────────────────────────────────────────────────────

def get_vouchers(party_type: str, date_from: str, date_to: str,
                 branch: str | None = None, personcode: str | None = None,
                 rowcount: int = 100_000) -> list[dict]:
    where = ['c.cheqdate >= ?', 'c.cheqdate <= ?', 'c.cheqvalue > 0']
    params = [date_from, date_to]
    if party_type == 'supplier':
        where.append('p.ptcode = ?'); params.append(SUPPLIER_PTCODE)
    else:
        where.append('(p.ptcode <> ? OR p.ptcode IS NULL)'); params.append(SUPPLIER_PTCODE)
    if branch:
        where.append('c.branchcode = ?'); params.append(branch)
    if personcode:
        where.append('c.personcode = ?'); params.append(personcode)
    sql = f"""
        SELECT c.branchcode, c.cheqsno, c.cheqno, c.ourcheqsno, c.financialdoccode,
               c.cheqtype, c.cheqdate, c.bankcode, c.personcode, c.cheqvalue,
               c.chequenote, c.personnewbal, c.banknewbal, c.blockinv, c.usercode,
               c.trans_time,
               p.ptcode        AS ptcode,
               p.personname    AS _party_name
        FROM   {DB}.cheques c
        LEFT   JOIN {DB}.personsdata p ON p.personcode = c.personcode
        WHERE  {' AND '.join(where)}
        ORDER  BY c.cheqdate
    """
    rows = _rows(sql, params, rowcount=rowcount)
    # personsdata name column varies by install; retry without it on failure.
    if rows and '_error' in rows[0] and 'personname' in rows[0]['_error']:
        sql2 = sql.replace(',\n               p.personname    AS _party_name', '')
        rows = _rows(sql2, params, rowcount=rowcount)
    return rows


# ── 3. allocations (chequestrans) ─────────────────────────────────────────────

def get_allocations(party_type: str, date_from: str, date_to: str,
                    branch: str | None = None, personcode: str | None = None,
                    rowcount: int = 200_000) -> list[dict]:
    ph, codes = _doccode_in(party_type)
    where = ['c.cheqdate >= ?', 'c.cheqdate <= ?', f'ct.doccode IN ({ph})']
    params = [date_from, date_to] + codes
    if branch:
        where.append('c.branchcode = ?'); params.append(branch)
    if personcode:
        where.append('c.personcode = ?'); params.append(personcode)
    sql = f"""
        SELECT ct.cheqsno, ct.cheqbranchcode, ct.branchcode, ct.doccode,
               ct.docnumber, ct.docdate, ct.docvaluepaid, ct.docvaluepaynow
        FROM   {DB}.chequestrans ct
        JOIN   {DB}.cheques c
          ON   c.cheqsno = ct.cheqsno AND c.branchcode = ct.cheqbranchcode
        WHERE  {' AND '.join(where)}
        ORDER  BY ct.docdate
    """
    return _rows(sql, params, rowcount=rowcount)


# ── 4. party balances (personsdata) — for the حصر equation ────────────────────

def get_party_balances(personcodes: list[str]) -> list[dict]:
    """
    Current + opening A/P balance per party from personsdata, in an OWED
    convention (positive = we owe the supplier):
        softech_balance = Σcredit − Σdebit
        opening_balance = personopencredit − personopendebit
    Batched over `personcodes` (bounded IN lists) so no full-table scan.
    """
    codes = [str(c).strip() for c in personcodes if str(c).strip()]
    if not codes:
        return []
    out: list[dict] = []
    BATCH = 400
    for i in range(0, len(codes), BATCH):
        chunk = codes[i:i + BATCH]
        ph = ','.join(['?'] * len(chunk))
        sql = f"""
            SELECT personcode, personname, ptcode, ptclassifcode,
                   (ISNULL(personcredit,0)+ISNULL(personcredit1,0)+ISNULL(personcredit2,0))
                   - (ISNULL(persondebit,0)+ISNULL(persondebit1,0)+ISNULL(persondebit2,0)) AS softech_balance,
                   (ISNULL(personopencredit,0) - ISNULL(personopendebit,0))                AS opening_balance
            FROM   {DB}.personsdata
            WHERE  personcode IN ({ph})
        """
        rows = _rows(sql, chunk, rowcount=BATCH)
        if rows and isinstance(rows[0], dict) and '_error' in rows[0]:
            return rows
        out += rows
    return out
