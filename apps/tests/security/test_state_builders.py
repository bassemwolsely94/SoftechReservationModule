"""
apps/tests/security/test_state_builders.py

Wave 4 (doc 13): the state-aware sweep builder (state_builders.py) and the role_unproven ratchet.

  * every rendered /api/ route resolves — a path that resolves nowhere answers 404 to every role,
    which the role sweep can only call 'unproven' (two replacement routes did, before the regex
    groups were rendered with values they accept);
  * every builder targets a real protected route and gives admin (the positive control) a record
    it reaches with every method the route handles — so the role sweep's verdicts there are real;
  * baselines/role_unproven.txt may only shrink: UNPROVEN_CEILING is its size today. Lowering it is
    the reward for a new builder; raising it needs the owner (a route nobody can prove is a gap).

Small on purpose (one admin client, six routes): the full role × route sweep is test_role_sweep.py.
"""
import logging

from django.test import TestCase, override_settings
from django.urls import Resolver404, resolve

from apps.tests.factories import make_branch
from apps.users.models import StaffProfile

from .baseline import load_baseline
from .canary import Planter
from .fixtures import role_clients, seed_code_matrix
from .routes import Tripwire, api_routes, handles
from .state_builders import BUILDERS
from .sweep import FEATURE_FLAGS_ON, METHODS, SWEEP_ID, _call, protected_routes
from core.middleware import module_access
from core.middleware.module_access import required

# The ratchet. Wave 4 (2026-11-20) took the list from 84 lines to 0; it may only go down.
UNPROVEN_CEILING = 0


class RouteRenderingTests(TestCase):

    def test_every_rendered_route_resolves(self):
        for id_value in (SWEEP_ID, '1'):
            unresolved = []
            for path, _ in api_routes(id_value=id_value):
                try:
                    resolve(path)
                except Resolver404:
                    unresolved.append(path)
            self.assertEqual(unresolved, [], f'routes rendered with {id_value} that resolve nowhere')


class UnprovenRatchetTests(TestCase):

    def test_role_unproven_only_shrinks(self):
        n = len(load_baseline('role_unproven'))
        self.assertLessEqual(
            n, UNPROVEN_CEILING,
            f'baselines/role_unproven.txt has {n} lines, the ceiling is {UNPROVEN_CEILING}. A detail route the '
            f'sweep cannot reach needs a builder in state_builders.py, not a baseline line.')

    def test_builders_target_protected_routes(self):
        routes = set(protected_routes())
        self.assertEqual(sorted(set(BUILDERS) - routes), [])


class StateBuilderTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        cls.branch = make_branch()
        cls.clients = role_clients(cls.branch)
        admin = StaffProfile.objects.select_related('user').get(user__username='sec_admin')
        cls.planter = Planter(cls.branch, admin.user, admin)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        module_access.clear_cache()

    def test_each_builder_gives_admin_a_reachable_record(self):
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        problems = []
        try:
            with override_settings(**FEATURE_FLAGS_ON), Tripwire() as tw:
                for path, fn in BUILDERS.items():
                    real = fn(self.planter)
                    if not real or real == path:
                        problems.append(f'{path}: builder made nothing')
                        continue
                    for m in METHODS:
                        if required(path, m) is None or not handles(path, m):
                            continue
                        code = _call(self.clients['admin'], m, real)
                        if code == 404 or code == 500 or isinstance(code, str):
                            problems.append(f'admin {m} {real} → {code}')
                self.assertEqual(tw.softech_calls, [], 'a builder route reached SOFTECH')
        finally:
            logging.disable(previous)
            from django.core.cache import cache
            cache.clear()
        self.assertEqual(problems, [])
