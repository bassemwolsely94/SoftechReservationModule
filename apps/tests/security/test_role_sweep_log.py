"""
apps/tests/security/test_role_sweep_log.py

The role × route sweep in log mode: the middleware only logs, so whatever answers is the
VIEW's own check. Split from test_role_sweep.py (enforce mode) so the two ~6-minute sweeps
run on different CI shards; the module docstring there explains the sweep.
"""
from django.test import TestCase

from .baseline import assert_matches_baseline
from .test_role_sweep import SweepSetup


class RoleSweepLogTests(SweepSetup, TestCase):
    MODE = 'log'

    def test_sweep_is_not_empty(self):
        self.assertGreater(self.result.classified, 2000)

    def test_log_mode_leaks(self):
        assert_matches_baseline(self, 'role_leaks_log', self.result.leaks)

    def test_unproven(self):
        """Denied role got 404 and so did admin: the check behind it was never reached."""
        assert_matches_baseline(self, 'role_unproven', self.result.unproven)
