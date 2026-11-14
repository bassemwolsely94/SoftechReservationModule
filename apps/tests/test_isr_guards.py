"""
ISR draft guards (apps/purchasing/isr_guards.py, doc 30 phase A, owner 2026-10-24) — nothing
reaches SOFTECH twice: valid routes only, one live general draft per route (supersede /
refuse), identical re-push refused without a reason, forwarding leg after its feeder,
audited cancel. SOFTECH is never touched (build_items_plan / the writer are mocked).
"""
import datetime
from unittest import mock

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.purchasing import isr_guards as G
from apps.purchasing import isr_writer as W
from apps.purchasing.models import IsrPush as P
from apps.tests.factories import make_hq


def _lines(*pairs):
    return [{'itemcode': c, 'item_name': c, 'itemqty': q, 'itemqty_cfarma': float(q), 'nowqty': 0.0,
             'itemsaleprice': 1.0, 'itemcostprice': 2.0, 'suppcode': '', 'gap': float(q)} for c, q in pairs]


def _fake_items_plan(node, items):
    return _lines(*[(c, int(q)) for c, q in items])


class RouteTests(TestCase):
    def setUp(self):
        super().setUp()
        make_hq('100', self)   # HQ is read through hq_code()

    def test_valid_and_invalid_routes(self):
        G.validate_route(P.KIND_HQ_TO_BRANCH, '100', '160')
        G.validate_route(P.KIND_BRANCH_TO_HQ, '170', '100')
        G.validate_route(P.KIND_SELF, '130', '')
        G.validate_route(P.KIND_SELF, '130', '130')
        for kind, s, d in ((P.KIND_HQ_TO_BRANCH, '100', '100'),      # the #34 bug
                           (P.KIND_BRANCH_TO_HQ, '100', '100'), (P.KIND_HQ_TO_BRANCH, '150', '160'),
                           (P.KIND_SELF, '130', '140'), ('teleport', '100', '160')):
            with self.assertRaises(G.GuardError):
                G.validate_route(kind, s, d)
        with self.assertRaises(G.GuardError):
            W._persist_proposal(source='100', dest='100', kind=P.KIND_HQ_TO_BRANCH, lines=_lines(('A', 1)))


class OneLiveDraftTests(TestCase):
    def setUp(self):
        super().setUp()
        make_hq('100', self)   # HQ is read through hq_code()

    def _new(self, lines=(('A', 2),)):
        return W._persist_proposal(source='100', dest='160', kind=P.KIND_HQ_TO_BRANCH, lines=_lines(*lines))

    def test_new_draft_supersedes_older_proposed(self):
        from apps.audit.models import AuditLog
        old = self._new()
        new = self._new((('A', 3),))
        old.refresh_from_db()
        self.assertEqual(old.status, P.STATUS_CANCELLED)
        self.assertEqual(old.params['cancelled']['superseded_by'], new.pk)
        self.assertEqual(P.objects.filter(status='proposed', branchcode='100', dest_branchcode='160').count(), 1)
        self.assertTrue(AuditLog.objects.filter(action='isr_draft_cancelled').exists())

    def test_approved_draft_blocks_the_route(self):
        p = self._new()
        P.objects.filter(pk=p.pk).update(status=P.STATUS_APPROVED)
        with self.assertRaises(G.GuardError) as e:
            self._new()
        self.assertEqual(e.exception.code, 'approved_exists')

    def test_database_backs_it_up(self):
        P.objects.create(branchcode='100', dest_branchcode='150', kind=P.KIND_HQ_TO_BRANCH)
        with self.assertRaises(IntegrityError), transaction.atomic():
            P.objects.create(branchcode='100', dest_branchcode='150', kind=P.KIND_HQ_TO_BRANCH)

    def test_request_tied_drafts_keep_their_own_rules(self):
        a = W._persist_proposal(source='150', dest='100', kind=P.KIND_BRANCH_TO_HQ, lines=_lines(('A', 1)),
                                origin_isr=2616001)
        b = W._persist_proposal(source='150', dest='100', kind=P.KIND_BRANCH_TO_HQ, lines=_lines(('B', 1)),
                                origin_isr=2616002)
        c = W._persist_proposal(source='150', dest='100', kind=P.KIND_BRANCH_TO_HQ, lines=_lines(('C', 1)))
        self.assertEqual({p.status for p in P.objects.filter(pk__in=[a.pk, b.pk, c.pk])}, {'proposed'})


