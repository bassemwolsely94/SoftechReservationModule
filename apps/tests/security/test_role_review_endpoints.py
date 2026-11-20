"""
Role review 2026-11-20 (task 2): endpoints only one tool screen calls ask that screen's own
matrix module (spec docs/superpowers/specs/2026-11-20-role-review-design.md, decision 7).

Moved: images/* + vision/* → catalog_tools; analytics/inventory* → stock; referral/* → loyalty;
delivery/app/* → rider; finance/reconciliation/* → reconciliation; access/{networks,devices,
zone-policies} → access_control; config/code-maps/* → code_maps; forecasting/{runs,seasonality,
accuracy,salesperson-board} → forecast. Shared prefixes stay on the parent.

Each moved path is checked both ways with the parent / new module rows flipped off, so the test
proves which module decides, whatever the seeded grants are.
"""
from django.test import SimpleTestCase, TestCase, override_settings

from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access
from core.middleware.module_access import required

from .fixtures import bearer_client, seed_code_matrix

# (path, new module, parent module)
MOVED_GETS = (
    ('/api/images/jobs/', 'catalog_tools', 'catalog'),
    ('/api/images/report/', 'catalog_tools', 'catalog'),
    ('/api/vision/corpus-stats/', 'catalog_tools', 'catalog'),
    ('/api/vision/corpus-accuracy/', 'catalog_tools', 'catalog'),
    ('/api/analytics/inventory/', 'stock', 'analytics'),
    ('/api/analytics/inventory-investment/', 'stock', 'analytics'),
    ('/api/referral/leads/', 'loyalty', 'customers'),
    ('/api/referral/my-code/', 'loyalty', 'customers'),
    ('/api/delivery/app/my-orders/', 'rider', 'delivery'),
    ('/api/delivery/app/my-route/', 'rider', 'delivery'),
    ('/api/finance/reconciliation/dashboard/', 'reconciliation', 'finance'),
    ('/api/finance/reconciliation/parties/', 'reconciliation', 'finance'),
    ('/api/access/networks/', 'access_control', 'settings'),
    ('/api/access/devices/', 'access_control', 'settings'),
    ('/api/access/zone-policies/', 'access_control', 'settings'),
    ('/api/config/code-maps/channels/', 'code_maps', 'settings'),
    ('/api/config/code-maps/item-types/', 'code_maps', 'settings'),
    ('/api/forecasting/runs/', 'forecast', 'analytics'),
    ('/api/forecasting/seasonality/', 'forecast', 'analytics'),
    ('/api/forecasting/accuracy/', 'forecast', 'analytics'),
    ('/api/forecasting/salesperson-board/', 'forecast', 'analytics'),
)

# Shared prefixes keep their parent module (brief: "stay on the parent")
STAY = (
    ('/api/forecasting/scenarios/', 'analytics'),
    ('/api/forecasting/kpi-board/', 'analytics'),
    ('/api/forecasting/plan/', 'analytics'),
    ('/api/analytics/filter-options/', 'analytics'),
    ('/api/analytics/sales/', 'analytics'),
    ('/api/delivery/', 'delivery'),
    ('/api/delivery/routes/', 'delivery'),
    ('/api/loyalty/redemptions/', 'customers'),
    ('/api/finance/dashboard/', 'finance'),
    ('/api/incentives/targets/', 'analytics'),
    ('/api/batches/stock-expiry/', 'catalog'),
    ('/api/enrichment/jobs/', 'catalog'),
)


