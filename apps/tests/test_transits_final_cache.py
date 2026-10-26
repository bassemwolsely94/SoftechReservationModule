"""sync_in_transit (doc 30, F3): final documents (received without mismatch, or
force-closed) are not re-read from SOFTECH every run — only on the daily full pass."""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.transits.management.commands import sync_in_transit as mod
from apps.transits.models import InTransitTransfer
from .factories import make_branch, make_branch2
from .test_transits_sync import FakeConn, TODAY, _hdr, _line


def _softech_reads(conn):
    """Receipt + line queries (everything except the header scan)."""
    return [s for s, _ in conn.queries if not ("from softechdb9.dbo.stktransm" in s and "doccode = '125'" in s)]


class FinalDocumentCacheTests(TestCase):

    def setUp(self):
        make_branch('HQ', '100')
        make_branch2('Giza', '140')
        self.cmd = mod.Command()

    def _conn(self, doc, received_qty=5):
        c = FakeConn()
        c.headers = [_hdr(doc, '100', '140', date=TODAY - datetime.timedelta(days=3))]
        c.lines[(doc, '100', '125')] = [_line('IT001', 5, 350)]
        c.receipts[('140', '100', doc)] = [(doc + 1, TODAY)]
        c.lines[(doc + 1, '140', '25')] = [_line('IT001', received_qty, 70 * received_qty)]
        return c

    def test_received_document_not_reread_between_full_passes(self):
        self.cmd._sync(self._conn(900500), 30, '', full=True)
        self.assertEqual(InTransitTransfer.objects.get().transit_status, 'received')

        conn = self._conn(900500)
        stats = self.cmd._sync(conn, 30, '', full=False)
        self.assertEqual(_softech_reads(conn), [])          # header scan only
        self.assertEqual(stats['final_cached'], 1)
        t = InTransitTransfer.objects.get()
        self.assertEqual((t.transit_status, t.erp_receipt_doc_number, t.item_count),
                         ('received', '900501', 1))

    def test_full_pass_rereads_final_documents(self):
        self.cmd._sync(self._conn(900510), 30, '', full=True)
        conn = self._conn(900510)
        self.cmd._sync(conn, 30, '', full=True)
        self.assertTrue(_softech_reads(conn))

    def test_mismatch_and_open_documents_still_reread(self):
        self.cmd._sync(self._conn(900520, received_qty=3), 30, '', full=True)
        self.assertEqual(InTransitTransfer.objects.get().transit_status, 'erp_mismatch')
        conn = self._conn(900520, received_qty=3)
        self.cmd._sync(conn, 30, '', full=False)
        self.assertTrue(_softech_reads(conn))

        open_conn = FakeConn()
        open_conn.headers = [_hdr(900530, '100', '140')]
        open_conn.lines[(900530, '100', '125')] = [_line('IT001', 5, 350)]
        self.cmd._sync(open_conn, 30, '', full=True)
        again = FakeConn()
        again.headers, again.lines = open_conn.headers, open_conn.lines
        self.cmd._sync(again, 30, '', full=False)
        self.assertTrue(_softech_reads(again))

    def test_header_changes_still_applied_from_the_cached_path(self):
        self.cmd._sync(self._conn(900540), 30, '', full=True)
        conn = self._conn(900540)
        conn.headers = [_hdr(900540, '100', '140', date=TODAY - datetime.timedelta(days=3), value=999)]
        self.cmd._sync(conn, 30, '', full=False)
        self.assertEqual(InTransitTransfer.objects.get().doc_value, Decimal('999'))

    def test_full_pass_due_once_a_day(self):
        old = mod._last_full_pass
        try:
            mod._last_full_pass = None
            self.assertTrue(mod._full_pass_due(now=1000.0))
            mod._last_full_pass = 1000.0
            self.assertFalse(mod._full_pass_due(now=1000.0 + 3600))
            self.assertTrue(mod._full_pass_due(now=1000.0 + mod.FINAL_RECHECK_HOURS * 3600))
        finally:
            mod._last_full_pass = old
