"""
apps/tests/test_pos_discount_authority.py — authority-aware discount check logic.

Uses a FakeReader so the rules are tested without SOFTECH. Proves:
  • allow_sell=0 blocks the line
  • discount above the contracted rate needs the seller's ceiling
  • unresolved mappings (None) are skipped (never a false reject)
"""
from decimal import Decimal
from django.test import TestCase

from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
from apps.pos_orders.discount_authority import check_order, validate_contract_discount_role
from .factories import make_branch


def _order(seller='1509', pic='130HD9668', **kw):
    br = make_branch()
    return SoftechSalesOrder.objects.create(
        branch=br, softech_branchcode=br.softech_branch_id, store_code='130',
        seller_usercode=seller, softech_pic=pic, channel='contract', **kw)


def _line(o, discp, item='123'):
    return SoftechSalesOrderLine.objects.create(
        order=o, softech_itemcode=item, qty=Decimal('1'),
        item_sale_price=Decimal('100'), cust_discp=Decimal(str(discp)))


class FakeReader:
    """Configurable stand-in for DiscountAuthorityReader."""
    def __init__(self, *, category='10', personcode='1500', seller_pc='89',
                 contracted=(Decimal('40'), 1), ceiling=Decimal('50')):
        self._category, self._personcode, self._seller_pc = category, personcode, seller_pc
        self._contracted, self._ceiling = contracted, ceiling
    def item_category(self, itemcode): return self._category
    def customer_personcode(self, channel): return self._personcode
    def seller_personcode(self, usercode): return self._seller_pc
    def contracted(self, personcode, custdiscpcode): return self._contracted
    def max_authority(self, personcode, branchcode): return self._ceiling


class DiscountAuthorityTests(TestCase):
    def test_within_contracted_passes(self):
        o = _order(); _line(o, 40)                      # == contracted 40%
        self.assertEqual(check_order(o, FakeReader()), [])

    def test_below_contracted_passes(self):
        o = _order(); _line(o, 25)
        self.assertEqual(check_order(o, FakeReader()), [])

    def test_above_contracted_within_ceiling_passes(self):
        o = _order(); _line(o, 48)                      # >40 contracted, <=50 ceiling
        self.assertEqual(check_order(o, FakeReader()), [])

    def test_above_contracted_over_ceiling_blocked(self):
        o = _order(); _line(o, 60)                      # >40 contracted, >50 ceiling
        errs = check_order(o, FakeReader())
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]['field'], 'cust_discp')

    def test_above_contracted_no_ceiling_blocked(self):
        o = _order(); _line(o, 45)
        errs = check_order(o, FakeReader(ceiling=None))  # seller has no authority row
        self.assertEqual(len(errs), 1)

    def test_allow_sell_zero_blocks(self):
        o = _order(); _line(o, 10)
        errs = check_order(o, FakeReader(contracted=(Decimal('40'), 0)))
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]['field'], 'softech_itemcode')

    def test_unresolved_category_skips(self):
        o = _order(); _line(o, 99)                      # crazy discount
        self.assertEqual(check_order(o, FakeReader(category=None)), [])  # no false reject

    def test_unresolved_customer_skips(self):
        o = _order(); _line(o, 99)
        self.assertEqual(check_order(o, FakeReader(personcode=None)), [])

    def test_zero_discount_ignored(self):
        o = _order(); _line(o, 0)
        self.assertEqual(check_order(o, FakeReader(contracted=(Decimal('0'), 0))), [])


def _ord(channel):
    br = make_branch()
    return SoftechSalesOrder.objects.create(
        branch=br, softech_branchcode=br.softech_branch_id, store_code='130',
        seller_usercode='1509', softech_pic='x', channel=channel)


class ContractDiscountRoleTests(TestCase):
    """Manager-locked contract/permanent discount (deterministic, no live DB)."""

    def test_nonpriv_contract_discount_blocked(self):
        o = _ord('contract'); _line(o, 10)
        errs = validate_contract_discount_role(o, privileged=False)
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]['field'], 'cust_discp')

    def test_priv_contract_discount_allowed(self):
        o = _ord('contract'); _line(o, 10)
        self.assertEqual(validate_contract_discount_role(o, privileged=True), [])

    def test_nonpriv_permanent_discount_blocked(self):
        o = _ord('permanent'); _line(o, 5)
        self.assertEqual(len(validate_contract_discount_role(o, privileged=False)), 1)

    def test_nonpriv_cash_discount_allowed(self):
        o = _ord('cash'); _line(o, 5)          # retail is cap-only, not manager-locked here
        self.assertEqual(validate_contract_discount_role(o, privileged=False), [])

    def test_offer_line_skipped(self):
        o = _ord('contract'); ln = _line(o, 10)
        ln.discount_source = 'offer'; ln.save()
        self.assertEqual(validate_contract_discount_role(o, privileged=False), [])

    def test_zero_discount_allowed(self):
        o = _ord('contract'); _line(o, 0)
        self.assertEqual(validate_contract_discount_role(o, privileged=False), [])
