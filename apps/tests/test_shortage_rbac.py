"""
apps/tests/test_shortage_rbac.py

The market-shortage (/api/purchasing/shortage/) and phantom-sales
(/api/purchasing/phantom/) APIs check the RBAC matrix server-side
(apps.purchasing.shortage_permissions), not just the React RequireRole.
A denied confirm must never reach shortage_writer (the SOFTECH push).
"""
from unittest import mock

from django.test import TestCase

from apps.users.models import RoleModuleAccess
from core.middleware import module_access
from .factories import make_item, make_user

FLAG = '/api/purchasing/shortage/flag/'
DISMISS = '/api/purchasing/shortage/dismiss/'
CANDIDATES = '/api/purchasing/shortage/confirmed/'
EXPORT = '/api/purchasing/shortage/export/'
PHANTOM_CONFIRM = '/api/purchasing/phantom/confirm/'
PUSH = 'apps.purchasing.shortage_writer.push_item'


def grant(role, module, *actions):
    for a in actions:
        RoleModuleAccess.objects.create(role=role, module=module, action=a, is_allowed=True)
    module_access.clear_cache()


class SeededMatrixTests(TestCase):
    def setUp(self):
        module_access.clear_cache()
        # mirrors the live matrix: pharmacist approves shortages; salesperson may only
        # view/create/edit; quality_manager view + export; nobody but purchasing on 'purchasing'
        grant('pharmacist', 'shortage', 'view', 'create', 'edit', 'approve', 'export')
        grant('salesperson', 'shortage', 'view', 'create', 'edit')
        grant('quality_manager', 'shortage', 'view', 'export')
        grant('purchasing', 'purchasing', 'view', 'edit', 'approve')
        self.item = make_item(softech_id='SR001')
        self.item.shortage_softech_synced = True
        self.item.save(update_fields=['shortage_softech_synced'])

    def tearDown(self):
        module_access.clear_cache()

    def _assert_untouched(self):
        self.item.refresh_from_db()
        self.assertFalse(self.item.in_shortage)
        self.assertFalse(self.item.shortage_dismissed)
        self.assertTrue(self.item.shortage_softech_synced)   # nothing queued for SOFTECH

    def test_role_without_approve_cannot_flag(self):
        _, _, client = make_user('sr_sales', role='salesperson')
        with mock.patch(PUSH) as push:
            r = client.post(FLAG, {'item_id': self.item.id}, format='json')
        self.assertEqual(r.status_code, 403)
        push.assert_not_called()
        self._assert_untouched()

    def test_role_without_approve_cannot_dismiss(self):
        _, _, client = make_user('sr_qm', role='quality_manager')
        with mock.patch(PUSH) as push:
            r = client.post(DISMISS, {'item_id': self.item.id, 'reason': 'obsolete'}, format='json')
        self.assertEqual(r.status_code, 403)
        push.assert_not_called()
        self._assert_untouched()

    def test_role_with_no_grant_cannot_read(self):
        _, _, client = make_user('sr_cc', role='call_center')
        self.assertEqual(client.get(CANDIDATES).status_code, 403)

    def test_pharmacist_with_approve_can_flag(self):
        _, _, client = make_user('sr_pharm', role='pharmacist')
        with mock.patch(PUSH, return_value=True) as push:
            r = client.post(FLAG, {'item_id': self.item.id}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        push.assert_called_once()
        self.item.refresh_from_db()
        self.assertTrue(self.item.in_shortage)

    def test_purchasing_grant_also_counts(self):
        _, _, client = make_user('sr_purch', role='purchasing')
        with mock.patch(PUSH, return_value=True) as push:
            r = client.post(FLAG, {'item_id': self.item.id}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        push.assert_called_once()

    def test_view_grant_reads_but_export_needs_export(self):
        _, _, client = make_user('sr_sales2', role='salesperson')
        self.assertEqual(client.get(CANDIDATES).status_code, 200)
        self.assertEqual(client.get(EXPORT, {'view': 'confirmed'}).status_code, 403)

    def test_phantom_review_needs_edit(self):
        _, _, qm = make_user('sr_qm2', role='quality_manager')
        self.assertEqual(qm.post(PHANTOM_CONFIRM, {'item_id': self.item.id}, format='json').status_code, 403)
        _, _, sales = make_user('sr_sales3', role='salesperson')
        self.assertEqual(sales.post(PHANTOM_CONFIRM, {'item_id': self.item.id}, format='json').status_code, 200)


class EmptyMatrixFallbackTests(TestCase):
    """Matrix never seeded → the old frontend role list decides."""

    def setUp(self):
        RoleModuleAccess.objects.all().delete()   # data migrations seed a few rows
        module_access.clear_cache()
        self.item = make_item(softech_id='SR002')

    def tearDown(self):
        module_access.clear_cache()

    def test_listed_role_allowed(self):
        _, _, client = make_user('fb_qm', role='quality_manager')
        with mock.patch(PUSH, return_value=True) as push:
            r = client.post(FLAG, {'item_id': self.item.id}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        push.assert_called_once()

    def test_unlisted_role_denied(self):
        _, _, client = make_user('fb_sales', role='salesperson')
        with mock.patch(PUSH) as push:
            r = client.post(FLAG, {'item_id': self.item.id}, format='json')
        self.assertEqual(r.status_code, 403)
        push.assert_not_called()
        self.item.refresh_from_db()
        self.assertFalse(self.item.in_shortage)
