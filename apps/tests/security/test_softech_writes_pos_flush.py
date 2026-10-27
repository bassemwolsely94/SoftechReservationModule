"""
SOFTECH write safety — POS double post (Batch 2, P-11).

  * apps/sync/tasks.py defined _flush_pos_orders (and _reconcile_pos_orders) TWICE and
    registered each as TWO scheduler jobs (pos_orders_flush + pos_flush_queued), so two
    jobs flushed the same QUEUED orders every 2 minutes.
  * push_order checked the order's in-memory status and then saved PUSHING with a plain
    save: two callers holding the same QUEUED order both passed and both wrote the pending
    order into SOFTECH. The claim must be atomic (one conditional UPDATE in PostgreSQL).
"""
import ast
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from apps.pos_orders import writer
from apps.pos_orders.models import SoftechSalesOrder
from apps.tests.factories import make_branch

from .baseline import REPO_ROOT


class SchedulerRegistrationTests(SimpleTestCase):

    def test_each_pos_job_defined_and_registered_once(self):
        tree = ast.parse((REPO_ROOT / 'apps' / 'sync' / 'tasks.py').read_text(encoding='utf-8-sig'))
        for name in ('_flush_pos_orders', '_reconcile_pos_orders'):
            defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
            jobs = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and getattr(n.func, 'attr', '') == 'add_job'
                    and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == name]
            self.assertEqual((len(defs), len(jobs)), (1, 1), name)


class _FakeConn:
    def begin(self): pass
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass


@override_settings(POS_WRITER_ENABLED=True)
class ConcurrentPushTests(TestCase):

    def setUp(self):
        branch = make_branch()
        branch.db_host = '10.0.0.130'
        branch.save()
        self.order = SoftechSalesOrder.objects.create(
            branch=branch, softech_branchcode='130', store_code='130', softech_pic='130HD9668',
            status=SoftechSalesOrder.STATUS_QUEUED)
        self.writes = 0

    def _patches(self, during_write=None):
        test = self

        def fake_execute_write(conn, order, seller):
            test.writes += 1
            if during_write and test.writes == 1:     # the other caller arrives mid-write, once
                during_write()
            return {'ok': True, 'docnumber': 9000 + test.writes}

        return [mock.patch.object(writer, 'build_payload', return_value={}),
                mock.patch('apps.pos_orders.stock.check_item_restrictions', return_value=[]),
                mock.patch('apps.pos_orders.stock.enabled', return_value=False),
                mock.patch('config.sybase.get_branch_connection', return_value=_FakeConn()),
                mock.patch.object(writer, '_pending_docnumber_by_vf2', return_value=None),
                mock.patch.object(writer, '_execute_write', side_effect=fake_execute_write)]

    def test_two_callers_holding_the_same_queued_order_write_once(self):
        second = SoftechSalesOrder.objects.get(pk=self.order.pk)   # loaded BEFORE the first push
        results = {}

        def other_caller_pushes():                                # e.g. the other flush job
            results['second'] = writer.push_order(second, dry_run=False)

        ps = self._patches(during_write=other_caller_pushes)
        for p in ps:
            p.start()
        try:
            results['first'] = writer.push_order(self.order, dry_run=False)
        finally:
            for p in ps:
                p.stop()
        self.assertEqual(self.writes, 1, 'SOFTECH written twice for one order')
        self.assertTrue(results['first']['ok'])
        self.assertFalse(results['second'].get('wrote_to_softech'))

    def test_single_push_still_lands(self):
        ps = self._patches()
        for p in ps:
            p.start()
        try:
            res = writer.push_order(self.order, dry_run=False)
        finally:
            for p in ps:
                p.stop()
        self.assertTrue(res['ok'])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, SoftechSalesOrder.STATUS_PUSHED)
        self.assertEqual(self.writes, 1)
