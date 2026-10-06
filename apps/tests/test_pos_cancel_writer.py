"""
apps/tests/test_pos_cancel_writer.py — Wave 3 inc3.

The batch writer that feeds OUR POS item-selection telemetry into SOFTECH pos_cancel:
native row shape, the sold-exclusion rule, dry-run safety, and the crash-safe idempotency
(claim-before-write / un-claim-on-failure → never double-post). The Sybase insert is mocked;
no live SOFTECH contact.
"""
import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.pos_orders.models import (
    SoftechSalesOrder, SoftechSalesOrderLine, PosSelectionEvent,
)
from apps.pos_orders import pos_cancel_writer as PCW
from .factories import make_branch


def _evt(branch, *, code='96690', etype='add', token=None, ago_min=600, qty=1, list_price='28.5'):
    e = PosSelectionEvent.objects.create(
        cart_token=token, branch=branch, softech_branchcode=branch.softech_branch_id,
        doc_kind='sale', event_type=etype, item_code=code, item_name='ASPIRIN',
        itemsaleprice=list_price, transprice=list_price, transqty=(0 if etype == 'clear' else qty),
        transprice_total=(0 if etype == 'clear' else qty) and (float(list_price) * qty),
        custcode='1510', seller_usercode='1509', occurred_at=timezone.now() - timedelta(minutes=ago_min),
    )
    return e


def _sold_order(branch, token, code):
    o = SoftechSalesOrder.objects.create(
        branch=branch, softech_branchcode=branch.softech_branch_id, store_code='B01',
        channel='cash', doc_kind='sale', customer_name='T', client_token=token,
        status=SoftechSalesOrder.STATUS_SETTLED)
    SoftechSalesOrderLine.objects.create(order=o, item=None, softech_itemcode=code,
                                         item_name='X', qty=1, item_sale_price=28.5)
    return o


class RowShapeTests(TestCase):
    def test_native_row_shape_and_defaults(self):
        br = make_branch()
        e = _evt(br, code='33555', qty=1, list_price='311')
        e.custcode = ''; e.seller_usercode = ''      # exercise the '0' defaults
        row = PCW._row_from_event(e)
        self.assertEqual(row['branchcode'], br.softech_branch_id)
        self.assertEqual(row['doccode'], '115')       # sale
        self.assertEqual(row['itemcode'], '33555')
        self.assertEqual(row['custcode'], '0')        # NOT NULL default
        self.assertEqual(row['usercode'], '0')
        self.assertEqual(len(row['trans_time']), 19)  # 'YYYY-MM-DD HH:MM:SS'
        self.assertTrue(row['trans_date'].endswith('00:00:00'))
        self.assertEqual(set(row), {'branchcode', 'doccode', 'itemcode', 'itemsaleprice',
                                    'transprice', 'transqty', 'transprice_total', 'custcode',
                                    'usercode', 'trans_time', 'trans_date', 'mitemname'})

    def test_return_maps_doccode_30(self):
        e = _evt(make_branch()); e.doc_kind = 'return'
        self.assertEqual(PCW._row_from_event(e)['doccode'], '30')


class ExclusionAndDryRunTests(TestCase):
    def test_dry_run_excludes_sold_and_never_mutates(self):
        br = make_branch()
        sold_tok = uuid.uuid4()
        _sold_order(br, sold_tok, '96690')
        e_sold = _evt(br, code='96690', token=sold_tok)          # add that WAS sold → excluded
        e_lost = _evt(br, code='77777', token=uuid.uuid4())       # add, cart never reached → written
        e_clear = _evt(br, code='96690', etype='clear', token=sold_tok)  # clear → always written
        s = PCW.write_pos_cancel_batch(dry_run=True, min_age_minutes=0)
        self.assertEqual(s['candidates'], 3)
        self.assertEqual(s['skipped_sold'], 1)
        self.assertTrue(s['dry_run'])
        self.assertEqual(s['branches'][br.softech_branch_id]['would_write'], 2)  # lost add + clear
        for e in (e_sold, e_lost, e_clear):
            e.refresh_from_db()
            self.assertIsNone(e.softech_written_at)              # dry-run mutates nothing

    def test_min_age_excludes_recent(self):
        br = make_branch()
        _evt(br, ago_min=5)                                       # too fresh
        s = PCW.write_pos_cancel_batch(dry_run=True, min_age_minutes=360)
        self.assertEqual(s['candidates'], 0)


