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
from .sweep import SWEEP_ID, protected_routes


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


@override_settings(RBAC_ENFORCEMENT='enforce')
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

    def test_branch_user_never_sees_another_branchs_records(self):
        assert_matches_baseline(self, 'branch_canary_leaks', self.leaks)