class TransferPairTests(TestCase):
    def setUp(self):
        make_hq('100', self)   # HQ is read through hq_code()
        p = mock.patch.object(W, 'build_items_plan', side_effect=_fake_items_plan)
        p.start()
        self.addCleanup(p.stop)

    def test_pairs_touching_hq_get_one_leg(self):
        l1, l2 = W.create_transfer_proposals('170', '100', [('A', 2)])
        self.assertEqual((l1.kind, l1.branchcode, l1.dest_branchcode, l2), (P.KIND_BRANCH_TO_HQ, '170', '100', None))
        l1, l2 = W.create_transfer_proposals('100', '160', [('A', 2)])
        self.assertEqual((l1, l2.kind, l2.branchcode, l2.dest_branchcode), (None, P.KIND_HQ_TO_BRANCH, '100', '160'))
        self.assertEqual(W.create_transfer_proposals('130', '130', [('A', 2)]), (None, None))
        self.assertFalse(P.objects.filter(branchcode='100', dest_branchcode='100').exists())

    def test_normal_pair_is_two_linked_legs_or_nothing(self):
        l1, l2 = W.create_transfer_proposals('150', '140', [('A', 2)])
        self.assertEqual((l1.linked_push_id, l2.linked_push_id), (l2.pk, l1.pk))
        # an approved HQ → 140 draft blocks leg 2 → leg 1 must not be left behind
        P.objects.filter(pk=l2.pk).update(status=P.STATUS_APPROVED)
        before = P.objects.count()
        with self.assertRaises(G.GuardError):
            W.create_transfer_proposals('130', '140', [('B', 1)])
        self.assertEqual(P.objects.count(), before)

class PushGuardTests(TestCase):
    def setUp(self):
        super().setUp()
        make_hq('100', self)   # HQ is read through hq_code()

    def _pushed(self, lines, days_ago=1):
        p = P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH,
                             status=P.STATUS_PUSHED, lines_snapshot=lines, isrdocnumber=26100661,
                             pushed_at=timezone.now() - datetime.timedelta(days=days_ago))
        return p

    def _approved(self, lines):
        return P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH,
                                status=P.STATUS_APPROVED, lines_snapshot=lines)

    def test_identical_re_push_refused_unless_a_reason(self):
        self._pushed(_lines(('A', 2), ('B', 1)))
        p = self._approved(_lines(('B', 1), ('A', 2)))          # same lines, other order
        with self.assertRaises(G.GuardError) as e:
            G.check_push(p)
        self.assertEqual(e.exception.code, 'duplicate_push')
        G.check_push(p, force_reason='الفرع لم يستلم الأول — إعادة مقصودة')
        p.refresh_from_db()
        self.assertIn('forced_push', p.params)

    def test_different_lines_or_old_push_pass(self):
        self._pushed(_lines(('A', 2)))
        G.check_push(self._approved(_lines(('A', 3))))          # other qty → another ISR
        P.objects.all().delete()
        self._pushed(_lines(('A', 2)), days_ago=10)
        G.check_push(self._approved(_lines(('A', 2))))          # older than 7 days

    def test_forwarding_leg_waits_for_its_feeder(self):
        leg1 = P.objects.create(branchcode='150', dest_branchcode='100', kind=P.KIND_BRANCH_TO_HQ,
                                status=P.STATUS_APPROVED, lines_snapshot=_lines(('A', 1)))
        leg2 = P.objects.create(branchcode='100', dest_branchcode='140', kind=P.KIND_HQ_TO_BRANCH,
                                status=P.STATUS_APPROVED, lines_snapshot=_lines(('A', 1)), linked_push=leg1)
        with self.assertRaises(G.GuardError) as e:
            G.check_push(leg2)
        self.assertEqual(e.exception.code, 'feeder_first')
        P.objects.filter(pk=leg1.pk).update(status=P.STATUS_PUSHED, pushed_at=timezone.now())
        leg2.refresh_from_db()
        with self.assertRaises(G.GuardError) as e:              # pushed, but not received at HQ yet
            G.check_push(leg2)
        self.assertEqual(e.exception.code, 'feeder_not_received')
        from apps.transits.models import InTransitTransfer
        InTransitTransfer.objects.create(erp_doc_number='7001', erp_supplying_branch_code='150',
                                         erp_receiving_branch_code='100', issue_date=timezone.localdate(),
                                         transit_status='received', erp_received_date=timezone.localdate(),
                                         items_snapshot=[{'itemcode': 'A', 'qty': 1}])
        G.check_push(leg2)

    @override_settings(ISR_WRITER_ENABLED=True)
    def test_writer_refuses_before_connecting(self):
        self._pushed(_lines(('A', 2)))
        p = self._approved(_lines(('A', 2)))
        with mock.patch('config.sybase.get_branch_connection') as conn:
            with self.assertRaises(G.GuardError):
                W.push_isr_record(p)
        conn.assert_not_called()


