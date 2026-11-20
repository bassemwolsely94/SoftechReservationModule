"""
C21 (audit doc 08): delivery orders stuck open here although SOFTECH already delivered (90) or
cancelled (100) them are closed by a deterministic rule — SOFTECH's own status, read only.
Switch off = dry run; every close is audited; cash-collection rows are never touched.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from apps.config.models import SystemSetting
from apps.delivery import stuck_close as sc
from apps.delivery.models import CashCollection, DeliveryOrder, DeliveryStatusLog
from apps.tests.factories import make_branch, make_branch2, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access


def _switch(on):
    SystemSetting.objects.update_or_create(key=sc.SWITCH_KEY, defaults={
        'value': 'true' if on else 'false', 'value_type': 'boolean', 'label': 'x', 'category': 'general'})


class StuckCloseRuleTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        self.old = timezone.now() - timedelta(hours=30)
        self.n = 1000

    def _order(self, status=DeliveryOrder.STATUS_READY, age=None, crm=True, **kw):
        self.n += 1
        return DeliveryOrder.objects.create(
            branch=self.branch, customer_name='عميل', status=status,
            ordered_at=age or self.old, softech_crm_branch='100' if crm else '',
            softech_crm_order_no=self.n if crm else None, total_value=Decimal('150'), **kw)

    def _fetch(self, statuses):
        """Fake SOFTECH: {order: orderstatus}. Records the keys it was asked for."""
        self.asked = []

        def fetch(keys):
            self.asked = list(keys)
            return {('100', o.softech_crm_order_no): st for o, st in statuses.items()}
        return fetch

    # ── the pure rule ──────────────────────────────────────────────────────────
    def test_verdict_rule(self):
        row = {'softech_crm_order_no': 5}
        self.assertEqual(sc.verdict(row, 90, False), sc.VERDICT_CLOSE)
        self.assertEqual(sc.verdict(row, 100, False), sc.VERDICT_CANCEL)
        for st in (None, 10, 30, 44, 50):
            self.assertEqual(sc.verdict(row, st, False), sc.VERDICT_OPEN)
        self.assertEqual(sc.verdict(row, sc._MISSING, False), sc.VERDICT_NOT_FOUND)
        self.assertEqual(sc.verdict(row, 90, True), sc.VERDICT_CASH)          # cash always wins
        self.assertEqual(sc.verdict({'softech_crm_order_no': None}, 90, False), sc.VERDICT_NO_KEY)

    # ── dry run (switch off, the default) ──────────────────────────────────────
    def test_switch_off_is_a_dry_run_that_changes_nothing(self):
        a = self._order()
        rec = sc.run(fetch=self._fetch({a: 90}))
        self.assertEqual(rec['mode'], 'dry_run')
        a.refresh_from_db()
        self.assertEqual(a.status, DeliveryOrder.STATUS_READY)
        self.assertFalse(DeliveryStatusLog.objects.filter(order=a).exists())
        self.assertEqual(rec['rows'], [{'id': a.id, 'verdict': sc.VERDICT_CLOSE, 'done': False, 'softech_status': 90}])
        self.assertEqual(sc.last_run()['counts'], {sc.VERDICT_CLOSE: 1})   # stored for the board

    # ── apply (switch on) ──────────────────────────────────────────────────────
    def test_apply_closes_delivered_cancels_cancelled_and_leaves_the_rest(self):
        _switch(True)
        done, gone, running, unknown = self._order(), self._order(), self._order(), self._order()
        young = self._order(age=timezone.now() - timedelta(hours=2))
        rec = sc.run(fetch=self._fetch({done: 90, gone: 100, running: 44, young: 90}))
        self.assertEqual(rec['mode'], 'apply')
        for o in (done, gone, running, unknown, young):
            o.refresh_from_db()
        self.assertEqual(done.status, DeliveryOrder.STATUS_CLOSED)
        self.assertIsNotNone(done.closed_at)
        self.assertEqual(done.softech_order_status, 90)
        self.assertEqual(gone.status, DeliveryOrder.STATUS_CANCELLED)
        self.assertEqual(running.status, DeliveryOrder.STATUS_READY)    # SOFTECH still running → exception
        self.assertEqual(unknown.status, DeliveryOrder.STATUS_READY)    # SOFTECH has no row → left open
        self.assertEqual(young.status, DeliveryOrder.STATUS_READY)      # younger than the threshold
        self.assertNotIn(('100', young.softech_crm_order_no), self.asked)
        self.assertEqual((rec['closed'], rec['cancelled']), (1, 1))

    def test_every_close_is_audited(self):
        _switch(True)
        a = self._order(status=DeliveryOrder.STATUS_OUT)
        sc.run(fetch=self._fetch({a: 90}))
        log = DeliveryStatusLog.objects.get(order=a)
        self.assertEqual((log.from_status, log.to_status, log.source),
                         (DeliveryOrder.STATUS_OUT, DeliveryOrder.STATUS_CLOSED, 'system'))
        self.assertIn('orderstatus=90', log.notes)

    def test_cash_collection_is_never_touched(self):
        _switch(True)
        a = self._order()
        cash = CashCollection.objects.create(order=a, expected_amount=Decimal('150'), collected_amount=Decimal('140'))
        before = CashCollection.objects.filter(pk=cash.pk).values().get()
        rec = sc.run(fetch=self._fetch({a: 90}))
        a.refresh_from_db()
        self.assertEqual(a.status, DeliveryOrder.STATUS_READY)
        self.assertEqual(rec['rows'][0]['verdict'], sc.VERDICT_CASH)
        self.assertNotIn(('100', a.softech_crm_order_no), self.asked)   # not even asked of SOFTECH
        self.assertEqual(CashCollection.objects.filter(pk=cash.pk).values().get(), before)

    def test_a_person_moving_the_order_first_wins(self):
        a = self._order()
        DeliveryOrder.objects.filter(pk=a.pk).update(status=DeliveryOrder.STATUS_ASSIGNED)
        self.assertFalse(sc._close_one(a.pk, DeliveryOrder.STATUS_READY, DeliveryOrder.STATUS_CLOSED, 90,
                                       timezone.now()))
        a.refresh_from_db()
        self.assertEqual(a.status, DeliveryOrder.STATUS_ASSIGNED)
        self.assertFalse(DeliveryStatusLog.objects.filter(order=a).exists())

    def test_second_run_closes_nothing_twice(self):
        _switch(True)
        a = self._order()
        sc.run(fetch=self._fetch({a: 90}))
        rec = sc.run(fetch=self._fetch({a: 90}))
        self.assertEqual(rec['closed'], 0)
        self.assertEqual(DeliveryStatusLog.objects.filter(order=a).count(), 1)

    def test_final_states_are_never_candidates(self):
        _switch(True)
        for st in (DeliveryOrder.STATUS_DELIVERED, DeliveryOrder.STATUS_CLOSED, DeliveryOrder.STATUS_CANCELLED,
                   DeliveryOrder.STATUS_RETURNED, DeliveryOrder.STATUS_FAILED, DeliveryOrder.STATUS_PARTIAL):
            self._order(status=st)
        self.assertEqual(sc.run(fetch=self._fetch({}))['checked'], 0)

    def test_sla_is_filled_only_when_the_owner_sets_minutes(self):
        _switch(True)
        a = self._order()
        sc.run(fetch=self._fetch({}))
        a.refresh_from_db()
        self.assertIsNone(a.sla_due_at)                                  # default 0 = off
        SystemSetting.objects.create(key=sc.SLA_KEY, value='90', value_type='integer', label='x', category='general')
        sc.run(fetch=self._fetch({}))
        a.refresh_from_db()
        self.assertEqual(a.sla_due_at, a.ordered_at + timedelta(minutes=90))

    def test_command_apply_refused_while_switch_off(self):
        with self.assertRaises(CommandError):
            call_command('delivery_stuck_autoclose', '--apply')


GRANTS = {'viewer': {'view'}, 'pharmacist': {'view', 'create', 'edit', 'approve', 'finalize'}}


class StuckOrdersEndpointTests(TestCase):
    URL = '/api/delivery/stuck-orders/'

    def setUp(self):
        module_access.clear_cache()
        for role, actions in GRANTS.items():
            for act in actions:
                RoleModuleAccess.objects.create(role=role, module='delivery', action=act)
        self.branch, self.other = make_branch(), make_branch2()
        old = timezone.now() - timedelta(hours=30)
        self.mine = DeliveryOrder.objects.create(branch=self.branch, customer_name='أ', ordered_at=old,
                                                 status=DeliveryOrder.STATUS_READY)
        self.theirs = DeliveryOrder.objects.create(branch=self.other, customer_name='ب', ordered_at=old,
                                                   status=DeliveryOrder.STATUS_READY)

    def tearDown(self):
        module_access.clear_cache()

    def test_needs_delivery_view(self):
        self.assertEqual(make_user('st_sales', role='salesperson', branch=self.branch)[2].get(self.URL).status_code, 403)
        self.assertEqual(make_user('st_view', role='viewer', branch=self.branch)[2].get(self.URL).status_code, 200)

    def test_read_only(self):
        c = make_user('st_ph', role='pharmacist', branch=self.branch)[2]
        self.assertEqual(c.post(self.URL, {}, format='json').status_code, 405)

    def test_branch_scoped(self):
        r = make_user('st_ph2', role='pharmacist', branch=self.branch)[2].get(self.URL)
        ids = [row['id'] for row in r.data['results']]
        self.assertIn(self.mine.id, ids)
        self.assertNotIn(self.theirs.id, ids)
        self.assertFalse(r.data['enabled'])
        self.assertEqual(r.data['min_age_hours'], sc.DEFAULT_MIN_AGE_HOURS)
