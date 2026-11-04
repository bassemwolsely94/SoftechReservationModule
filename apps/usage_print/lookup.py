"""
apps/usage_print/lookup.py — find ONE sale invoice for the usage slip. READ-ONLY vs SOFTECH.

Identity is always (branch, doccode 115, docnumber, docdate) — SOFTECH docnumbers are per-(branch,
doctype) sequences, so the bare number would open another branch's or another day's invoice.

  1. Our sales mirror: PurchaseHistory.softech_invoice_id = "{branch}-115-{docnumber}-{YYYYMMDD}"
     (the key sync_sales writes; the fast lane runs every 5 minutes).
  2. Not mirrored yet → one bounded SELECT on the selling branch's own server (it has the sale
     first), then HQ. Nothing is written to PurchaseHistory — the normal sync does that.
"""
import datetime as _dt
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal

from apps.catalog.models import Item
from apps.customers.models import Customer, PurchaseHistory

logger = logging.getLogger(__name__)

SALE_DOCCODE = '115'
LIVE_TIMEOUT = 15   # seconds — interactive, a patient is waiting

# One invoice, indexed predicates only (branchcode + doccode + docnumber + docdate).
QUERY_ONE_SALE = """
    SELECT st.itemcode, st.transqty, sm.phcode, st.personcode
    FROM SOFTECHDB9.dbo.stktrans st
    JOIN SOFTECHDB9.dbo.stktransm sm
        ON  sm.branchcode = st.branchcode
        AND sm.doccode    = st.doccode
        AND sm.docnumber  = st.docnumber
        AND sm.docdate    = st.docdate
    WHERE st.branchcode = '{branch}'
    AND st.doccode = '115'
    AND st.docnumber = {docnumber}
    AND st.docdate = '{docdate}'
"""


class LiveUnavailable(Exception):
    """The invoice is not mirrored yet and SOFTECH could not be read right now."""


@dataclass
class InvoiceData:
    invoice_id: str
    branch: object
    docnumber: str
    docdate: _dt.date
    source: str                       # 'mirror' | 'live'
    customer: Customer | None = None
    patient_name: str = ''
    purchase: PurchaseHistory | None = None
    # itemcode → {'item': Item|None, 'name': str, 'qty': Decimal}, invoice order
    lines: 'OrderedDict[str, dict]' = field(default_factory=OrderedDict)


def invoice_id(branch_code, docnumber, docdate) -> str:
    return f'{branch_code}-{SALE_DOCCODE}-{int(docnumber)}-{docdate.strftime("%Y%m%d")}'


def _named(customer, phcode):
    """The patient's name only for a real named customer — the invoice PIC is that customer's own
    PIC (never the ACCT-<personcode> placeholder of a cash / contract account)."""
    pic = (phcode or '').strip()
    if customer is not None and pic and (customer.softech_pic or '').strip() == pic:
        return customer, (customer.name or '').strip()
    return None, ''


def _add(lines, code, item, qty):
    code = str(code).strip()
    row = lines.setdefault(code, {'item': item, 'name': (item.name if item else code), 'qty': Decimal(0)})
    row['qty'] += Decimal(str(qty or 0))   # one item spans several rows (one per batch) → summed


def from_mirror(branch, docnumber, docdate):
    inv_id = invoice_id(branch.softech_branch_id, docnumber, docdate)
    ph = (PurchaseHistory.objects.select_related('customer')
          .filter(softech_invoice_id=inv_id, doc_code=SALE_DOCCODE).first())
    if ph is None:
        return None
    lines = OrderedDict()
    for ln in ph.lines.select_related('item').order_by('id'):
        code = ln.item.softech_id if ln.item_id else f'?{ln.pk}'
        _add(lines, code, ln.item, ln.quantity)
    if not lines:
        return None
    customer, name = _named(ph.customer, ph.softech_phcode)
    return InvoiceData(inv_id, branch, str(int(docnumber)), docdate, 'mirror', customer, name, ph, lines)


def _connections(branch):
    """Selling branch's own server first (today's sales land there first), then HQ."""
    from config.sybase import get_branch_connection, get_sybase_connection
    if (branch.db_host or '').strip():
        yield lambda: get_branch_connection(branch.effective_db_host, branch.effective_db_port, 'SOFTECHDB9')
    yield get_sybase_connection


def _read_live(branch, docnumber, docdate):
    sql = QUERY_ONE_SALE.format(branch=str(branch.softech_branch_id).replace("'", ''),
                                docnumber=int(docnumber), docdate=docdate.strftime('%Y%m%d'))
    last_error = None
    for connect in _connections(branch):
        conn = None
        try:
            conn = connect()
            cur = conn.cursor()
            cur.execute(sql, timeout=LIVE_TIMEOUT)
            return cur.fetchall()
        except Exception as exc:   # gate denial, unreachable node, timeout → try the next server
            last_error = exc
            logger.warning('usage_print live read failed (%s): %s', branch.softech_branch_id, exc)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    raise LiveUnavailable(str(last_error or 'no connection'))


def from_live(branch, docnumber, docdate):
    rows = _read_live(branch, docnumber, docdate)
    if not rows:
        return None
    codes = {str(r[0]).strip() for r in rows}
    items = {i.softech_id: i for i in Item.objects.filter(softech_id__in=codes)}
    lines = OrderedDict()
    for r in rows:
        _add(lines, r[0], items.get(str(r[0]).strip()), r[1])
    phcode = str(rows[0][2] or '').strip()
    customer = Customer.objects.filter(softech_pic=phcode).first() if phcode else None
    customer, name = _named(customer, phcode)
    inv_id = invoice_id(branch.softech_branch_id, docnumber, docdate)
    return InvoiceData(inv_id, branch, str(int(docnumber)), docdate, 'live', customer, name, None, lines)


def find_invoice(branch, docnumber, docdate):
    """InvoiceData, or None when no such sale exists. Raises LiveUnavailable when the mirror
    misses and SOFTECH can't be read."""
    return from_mirror(branch, docnumber, docdate) or from_live(branch, docnumber, docdate)
