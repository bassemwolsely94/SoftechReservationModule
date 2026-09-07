"""
apps/finance/queries/sybase_accounting.py

Queries for confirmed high-value financial tables discovered in Phase 0.

ALL queries are SELECT-only.
ABSOLUTE RULE: never INSERT / UPDATE / DELETE on any Sybase connection.

Tables covered (column names VERIFIED from live SOFTECHDB9 schema)
──────────────────────────────────────────────────────────────────
  accitems        — chart of accounts (6-level hierarchy, 148 rows)
  acctrans/2/3    — double-entry journal (ALL EMPTY — accounting module inactive)
  branchesales    — payment register, 4M rows, one row per payment line
  cheques         — cheque register, 375K rows
  bankstrans      — bank movement ledger
  branchescash    — cash balance per branch
  dailyexpenses   — expense transactions (176K rows)
  expenses        — expense type master (93 rows)
  custpayments    — customer payment records
  empsalaries     — payroll (0 rows — module not active)
  banks           — bank/cash-box master (29 rows)
  paymentstypes   — payment method code → description

Connection reuse pattern
────────────────────────
Every function accepts an optional ``conn`` argument.  When None the
function opens its own connection and closes it in a ``finally`` block.
When a connection is passed in (e.g. from FinanceSyncEngine._get_conn()),
the function borrows it — it does NOT close it.  This eliminates the
JPype/JVM connection overhead when multiple queries share one connection.

Sybase ASE 12.5 quirks
──────────────────────
- No CTEs.
- SELECT TOP n NOT SUPPORTED — use SET ROWCOUNT n before SELECT instead.
- CONVERT(type, expr) for casts.
- ISNULL(expr, default) for null handling.
- String concat: expr + expr (not CONCAT).
"""

from __future__ import annotations
from typing import Any
import datetime

from config.sybase import get_sybase_connection

DB = "SOFTECHDB9.dbo"


# ── helpers ──────────────────────────────────────────────────────────────────

def _rows_as_dicts(cursor, rows: list) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


