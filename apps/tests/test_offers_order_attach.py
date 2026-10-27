"""
apps/tests/test_offers_order_attach.py

Phase-3 exec step 3 (PG-only, NO SOFTECH push): attach an offer plan onto a real
POS order — writes cust_discp + applied_offer + discount_source, records
OfferApplication, and gates the live push behind an apps/approvals approval when
the plan needs sign-off. Everything is gated by POS_OFFERS_EXECUTION_ENABLED.
"""
from decimal import Decimal
from django.test import TestCase, override_settings

from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
from apps.offers.models import Offer, OfferApplication
from apps.offers import order_attach
from .factories import make_branch, make_item, make_user


def _item(code, pos_discp):
    it = make_item(name=code, softech_id=code)
    it.pos_discp = Decimal(str(pos_discp))
    it.save(update_fields=['pos_discp'])
    return it


def _order(branch, channel='cash'):
    return SoftechSalesOrder.objects.create(
        branch=branch, softech_branchcode=branch.softech_branch_id, store_code='1',
        seller_usercode='1', softech_pic='PIC', channel=channel)


def _line(o, it, qty, price):
    return SoftechSalesOrderLine.objects.create(
        order=o, item=it, softech_itemcode=it.softech_id, qty=Decimal(str(qty)),
        item_sale_price=Decimal(str(price)))


def _bxgy(auth='item_card', **kw):
    d = dict(name='BXGY', offer_type='bxgy', status='active', target_all=True,
             buy_qty=1, get_qty=1, bxgy_scope='group_cheapest', authorization_source=auth,
             require_stock=False)
    d.update(kw)
    return Offer.objects.create(**d)


class GatingTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.a = _item('A', 100); self.b = _item('B', 100)
        self.order = _order(self.branch)
        _line(self.order, self.a, 1, 100); _line(self.order, self.b, 1, 60)
        _bxgy()

    def test_disabled_is_noop(self):   # default flag off
        res = order_attach.apply_offers_to_order(self.order)
        self.assertFalse(res['enabled'])
        self.assertFalse(res['attached'])
        self.assertEqual(self.order.lines.filter(discount_source='offer').count(), 0)

    @override_settings(POS_OFFERS_EXECUTION_ENABLED=True)
    def test_enabled_attaches_offer_to_line(self):
        res = order_attach.apply_offers_to_order(self.order)
        self.assertTrue(res['attached'])
        # cheaper line (B) gets the 100% offer discount + provenance
        bline = self.order.lines.get(item=self.b)
        self.assertEqual(bline.discount_source, 'offer')
        self.assertEqual(bline.cust_discp, Decimal('100.00'))
        self.assertIsNotNone(bline.applied_offer_id)
        self.assertEqual(bline.trans_price_total, Decimal('0.00'))   # free
        # audit row written
        self.assertTrue(OfferApplication.objects.filter(pos_order=self.order).exists())

    @override_settings(POS_OFFERS_EXECUTION_ENABLED=True)
    def test_item_card_needs_no_approval(self):
        res = order_attach.apply_offers_to_order(self.order)
        self.assertFalse(res['requires_approval'])
        self.assertIsNone(order_attach.offer_approval_request(self.order))


@override_settings(POS_OFFERS_EXECUTION_ENABLED=True)
class ApprovalGateTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.actor, _ = make_user('attach_actor', role='pharmacist')
        _, self.sup, _ = make_user('attach_sup', role='supervisor')   # step approver
        self.a = _item('A', 0); self.b = _item('B', 0)                 # item card authorizes 0…
        self.order = _order(self.branch)
        _line(self.order, self.a, 1, 100); _line(self.order, self.b, 1, 60)
        _bxgy(auth='offer', get_discount_percent=100)                   # …offer overrides → approval

    def test_offer_mode_raises_pending_approval(self):
        res = order_attach.apply_offers_to_order(self.order, actor=self.actor)
        self.assertTrue(res['requires_approval'])
        req = order_attach.offer_approval_request(self.order)
        self.assertIsNotNone(req)
        self.assertEqual(req.status, 'pending')

    def test_push_blocked_until_approved(self):
        order_attach.apply_offers_to_order(self.order, actor=self.actor)
        self.assertIsNotNone(order_attach.push_blocked_by_offer_approval(self.order))
        # approve via the EXISTING approvals engine
        from apps.approvals.service import ApprovalService
        from apps.approvals.models import ApprovalDecision
        req = order_attach.offer_approval_request(self.order)
        ApprovalService.decide(request=req, decision=ApprovalDecision.DECISION_APPROVED,
                               decided_by=self.sup, notes='ok')
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        self.assertIsNone(order_attach.push_blocked_by_offer_approval(self.order))

    def test_guard_noop_for_non_offer_order(self):
        plain = _order(self.branch)
        _line(plain, self.a, 1, 100)
        self.assertIsNone(order_attach.push_blocked_by_offer_approval(plain))


class PushViewGuardTests(TestCase):
    @override_settings(POS_OFFERS_EXECUTION_ENABLED=True, POS_WRITER_ENABLED=True)
    def test_live_push_blocked_by_pending_offer_approval(self):
        branch = make_branch()
        _, actor, _ = make_user('pv_actor', role='pharmacist')
        _, _, sup_client = make_user('pv_sup', role='supervisor')
        a = _item('A', 0); b = _item('B', 0)
        order = _order(branch)
        _line(order, a, 1, 100); _line(order, b, 1, 60)
        _bxgy(auth='offer', get_discount_percent=100)
        order_attach.apply_offers_to_order(order, actor=actor)
        # a live push attempt must be refused (409) pending approval
        r = sup_client.post(f'/api/pos-orders/{order.id}/push/',
                            {'dry_run': False, 'confirm': True}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.data.get('requires_offer_approval'))
