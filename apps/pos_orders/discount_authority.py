"""
apps/pos_orders/discount_authority.py

Authority-aware POS discount validation (LIVE read against SOFTECH), called from
/ready. For each line it checks the entered discount against three layers:

  1. allow_sell — the customer may buy the item's discount CATEGORY at all
  2. contracted — the customer's contracted discount for that category (`custdiscounts`)
  3. authority  — a discount ABOVE the contracted value needs the seller's ceiling
                  (`managerdiscount.max_custdiscp` at the branch)

Gated by settings.POS_DISCOUNT_AUTHORITY (default False). It **degrades gracefully**:
any mapping it cannot resolve (resolver returns None) is SKIPPED, so it can never
falsely reject a legitimate sale. Enable it only once the three resolvers below are
confirmed against production.

JOINS (resolved read-only 2026-06-23):
  • item category   = items.itemstoreclassif  (values match custdiscpclassif catalog,
                      e.g. item 100038 → 10 = "Med: Local")
  • seller ceiling  = managerdiscount.personcode == the seller's usercode (same numbering;
                      e.g. usercode 2050 has a managerdiscount row)
  • customer        = custdiscounts is keyed by the channel/contract customer. CONFIRMED
                      channel defaults: cash → personglobalcode 'CashCust',
                      delivery → 'HomeDlvry'. The individual contract-patient → contract-
                      entity personcode (4212+) link is NOT in the visible schema, so for
                      contract/insurance the customer is unresolved → those lines are SKIPPED.

So the check is active for cash/delivery (their contracted schedule + the seller ceiling)
and degrades gracefully elsewhere. It only ever escalates a discount ABOVE the contracted
rate, so it cannot reject a discount that is within entitlement.
"""
from decimal import Decimal

from django.conf import settings

from config.sybase import get_branch_connection

# channel → the representative customer's personglobalcode in personsdata (confirmed)
_CHANNEL_GLOBALCODE = {'cash': 'CashCust', 'delivery': 'HomeDlvry'}


def enabled():
    return bool(getattr(settings, 'POS_DISCOUNT_AUTHORITY', False))


def _d(v):
    return v if isinstance(v, Decimal) else Decimal(str(v or 0))


class DiscountAuthorityReader:
    """Read-only SOFTECH lookups for discount authority. One connection per order."""

    def __init__(self, db_host, db_port=5000, db_name='SOFTECHDB9'):
        self.conn = get_branch_connection(db_host, db_port or 5000, db_name or 'SOFTECHDB9')

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass

    def _q1(self, sql, params=None):
        cur = self.conn.cursor()
        cur.execute(sql, params or [])
        return cur.fetchone()

    # ── resolvers ──────────────────────────────────────────────────────────────
    def item_category(self, itemcode):
        """itemcode -> custdiscpcode (items.itemstoreclassif)."""
        row = self._q1("SELECT itemstoreclassif FROM items WHERE itemcode=?", [str(itemcode)])
        cat = (str(row[0]).strip() if row and row[0] is not None else '')
        return cat or None

    def seller_personcode(self, usercode):
        """managerdiscount.personcode uses the same numbering as the seller usercode."""
        uc = (str(usercode).strip() if usercode else '')
        return uc or None

    def customer_personcode(self, channel):
        """The custdiscounts personcode for the channel's representative customer.
        Resolved for cash/delivery; None for contract/insurance (individual→contract
        mapping unconfirmed) ⇒ those lines are skipped."""
        gc = _CHANNEL_GLOBALCODE.get(channel)
        if not gc:
            return None
        row = self._q1("SELECT personcode FROM personsdata WHERE personglobalcode=?", [gc])
        return (str(row[0]).strip() if row and row[0] is not None else None)

    def item_alt3(self, itemcode):
        """items.itemcode_alt3 — the item's CONTRACT-DISCOUNT classification (تصنيف خصم التعاقدات).
        This is the key SOFTECH uses for LOYALTY POINTS (verified live 2026-08-19): points% =
        custdiscounts[channel-rep, itemcode_alt3]. (NOT itemstoreclassif, which drives line discounts.)"""
        row = self._q1("SELECT itemcode_alt3 FROM items WHERE itemcode=?", [str(itemcode)])
        return (str(row[0]).strip() if row and row[0] is not None else None) or None

    def item_posdiscp(self, itemcode):
        """items.posdiscp — the item's own max POS discount % (the retail/walk-in default).
        This is the item-master field that drives cash/delivery discounts — NOT custdiscounts
        (which carries contract/point-system schedules keyed by a customer)."""
        row = self._q1("SELECT posdiscp FROM items WHERE itemcode=?", [str(itemcode)])
        return _d(row[0]) if row and row[0] is not None else None

    # ── confirmed lookups ──────────────────────────────────────────────────────
    def contracted(self, personcode, custdiscpcode):
        """(custdiscp, allow_sell) for the customer × category, or None if no row."""
        row = self._q1(
            "SELECT custdiscp, allow_sell FROM custdiscounts WHERE personcode=? AND custdiscpcode=?",
            [str(personcode), str(custdiscpcode)])
        if not row:
            return None
        return (_d(row[0]), int(row[1] or 0))

    def max_authority(self, personcode, branchcode):
        """The seller's max grantable discount % at this branch (None ⇒ no ceiling row)."""
        row = self._q1(
            "SELECT max_custdiscp FROM managerdiscount WHERE personcode=? AND branchcode=?",
            [str(personcode), str(branchcode)])
        return _d(row[0]) if row else None


