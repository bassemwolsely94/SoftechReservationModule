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


class ManualReceiptSurvivesSyncTests(TestCase):
    """A local «تسجيل الاستلام» stands until SOFTECH's own receipt (doc 25) appears;
    then SOFTECH's result wins and the lines are reconciled. (Bug: the next sync used
    to flip it back to in_transit, and the button then refused a second attempt.)"""

    def setUp(self):
        from django.utils import timezone
        self.hq   = make_branch('HQ', '100')
        self.giza = make_branch2('Giza', '140')
        self.cmd = Command()
        self.now = timezone.now()

    def _local(self, doc, days_ago=3):
        return InTransitTransfer.objects.create(
            erp_doc_number=str(doc), erp_supplying_branch_code='100',
            erp_receiving_branch_code='140', receiving_branch=self.giza,
            issue_date=TODAY - datetime.timedelta(days=days_ago),
            transit_status='received', manually_received_at=self.now,
            item_count=1,
            items_snapshot=[{'itemcode': 'IT001', 'itemname': 'X', 'qty': 5,
                             'unit_cost': 70, 'extended_cost': 350,
                             'batch': None, 'expiry': None, 'near_expiry': False}],
        )

    def test_no_doc25_keeps_local_receipt(self):
        self._local(901000)
        conn = FakeConn()
        conn.headers = [_hdr(901000, '100', '140', date=TODAY - datetime.timedelta(days=3))]
        conn.lines[(901000, '100', '125')] = [_line('IT001', 5, 350)]
        self.cmd._sync(conn, 30, '')
        t = InTransitTransfer.objects.get(erp_doc_number='901000')
        self.assertEqual(t.transit_status, 'received')
        self.assertIsNotNone(t.manually_received_at)
        self.assertEqual(t.erp_receipt_doc_number, '')

    def test_later_doc25_mismatch_wins(self):
        self._local(901100)
        conn = FakeConn()
        conn.headers = [_hdr(901100, '100', '140', date=TODAY - datetime.timedelta(days=3))]
        conn.lines[(901100, '100', '125')] = [_line('IT001', 5, 350)]
        conn.receipts[('140', '100', 901100)] = [(777, TODAY)]
        conn.lines[(777, '140', '25')] = [_line('IT001', 3, 210)]      # 2 short
        self.cmd._sync(conn, 30, '')
        t = InTransitTransfer.objects.get(erp_doc_number='901100')
        self.assertEqual(t.transit_status, 'erp_mismatch')
        self.assertEqual(t.erp_receipt_doc_number, '777')
        self.assertTrue(t.has_discrepancy)

    def test_wide_recheck_reconciles_locally_received(self):
        """An old doc outside the header window, received locally, is still picked up
        by the wide re-check when its 25 appears."""
        self._local(901200, days_ago=90)
        conn = FakeConn()
        conn.headers = []                                   # outside the window
        conn.receipts[('140', '100', 901200)] = [(888, TODAY)]
        conn.lines[(888, '140', '25')] = [_line('IT001', 5, 350)]
        self.cmd._sync(conn, 30, '')
        t = InTransitTransfer.objects.get(erp_doc_number='901200')
        self.assertEqual(t.transit_status, 'received')
        self.assertEqual(t.erp_receipt_doc_number, '888')
        self.assertFalse(t.has_discrepancy)


class FlakyConn(FakeConn):
    """Receipt (doc 25) queries raise like a dropped jConnect session.
    `reconnect()` heals it when `heal_on_reconnect` is set."""
    def __init__(self, heal_on_reconnect=False):
        super().__init__()
        self.broken = True
        self.heal_on_reconnect = heal_on_reconnect
        self.reconnects = 0

    def cursor(self):
        conn = self
        base = FakeCursor(self)
        real_execute = base.execute

        def execute(sql, params=None):
            s = ' '.join(sql.split()).lower()
            if conn.broken and "doccode = '25'" in s and 'docnumber2' in s:
                raise Exception('java.sql.SQLException: JZ0C0: Connection is already closed.')
            return real_execute(sql, params)
        base.execute = execute
        return base

    def reconnect(self):
        self.reconnects += 1
        if self.heal_on_reconnect:
            self.broken = False