def _safe(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode('utf-8', errors='replace')
        except Exception:
            return repr(v)
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.isoformat()
    return v


def _clean(row: dict) -> dict:
    return {k: _safe(v) for k, v in row.items()}


def _period_clause(col: str, year: int, month: int) -> str:
    from calendar import monthrange
    last_day = monthrange(year, month)[1]
    return f"{col} >= '{year}-{month:02d}-01' AND {col} <= '{year}-{month:02d}-{last_day:02d}'"


def _conn_ctx(conn):
    """Return (conn, is_owned).  If conn is None, open a new one."""
    if conn is not None:
        return conn, False
    return get_sybase_connection(), True


def _fetch(conn, sql: str, rowcount: int | None = None) -> tuple[list, list[str]]:
    """
    Execute ``sql`` on ``conn`` and return (rows, col_names).
    Optionally prepend SET ROWCOUNT for Sybase ASE 12.5 (no SELECT TOP).

    CRITICAL: SET ROWCOUNT persists for the lifetime of a Sybase connection
    session.  When the connection is shared (reused across multiple queries),
    we MUST reset it to 0 (= no limit) after every limited query, otherwise
    all subsequent queries on the same connection will be silently truncated.
    """
    cur = conn.cursor()
    if rowcount:
        cur.execute(f'SET ROWCOUNT {rowcount}')
    try:
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
    finally:
        if rowcount:
            # Always reset — even on exception — so the shared connection
            # is left in a clean state for the next query.
            try:
                cur.execute('SET ROWCOUNT 0')
            except Exception:
                pass
    return rows, cols


# ══════════════════════════════════════════════════════════════════════════════
# 1. CHART OF ACCOUNTS (accitems)
# ══════════════════════════════════════════════════════════════════════════════

# Arabic keyword → account_type mapping (applied to accitemname)
_ARABIC_ACCT_TYPE: list[tuple[str, str]] = [
    ('مصروف',   'expense'),
    ('مصاريف',  'expense'),
    ('إيراد',   'revenue'),
    ('دخل',     'revenue'),
    ('أصول',    'asset'),
    ('نقدي',    'asset'),
    ('نقدية',   'asset'),
    ('خزينة',   'asset'),
    ('صندوق',   'asset'),
    ('مخزون',   'asset'),
    ('بنك',     'asset'),
    ('التزام',  'liability'),
    ('دائنون',  'liability'),
    ('مورد',    'liability'),
    ('رأس مال', 'equity'),
    ('ملكية',   'equity'),
    ('أرباح',   'equity'),
    ('تكلفة',   'cogs'),
]


def _infer_account_type(name_ar: str) -> str:
    if not name_ar:
        return 'unknown'
    for keyword, atype in _ARABIC_ACCT_TYPE:
        if keyword in name_ar:
            return atype
    return 'unknown'


def _infer_nature(accnature) -> str:
    v = str(accnature or '').strip()
    if v in ('1', 'D', 'd', 'debit', 'مدين'):
        return 'debit'
    if v in ('2', 'C', 'c', 'credit', 'دائن', 'دائنة'):
        return 'credit'
    return 'debit'


def _accitems_level_and_parent(row: dict) -> tuple[int, str | None]:
    """
    Determine level (1–6) and parent_code from the denormalised accitemlN fields.

    SOFTECH COA stores the full path as:
      acciteml1 = root code
      acciteml2 = level-2 code (or null if account IS at level 1)
      ...
      accitemlN = accitemcode  (the account's own code, at the deepest level)

    Parent = value at level (depth - 1), or None for roots.
    """
    levels = [
        str(row.get('acciteml1') or '').strip(),
        str(row.get('acciteml2') or '').strip(),
        str(row.get('acciteml3') or '').strip(),
        str(row.get('acciteml4') or '').strip(),
        str(row.get('acciteml5') or '').strip(),
        str(row.get('acciteml6') or '').strip(),
    ]
    code = str(row.get('accitemcode') or '').strip()
    # Find the deepest non-empty level
    depth = 0
    for i, v in enumerate(levels):
        if v:
            depth = i + 1
    if depth == 0:
        return 1, None
    parent_code = levels[depth - 2] if depth >= 2 else None
    return depth, (parent_code if parent_code else None)


def get_chart_of_accounts(limit: int = 5000, conn=None) -> list[dict]:
    """
    Return all rows from accitems (148 rows).
    Verified columns: accitemcode, accitemname (Arabic), acciteml1..l6,
                      accnature, acclast (1=leaf posting account).
    """
    sql = f'SELECT * FROM {DB}.accitems ORDER BY accitemcode'
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql, rowcount=limit)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_chart_of_accounts_structured(conn=None) -> list[dict]:
    """
    Return COA rows enriched with derived ``level`` and ``parent_code`` fields,
    ready to feed directly into FinanceSyncEngine._sync_chart_of_accounts().

    Each dict has:
      accitemcode, accitemname, acciteml1..l6, accnature, acclast,
      _level (int 1–6), _parent_code (str | None),
      _account_type (str), _nature (str)
    """
    sql = f"""
        SELECT
            accitemcode,
            accitemname,
            acciteml1, acciteml2, acciteml3,
            acciteml4, acciteml5, acciteml6,
            accnature,
            acclast
        FROM {DB}.accitems
        ORDER BY accitemcode
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        result = []
        for r in rows:
            d = _clean(dict(zip(cols, r)))
            level, parent = _accitems_level_and_parent(d)
            d['_level'] = level
            d['_parent_code'] = parent
            d['_account_type'] = _infer_account_type(str(d.get('accitemname') or ''))
            d['_nature'] = _infer_nature(d.get('accnature'))
            result.append(d)
        return result
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_accitems_columns() -> list[str]:
    """Return column names of accitems (for schema-adaptive mapping)."""
    _conn, _own = _conn_ctx(None)
    try:
        rows, cols = _fetch(_conn, f'SELECT * FROM {DB}.accitems', rowcount=1)
        return cols
    except Exception:
        return []
    finally:
        if _own:
            _conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 2. DOUBLE-ENTRY JOURNAL (acctrans / acctrans2 / acctrans3)
#    NOTE: ALL THREE TABLES ARE EMPTY — accounting module not active in SOFTECH.
#    These functions are retained for future use.
# ══════════════════════════════════════════════════════════════════════════════

def get_acctrans_columns(table: str = 'acctrans', conn=None) -> list[str]:
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, f'SELECT * FROM {DB}.{table}', rowcount=1)
        return cols
    except Exception:
        return []
    finally:
        if _own:
            _conn.close()


def get_acctrans_by_month(
    year: int,
    month: int,
    table: str = 'acctrans',
    date_col: str = 'acctransdate',
    limit: int = 50_000,
    conn=None,
) -> list[dict]:
    """Fetch double-entry journal lines for the given month.  Likely returns [] (tables empty)."""
    period = _period_clause(date_col, year, month)
    sql = f"SELECT * FROM {DB}.{table} WHERE {period} ORDER BY {date_col}"
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql, rowcount=limit)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e), 'table': table}]
    finally:
        if _own:
            _conn.close()


def get_acctrans_monthly_totals(
    year: int,
    month: int,
    table: str = 'acctrans',
    date_col: str = 'acctransdate',
    debit_col: str = 'acctransdebit',
    credit_col: str = 'acctranscredit',
    acc_col: str = 'accitemcode',
    conn=None,
) -> list[dict]:
    """Aggregate acctrans by account for the month.  Likely returns [] (tables empty)."""
    period = _period_clause(date_col, year, month)
    sql = f"""
        SELECT
            {acc_col}                           AS account_code,
            SUM(ISNULL({debit_col},  0))        AS total_debit,
            SUM(ISNULL({credit_col}, 0))        AS total_credit,
            SUM(ISNULL({debit_col},  0))
            - SUM(ISNULL({credit_col}, 0))      AS net_balance,
            COUNT(*)                            AS line_count
        FROM   {DB}.{table}
        WHERE  {period}
        GROUP  BY {acc_col}
        ORDER  BY {acc_col}
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 3. PAYMENT REGISTER (branchesales) — 4,032,056 rows
#
# VERIFIED columns: branchcode, doccode, docnumber, docdate, paymentsno,
#   paymenttype, paymentvalue, personcode, cheqdate, creditcardtype,
#   trans_time, intervalcode, bcurrency, bcrate
#
# THIS IS A PAYMENT REGISTER (one row per payment line per invoice),
# NOT a pre-aggregated sales table.  direction = always 'in' (money received).
# ══════════════════════════════════════════════════════════════════════════════

