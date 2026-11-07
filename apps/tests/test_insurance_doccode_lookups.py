"""
Every single-receipt line lookup matches on (docnumber, branchcode, doccode).

SOFTECH numbers each document type separately per branch, so docnumber + branch can match
several documents: 15540 at branch 140 is a 2026 return (30) AND a 2017 sale (115). Without
doccode their lines were merged. Companion of test_insurance_import_batching (claim import).
"""
import re
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.test import TestCase

from apps.insurance import importer, reprice_service, resync
from apps.insurance import models as m
from apps.insurance.management.commands import repair_partial_pack_gross as repair
from apps.insurance.sybase_queries import (
    QUERY_PRESCRIPTION_HEADER_BY_DOCNO, QUERY_PRESCRIPTION_HEADER_BY_DOCNO_BRANCH,
)

DOC, BRANCH = '15540', '140'


def _cols(itemcode, price, qty=1):
    # itemcode, itemname, transqty, transprice, transprice_total, importedorigin,
    # itemstoreclassif, itemorigincode, custdiscpdescr, phcode, itemsaleprice, patientname
    return (itemcode, f'صنف {itemcode}', qty, price, price, '0', '1', '1', '', None, price, 'مريض')


class _Cursor:
    """stktrans keyed by doccode; a lookup without doccode gets every document's lines."""

    def __init__(self, lines, headers=()):
        self.lines, self.headers, self._rows = lines, list(headers), []

    def execute(self, sql, params=()):
        if sql in (QUERY_PRESCRIPTION_HEADER_BY_DOCNO, QUERY_PRESCRIPTION_HEADER_BY_DOCNO_BRANCH):
            self._rows = self.headers
        elif 'dbo.stktrans st' in sql:
            if re.search(r'st\.doccode\s*=\s*\?', sql):
                self._rows = self.lines.get(str(params[2]).strip(), [])
            else:
                self._rows = [r for rows in self.lines.values() for r in rows]
        else:
            self._rows = []

    def close(self):
        pass

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _conn(lines, headers=()):
    conn = mock.Mock()
    conn.cursor.side_effect = lambda: _Cursor(lines, headers)
    return conn


# Foreign document first, so a merged result would be picked up first.
LINES = {'115': [_cols('OLD', 99)], '30': [_cols('RET', 54)]}
HEADERS = [(BRANCH, '115', int(DOC), datetime(2017, 5, 31), 99, None, ''),
           (BRANCH, '30', int(DOC), datetime(2026, 10, 21), 54, None, '')]


class DoccodeLookupTests(TestCase):
    def setUp(self):
        client = m.InsuranceClient.objects.create(name='عميل')
        self.sub = m.InsuranceSubClient.objects.create(client=client, name='فئة', softech_personcode='5008')
        self.claim = m.InsuranceClaim.objects.create(
            claim_number='MT-D-1', subclient=self.sub,
            period_from=date(2026, 10, 1), period_to=date(2026, 10, 31))

    def _import_one(self, doccode='30'):
        return resync._import_one(
            self.claim, DOC, BRANCH, date(2026, 10, 21), doccode, Decimal('54'), Decimal('54'), '5008',
            Decimal('0'), Decimal('0'), Decimal('0'), None, _conn(LINES))

    def test_resync_import_takes_only_the_receipts_document(self):
        rx = self._import_one()
        self.assertEqual([ln.softech_itemcode for ln in rx.lines.all()], ['RET'])

    def test_single_receipt_add_uses_the_newest_documents_lines_and_date(self):
        with mock.patch.object(importer, '_get_connection', return_value=_conn(LINES, HEADERS)):
            out = importer.fetch_single_rx_from_softech(DOC, self.claim, branchcode=BRANCH)
        self.assertEqual([ln['itemcode'] for ln in out['lines']], ['RET'])
        self.assertEqual(out['softech_docdate'], date(2026, 10, 21))

    def test_single_receipt_add_with_one_document_is_unchanged(self):
        with mock.patch.object(importer, '_get_connection',
                               return_value=_conn(LINES, [HEADERS[0]])):
            out = importer.fetch_single_rx_from_softech(DOC, self.claim, branchcode=BRANCH)
        self.assertEqual([ln['itemcode'] for ln in out['lines']], ['OLD'])

    def test_reprice_pick_list_shows_only_the_asked_document(self):
        with mock.patch.object(importer, '_get_connection', return_value=_conn(LINES)):
            self.assertEqual([x['itemcode'] for x in reprice_service.list_receipt_lines(DOC, BRANCH)], ['OLD'])
            self.assertEqual([x['itemcode'] for x in reprice_service.list_receipt_lines(DOC, BRANCH, '30')], ['RET'])

    def _repair_output(self, softech_lines, headers):
        rx = self._import_one()
        ln = rx.lines.get()
        ln.softech_itemcode, ln.line_total = 'SAME', Decimal('54.03')
        ln.save(update_fields=['softech_itemcode', 'line_total'])
        cmd = repair.Command(stdout=StringIO())
        with mock.patch.object(repair, 'line_variance_map',
                               return_value={ln.pk: {'value_discrepancy': True}}):
            cmd._repair_claim(self.claim, _conn(softech_lines, headers), Decimal('1'), apply=False)
        return cmd.stdout.getvalue()

    def test_repair_compares_with_the_receipts_own_document(self):
        out = self._repair_output({'115': [_cols('SAME', 99)], '30': [_cols('SAME', 54)]}, HEADERS)
        self.assertIn('→ 54.00', out)
        self.assertIn('1 to fix', out)

    def test_repair_skips_a_receipt_whose_document_cannot_be_told(self):
        other_dates = [(BRANCH, '115', int(DOC), datetime(2017, 5, 31), 99, None, ''),
                       (BRANCH, '30', int(DOC), datetime(2025, 1, 1), 54, None, '')]
        out = self._repair_output({'115': [_cols('SAME', 99)], '30': [_cols('SAME', 54)]}, other_dates)
        self.assertIn('doccode_unknown', out)
        self.assertIn('0 to fix', out)
