"""
Supplier item-code ↔ catalog item bridge, backed by SOFTECH ``itemssuppliers``.

The supplier's printed product code on an invoice (``vendor_item_code`` = the
كود الصنف column) equals ``itemssuppliers.suppitemcode`` for that supplier
(``suppcode`` = the supplier's personcode). If it's filled, one code resolves
straight to the catalog item with full confidence — no fuzzy name matching.

Reality (probed 2026-07-06): the ``(itemcode, suppcode)`` LINK rows mostly exist
(e.g. supplier 565 has 10,166) but the ``suppitemcode`` field is almost always
empty (565: only 22 filled) — so a read alone rarely hits. We therefore INJECT
the confirmed code on the existing row, then RECALL it on later invoices.

Table facts that make this safe:
  • unique key ``(itemcode, suppcode)`` — one row per pair.
  • NO insert/update/delete triggers (unlike stktrans) → a plain guarded write.
We still write through the proven unchained ``begin tran … verify … commit/rollback``
batch, gated by ``INVOICE_SUPPLIER_ITEM_WRITE_ENABLED`` (default off), and we
NEVER clobber a pre-existing different ``suppitemcode``.
"""
from __future__ import annotations

import logging

from django.conf import settings

from .writer import _q1, _sql_literal, _run_batch_lastrow

logger = logging.getLogger(__name__)


def resolve_codes(conn, personcode: str, codes) -> dict:
    """Batch-recall: {suppitemcode → SOFTECH itemcode} for a supplier, for the
    given printed codes. One query per invoice (not per line). Empty/unknown codes
    are absent from the result.

    A code that maps to MORE THAN ONE itemcode (the data has ~320 such real-code
    collisions + junk placeholders like code '1') is AMBIGUOUS and deliberately
    dropped — we never guess; those lines fall through to name matching + review."""
    supp = str(personcode or '').strip()
    wanted = sorted({str(c).strip() for c in (codes or []) if str(c).strip()})
    if not supp or not wanted:
        return {}
    inlist = ','.join("'" + c.replace("'", "''") + "'" for c in wanted)
    cur = conn.cursor()
    try:
        cur.execute(f"SELECT suppitemcode, itemcode FROM itemssuppliers "
                    f"WHERE suppcode=? AND suppitemcode IN ({inlist})", [supp])
        by_code: dict[str, set] = {}
        for sc, ic in cur.fetchall():
            if sc is None or ic is None:
                continue
            by_code.setdefault(str(sc).strip(), set()).add(str(ic).strip())
    finally:
        cur.close()
    # keep only codes that resolve to exactly ONE item
    return {code: next(iter(items)) for code, items in by_code.items() if len(items) == 1}


def read_current(conn, personcode: str, itemcode: str):
    """Return the current suppitemcode on the (itemcode, suppcode) row, or None if
    no row, '' if the row exists but the code is empty."""
    row = _q1(conn, "SELECT suppitemcode FROM itemssuppliers WHERE itemcode=? AND suppcode=?",
              [str(itemcode).strip(), str(personcode).strip()])
    if row is None:
        return None
    return str(row[0]).strip() if row[0] is not None else ''


