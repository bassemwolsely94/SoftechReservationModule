"""
apps/tests/test_pos_checkout_concurrency.py — D-18 double submit, with real threads (doc 39 §4.3 cases 1–3).

TransactionTestCase so each thread has its own committed view of the database, as two browser tabs
would. SOFTECH is replaced at the writer's connection boundary; _execute_write is slowed down so the
second request arrives while the first is inside the write. Run serially (never --parallel).
"""
import threading
import time
import uuid
from unittest import mock

from django.db import connection
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.pos_orders import writer
from apps.pos_orders.models import SoftechSalesOrder
from .factories import make_branch, make_call_center
from .test_pos_checkout import CHECKOUT, _checkout


@override_settings(POS_SERVER_CHECKOUT=True, WRITER_INSTANCE=True, POS_WRITER_ENABLED=True,
                   POS_BLOCK_POINTS_SALES=False)
class CheckoutDoubleSubmitTests(TransactionTestCase):

    def setUp(self):
        self.branch = make_branch()
        self.branch.db_host = '10.0.0.9'
        self.branch.save()
        self.user, _, self.cc = make_call_center('cc_ck_threads')
        self.calls = []
        for p in (mock.patch('config.sybase.get_branch_connection', return_value=mock.MagicMock()),
                  mock.patch.object(writer, '_pending_docnumber_by_vf2', return_value=None),
                  mock.patch('apps.pos_orders.stock.check_item_restrictions', return_value=[]),
                  mock.patch('apps.pos_orders.stock.enabled', return_value=False),
                  mock.patch('apps.pos_orders.views.validate_discount_authority', return_value=[]),
                  mock.patch.object(writer, '_execute_write', side_effect=self._slow_write)):
            p.start()
            self.addCleanup(p.stop)

    def _slow_write(self, conn, order, seller):
        self.calls.append(order.pk)
        time.sleep(0.6)
        return {'ok': True, 'docnumber': 480000 + len(self.calls)}

    def _post_in_threads(self, bodies):
        out = [None] * len(bodies)

        def run(i, body):
            try:
                client = APIClient()                    # one client per "browser tab"
                client.force_authenticate(user=self.user)
                out[i] = client.post(CHECKOUT, body, format='json')
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(i, b)) for i, b in enumerate(bodies)]
        for t in threads:
            t.start()
            time.sleep(0.05)
        for t in threads:
            t.join(30)
        return out

    def test_double_click_posts_once(self):
        token = str(uuid.uuid4())
        body = _checkout(self.branch.id, token=token, mode='live', confirm=True)
        r1, r2 = self._post_in_threads([body, body])
        codes = sorted([r1.status_code, r2.status_code])
        self.assertEqual(codes, [200, 202], (r1.data, r2.data))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(SoftechSalesOrder.objects.filter(client_token=token).count(), 1)
        # the cashier presses again afterwards → the docnumber, no second write
        r3 = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r3.status_code, 200, r3.data)
        self.assertTrue(r3.data['replayed'])
        self.assertEqual(len(self.calls), 1)

    def test_same_token_other_basket_in_parallel_never_overwrites(self):
        token = str(uuid.uuid4())
        a = _checkout(self.branch.id, token=token, mode='live', confirm=True)
        b = _checkout(self.branch.id, token=token, mode='live', confirm=True)
        b['lines'][0]['qty'] = 2
        r1, r2 = self._post_in_threads([a, b])
        self.assertEqual(len(self.calls), 1)
        self.assertIn(r2.status_code, (202, 409), r2.data)
        o = SoftechSalesOrder.objects.get(client_token=token)
        self.assertEqual(o.lines.order_by('id').first().qty, 1)

    def test_checkout_racing_the_flush_job_writes_once(self):
        """Phase B vs the flush job on the same order: the writer's PUSHING claim (P-11) lets one in."""
        token = str(uuid.uuid4())
        dry = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=token), format='json')
        self.assertEqual(dry.status_code, 200, dry.data)
        order_id = dry.data['order_id']
        results = {}

        def flush():
            try:
                results['flush'] = writer.push_order(SoftechSalesOrder.objects.get(pk=order_id), dry_run=False)
            finally:
                connection.close()

        t = threading.Thread(target=flush)
        live = _checkout(self.branch.id, token=token, mode='live', confirm=True)
        t.start()
        time.sleep(0.1)
        r = self.cc.post(CHECKOUT, live, format='json')
        t.join(30)
        self.assertEqual(len(self.calls), 1, (r.data, results))
        self.assertEqual(SoftechSalesOrder.objects.get(pk=order_id).status, 'pushed')