# Payment type code → payment method (heuristic; overridden by paymentstypes master)
_PAYTYPE_METHOD_MAP: dict[str, str] = {
    '1': 'cash',
    '2': 'cheque',
    '3': 'card',
    '4': 'transfer',
    '5': 'credit',
    '6': 'cash',      # may vary by SOFTECH version
    '7': 'card',
}


def _map_payment_method(paymenttype, paytypes_master: dict | None = None) -> str:
    """Map paymenttype code to TreasuryMovement.payment_method choice."""
    code = str(paymenttype or '').strip()
    if paytypes_master and code in paytypes_master:
        descr = paytypes_master[code].lower()
        if any(k in descr for k in ('نقد', 'cash', 'كاش')):
            return 'cash'
        if any(k in descr for k in ('شيك', 'cheque', 'check')):
            return 'cheque'
        if any(k in descr for k in ('بطاقة', 'card', 'visa', 'كارت')):
            return 'card'
        if any(k in descr for k in ('تحويل', 'transfer', 'wire')):
            return 'transfer'
        if any(k in descr for k in ('آجل', 'credit', 'تسهيل')):
            return 'credit'
    return _PAYTYPE_METHOD_MAP.get(code, 'other')


def get_branchesales_columns(conn=None) -> list[str]:
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, f'SELECT * FROM {DB}.branchesales', rowcount=1)
        return cols
    except Exception:
        return []
    finally:
        if _own:
            _conn.close()


