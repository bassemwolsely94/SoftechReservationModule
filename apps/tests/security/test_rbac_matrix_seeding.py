"""
Authorization — the matrix's "not seeded yet" safety net works per module, and the grants
cache never outlives a test (Batch 4, Z-5c).

Before: matrix_allows treated the WHOLE matrix as seeded as soon as any RoleModuleAccess row
existed. The `stock_audit` and `offers` data migrations add a few rows, so a fresh install (or a
fresh test database) refused every non-admin role on every module until seed_permissions ran.
And the 60-second grants cache carried one test's matrix into the next, so suites passed alone
and failed together.
"""
from django.test import TestCase

from apps.tests.factories import make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access
from core.permissions import matrix_allows



class PerModuleSeedingTests(TestCase):

    def setUp(self):
        RoleModuleAccess.objects.all().delete()
        module_access.clear_cache()
        self.pharmacist = make_user('z5c_ph', role='pharmacist')[1]

    def tearDown(self):
        module_access.clear_cache()

    def test_a_module_nobody_has_rows_for_is_not_enforced(self):
        # only another module's migration rows exist — analytics was never seeded
        RoleModuleAccess.objects.create(role='supervisor', module='stock_audit', action='view', is_allowed=True)
        module_access.clear_cache()
        self.assertTrue(matrix_allows(self.pharmacist, 'analytics', 'view'))

    def test_a_seeded_module_is_enforced(self):
        RoleModuleAccess.objects.create(role='supervisor', module='analytics', action='view', is_allowed=True)
        module_access.clear_cache()
        self.assertFalse(matrix_allows(self.pharmacist, 'analytics', 'view'))

    def test_an_explicit_denial_counts_as_seeded(self):
        RoleModuleAccess.objects.create(role='pharmacist', module='analytics', action='view', is_allowed=False)
        module_access.clear_cache()
        self.assertFalse(matrix_allows(self.pharmacist, 'analytics', 'view'))


class GrantsCacheTests(TestCase):

    def test_cache_does_not_outlive_a_change_under_tests(self):
        RoleModuleAccess.objects.all().delete()
        module_access.clear_cache()
        module_access._grants()                       # cache: nothing seeded
        RoleModuleAccess.objects.create(role='supervisor', module='analytics', action='view', is_allowed=True)
        self.assertIn('analytics', module_access.seeded_modules(),
                      'grants cache served a stale matrix inside the test run')