def check_order(order, reader):
    """
    Return a list of {index, field, detail} errors for lines that violate authority.
    Skips any line whose category/customer/seller mapping can't be resolved (no false reject).

    Mirrors discount_suggest:
      • retail  → entered discount must be ≤ min(item posdiscp, seller max).
      • contract/insurance → a discount ABOVE the contracted rate needs the seller ceiling.
    """
    errors = []
    is_contract = order.channel in ('contract', 'insurance')
    seller_pc = reader.seller_personcode(order.seller_usercode)
    branchcode = order.softech_branchcode
    ceiling = reader.max_authority(seller_pc, branchcode) if seller_pc is not None else None
    personcode = reader.customer_personcode(order.channel) if is_contract else None

    for i, ln in enumerate(order.lines.all()):
        entered = _d(ln.cust_discp)
        if entered <= 0:
            continue  # no discount → nothing to authorize

        if is_contract:
            category = reader.item_category(ln.softech_itemcode)
            if personcode is None or category is None:
                continue  # cannot resolve the contracted rate → skip
            contracted = reader.contracted(personcode, category)
            if contracted is None:
                continue  # no contract row → skip
            cust_discp, allow_sell = contracted
            if allow_sell == 0:
                errors.append({'index': i, 'field': 'softech_itemcode',
                               'detail': 'لا يُسمح ببيع هذه الفئة لهذا العميل (allow_sell=0).'})
                continue
            if entered > cust_discp and (ceiling is None or entered > ceiling):
                errors.append({
                    'index': i, 'field': 'cust_discp',
                    'detail': (f'الخصم {entered}% يتجاوز المتعاقد عليه ({cust_discp}%) ويتطلب صلاحية أعلى'
                               + (f' (الحد المسموح {ceiling}%).' if ceiling is not None else '.')),
                })
        else:
            # retail: cap = the tighter of the item's POS discount and the seller's max
            pd = reader.item_posdiscp(ln.softech_itemcode)
            bounds = [b for b in (pd, ceiling) if b is not None]
            if not bounds:
                continue  # cannot resolve either bound → skip
            cap = min(bounds)
            if entered > cap:
                errors.append({'index': i, 'field': 'cust_discp',
                               'detail': f'الخصم {entered}% يتجاوز الحد المسموح ({cap}%) لهذا الصنف.'})
    return errors


def validate_discount_authority(order):
    """Entry point for /ready. No-op unless enabled. Returns list of error dicts."""
    if not enabled():
        return []
    reader = DiscountAuthorityReader(order.branch.effective_db_host, order.branch.effective_db_port,
                                     order.branch.db_name or 'SOFTECHDB9')
    try:
        return check_order(order, reader)
    finally:
        reader.close()