def _all_others(conn, personcode: str, code: str, itemcode: str):
    """Every OTHER itemcode that currently holds this vendor code (collision set)."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT itemcode FROM itemssuppliers "
                    "WHERE suppcode=? AND suppitemcode=? AND itemcode<>?",
                    [str(personcode).strip(), str(code).strip(), str(itemcode).strip()])
        return cur.fetchall()
    finally:
        cur.close()


def inject_mapping(conn, personcode: str, itemcode: str, suppitemcode: str, *,
                   commit: bool = False, approved: bool = False) -> dict:
    """Write ``suppitemcode`` onto the supplier↔item row (UPDATE if the link exists,
    INSERT a minimal link if not), keeping the vendor code ↔ item map 1:1.

      • already set to this code             → no-op ok
      • NEW mapping (row empty, code unused) → written directly
      • CHANGE to an existing mapping        → requires ``approved=True``:
          – code_changed:    the item already had a different vendor code
          – code_reassigned: the code was on other item(s) (moved off them here)
        Without approval, returns ``action='needs_approval'`` + ``discrepancies``
        (the UI warns; the data-entry user approves; then we re-call approved).

    Every write verifies BOTH invariants (target carries the code, no other item
    does) before commit. ``commit=False`` runs it all and rolls back (safe probe)."""
    supp = str(personcode or '').strip()
    item = str(itemcode or '').strip()
    code = str(suppitemcode or '').strip()
    if not (supp and item and code):
        return {'ok': False, 'action': 'skip', 'reason': 'missing_args'}

    current = read_current(conn, supp, item)
    exists = current is not None
    if exists and current == code:
        return {'ok': True, 'action': 'noop', 'reason': 'already_set', 'committed': False,
                'discrepancies': []}

    # Detect the two kinds of mapping CHANGE that need the user's explicit sign-off:
    #   • code_changed     — this item already had a DIFFERENT vendor code
    #   • code_reassigned  — this vendor code is currently on OTHER item(s)
    discrepancies = []
    if exists and current:
        discrepancies.append({'type': 'code_changed', 'itemcode': item,
                              'from': current, 'to': code})
    others = [str(r[0]).strip() for r in _all_others(conn, supp, code, item)]
    if others:
        discrepancies.append({'type': 'code_reassigned', 'code': code,
                              'from_itemcodes': others, 'to_itemcode': item})

    # A change to an existing mapping is refused until the user approves the warning.
    if discrepancies and not approved:
        return {'ok': False, 'action': 'needs_approval', 'requires_approval': True,
                'discrepancies': discrepancies, 'current': current}

    li, ls, lc = _sql_literal(item), _sql_literal(supp), _sql_literal(code)
    stmts = []
    # 1. If reassigning, clear the code off the other item(s) first (keeps 1:1).
    if others:
        stmts.append(f"update itemssuppliers set suppitemcode='', modif_lastupdate=getdate() "
                     f"where suppcode={ls} and suppitemcode={lc} and itemcode<>{li}")
    # 2. Set the code on the target row (approved → overwrite; clean → empty-guarded).
    if exists:
        guard = "" if approved else f" and (suppitemcode is null or suppitemcode='' or suppitemcode={lc})"
        stmts.append(f"update itemssuppliers set suppitemcode={lc}, modif_lastupdate=getdate() "
                     f"where itemcode={li} and suppcode={ls}{guard}")
        action = 'update'
    else:
        stmts.append(f"insert itemssuppliers (itemcode, suppcode, suppitemcode, itemsort, "
                     f"main_supp, modif_lastupdate) values ({li}, {ls}, {lc}, 0, '0', getdate())")
        action = 'insert'
    write = '\n'.join(stmts)

    final = 'commit tran' if commit else 'rollback tran'
    # Verify BOTH invariants: target now carries the code AND no other item does.
    batch = f"""
set chained off
declare @done int, @others int
begin tran
{write}
select @done = count(*) from itemssuppliers where itemcode={li} and suppcode={ls} and suppitemcode={lc}
select @others = count(*) from itemssuppliers where suppcode={ls} and suppitemcode={lc} and itemcode<>{li}
if @done = 1 and @others = 0 {final}
else rollback tran
select @done as done, @others as others
"""
    jst = conn._conn.createStatement()
    try:
        row = _run_batch_lastrow(jst, batch)
    finally:
        try:
            jst.close()
        except Exception:
            pass

    def _i(v, d=0):
        try:
            return int(str(v))
        except Exception:
            return d
    done = _i(row[0]) if row else 0
    remaining_others = _i(row[1], -1) if row else -1
    ok = (done == 1 and remaining_others == 0)
    return {'ok': ok, 'action': action, 'verified': ok, 'committed': bool(commit and ok),
            'discrepancies': discrepancies if approved else [], 'approved': bool(approved)}


def open_conn():
    """Open a SOFTECH connection for the master-data (HQ) itemssuppliers table,
    using the invoice-writer profile. Returns the ConnectionWrapper (has
    ``.cursor()`` and ``._conn``, matching what the writer helpers expect);
    call ``.close()`` on it when done."""
    from config.sybase import SoftechConnector
    profile = getattr(settings, 'INVOICE_WRITER_PROFILE', '') or getattr(settings, 'SOFTECH_PROFILE', 'prod')
    return SoftechConnector(profile=profile).connect()._conn


def write_enabled() -> bool:
    return bool(getattr(settings, 'INVOICE_SUPPLIER_ITEM_WRITE_ENABLED', False))
