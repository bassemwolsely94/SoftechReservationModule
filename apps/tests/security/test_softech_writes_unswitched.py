"""
SOFTECH write safety — writes reachable over HTTP with no switch (Batch 2, P-6).

  * alignment tier-create → discount_approvals.alignment.create_new_tier INSERTs a new tier
    into a SOFTECH lookup table. Now obeys PRICING_SOFTECH_WRITE_ENABLED, like its sibling
    apply_classification_changes.
  * invoice «probe» and coupon «batch-probe» → invoices.writer.probe_invoice runs the REAL
    INSERTs on SOFTECH then rolls back (production triggers fire, locks are held). Now obeys
    SOFTECH_PROBES_ENABLED (default off) — one check inside probe_invoice covers every caller.

The check happens BEFORE any SOFTECH connection is attempted.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from .routes import Tripwire


class ProbeSwitchTests(SimpleTestCase):

    @override_settings(SOFTECH_PROBES_ENABLED=False)
    def test_probe_refused_before_softech_when_switched_off(self):
        from apps.invoices import writer
        with Tripwire() as tw:
            with self.assertRaisesMessage(ValueError, 'SOFTECH_PROBES_ENABLED'):
                writer.probe_invoice(SimpleNamespace(branch=None, pk=1), confirm=True)
        self.assertEqual(tw.softech_calls, [])

    @override_settings(SOFTECH_PROBES_ENABLED=True)
    def test_probe_still_needs_confirm(self):
        from apps.invoices import writer
        with self.assertRaisesMessage(ValueError, 'confirm=True'):
            writer.probe_invoice(SimpleNamespace(branch=None, pk=1))


class TierCreateSwitchTests(SimpleTestCase):

    @override_settings(PRICING_SOFTECH_WRITE_ENABLED=False)
    def test_tier_create_refused_before_softech_when_switched_off(self):
        from apps.discount_approvals.alignment import create_new_tier
        with Tripwire() as tw:
            err, result = create_new_tier('store', 'تجربة', '1509')
        self.assertIsNone(result)
        self.assertIn('PRICING_SOFTECH_WRITE_ENABLED', err)
        self.assertEqual(tw.softech_calls, [])

    @override_settings(PRICING_SOFTECH_WRITE_ENABLED=True)
    def test_tier_create_validation_unchanged(self):
        from apps.discount_approvals.alignment import create_new_tier
        self.assertEqual(create_new_tier('nope', 'x', '1509'), ('نوع غير صالح', None))
