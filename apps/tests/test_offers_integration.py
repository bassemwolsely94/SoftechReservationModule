"""
apps/tests/test_offers_integration.py

End-to-end: the exact pipeline the /offers config page drives — create an offer
via the API with the flexible selector, preview its matches, then execute it onto a
real POS order and confirm the discount + the SOFTECH override stamp. PG-only
(no SOFTECH push).
"""
from decimal import Decimal
from django.test import TestCase, override_settings

from apps.catalog.models import Item
from apps.offers.models import Offer
from apps.offers import order_attach
from apps.pos_orders.models import SoftechSalesOrder, SoftechSalesOrderLine
from apps.pos_orders.writer import _header_row
from .factories import make_branch, make_item, make_user


def _item(code, producer, pos_discp=0, price=0):
    it = make_item(name=code, softech_id=code)
    it.producer_code = producer
    it.pos_discp = Decimal(str(pos_discp))
    it.save()
    return it


@override_settings(POS_OFFERS_EXECUTION_ENABLED=True)
class ConfigToExecutionTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, self.admin_p, self.admin = make_user('int_admin', role='admin')
        # a Parkville-style 1+1 on two items (posdiscp 100 = genuine free)
        self.a = _item('PA', 'PARK', pos_discp=100)
        self.b = _item('PB', 'PARK', pos_discp=100)
        self.other = _item('OT', 'OTHER', pos_discp=100)

    def test_full_pipeline(self):
        # 1) create the offer exactly as the config page would POST it
        body = {
            'name': 'Parkville 1+1', 'name_ar': 'باركفيل 1+1', 'offer_type': 'bxgy',
            'status': 'active', 'authorization_source': 'item_card',
            'buy_qty': 1, 'get_qty': 1, 'bxgy_scope': 'group_cheapest',
            'require_stock': False,
            'target_spec': {'match': 'all', 'rules': [
                {'field': 'producer_code', 'op': 'eq', 'value': 'PARK'}]},
        }
        r = self.admin.post('/api/offers/', body, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        offer_id = r.data['id']

        # 2) the selector preview the page shows must match exactly the PARK items
        pv = self.admin.post('/api/offers/target-preview/',
                             {'target_spec': body['target_spec']}, format='json')
        self.assertEqual(pv.status_code, 200)
        self.assertEqual(pv.data['count'], 2)
        codes = {s['softech_id'] for s in pv.data['sample']}
        self.assertEqual(codes, {'PA', 'PB'})

        # 3) build a POS order: buy PA@100 + PB@60 (+ an unrelated item)
        order = SoftechSalesOrder.objects.create(
            branch=self.branch, softech_branchcode=self.branch.softech_branch_id,
            store_code='1', seller_usercode='1', softech_pic='PIC', channel='cash')
        for it, price in ((self.a, 100), (self.b, 60), (self.other, 50)):
            SoftechSalesOrderLine.objects.create(
                order=order, item=it, softech_itemcode=it.softech_id, qty=1, item_sale_price=price)

        # 4) execute the offer onto the order (Channel C attach; still no SOFTECH push)
        res = order_attach.apply_offers_to_order(order, actor=self.admin_p)
        self.assertTrue(res['attached'])
        self.assertFalse(res['requires_approval'])          # item_card 1+1 → no approval

        # the cheaper PARK unit (PB@60) is the free one; OTHER untouched
        pb = order.lines.get(item=self.b)
        self.assertEqual(pb.discount_source, 'offer')
        self.assertEqual(pb.cust_discp, Decimal('100.00'))
        self.assertEqual(pb.trans_price_total, Decimal('0.00'))
        self.assertEqual(order.lines.get(item=self.other).discount_source, 'manual')

        # 5) the writer header carries the Ctrl+M/OFFERS override stamp (verified live)
        h = _header_row(order, docnumber=1, seller='1')
        self.assertEqual(h['supp_main_code'], '89')

    def test_offer_create_requires_privilege(self):
        _, _, viewer = make_user('int_viewer', role='viewer')
        r = viewer.post('/api/offers/', {'name': 'x', 'offer_type': 'percent', 'value': 10}, format='json')
        self.assertEqual(r.status_code, 403)
