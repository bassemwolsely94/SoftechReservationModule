"""
apps/finance/queries/sybase_discovery.py

Phase 0 — SOFTECH schema discovery.

All queries are SELECT-only on the Sybase connection.
ABSOLUTE RULE: never INSERT / UPDATE / DELETE via the Sybase connection.

Strategy
────────
1. Scan syscolumns / sysobjects for tables whose names or columns match a
   broad set of financial keywords.
2. For every candidate table: fetch column metadata, row count, and a tiny
   sample (≤ 3 rows).
3. Infer a human-readable "purpose" label from the table + column names.
4. Return structured dicts the management command will persist to
   FinanceSchemaTable.

Sybase ASE 12.5 quirks
──────────────────────
- No CTEs.  Use subqueries or temp tables only when necessary.
- Column types stored as integers (syscolumns.type); map through master..systypes.
- TOP n syntax is supported: SELECT TOP 3 * FROM table
- String comparison: use LIKE with % wildcards; no ILIKE.
- Object IDs are integers; table names in sysobjects.name.
- Database prefix: SOFTECHDB9.dbo.<tablename>
"""

from __future__ import annotations
from typing import Any

from config.sybase import get_sybase_connection

DB_PREFIX = "SOFTECHDB9.dbo"

# ── Financial keyword lists ──────────────────────────────────────────────────

# Table-name fragments that strongly suggest financial relevance
TABLE_KEYWORDS: list[str] = [
    "account", "acct", "ledger", "journal", "entry", "entries",
    "gl", "coa",                              # general ledger / chart of accounts
    "invoice", "invo",
    "payment", "pay", "receipt", "collect",
    "cash", "bank", "cheque", "check", "treasury",
    "expense", "expens", "cost",
    "budget", "budg",
    "tax", "vat", "gst",
    "profit", "loss", "revenue", "revenu",
    "balance", "trial",
    "finance", "financ", "financi",
    "salary", "payroll", "wage",
    "vendor", "supplier", "creditor",
    "customer", "debtor", "receiv",
    "purchase", "purch",
    "sale", "sales",
    "stock", "inventory",           # needed for COGS derivation
    "stktrans",                     # SOFTECH core transactions
    "trans", "trn",
    "doc", "document",
    "period", "fiscal", "month", "year",
    "currency", "currenc", "exchange",
]

# Column-name fragments that boost confidence even if table name is opaque
COLUMN_KEYWORDS: list[str] = [
    "amount", "amnt", "amt",
    "debit", "credit",
    "balance", "net", "gross",
    "price", "cost",
    "tax", "discount",
    "account", "acct",
    "currency",
    "payment",
    "invoice",
    "date",
    "total",
]

# Mapping: keyword → inferred category label
CATEGORY_MAP: list[tuple[str, str]] = [
    ("stktrans",   "journal"),
    ("trans",      "journal"),
    ("journal",    "journal"),
    ("ledger",     "journal"),
    ("entry",      "journal"),
    ("gl",         "journal"),
    ("account",    "accounts"),
    ("acct",       "accounts"),
    ("coa",        "accounts"),
    ("cash",       "cash"),
    ("bank",       "bank"),
    ("cheque",     "bank"),
    ("check",      "bank"),
    ("treasury",   "cash"),
    ("receipt",    "cash"),
    ("payment",    "payment"),
    ("pay",        "payment"),
    ("invoice",    "invoice"),
    ("invo",       "invoice"),
    ("expense",    "expense"),
    ("expens",     "expense"),
    ("cost",       "expense"),
    ("salary",     "payroll"),
    ("payroll",    "payroll"),
    ("wage",       "payroll"),
    ("budget",     "budget"),
    ("tax",        "tax"),
    ("vat",        "tax"),
    ("stock",      "inventory"),
    ("inventory",  "inventory"),
    ("sale",       "revenue"),
    ("revenue",    "revenue"),
    ("purchase",   "purchase"),
    ("purch",      "purchase"),
    ("customer",   "receivable"),
    ("debtor",     "receivable"),
    ("vendor",     "payable"),
    ("supplier",   "payable"),
    ("creditor",   "payable"),
]


# ── Low-level helpers ────────────────────────────────────────────────────────

def _rows_as_dicts(cursor, rows: list) -> list[dict]:
    """Convert raw fetchall rows to list-of-dicts using cursor.description."""
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in rows]


def _safe_str(v: Any) -> Any:
    """Convert bytes / bytearray to str so JSON serialisation doesn't choke."""
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:
            return repr(v)
    return v