@override_settings(SUPPLY_ERP_GROUPS='10,19,21,27')
class ApiTests(TestCase):
    def setUp(self):
        make_hq('100', self)   # HQ is read through hq_code()
        from .factories import make_user
        self.admin, _, _ = make_user('g_admin', role='admin')
        self.viewer, _, _ = make_user('g_sales', role='salesperson')
        self.c = APIClient()

    def test_cancel_needs_rights_and_reason(self):
        p = P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH)
        url = f'/api/purchasing/isr/pushes/{p.pk}/cancel/'
        self.c.force_authenticate(self.viewer)
        self.assertEqual(self.c.post(url, {'reason': 'مكرر'}, format='json').status_code, 403)
        self.c.force_authenticate(self.admin)
        self.assertEqual(self.c.post(url, {'reason': ''}, format='json').status_code, 400)
        r = self.c.post(url, {'reason': 'مكرر مع طلب آخر'}, format='json')
        self.assertEqual((r.status_code, r.data['status']), (200, 'cancelled'))
        P.objects.filter(pk=p.pk).update(status=P.STATUS_PUSHED)
        self.assertEqual(self.c.post(url, {'reason': 'مكرر مع طلب آخر'}, format='json').status_code, 400)

    @override_settings(ISR_WRITER_ENABLED=True)
    def test_push_duplicate_is_409_with_code(self):
        P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH, status=P.STATUS_PUSHED,
                         lines_snapshot=_lines(('A', 2)), isrdocnumber=1, pushed_at=timezone.now())
        p = P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH,
                             status=P.STATUS_APPROVED, lines_snapshot=_lines(('A', 2)))
        self.c.force_authenticate(self.admin)
        r = self.c.post(f'/api/purchasing/isr/pushes/{p.pk}/push/', {}, format='json')
        self.assertEqual((r.status_code, r.data['code']), (409, 'duplicate_push'))


