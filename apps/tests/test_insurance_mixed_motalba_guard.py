"""
A date-range import must never stitch several SOFTECH motalbas into one claim.

Real case (2026-11-01): جنوب القاهرة العاملين, 1/10–31/10 by dates pulled motalbas
127/128/129/130 together; the issued one was 130 (27/9–31/10).
"""
from datetime import date, datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from apps.insurance import importer
from apps.insurance import models as m
from apps.insurance.sybase_queries import (
    QUERY_MOTALBA_HEADER_FROM_DETAIL, QUERY_MOTALBA_LINES_BY_PERSONCODE_DATERANGE,
)

HEADERS = {
    127: ('4227', 127, datetime(2026, 10, 1), datetime(2026, 10, 28), 609, 867466.71),
    130: ('4227', 130, datetime(2026, 9, 27), datetime(2026, 10, 31), 661, 936729.01),
}


def _line(motno, doc):
    # personcode, motalbano, branch, docnumber, docdate, doccode, order, grand, patient, ppc, custbr, required
    return ('4227', motno, '160', doc, datetime(2026, 10, 5), '115', doc, 100, 1, None, '160', 90)


class _Cursor:
    def __init__(self, lines):
        self.lines, self._rows = lines, []

    def execute(self, sql, params):
        if sql == QUERY_MOTALBA_LINES_BY_PERSONCODE_DATERANGE:
            self._rows = self.lines
        elif sql == QUERY_MOTALBA_HEADER_FROM_DETAIL:
            self._rows = [HEADERS[params[1]]] if params[1] in HEADERS else []
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


def _conn(lines):
    c = mock.Mock()
    c.cursor.return_value = _Cursor(lines)
    return c


_TOTALS = {k: Decimal('0') for k in ('local_before', 'imported_before', 'tarsia_before',
                                      'gross_before', 'total_discount', 'net_after')}


class MixedMotalbaGuardTests(TestCase):
    def setUp(self):
        client = m.InsuranceClient.objects.create(name='جنوب القاهرة')
        self.sub = m.InsuranceSubClient.objects.create(client=client, name='العاملين',
                                                       softech_personcode='4227')
        u = get_user_model().objects.create_user(username='g', password='x',
                                                  is_staff=True, is_superuser=True)
        self.api = APIClient(); self.api.force_authenticate(u)

    def _claim(self):
        return m.InsuranceClaim.objects.create(
            claim_number='MT-G-1', subclient=self.sub,
            period_from=date(2026, 10, 1), period_to=date(2026, 10, 31))

    def test_several_motalbas_refused_before_any_write(self):
        claim = self._claim()
        lines = [_line(127, 1), _line(127, 2), _line(130, 3)]
        with mock.patch.object(importer, '_get_connection', return_value=_conn(lines)):
            with self.assertRaises(importer.InsuranceMixedMotalbaError) as cm:
                importer.import_claim_from_softech(claim, ['4227'], date(2026, 10, 1), date(2026, 10, 31))
        found = {f['motalbano']: f for f in cm.exception.motalbas}
        self.assertEqual(set(found), {127, 130})
        self.assertEqual(found[130]['motfromdate'], '2026-09-27')
        self.assertEqual(found[130]['rxcount'], 661)
        self.assertEqual(found[127]['in_range'], 2)
        self.assertEqual(claim.prescriptions.count(), 0)

    def test_numbered_plus_unnumbered_also_refused(self):
        with mock.patch.object(importer, '_get_connection',
                               return_value=_conn([_line(130, 1), _line(None, 2)])):
            with self.assertRaises(importer.InsuranceMixedMotalbaError):
                importer.import_claim_from_softech(self._claim(), ['4227'],
                                                   date(2026, 10, 1), date(2026, 10, 31))

    def test_single_motalba_imports_and_records_its_number(self):
        claim = self._claim()
        with mock.patch.object(importer, '_get_connection', return_value=_conn([_line(130, 1)])), \
             mock.patch.object(importer, '_fetch_and_classify_lines', return_value=([], dict(_TOTALS), 'اسم')), \
             mock.patch.object(importer, '_write_prescription_snapshot'), \
             mock.patch.object(importer, 'enrich_prescriptions_from_cache'):
            importer.import_claim_from_softech(claim, ['4227'], date(2026, 10, 1), date(2026, 10, 31))
        claim.refresh_from_db()
        self.assertEqual(claim.softech_motalba_no, '130')

    def test_create_and_import_returns_409_with_choices_and_leaves_no_claim(self):
        before = m.InsuranceClaim.objects.count()
        with mock.patch.object(importer, '_get_connection',
                               return_value=_conn([_line(127, 1), _line(130, 2)])):
            r = self.api.post('/api/insurance/claims/create-and-import/', {
                'subclient_id': self.sub.id, 'period_from': '2026-10-01',
                'period_to': '2026-10-31', 'softech_motalba_no': ''}, format='json')
        self.assertEqual(r.status_code, 409, r.content)
        self.assertEqual({x['motalbano'] for x in r.json()['motalbas']}, {127, 130})
        self.assertEqual(m.InsuranceClaim.objects.count(), before)
