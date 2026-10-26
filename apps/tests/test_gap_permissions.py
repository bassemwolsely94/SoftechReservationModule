"""
Server-side permissions for four screens that were limited only in the frontend
(SECURITY_HARDENING gaps 3–6, fixed 2026-10-26): supplier invoices, system settings,
cash-optimization spike confirm, and the demand detail final actions.
"""
from django.test import TestCase

from apps.catalog.models import Item
from apps.config.models import SystemSetting
from apps.demand.models import DemandRecord
from apps.invoices.models import SupplierInvoice
from apps.tests.factories import make_branch, make_item, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

GRANTS = {
    ('purchasing', 'invoices'):   {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
    ('purchasing', 'purchasing'): {'view', 'create', 'edit', 'approve', 'export', 'finalize'},
    ('pharmacist', 'settings'):   {'view'},
    ('pharmacist', 'demand'):     {'view', 'create', 'edit'},
    ('supervisor', 'demand'):     {'view', 'create', 'edit', 'approve', 'export', 'assign'},
    ('viewer', 'invoices'):       {'view'},
}


class _Base(TestCase):
    def setUp(self):
        module_access.clear_cache()
        for (role, module), actions in GRANTS.items():
            for a in actions:
                RoleModuleAccess.objects.create(role=role, module=module, action=a)
        self.branch = make_branch()

    def tearDown(self):
        module_access.clear_cache()

    def _client(self, role):
        return make_user(f'gp_{role}', role=role, branch=self.branch)[2]


class InvoicePermissionTests(_Base):
    def setUp(self):
        super().setUp()
        self.inv = SupplierInvoice.objects.create(branch=self.branch)
        self.url = f'/api/invoices/invoices/{self.inv.pk}/'

    def test_reads_need_view(self):
        self.assertEqual(self._client('salesperson').get('/api/invoices/invoices/').status_code, 403)
        self.assertEqual(self._client('viewer').get('/api/invoices/invoices/').status_code, 200)

    def test_decisions_need_approve(self):
        v = self._client('viewer')
        for action in ('confirm/', 'confirm-green/', 'reject/', 'create-return/'):
            self.assertEqual(v.post(self.url + action, {}, format='json').status_code, 403, action)
        self.assertNotEqual(self._client('purchasing').post(self.url + 'reject/', {}, format='json').status_code, 403)

    def test_edits_and_ocr_need_edit(self):
        v = self._client('viewer')
        self.assertEqual(v.post(self.url + 'run-ocr/', {}, format='json').status_code, 403)
        self.assertEqual(v.post(self.url + 'add-line/', {}, format='json').status_code, 403)
        self.assertEqual(v.patch(self.url + 'update-header/', {}, format='json').status_code, 403)

    def test_delete_and_push(self):
        v = self._client('viewer')
        self.assertEqual(v.delete(self.url).status_code, 403)
        self.assertEqual(v.post(self.url + 'push/', {}, format='json').status_code, 403)
        self.assertTrue(SupplierInvoice.objects.filter(pk=self.inv.pk).exists())

    def test_vendor_lookup_stays_open(self):
        # the shortage page reads the main vendors for every shortage user
        self.assertEqual(self._client('salesperson').get('/api/invoices/vendors/main/').status_code, 200)
        self.assertEqual(self._client('salesperson').post('/api/invoices/vendors/', {}, format='json').status_code, 403)


class SettingsPermissionTests(_Base):
    def setUp(self):
        super().setUp()
        self.setting = SystemSetting.objects.create(key='gp_flag', label='x', value='false')

    def test_reads_open_writes_need_edit(self):
        c = self._client('pharmacist')
        self.assertEqual(c.get('/api/config/settings/').status_code, 200)
        self.assertEqual(c.post('/api/config/settings/by_key/', {'keys': ['gp_flag']}, format='json').status_code, 200)
        self.assertEqual(c.patch(f'/api/config/settings/{self.setting.pk}/', {'value': 'true'}, format='json').status_code, 403)
        self.assertEqual(c.post('/api/config/settings/bulk_update/', {'gp_flag': 'true'}, format='json').status_code, 403)
        self.setting.refresh_from_db()
        self.assertEqual(self.setting.value, 'false')

    def test_dropdowns_and_pharmacy(self):
        c = self._client('viewer')
        self.assertEqual(c.get('/api/config/dropdowns/').status_code, 200)
        self.assertEqual(c.post('/api/config/dropdowns/', {}, format='json').status_code, 403)
        self.assertEqual(c.get('/api/config/pharmacy/').status_code, 200)
        self.assertEqual(c.patch('/api/config/pharmacy/', {'whatsapp_number': '0'}, format='json').status_code, 403)

    def test_admin_can_edit(self):
        r = self._client('admin').patch(f'/api/config/settings/{self.setting.pk}/', {'value': 'true'}, format='json')
        self.assertNotEqual(r.status_code, 403)


class SpikePermissionTests(_Base):
    def test_confirm_needs_purchasing_edit(self):
        it = make_item()
        Item.objects.filter(pk=it.pk).update(spike_tier='strong')
        for role in ('pharmacist', 'supervisor', 'quality_manager'):
            r = self._client(role).post('/api/purchasing/spike/confirm/', {'item_id': it.pk}, format='json')
            self.assertEqual(r.status_code, 403, role)
        it.refresh_from_db()
        self.assertFalse(it.spike_confirmed)
        r = self._client('purchasing').post('/api/purchasing/spike/confirm/', {'item_id': it.pk}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        r = self._client('pharmacist').post('/api/purchasing/spike/unconfirm/', {'item_id': it.pk}, format='json')
        self.assertEqual(r.status_code, 403)


class DemandFinalActionTests(_Base):
    def setUp(self):
        super().setUp()
        self.d = DemandRecord.objects.create(phone='0100', customer_name='عميل', branch=self.branch)

    def test_fulfill_needs_finalize(self):
        r = self._client('supervisor').post(f'/api/demand/{self.d.pk}/fulfill/', {}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_cancel_needs_delete(self):
        r = self._client('supervisor').post(f'/api/demand/{self.d.pk}/cancel/', {}, format='json')
        self.assertEqual(r.status_code, 403)
        self.d.refresh_from_db()
        self.assertNotEqual(self.d.status, 'cancelled')

    def test_lost_needs_edit(self):
        self.assertEqual(self._client('viewer').post(f'/api/demand/{self.d.pk}/lost/', {}, format='json').status_code, 403)
        r = self._client('pharmacist').post(f'/api/demand/{self.d.pk}/lost/', {}, format='json')
        self.assertNotEqual(r.status_code, 403)

    def test_admin_passes(self):
        r = self._client('admin').post(f'/api/demand/{self.d.pk}/cancel/', {}, format='json')
        self.assertNotEqual(r.status_code, 403)
