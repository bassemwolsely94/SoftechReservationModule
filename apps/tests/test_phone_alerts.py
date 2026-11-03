from django.conf import settings
from django.test import TestCase

from apps.notifications.phone_alerts.events import EVENTS
from apps.notifications.phone_alerts.models import PhoneAlertPolicy


class PolicySeedTests(TestCase):
    def test_policy_seeded_for_v1_events(self):
        rows = {p.event: p for p in PhoneAlertPolicy.objects.all()}
        self.assertEqual(set(rows), set(EVENTS))
        self.assertEqual(len(rows), 7)
        for key, p in rows.items():
            self.assertEqual(p.mode, 'always' if key == 'escalation' else 'optional', key)
            self.assertEqual((p.remind_after_min, p.escalate_after_min, p.max_reminders), (15, 30, 2))

    def test_policy_absent_means_never(self):
        self.assertIsNone(PhoneAlertPolicy.for_event('x'))

    def test_switches_default_off(self):
        self.assertIs(settings.PHONE_ALERTS_SEND_ENABLED, False)
        self.assertIs(settings.MORNING_BRIEF_SEND_ENABLED, False)
