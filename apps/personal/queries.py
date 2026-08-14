"""
apps/personal/queries.py — SELECT-only SOFTECH person-scoped reads for the
personal dashboard.

ABSOLUTE RULE: SELECT only. Never INSERT / UPDATE / DELETE on SOFTECHDB9.

Doc codes
    '10'  purchase from supplier (+)     '120' return to supplier (-)
    '115' sale to customer (+)           '30'  sales return (-)

Person keys on stktransm  (VERIFIED against live SOFTECHDB9, 2026-08-13)
    stktransm has NO `personcode` column. The counterparty's personsdata.personcode
    is stored in `cust_branch_code` for BOTH roles — supplier on purchase docs,
    customer on sale docs — disambiguated by doccode:
        supplier docs → cust_branch_code + doccode IN ('10','120')  (purchase/return)
        customer docs → cust_branch_code + doccode IN ('115','30')  (sale/return)
    Confirmed: cust_branch_code='5014' on doccode 10 (supplier مورد عام غوالى),
    cust_branch_code='4231' on doccode 115 (employee-client د باسم فادى, whose
    row also carries phcode='01HD1269' — the walk-in PIC, which we do NOT match on).
    `supp_main_code` and `phcode` are separate columns and NOT the join key here.
    (This mirrors apps/procurement, whose production purchase query keys on
    stktransm.cust_branch_code.)

Financial person keys  (VERIFIED live 2026-08-13)
    cheques.personcode         — money for a person (supplier purchase cheques
                                 financialdoccode='10'; also customer cheques).
                                 Works for both 5014 and 4231.
    custpayments               — EMPTY in this install (module inactive) → dropped.
    branchesales is NOT used   — 4M-row sales register, unindexed personcode →
                                 a person scan times out inside the widget window.

All person-scoped functions are parameterised (jConnect PreparedStatement) so
the personcode is bound, never string-interpolated. Every function degrades to
{'error': ...} rather than raising, matching the finance/procurement query
convention — the widget UI renders the error inline instead of 500-ing.
"""
from __future__ import annotations

import datetime

from config.sybase import get_sybase_connection

DB = 'SOFTECHDB9.dbo'

# Bound the live scan; a single person's history is small but stktransm is huge
# and its docnumber is unindexed, so cap both rowcount and query time.
_DEFAULT_TIMEOUT = 45


def _safe(v):
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    return v


def _rows(sql: str, params: list | None = None,
          rowcount: int | None = None, timeout: int = _DEFAULT_TIMEOUT) -> list[dict]:
    """Run a SELECT and return list[dict]. Never raises — errors become []."""
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
        cur.close()
        return out
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _one(sql: str, params: list | None = None, timeout: int = _DEFAULT_TIMEOUT) -> dict:
    rows = _rows(sql, params, rowcount=1, timeout=timeout)
    return rows[0] if rows else {}


def _norm(rows: list[dict], mapping: dict[str, tuple]) -> list[dict]:
    """
    Rename raw row keys to stable frontend keys.

    IMPORTANT jConnect quirk: our CursorWrapper.description reads
    ResultSetMetaData.getColumnName(), which returns the BASE column name — so a
    plain-column ``SELECT c.cheqvalue AS amount`` still comes back keyed as
    ``cheqvalue`` (the alias is dropped). Aggregates like ``SUM(x) AS qty`` keep
    the alias because they have no base name. This maps each output key from the
    first present candidate, so payment rows carry pay_date/amount reliably.
    """
    out = []
    for r in rows:
        if isinstance(r, dict) and r.get('_error'):
            out.append(r)
            continue
        d = {}
        for out_key, cands in mapping.items():
            v = None
            for k in cands:
                if r.get(k) is not None:
                    v = r[k]
                    break
            d[out_key] = v
        out.append(d)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# PERSON SEARCH (for identity claiming)
# ══════════════════════════════════════════════════════════════════════════════

def search_persons(q: str, kind: str | None = None, limit: int = 25) -> list[dict]:
    """
    Search personsdata by name OR code so a user can claim their identity.
    kind='supplier' → ptcode='20'; kind='customer' → ptcode<>'20'; else all.
    Returns [{person_code, name, ptcode, ptclassifcode}].
    """
    q = (q or '').strip()
    if not q:
        return []
    where = ["pd.personname IS NOT NULL", "pd.personname != ''",
             "(pd.personname LIKE ? OR pd.personcode LIKE ?)"]
    like = f'%{q}%'
    params: list = [like, like]
    if kind == 'supplier':
        where.append("pd.ptcode = '20'")
    elif kind == 'customer':
        where.append("(pd.ptcode IS NULL OR pd.ptcode <> '20')")
    sql = f"""
        SELECT pd.personcode, pd.personname,
               COALESCE(pd.ptcode, '')        AS ptcode,
               COALESCE(pd.ptclassifcode, '') AS ptclassifcode
        FROM {DB}.personsdata pd
        WHERE {' AND '.join(where)}
        ORDER BY pd.personname
    """
    try:
        rows = _rows(sql, params, rowcount=limit)
    except Exception as e:  # pragma: no cover — surfaced to UI
        return [{'_error': str(e)[:200]}]
    return [
        {
            'person_code':   str(r.get('personcode') or '').strip(),
            'name':          r.get('personname') or '',
            'ptcode':        r.get('ptcode') or '',
            'ptclassifcode': r.get('ptclassifcode') or '',
        }
        for r in rows if not r.get('_error')
    ] or ([rows[0]] if rows and rows[0].get('_error') else [])


