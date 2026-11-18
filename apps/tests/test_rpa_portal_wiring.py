from django.conf import settings
from django.test import TestCase


class PortalWiringTests(TestCase):
    def test_flag_off_and_registered(self):
        from config.writers import WRITER_FLAGS, writer_allowed
        self.assertIn('RPA_SUPPLIER_PORTAL_ENABLED', WRITER_FLAGS)
        self.assertFalse(settings.RPA_SUPPLIER_PORTAL_ENABLED)
        self.assertFalse(writer_allowed('RPA_SUPPLIER_PORTAL_ENABLED'))

    def test_portal_source_choice(self):
        from apps.supply.models import AvailabilityBatch
        self.assertIn('portal', dict(AvailabilityBatch.SOURCE_CHOICES))

    def test_audit_actions(self):
        from apps.audit.models import AuditLog
        acts = dict(AuditLog._meta.get_field('action').choices)
        for a in ('rpa_portal_basket_recorded', 'rpa_portal_needs_person', 'rpa_portal_code_learnt'):
            self.assertIn(a, acts)
