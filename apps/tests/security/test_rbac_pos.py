"""
Authorization — POS orders follow the `pos` matrix; commerce its own module (Batch 4, Z-5b).

Before (RBAC log mode = production): CanOperatePosOrders meant "any active staff", so delivery,
purchasing, quality and viewer read every sale order, the lost-sales and exceptions lists,
points previews and returns, and could create sale orders; any logged-in user could DELETE any
POS order — pushed / collected ones included — through the order detail route; seven roles read
the commerce status and index. Under enforce, doctor-referral stats (an Analytics report) was
blocked for quality and viewer because it sits under /api/pos-orders/.
"""
from django.test import TestCase, override_settings

from apps.pos_orders.models import SoftechSalesOrder
from apps.tests.factories import make_branch, make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .sweep import sweep

PREFIXES = {'pos-orders', 'offers', 'commerce'}


def _blocked_by_matrix(response):
    return response.status_code == 403 and 'module' in (response.json() if response.content else {})


class PosSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes=PREFIXES)
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class PosOrderRecordTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        br = make_branch()
        self.order = SoftechSalesOrder.objects.create(branch=br, softech_branchcode=br.softech_branch_id)

    def tearDown(self):
        module_access.clear_cache()

    def _as(self, role):
        return bearer_client(make_user(f'z5b_{role}', role=role)[0])

    def test_viewer_cannot_delete_a_sale_order(self):
        self.assertEqual(self._as('viewer').delete(f'/api/pos-orders/{self.order.pk}/').status_code, 403)
        self.assertTrue(SoftechSalesOrder.objects.filter(pk=self.order.pk).exists())

    def test_cashier_cannot_delete_a_sale_order(self):
        # matrix: salesperson has pos view + create, not delete
        self.assertEqual(self._as('salesperson').delete(f'/api/pos-orders/{self.order.pk}/').status_code, 403)

    def test_delivery_cannot_read_sale_orders(self):
        self.assertEqual(self._as('delivery').get(f'/api/pos-orders/{self.order.pk}/').status_code, 403)

    def test_cashier_reads_the_order(self):
        self.assertEqual(self._as('salesperson').get(f'/api/pos-orders/{self.order.pk}/').status_code, 200)


@override_settings(RBAC_ENFORCEMENT='enforce')
class ReferralStatsUnderEnforceTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def test_analytics_roles_keep_referral_stats(self):
        for role in ('viewer', 'quality_manager'):
            r = bearer_client(make_user(f'z5r_{role}', role=role)[0]).get('/api/pos-orders/referral-stats/')
            self.assertFalse(_blocked_by_matrix(r), role)
