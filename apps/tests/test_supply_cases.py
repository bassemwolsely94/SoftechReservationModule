"""
Phase-4 tests for SupplyCase lifecycle, daily follow-up queue, alerts and RBAC (doc 24 §16/
§26/§27/§31/§39/§40).
"""
from datetime import date

from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from apps.supply import cases as svc
from apps.supply import demand_signals as ds
from apps.supply.models import (AvailabilityBatch, AvailabilityLine, DemandSignal,
                                 SupplyCase)
from .factories import make_user

S = SupplyCase


def _run():
    from apps.purchasing.models import DemandCalculationRun
    return DemandCalculationRun.objects.create(status='success', calc_date=date.today())


def _metric(run, item, branch, *, stock=0, safety=0, gap=0, in_transit=0):
    from apps.purchasing.models import ItemDemandMetrics
    return ItemDemandMetrics.objects.create(
        run=run, item=item, branch=branch, calc_date=date.today(),
        current_stock=stock, safety_stock=safety, gap=gap, in_transit_qty=in_transit)


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.catalog.models import Item
        from apps.branches.models import Branch
        cls.item = Item.objects.create(softech_id='600001', name='RECORMON 4000', is_active=True)
        cls.branch = Branch.objects.create(softech_branch_id='130', name='B130')
        cls.donor = Branch.objects.create(softech_branch_id='140', name='B140')


# ── Lifecycle ──────────────────────────────────────────────────────────────────

class EvaluateCaseTests(_Base):
    def test_opens_case_when_net_requirement_exists_and_audits(self):
        from apps.audit.models import AuditLog
        _metric(_run(), self.item, self.branch, stock=0, gap=8)
        r = svc.evaluate_case(self.item.id, self.branch.id)
        self.assertEqual(r['event'], 'opened')
        c = r['case']
        self.assertEqual(c.status, S.STATUS_DETECTED)
        self.assertEqual(float(c.required_qty), 8.0)
        self.assertTrue(AuditLog.objects.filter(action='supply_case_opened',
                                                object_id=str(c.pk)).exists())

    def test_no_case_when_nothing_is_needed(self):
        _metric(_run(), self.item, self.branch, stock=20, gap=0)
        r = svc.evaluate_case(self.item.id, self.branch.id)
        self.assertEqual(r['event'], 'none')
        self.assertFalse(SupplyCase.objects.exists())

    def test_reevaluation_reuses_the_same_case_and_moves_to_searching(self):
        _metric(_run(), self.item, self.branch, gap=8)
        c1 = svc.evaluate_case(self.item.id, self.branch.id)['case']
        r2 = svc.evaluate_case(self.item.id, self.branch.id)
        self.assertEqual(r2['case'].pk, c1.pk)
        self.assertEqual(r2['case'].status, S.STATUS_SEARCHING)
        self.assertEqual(SupplyCase.objects.count(), 1)

    def test_internal_surplus_moves_case_to_awaiting_decision(self):
        run = _run()
        _metric(run, self.item, self.branch, stock=0, gap=5)
        _metric(run, self.item, self.donor, stock=9, safety=2)       # surplus 7
        c = svc.evaluate_case(self.item.id, self.branch.id)['case']
        self.assertEqual(c.status, S.STATUS_AWAITING_DECISION)
        self.assertEqual(float(c.internal_cover), 5.0)

    def test_confirmed_supplier_offer_marks_availability_found(self):
        _metric(_run(), self.item, self.branch, gap=5)
        b = AvailabilityBatch.objects.create(source='whatsapp', supplier_name='X')
        line = AvailabilityLine.objects.create(batch=b, raw_text='recormon 4000 10',
                                               item=self.item, is_confirmed=True,
                                               supplier_qty=10, price=500)
        c = svc.evaluate_case(self.item.id, self.branch.id)['case']
        self.assertEqual(c.status, S.STATUS_AVAILABILITY_FOUND)
        self.assertTrue(c.has_availability)
        self.assertIn(line, c.availability_lines.all())

    def test_weak_unconfirmed_match_is_not_treated_as_availability(self):
        _metric(_run(), self.item, self.branch, gap=5)
        b = AvailabilityBatch.objects.create(source='whatsapp')
        AvailabilityLine.objects.create(batch=b, raw_text='recor?', item=self.item,
                                        is_confirmed=False, match_score=0.4)
        c = svc.evaluate_case(self.item.id, self.branch.id)['case']
        self.assertFalse(c.has_availability)

    def test_auto_resolves_only_when_need_is_gone(self):
        from apps.audit.models import AuditLog
        m = _metric(_run(), self.item, self.branch, gap=8)
        c = svc.evaluate_case(self.item.id, self.branch.id)['case']
        m.gap = 0
        m.current_stock = 12
        m.save()
        r = svc.evaluate_case(self.item.id, self.branch.id)
        self.assertEqual(r['event'], 'closed')
        c.refresh_from_db()
        self.assertEqual(c.status, S.STATUS_FULFILLED)
        self.assertIsNotNone(c.closed_at)
        self.assertTrue(c.close_reason)
        self.assertTrue(AuditLog.objects.filter(action='supply_case_closed',
                                                object_id=str(c.pk)).exists())

    def test_human_status_is_never_overwritten_by_reevaluation(self):
        m = _metric(_run(), self.item, self.branch, gap=8)
        c = svc.evaluate_case(self.item.id, self.branch.id)['case']
        svc.transition(c, S.STATUS_ORDERED)
        m.gap = 6
        m.save()
        r = svc.evaluate_case(self.item.id, self.branch.id)
        self.assertEqual(r['case'].status, S.STATUS_ORDERED)     # kept
        self.assertEqual(float(r['case'].required_qty), 6.0)     # numbers refreshed

    def test_one_open_case_per_item_branch_is_enforced_by_the_database(self):
        SupplyCase.objects.create(item=self.item, branch=self.branch)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupplyCase.objects.create(item=self.item, branch=self.branch)
        # A closed case does not block a new open one.
        SupplyCase.objects.filter(item=self.item).update(status=S.STATUS_FULFILLED)
        SupplyCase.objects.create(item=self.item, branch=self.branch)

    def test_one_open_network_case_per_item(self):
        SupplyCase.objects.create(item=self.item, branch=None)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SupplyCase.objects.create(item=self.item, branch=None)


