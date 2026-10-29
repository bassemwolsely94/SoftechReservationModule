"""
Authorization — pricing approvals follow the `approvals` matrix (Batch 4, Z-6).

Before (RBAC log mode = production): every pricing-approval read — price preview, current
prices, price history, the SLA board, approver info, pending count, the alignment scan /
policies / tiers — answered any logged-in role; call center, delivery and salesperson (no
approvals grant) and viewer (view only) could file price-change requests one by one, in bulk
from a spreadsheet, or as a rollback of an executed change; /api/approvals/ answered with its
router index. Executing a change still needed an admin — that part is unchanged.
"""
from decimal import Decimal

from django.test import TestCase, override_settings

from apps.discount_approvals.models import ItemPriceChangeRequest
from apps.tests.factories import make_item, make_user
from core.middleware import module_access

from .fixtures import bearer_client, role_clients, seed_code_matrix
from .sweep import sweep

PREFIXES = {'pricing-approvals', 'approvals'}


class PricingSweepTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = role_clients()

    def tearDown(self):
        module_access.clear_cache()

    def test_no_role_gets_past_the_view_without_the_grant(self):
        res = sweep('log', self.clients, prefixes=PREFIXES)
        self.assertEqual(sorted(res.leaks), [])


@override_settings(RBAC_ENFORCEMENT='log')
class PriceRequestTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.item = make_item(name='Z6 item', softech_id='Z6001')

    def tearDown(self):
        module_access.clear_cache()

    def _file(self, role):
        c = bearer_client(make_user(f'z6_{role}', role=role)[0])
        return c.post('/api/pricing-approvals/', {'item': self.item.pk, 'new_values': {'pack_price': '99.00'},
                                                  'reason': 'z6'}, format='json')

    def test_salesperson_cannot_file_a_price_change(self):
        self.assertEqual(self._file('salesperson').status_code, 403)
        self.assertFalse(ItemPriceChangeRequest.objects.exists())

    def test_viewer_cannot_file_a_price_change(self):
        self.assertEqual(self._file('viewer').status_code, 403)

    def test_delivery_cannot_read_price_history(self):
        c = bearer_client(make_user('z6_del', role='delivery')[0])
        self.assertEqual(c.get(f'/api/pricing-approvals/history/{self.item.softech_id}/').status_code, 403)

    def test_purchasing_still_files_a_price_change(self):
        self.assertNotEqual(self._file('purchasing').status_code, 403)
