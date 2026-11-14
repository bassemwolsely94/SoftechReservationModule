"""ETA history screens (phase 2): browse, detail, official PDF, export. Spec 2026-11-14-eta-history-mirror-design.md."""
import datetime as dt
import io
from decimal import Decimal
from unittest import mock

import openpyxl
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.tax_invoicing import eta_client, history_views
from apps.tax_invoicing.models import EtaMirrorDocument, EtaMirrorReceipt
from apps.tests.test_tax_invoicing import Fixture, api

URL = '/api/tax-invoicing/history/'


def _response(status_code, body=None, content=b'', headers=None):
    r = mock.Mock(status_code=status_code, content=content, headers=headers or {'Content-Type': 'application/json'})
    r.json.return_value = body if body is not None else {}
    return r


def _when(day, hour=10):
    return timezone.make_aware(dt.datetime(2026, 10, day, hour))


class HistoryScreenTests(Fixture, TestCase):

    def setUp(self):
        self.build('hs')
        D = EtaMirrorDocument.objects
        D.create(system='production', uuid='D1', internal_id='INV-1', doc_type='i', direction='sent', status='valid',
                 issuer_rin='499336534', receiver_type='B', receiver_id='999888777', receiver_name='شركة النور',
                 issued_at=_when(1), total_amount=Decimal('114'), net_amount=Decimal('100'))
        D.create(system='production', uuid='D2', internal_id='INV-2', doc_type='c', direction='sent', status='cancelled',
                 issuer_rin='499336534', receiver_type='P', receiver_id='29001011234567', receiver_name='أحمد',
                 issued_at=_when(5), total_amount=Decimal('50'))
        D.create(system='production', uuid='D3', internal_id='S-9', doc_type='i', direction='received', status='valid',
                 issuer_rin='111', issuer_name='مورد', issued_at=_when(9), total_amount=Decimal('900'))
        D.create(system='preprod', uuid='T1', doc_type='i', direction='sent', status='valid', issued_at=_when(2),
                 total_amount=Decimal('1'))
        R = EtaMirrorReceipt.objects
        for i in range(3):
            R.create(system='production', uuid=f'R{i}', receipt_number=f'90{i}', pos_serial='POS-A' if i < 2 else 'POS-B',
                     issued_at=_when(3 + i), status='valid', receipt_type='s', total_amount=Decimal('10') * (i + 1))

    # ── browse ──────────────────────────────────────────────────────────────────────────────────

    def test_browsing_needs_view_and_a_known_system(self):
        self.assertEqual(api(self.pharmacist).get(URL + 'documents/', {'system': 'production'}).status_code, 403)
        self.assertEqual(api(self.accountant).get(URL + 'documents/', {'system': 'staging'}).status_code, 400)

    def test_documents_filter_sort_page_and_total_within_one_system(self):
        body = api(self.accountant).get(URL + 'documents/', {'system': 'production', 'direction': 'sent',
                                                           'ordering': '-total_amount'}).json()
        self.assertEqual([r['uuid'] for r in body['rows']], ['D1', 'D2'])
        self.assertEqual((body['count'], body['total_amount']), (2, '164.00000'))
        body = api(self.accountant).get(URL + 'documents/', {'system': 'production', 'date_from': '2026-10-04',
                                                           'date_to': '2026-10-09', 'status': 'valid'}).json()
        self.assertEqual([r['uuid'] for r in body['rows']], ['D3'])
        body = api(self.accountant).get(URL + 'documents/', {'system': 'production', 'q': 'النور'}).json()
        self.assertEqual([r['uuid'] for r in body['rows']], ['D1'])
        body = api(self.accountant).get(URL + 'documents/', {'system': 'production', 'page_size': 1, 'page': 2,
                                                           'ordering': 'issued_at'}).json()
        self.assertEqual(([r['uuid'] for r in body['rows']], body['pages']), (['D2'], 3))
        self.assertNotIn('T1', [r['uuid'] for r in api(self.accountant).get(URL + 'documents/', {'system': 'production'}).json()['rows']])

    def test_a_persons_national_id_is_masked_a_companys_tax_id_is_not(self):
        rows = {r['uuid']: r for r in api(self.accountant).get(URL + 'documents/', {'system': 'production'}).json()['rows']}
        self.assertEqual(rows['D1']['receiver_id'], '999888777')
        self.assertEqual(rows['D2']['receiver_id'], '••••••••••4567')

    def test_receipts_filter_by_device_and_list_the_devices(self):
        body = api(self.accountant).get(URL + 'receipts/', {'system': 'production', 'device': 'POS-A'}).json()
        self.assertEqual(sorted(r['receipt_number'] for r in body['rows']), ['900', '901'])
        self.assertEqual((body['count'], body['total_amount']), (2, '30.00000'))
        self.assertEqual(body['devices'], ['POS-A', 'POS-B'])
        self.assertEqual(api(self.accountant).get(URL + 'receipts/', {'system': 'production', 'ordering': 'nope'}).status_code, 400)

    # ── detail and PDF ──────────────────────────────────────────────────────────────────────────

    def _details(self):
        return {'invoiceLines': [{'internalCode': '60001', 'description': 'Panadol', 'itemCode': 'EG-1-60001', 'quantity': 2,
                                  'unitValue': {'amountEGP': 50}, 'salesTotal': 100, 'discount': {'amount': 0},
                                  'netTotal': 100, 'lineTaxableItems': [{'taxType': 'T1', 'amount': 14}], 'total': 114}],
                'validationResults': {'status': 'Valid', 'validationSteps': [{'stepName': 'Step-03', 'status': 'Valid', 'error': None}]},
                'canbeCancelledUntil': '2026-10-08T10:00:00Z'}

    @override_settings(TAX_ETA_READ_PRODUCTION_ENABLED=True, TAX_ETA_READ_PRODUCTION_CLIENT_ID='i', TAX_ETA_READ_PRODUCTION_CLIENT_SECRET='s')
    def test_detail_asks_eta_once_then_keeps_it(self):
        doc = EtaMirrorDocument.objects.get(uuid='D1')
        with mock.patch.object(history_views, 'EtaReader') as R:
            R.return_value.why_not.return_value = ''
            R.return_value.get.return_value = _response(200, self._details())
            first = api(self.accountant).get(URL + f'documents/{doc.pk}/').json()
            second = api(self.accountant).get(URL + f'documents/{doc.pk}/').json()
        self.assertEqual(R.return_value.get.call_count, 1)
        line = first['lines'][0]
        self.assertEqual((line['internal_code'], line['quantity'], line['unit_value'], line['tax'], line['total']),
                         ('60001', '2', '50', '14', '114'))
        self.assertEqual(first['validation'][0]['name'], 'Step-03')
        self.assertEqual(second['lines'], first['lines'])

    def test_detail_without_eta_still_shows_the_copy_and_says_why(self):
        doc = EtaMirrorDocument.objects.get(uuid='D2')
        with mock.patch.object(history_views, 'EtaReader') as R:
            R.return_value.why_not.return_value = 'off'
            body = api(self.accountant).get(URL + f'documents/{doc.pk}/').json()
        self.assertEqual((body['uuid'], body['lines'], body['detail_unavailable']), ('D2', None, 'off'))
        self.assertEqual(body['receiver_id'], '••••••••••4567')

    def test_receipt_detail_lists_its_items(self):
        rec = EtaMirrorReceipt.objects.get(uuid='R0')
        details = {'receipt': {'itemData': [{'internalCode': '60001', 'description': 'Panadol', 'itemCode': 'EG-1-60001',
                                             'quantity': 1, 'unitPrice': 10, 'totalSale': 10, 'netSale': 10,
                                             'taxableItems': [{'amount': 0}], 'total': 10}],
                               'seller': {'branchCode': '1', 'deviceSerialNumber': 'POS-A'}}}
        with mock.patch.object(history_views, 'EtaReader') as R:
            R.return_value.why_not.return_value = ''
            R.return_value.get.return_value = _response(200, details)
            body = api(self.accountant).get(URL + f'receipts/{rec.pk}/').json()
        self.assertEqual((body['lines'][0]['description'], body['lines'][0]['total'], body['branch']), ('Panadol', '10', '1'))

    def test_official_pdf_comes_from_eta_and_is_audited(self):
        from apps.tax_invoicing.models import TaxAuditEvent
        doc = EtaMirrorDocument.objects.get(uuid='D1')
        with mock.patch.object(history_views, 'EtaReader') as R:
            R.return_value.why_not.return_value = ''
            R.return_value.get.return_value = _response(200, content=b'%PDF-1.4 x', headers={'Content-Type': 'application/pdf'})
            r = api(self.accountant).get(URL + f'documents/{doc.pk}/pdf/')
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'application/pdf'))
        self.assertEqual(r.content, b'%PDF-1.4 x')
        self.assertTrue(TaxAuditEvent.objects.filter(action='eta_history_pdf', entity_id=str(doc.pk)).exists())
        with mock.patch.object(history_views, 'EtaReader') as R:
            R.return_value.why_not.return_value = ''
            R.return_value.get.side_effect = eta_client.EtaUncertain('down')
            self.assertEqual(api(self.accountant).get(URL + f'documents/{doc.pk}/pdf/').status_code, 503)

    # ── export ──────────────────────────────────────────────────────────────────────────────────

    def test_export_is_a_workbook_of_the_filtered_rows_with_ids_masked(self):
        r = api(self.accountant).get(URL + 'documents/export/', {'system': 'production', 'direction': 'sent'})
        self.assertEqual(r.status_code, 200)
        ws = openpyxl.load_workbook(io.BytesIO(r.content)).active
        values = [[c for c in row] for row in ws.iter_rows(values_only=True)]
        self.assertEqual(len(values), 3)                        # header + 2 sent documents
        self.assertIn('••••••••••4567', [v for row in values for v in row])
        self.assertEqual(api(self.pharmacist).get(URL + 'documents/export/', {'system': 'production'}).status_code, 403)
