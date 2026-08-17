"""
Supplier sourcing intelligence for shortage → ordering.

For a set of our SOFTECH itemcodes, gather (read-only) from the ERP:
  • which suppliers carry each item + that supplier's own code  (itemssuppliers)
  • which supplier we last BOUGHT each item from, and at what cost   (stktrans doccode 10)

This is a GUIDING LINE, not a rule: exclusivity is uncommon and distributors
change their catalogues constantly, so the data is historical/advisory — it helps
the buyer filter and compare prices, and it powers the supplier-code columns in the
shortage Excel exports.

Both lookups are indexed (itemssuppliers key (itemcode,suppcode); stktrans_ndx2
(itemcode,branchcode,doccode,docdate)) so this stays fast for a whole list.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_HISTORY_SINCE = '2019-01-01'   # ignore ancient purchases for price comparison


def _open():
    from config.sybase import SoftechConnector
    from django.conf import settings
    profile = getattr(settings, 'SOFTECH_PROFILE', 'prod') or 'prod'
    return SoftechConnector(profile=profile).connect()


def _chunks(seq, n=400):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def build_sourcing(itemcodes, *, restrict_supplier: str = '', with_history: bool = True,
                   branch: str = '100', main_only: bool = True) -> dict:
    """Return {itemcode: {'suppliers': {suppcode: {'code','name'}},
                          'history': {suppcode: {'name','cost','date'}},
                          'last_bought': {suppcode,'name','cost','date'} | None}}.

    ``restrict_supplier`` limits the lookup to one personcode. ``main_only`` (default)
    restricts EVERYTHING to the vendors flagged is_main — we never process unofficial
    suppliers (wasteful in both data and query time)."""
    codes = sorted({str(c).strip() for c in itemcodes if str(c).strip()})
    out = {c: {'suppliers': {}, 'history': {}, 'last_bought': None} for c in codes}
    if not codes:
        return out

    # SQL filter that keeps only official/main suppliers (and any explicit restrict).
    supp_filter = ''
    if restrict_supplier:
        supp_filter = f" AND {{col}}='{str(restrict_supplier).strip()}'"
    elif main_only:
        from apps.invoices.suppliers import main_personcodes
        mains = main_personcodes()
        if not mains:
            return out   # nothing flagged main → nothing to process
        inl = ','.join("'" + c.replace("'", "''") + "'" for c in sorted(mains))
        supp_filter = f" AND {{col}} IN ({inl})"

    conn = _open()
    try:
        cur = conn._cursor()
        cur.execute('SET ROWCOUNT 0')
        supp_names: dict[str, str] = {}

        # 1. suppliers-per-item + vendor code (itemssuppliers) ─────────────────
        for chunk in _chunks(codes):
            inlist = ','.join("'" + c.replace("'", "''") + "'" for c in chunk)
            sql = (f"SELECT itemcode, suppcode, suppitemcode FROM itemssuppliers "
                   f"WHERE itemcode IN ({inlist})" + supp_filter.format(col='suppcode'))
            cur.execute(sql)
            for ic, sc, code in cur.fetchall():
                ic = str(ic).strip(); sc = str(sc).strip()
                out[ic]['suppliers'][sc] = {'code': (str(code).strip() if code else ''), 'name': ''}
                supp_names[sc] = ''

        # 2. purchase history: last supplier + cost per item (stktrans⋈stktransm)
        if with_history:
            for chunk in _chunks(codes):
                inlist = ','.join("'" + c.replace("'", "''") + "'" for c in chunk)
                cur.execute(
                    f"SELECT t.itemcode, m.cust_branch_code, t.transprice, t.docdate "
                    f"FROM stktrans t, stktransm m "
                    f"WHERE t.branchcode=m.branchcode AND t.doccode=m.doccode "
                    f"AND t.docnumber=m.docnumber AND t.doccode='10' "
                    f"AND t.branchcode='{branch}' AND t.itemcode IN ({inlist}) "
                    f"AND t.docdate > convert(datetime,'{_HISTORY_SINCE}')"
                    + supp_filter.format(col='m.cust_branch_code'))
                for ic, sc, cost, ddate in cur.fetchall():
                    ic = str(ic).strip(); sc = str(sc).strip()
                    try:
                        cost = float(cost) if cost is not None else None
                    except Exception:
                        cost = None
                    h = out[ic]['history']
                    prev = h.get(sc)
                    if prev is None or (ddate and prev['date'] and ddate > prev['date']):
                        h[sc] = {'name': '', 'cost': cost, 'date': ddate}
                    supp_names.setdefault(sc, '')
            # newest purchase across suppliers → last_bought
            for ic, rec in out.items():
                latest = None
                for sc, h in rec['history'].items():
                    if latest is None or (h['date'] and latest[1]['date'] and h['date'] > latest[1]['date']):
                        latest = (sc, h)
                if latest:
                    rec['last_bought'] = {'suppcode': latest[0], **latest[1]}

        # 3. supplier names (personsdata) ─────────────────────────────────────
        if supp_names:
            for chunk in _chunks(list(supp_names)):
                inlist = ','.join("'" + c.replace("'", "''") + "'" for c in chunk)
                cur.execute(f"SELECT personcode, personname FROM personsdata "
                            f"WHERE personcode IN ({inlist})")
                for pc, nm in cur.fetchall():
                    supp_names[str(pc).strip()] = str(nm or '').strip()
            for rec in out.values():
                for sc, s in rec['suppliers'].items():
                    s['name'] = supp_names.get(sc, '')
                for sc, h in rec['history'].items():
                    h['name'] = supp_names.get(sc, '')
                if rec['last_bought']:
                    rec['last_bought']['name'] = supp_names.get(rec['last_bought']['suppcode'], '')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return out


def main_supplier_columns():
    """The is_main distributors used as columns in the comprehensive matrix, as
    [(personcode, name)] — dynamically driven by the VendorProfile.is_main flag."""
    try:
        from apps.invoices.suppliers import main_suppliers
        return main_suppliers()
    except Exception:
        return []
