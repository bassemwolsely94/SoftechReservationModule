"""N3 / Task 3 - zone policy table seeded from the owner's external profile."""
from types import SimpleNamespace

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from apps.access.models import ZonePolicy
from apps.access.policy import Decision, decide, is_export, policy_for, softech_write_allowed
from apps.users.models import StaffProfile

ROLES = ['admin', 'supervisor', 'purchasing', 'quality_manager', 'call_center', 'delivery',
         'pharmacist', 'salesperson', 'viewer']
CC_MODULES = ['callcenter', 'demand', 'reservations', 'customers']


def _expected(role, zone):
    """The owner table 7.3, written out independently of the seed."""
    if zone == 'Z1':
        return dict(access='full', export=True, softech_read=True, softech_write=True)
    if zone == 'Z2':
        return dict(access='read_only', export=False, softech_read=True, softech_write=False)
    if role == 'delivery':
        return dict(access='rider', export=False, softech_read=False, softech_write=False)
    if zone == 'Z4':
        return dict(access='none', export=False, softech_read=False, softech_write=False)
    if role == 'admin':
        return dict(access='full', export=False, softech_read=True, softech_write=False)
    if role in ('supervisor', 'purchasing', 'quality_manager'):
        return dict(access='read_only', export=False, softech_read=True, softech_write=False)
    if role == 'call_center':
        return dict(access='listed', export=False, softech_read=True, softech_write=False)
    return dict(access='none', export=False, softech_read=False, softech_write=False)


def _profile(role, export=False, softech=False):
    return SimpleNamespace(role=role, external_export=export, external_softech_write=softech)


class SeedTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_seed_matches_owner_table(self):
        self.assertEqual(ZonePolicy.objects.count(), len(ROLES) * 4)
        for role in ROLES:
            for zone in ('Z1', 'Z2', 'Z3', 'Z4'):
                row = ZonePolicy.objects.get(role=role, zone=zone)
                for k, v in _expected(role, zone).items():
                    self.assertEqual(getattr(row, k), v, f'{role} {zone} {k}')
                if zone in ('Z1', 'Z2'):
                    self.assertFalse(row.require_mfa, f'{role} {zone}')
                    self.assertIsNone(row.max_session_hours)
                else:
                    self.assertTrue(row.require_mfa, f'{role} {zone}')
                    cap = 12 if role == 'delivery' else 8
                    self.assertEqual(row.max_session_hours, cap, f'{role} {zone}')
                self.assertFalse(row.view_only, f'{role} {zone}')
        cc = ZonePolicy.objects.get(role='call_center', zone='Z3')
        self.assertEqual(sorted(cc.modules), sorted(CC_MODULES))

    def test_call_center_modules_are_real_module_keys(self):
        from core.middleware.module_access import MODULE_BY_PREFIX
        for prefix in ('callcenter', 'demand', 'reservations', 'customers'):
            self.assertIn(MODULE_BY_PREFIX[prefix], CC_MODULES)

    def test_staff_flags_default_off(self):
        f = StaffProfile._meta.get_field
        self.assertFalse(f('external_export').default)
        self.assertFalse(f('external_softech_write').default)