def get_branchesales_by_month(year: int, month: int, conn=None) -> list[dict]:
    """
    Fetch ALL individual payment rows for the month.
    WARNING: up to ~100K rows per month from a 4M-row table.
    For analytics, prefer get_branchesales_monthly_aggregated().
    """
    period = _period_clause('docdate', year, month)
    sql = f"SELECT * FROM {DB}.branchesales WHERE {period} ORDER BY docdate"
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_branchesales_monthly_aggregated(
    year: int,
    month: int,
    conn=None,
) -> list[dict]:
    """
    Aggregate branchesales by (branchcode, paymenttype) for the given month.

    Returns one row per (branch × payment-type) instead of one row per transaction.
    This is the efficient path for syncing TreasuryMovement monthly summaries.

    Returns: [{branchcode, paymenttype, total_payments, payment_count, has_cheques}]
    """
    period = _period_clause('docdate', year, month)
    sql = f"""
        SELECT
            branchcode,
            paymenttype,
            SUM(ISNULL(paymentvalue, 0))    AS total_payments,
            COUNT(*)                        AS payment_count,
            SUM(CASE WHEN cheqdate IS NOT NULL THEN 1 ELSE 0 END) AS has_cheques
        FROM   {DB}.branchesales
        WHERE  {period}
        AND    paymentvalue > 0
        GROUP  BY branchcode, paymenttype
        ORDER  BY branchcode, paymenttype
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_branchesales_ytd(year: int, conn=None) -> list[dict]:
    """Monthly payment totals by branch for the full year."""
    sql = f"""
        SELECT
            branchcode,
            MONTH(docdate)          AS month_num,
            SUM(paymentvalue)       AS total_payments,
            COUNT(*)                AS payment_count
        FROM   {DB}.branchesales
        WHERE  YEAR(docdate) = {year}
        GROUP  BY branchcode, MONTH(docdate)
        ORDER  BY branchcode, month_num
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 4. CHEQUES — 375,870 rows
#
# VERIFIED columns: cheqsno, cheqdate, cheqvalue, cheqtype, bankcode,
#   personcode, wentto_bankstrans, branchcode, financialdoccode
#
# cheqtype='10' = cash/POS entry (NOT an actual cheque — skip for cheque ETL)
# cheqtype='20' = actual bank cheque
# financialdoccode: e.g. '10'=purchase cheque (OUT), '115'=sales receipt (IN)
# ══════════════════════════════════════════════════════════════════════════════

def get_cheques_columns(conn=None) -> list[str]:
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, f'SELECT * FROM {DB}.cheques', rowcount=1)
        return cols
    except Exception:
        return []
    finally:
        if _own:
            _conn.close()