def get_person(person_code: str) -> dict:
    """Fetch a single personsdata row by code (used to cache the label on claim)."""
    pc = str(person_code or '').strip()
    if not pc:
        return {}
    try:
        r = _one(
            f"SELECT pd.personcode, pd.personname, "
            f"COALESCE(pd.ptcode,'') AS ptcode, COALESCE(pd.ptclassifcode,'') AS ptclassifcode "
            f"FROM {DB}.personsdata pd WHERE pd.personcode = ?",
            [pc],
        )
    except Exception:
        return {}
    if not r:
        return {}
    return {
        'person_code':   str(r.get('personcode') or '').strip(),
        'name':          r.get('personname') or '',
        'ptcode':        r.get('ptcode') or '',
        'ptclassifcode': r.get('ptclassifcode') or '',
    }


# ══════════════════════════════════════════════════════════════════════════════
# SUPPLIER — purchases / returns (stktrans) + money (cheques / branchesales)
# ══════════════════════════════════════════════════════════════════════════════

def supplier_transactions(person_code: str, days: int = 90, limit: int = 300) -> dict:
    """Recent purchase/return lines + a headline summary for a supplier personcode."""
    pc = str(person_code or '').strip()
    if not pc:
        return {'error': 'no person_code'}
    try:
        summary = _one(f"""
            SELECT COUNT(*)                                                    AS doc_count,
                   SUM(CASE sm.doccode WHEN '10' THEN sm.docvalue
                                       WHEN '120' THEN -sm.docvalue ELSE 0 END) AS net_value,
                   MIN(sm.docdate)                                            AS first_doc,
                   MAX(sm.docdate)                                            AS last_doc
            FROM {DB}.stktransm sm
            WHERE sm.cust_branch_code = ?
              AND sm.doccode IN ('10','120')
              AND sm.docdate >= DATEADD(day, -?, GETDATE())
        """, [pc, int(days)])

        lines = _rows(f"""
            SELECT sm.doccode, sm.docnumber, sm.docdate, sm.branchcode,
                   st.itemcode,
                   MAX(i.itemname)                         AS item_name,
                   MAX(sm.comments)                        AS doc_comment,
                   MAX(u.userid)                           AS entered_by,
                   SUM(st.transqty)                        AS qty,
                   SUM(COALESCE(st.transprice_total, 0))   AS line_value,
                   sm.docvalue
            FROM {DB}.stktransm sm
            JOIN {DB}.stktrans st
              ON  st.branchcode = sm.branchcode AND st.doccode = sm.doccode
              AND st.docnumber  = sm.docnumber  AND st.docdate = sm.docdate
            LEFT JOIN {DB}.items i ON i.itemcode = st.itemcode
            LEFT JOIN {DB}.users u ON u.usercode = sm.usercode
            WHERE sm.cust_branch_code = ?
              AND sm.doccode IN ('10','120')
              AND sm.docdate >= DATEADD(day, -?, GETDATE())
              AND st.itemcode IS NOT NULL AND st.transqty > 0
            GROUP BY sm.doccode, sm.docnumber, sm.docdate, sm.branchcode,
                     st.itemcode, sm.docvalue
            ORDER BY sm.docdate DESC
        """, [pc, int(days)], rowcount=limit)
    except Exception as e:
        return {'error': str(e)[:200]}
    return {'summary': summary, 'lines': lines, 'days': int(days)}


def _person_cheques(pc: str, days: int, limit: int) -> list[dict]:
    """Enriched cheque rows for a personcode — the shared source for both
    supplier_payments and customer_payments. Includes the fields the drill-down
    needs: cheque #, branch, type, note (chequenote), running balance."""
    raw = _rows(f"""
        SELECT c.cheqsno, c.cheqno, c.cheqdate, c.cheqvalue, c.branchcode,
               c.bankcode, c.financialdoccode, c.cheqtype, c.chequenote,
               c.personnewbal, c.handedto, u.userid,
               bk.bankname, bk.banktype
        FROM {DB}.cheques c
        LEFT JOIN {DB}.users u  ON u.usercode  = c.usercode
        LEFT JOIN {DB}.banks bk ON bk.bankcode = c.bankcode
        WHERE c.personcode = ?
          AND c.cheqvalue > 0
          AND c.cheqdate >= DATEADD(day, -?, GETDATE())
        ORDER BY c.cheqdate DESC
    """, [pc, int(days)], rowcount=limit)
    return _norm(raw, {
        'cheqsno': ('cheqsno',), 'cheqno': ('cheqno',),
        'pay_date': ('cheqdate',), 'amount': ('cheqvalue',),
        'branchcode': ('branchcode',), 'bankcode': ('bankcode',),
        'financialdoccode': ('financialdoccode',), 'cheqtype': ('cheqtype',),
        'note': ('chequenote',), 'balance': ('personnewbal',),
        'handedto': ('handedto',), 'user': ('userid',),
        # bank/cash-box: banktype 0 = خزينة (cash), 1 = bank → real payment method
        'bankname': ('bankname',), 'banktype': ('banktype',),
    })


