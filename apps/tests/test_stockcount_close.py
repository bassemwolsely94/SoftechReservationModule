"""
Stock-count close rule: a session closes once it has counts — uploaded from the Excel
sheet (variance_ready) or counted live on mobile (uploaded). Bug: the desktop close
button only appeared at variance_ready, so a session counted only on mobile (which
stops at 'uploaded') could never be closed; the API meanwhile closed any status.
Nothing here writes to SOFTECH.
"""
from decimal import Decimal

from django.test import TestCase

from apps.stockcount.engine import refresh_session_counts
from apps.stockcount.models import StockCountSession, StockCountSnapshot
from .factories import make_admin


class StockCountCloseTests(TestCase):
    def setUp(self):
        _, self.profile, self.client_ = make_admin('sc_admin')

    def _session(self, status):
        return StockCountSession.objects.create(name='جرد', branch_code='B01', status=status)

    def _close(self, s):
        return self.client_.post(f'/api/stockcount/sessions/{s.pk}/close/')

    def test_live_counted_session_can_close(self):
        s = self._session('snapshot_taken')
        StockCountSnapshot.objects.create(session=s, item_code='IT001', item_name='X', branch_code='B01',
                                          expected_qty=Decimal('5'), counted_qty=Decimal('4'),
                                          difference=Decimal('-1'), variance_type='deficit')
        refresh_session_counts(s)                     # what the mobile count-entry endpoint calls
        s.refresh_from_db()
        self.assertEqual(s.status, 'uploaded')
        self.assertEqual(s.deficit_count, 1)
        r = self._close(s)
        self.assertEqual(r.status_code, 200, r.content)
        s.refresh_from_db()
        self.assertEqual(s.status, 'closed')

    def test_excel_uploaded_session_can_close(self):
        s = self._session('variance_ready')
        self.assertEqual(self._close(s).status_code, 200)

    def test_cannot_close_before_counts(self):
        for st in ('draft', 'snapshot_taken', 'exported'):
            s = self._session(st)
            self.assertEqual(self._close(s).status_code, 400, st)
            s.refresh_from_db()
            self.assertEqual(s.status, st)

    def test_already_closed_is_idempotent(self):
        s = self._session('closed')
        self.assertEqual(self._close(s).status_code, 200)