class TransitionTests(_Base):
    def setUp(self):
        self.case = SupplyCase.objects.create(item=self.item, branch=self.branch)

    def test_valid_path_detected_to_ordered_to_received_to_fulfilled(self):
        svc.transition(self.case, S.STATUS_ORDERED)
        svc.transition(self.case, S.STATUS_RECEIVED)
        c = svc.transition(self.case, S.STATUS_FULFILLED)
        self.assertEqual(c.status, S.STATUS_FULFILLED)
        self.assertIsNotNone(c.closed_at)

    def test_invalid_transition_rejected(self):
        with self.assertRaises(svc.CaseTransitionError):
            svc.transition(self.case, S.STATUS_RECEIVED)        # detected → received: no
        with self.assertRaises(svc.CaseTransitionError):
            svc.transition(self.case, S.STATUS_SEARCHING)       # auto-only status

    def test_cancel_requires_a_reason(self):
        with self.assertRaises(svc.CaseTransitionError):
            svc.transition(self.case, S.STATUS_CANCELLED)
        c = svc.transition(self.case, S.STATUS_CANCELLED, reason='الصنف متوقف')
        self.assertEqual(c.close_reason, 'الصنف متوقف')

    def test_closed_case_cannot_move(self):
        svc.transition(self.case, S.STATUS_CANCELLED, reason='x')
        with self.assertRaises(svc.CaseTransitionError):
            svc.transition(self.case, S.STATUS_ORDERED)


# ── Sweep + queue ──────────────────────────────────────────────────────────────

class SweepAndQueueTests(_Base):
    def test_sweep_opens_cases_from_open_demand_signals(self):
        _metric(_run(), self.item, self.branch, stock=0, gap=0)
        ds.record_signal('reservation', 'r1', provenance_class=DemandSignal.CLASS_CUSTOMER,
                         qty=3, item_id=self.item.id, branch_id=self.branch.id)
        counts = svc.sweep_cases(notify=False)
        self.assertEqual(counts['opened'], 1)
        c = SupplyCase.objects.get()
        self.assertEqual(float(c.customer_demand), 3.0)
        self.assertTrue(c.is_urgent)                             # zero stock + waiting customer

    def test_network_case_skipped_when_item_has_branch_need(self):
        _metric(_run(), self.item, self.branch, stock=0, gap=4)
        ds.record_signal('shortage_item', 's1', provenance_class=DemandSignal.CLASS_BRANCH,
                         qty=4, item_id=self.item.id, branch_id=self.branch.id)
        ds.record_signal('market_shortage', str(self.item.id),
                         provenance_class=DemandSignal.CLASS_STATISTICAL,
                         qty=12, item_id=self.item.id)
        pairs = svc.candidate_pairs()
        self.assertIn((self.item.id, self.branch.id), pairs)
        self.assertNotIn((self.item.id, None), pairs)

    def test_queue_buckets_and_summary(self):
        _metric(_run(), self.item, self.branch, stock=0, gap=0)
        ds.record_signal('reservation', 'r1', provenance_class=DemandSignal.CLASS_CUSTOMER,
                         qty=2, item_id=self.item.id, branch_id=self.branch.id)
        svc.sweep_cases(notify=False)
        summ = svc.queue_summary()
        self.assertEqual(summ['total'], 1)
        self.assertEqual(summ['urgent'], 1)
        self.assertEqual(summ['zero_stock'], 1)
        self.assertEqual(summ['customer_waiting'], 1)
        self.assertEqual(summ['ordered'], 0)


