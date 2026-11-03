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
