"""
apps/tests/test_pos_branch_lock.py

UAT finding (2026-11-17, owner decision D2): the POS is locked to the user's own branches.
Every POS lookup that reads a branch's SOFTECH node (stores, salespeople, customer directory,
batches, contract fields, discount caps) refuses a branch outside core.branch_scope; all-branch
roles keep every branch. Read failures reach the user through core.errors.public_error only.
"""
from unittest import mock

from django.test import TestCase, override_settings

from .factories import make_branch, make_branch2, make_user

BASE = '/api/pos-orders/'
LEAK = 'JZ006: Caught IOException: java.net.UnknownHostException: 192.168.77.5 SOFTECHDB9'

# endpoint → (extra query params, reader to stub, stub return value)
LOOKUPS = {
    'customer-entities/': ({'type': 'cash'}, 'apps.pos_orders.customer_directory.list_entities', []),
    'salespeople/':       ({}, 'apps.pos_orders.customer_directory.salespeople', []),
    'branch-stores/':     ({}, 'apps.pos_orders.customer_directory.branch_stores', []),
    'batches/':           ({'item': '123'}, 'apps.pos_orders.batch_availability.item_availability', ([], True)),
    'contract-fields/':   ({'customer': '9001'}, 'apps.pos_orders.contract_fields.contract_field_spec', []),
    'discount-suggest/':  ({'items': '123'}, 'apps.pos_orders.discount_authority.DiscountAuthorityReader', None),
}


def _stub(target, value):
    if value is None:                      # the discount reader is a class: stub its instance
        reader = mock.MagicMock()
        reader.max_authority.return_value = None
        reader.item_posdiscp.return_value = None
        return mock.patch(target, return_value=reader)
    return mock.patch(target, return_value=value)


class PosBranchLockTests(TestCase):
    def setUp(self):
        self.a = make_branch('فرع أ', 'B01')
        self.b = make_branch2('فرع ب', 'B02')
        _, _, self.seller = make_user('lock_seller', role='salesperson', branch=self.a)
        _, _, self.cc = make_user('lock_cc', role='call_center', branch=self.a)

    def _get(self, client, path, branch):
        params, target, value = LOOKUPS[path]
        with _stub(target, value):
            return client.get(BASE + path, {'branch': branch.pk, **params})

    def test_branch_user_refused_for_another_branch(self):
        for path in LOOKUPS:
            with self.subTest(path=path):
                r = self._get(self.seller, path, self.b)
                self.assertEqual(r.status_code, 403, f'{path}: {r.status_code} {getattr(r, "data", "")}')

    def test_branch_user_served_for_own_branch(self):
        for path in LOOKUPS:
            with self.subTest(path=path):
                self.assertEqual(self._get(self.seller, path, self.a).status_code, 200, path)

    def test_all_branch_role_served_for_any_branch(self):
        for path in LOOKUPS:
            with self.subTest(path=path):
                self.assertEqual(self._get(self.cc, path, self.b).status_code, 200, path)


@override_settings(DEBUG=False)
class PosLookupErrorTextTests(TestCase):
    """A failed SOFTECH read shows a reference code, never the driver text or host."""

    def setUp(self):
        self.a = make_branch('فرع أ', 'B01')
        _, _, self.seller = make_user('err_seller', role='salesperson', branch=self.a)

    def test_lookup_failure_hides_internals(self):
        cases = {
            'customer-entities/': ({'type': 'cash'}, 'apps.pos_orders.customer_directory.list_entities'),
            'salespeople/':       ({}, 'apps.pos_orders.customer_directory.salespeople'),
            'branch-stores/':     ({}, 'apps.pos_orders.customer_directory.branch_stores'),
            'discount-suggest/':  ({'items': '123'}, 'apps.pos_orders.discount_authority.DiscountAuthorityReader'),
        }
        for path, (params, target) in cases.items():
            with self.subTest(path=path), \
                    mock.patch(target, side_effect=RuntimeError(LEAK)), \
                    self.assertLogs('elrezeiky.errors', level='ERROR'):
                r = self.seller.get(BASE + path, {'branch': self.a.pk, **params})
                self.assertEqual(r.status_code, 200)          # graceful: empty lists + a note
                body = r.content.decode('utf-8')
                self.assertNotIn('192.168', body)
                self.assertNotIn('JZ006', body)
                self.assertIn('مرجع', r.json()['note'])