class RequiredMappingTests(SimpleTestCase):
    """module_access.required() — the question the middleware and RouteModulePermission ask."""

    def test_moved_reads_ask_the_new_module(self):
        for path, new, _parent in MOVED_GETS:
            with self.subTest(path=path):
                self.assertEqual(required(path, 'GET'), (new, ('view',)))

    def test_shared_prefixes_stay_on_the_parent(self):
        for path, parent in STAY:
            with self.subTest(path=path):
                self.assertEqual(required(path, 'GET')[0], parent)

    def test_moved_writes_ask_the_new_module(self):
        cases = (
            ('/api/images/jobs/', 'POST', 'catalog_tools'),
            ('/api/images/products/5/reorder/', 'PATCH', 'catalog_tools'),
            ('/api/images/products/5/images/7/', 'DELETE', 'catalog_tools'),    # line removal = edit
            ('/api/referral/leads/5/validate/', 'POST', 'loyalty'),
            ('/api/delivery/app/orders/5/location/', 'POST', 'rider'),
            ('/api/finance/reconciliation/candidates/5/approve/', 'POST', 'reconciliation'),
            ('/api/access/networks/', 'POST', 'access_control'),
            ('/api/access/devices/5/', 'PATCH', 'access_control'),
            ('/api/access/zone-policies/5/', 'PATCH', 'access_control'),
            ('/api/config/code-maps/channels/5/', 'PATCH', 'code_maps'),
            ('/api/forecasting/seasonality/', 'POST', 'forecast'),
            ('/api/forecasting/accuracy/5/', 'DELETE', 'forecast'),
        )
        for path, method, module in cases:
            with self.subTest(path=path, method=method):
                self.assertEqual(required(path, method)[0], module)

    def test_line_removal_and_write_actions_keep_their_shape(self):
        self.assertEqual(required('/api/images/products/5/images/7/', 'DELETE'), ('catalog_tools', ('edit',)))
        self.assertEqual(required('/api/config/code-maps/channels/5/', 'PATCH'), ('code_maps', ('edit',)))
        self.assertEqual(required('/api/forecasting/accuracy/5/', 'DELETE'), ('forecast', ('delete',)))
        self.assertEqual(required('/api/forecasting/scenarios/5/', 'PATCH'), ('analytics', ('edit',)))

    def test_rider_complete_stays_on_delivery(self):
        # ruling: delivery/{id}/complete shares the prefix with dispatch, so only delivery/app/* moves
        self.assertEqual(required('/api/delivery/5/complete/', 'POST')[0], 'delivery')

    def test_whoami_stays_open(self):
        self.assertIsNone(required('/api/access/whoami/', 'GET'))

    def test_other_config_reads_stay_open(self):
        self.assertIsNone(required('/api/config/', 'GET'))


