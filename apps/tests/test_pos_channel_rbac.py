"""
apps/tests/test_pos_channel_rbac.py — per-employee POS channel RBAC.

A member may only operate the sales channels they're allowed. Server-authoritative:
the type list is filtered, reference exposes the allow-list, and order creation on a
disallowed channel is rejected. Managers (admin/supervisor) get all channels.
"""
from django.test import TestCase
from .factories import make_user


def _restrict(profile, channels):
    profile.allowed_pos_channels = channels
    profile.save(update_fields=['allowed_pos_channels'])


class ChannelRbacTests(TestCase):
    def test_types_filtered_for_restricted_seller(self):
        _, prof, client = make_user('cash_only', role='salesperson')
        _restrict(prof, ['cash', 'delivery'])
        r = client.get('/api/pos-orders/customer-types/')
        keys = {t['key'] for t in r.data['types']}
        self.assertEqual(keys, {'cash', 'delivery'})
        self.assertNotIn('contract', keys)

    def test_reference_exposes_allow_list(self):
        _, prof, client = make_user('cash_only2', role='salesperson')
        _restrict(prof, ['cash'])
        r = client.get('/api/pos-orders/reference/')
        self.assertEqual(sorted(r.data['allowed_channels']), ['cash'])

    def test_manager_gets_all_channels(self):
        _, _, client = make_user('mgr', role='supervisor')
        r = client.get('/api/pos-orders/customer-types/')
        self.assertGreater(len(r.data['types']), 3)
        ref = client.get('/api/pos-orders/reference/')
        self.assertIsNone(ref.data['allowed_channels'])   # None = all

    def test_empty_allowlist_means_all(self):
        _, _, client = make_user('unrestricted', role='salesperson')  # default [] = all
        r = client.get('/api/pos-orders/customer-types/')
        self.assertGreater(len(r.data['types']), 3)

    def test_create_on_disallowed_channel_rejected(self):
        _, prof, client = make_user('cash_seller', role='salesperson')
        _restrict(prof, ['cash'])
        r = client.post('/api/pos-orders/', {'channel': 'contract', 'branch': 1}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_create_on_allowed_channel_passes_rbac(self):
        _, prof, client = make_user('cash_seller2', role='salesperson')
        _restrict(prof, ['cash'])
        r = client.post('/api/pos-orders/', {'channel': 'cash'}, format='json')
        self.assertNotEqual(r.status_code, 403)   # RBAC passed (serializer may 400 on payload)
