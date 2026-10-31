"""The OCR purchase writer sends what the native «مشتريات من الموردين» screen sends.
custdiscp = 1.0 on purchase lines (owner-approved 2026-10-31; 862/871 native lines on
branch 130; rollback probe 2026-10-26 showed no trigger sets it). Returns stay 0."""
from types import SimpleNamespace as NS

from django.test import SimpleTestCase

from apps.invoices import writer as IW


def _invoice(kind):
    return NS(softech_branchcode='130', store_code='130', softech_doccode='10' if kind == 'purchase' else '120',
              doc_kind=kind, return_of_docnumber=0, vendor=NS(softech_personcode='565'))


def _entry():
    line = NS(expiry_date='2028-06-06', quantity=2, batch_number='', item=NS(softech_id='1356'))
    return {'_line': line, 'qty': 2, 'itemsalestax': 0.0, 'itemsaleprice_tax': 338.0,
            'pharmacydiscp': 18.947, 'additionaldiscp': 0.0, 'specialdiscp': 0.0,
            'transprice': 273.96, 'transprice_total': 547.92, 'origintaxp': 0.0, 'itemsaleprice': 338.0}


class NativeCustdiscpTests(SimpleTestCase):
    def test_purchase_line_sends_native_custdiscp(self):
        row = IW._line_row(_invoice('purchase'), _entry(), 1, '1', 2)
        self.assertEqual(row['custdiscp'], 1.0)

    def test_return_line_keeps_zero(self):
        row = IW._line_row(_invoice('return'), _entry(), 1, '1', 0)
        self.assertEqual(row['custdiscp'], 0.0)


class _Lines(list):
    def select_related(self, *a):
        return self

    def all(self):
        return self


def _vinvoice(kind, *lines):
    return NS(doc_kind=kind, vendor=NS(softech_personcode='565'), lines=_Lines(lines))


def _vline(lid, batch, required):
    return NS(id=lid, item_id=lid, quantity=2, unit_price=273.96, public_price=338,
              discount_pct=0, extra_discount_pct=0, batch_number=batch, manual_name='', raw_text='',
              item=NS(name='ENTRESTO 100MG', softech_id='120468', batch_required=required))


class BatchRequiredValidationTests(SimpleTestCase):
    """SOFTECH items.itempartno = 1 (Entresto, Kisqali…) → the batch must be entered
    before posting; it lands in stktrans.item_partno. Owner rule 2026-10-31."""
    def _codes(self, inv):
        from apps.invoices import validations
        return [e['code'] for e in validations.validate_invoice(inv, live=False)['errors']]

    def test_required_batch_missing_blocks(self):
        self.assertIn('batch_required', self._codes(_vinvoice('purchase', _vline(1, '', True))))

    def test_required_batch_present_ok(self):
        self.assertNotIn('batch_required', self._codes(_vinvoice('purchase', _vline(1, 'VR75C9G', True))))

    def test_optional_batch_may_be_empty(self):
        self.assertNotIn('batch_required', self._codes(_vinvoice('purchase', _vline(1, '', False))))

    def test_returns_not_checked(self):
        self.assertNotIn('batch_required', self._codes(_vinvoice('return', _vline(1, '', True))))