class _Base(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.branch = make_branch()

    def tearDown(self):
        module_access.clear_cache()

    def _deny(self, role, module):
        RoleModuleAccess.objects.filter(role=role, module=module).update(is_allowed=False)
        module_access.clear_cache()

    def _grant(self, role, module, action='view'):
        RoleModuleAccess.objects.filter(role=role, module=module, action=action).update(is_allowed=True)
        module_access.clear_cache()

    def _client(self, role, name=None):
        user, profile, _ = make_user(name or f'rr2_{role}', role=role, branch=self.branch, access_all=True)
        if role in ('call_center', 'delivery', 'supervisor'):
            from apps.delivery.models import DeliveryDriver
            DeliveryDriver.objects.get_or_create(staff_profile=profile,
                                                 defaults={'full_name': 'rr2', 'mobile': '0100000077'})
        return bearer_client(user)


# a role holding the new module (view) for each moved read, and a role holding the parent's view
# but not the new module's — the second is refused by the new module, the first passes without
# the parent
NEW_ROLE = {'catalog_tools': 'supervisor', 'stock': 'salesperson', 'loyalty': 'salesperson',
            'rider': 'call_center', 'reconciliation': 'supervisor', 'code_maps': 'purchasing',
            'forecast': 'supervisor'}
PARENT_ONLY_ROLE = {'catalog_tools': 'pharmacist', 'stock': 'viewer', 'loyalty': 'viewer',
                    'rider': 'pharmacist', 'reconciliation': 'pharmacist', 'code_maps': 'pharmacist',
                    'forecast': 'pharmacist', 'access_control': 'pharmacist'}


@override_settings(RBAC_ENFORCEMENT='enforce')
class MiddlewareEnforceTests(_Base):

    def test_new_module_without_parent_passes(self):
        for path, new, parent in MOVED_GETS:
            if new == 'access_control':
                continue                                   # admin only: below
            role = NEW_ROLE[new]
            with self.subTest(path=path, role=role):
                seed_code_matrix()
                self._deny(role, parent)
                r = self._client(role).get(path)
                self.assertNotEqual(r.status_code, 403, getattr(r, 'data', r.content))

    def test_parent_without_new_module_is_refused(self):
        for path, new, parent in MOVED_GETS:
            role = PARENT_ONLY_ROLE[new]
            with self.subTest(path=path, role=role):
                seed_code_matrix()
                self._grant(role, parent)
                self._deny(role, new)
                r = self._client(role).get(path)
                self.assertEqual(r.status_code, 403)
                self.assertEqual(r.json().get('module'), new)

    def test_access_refuses_supervisor_admits_admin(self):
        sup, adm = self._client('supervisor'), self._client('admin')
        for path in ('/api/access/networks/', '/api/access/devices/', '/api/access/zone-policies/'):
            with self.subTest(path=path):
                self.assertEqual(sup.get(path).status_code, 403)
                self.assertEqual(adm.get(path).status_code, 200)

    def test_whoami_stays_open(self):
        self.assertEqual(self._client('salesperson').get('/api/access/whoami/').status_code, 200)

    def test_shared_forecasting_stays_on_analytics(self):
        # pharmacist: analytics view, no forecast — the scenarios list (shared) still answers
        self.assertEqual(self._client('pharmacist').get('/api/forecasting/scenarios/').status_code, 200)


@override_settings(RBAC_ENFORCEMENT='log')
class ViewGateTests(_Base):
    """Log mode: the middleware only logs, so the views must ask the new module themselves."""

    def test_parent_without_new_module_is_refused_by_the_view(self):
        for path, new, parent in MOVED_GETS:
            role = PARENT_ONLY_ROLE[new]
            with self.subTest(path=path, role=role):
                seed_code_matrix()
                self._grant(role, parent)
                self._deny(role, new)
                self.assertEqual(self._client(role).get(path).status_code, 403)

    def test_new_module_without_parent_passes_the_view(self):
        for path, new, parent in MOVED_GETS:
            if new == 'access_control':
                continue
            role = NEW_ROLE[new]
            with self.subTest(path=path, role=role):
                seed_code_matrix()
                self._deny(role, parent)
                r = self._client(role).get(path)
                self.assertNotEqual(r.status_code, 403, getattr(r, 'data', r.content))

    def test_access_follows_the_matrix_not_a_role_list(self):
        c = self._client('supervisor')
        self.assertEqual(c.get('/api/access/networks/').status_code, 403)
        self._grant('supervisor', 'access_control')
        self.assertEqual(c.get('/api/access/networks/').status_code, 200)
        # view alone does not let it write
        r = c.post('/api/access/networks/', {'name': 'x', 'cidr': '10.9.0.0/24', 'kind': 'branch'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_vision_has_no_inline_role_list(self):
        # call center holds catalog_tools (owner 2026-11-20) — the old admin / supervisor /
        # purchasing / pharmacist list refused it
        self.assertEqual(self._client('call_center').get('/api/vision/corpus-stats/').status_code, 200)

    def test_code_maps_edit_needs_code_maps_edit(self):
        r = self._client('purchasing').patch('/api/config/code-maps/channels/987654321/', {}, format='json')
        self.assertEqual(r.status_code, 403)            # code_maps view only

    def test_forecast_writes_keep_the_analyst_rule(self):
        # quality manager holds forecast view + export but is not an analyst: writes stay refused
        r = self._client('quality_manager').post('/api/forecasting/seasonality/', {}, format='json')
        self.assertEqual(r.status_code, 403)
        # and the salesperson board stays with the analysts
        self.assertEqual(self._client('quality_manager').get('/api/forecasting/salesperson-board/').status_code, 403)

    def test_driver_app_still_needs_a_driver_record(self):
        # supervisor holds rider; a profile with no driver record is still refused by the view
        user, _, _ = make_user('rr2_nodriver', role='supervisor', branch=self.branch)
        r = bearer_client(user).get('/api/delivery/app/my-orders/')
        self.assertEqual(r.status_code, 403)
        self.assertIn('سائق', str(r.data))
