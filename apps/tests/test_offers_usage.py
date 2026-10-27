"""
apps/tests/test_offers_usage.py

Phase-3 exec step 4 (PG-only, NO SOFTECH): offer usage limits + concurrency.
Exhausted offers never attach; consumption is atomic under select_for_update so
two concurrent cashiers can't both take the last use.
"""
from decimal import Decimal
from threading import Thread

from django.db import connection
from django.test import TestCase, TransactionTestCase

from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
from apps.offers.models import Offer, OfferApplication
from apps.offers.engine import evaluate_offers
from apps.offers.usage import (
    offer_exhausted, committed_uses, consume_offer_uses, UsageLimitExceeded,
)
from apps.customers.models import Customer
from .factories import make_branch, make_item


def _item(code, pos_discp=100):
    it = make_item(name=code, softech_id=code)
    it.pos_discp = Decimal(str(pos_discp))
    it.save(update_fields=['pos_discp'])
    return it


def _offer(**kw):
    d = dict(name='O', offer_type='percent', status='active', target_all=True,
             authorization_source='item_card', value=100)
    d.update(kw)
    return Offer.objects.create(**d)


def _order(branch):
    return SoftechSalesOrder.objects.create(
        branch=branch, softech_branchcode=branch.softech_branch_id, store_code='1',
        seller_usercode='1', softech_pic='PIC', channel='cash')


def _attach(order, item, offer, customer=None):
    """Simulate step-3 attach: an offer line + a pending OfferApplication."""
    SoftechSalesOrderLine.objects.create(
        order=order, item=item, softech_itemcode=item.softech_id, qty=1,
        item_sale_price=100, cust_discp=100, discount_source='offer', applied_offer=offer)
    OfferApplication.objects.create(offer=offer, pos_order=order, branch=order.branch,
                                    customer=customer, was_applied=False, discount_amount=100)


class ExhaustionTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.it = _item('A')

    def test_no_limit_never_exhausted(self):
        o = _offer()
        self.assertEqual(offer_exhausted(o), (False, ''))

    def test_total_limit_reached(self):
        o = _offer(max_uses_total=1)
        OfferApplication.objects.create(offer=o, pos_order=_order(self.branch), was_applied=True)
        self.assertEqual(offer_exhausted(o)[0], True)

    def test_per_customer_limit(self):
        o = _offer(max_uses_per_customer=1)
        c = Customer.objects.create(name='C', phone='0100')
        OfferApplication.objects.create(offer=o, pos_order=_order(self.branch),
                                        customer=c, was_applied=True)
        self.assertTrue(offer_exhausted(o, c)[0])         # this customer exhausted
        other = Customer.objects.create(name='D', phone='0200')
        self.assertFalse(offer_exhausted(o, other)[0])    # a different customer is fine

    def test_engine_skips_exhausted_offer(self):
        o = _offer(max_uses_total=1)
        OfferApplication.objects.create(offer=o, pos_order=_order(self.branch), was_applied=True)
        plan = evaluate_offers(
            [{'softech_id': 'A', 'item': self.it, 'qty': 1, 'unit_price': 100}], offers=[o])
        self.assertEqual(plan['total_discount'], Decimal('0.00'))
        self.assertTrue(any('استُنفد' in r['reason'] for r in plan['rejected']))


class ConsumeTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.it = _item('A')

    def test_consume_flips_applied(self):
        o = _offer(max_uses_total=5)
        order = _order(self.branch)
        _attach(order, self.it, o)
        consume_offer_uses(order)
        self.assertEqual(committed_uses(o)[0], 1)

    def test_consume_is_idempotent(self):
        o = _offer(max_uses_total=5)
        order = _order(self.branch)
        _attach(order, self.it, o)
        consume_offer_uses(order)
        consume_offer_uses(order)   # re-run
        self.assertEqual(committed_uses(o)[0], 1)

    def test_consume_blocks_when_exhausted(self):
        o = _offer(max_uses_total=1)
        first = _order(self.branch); _attach(first, self.it, o)
        consume_offer_uses(first)                     # takes the only use
        second = _order(self.branch); _attach(second, self.it, o)
        with self.assertRaises(UsageLimitExceeded):
            consume_offer_uses(second)


class ConcurrencyTests(TransactionTestCase):
    reset_sequences = False

    def test_two_concurrent_consumes_only_one_wins(self):
        branch = make_branch()
        it = _item('A')
        o = _offer(max_uses_total=1)
        o1 = _order(branch); _attach(o1, it, o)
        o2 = _order(branch); _attach(o2, it, o)

        results = {}

        def worker(order, key):
            try:
                consume_offer_uses(order)
                results[key] = 'ok'
            except UsageLimitExceeded:
                results[key] = 'blocked'
            finally:
                connection.close()

        t1 = Thread(target=worker, args=(o1, 'a'))
        t2 = Thread(target=worker, args=(o2, 'b'))
        t1.start(); t2.start()
        t1.join(); t2.join()

        # exactly one succeeds, one is blocked — select_for_update serialized them
        self.assertEqual(sorted(results.values()), ['blocked', 'ok'])
        self.assertEqual(committed_uses(o)[0], 1)
