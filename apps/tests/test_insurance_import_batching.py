"""
Claim import fetches receipt lines from SOFTECH in batches, matched on the full
stktrans index key (branchcode, doccode, docnumber).

Real case (2026-11-05): one SOFTECH round-trip per receipt made create-and-import
take up to 47 s, and matching on docnumber + branch only (no doccode) pulled in lines
of unrelated documents that share the number — return 15540 at branch 140 (513 EGP)
came back with 26 extra lines of a 2024 doccode-25 document.
"""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from apps.insurance import importer
from apps.insurance import models as m
from apps.insurance.sybase_queries import (
    QUERY_MOTALBA_HEADER_FROM_DETAIL, QUERY_MOTALBA_LINES_BY_NO,
    QUERY_MOTALBA_LINES_BY_PERSONCODE_DATERANGE,
)

PC, MOTNO, BRANCH = '5008', 109, '140'


def _line_cols(itemcode, price):
    # itemcode, itemname, transqty, transprice, transprice_total, importedorigin,
    # itemstoreclassif, itemorigincode, custdiscpdescr, phcode, itemsaleprice, patientname
    return (itemcode, f'صنف {itemcode}', 1, price, price, '0', '1', '1', '', None, price, 'مريض')


class _FakeSoftech:
    """stktrans keyed by (branch, doccode, docnumber). Counts line queries."""

    def __init__(self, receipts, stktrans, fail_lines=0):
        self.receipts, self.stktrans = receipts, stktrans
        self.line_queries, self.fail_lines = 0, fail_lines

    def connection(self):
        c = mock.Mock()
        c.cursor.side_effect = lambda: _Cursor(self)
        return c


class _Cursor:
    def __init__(self, db):
        self.db, self._rows = db, []

    def execute(self, sql, params=()):
        db = self.db
        if sql == QUERY_MOTALBA_HEADER_FROM_DETAIL:
            self._rows = [(PC, MOTNO, datetime(2026, 10, 1), datetime(2026, 10, 31), 0, 0)]
        elif sql in (QUERY_MOTALBA_LINES_BY_NO, QUERY_MOTALBA_LINES_BY_PERSONCODE_DATERANGE):
            self._rows = db.receipts
        elif 'dbo.stktrans st' in sql:
            db.line_queries += 1
            if db.fail_lines:
                db.fail_lines -= 1
                raise RuntimeError('JZ0C0: Connection is already closed')
            if 'st.doccode = ?' in sql:          # batched, full index key
                rows = []
                for i in range(0, len(params), 3):
                    br, dc, dn = params[i:i + 3]
                    key = (str(br).strip(), str(dc).strip(), str(dn))
                    rows += [(int(dn), br, dc) + r for r in db.stktrans.get(key, [])]
                self._rows = rows
            else:                                 # old per-receipt: docnumber + branch only
                dn, br = str(params[0]), str(params[1]).strip()
                self._rows = [r for (b, _dc, d), rs in db.stktrans.items()
                              if b == br and d == dn for r in rs]
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _receipt(docnumber, doccode='115', branch=BRANCH, grand=100):
    # personcode, motalbano, branch, docnumber, docdate, doccode, order, grand,
    # patient, ppersoncode, custbranch, required
    return (PC, MOTNO, branch, docnumber, datetime(2026, 10, 5), doccode,
            docnumber, grand, 1, None, branch, grand)


class ImportBatchingTests(TestCase):
    def setUp(self):
        client = m.InsuranceClient.objects.create(name='عميل')
        self.sub = m.InsuranceSubClient.objects.create(client=client, name='فئة',
                                                       softech_personcode=PC)

    def _claim(self):
        return m.InsuranceClaim.objects.create(
            claim_number='MT-B-1', subclient=self.sub,
            period_from=date(2026, 10, 1), period_to=date(2026, 10, 31))

    def _run(self, db, path='motalbano'):
        claim = self._claim()
        with mock.patch.object(importer, '_get_connection', side_effect=db.connection), \
             mock.patch.object(importer, 'enrich_prescriptions_from_cache'):
            if path == 'motalbano':
                importer.import_claim_by_motalbano(claim, MOTNO)
            else:
                importer.import_claim_from_softech(claim, [PC], date(2026, 10, 1), date(2026, 10, 31))
        return claim

    def _many(self, n):
        receipts = [_receipt(1000 + i) for i in range(n)]
        stktrans = {(BRANCH, '115', str(1000 + i)): [_line_cols(f'I{i}', 100)] for i in range(n)}
        return _FakeSoftech(receipts, stktrans)

    def test_lines_for_many_receipts_come_in_a_few_queries(self):
        db = self._many(120)
        claim = self._run(db)
        self.assertEqual(claim.prescriptions.count(), 120)
        self.assertLessEqual(db.line_queries, 3)

    def test_date_range_path_is_batched_too(self):
        db = self._many(120)
        claim = self._run(db, path='dates')
        self.assertEqual(claim.prescriptions.count(), 120)
        self.assertLessEqual(db.line_queries, 3)

    def test_other_document_with_the_same_number_is_not_mixed_in(self):
        receipts = [_receipt(15540, doccode='30', grand=513)]
        stktrans = {
            (BRANCH, '30', '15540'): [_line_cols('RET1', 513)],
            (BRANCH, '25', '15540'): [_line_cols(f'OLD{i}', 200) for i in range(26)],
        }
        claim = self._run(_FakeSoftech(receipts, stktrans))
        rx = claim.prescriptions.get()
        self.assertEqual([ln.softech_itemcode for ln in rx.lines.all()], ['RET1'])

    def test_each_receipt_keeps_its_own_lines(self):
        receipts = [_receipt(1), _receipt(2)]
        stktrans = {(BRANCH, '115', '1'): [_line_cols('A', 10), _line_cols('B', 20)],
                    (BRANCH, '115', '2'): [_line_cols('C', 30)]}
        claim = self._run(_FakeSoftech(receipts, stktrans))
        got = {rx.softech_docnumber: sorted(ln.softech_itemcode for ln in rx.lines.all())
               for rx in claim.prescriptions.all()}
        self.assertEqual(got, {'1': ['A', 'B'], '2': ['C']})

    def test_dead_connection_after_retry_fails_the_import(self):
        db = self._many(3)
        db.fail_lines = 2
        with self.assertRaises(importer.InsuranceImportError):
            self._run(db)

    def test_one_dropped_connection_is_retried(self):
        db = self._many(3)
        db.fail_lines = 1
        claim = self._run(db)
        self.assertEqual(claim.prescriptions.count(), 3)
        self.assertEqual(sum(rx.lines.count() for rx in claim.prescriptions.all()), 3)
