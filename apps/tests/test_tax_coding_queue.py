"""ETA production item coding queue (batch S1): the shared VAT-treatment confirmation and the queue built on it."""
from django.test import TestCase

from apps.tax_invoicing import services
from apps.tax_invoicing.models import TaxItemProfile
from apps.tests.test_tax_invoicing import Fixture


class ConfirmTreatmentTests(Fixture, TestCase):
    def setUp(self):
        self.build('cq')

    def test_taxable_sets_rate_and_confirmation(self):
        p = TaxItemProfile(softech_itemcode='Q1')
        services.confirm_treatment(p, treatment='taxable', vat_rate='14', reference='', actor=self.accountant)
        self.assertEqual(p.tax_treatment, 'taxable')
        self.assertEqual(int(p.vat_rate), 14)
        self.assertIsNotNone(p.treatment_confirmed_at)
        self.assertEqual(p.treatment_confirmed_by, self.accountant)

    def test_exempt_without_reference_raises(self):
        p = TaxItemProfile(softech_itemcode='Q2')
        with self.assertRaises(services.TaxRuleError):
            services.confirm_treatment(p, treatment='exempt', vat_rate=0, reference=' ', actor=self.accountant)

    def test_exempt_with_reference_sets_vat_zero(self):
        p = TaxItemProfile(softech_itemcode='Q3')
        services.confirm_treatment(p, treatment='exempt', vat_rate=14, reference='م/1', actor=self.accountant)
        self.assertEqual(int(p.vat_rate), 0)
        self.assertEqual(p.treatment_reference, 'م/1')

    def test_unclassified_clears_confirmation(self):
        p = self.coded('Q4')
        services.confirm_treatment(p, treatment='unclassified', vat_rate=0, reference='', actor=self.accountant)
        self.assertIsNone(p.treatment_confirmed_at)
        self.assertIsNone(p.treatment_confirmed_by)

    def test_unknown_and_bad_taxable_rate(self):
        p = TaxItemProfile(softech_itemcode='Q5')
        with self.assertRaises(services.TaxRuleError):
            services.confirm_treatment(p, treatment='nope', vat_rate=0, reference='', actor=self.accountant)
        with self.assertRaises(services.TaxRuleError):
            services.confirm_treatment(p, treatment='taxable', vat_rate=0, reference='', actor=self.accountant)
