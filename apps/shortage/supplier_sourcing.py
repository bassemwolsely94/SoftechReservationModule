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

P-33 (d): the same answers come from our mirrors first — catalog.ItemSupplierLink (nightly
itemssuppliers) and procurement.PurchaseLine (doc 10) — so an export never waits on the SOFTECH
link. SOFTECH is read live only when a mirror is stale (ItemSupplierLink older than 48 h, or the
`purchases` freshness domain stale). meta['source'] says which ('mirror' | 'live').
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


_MAX_PARAMS = 400   # bound parameters per statement (proven live elsewhere)


def _chunks(seq, n=_MAX_PARAMS):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _marks(values) -> str:
    """'?, ?, ?' — one bound-parameter marker per value, for an IN (...) list."""
    return ', '.join('?' for _ in values)


def build_sourcing(itemcodes, *, restrict_supplier: str = '', with_history: bool = True,
                   branch: str = '100', main_only: bool = True, meta: dict | None = None) -> dict:
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

    # Filter that keeps only official/main suppliers (and any explicit restrict) —
    # supplier codes are bound parameters like every other value below.
    supp_params = []
    if restrict_supplier:
        supp_params = [str(restrict_supplier).strip()]
    elif main_only:
        from apps.invoices.suppliers import main_personcodes
        mains = main_personcodes()
        if not mains:
            return out   # nothing flagged main → nothing to process
        supp_params = sorted(str(c) for c in mains)
    if _mirrors_fresh():
        source, out = 'mirror', _from_mirror(codes, supp_params, with_history, branch)
    else:
        source, out = 'live', _from_softech(codes, supp_params, with_history, branch)
    if meta is not None:
        meta['source'] = source
    return out


_LINK_MAX_AGE_HOURS = 48


def _mirrors_fresh() -> bool:
    """ItemSupplierLink synced within 48 h and the `purchases` domain (PurchaseLine) not stale."""
    import datetime
    from django.db.models import Max
    from django.utils import timezone
    from apps.catalog.models import ItemSupplierLink
    last = ItemSupplierLink.objects.aggregate(m=Max('synced_at'))['m']
    if last is None or timezone.now() - last > datetime.timedelta(hours=_LINK_MAX_AGE_HOURS):
        return False
    try:
        from apps.sync.freshness import get_freshness
        return not get_freshness(['purchases'])['domains']['purchases']['stale']
    except Exception:
        logger.exception('supplier sourcing: purchases freshness unavailable — using SOFTECH')
        return False


def _supplier_names(codes):
    """Supplier names from our tables: VendorProfile, then SupplierSegmentation."""
    from apps.invoices.models import VendorProfile
    from apps.procurement.models import SupplierSegmentation
    names = dict(SupplierSegmentation.objects.filter(supplier_code__in=codes).exclude(supplier_name='')
                 .values_list('supplier_code', 'supplier_name'))
    names.update({c: n for c, n in VendorProfile.objects.filter(softech_personcode__in=codes)
                  .values_list('softech_personcode', 'name') if n})
    return names


def _from_mirror(codes, supp_params, with_history, branch) -> dict:
    """build_sourcing's answer from catalog.ItemSupplierLink + procurement.PurchaseLine."""
    import datetime
    from apps.catalog.models import ItemSupplierLink
    from apps.procurement.models import PurchaseLine
    out = {c: {'suppliers': {}, 'history': {}, 'last_bought': None} for c in codes}
    links = ItemSupplierLink.objects.filter(item_code__in=codes)
    if supp_params:
        links = links.filter(supp_code__in=supp_params)
    for ic, sc, code in links.values_list('item_code', 'supp_code', 'supp_item_code'):
        out[ic.strip()]['suppliers'][sc.strip()] = {'code': (code or '').strip(), 'name': ''}
    if with_history:
        lines = PurchaseLine.objects.filter(doccode='10', branch_code=str(branch), item_code__in=codes,
                                            doc_date__gt=datetime.date.fromisoformat(_HISTORY_SINCE))
        if supp_params:
            lines = lines.filter(supplier_code__in=supp_params)
        for ic, sc, cost, ddate in lines.order_by('doc_date', 'pk').values_list(
                'item_code', 'supplier_code', 'unit_price', 'doc_date'):
            out[ic.strip()]['history'][sc.strip()] = {'name': '', 'cost': float(cost) if cost is not None else None,
                                                      'date': ddate}            # newest wins (ordered)
        for rec in out.values():
            if rec['history']:
                sc, h = max(rec['history'].items(), key=lambda kv: (kv[1]['date'], kv[0]))
                rec['last_bought'] = {'suppcode': sc, **h}
    names = _supplier_names({sc for r in out.values() for sc in (*r['suppliers'], *r['history'])})
    for rec in out.values():
        for sc, s in rec['suppliers'].items():
            s['name'] = names.get(sc, '')
        for sc, h in rec['history'].items():
            h['name'] = names.get(sc, '')
        if rec['last_bought']:
            rec['last_bought']['name'] = names.get(rec['last_bought']['suppcode'], '')
    return out


def _from_softech(codes, supp_params, with_history, branch) -> dict:
    """build_sourcing's answer read live from SOFTECH (the fallback when a mirror is stale)."""
    out = {c: {'suppliers': {}, 'history': {}, 'last_bought': None} for c in codes}
    supp_filter = f' AND {{col}} IN ({_marks(supp_params)})' if supp_params else ''
    item_chunk = max(1, _MAX_PARAMS - len(supp_params) - 1)   # room for branch + suppliers

    conn = _open()
    try:
        cur = conn._cursor()
        cur.execute('SET ROWCOUNT 0')
        supp_names: dict[str, str] = {}

        # 1. suppliers-per-item + vendor code (itemssuppliers) ─────────────────
        for chunk in _chunks(codes, item_chunk):
            sql = (f"SELECT itemcode, suppcode, suppitemcode FROM itemssuppliers "
                   f"WHERE itemcode IN ({_marks(chunk)})" + supp_filter.format(col='suppcode'))
            cur.execute(sql, list(chunk) + supp_params)
            for ic, sc, code in cur.fetchall():
                ic = str(ic).strip(); sc = str(sc).strip()
                out[ic]['suppliers'][sc] = {'code': (str(code).strip() if code else ''), 'name': ''}
                supp_names[sc] = ''

        # 2. purchase history: last supplier + cost per item (stktrans⋈stktransm)
        if with_history:
            for chunk in _chunks(codes, item_chunk):
                cur.execute(
                    f"SELECT t.itemcode, m.cust_branch_code, t.transprice, t.docdate "
                    f"FROM stktrans t, stktransm m "
                    f"WHERE t.branchcode=m.branchcode AND t.doccode=m.doccode "
                    f"AND t.docnumber=m.docnumber AND t.doccode='10' "
                    f"AND t.branchcode=? AND t.itemcode IN ({_marks(chunk)}) "
                    f"AND t.docdate > convert(datetime,'{_HISTORY_SINCE}')"
                    + supp_filter.format(col='m.cust_branch_code'),
                    [str(branch)] + list(chunk) + supp_params)
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
                cur.execute(f"SELECT personcode, personname FROM personsdata "
                            f"WHERE personcode IN ({_marks(chunk)})", list(chunk))
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