class IngestEndpointTests(TestCase):
    def setUp(self):
        from .factories import make_pharmacist
        self.br = make_branch()
        user, profile, self.client = make_pharmacist(branch=self.br)
        profile.softech_user_id = '1509'; profile.save()

    def test_capture_events_server_attributed(self):
        r = self.client.post('/api/pos-orders/selection-events/', {
            'branch': self.br.id, 'cart_token': str(uuid.uuid4()),
            'events': [
                {'item_code': '96690', 'item_name': 'ASPIRIN', 'event_type': 'add',
                 'itemsaleprice': 28.5, 'transprice': 28.5, 'transqty': 1, 'transprice_total': 28.5,
                 'doc_kind': 'sale', 'custcode': '1510', 'occurred_at': '2026-09-14T08:34:41Z'},
                {'item_code': '96690', 'event_type': 'clear', 'transqty': 0},
                {'item_code': '', 'event_type': 'add'},        # no code → skipped
            ],
        }, format='json')
        self.assertEqual(r.status_code, 202)
        self.assertEqual(r.json()['captured'], 2)              # the empty-code row dropped
        rows = PosSelectionEvent.objects.filter(branch=self.br)
        self.assertEqual(rows.count(), 2)
        add = rows.get(event_type='add')
        self.assertEqual(add.seller_usercode, '1509')          # server-set, not client-spoofable
        self.assertEqual(add.softech_branchcode, self.br.softech_branch_id)
        self.assertEqual(rows.get(event_type='clear').transqty, 0)


@override_settings(POS_CANCEL_WRITE_ENABLED=True)
class LiveWritePathTests(TestCase):
    def _fake_conn(self):
        c = MagicMock()
        c.begin.return_value = None; c.commit.return_value = None; c.rollback.return_value = None
        return c

    def test_live_success_marks_written_and_inserts(self):
        br = make_branch()
        tok = uuid.uuid4(); _sold_order(br, tok, '96690')
        e_sold = _evt(br, code='96690', token=tok)
        e_lost = _evt(br, code='77777')
        inserts = []
        with patch('config.sybase.get_branch_connection', return_value=self._fake_conn()), \
             patch('apps.pos_orders.writer._exec_insert',
                   side_effect=lambda conn, table, row: inserts.append((table, row))):
            s = PCW.write_pos_cancel_batch(dry_run=False, min_age_minutes=0)
        self.assertFalse(s['dry_run'])
        self.assertEqual(s['written'], 1)          # only the lost add
        self.assertEqual(s['skipped_sold'], 1)
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0][0], 'pos_cancel')
        e_lost.refresh_from_db(); e_sold.refresh_from_db()
        self.assertIsNotNone(e_lost.softech_written_at)          # written
        self.assertIsNotNone(e_sold.softech_written_at)          # processed (skip:sold)
        self.assertEqual(e_sold.write_error, 'skip:sold')

    def test_live_failure_unclaims_never_double_posts(self):
        br = make_branch()
        e = _evt(br, code='77777')
        with patch('config.sybase.get_branch_connection', return_value=self._fake_conn()), \
             patch('apps.pos_orders.writer._exec_insert', side_effect=RuntimeError('ASE down')):
            s = PCW.write_pos_cancel_batch(dry_run=False, min_age_minutes=0)
        self.assertEqual(s['written'], 0)
        e.refresh_from_db()
        self.assertIsNone(e.softech_written_at)                  # UN-claimed → retried, no dup
        self.assertIn('ASE down', e.write_error)