def _sanitise_row(row: dict) -> dict:
    return {k: _safe_str(v) for k, v in row.items()}


# ── Sybase type-code → readable name ────────────────────────────────────────

# Partial map — covers the most common Sybase ASE base types.
# Full list lives in master..systypes; we fall back to "type:<n>" if unknown.
_SYBASE_TYPES: dict[int, str] = {
    35:  "text",
    37:  "varbinary",
    38:  "intn",
    39:  "varchar",
    45:  "binary",
    47:  "char",
    48:  "tinyint",
    49:  "date",
    50:  "bit",
    51:  "time",
    52:  "smallint",
    55:  "decimaln",
    56:  "int",
    58:  "smalldatetime",
    59:  "real",
    60:  "money",
    61:  "datetime",
    62:  "float",
    63:  "nchar",
    64:  "numericn",
    65:  "nvarchar",
    109: "bigint",
    110: "moneyn",
    111: "datetimn",
    127: "bigint",
}


def _type_name(type_code: int | None) -> str:
    if type_code is None:
        return "unknown"
    return _SYBASE_TYPES.get(int(type_code), f"type:{type_code}")


# ── Core discovery functions ─────────────────────────────────────────────────

def get_all_table_names() -> list[str]:
    """
    Return every user table name from SOFTECHDB9 (no system tables).
    Uses sysobjects where type = 'U' (user table).
    """
    sql = f"""
        SELECT name
        FROM   {DB_PREFIX.replace('.dbo', '')}.dbo.sysobjects
        WHERE  type = 'U'
        ORDER  BY name
    """
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return [r[0].strip() if isinstance(r[0], str) else r[0] for r in rows]
    finally:
        conn.close()


def get_table_columns(table_name: str) -> list[dict]:
    """
    Return column metadata for table_name.
    Returns: [{name, type, length, colid}]
    """
    sql = f"""
        SELECT c.name,
               c.type,
               c.length,
               c.colid
        FROM   {DB_PREFIX.replace('.dbo', '')}.dbo.syscolumns c
        JOIN   {DB_PREFIX.replace('.dbo', '')}.dbo.sysobjects o
               ON  o.id = c.id
        WHERE  o.name = '{table_name}'
        AND    o.type = 'U'
        ORDER  BY c.colid
    """
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        return [
            {
                "name":   r[0].strip() if isinstance(r[0], str) else r[0],
                "type":   _type_name(r[1]),
                "length": r[2],
                "colid":  r[3],
            }
            for r in rows
        ]
    finally:
        conn.close()


def get_table_row_count(table_name: str) -> int:
    """
    Return row count for table_name.

    Strategy (fastest-first):
    1. sysindexes.rowcnt (estimate, no full scan) — Sybase 12.x stores this in
       indid=0 (heap) or indid=1 (clustered index).  Some Sybase installs don't
       expose rowcnt in the dbo-qualified view; we try both the cross-db form
       and a simple COUNT fallback.
    2. Exact COUNT(*) — used when sysindexes returns nothing or 0.
    """
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()

        # ── Try sysindexes (fast estimate) ────────────────────────────────
        try:
            sql_idx = f"""
                SELECT i.rowcnt
                FROM   {DB_PREFIX.replace('.dbo', '')}.dbo.sysindexes i
                JOIN   {DB_PREFIX.replace('.dbo', '')}.dbo.sysobjects o
                       ON  o.id = i.id
                WHERE  o.name = '{table_name}'
                AND    o.type = 'U'
                AND    i.indid IN (0, 1)
            """
            cur.execute(sql_idx)
            row = cur.fetchone()
            if row and row[0] is not None and int(row[0]) > 0:
                return int(row[0])
        except Exception:
            pass   # fall through to COUNT

        # ── Exact COUNT (slower but reliable) ─────────────────────────────
        cur.execute(f"SELECT COUNT(*) FROM {DB_PREFIX}.{table_name}")
        row = cur.fetchone()
        return int(row[0]) if row else 0

    except Exception:
        return -1
    finally:
        conn.close()


def get_table_sample(table_name: str, n: int = 3) -> list[dict]:
    """
    Return up to n rows from table_name as sanitised dicts.

    Uses SET ROWCOUNT instead of SELECT TOP n for Sybase ASE 12.5 / jConnect 3
    compatibility — SELECT TOP n syntax raises "Incorrect syntax near '<n>'".
    The connection is closed after use so the session ROWCOUNT setting is discarded.
    """
    conn = get_sybase_connection()
    try:
        cur = conn.cursor()
        cur.execute(f'SET ROWCOUNT {n}')
        cur.execute(f'SELECT * FROM {DB_PREFIX}.{table_name}')
        rows = cur.fetchall()
        if not rows:
            return []
        dicts = _rows_as_dicts(cur, rows)
        return [_sanitise_row(d) for d in dicts]
    except Exception:
        return []
    finally:
        conn.close()


