"""
Authorization — offers are their own matrix module, under المخزون, not POS (Batch 4, Z-5a;
owner decisions 2026-10-27: a new `offers` module managed by admin / supervisor / purchasing;
offers belong under المخزون and not under POS directly).

Before: /api/offers/ was checked as POS, so under enforce purchasing (which manages offers, per
apps/offers/permissions.py and the menu) lost the screen; in log mode (production) any active
staff — viewer, delivery, quality — read every offer and could run the checkout evaluation; and
the menu listed offers under العملاء.
"""
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from apps.users.management.commands.seed_permissions import ALL_MODULES, PERMISSIONS
from apps.users.models import MODULE_CHOICES
from core.middleware import module_access

from .fixtures import bearer_client, seed_code_matrix


def _blocked_by_matrix(response):
    return response.status_code == 403 and 'module' in (response.json() if response.content else {})


class OffersModuleTests(TestCase):

    def test_offers_is_a_matrix_module(self):
        self.assertIn('offers', dict(MODULE_CHOICES))
        self.assertIn('offers', ALL_MODULES)
        for role in ('supervisor', 'purchasing'):
            self.assertIn('edit', PERMISSIONS[role].get('offers', set()), role)
        for role in ('salesperson', 'call_center', 'delivery', 'viewer'):
            self.assertFalse(PERMISSIONS[role].get('offers'), role)

    def test_management_is_offers_checkout_stays_pos(self):
        self.assertEqual(module_access.required('/api/offers/', 'GET')[0], 'offers')
        self.assertEqual(module_access.required('/api/offers/evaluate/', 'POST')[0], 'pos')
        self.assertEqual(module_access.required('/api/offers/apply-to-order/', 'POST')[0], 'pos')

    def test_menu_lists_offers_under_inventory(self):
        layout = (Path(settings.BASE_DIR) / 'frontend/src/components/Layout.jsx').read_text(encoding='utf-8')
        start = layout.index("id: 'inventory'")
        end = layout.index("id: 'purchasing'")
        self.assertIn("to: '/offers'", layout[start:end], 'offers not in the المخزون menu section')


@override_settings(RBAC_ENFORCEMENT='enforce')
class OffersUnderEnforceTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def _as(self, role):
        return bearer_client(make_user(f'z5_{role}', role=role)[0])

    def test_purchasing_keeps_the_offers_screen(self):
        self.assertFalse(_blocked_by_matrix(self._as('purchasing').get('/api/offers/')))

    def test_cashier_still_evaluates_offers_at_checkout(self):
        r = self._as('salesperson').post('/api/offers/evaluate/', {'basket': []}, format='json')
        self.assertFalse(_blocked_by_matrix(r))


@override_settings(RBAC_ENFORCEMENT='log')
class OffersViewLevelTests(TestCase):

    def setUp(self):
        seed_code_matrix()

    def tearDown(self):
        module_access.clear_cache()

    def test_roles_without_offers_cannot_read_them(self):
        for role in ('viewer', 'delivery', 'quality_manager'):
            r = bearer_client(make_user(f'z5v_{role}', role=role)[0]).get('/api/offers/')
            self.assertEqual(r.status_code, 403, role)

    def test_checkout_evaluation_needs_pos(self):
        r = bearer_client(make_user('z5v_viewer2', role='viewer')[0]).post(
            '/api/offers/evaluate/', {'basket': [{'softech_id': '1', 'qty': 1, 'unit_price': 10}]}, format='json')
        self.assertEqual(r.status_code, 403)