def get_cheques_by_month(year: int, month: int, limit: int = 2000, conn=None) -> list[dict]:
    """
    Fetch ALL cheque records for the month (including cheqtype='10' cash entries).
    Verified date column: cheqdate (NOT chequedate).
    """
    period = _period_clause('cheqdate', year, month)
    sql = f"SELECT * FROM {DB}.cheques WHERE {period} ORDER BY cheqdate"
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql, rowcount=limit)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_actual_cheques_by_month(
    year: int,
    month: int,
    conn=None,
) -> list[dict]:
    """
    Fetch ACTUAL bank cheques only (cheqtype = '20') for the month.
    Excludes cash/POS entries (cheqtype='10').

    Returned rows are enriched with a ``_direction`` field:
      'in'  — cheque received from customer (financialdoccode='115' or similar)
      'out' — cheque issued to supplier (financialdoccode='10')
    """
    period = _period_clause('cheqdate', year, month)
    sql = f"""
        SELECT
            cheqsno,
            cheqdate,
            cheqvalue,
            cheqtype,
            bankcode,
            personcode,
            branchcode,
            financialdoccode,
            wentto_bankstrans
        FROM   {DB}.cheques
        WHERE  {period}
        AND    cheqtype = '20'
        AND    cheqvalue > 0
        ORDER  BY cheqdate
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        result = []
        for r in rows:
            d = _clean(dict(zip(cols, r)))
            # Infer direction from financialdoccode
            fdc = str(d.get('financialdoccode') or '').strip()
            # Purchase doccodes (10, 120...) = cheque issued OUT to supplier
            d['_direction'] = 'out' if fdc in ('10', '11', '120') else 'in'
            result.append(d)
        return result
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 5. BANK TRANSACTIONS (bankstrans)
# ══════════════════════════════════════════════════════════════════════════════

def get_bankstrans_by_month(year: int, month: int, limit: int = 2000, conn=None) -> list[dict]:
    """Fetch bank transaction movements for the month."""
    period = _period_clause('transdate', year, month)
    sql = f"SELECT * FROM {DB}.bankstrans WHERE {period} ORDER BY transdate"
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql, rowcount=limit)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 6. BANKS MASTER — 29 rows (bank accounts + cash boxes)
#
# VERIFIED columns: bankcode, bankname, banktype, bankaccountbalance, branchcode
# banktype=0 → خزينة (cash box)
# banktype=1 → bank account
# ══════════════════════════════════════════════════════════════════════════════

def get_banks_all(conn=None) -> list[dict]:
    """
    Return all 29 bank/cash-box records from the banks master.
    Useful for mapping bankcode in cheques/bankstrans to names.
    """
    sql = f"""
        SELECT
            bankcode,
            bankname,
            banktype,
            ISNULL(bankaccountbalance, 0) AS bankaccountbalance,
            branchcode
        FROM {DB}.banks
        ORDER BY banktype DESC, bankcode
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        result = [_clean(dict(zip(cols, r))) for r in rows]
        # Add human-readable type label
        for row in result:
            bt = str(row.get('banktype') or '').strip()
            row['_type_label'] = 'خزينة' if bt == '0' else 'حساب بنكي'
        return result
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_banks_balance_dict(conn=None) -> dict[str, str]:
    """Return {bankcode: bankname} — used for fast lookup in cheque enrichment."""
    rows = get_banks_all(conn=conn)
    return {str(r.get('bankcode') or ''): str(r.get('bankname') or '') for r in rows if r.get('bankcode')}


# ══════════════════════════════════════════════════════════════════════════════
# 7. CASH BALANCE (branchescash)
# ══════════════════════════════════════════════════════════════════════════════

def get_branchescash_snapshot(conn=None) -> list[dict]:
    """Current cash balance per branch (latest snapshot in branchescash)."""
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, f'SELECT * FROM {DB}.branchescash ORDER BY branchcode', rowcount=200)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        # Fallback: older SOFTECH versions use branchid instead of branchcode
        try:
            rows2, cols2 = _fetch(_conn, f'SELECT * FROM {DB}.branchescash', rowcount=200)
            return [_clean(dict(zip(cols2, r))) for r in rows2]
        except Exception as e2:
            return [{'_error': str(e2)}]
    finally:
        if _own:
            _conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 8. EXPENSES — dailyexpenses (176K rows) + expenses master (93 rows)
#
# VERIFIED columns
# dailyexpenses: branchcode, expensedate, expcode, expvalue, expcomment,
#                cheqsno, costcentercode, branchcode2, expusercode
# expenses:      expcode, expdescr, expclassifcode, exptype,
#                expaccitemcode, allmonths
# ══════════════════════════════════════════════════════════════════════════════

# exptype → EXPENSE_CATEGORY_CHOICES mapping (heuristic for SOFTECH)
_EXPTYPE_CATEGORY: dict[str, str] = {
    '1':  'payroll',
    '2':  'rent',
    '3':  'utilities',
    '4':  'maintenance',
    '5':  'fuel',
    '6':  'delivery',
    '7':  'marketing',
    '8':  'admin',
    '9':  'finance_cost',
    '10': 'bank_charges',
    '11': 'taxes',
    '12': 'insurance',
}

