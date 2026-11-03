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