# ── Keyword scoring ──────────────────────────────────────────────────────────

def _score_table(table_name: str, columns: list[dict]) -> int:
    """
    Score a table for financial relevance (higher = more relevant).
    Table-name matches count 3×; column-name matches count 1× each.
    """
    score = 0
    lower_name = table_name.lower()
    col_names_lower = [c["name"].lower() for c in columns]

    for kw in TABLE_KEYWORDS:
        if kw in lower_name:
            score += 3

    for col in col_names_lower:
        for kw in COLUMN_KEYWORDS:
            if kw in col:
                score += 1
                break  # one match per column

    return score


def _infer_purpose(table_name: str, columns: list[dict]) -> str:
    """Generate a short English label from table + column names."""
    lower = table_name.lower()
    col_names = [c["name"].lower() for c in columns]

    # Direct name hints
    if "stktrans" in lower:
        return "Stock transactions (purchases / sales / returns) — core financial ledger"
    if "account" in lower and "chart" in lower:
        return "Chart of accounts"
    if "journal" in lower:
        return "Journal entries"
    if "cash" in lower:
        return "Cash movements"
    if "bank" in lower and "trans" in lower:
        return "Bank transactions"
    if "payroll" in lower or "salary" in lower:
        return "Payroll / salary records"
    if "tax" in lower:
        return "Tax records"
    if "budget" in lower:
        return "Budget / forecast data"
    if "invoice" in lower:
        return "Invoice records"
    if "payment" in lower:
        return "Payment records"
    if "expense" in lower:
        return "Expense records"

    # Column-based inference
    has_debit   = any("debit"  in c for c in col_names)
    has_credit  = any("credit" in c for c in col_names)
    has_amount  = any(kw in c  for c in col_names for kw in ("amount","amnt","amt","total"))
    has_account = any("account" in c or "acct" in c for c in col_names)

    if has_debit and has_credit:
        return "Double-entry ledger / journal lines"
    if has_account and has_amount:
        return "Account-based financial records"
    if has_amount:
        return "Transactional / monetary data"

    return "Potentially financial — needs manual review"


def _infer_category(table_name: str) -> str:
    """Map table name to a coarse category label."""
    lower = table_name.lower()
    for keyword, category in CATEGORY_MAP:
        if keyword in lower:
            return category
    return "other"


# ── Main discovery routine ───────────────────────────────────────────────────

def discover_financial_tables(
    min_score: int = 3,
    progress_callback=None,
) -> list[dict]:
    """
    Full Phase-0 discovery pass.

    Returns a list of dicts, one per relevant table:
    {
        table_name,
        inferred_purpose,
        row_count,
        columns,        # [{name, type, length, colid}]
        sample_rows,    # up to 3 rows
        category,
        score,          # internal relevance score (not persisted)
    }

    progress_callback(current, total, table_name) — optional callable
    used by the management command to log progress.
    """
    all_tables = get_all_table_names()
    results: list[dict] = []

    for idx, table_name in enumerate(all_tables):
        if progress_callback:
            progress_callback(idx + 1, len(all_tables), table_name)

        try:
            columns = get_table_columns(table_name)
        except Exception:
            columns = []

        score = _score_table(table_name, columns)
        if score < min_score:
            continue

        row_count   = get_table_row_count(table_name)
        sample_rows = get_table_sample(table_name, n=3)

        results.append({
            "table_name":       table_name,
            "inferred_purpose": _infer_purpose(table_name, columns),
            "row_count":        row_count,
            "columns":          columns,
            "sample_rows":      sample_rows,
            "category":         _infer_category(table_name),
            "score":            score,
        })

    # Sort by score descending so the most likely tables surface first
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def get_known_table_info(table_name: str) -> dict | None:
    """
    Fetch fresh metadata for a single known table (used for re-inspection).
    Returns None if the table doesn't exist or is inaccessible.
    """
    try:
        columns     = get_table_columns(table_name)
        row_count   = get_table_row_count(table_name)
        sample_rows = get_table_sample(table_name, n=3)
        return {
            "table_name":       table_name,
            "inferred_purpose": _infer_purpose(table_name, columns),
            "row_count":        row_count,
            "columns":          columns,
            "sample_rows":      sample_rows,
            "category":         _infer_category(table_name),
        }
    except Exception:
        return None