def supplier_payments(person_code: str, days: int = 180, limit: int = 300) -> dict:
    """
    Cheques issued to a supplier (money OUT). Keyed on cheques.personcode
    (VERIFIED: personcode=5014 → purchase cheques, financialdoccode='10').

    NOTE: branchesales is deliberately NOT queried — it is the 4M-row *sales*
    payment register (money received from customers) with an unindexed
    personcode, so a person scan times out and would be conceptually wrong for
    a supplier anyway.
    """
    pc = str(person_code or '').strip()
    if not pc:
        return {'error': 'no person_code'}
    out: dict = {'days': int(days)}
    try:
        out['cheques'] = _person_cheques(pc, int(days), limit)
    except Exception as e:
        out['cheques'] = [{'_error': str(e)[:200]}]
    return out


# ══════════════════════════════════════════════════════════════════════════════
# CUSTOMER — sales / returns (stktrans by phcode) + money
# ══════════════════════════════════════════════════════════════════════════════

def customer_transactions(person_code: str, days: int = 180, limit: int = 300) -> dict:
    """Recent sale/return lines + summary for a customer personcode (stktransm.personcode)."""
    pc = str(person_code or '').strip()
    if not pc:
        return {'error': 'no person_code'}
    try:
        summary = _one(f"""
            SELECT COUNT(*)                                                     AS doc_count,
                   SUM(CASE sm.doccode WHEN '115' THEN sm.docvalue
                                       WHEN '30' THEN -sm.docvalue ELSE 0 END)  AS net_value,
                   MIN(sm.docdate)                                             AS first_doc,
                   MAX(sm.docdate)                                             AS last_doc
            FROM {DB}.stktransm sm
            WHERE sm.cust_branch_code = ?
              AND sm.doccode IN ('115','30')
              AND sm.docdate >= DATEADD(day, -?, GETDATE())
        """, [pc, int(days)])

        lines = _rows(f"""
            SELECT sm.doccode, sm.docnumber, sm.docdate, sm.branchcode,
                   st.itemcode,
                   MAX(i.itemname)                         AS item_name,
                   MAX(sm.comments)                        AS doc_comment,
                   MAX(u.userid)                           AS entered_by,
                   SUM(st.transqty)                        AS qty,
                   SUM(COALESCE(st.transprice_total, 0))   AS line_value,
                   sm.docvalue
            FROM {DB}.stktransm sm
            JOIN {DB}.stktrans st
              ON  st.branchcode = sm.branchcode AND st.doccode = sm.doccode
              AND st.docnumber  = sm.docnumber  AND st.docdate = sm.docdate
            LEFT JOIN {DB}.items i ON i.itemcode = st.itemcode
            LEFT JOIN {DB}.users u ON u.usercode = sm.usercode
            WHERE sm.cust_branch_code = ?
              AND sm.doccode IN ('115','30')
              AND sm.docdate >= DATEADD(day, -?, GETDATE())
              AND st.itemcode IS NOT NULL AND st.transqty > 0
            GROUP BY sm.doccode, sm.docnumber, sm.docdate, sm.branchcode,
                     st.itemcode, sm.docvalue
            ORDER BY sm.docdate DESC
        """, [pc, int(days)], rowcount=limit)
    except Exception as e:
        return {'error': str(e)[:200]}
    return {'summary': summary, 'lines': lines, 'days': int(days)}


def customer_payments(person_code: str, days: int = 180, limit: int = 300) -> dict:
    """
    Customer money movements: cheque receipts keyed on cheques.personcode.

    NOTE: two SOFTECH tables are deliberately NOT queried here —
      • branchesales — 4M-row sales register, unindexed personcode → times out
        inside the widget window (see supplier_payments).
      • custpayments — VERIFIED EMPTY in this SOFTECH install (0 rows total,
        module inactive, like empsalaries/acctrans). Querying it was a guaranteed
        wasted round-trip, so it is dropped. Columns, if the module is ever
        activated: custcode, custpaydate, custpayvalue, custdeductvalue.
    So cheques is the authoritative customer-money source here.
    """
    pc = str(person_code or '').strip()
    if not pc:
        return {'error': 'no person_code'}
    out: dict = {'days': int(days)}
    try:
        out['cheques'] = _person_cheques(pc, int(days), limit)
    except Exception as e:
        out['cheques'] = [{'_error': str(e)[:200]}]
    return out