class OverlapGuardTests(TestCase):
    """P-32 §2.4: a draft that shares some items with an ISR pushed to the same destination in the last
    DUP_PUSH_DAYS days. Off by default (SystemSetting isr_overlap_guard) until the owner confirms the rule."""
    def setUp(self):
        super().setUp()
        make_hq('100', self)   # HQ is read through hq_code()


    def _pushed(self, lines, days_ago=1, dest='160', kind=P.KIND_HQ_TO_BRANCH, source='100'):
        return P.objects.create(branchcode=source, dest_branchcode=dest, kind=kind, status=P.STATUS_PUSHED,
                                lines_snapshot=lines, isrdocnumber=26100700,
                                pushed_at=timezone.now() - datetime.timedelta(days=days_ago))

    def _approved(self, lines, dest='160'):
        return P.objects.create(branchcode='100', dest_branchcode=dest, kind=P.KIND_HQ_TO_BRANCH,
                                status=P.STATUS_APPROVED, lines_snapshot=lines)

    def _on(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(key='isr_overlap_guard', defaults={'value': 'on'})

    def test_overlap_lists_shared_items_only(self):
        earlier = self._pushed(_lines(('A', 2), ('B', 1)))
        rows = G.overlapping_pushed(self._approved(_lines(('A', 5), ('C', 1))))
        self.assertEqual([(r['itemcode'], r['qty'], r['earlier_qty'], r['push_id']) for r in rows],
                         [('A', 5, 2, earlier.pk)])

    def test_other_destination_old_push_or_identical_are_not_overlaps(self):
        self._pushed(_lines(('A', 2)), dest='150')                   # other branch
        self._pushed(_lines(('A', 2)), days_ago=10)                  # older than the window
        self._pushed(_lines(('B', 1)))                               # identical → duplicate guard, not this one
        first = self._approved(_lines(('A', 2)))
        self.assertEqual(G.overlapping_pushed(first), [])
        first.delete()                                               # one live draft per route
        self.assertEqual(G.overlapping_pushed(self._approved(_lines(('B', 1)))), [])

    def test_off_by_default_then_refused_without_reason(self):
        self._pushed(_lines(('A', 2), ('B', 1)))
        p = self._approved(_lines(('A', 5), ('C', 1)))
        G.check_push(p)                                              # switch off: passes as before
        self._on()
        with self.assertRaises(G.GuardError) as e:
            G.check_push(p)
        self.assertEqual(e.exception.code, 'overlap_push')
        self.assertIn('A', str(e.exception))

    def test_reason_lets_it_through_once_and_is_audited(self):
        from apps.audit.models import AuditLog
        self._on()
        earlier = self._pushed(_lines(('A', 2)))
        p = self._approved(_lines(('A', 5), ('C', 1)))
        G.check_push(p, force_reason='الفرع طلب كمية إضافية من A')
        p.refresh_from_db()
        self.assertEqual(p.params['forced_overlap']['items'], ['A'])
        self.assertEqual(p.params['forced_overlap']['earlier'], [earlier.pk])
        self.assertEqual(AuditLog.objects.filter(action='isr_overlap_push_forced').count(), 1)


class OverlapDispensedTests(TestCase):
    """Owner 2026-11-01: a repeat counts only while the earlier ISR is NOT dispensed. Dispensed = the source issued
    that item to that destination (stock ledger doc 125, counterpart store = destination) after the earlier push."""

    def setUp(self):
        self.earlier = P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH,
                                        status=P.STATUS_PUSHED, lines_snapshot=_lines(('A', 2), ('B', 1)),
                                        isrdocnumber=26100701,
                                        pushed_at=timezone.now() - datetime.timedelta(days=3))
        self.draft = P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH,
                                      status=P.STATUS_APPROVED, lines_snapshot=_lines(('A', 5), ('B', 2)))

    def _issue(self, item, days_ago, to='160'):
        from apps.stock_audit.models import StockLedgerLine
        at = timezone.now() - datetime.timedelta(days=days_ago)
        StockLedgerLine.objects.create(branchcode='100', doccode='125', docnumber=90000 + int(days_ago * 10),
                                       docdate=timezone.localdate(at), trans_time=at, storecode='100',
                                       storecode2=to, personcode=to, itemcode=item, transqty=1, newqty=0)

    def test_dispensed_item_is_not_an_overlap(self):
        self._issue('A', 1)                                         # HQ sent A to 160 after the earlier push
        self.assertEqual([r['itemcode'] for r in G.overlapping_pushed(self.draft)], ['B'])

    def test_issue_before_the_push_or_to_another_branch_does_not_count(self):
        self._issue('A', 5)                                         # before the earlier push
        self._issue('B', 1, to='150')                               # to another branch
        self.assertEqual([r['itemcode'] for r in G.overlapping_pushed(self.draft)], ['A', 'B'])


class OverlapReportTests(TestCase):

    def test_report_counts_pushes_that_repeated_items(self):
        from io import StringIO
        from django.core.management import call_command
        now = timezone.now()
        for days, lines in ((5, _lines(('A', 2), ('B', 1))), (3, _lines(('A', 1), ('C', 4))), (1, _lines(('D', 1)))):
            P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH,
                             status=P.STATUS_PUSHED, lines_snapshot=lines,
                             pushed_at=now - datetime.timedelta(days=days))
        out = StringIO()
        call_command('report_isr_overlaps', days=30, stdout=out)
        self.assertIn('pushes 3 · with overlap 1 · overlapping lines 1', out.getvalue())


