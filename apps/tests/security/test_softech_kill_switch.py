"""
SOFTECH kill-switch integrity (Batch 2, P-3).

Every SOFTECH connection must go through config/sybase.py's guarded path, so that
SOFTECH_READ_ONLY (and the branch-host override) apply to it. The static guard lists any
exception in baselines/raw_softech_connect.txt; this test keeps that list EMPTY — a
connection that bypasses the kill-switch is never an acceptable, reviewed exception.
"""
from django.test import SimpleTestCase

from .baseline import load_baseline


class KillSwitchIntegrityTests(SimpleTestCase):

    def test_no_connection_may_bypass_the_kill_switch(self):
        self.assertEqual(load_baseline('raw_softech_connect'), set(),
                         'SOFTECH connections outside config/sybase.py ignore SOFTECH_READ_ONLY')


class WriteSwitchDefaultTests(SimpleTestCase):
    """Batch 2, P-5: a SOFTECH write runs only when someone deliberately switched it on.
    (Under manage.py test the settings ignore .env, so these read the CODE defaults.)"""

    FOUR = ('PRICING_SOFTECH_WRITE_ENABLED', 'REPLICATION_REPAIR_ENABLED',
            'LOYALTY_SOFTECH_WRITE_ENABLED', 'PERSONAL_COMMENT_WRITE_ENABLED')

    def test_softech_write_switches_default_off(self):
        from django.conf import settings
        self.assertEqual([n for n in self.FOUR if getattr(settings, n)], [])