# Arabic keyword fallback (applied to expdescr if exptype mapping fails)
_EXPDESCR_KEYWORDS: list[tuple[str, str]] = [
    ('راتب',    'payroll'),
    ('مرتب',    'payroll'),
    ('موظف',    'payroll'),
    ('إيجار',   'rent'),
    ('كهرباء',  'utilities'),
    ('مياه',    'utilities'),
    ('اتصال',   'utilities'),
    ('تليفون',  'utilities'),
    ('إنترنت',  'utilities'),
    ('وقود',    'fuel'),
    ('بنزين',   'fuel'),
    ('صيانة',   'maintenance'),
    ('تسليم',   'delivery'),
    ('شحن',     'delivery'),
    ('توصيل',   'delivery'),
    ('تسويق',   'marketing'),
    ('إعلان',   'marketing'),
    ('إداري',   'admin'),
    ('مكتب',    'admin'),
    ('بنك',     'bank_charges'),
    ('رسوم',    'bank_charges'),
    ('ضريبة',   'taxes'),
    ('ضرائب',   'taxes'),
    ('تأمين',   'insurance'),
    ('استهلاك', 'depreciation'),
    ('فاقد',    'shrinkage'),
    ('عجز',     'shrinkage'),
    ('منتهي',   'expiry'),
]


def _infer_expense_category(exptype, expdescr: str) -> str:
    cat = _EXPTYPE_CATEGORY.get(str(exptype or '').strip())
    if cat:
        return cat
    if expdescr:
        for keyword, cat2 in _EXPDESCR_KEYWORDS:
            if keyword in expdescr:
                return cat2
    return 'other'


def get_expenses_master(conn=None) -> list[dict]:
    """
    Return all 93 rows from the expenses type master table.
    Verified columns: expcode, expdescr, expclassifcode, exptype, expaccitemcode.
    """
    sql = f"SELECT expcode, expdescr, expclassifcode, exptype, expaccitemcode, allmonths FROM {DB}.expenses ORDER BY expcode"
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        # Fallback: SELECT *
        try:
            rows2, cols2 = _fetch(_conn, f'SELECT * FROM {DB}.expenses ORDER BY expcode')
            return [_clean(dict(zip(cols2, r))) for r in rows2]
        except Exception as e2:
            return [{'_error': str(e2)}]
    finally:
        if _own:
            _conn.close()


def get_expenses_master_dict(conn=None) -> dict[str, dict]:
    """
    Return {expcode: {expdescr, expclassifcode, exptype, expaccitemcode}} for fast lookup.
    """
    rows = get_expenses_master(conn=conn)
    return {
        str(r.get('expcode') or ''): r
        for r in rows
        if r.get('expcode') and '_error' not in r
    }


