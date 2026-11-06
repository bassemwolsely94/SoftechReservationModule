"""
Batch 5 — the generic canary sweep over every list route.

One marked record (canary.MARKER in every free-text field) is planted in branch A for every model
linked to a branch. Then every protected GET route without an id in its path is called by:

  • a pharmacist of branch B who holds EVERY module action (so only branch scoping can stop them) —
    a response containing the marker is a cross-branch read;
  • an admin (positive control) — proves the canaries are actually serialized somewhere, so an
    empty result can't mean "nothing was planted".

Routes that show other branches on purpose (network stock, transfers between branches, rebalance
suggestions…) are listed with a reason in baselines/branch_canary_leaks.txt — the usual ratchet:
a NEW route fails the test, a STALE line must be removed.

Round 2, R4:
  • step 1 — models the planter cannot build are ratcheted in baselines/canary_skipped_models.txt,
    each with a reason (a NEW skipped model fails: give it a builder or a reason);
  • step 2 — DETAIL routes too: for each GET detail route whose planted record admin sees (marker at
    that path), branch B's user asks for the same path; a marker there is a cross-branch read
    (lines start "GET-DETAIL"). Baseline lines keep the canonical 987654321 path;
  • step 3 — the sweep runs with sweep.FEATURE_FLAGS_ON, so flag-gated screens are really checked.
"""
import logging

from django.db import transaction
from django.test import TestCase, override_settings

from apps.tests.factories import make_branch, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

from .baseline import assert_matches_baseline
from .canary import MARKER, Planter
from .fixtures import bearer_client, seed_code_matrix
from .routes import Tripwire, handles
from .sweep import FEATURE_FLAGS_ON, SWEEP_ID, planted_detail_paths, protected_routes


def _list_routes():
    return sorted(p for p in protected_routes() if SWEEP_ID not in p and handles(p, 'GET'))


def _body(resp):
    ctype = resp.get('Content-Type', '')
    if 'json' not in ctype and not ctype.startswith('text/'):
        return ''                      # xlsx / pdf / images: compressed, can't be grepped
    try:
        return resp.content.decode('utf-8', 'replace')
    except Exception:                  # noqa: BLE001 — streaming responses
        return ''


def _get(client, path):
    try:
        with transaction.atomic():
            r = client.get(path)
            transaction.set_rollback(True)
        return r.status_code, _body(r)
    except Exception as exc:           # noqa: BLE001 — crashes are the role sweep's business
        return f'raised {type(exc).__name__}', ''


@override_settings(RBAC_ENFORCEMENT='enforce', **FEATURE_FLAGS_ON)
class BranchCanarySweepTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_code_matrix()
        RoleModuleAccess.objects.filter(role='pharmacist').update(is_allowed=True)
        module_access.clear_cache()
        cls.branch_a = make_branch('Canary A', softech_id='CNA')
        cls.branch_b = make_branch('Canary B', softech_id='CNB')
        user_a, prof_a, _ = make_user('cnry_a', role='pharmacist', branch=cls.branch_a)
        user_b, _, _ = make_user('cnry_b', role='pharmacist', branch=cls.branch_b)
        admin, _, _ = make_user('cnry_admin', role='admin', branch=cls.branch_b, access_all=True)
        previous = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            with Tripwire():
                cls.planter = Planter(cls.branch_a, user_a, prof_a).plant_all()
                b, adm = bearer_client(user_b), bearer_client(admin)
                cls.leaks, cls.admin_sees = set(), set()
                for path in _list_routes():
                    code, body = _get(adm, path)
                    if MARKER in body:
                        cls.admin_sees.add(path)
                    code, body = _get(b, path)
                    if code == 200 and MARKER in body:
                        cls.leaks.add(f'GET {path}')
                cls.details = planted_detail_paths(adm, cls.planter, sorted(protected_routes()), MARKER)
                for path, real in cls.details.items():
                    code, body = _get(b, real)
                    if code == 200 and MARKER in body:
                        cls.leaks.add(f'GET-DETAIL {path}')
        finally:
            logging.disable(previous)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        module_access.clear_cache()

    def test_canaries_were_planted(self):
        self.assertGreater(len(self.planter.planted), 40, sorted(self.planter.skipped))

    def test_admin_sees_the_canaries(self):
        """Positive control: the marker really reaches list responses."""
        self.assertGreater(len(self.admin_sees), 20)

    def test_admin_sees_planted_detail_records(self):
        """Positive control for step 2: detail routes really reach planted records."""
        self.assertGreater(len(self.details), 15)

    def test_skipped_models_are_baselined(self):
        assert_matches_baseline(self, 'canary_skipped_models', set(self.planter.skipped))

    def test_skipped_models_baseline_lines_are_all_explained(self):
        from .baseline import BASELINE_DIR
        header, unexplained = None, []
        for ln in (BASELINE_DIR / 'canary_skipped_models.txt').read_text(encoding='utf-8').splitlines():
            s = ln.strip()
            if s.startswith('# reason:'):
                header = s
            elif s and not s.startswith('#') and header is None:
                unexplained.append(s)
        self.assertEqual(unexplained, [], 'skipped models without a reason: ' + ', '.join(unexplained))

    def test_branch_user_never_sees_another_branchs_records(self):
        assert_matches_baseline(self, 'branch_canary_leaks', self.leaks)
