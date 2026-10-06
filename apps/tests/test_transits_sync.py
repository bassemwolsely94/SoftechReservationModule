"""
apps/tests/test_transits_sync.py

sync_in_transit correctness — the docnumber-collision fix (2026-07-20):
  • receiving branch comes from the 125 header's cust_branch_code,
    NEVER inferred from same-numbered documents at other branches
  • receipt = doccode-25 doc at the destination linked via docnumber2
    (own docnumber), reconciliation uses the 25-doc's own lines
  • stale false-receipt data recorded by the old heuristic is cleared
  • upsert identity = (docnumber, supplying branch)

Uses a scripted fake Sybase connection — no network access.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from apps.transits.management.commands.sync_in_transit import Command
from apps.transits.models import InTransitTransfer
from .factories import make_branch, make_branch2

TODAY = datetime.date.today()


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._rows = []

    def execute(self, sql, params=None):
        s = ' '.join(sql.split()).lower()
        params = params or []
        self.conn.queries.append((s, list(params)))

        if 'from softechdb9.dbo.stktransm' in s and "doccode = '125'" in s:
            self._rows = self.conn.headers
        elif "doccode = '25'" in s and 'docnumber2' in s:
            key = (str(params[0]), str(params[1]), int(params[2]))
            self._rows = self.conn.receipts.get(key, [])
        elif 'from softechdb9.dbo.stktrans ' in s:
            key = (int(params[0]), str(params[1]), str(params[2]))
            self._rows = self.conn.lines.get(key, [])
        else:
            self._rows = []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class FakeConn:
    """headers / receipts / lines are scripted per test."""
    def __init__(self):
        self.headers  = []   # stktransm 125 rows
        self.receipts = {}   # (recv, supply, docnum) → [(receipt_doc, docdate)]
        self.lines    = {}   # (docnum, branch, doccode) → item rows
        self.queries  = []

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        pass


def _hdr(doc, supply, dest, date=TODAY, value=100):
    # (docnumber, doccode, branchcode, docdate, docvalue, usercode, storecode, cust_branch_code)
    return (doc, '125', supply, date, value, '64', supply, dest)


def _line(code, qty, cost):
    # (itemcode, transqty, transprice_total, storecode, trans_time, expiry, batch)
    return (code, qty, cost, '100', None, None, None)


class SyncReceiptFixTests(TestCase):

    def setUp(self):
        self.hq   = make_branch('HQ', '100')
        self.giza = make_branch2('Giza', '140')
        make_branch('Qolali-cancelled', '110')
        self.cmd = Command()

    def _run(self, conn):
        return self.cmd._sync(conn, 30, '')

    def test_receiver_from_header_not_collisions(self):
        """Destination = cust_branch_code; colliding docs can't pollute it."""
        conn = FakeConn()
        conn.headers = [_hdr(900100, '100', '140')]
        conn.lines[(900100, '100', '125')] = [_line('IT001', 5, 350)]
        # NOTE: no receipt scripted; the fake would also return nothing for the
        # old DISTINCT-branches query — the point is what gets STORED:
        stats = self._run(conn)
        self.assertEqual(stats['created'], 1)

        t = InTransitTransfer.objects.get(erp_doc_number='900100')
        self.assertEqual(t.erp_receiving_branch_code, '140')
        self.assertEqual(t.receiving_branch, self.giza)
        self.assertEqual(t.transit_status, 'in_transit')
        self.assertEqual(t.erp_receipt_doc_number, '')
        self.assertIsNone(t.erp_received_date)

        # every stktrans lines query carried a doccode filter
        line_queries = [p for s, p in conn.queries
                        if 'from softechdb9.dbo.stktrans ' in s]
        self.assertTrue(line_queries)
        for params in line_queries:
            self.assertIn(params[2], ('125', '25'))

    def test_receipt_via_docnumber2_link(self):
        """Receipt found → status received, reconciliation vs the 25-doc lines."""
        recv_date = TODAY - datetime.timedelta(days=1)
        conn = FakeConn()
        conn.headers = [_hdr(900200, '100', '140',
                             date=TODAY - datetime.timedelta(days=3))]
        conn.lines[(900200, '100', '125')] = [_line('IT001', 5, 350)]
        conn.receipts[('140', '100', 900200)] = [(555, recv_date)]
        conn.lines[(555, '140', '25')] = [_line('IT001', 5, 350)]

        self._run(conn)
        t = InTransitTransfer.objects.get(erp_doc_number='900200')
        self.assertEqual(t.transit_status, 'received')
        self.assertEqual(t.erp_receipt_doc_number, '555')
        self.assertEqual(t.erp_received_date, recv_date)
        self.assertFalse(t.has_discrepancy)

    def test_receipt_qty_mismatch_flagged(self):
        conn = FakeConn()
        conn.headers = [_hdr(900300, '100', '140',
                             date=TODAY - datetime.timedelta(days=3))]
        conn.lines[(900300, '100', '125')] = [_line('IT001', 5, 350)]
        conn.receipts[('140', '100', 900300)] = [(556, TODAY)]
        conn.lines[(556, '140', '25')] = [_line('IT001', 3, 210)]   # short 2

        self._run(conn)
        t = InTransitTransfer.objects.get(erp_doc_number='900300')
        self.assertEqual(t.transit_status, 'erp_mismatch')
        self.assertTrue(t.has_discrepancy)
        self.assertEqual(t.reconciliation['qty_diffs'][0]['diff'], -2)

    def test_stale_false_receipt_is_cleared(self):
        """
        A record polluted by the old heuristic (wrong receiver 110, fake
        'received' + garbage reconciliation) self-corrects on re-sync.
        """
        InTransitTransfer.objects.create(
            erp_doc_number='900400',
            erp_supplying_branch_code='100',
            erp_receiving_branch_code='110',            # wrong (collision)
            issue_date=TODAY - datetime.timedelta(days=5),
            transit_status='erp_mismatch',              # fake mismatch
            erp_received_date=TODAY - datetime.timedelta(days=4),
            received_items_snapshot=[{'itemcode': 'JUNK', 'qty': 9}],
            reconciliation={'has_discrepancy': True},
            has_discrepancy=True,
            item_count=1,
            items_snapshot=[{'itemcode': 'IT001', 'itemname': 'X', 'qty': 5,
                             'unit_cost': 70, 'extended_cost': 350,
                             'batch': None, 'expiry': None, 'near_expiry': False}],
        )

        conn = FakeConn()
        conn.headers = [_hdr(900400, '100', '140',
                             date=TODAY - datetime.timedelta(days=5))]
        conn.lines[(900400, '100', '125')] = [_line('IT001', 5, 350)]
        # no real receipt exists

        self._run(conn)
        t = InTransitTransfer.objects.get(erp_doc_number='900400')
        self.assertEqual(t.erp_receiving_branch_code, '140')   # corrected
        self.assertEqual(t.receiving_branch, self.giza)
        self.assertEqual(t.transit_status, 'in_transit')       # un-received
        self.assertIsNone(t.erp_received_date)
        self.assertEqual(t.received_items_snapshot, [])
        self.assertEqual(t.reconciliation, {})
        self.assertFalse(t.has_discrepancy)

    def test_multi_batch_lines_are_aggregated(self):
        """
        One item spanning several stktrans rows (batches) must sum into a
        single snapshot entry — not collapse to the first row (doc 103289 bug:
        3 pens across 2 batches were shown as 1).
        """
        conn = FakeConn()
        conn.headers = [_hdr(900600, '100', '140', value=49949.99)]
        conn.lines[(900600, '100', '125')] = [
            # (itemcode, qty, line_cost, store, time, expiry, batch)
            ('129774', 1, 16649.9963, '100', None, '2028-02-02', None),
            ('129774', 2, 33299.9926, '100', None, '2028-02-28', None),
        ]
        self._run(conn)

        t = InTransitTransfer.objects.get(erp_doc_number='900600')
        self.assertEqual(t.item_count, 1)                 # one DISTINCT item
        self.assertEqual(float(t.total_quantity), 3.0)    # 1 + 2 pens
        line = t.items_snapshot[0]
        self.assertEqual(line['itemcode'], '129774')
        self.assertEqual(line['qty'], 3.0)
        self.assertAlmostEqual(line['extended_cost'], 49949.9889, places=3)
        # earliest expiry kept for FEFO; both batches recorded IN FULL so the
        # detail view can list them on separate lines (SOFTECH-style)
        self.assertEqual(line['expiry'], '2028-02-02')
        self.assertEqual(len(line['batches']), 2)
        b0, b1 = line['batches']
        self.assertEqual((b0['qty'], b0['expiry']), (1.0, '2028-02-02'))
        self.assertEqual((b1['qty'], b1['expiry']), (2.0, '2028-02-28'))
        self.assertAlmostEqual(b0['extended_cost'], 16649.9963, places=3)
        self.assertAlmostEqual(b1['extended_cost'], 33299.9926, places=3)
        # aggregate == sum of batches
        self.assertAlmostEqual(
            line['extended_cost'],
            b0['extended_cost'] + b1['extended_cost'], places=3)

    def test_same_docnumber_from_two_branches_are_two_records(self):
        """Branch sequences collide — identity must include the supplier."""
        conn = FakeConn()
        conn.headers = [
            _hdr(900500, '100', '140'),
            _hdr(900500, '140', '100'),    # same number, different supplier
        ]
        conn.lines[(900500, '100', '125')] = [_line('IT001', 5, 350)]
        conn.lines[(900500, '140', '125')] = [_line('IT002', 2, 60)]

        stats = self._run(conn)
        self.assertEqual(stats['created'], 2)
        self.assertEqual(
            InTransitTransfer.objects.filter(erp_doc_number='900500').count(), 2)
        by_supplier = {
            t.erp_supplying_branch_code: t
            for t in InTransitTransfer.objects.filter(erp_doc_number='900500')
        }
        self.assertEqual(by_supplier['100'].erp_receiving_branch_code, '140')
        self.assertEqual(by_supplier['140'].erp_receiving_branch_code, '100')