def get_dailyexpenses_by_month(
    year: int,
    month: int,
    limit: int = 10_000,
    conn=None,
) -> list[dict]:
    """
    Raw dailyexpenses rows for the month.
    Verified date column: expensedate (NOT transdate).
    """
    period = _period_clause('expensedate', year, month)
    sql = f"SELECT * FROM {DB}.dailyexpenses WHERE {period} ORDER BY expensedate"
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql, rowcount=limit)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_dailyexpenses_with_master_by_month(
    year: int,
    month: int,
    limit: int = 10_000,
    conn=None,
) -> list[dict]:
    """
    Expense transactions joined with the expenses type master for the month.

    JOIN: dailyexpenses.expcode = expenses.expcode

    Returns rows with:
      branchcode, expensedate, expcode, expvalue, expcomment,
      cheqsno, costcentercode, expusercode,
      expdescr, expclassifcode, exptype, expaccitemcode

    Each row also has derived ``_category`` (maps to ExpenseRecord.category choices).
    """
    period = _period_clause('d.expensedate', year, month)
    sql = f"""
        SELECT
            d.branchcode,
            d.expensedate,
            d.expcode,
            ISNULL(d.expvalue, 0)    AS expvalue,
            d.expcomment,
            d.cheqsno,
            d.costcentercode,
            d.expusercode,
            e.expdescr,
            e.expclassifcode,
            e.exptype,
            e.expaccitemcode
        FROM   {DB}.dailyexpenses d
        LEFT   JOIN {DB}.expenses e ON e.expcode = d.expcode
        WHERE  {period}
        AND    d.expvalue > 0
        ORDER  BY d.expensedate, d.branchcode
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql, rowcount=limit)
        result = []
        for r in rows:
            d = _clean(dict(zip(cols, r)))
            d['_category'] = _infer_expense_category(
                d.get('exptype'),
                str(d.get('expdescr') or ''),
            )
            result.append(d)
        return result
    except Exception as e:
        # Fallback: raw dailyexpenses without join (e.g. if 'expenses' table name differs)
        try:
            return get_dailyexpenses_by_month(year, month, limit=limit, conn=_conn)
        except Exception:
            return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_expenses_monthly_totals(year: int, month: int, conn=None) -> list[dict]:
    """
    Aggregate daily expenses by expense type for the month.
    Returns: [{expcode, expdescr, total_amount, record_count}] sorted by total DESC.
    """
    period = _period_clause('d.expensedate', year, month)
    sql = f"""
        SELECT
            d.expcode,
            e.expdescr,
            SUM(d.expvalue)  AS total_amount,
            COUNT(*)         AS record_count
        FROM   {DB}.dailyexpenses d
        LEFT   JOIN {DB}.expenses e ON e.expcode = d.expcode
        WHERE  {period}
        GROUP  BY d.expcode, e.expdescr
        ORDER  BY total_amount DESC
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_dailyexpenses_by_branch_month(year: int, month: int, conn=None) -> list[dict]:
    """
    Aggregate daily expenses by branch for the month.
    Returns: [{branchcode, total_expenses, expense_count}]
    """
    period = _period_clause('expensedate', year, month)
    sql = f"""
        SELECT
            branchcode,
            SUM(ISNULL(expvalue, 0)) AS total_expenses,
            COUNT(*)                  AS expense_count
        FROM   {DB}.dailyexpenses
        WHERE  {period}
        GROUP  BY branchcode
        ORDER  BY branchcode
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_expenses_columns(table: str = 'expenses', conn=None) -> list[str]:
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, f'SELECT * FROM {DB}.{table}', rowcount=1)
        return cols
    except Exception:
        return []
    finally:
        if _own:
            _conn.close()


def get_expenses_by_month(
    year: int,
    month: int,
    table: str = 'dailyexpenses',
    date_col: str = 'expensedate',
    limit: int = 5000,
    conn=None,
) -> list[dict]:
    """Legacy wrapper — use get_dailyexpenses_with_master_by_month() for new code."""
    period = _period_clause(date_col, year, month)
    sql = f"SELECT * FROM {DB}.{table} WHERE {period} ORDER BY {date_col}"
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql, rowcount=limit)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e), 'table': table}]
    finally:
        if _own:
            _conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 9. PAYMENT TYPES MASTER (paymentstypes)
# ══════════════════════════════════════════════════════════════════════════════

def get_paymenttypes_master(conn=None) -> list[dict]:
    """
    Return all payment type code → description rows from paymentstypes.
    Used to enrich branchesales.paymenttype → human-readable label.
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, f'SELECT * FROM {DB}.paymentstypes ORDER BY 1', rowcount=100)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_paymenttypes_dict(conn=None) -> dict[str, str]:
    """
    Return {paymenttype_code: description} for fast lookup.
    Tries common column name patterns (paymenttype/paymenttypedescr, id/name, etc.).
    """
    rows = get_paymenttypes_master(conn=conn)
    if not rows or '_error' in rows[0]:
        return {}
    # Auto-detect key/value columns
    if not rows:
        return {}
    sample = rows[0]
    keys = list(sample.keys())
    code_col = next((k for k in keys if 'code' in k.lower() or k == 'id' or 'type' in k.lower()), keys[0] if keys else None)
    name_col = next((k for k in keys if 'descr' in k.lower() or 'name' in k.lower()), keys[-1] if len(keys) > 1 else None)
    if not code_col or not name_col:
        return {}
    return {str(r.get(code_col) or ''): str(r.get(name_col) or '') for r in rows}


