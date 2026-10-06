"""
Phase-1 tests for the Commerce Document engine — the deterministic pricing core:
inclusive-VAT back-computation, document totals, the Option-A allocation grid
(row-sum), per-type numbering, and the seeded type registry.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.commerce.models import (
    DocumentType, Recipient, RecipientLocation,
    CommerceDocument, DocumentLine, AllocationCell, next_document_number,
)


def _doc(type_code='retail_invoice', vat_rate='14.00'):
    dt = DocumentType.objects.get(code=type_code)
    return CommerceDocument.objects.create(
        doc_type=dt, number=next_document_number(dt),
        doc_date=date(2026, 9, 2), vat_rate=Decimal(vat_rate))


class SeedTypesTests(TestCase):
    def test_types_seeded(self):
        for code, prefix in [('quotation', 'QT'), ('retail_invoice', 'INV'), ('allocation', 'ALC')]:
            t = DocumentType.objects.get(code=code)
            self.assertEqual(t.number_prefix, prefix)
        self.assertTrue(DocumentType.objects.get(code='allocation').is_allocation)


class InclusiveVatTests(TestCase):
    def test_flagged_line_backcomputes_vat(self):
        d = _doc()
        ln = DocumentLine.objects.create(document=d, item_name='مكمل', unit_price=Decimal('114'),
                                         quantity=Decimal('1'), vat_applicable=True)
        self.assertEqual(ln.line_total, Decimal('114.00'))
        self.assertEqual(ln.vat_amount(Decimal('14')), Decimal('14.00'))   # inclusive
        self.assertEqual(ln.base_amount(Decimal('14')), Decimal('100.00'))

    def test_unflagged_line_no_vat(self):
        d = _doc()
        ln = DocumentLine.objects.create(document=d, item_name='دواء أساسي', unit_price=Decimal('100'),
                                         quantity=Decimal('2'), vat_applicable=False)
        self.assertEqual(ln.line_total, Decimal('200.00'))
        self.assertEqual(ln.vat_amount(Decimal('14')), Decimal('0.00'))
        self.assertEqual(ln.base_amount(Decimal('14')), Decimal('200.00'))

    def test_document_totals_mixed(self):
        d = _doc()
        DocumentLine.objects.create(document=d, item_name='مكمل', unit_price=Decimal('114'),
                                    quantity=Decimal('1'), vat_applicable=True)     # 114, vat 14
        DocumentLine.objects.create(document=d, item_name='دواء', unit_price=Decimal('50'),
                                    quantity=Decimal('2'), vat_applicable=False)    # 100, vat 0
        t = d.recompute_totals()
        self.assertEqual(t['total'], Decimal('214.00'))          # Σ gross
        self.assertEqual(t['vat_total'], Decimal('14.00'))
        self.assertEqual(t['subtotal_ex_vat'], Decimal('200.00'))
        d.refresh_from_db()
        self.assertEqual(d.total, Decimal('214.00'))
        self.assertEqual(d.vat_total, Decimal('14.00'))


class AllocationGridTests(TestCase):
    def test_row_sum_and_total(self):
        d = _doc(type_code='allocation')
        rec = Recipient.objects.create(name='مستشفى اختبار', kind=Recipient.KIND_HOSPITAL)
        maadi = RecipientLocation.objects.create(recipient=rec, name='المعادي', sort_order=1)
        nasr  = RecipientLocation.objects.create(recipient=rec, name='مدينة نصر', sort_order=2)
        giza  = RecipientLocation.objects.create(recipient=rec, name='الجيزة', sort_order=3)
        d.recipient = rec; d.save()
        ln = DocumentLine.objects.create(document=d, item_name='بنادول',
                                         unit_price=Decimal('10'), quantity=Decimal('0'))
        AllocationCell.objects.create(line=ln, location=maadi, quantity=Decimal('100'))
        AllocationCell.objects.create(line=ln, location=nasr,  quantity=Decimal('50'))
        AllocationCell.objects.create(line=ln, location=giza,  quantity=Decimal('80'))
        ln.sync_quantity_from_cells()
        self.assertEqual(ln.quantity, Decimal('230.00'))
        self.assertEqual(ln.line_total, Decimal('2300.00'))     # 230 × 10
        t = d.recompute_totals()
        self.assertEqual(t['total'], Decimal('2300.00'))

    def test_cell_unique_per_branch(self):
        d = _doc(type_code='allocation')
        rec = Recipient.objects.create(name='م', kind=Recipient.KIND_HOSPITAL)
        loc = RecipientLocation.objects.create(recipient=rec, name='فرع')
        ln = DocumentLine.objects.create(document=d, item_name='x', unit_price=1, quantity=0)
        AllocationCell.objects.create(line=ln, location=loc, quantity=5)
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AllocationCell.objects.create(line=ln, location=loc, quantity=9)


from django.test import override_settings
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient


@override_settings(COMMERCE_DOCS_ENABLED=True)
class CommerceApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='cx', password='x', is_staff=True, is_superuser=True)
        self.api = APIClient(); self.api.force_authenticate(self.user)

    def test_flag_off_blocks(self):
        with override_settings(COMMERCE_DOCS_ENABLED=False):
            r = self.api.get('/api/commerce/documents/')
            self.assertEqual(r.status_code, 503)

    def test_create_invoice_add_lines_totals_export(self):
        inv = DocumentType.objects.get(code='retail_invoice')
        r = self.api.post('/api/commerce/documents/',
                          {'doc_type': inv.id, 'doc_date': '2026-09-02'}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        doc = r.json()
        self.assertTrue(doc['number'].startswith('INV-2026-'))
        did = doc['id']
        # flagged supplement 114 (vat 14) + non-flagged drug 100
        self.api.post(f'/api/commerce/documents/{did}/lines/',
                      {'item_name': 'مكمل', 'unit_price': '114', 'quantity': '1', 'vat_applicable': True}, format='json')
        self.api.post(f'/api/commerce/documents/{did}/lines/',
                      {'item_name': 'دواء', 'unit_price': '50', 'quantity': '2', 'vat_applicable': False}, format='json')
        got = self.api.get(f'/api/commerce/documents/{did}/').json()
        self.assertEqual(float(got['total']), 214.0)
        self.assertEqual(float(got['vat_total']), 14.0)
        self.assertEqual(float(got['subtotal_ex_vat']), 200.0)
        self.assertEqual(len(got['lines']), 2)
        # export
        e = self.api.get(f'/api/commerce/documents/{did}/export/')
        self.assertEqual(e.status_code, 200)
        self.assertIn('spreadsheetml', e['Content-Type'])

    def test_allocation_grid_via_api(self):
        alc = DocumentType.objects.get(code='allocation')
        rec = Recipient.objects.create(name='مستشفى', kind=Recipient.KIND_HOSPITAL)
        a = RecipientLocation.objects.create(recipient=rec, name='المعادي', sort_order=1)
        b = RecipientLocation.objects.create(recipient=rec, name='الجيزة', sort_order=2)
        d = self.api.post('/api/commerce/documents/',
                          {'doc_type': alc.id, 'doc_date': '2026-09-02', 'recipient': rec.id}, format='json').json()
        did = d['id']
        ln = self.api.post(f'/api/commerce/documents/{did}/lines/',
                           {'item_name': 'بنادول', 'unit_price': '10', 'quantity': '0'}, format='json').json()
        lid = ln['id']
        self.api.post(f'/api/commerce/documents/{did}/lines/{lid}/cells/',
                      {'location': a.id, 'quantity': '100'}, format='json')
        self.api.post(f'/api/commerce/documents/{did}/lines/{lid}/cells/',
                      {'location': b.id, 'quantity': '80'}, format='json')
        grid = self.api.get(f'/api/commerce/documents/{did}/grid/').json()
        self.assertEqual(len(grid['locations']), 2)
        self.assertEqual(grid['rows'][0]['total_qty'], 180.0)
        self.assertEqual(grid['total'], 1800.0)   # 180 × 10
        # allocation export renders the grid (landscape), returns a valid xlsx
        e = self.api.get(f'/api/commerce/documents/{did}/export/')
        self.assertEqual(e.status_code, 200)
        self.assertIn('spreadsheetml', e['Content-Type'])


class NumberingTests(TestCase):
    def test_series_increments_per_type(self):
        qt = DocumentType.objects.get(code='quotation')
        n1 = next_document_number(qt, on_date=date(2026, 9, 2))
        self.assertTrue(n1.startswith('QT-2026-'))
        CommerceDocument.objects.create(doc_type=qt, number=n1, doc_date=date(2026, 9, 2))
        n2 = next_document_number(qt, on_date=date(2026, 9, 2))
        self.assertEqual(int(n2.rsplit('-', 1)[1]), int(n1.rsplit('-', 1)[1]) + 1)
        # different type has its own series
        inv = DocumentType.objects.get(code='retail_invoice')
        self.assertTrue(next_document_number(inv, on_date=date(2026, 9, 2)).startswith('INV-2026-'))
