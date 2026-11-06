"""
apps/tests/security/test_role_sweep.py

Every non-admin role × every protected /api/ route × GET and POST {}, run twice:

  enforce — ModuleAccessMiddleware blocks per the role matrix. Proves the matrix
            + middleware close every mapped module.
  log     — the middleware only logs, so whatever answers is the VIEW's own
            check. The owner's rule: sensitive views must be safe on their own.

Expectations come from the code role matrix (seed_permissions.PERMISSIONS) via
module_access.required(path, method). Routes whose prefix is unmapped/exempt
have no expectation here; test_static_guards.test_every_api_prefix_is_classified
covers them. Verdicts: sweep.classify(). Engine: sweep.py.

Every request runs in a rolled-back savepoint inside the Tripwire (no SOFTECH,
network, subprocess or background thread ever runs). A request by a role the
matrix DENIES that still got as far as a SOFTECH connection attempt, or tried to
start a thread / HTTP call / socket / subprocess, is recorded separately —
permission was checked too late, or not at all.

Round 2, R3: detail routes are sent to a REAL record (sweep.seed_detail_paths plants one per
route through the canary Planter), so a denied role's 404 there is a real refusal, not an id
nobody created. Baseline lines keep the canonical 987654321 path.
"""
import logging

from django.test import TestCase

from core.middleware import module_access

from .baseline import assert_matches_baseline
from apps.tests.factories import make_branch
from apps.users.models import StaffProfile

from .canary import Planter
from .fixtures import role_clients, seed_code_matrix
from .routes import Tripwire
from .sweep import protected_routes, seed_detail_paths, sweep


def seeded_paths(clients, branch):
    """Plant one record per unreachable detail route (as admin, in the sweep users' branch)."""
    admin = StaffProfile.objects.select_related('user').get(user__username='sec_admin')
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with Tripwire():
            planter = Planter(branch, admin.user, admin)
            return seed_detail_paths(clients['admin'], planter, list(protected_routes()))
    finally:
        logging.disable(previous)


class RoleSweepTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        branch = make_branch()
        clients = role_clients(branch)
        cls.seeded = seeded_paths(clients, branch)
        cls.enforce = sweep('enforce', clients, seeded=cls.seeded)
        cls.log = sweep('log', clients, seeded=cls.seeded)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        module_access.clear_cache()      # the seeded matrix is rolled back with the class

    def test_sweep_is_not_empty(self):
        self.assertGreater(self.enforce.classified, 2000)

    def test_detail_routes_get_real_records(self):
        """R3: most detail routes admin could not reach now carry a planted record."""
        self.assertGreater(len(self.seeded), 50)

    def test_enforce_mode_leaks(self):
        assert_matches_baseline(self, 'role_leaks_enforce', self.enforce.leaks)

    def test_log_mode_leaks(self):
        assert_matches_baseline(self, 'role_leaks_log', self.log.leaks)

    def test_overblocks(self):
        assert_matches_baseline(self, 'role_overblocks', self.enforce.overblocks)

    def test_crashes(self):
        assert_matches_baseline(self, 'role_crashes', self.enforce.crashes | self.log.crashes)

    def test_unproven(self):
        """Denied role got 404 and so did admin: the check behind it was never reached."""
        assert_matches_baseline(self, 'role_unproven', self.log.unproven)

    def test_denied_roles_never_reach_softech(self):
        assert_matches_baseline(self, 'role_softech_reach',
                                self.enforce.softech_reach | self.log.softech_reach)

    def test_denied_roles_never_start_outside_work(self):
        assert_matches_baseline(self, 'role_outside_reach',
                                self.enforce.outside_reach | self.log.outside_reach)