# ══════════════════════════════════════════════════════════════════════════════
# 10. CUSTOMER PAYMENTS (custpayments)
# ══════════════════════════════════════════════════════════════════════════════

def get_custpayments_by_month(year: int, month: int, limit: int = 5000, conn=None) -> list[dict]:
    """
    Fetch customer payment records for the month.
    Verified columns: custcode, custpaydate, custpayvalue, custdeductvalue.
    """
    period = _period_clause('custpaydate', year, month)
    sql = f"SELECT * FROM {DB}.custpayments WHERE {period} ORDER BY custpaydate"
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql, rowcount=limit)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 11. PAYROLL (empsalaries) — currently 0 rows, module not active
# ══════════════════════════════════════════════════════════════════════════════

def get_empsalaries_by_month(year: int, month: int, conn=None) -> list[dict]:
    """
    Fetch employee salary records for the month.
    Returns [] when empsalaries is empty (module not active in this SOFTECH installation).
    """
    period = _period_clause('salarydate', year, month)
    sql = f"SELECT * FROM {DB}.empsalaries WHERE {period} ORDER BY personcode"
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        return [_clean(dict(zip(cols, r))) for r in rows]
    except Exception as e:
        return [{'_error': str(e)}]
    finally:
        if _own:
            _conn.close()


def get_total_payroll_by_month(year: int, month: int, conn=None) -> dict:
    """
    Aggregate payroll totals for the month from empsalaries.
    Returns {} / zeros when module is inactive.
    """
    period = _period_clause('salarydate', year, month)
    sql = f"""
        SELECT
            SUM(ISNULL(salary, 0))              AS total_net_salary,
            SUM(ISNULL(empsal_fixed, 0))        AS total_fixed,
            SUM(ISNULL(empsal_var, 0))          AS total_variable,
            SUM(ISNULL(empjoballow, 0)
              + ISNULL(emprepresent, 0)
              + ISNULL(emphousing, 0)
              + ISNULL(empextra, 0)
              + ISNULL(empsal_special, 0))      AS total_allowances,
            SUM(ISNULL(empinsurance_injury, 0)) AS total_insurance,
            COUNT(*)                            AS employee_count
        FROM   {DB}.empsalaries
        WHERE  {period}
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, sql)
        if rows and rows[0]:
            return _clean(dict(zip(cols, rows[0])))
        return {'total_net_salary': 0, 'employee_count': 0}
    except Exception as e:
        return {'_error': str(e)}
    finally:
        if _own:
            _conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# 12. SCHEMA INSPECTION HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def inspect_table(table_name: str, sample_rows: int = 5, conn=None) -> dict:
    """
    Fetch column names + sample rows for any table.
    Uses SET ROWCOUNT (Sybase ASE 12.5 / jConnect 3 — no SELECT TOP n).
    """
    _conn, _own = _conn_ctx(conn)
    try:
        rows, cols = _fetch(_conn, f'SELECT * FROM {DB}.{table_name}', rowcount=sample_rows)
        return {
            'table':   table_name,
            'columns': cols,
            'sample':  [_clean(dict(zip(cols, r))) for r in rows],
        }
    except Exception as e:
        return {'table': table_name, 'error': str(e)}
    finally:
        if _own:
            _conn.close()


def describe_confirmed_tables(conn=None) -> list[dict]:
    """
    Describe all tables marked sync_enabled=True in FinanceSchemaTable.
    """
    from apps.finance.models import FinanceSchemaTable
    results = []
    for t in FinanceSchemaTable.objects.filter(sync_enabled=True).order_by('table_name'):
        info = inspect_table(t.table_name, sample_rows=2, conn=conn)
        info['inferred_purpose'] = t.inferred_purpose
        info['category']         = t.category
        results.append(info)
    return results
