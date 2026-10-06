"""
apps/tests/test_offers_push_consume.py

Phase-3 exec step 5 WIRING (flag stays off in prod; here we force it on + mock the
SOFTECH writer): a successful LIVE push consumes offer uses (flips OfferApplication
was_applied=True); an exhausted offer is rejected BEFORE any write. The writer is
mocked — no real SOFTECH contact.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
from apps.offers.models import Offer, OfferApplication
from apps.offers import order_attach
from .factories import make_branch, make_item, make_user

PUSH = '/api/pos-orders/{}/push/'


def _item(code, pos_discp=100):
    it = make_item(name=code, softech_id=code)
    it.pos_discp = Decimal(str(pos_discp))
    it.save(update_fields=['pos_discp'])
    return it


def _order(branch):
    return SoftechSalesOrder.objects.create(
        branch=branch, softech_branchcode=branch.softech_branch_id, store_code='1',
        seller_usercode='1', softech_pic='PIC', channel='cash')


def _line(o, it, price):
    return SoftechSalesOrderLine.objects.create(
        order=o, item=it, softech_itemcode=it.softech_id, qty=1, item_sale_price=price)


def _bxgy(**kw):
    d = dict(name='1+1', offer_type='bxgy', status='active', target_all=True,
             buy_qty=1, get_qty=1, bxgy_scope='group_cheapest', authorization_source='item_card',
             require_stock=False)
    d.update(kw)
    return Offer.objects.create(**d)


@override_settings(POS_OFFERS_EXECUTION_ENABLED=True, POS_WRITER_ENABLED=True)
class PushConsumeTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, _, self.client_ = make_user('push_ph', role='pharmacist')
        self.a = _item('A'); self.b = _item('B')

    def _order_with_offer(self, offer):
        o = _order(self.branch)
        _line(o, self.a, 100); _line(o, self.b, 60)
        order_attach.apply_offers_to_order(o)   # attaches offer to cheaper line
        return o

    def _live_push(self, order):
        with patch('apps.pos_orders.views.validate_order'), \
             patch('apps.pos_orders.views.writer.writer_enabled', return_value=True), \
             patch('apps.pos_orders.views.writer.push_order', return_value={'pushed': True}):
            return self.client_.post(PUSH.format(order.id),
                                     {'dry_run': False, 'confirm': True}, format='json')

    def test_successful_push_consumes_uses(self):
        offer = _bxgy(max_uses_total=5)
        order = self._order_with_offer(offer)
        self.assertFalse(OfferApplication.objects.filter(pos_order=order, was_applied=True).exists())
        r = self._live_push(order)
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(r.data.get('offer_uses_consumed', 0), 1)
        self.assertTrue(OfferApplication.objects.filter(pos_order=order, was_applied=True).exists())

    def test_exhausted_offer_rejected_before_write(self):
        offer = _bxgy(max_uses_total=1)
        order = self._order_with_offer(offer)   # attach while still available
        # …then the last use is taken by another order before this one pushes
        other = _order(self.branch)
        OfferApplication.objects.create(offer=offer, pos_order=other, was_applied=True)
        with patch('apps.pos_orders.views.validate_order'), \
             patch('apps.pos_orders.views.writer.writer_enabled', return_value=True), \
             patch('apps.pos_orders.views.writer.push_order', return_value={'pushed': True}) as mock_push:
            r = self.client_.post(PUSH.format(order.id),
                                  {'dry_run': False, 'confirm': True}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.data.get('offer_usage_exhausted'))
        mock_push.assert_not_called()          # never wrote

    def test_dry_run_does_not_consume(self):
        offer = _bxgy(max_uses_total=5)
        order = self._order_with_offer(offer)
        with patch('apps.pos_orders.views.writer.push_order', return_value={'pushed': True, 'dry_run': True}):
            r = self.client_.post(PUSH.format(order.id), {'dry_run': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(OfferApplication.objects.filter(pos_order=order, was_applied=True).exists())

    def test_repush_is_idempotent(self):
        offer = _bxgy(max_uses_total=5)
        order = self._order_with_offer(offer)
        self._live_push(order)
        self._live_push(order)   # again
        self.assertEqual(
            OfferApplication.objects.filter(pos_order=order, offer=offer, was_applied=True).count(), 1)
