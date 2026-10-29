"""
Authorization — RBAC middleware gaps before production goes to `enforce` (Batch 4, Z-1;
owner decision 2026-10-27: enforce after Z-1, at the VPS cutover).

Before: with RBAC_ENFORCEMENT=enforce, a role without `users` / `sync` view got 403 on the reads
every screen makes — its own permission map (the menu) and the data-freshness bar; and three
/api/ prefixes (tasks, recommendations, stock-audit) were never classified, so the middleware
never checked them at all.
"""
from django.test import TestCase, override_settings

from apps.tests.factories import make_user
from core.middleware import module_access

from .fixtures import NON_ADMIN_ROLES, bearer_client, granted, seed_code_matrix


def _blocked_by_matrix(response):
    """The middleware's own refusal (403 naming a module), not a view's answer."""
    return response.status_code == 403 and 'module' in (response.json() if response.content else {})


@override_settings(RBAC_ENFORCEMENT='enforce')
class SharedReadsUnderEnforceTests(TestCase):

    def setUp(self):
        seed_code_matrix()
        self.clients = {}
        for role in NON_ADMIN_ROLES:
            user, _, _ = make_user(f'z1_{role}', role=role)
            self.clients[role] = bearer_client(user)

    def tearDown(self):
        module_access.clear_cache()

    def _roles_without(self, module):
        roles = [r for r in NON_ADMIN_ROLES if not granted(r, module, ('view',))]
        self.assertTrue(roles, f'every role has {module} view — test needs a role without it')
        return roles

    def test_own_permission_map_is_reachable(self):
        for role in self._roles_without('users'):
            r = self.clients[role].get('/api/users/my-permissions/')
            self.assertFalse(_blocked_by_matrix(r), f'{role}: menu permissions blocked')

    def test_freshness_bar_is_reachable(self):
        for role in self._roles_without('sync'):
            for path in ('/api/sync/freshness/', '/api/sync/status/'):
                r = self.clients[role].get(path)
                self.assertFalse(_blocked_by_matrix(r), f'{role}: {path} blocked')

    def test_sync_trigger_still_checked(self):
        role = self._roles_without('sync')[0]
        self.assertTrue(_blocked_by_matrix(self.clients[role].post('/api/sync/trigger/', {}, format='json')))


class PrefixClassificationTests(TestCase):

    def test_every_api_prefix_is_classified(self):
        known = (set(module_access.MODULE_BY_PREFIX) | set(module_access.READ_OPEN_PREFIXES)
                 | set(module_access.EXEMPT_PREFIXES))
        self.assertEqual({'tasks', 'recommendations', 'stock-audit'} - known, set())

    def test_recommendation_engine_trigger_needs_analytics(self):
        need = module_access.required('/api/recommendations/trigger/', 'POST')
        self.assertIsNotNone(need, 'engine trigger never checked by the middleware')
        self.assertEqual(need[0], 'analytics')

    def test_recommendation_reads_stay_open(self):
        # POS (frequently-bought-together, basket) and customer screens read these for every role.
        self.assertIsNone(module_access.required('/api/recommendations/fbt/for-item/', 'GET'))
