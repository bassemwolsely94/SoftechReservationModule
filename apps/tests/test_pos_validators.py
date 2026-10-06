"""
apps/tests/test_pos_validators.py — field-level validation for Indirect-POS orders.
"""
from decimal import Decimal
from django.test import TestCase
from rest_framework.exceptions import ValidationError

from apps.pos_orders.models import (
    SoftechSalesOrder, SoftechSalesOrderLine, SoftechSalesOrderPayment,
)
from apps.pos_orders.validators import validate_order
from .factories import make_branch


def _order(**kw):
    br = make_branch()
    kw.setdefault('store_code', '130')
    return SoftechSalesOrder.objects.create(
        branch=br, softech_branchcode=br.softech_branch_id, **kw)


def _line(o, **kw):
    kw.setdefault('softech_itemcode', '12345')
    kw.setdefault('qty', Decimal('1'))
    kw.setdefault('item_sale_price', Decimal('10'))
    kw.setdefault('cust_discp', Decimal('0'))
    return SoftechSalesOrderLine.objects.create(order=o, **kw)


def _err_keys(cm):
    return set(cm.exception.detail.keys())


class ValidatorTests(TestCase):
    def test_valid_cash_order_passes(self):
        o = _order(channel='cash', doc_kind='sale')
        _line(o)
        self.assertTrue(validate_order(o))

    def test_inactive_branch_blocked(self):
        o = _order(channel='cash'); _line(o)
        o.branch.is_operational = False; o.branch.save()
        with self.assertRaises(ValidationError) as cm:
            validate_order(o)
        self.assertIn('branch', _err_keys(cm))

    def test_no_lines_blocked(self):
        o = _order(channel='cash')
        with self.assertRaises(ValidationError) as cm:
            validate_order(o)
        self.assertIn('lines', _err_keys(cm))

    def test_return_requires_invoice(self):
        o = _order(channel='cash', doc_kind='return'); _line(o)
        with self.assertRaises(ValidationError) as cm:
            validate_order(o)
        self.assertIn('return_of_invoice', _err_keys(cm))

    def test_contract_requires_pic(self):
        o = _order(channel='contract', softech_pic=''); _line(o)
        with self.assertRaises(ValidationError) as cm:
            validate_order(o)
        self.assertIn('softech_pic', _err_keys(cm))

    def test_bad_qty_and_discount_flagged_per_line(self):
        o = _order(channel='cash')
        _line(o, qty=Decimal('0'))                 # qty must be > 0
        _line(o, cust_discp=Decimal('150'))        # discount out of range
        with self.assertRaises(ValidationError) as cm:
            validate_order(o)
        detail = cm.exception.detail['lines_detail']
        flagged = {k for d in detail for k in d if k != 'index'}
        self.assertIn('qty', flagged)
        self.assertIn('cust_discp', flagged)

    def test_credit_tender_rejected_on_cash_channel(self):
        o = _order(channel='cash'); _line(o)
        SoftechSalesOrderPayment.objects.create(order=o, pay_type='credit', amount=Decimal('10'))
        with self.assertRaises(ValidationError) as cm:
            validate_order(o)
        self.assertIn('payments_detail', _err_keys(cm))

    def test_push_balance_mismatch_blocked(self):
        o = _order(channel='cash', doc_value=Decimal('10')); _line(o)
        SoftechSalesOrderPayment.objects.create(order=o, pay_type='cash', amount=Decimal('7'))
        with self.assertRaises(ValidationError) as cm:
            validate_order(o, for_push=True)
        self.assertIn('payments', _err_keys(cm))

    def test_push_contract_requires_claim(self):
        o = _order(channel='contract', softech_pic='130HD9668', doc_value=Decimal('10'))
        _line(o)
        SoftechSalesOrderPayment.objects.create(order=o, pay_type='credit', amount=Decimal('10'))
        with self.assertRaises(ValidationError) as cm:
            validate_order(o, for_push=True)
        self.assertIn('claim', _err_keys(cm))

    def test_push_contract_with_claim_passes(self):
        o = _order(channel='contract', softech_pic='130HD9668', doc_value=Decimal('10'),
                   source_companies_raw={'patientno': '500145123261', 'membershipno': 'dms'})
        _line(o, source_raw={'itemexpirydate': {'__dt__': '2028-02-01 00:00:00'}})
        SoftechSalesOrderPayment.objects.create(order=o, pay_type='credit', amount=Decimal('10'))
        self.assertTrue(validate_order(o, for_push=True))