class ReceiptCheckFailureTests(TestCase):
    """2026-10-30 bug: a dropped SOFTECH connection made every remaining receipt check
    return "not received" — received transfers flipped back to in_transit, their receipt
    data was wiped, and a daily alert fired for each (13,320 failures in 10 days)."""

    def setUp(self):
        self.hq   = make_branch('HQ', '100')
        self.giza = make_branch2('Giza', '140')
        self.cmd = Command()

    def _received(self, doc):
        return InTransitTransfer.objects.create(
            erp_doc_number=str(doc), erp_supplying_branch_code='100', supplying_branch=self.hq,
            erp_receiving_branch_code='140', receiving_branch=self.giza,
            issue_date=TODAY - datetime.timedelta(days=5), transit_status='received',
            erp_receipt_doc_number='555', erp_received_date=TODAY - datetime.timedelta(days=4),
            item_count=1,
            items_snapshot=[{'itemcode': 'IT001', 'itemname': 'X', 'qty': 5,
                             'unit_cost': 70, 'extended_cost': 350,
                             'batch': None, 'expiry': None, 'near_expiry': False}],
        )

    def test_failed_check_never_unreceives(self):
        self._received(903000)
        conn = FlakyConn()
        conn.headers = [_hdr(903000, '100', '140', date=TODAY - datetime.timedelta(days=5))]
        conn.lines[(903000, '100', '125')] = [_line('IT001', 5, 350)]

        stats = self.cmd._sync(conn, 30, '')

        t = InTransitTransfer.objects.get(erp_doc_number='903000')
        self.assertEqual(t.transit_status, 'received')
        self.assertEqual(t.erp_receipt_doc_number, '555')
        self.assertIsNotNone(t.erp_received_date)
        self.assertEqual(stats['receipt_check_failed'], 1)

    def test_reconnects_and_retries_the_check(self):
        conn = FlakyConn(heal_on_reconnect=True)
        conn.headers = [_hdr(903100, '100', '140', date=TODAY - datetime.timedelta(days=3))]
        conn.lines[(903100, '100', '125')] = [_line('IT001', 5, 350)]
        conn.receipts[('140', '100', 903100)] = [(556, TODAY)]
        conn.lines[(556, '140', '25')] = [_line('IT001', 5, 350)]

        stats = self.cmd._sync(conn, 30, '')

        t = InTransitTransfer.objects.get(erp_doc_number='903100')
        self.assertEqual(t.transit_status, 'received')
        self.assertEqual(t.erp_receipt_doc_number, '556')
        self.assertEqual(conn.reconnects, 1)
        self.assertEqual(stats['receipt_check_failed'], 0)

    def _overdue(self, doc):
        return InTransitTransfer.objects.create(
            erp_doc_number=str(doc), erp_supplying_branch_code='100', supplying_branch=self.hq,
            erp_receiving_branch_code='140', receiving_branch=self.giza,
            issue_date=TODAY - datetime.timedelta(days=20), transit_status='in_transit',
            days_in_transit=20, item_count=1,
        )

    def test_no_alert_when_receipt_check_failed(self):
        from apps.notifications.models import Notification
        from .factories import make_admin
        make_admin('tr_alert_admin')
        self._overdue(903200)
        conn = FlakyConn()
        conn.headers = [_hdr(903200, '100', '140', date=TODAY - datetime.timedelta(days=20))]
        conn.lines[(903200, '100', '125')] = [_line('IT001', 5, 350)]

        self.cmd._sync(conn, 30, '')

        self.assertEqual(
            Notification.objects.filter(notification_type='transit_critical').count(), 0)

    def test_alert_still_fires_when_verified_unreceived(self):
        """Control: a successful check with no receipt is a real stuck transfer."""
        from apps.notifications.models import Notification
        from .factories import make_admin
        make_admin('tr_alert_admin2')
        self._overdue(903300)
        conn = FakeConn()
        conn.headers = [_hdr(903300, '100', '140', date=TODAY - datetime.timedelta(days=20))]
        conn.lines[(903300, '100', '125')] = [_line('IT001', 5, 350)]

        self.cmd._sync(conn, 30, '')

        self.assertGreater(
            Notification.objects.filter(notification_type='transit_critical').count(), 0)

    def test_stops_reconnecting_once_softech_stays_down(self):
        """A dead network must not cost a reconnect attempt per open transfer."""
        conn = FlakyConn()                       # never heals
        conn.headers = [_hdr(904000 + i, '100', '140') for i in range(6)]
        for i in range(6):
            conn.lines[(904000 + i, '100', '125')] = [_line('IT001', 1, 70)]

        stats = self.cmd._sync(conn, 30, '')

        self.assertEqual(stats['receipt_check_failed'], 6)
        self.assertLessEqual(conn.reconnects, 3)

    def test_old_open_transfer_check_failure_keeps_it_unalerted(self):
        """Wide re-check (outside the header window) obeys the same rule."""
        from apps.notifications.models import Notification
        from .factories import make_admin
        make_admin('tr_alert_admin3')
        self._overdue(903400)
        conn = FlakyConn()
        conn.headers = []                       # outside the 30-day header window

        stats = self.cmd._sync(conn, 30, '')

        self.assertEqual(stats['receipt_check_failed'], 1)
        self.assertEqual(
            Notification.objects.filter(notification_type='transit_critical').count(), 0)