class PlannerRuleTests(TestCase):
    """P-32 §2.3: one live draft per route, whoever made it — a draft from another planner is refused with
    `other_planner` instead of silently cancelling the waiting one; same planner still supersedes."""
    def setUp(self):
        super().setUp()
        make_hq('100', self)   # HQ is read through hq_code()


    def _draft(self, planner, *lines):
        return W._persist_proposal(source='100', dest='160', kind=P.KIND_HQ_TO_BRANCH, lines=_lines(*lines),
                                   planner=planner)

    def test_planner_is_recorded(self):
        p = self._draft('replenishment', ('A', 1))
        self.assertEqual(p.params['planner'], 'replenishment')

    def test_other_planner_refused_and_waiting_draft_kept(self):
        waiting = self._draft('replenishment', ('A', 1))
        with self.assertRaises(G.GuardError) as e:
            self._draft('distribution', ('B', 2))
        self.assertEqual((e.exception.code, e.exception.other), ('other_planner', waiting.pk))
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, P.STATUS_PROPOSED)

    def test_same_planner_and_untagged_drafts_still_supersede(self):
        old = self._draft('distribution', ('A', 1))
        new = self._draft('distribution', ('B', 1))
        old.refresh_from_db()
        self.assertEqual((old.status, old.params['cancelled']['superseded_by']), (P.STATUS_CANCELLED, new.pk))
        P.objects.filter(pk=new.pk).update(params={})               # a draft made before planners were recorded
        newer = self._draft('replenishment', ('C', 1))
        self.assertEqual(P.objects.get(pk=new.pk).status, P.STATUS_CANCELLED)
        self.assertEqual(newer.status, P.STATUS_PROPOSED)

class DraftExpiryTests(TestCase):
    """P-32 §2.4 / doc 30 §2.6: proposed general drafts older than N days are cancelled with audit (PG only).
    Off until switched on: SystemSetting isr_draft_expiry_days (0 = off)."""

    def _draft(self, days_old, **kw):
        p = P.objects.create(branchcode='100', dest_branchcode=kw.pop('dest', '160'), kind=P.KIND_HQ_TO_BRANCH,
                             status=kw.pop('status', P.STATUS_PROPOSED), lines_snapshot=_lines(('A', 1)), **kw)
        P.objects.filter(pk=p.pk).update(created_at=timezone.now() - datetime.timedelta(days=days_old))
        return p

    def test_off_by_default(self):
        old = self._draft(30)
        self.assertEqual(G.expire_drafts(), [])
        old.refresh_from_db()
        self.assertEqual(old.status, P.STATUS_PROPOSED)

    def test_cancels_only_old_proposed_general_drafts(self):
        from apps.audit.models import AuditLog
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(key='isr_draft_expiry_days', defaults={'value': '7'})
        old = self._draft(8)
        fresh = self._draft(2, dest='150')
        approved = self._draft(30, dest='140', status=P.STATUS_APPROVED)
        tied = self._draft(30, dest='130', origin_isr=26130001)
        self.assertEqual(G.expire_drafts(), [old.pk])
        statuses = dict(P.objects.values_list('pk', 'status'))
        self.assertEqual([statuses[x.pk] for x in (old, fresh, approved, tied)],
                         [P.STATUS_CANCELLED, P.STATUS_PROPOSED, P.STATUS_APPROVED, P.STATUS_PROPOSED])
        self.assertEqual(AuditLog.objects.filter(action='isr_draft_cancelled').count(), 1)
        self.assertEqual(G.expire_drafts(), [])                       # idempotent

    def test_scheduled_daily(self):
        from apps.sync import tasks
        from .test_scheduler_jobs import _FakeScheduler
        captured = {}

        class _Capture(_FakeScheduler):
            def add_job(self, func, trigger, *args, **kwargs):
                captured[kwargs.get('id')] = kwargs
                super().add_job(func, trigger, *args, **kwargs)

        with mock.patch.object(tasks, 'BackgroundScheduler', _Capture), \
             mock.patch.object(tasks, '_patch_apscheduler_for_python312', lambda: None), \
             mock.patch.object(tasks, '_scheduler', None):
            tasks.start_scheduler()
        self.assertIn('isr_draft_expiry', captured)
