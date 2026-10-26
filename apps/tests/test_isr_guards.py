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


def _lines(*pairs):
    return [{'itemcode': c, 'item_name': c, 'itemqty': q, 'itemqty_cfarma': float(q), 'nowqty': 0.0,
             'itemsaleprice': 1.0, 'itemcostprice': 2.0, 'suppcode': '', 'gap': float(q)} for c, q in pairs]


def _fake_items_plan(node, items):
    return _lines(*[(c, int(q)) for c, q in items])


class RouteTests(TestCase):
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

    def test_distribution_generate_reports_refused_routes(self):
        P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH, status=P.STATUS_APPROVED)
        sugs = [{'from_branch': '100', 'itemcode': 'A', 'qty_each': 1, 'to_branches': [{'code': '160', 'qty': 1}]},
                {'from_branch': '100', 'itemcode': 'B', 'qty_each': 1, 'to_branches': [{'code': '150', 'qty': 1}]}]
        skipped = []
        with mock.patch('apps.purchasing.distribution.analyze', return_value=sugs):
            created = W.create_distribution_proposals(skipped=skipped)
        self.assertEqual([c['path'] for c in created], [['100', '150']])   # screen draws the arrow per language
        self.assertEqual(skipped[0]['path'], ['100', '160'])


class PushGuardTests(TestCase):
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
        P.objects.filter(pk=leg1.pk).update(status=P.STATUS_PUSHED)
        leg2.refresh_from_db()
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
