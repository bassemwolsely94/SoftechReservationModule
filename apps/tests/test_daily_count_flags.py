"""
Project 2 switches (doc: docs/superpowers/specs/2026-11-03-phone-scan-and-daily-counts-design.md):
camera scanning and daily counts ship dark — /api/auth/me/ tells the frontend whether to show them.
"""
from django.test import TestCase, override_settings

from .factories import make_salesperson


class FeatureFlagsOnMeTests(TestCase):
    def setUp(self):
        _, self.profile, self.client_ = make_salesperson('flags_sales')

    def test_me_features_default_off(self):
        r = self.client_.get('/api/auth/me/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['features'], {'camera_scan': False, 'daily_count': False})

    @override_settings(CAMERA_SCAN_ENABLED=True, DAILY_COUNT_ENABLED=True)
    def test_me_features_on(self):
        r = self.client_.get('/api/auth/me/')
        self.assertEqual(r.json()['features'], {'camera_scan': True, 'daily_count': True})


class BranchPilotSwitchTests(TestCase):
    """The per-branch daily-count pilot switch is reachable from the branch settings screen (admin only)."""

    def test_admin_turns_branch_pilot_on(self):
        from apps.branches.models import BranchSettings
        from .factories import make_admin, make_branch
        b = make_branch()
        _, _, ca = make_admin('pilot_admin')
        r = ca.get(f'/api/branches/{b.pk}/settings/')
        self.assertIs(r.json()['daily_count_enabled'], False)
        r = ca.patch(f'/api/branches/{b.pk}/settings/', {'daily_count_enabled': True}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(BranchSettings.for_branch(b).daily_count_enabled)

    def test_salesperson_cannot_turn_it_on(self):
        from .factories import make_branch
        b = make_branch()
        _, _, c = make_salesperson('pilot_sales', branch=b)
        r = c.patch(f'/api/branches/{b.pk}/settings/', {'daily_count_enabled': True}, format='json')
        self.assertEqual(r.status_code, 403)


@override_settings(DAILY_COUNT_ENABLED=True)
class DailyCountOwnGateTests(TestCase):
    """/api/stockcount/daily/ has its own gate (counter = own list; reviewers = stock-audit access),
    like /api/stock-audit/. The `stockcount` matrix module must not block a salesperson's own list."""

    def test_daily_routes_are_not_mapped_to_the_matrix(self):
        from core.middleware.module_access import required
        for path in ('/api/stockcount/daily/my/', '/api/stockcount/daily/my/count/', '/api/stockcount/daily/board/'):
            self.assertIsNone(required(path, 'GET'), path)
            self.assertIsNone(required(path, 'POST'), path)
        self.assertIsNotNone(required('/api/stockcount/sessions/', 'GET'))

    def test_salesperson_reaches_own_list_under_enforce(self):
        from apps.tests.security.fixtures import seed_code_matrix
        from core.middleware import module_access
        seed_code_matrix()
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        _, _, c = make_salesperson('gate_sales')
        with override_settings(RBAC_ENFORCEMENT='enforce'):
            self.assertEqual(c.get('/api/stockcount/daily/my/').status_code, 200)
            # saving a count is a POST — the matrix gives salespeople read-only stockcount
            r = c.post('/api/stockcount/daily/my/count/', {'pick_id': 999999, 'counted_qty': '1'}, format='json')
            self.assertEqual(r.status_code, 404, r.content)      # reached the view (no such pick), not 403
            self.assertEqual(c.get('/api/stockcount/daily/board/').status_code, 403)   # the view's own gate