# ── Alerts (existing Notification system, once per case) ───────────────────────

class NotificationTests(_Base):
    def test_urgent_case_alerts_purchasing_once(self):
        from apps.notifications.models import Notification
        _, buyer, _ = make_user('buyer1', role='purchasing')
        _metric(_run(), self.item, self.branch, stock=0, gap=0)
        ds.record_signal('reservation', 'r1', provenance_class=DemandSignal.CLASS_CUSTOMER,
                         qty=2, item_id=self.item.id, branch_id=self.branch.id)
        svc.sweep_cases(notify=True)
        svc.sweep_cases(notify=True)                            # second sweep: no repeat
        n = Notification.objects.filter(recipient=buyer, dedup_key__startswith='supply_case_urgent_')
        self.assertEqual(n.count(), 1)

    def test_alerts_off_by_default(self):
        from apps.notifications.models import Notification
        make_user('buyer2', role='purchasing')
        _metric(_run(), self.item, self.branch, stock=0, gap=0)
        ds.record_signal('reservation', 'r1', provenance_class=DemandSignal.CLASS_CUSTOMER,
                         qty=2, item_id=self.item.id, branch_id=self.branch.id)
        svc.sweep_cases()                                       # SUPPLY_CASE_NOTIFY default False
        self.assertFalse(Notification.objects.filter(
            dedup_key__startswith='supply_case_').exists())


# ── API + RBAC ─────────────────────────────────────────────────────────────────

class CaseApiRbacTests(_Base):
    def _client(self, user):
        c = APIClient()
        c.force_authenticate(user)
        return c

    def setUp(self):
        self.case = SupplyCase.objects.create(item=self.item, branch=self.branch)

    def test_purchasing_can_list_and_transition(self):
        user, _, _ = make_user('buyer_api', role='purchasing')
        c = self._client(user)
        self.assertEqual(c.get('/api/supply/cases/').status_code, 200)
        r = c.post(f'/api/supply/cases/{self.case.id}/transition/',
                   {'status': 'ordered'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['status'], 'ordered')

    def test_invalid_transition_returns_400(self):
        user, _, _ = make_user('buyer_api2', role='purchasing')
        r = self._client(user).post(f'/api/supply/cases/{self.case.id}/transition/',
                                    {'status': 'received'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_salesperson_is_denied_server_side(self):
        user, _, _ = make_user('seller', role='salesperson')
        c = self._client(user)
        self.assertEqual(c.get('/api/supply/cases/').status_code, 403)
        self.assertEqual(c.post(f'/api/supply/cases/{self.case.id}/transition/',
                                {'status': 'ordered'}, format='json').status_code, 403)

    def test_explicit_matrix_denial_beats_the_role_fallback(self):
        from apps.users.models import RoleModuleAccess
        RoleModuleAccess.objects.create(role='purchasing', module='purchasing',
                                        action='view', is_allowed=True)
        RoleModuleAccess.objects.create(role='purchasing', module='purchasing',
                                        action='edit', is_allowed=False)
        user, _, _ = make_user('buyer_denied', role='purchasing')
        c = self._client(user)
        self.assertEqual(c.get('/api/supply/cases/').status_code, 200)
        self.assertEqual(c.post(f'/api/supply/cases/{self.case.id}/transition/',
                                {'status': 'ordered'}, format='json').status_code, 403)

    def test_summary_and_unknown_bucket(self):
        user, _, _ = make_user('buyer_api3', role='purchasing')
        c = self._client(user)
        self.assertEqual(c.get('/api/supply/cases/summary/').status_code, 200)
        self.assertEqual(c.get('/api/supply/cases/?bucket=nope').status_code, 400)