class LocalReceiptAlertTests(TestCase):
    """A local receipt not confirmed in SOFTECH (no doc 25) after N days alerts the
    receiving branch once a day; confirmed / recent / in-transit ones don't."""

    def setUp(self):
        from django.utils import timezone
        self.hq = make_branch('HQ', '100')
        self.giza = make_branch2('Giza', '140')
        self.cmd = Command()
        self.now = timezone.now()

    def _t(self, doc, days_ago, received_date=None, status='received'):
        return InTransitTransfer.objects.create(
            erp_doc_number=str(doc), erp_supplying_branch_code='100', supplying_branch=self.hq,
            erp_receiving_branch_code='140', receiving_branch=self.giza,
            issue_date=TODAY - datetime.timedelta(days=days_ago + 2), transit_status=status,
            manually_received_at=self.now - datetime.timedelta(days=days_ago),
            erp_received_date=received_date, item_count=1)

    def test_alert_once_a_day_only_for_unconfirmed_old(self):
        from apps.transits.models import InTransitNote
        old = self._t(902000, days_ago=4)
        self._t(902001, days_ago=1)                                  # too recent
        self._t(902002, days_ago=5, received_date=TODAY)             # SOFTECH confirmed
        self.assertEqual(self.cmd._fire_local_receipt_alerts(), 1)
        self.assertEqual(self.cmd._fire_local_receipt_alerts(), 0)   # same day → no repeat
        old.refresh_from_db()
        self.assertEqual(old.last_alert_level, 'local')
        self.assertEqual(InTransitNote.objects.filter(transfer=old, note_type='alert').count(), 1)

    def test_setting_controls_threshold_and_off(self):
        from apps.config.models import SystemSetting
        self._t(902100, days_ago=4)
        SystemSetting.objects.update_or_create(key='transit_local_receipt_alert_days',
                                               defaults={'value': '0', 'value_type': 'integer'})
        self.assertEqual(self.cmd._fire_local_receipt_alerts(), 0)
        SystemSetting.objects.filter(key='transit_local_receipt_alert_days').update(value='7')
        self.assertEqual(self.cmd._fire_local_receipt_alerts(), 0)
        SystemSetting.objects.filter(key='transit_local_receipt_alert_days').update(value='2')
        self.assertEqual(self.cmd._fire_local_receipt_alerts(), 1)

    def test_grid_filter_awaiting_erp(self):
        from .factories import make_admin
        self._t(902200, days_ago=4)
        self._t(902201, days_ago=4, received_date=TODAY)
        _, _, client = make_admin('tr_admin_f')
        r = client.get('/api/transits/?awaiting_erp=1')
        self.assertEqual(r.status_code, 200)
        rows = r.json()['results'] if isinstance(r.json(), dict) else r.json()
        self.assertEqual([x['erp_doc_number'] for x in rows], ['902200'])
