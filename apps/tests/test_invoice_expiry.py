"""Expiry entry follows the SofTech screen: . - / separators, day first, 2- or 4-digit
year; a month/year expiry gets day = month (owner rule 2026-10-31)."""
from django.test import SimpleTestCase

from apps.invoices.ocr import normalize_expiry
from apps.invoices.serializers import InvoiceLineWriteSerializer
from apps.invoices.writer import _parse_expiry


class NormalizeExpiryTests(SimpleTestCase):
    def test_day_first_any_separator(self):
        for raw in ('09/09/2029', '09.09.2029', '09-09-2029', '9.9.29', '9-9-29'):
            self.assertEqual(normalize_expiry(raw), '2029-09-09', raw)
        self.assertEqual(normalize_expiry('01-09-2029'), '2029-09-01')
        self.assertEqual(normalize_expiry('1/9/29'), '2029-09-01')

    def test_two_digit_year_full_date(self):
        # stored on invoice 224 and previously parsed to nothing (would post no expiry)
        self.assertEqual(normalize_expiry('5-5-28'), '2028-05-05')
        self.assertEqual(normalize_expiry('6-6-28'), '2028-06-06')

    def test_month_year_day_equals_month(self):
        self.assertEqual(normalize_expiry('09.2029'), '2029-09-09')
        self.assertEqual(normalize_expiry('05.2028'), '2028-05-05')
        self.assertEqual(normalize_expiry('08-27'), '2027-08-08')
        self.assertEqual(normalize_expiry('2027-08'), '2027-08-08')
        self.assertEqual(normalize_expiry('Aug 2027'), '2027-08-08')

    def test_iso_and_month_end(self):
        self.assertEqual(normalize_expiry('2029-09-01'), '2029-09-01')
        self.assertEqual(normalize_expiry('31/04/2027'), '2027-04-30')
        self.assertEqual(normalize_expiry('abc'), '')

    def test_writer_reads_two_digit_year(self):
        self.assertEqual(str(_parse_expiry('5-5-28')), '2028-05-05')


class ExpirySaveTests(SimpleTestCase):
    def test_typed_expiry_saved_normalized(self):
        s = InvoiceLineWriteSerializer()
        self.assertEqual(s.validate_expiry_date('6-6-28'), '2028-06-06')
        self.assertEqual(s.validate_expiry_date(''), '')

    def test_unreadable_expiry_rejected(self):
        from rest_framework.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            InvoiceLineWriteSerializer().validate_expiry_date('xx')


class GridSaveRoundingTests(SimpleTestCase):
    """The grid engine back-solves discounts to 4 places; the column keeps 3. The save
    must round, not reject — a rejected save silently lost the operator's edit
    (invoice 224, Actrapid net 268.96 never saved → total 16.41 off the paper)."""
    def test_engine_precision_is_rounded_not_rejected(self):
        s = InvoiceLineWriteSerializer(data={'unit_price': 268.96, 'discount_pct': 18.9467,
                                             'vat_pct': 14.0001}, partial=True)
        self.assertTrue(s.is_valid(), s.errors)
        self.assertEqual(str(s.validated_data['discount_pct']), '18.947')
        self.assertEqual(str(s.validated_data['vat_pct']), '14.00')

    def test_garbage_still_rejected(self):
        s = InvoiceLineWriteSerializer(data={'discount_pct': 'abc'}, partial=True)
        self.assertFalse(s.is_valid())


class RenormalizeStoredExpiryTests(SimpleTestCase):
    """renormalize_invoice_expiry: only month/year printings still stored as the old
    1st-of-month form change; hand-typed dates stay."""
    def _line(self, printed, stored):
        import json
        from types import SimpleNamespace as NS
        return NS(raw_text=json.dumps({'expiry_date': printed}), expiry_date=stored)

    def test_month_year_first_of_month_becomes_day_equals_month(self):
        from apps.invoices.management.commands.renormalize_invoice_expiry import new_expiry
        self.assertEqual(new_expiry(self._line('05.2028', '2028-05-01')), '2028-05-05')

    def test_hand_typed_or_full_dates_left_alone(self):
        from apps.invoices.management.commands.renormalize_invoice_expiry import new_expiry
        self.assertIsNone(new_expiry(self._line('05.2028', '2028-05-17')))   # typed by hand
        self.assertIsNone(new_expiry(self._line('01/09/2029', '2029-09-01')))  # full printed date
        self.assertIsNone(new_expiry(self._line('05.2028', '2029-01-01')))   # changed month by hand