class DecideTests(TestCase):
    def setUp(self):
        cache.clear()

    def d(self, role, zone, path='/api/pos-orders/', method='GET', module='pos', export=False):
        return decide(_profile(role), zone, path, method, module, export)

    def test_listed_module_none_writes_refused(self):
        r = self.d('call_center', 'Z3', '/api/tasks/5/', 'POST', None)
        self.assertEqual((r.allowed, r.reason), (False, 'module'))
        self.assertTrue(self.d('call_center', 'Z3', '/api/items/', 'GET', None).allowed)

    def test_softech_write_zone_none_is_z4(self):
        self.assertFalse(softech_write_allowed(_profile('admin', softech=True), None))
        self.assertTrue(softech_write_allowed(_profile('admin', softech=True), 'Z3'))
        self.assertFalse(softech_write_allowed(_profile('admin'), 'Z3'))

    def test_decide_matrix(self):
        self.assertEqual(self.d('pharmacist', 'Z3'), Decision(False, 'blocked', 'Z3'))
        self.assertEqual(self.d('purchasing', 'Z3', method='POST', module='purchasing').reason, 'read_only')
        self.assertTrue(self.d('purchasing', 'Z3', module='purchasing').allowed)
        self.assertTrue(self.d('call_center', 'Z3', '/api/customers/', 'POST', 'customers').allowed)
        r = self.d('call_center', 'Z3', '/api/pos-orders/', 'GET', 'pos')
        self.assertEqual((r.allowed, r.reason), (False, 'module'))
        r = self.d('admin', 'Z3', '/api/purchasing/export/', 'GET', 'purchasing', True)
        self.assertEqual((r.allowed, r.reason), (False, 'export'))
        self.assertTrue(decide(_profile('admin', export=True), 'Z3', '/api/purchasing/export/', 'GET',
                               'purchasing', True).allowed)
        self.assertTrue(self.d('admin', 'Z3', method='POST').allowed)
        self.assertTrue(self.d('delivery', 'Z4', '/api/delivery/app/my-orders/', module='delivery').allowed)
        r = self.d('delivery', 'Z4', '/api/delivery/summary/', module='delivery')
        self.assertEqual((r.allowed, r.reason), (False, 'module'))
        self.assertEqual(self.d('delivery', 'Z3', '/api/pos-orders/').reason, 'module')
        for role in ROLES:
            r = self.d(role, 'Z2', method='POST')
            self.assertEqual((r.allowed, r.reason), (False, 'read_only'), role)
            self.assertTrue(self.d(role, 'Z2').allowed, role)
            self.assertTrue(self.d(role, 'Z1', method='POST', export=True).allowed, role)
        self.assertEqual(self.d('admin', 'Z4').reason, 'blocked')

    def test_export_blocked_in_z2(self):
        r = self.d('admin', 'Z2', export=True)
        self.assertEqual((r.allowed, r.reason), (False, 'export'))

    def test_admin_flag_only_widens_in_z3(self):
        self.assertTrue(decide(_profile('admin', export=True), 'Z3', '/x', 'GET', 'pos', True).allowed)
        self.assertFalse(decide(_profile('admin', export=True), 'Z2', '/x', 'GET', 'pos', True).allowed)
        self.assertFalse(decide(_profile('admin', export=True), 'Z4', '/x', 'GET', 'pos', True).allowed)
        self.assertFalse(decide(_profile('purchasing', export=True), 'Z3', '/x', 'GET', 'pos', True).allowed)

    def test_rider_paths(self):
        for p, m in [('/api/delivery/app/my-route/', 'GET'), ('/api/delivery/12/', 'GET'),
                     ('/api/delivery/12/accept/', 'POST'), ('/api/delivery/12/collect-cash/', 'POST'),
                     ('/api/delivery/12/items/', 'GET')]:
            self.assertTrue(self.d('delivery', 'Z4', p, m, 'delivery').allowed, p)
        for p, m in [('/api/delivery/12/', 'PATCH'), ('/api/delivery/12/assign/', 'POST'),
                     ('/api/delivery/', 'GET'), ('/api/delivery/12/cancel/', 'POST')]:
            self.assertFalse(self.d('delivery', 'Z4', p, m, 'delivery').allowed, p)

    def test_always_open_allowed_everywhere(self):
        for p in ['/api/auth/me/', '/api/auth/refresh/', '/api/users/my-permissions/',
                  '/api/notifications/', '/api/help/x/', '/api/access/whoami/', '/api/audit/screen-view/']:
            for role in ROLES:
                for z in ('Z2', 'Z3', 'Z4'):
                    self.assertTrue(self.d(role, z, p, 'POST', 'pos').allowed, (p, role, z))

    def test_zone_none(self):
        self.assertTrue(decide(None, None, '/api/pos-orders/', 'GET', 'pos', False).allowed)
        r = decide(_profile('admin'), None, '/api/pos-orders/', 'GET', 'pos', False)
        self.assertEqual((r.allowed, r.reason), (False, 'blocked'))   # context failure -> Z4

    def test_no_policy_row_allowed(self):
        self.assertTrue(decide(_profile('newrole'), 'Z4', '/api/pos-orders/', 'GET', 'pos', False).allowed)

    def test_listed_view_only_refuses_writes(self):
        ZonePolicy.objects.filter(role='call_center', zone='Z3').update(view_only=True)
        cache.clear()
        r = self.d('call_center', 'Z3', '/api/customers/', 'POST', 'customers')
        self.assertEqual(r.reason, 'read_only')


class CacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_policy_for_cached_and_invalidated(self):
        self.assertEqual(policy_for('viewer', 'Z1').access, 'full')
        ZonePolicy.objects.filter(role='viewer', zone='Z1').update(access='none')
        self.assertEqual(policy_for('viewer', 'Z1').access, 'full')      # still cached
        row = ZonePolicy.objects.get(role='viewer', zone='Z1')
        row.save()                                                        # post_save invalidates
        self.assertEqual(policy_for('viewer', 'Z1').access, 'none')
        row.delete()
        self.assertIsNone(policy_for('viewer', 'Z1'))


# Every route containing "export" in an apps/*/urls.py or a DRF @action url_path (grep inventory).
EXPORT_ROUTES = [
    '/api/batches/purchase-expiry/export/', '/api/batches/stock-expiry/export/',
    '/api/batches/stock-expiry/disposal/export/', '/api/batches/return-window/export/',
    '/api/finance/receivables/export/', '/api/finance/cash-view/export/',
    '/api/finance/supplier-terms/export/', '/api/finance/reconciliation/partial/export/',
    '/api/finance/reconciliation/unpaid/export/', '/api/finance/reconciliation/review/export/',
    '/api/finance/reconciliation/returns-chains/export/',
    '/api/forecasting/kpi-board/export/', '/api/forecasting/scenarios/3/export/',
    '/api/gamification/reports/export/', '/api/products/export/',
    '/api/purchasing/export/', '/api/purchasing/advanced-export/',
    '/api/purchasing/advanced-pivot-export/', '/api/purchasing/shortage/export/',
    '/api/purchasing/rates/pushes/4/export/', '/api/purchasing/isr/transfer-preview/export/',
    '/api/purchasing/isr/fulfilment/export/',
    '/api/purchasing/isr/branch-requests/5/analysis/export/',
    '/api/stock-audit/findings/export/', '/api/vouchers/coupons/batches/6/export/',
    '/api/commerce/documents/7/export/', '/api/incentives/settlements/8/export-settlements/',
    '/api/insurance/claims/9/softech-reprice/runs/export/', '/api/insurance/claims/9/export/excel/',
    '/api/insurance/claims/9/export/statistical/', '/api/insurance/claims/9/discrepancy-export/',
    '/api/insurance/claims/pivot-export/', '/api/insurance/batches/9/export/',
    '/api/invoices/10/export-excel/', '/api/invoices/10/export-csv/',
    '/api/transits/11/export-picking/', '/api/transits/export-picking/',
    '/api/transits/export-stocking/',
    '/api/supply/availability/12/export/', '/api/supply/cases/export/',
    '/api/shortage/lists/13/export-excel/', '/api/shortage/lists/13/export-supplier-matrix/',
    '/api/shortage/lists/13/export-supplier-po/S1/', '/api/shortage/lists/export-aggregated/',
]
NON_EXPORT = ['/api/pos-orders/', '/api/customers/12/', '/api/purchasing/runs/latest/',
              '/api/products/exporter-list/', '/api/delivery/app/my-orders/',
              '/api/reservations/', '/api/auth/me/']


class ExportDetectionTests(SimpleTestCase):
    def test_export_routes_detected(self):
        for p in EXPORT_ROUTES:
            self.assertTrue(is_export(p, 'GET'), p)
            self.assertTrue(is_export(p, 'POST'), p)

    def test_format_query_detected(self):
        for p in ['/api/purchasing/isr/distribution-preview/', '/api/supply/supplier-code-report/',
                  '/api/supply/purchase-prices/', '/api/supply/supplier-comparison/']:
            for fmt in ('xlsx', 'XLSX', 'csv', 'xls', 'excel'):
                self.assertTrue(is_export(p, 'GET', query={'format': fmt}), (p, fmt))
            self.assertFalse(is_export(p, 'GET', query={'format': 'json'}), p)
            self.assertFalse(is_export(p, 'GET', query={}), p)

    def test_reservations_bulk_body_export(self):
        p = '/api/reservations/bulk/'
        self.assertTrue(is_export(p, 'POST', body={'action': 'export', 'ids': [1]}))
        self.assertFalse(is_export(p, 'POST', body={'action': 'assign'}))
        self.assertFalse(is_export(p, 'POST', body=None))
        self.assertFalse(is_export('/api/customers/', 'POST', body={'action': 'export'}))

    def test_non_export_paths(self):
        for p in NON_EXPORT:
            self.assertFalse(is_export(p, 'GET'), p)
