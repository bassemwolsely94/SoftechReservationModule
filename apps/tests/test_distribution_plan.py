"""
«التوزيعة» as one plan (apps/purchasing/distribution_plan.py, doc 30 phases B–D, owner 2026-11-10):
waves HQ-first, what is already on its way subtracted, 100 EGP / 1,000 EGP thresholds, one feeder
per source + one «جاهز الآن» per destination + one «بعد الاستلام» part per (destination, source),
and the forwarding part pushed only after the branch leg is RECEIVED at HQ.
SOFTECH is never touched: the live reads, analyze and build_items_plan are patched.
"""
import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.purchasing import distribution_plan as DP
from apps.purchasing import isr_guards as G
from apps.purchasing import isr_writer as W
from apps.purchasing.models import DistributionPlan, IsrPush as P, PlannedMove
from apps.tests.factories import make_admin, make_item, make_salesperson

TH = {'min_line': 100.0, 'min_doc': 1000.0}
NO_HOLD = lambda key: (None, '')


def _sug(code, cat, src, targets, qty=2, name=None, age=100):
    return {'itemcode': code, 'item_name': name or code, 'category': cat, 'from_branch': src,
            'qty_each': qty, 'to_branches': [{'code': t, 'qty': qty} for t in targets],
            'signals': [], 'reason': '', 'from_position': {}, 'age_days': age}


def _lines(items):
    return [{'itemcode': c, 'item_name': c, 'itemqty': int(q), 'itemqty_cfarma': float(q), 'nowqty': 0.0,
             'itemsaleprice': 1.0, 'itemcostprice': 1.0, 'suppcode': '', 'gap': float(q)} for c, q in items]


def _plan(sugs, costs, *, hq=None, ceilings=None, flows=None, th=TH, holder=NO_HOLD):
    return DP.plan_moves(sugs, costs=costs, hq_stock=hq or {}, ceilings=ceilings or {},
                         flows=flows or {}, th=th, holder=holder)


def _by(moves):
    return {(m['itemcode'], m['to_code']): m for m in moves}


class WaveTests(TestCase):
    def test_waves_and_source_rules(self):
        sugs = [_sug('H', 'never_stocked', '100', ['160']),
                _sug('O', 'over_piled', '130', ['160']),
                _sug('N', 'never_stocked', '140', ['160']),           # 140 not over its max
                _sug('M', 'never_stocked', '150', ['160']),           # 150 over its max
                _sug('T', 'new_no_rate', '170', ['160'])]
        ceil = {'150': {'M': (9.0, 2.0)}, '140': {'N': (3.0, 5.0)}}
        moves, _ = _plan(sugs, {c: 1000 for c in 'HONMT'}, ceilings=ceil, th={'min_line': 0, 'min_doc': 0})
        m = _by(moves)
        self.assertEqual([m[(c, '160')]['wave'] for c in 'HOMT'], [1, 2, 3, 4])
        self.assertEqual(m[('N', '160')]['status'], 'not_allowed')
        self.assertEqual(m[('M', '160')]['status'], 'planned')

    def test_a_seed_hq_can_cover_moves_to_hq(self):
        moves, _ = _plan([_sug('T', 'new_no_rate', '170', ['160', '150'], qty=1)], {'T': 900},
                         hq={'T': 5}, th={'min_line': 0, 'min_doc': 0})
        self.assertEqual({(x['from_code'], x['wave']) for x in moves}, {('100', 1)})

    def test_trial_stock_new_codes_two_branches_and_a_cap(self):
        """Owner 2026-11-11: wave 4 = new codes only, ≤ 2 branches per item, ≤ the per-plan cap."""
        th = {'min_line': 0, 'min_doc': 0, 'trial_cap': 2500}
        sugs = [_sug('NEW', 'new_no_rate', '170', ['160', '150', '140'], qty=1, age=60),
                _sug('OLD', 'new_no_rate', '170', ['160'], qty=1, age=2000),
                _sug('UNK', 'new_no_rate', '170', ['160'], qty=1, age=None),
                _sug('NEWER', 'new_no_rate', '130', ['160'], qty=1, age=10)]
        m = _by(_plan(sugs, {'NEW': 1000, 'OLD': 1000, 'UNK': 1000, 'NEWER': 1000}, th=th)[0])
        self.assertEqual(m[('NEW', '160')]['status'], 'not_allowed')       # third branch: over the 2-branch limit
        self.assertIn('فرعين', m[('NEW', '160')]['status_note'])
        self.assertEqual((m[('OLD', '160')]['status'], m[('UNK', '160')]['status']), ('not_allowed', 'not_allowed'))
        # cap 2,500: the newest code (NEWER) goes first, then one NEW move; the other NEW waits
        self.assertEqual(m[('NEWER', '160')]['status'], 'planned')
        self.assertEqual(sorted(m[('NEW', b)]['status'] for b in ('140', '150')), ['folded', 'planned'])

    def test_ranked_by_value_within_a_wave(self):
        moves, _ = _plan([_sug('A', 'never_stocked', '100', ['160']), _sug('B', 'never_stocked', '100', ['160'])],
                         {'A': 10, 'B': 900}, th={'min_line': 0, 'min_doc': 0})
        self.assertEqual(_by(moves)[('B', '160')]['rank'], 1)


class CommittedFlowTests(TestCase):
    def test_seed_already_coming_is_a_conflict(self):
        flows = {('A', '160'): [{'source': 'softech_isr', 'label': 'ISR سوفتك 26100700', 'ref': 26100700, 'qty': 3}]}
        moves, docs = _plan([_sug('A', 'never_stocked', '100', ['160'])], {'A': 900}, flows=flows,
                            th={'min_line': 0, 'min_doc': 0})
        self.assertEqual(moves[0]['status'], 'conflict')
        self.assertIn('26100700', moves[0]['status_note'])
        self.assertEqual(docs, [])

    def test_over_piled_is_cut_by_what_is_coming(self):
        flows = {('O', '160'): [{'source': 'transit', 'label': 'بالطريق', 'ref': None, 'qty': 2}]}
        moves, _ = _plan([_sug('O', 'over_piled', '130', ['160'], qty=5)], {'O': 900}, flows=flows,
                         th={'min_line': 0, 'min_doc': 0})
        self.assertEqual((moves[0]['status'], moves[0]['qty']), ('planned', 3))
        flows[('O', '160')][0]['qty'] = 5
        moves, _ = _plan([_sug('O', 'over_piled', '130', ['160'], qty=5)], {'O': 900}, flows=flows,
                         th={'min_line': 0, 'min_doc': 0})
        self.assertEqual(moves[0]['status'], 'conflict')

    def test_committed_flows_reads_our_drafts_and_transfers(self):
        P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH,
                         status=P.STATUS_APPROVED, lines_snapshot=_lines([('A', 2)]))
        P.objects.create(branchcode='100', dest_branchcode='150', kind=P.KIND_HQ_TO_BRANCH, route_tag='dist',
                         status=P.STATUS_PROPOSED, lines_snapshot=_lines([('A', 2)]),
                         params={'planner': 'distribution'})               # replaced by a new generation
        with mock.patch.object(DP, '_softech_isrs', return_value=[]):
            flows, notes = DP.committed_flows({'A'}, {'160', '150'})
        self.assertIn(('A', '160'), flows)
        self.assertNotIn(('A', '150'), flows)
        self.assertEqual(notes, [])

    def test_transfer_requests_follow_the_shared_commitment_rule(self):
        """Same rule as apps/supply/engine/commitments.py: open AND not yet dispatched (a dispatched
        request is already in transit), needs-revision included, the approved qty wins."""
        from apps.tests.factories import make_branch
        from apps.transfers.models import TransferRequest, TransferRequestItem
        src, dst = make_branch('مصدر', '130'), make_branch('مستلم', '160')
        _, staff, _ = make_admin('dist_tr_admin')
        item = make_item('A', softech_id='A')
        for status, dispatched, qty, approved in (('needs_revision', False, 5, 3), ('sent_to_erp', True, 9, None),
                                                  ('completed', False, 7, None)):
            tr = TransferRequest.objects.create(requesting_branch=dst, supplying_branch=src, created_by=staff,
                                                status=status,
                                                dispatched_at=timezone.now() if dispatched else None)
            TransferRequestItem.objects.create(request=tr, item=item, quantity=qty, approved_quantity=approved)
        with mock.patch.object(DP, '_softech_isrs', return_value=[]):
            flows, _ = DP.committed_flows({'A'}, {'160'})
        got = [g for g in flows[('A', '160')] if g['source'] == 'transfer']
        self.assertEqual([g['qty'] for g in got], [3.0])

    def test_softech_unreachable_is_noted_not_fatal(self):
        with mock.patch.object(DP, '_softech_isrs', side_effect=RuntimeError('JZ0C0')):
            flows, notes = DP.committed_flows({'A'}, {'160'})
        self.assertTrue(notes)


class ThresholdAndDocumentTests(TestCase):
    def test_branch_line_under_100_dropped_hq_line_kept(self):
        moves, _ = _plan([_sug('A', 'over_piled', '130', ['160'], qty=1), _sug('B', 'never_stocked', '100', ['160'], qty=1)],
                         {'A': 50, 'B': 50}, th={'min_line': 100, 'min_doc': 0})
        m = _by(moves)
        self.assertEqual((m[('A', '160')]['status'], m[('B', '160')]['status']), ('below_line', 'planned'))

    def test_one_feeder_per_source_one_ready_per_destination(self):
        sugs = [_sug('A', 'over_piled', '130', ['160', '150']), _sug('B', 'over_piled', '130', ['160']),
                _sug('C', 'never_stocked', '100', ['160', '150'])]
        _, docs = _plan(sugs, {'A': 600, 'B': 600, 'C': 600})
        keys = sorted(d['key'] for d in docs)
        self.assertEqual(keys, ['after:150:130', 'after:160:130', 'feed:130', 'ready:150', 'ready:160'])
        feed = next(d for d in docs if d['key'] == 'feed:130')
        self.assertEqual((feed['lines'], feed['qty']), (2, 6))     # A to two branches + B, summed per item
        after = next(d for d in docs if d['key'] == 'after:160:130')
        self.assertEqual((after['waits_for'], after['route_tag']), ('130', 'dist:130'))

    def test_small_after_part_folds_with_its_feeder_lines(self):
        sugs = [_sug('A', 'over_piled', '130', ['160'], qty=10), _sug('B', 'over_piled', '130', ['150'], qty=1)]
        moves, docs = _plan(sugs, {'A': 200, 'B': 200})             # 160 part 2,000; 150 part 200
        m = _by(moves)
        self.assertEqual((m[('A', '160')]['status'], m[('B', '150')]['status']), ('planned', 'folded'))
        self.assertEqual(sorted(d['key'] for d in docs), ['after:160:130', 'feed:130'])
        self.assertEqual(next(d for d in docs if d['key'] == 'feed:130')['value'], 2000)

    def test_small_feeder_folds_everything_it_carries(self):
        sugs = [_sug('A', 'over_piled', '130', ['160'], qty=3)]
        moves, docs = _plan(sugs, {'A': 200}, th={'min_line': 100, 'min_doc': 1000})
        self.assertEqual(moves[0]['status'], 'folded')
        self.assertEqual(docs, [])

    def test_small_hq_document_still_goes(self):
        moves, docs = _plan([_sug('C', 'never_stocked', '100', ['160'], qty=1)], {'C': 50})
        self.assertEqual((moves[0]['status'], [d['key'] for d in docs]), ('planned', ['ready:160']))

    def test_route_held_by_approved_draft_blocks_its_moves(self):
        holder = lambda key: ((77, 'طلب معتمد #77') if key == ('ready', '160', '') else (None, ''))
        moves, docs = _plan([_sug('A', 'never_stocked', '100', ['160', '150'], qty=1)], {'A': 2000}, holder=holder)
        m = _by(moves)
        self.assertEqual((m[('A', '160')]['status'], m[('A', '150')]['status']), ('blocked', 'planned'))
        self.assertEqual([d['key'] for d in docs], ['ready:150'])


def _fake_items_plan(node, items):
    return _lines(items)


class GenerateTests(TestCase):
    def setUp(self):
        for c in 'ABC':
            make_item(c, softech_id=c)
        from apps.catalog.models import Item
        Item.objects.filter(softech_id__in=list('ABC')).update(cost_price=Decimal('600'))
        self.user, _, _ = make_admin('dist_plan_admin')
        sugs = [_sug('A', 'over_piled', '130', ['160', '150']), _sug('B', 'over_piled', '130', ['160']),
                _sug('C', 'never_stocked', '100', ['160', '150'])]
        for p in (mock.patch('apps.purchasing.distribution.analyze', return_value=sugs),
                  mock.patch('apps.purchasing.distribution._operational_branches', return_value={}),
                  mock.patch.object(DP, '_softech_isrs', return_value=[]),
                  mock.patch.object(W, 'build_items_plan', side_effect=_fake_items_plan)):
            p.start()
            self.addCleanup(p.stop)
        from apps.purchasing.models import DemandCalculationRun
        self.run_obj = DemandCalculationRun.objects.create(status='success')

    def _build(self):
        return DP.build(user=self.user, live=False, run=self.run_obj)

    def test_build_stores_the_ledger(self):
        plan = self._build()
        self.assertEqual(plan.moves.count(), 5)
        self.assertEqual(plan.totals['waves']['1']['moves'], 2)
        self.assertEqual(len(plan.documents), 5)

    def test_generate_makes_linked_drafts_on_their_own_routes(self):
        replenishment = W._persist_proposal(source='100', dest='160', kind=P.KIND_HQ_TO_BRANCH,
                                            lines=_lines([('Z', 1)]), planner='replenishment')
        plan = self._build()
        res = DP.generate(plan, user=self.user)
        self.assertEqual(res['skipped'], [])
        drafts = {(p.kind, p.branchcode, p.dest_branchcode, p.route_tag): p
                  for p in P.objects.filter(status='proposed', params__planner='distribution')}
        self.assertEqual(sorted(drafts), sorted([
            ('branch_to_hq', '130', '100', ''), ('hq_to_branch', '100', '160', 'dist'),
            ('hq_to_branch', '100', '150', 'dist'), ('hq_to_branch', '100', '160', 'dist:130'),
            ('hq_to_branch', '100', '150', 'dist:130')]))
        feeder = drafts[('branch_to_hq', '130', '100', '')]
        after = drafts[('hq_to_branch', '100', '160', 'dist:130')]
        self.assertEqual(after.linked_push_id, feeder.pk)
        self.assertEqual(sorted(feeder.params['feeds']), sorted(
            [after.pk, drafts[('hq_to_branch', '100', '150', 'dist:130')].pk]))
        replenishment.refresh_from_db()
        self.assertEqual(replenishment.status, 'proposed')          # a different route — untouched
        self.assertFalse(PlannedMove.objects.filter(plan=plan, status='planned', isr_push__isnull=True).exists())

    def test_second_generate_and_stale_plans_refused(self):
        plan = self._build()
        DP.generate(plan, user=self.user)
        with self.assertRaises(ValueError):
            DP.generate(plan, user=self.user)
        newer = self._build()
        DistributionPlan.objects.filter(pk=newer.pk).update(created_at=timezone.now() - datetime.timedelta(hours=13))
        with self.assertRaises(ValueError):
            DP.generate(newer, user=self.user)

    def test_new_generation_replaces_older_proposed_distribution_drafts(self):
        old = W._persist_proposal(source='100', dest='140', kind=P.KIND_HQ_TO_BRANCH, lines=_lines([('A', 1)]),
                                  planner='distribution', route_tag='dist')
        DP.generate(self._build(), user=self.user)
        old.refresh_from_db()
        self.assertEqual(old.status, 'cancelled')


def _transit(doc, status, items, days_after=0, pushed=None):
    from apps.transits.models import InTransitTransfer
    return InTransitTransfer.objects.create(
        erp_doc_number=doc, erp_supplying_branch_code='130', erp_receiving_branch_code='100',
        issue_date=timezone.localdate(pushed) + datetime.timedelta(days=days_after), transit_status=status,
        items_snapshot=[{'itemcode': c, 'qty': 1} for c in items])


class ReceivedAtHqTests(TestCase):
    def setUp(self):
        self.feeder = P.objects.create(branchcode='130', dest_branchcode='100', kind=P.KIND_BRANCH_TO_HQ,
                                       status=P.STATUS_PUSHED, pushed_at=timezone.now(), isrdocnumber=2613050,
                                       lines_snapshot=_lines([('A', 2)]))
        self.after = P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH,
                                      route_tag='dist:130', status=P.STATUS_APPROVED, linked_push=self.feeder,
                                      lines_snapshot=_lines([('A', 2)]))

    def test_waits_until_the_issue_is_received(self):
        with self.assertRaises(G.GuardError) as e:
            G.check_push(self.after)                                    # nothing issued yet
        self.assertEqual(e.exception.code, 'feeder_not_received')
        t = _transit('9001', 'in_transit', ['A'], pushed=self.feeder.pushed_at)
        with self.assertRaises(G.GuardError):
            G.check_push(self.after)                                    # issued, still on the road
        t.transit_status = 'received'
        t.save(update_fields=['transit_status'])
        G.check_push(self.after)                                        # received at HQ → allowed

    def test_an_issue_before_the_push_or_of_other_items_does_not_count(self):
        _transit('9002', 'received', ['A'], days_after=-2, pushed=self.feeder.pushed_at)
        _transit('9003', 'received', ['Z'], pushed=self.feeder.pushed_at)
        ok, _why = G.received_at_hq(self.feeder)
        self.assertFalse(ok)

    def test_every_forwarding_leg_waits_for_receipt(self):
        """Owner 2026-11-11: one rule — WhatsApp / shortage / engine-transfer legs wait too."""
        self.after.route_tag = ''
        self.after.save(update_fields=['route_tag'])
        with self.assertRaises(G.GuardError):
            G.check_push(self.after)

    def test_stale_issue_is_flagged_and_manual_receipt_releases_it(self):
        t = _transit('9004', 'in_transit', ['A'], pushed=self.feeder.pushed_at)
        P.objects.filter(pk=self.feeder.pk).update(pushed_at=timezone.now() - datetime.timedelta(days=20))
        self.feeder.refresh_from_db()
        t.issue_date = timezone.localdate() - datetime.timedelta(days=19)
        t.save(update_fields=['issue_date'])
        st = G.receipt_status(self.feeder)
        self.assertEqual((st['received'], st['stale'], st['waiting_days']), (False, True, 19))
        self.assertIn('يدوياً', st['why'])
        t.manually_received_at = timezone.now()
        t.save(update_fields=['manually_received_at'])
        self.assertTrue(G.receipt_status(self.feeder)['received'])


class ForwardingExpiryTests(TestCase):
    """A waiting forwarding leg's 7-day clock starts at the receipt at HQ (owner 2026-11-11)."""

    def setUp(self):
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(key='isr_draft_expiry_days', defaults={'value': '7'})
        long_ago = timezone.now() - datetime.timedelta(days=12)
        self.feeder = P.objects.create(branchcode='130', dest_branchcode='100', kind=P.KIND_BRANCH_TO_HQ,
                                       status=P.STATUS_PUSHED, pushed_at=long_ago, lines_snapshot=_lines([('A', 2)]))
        self.leg = P.objects.create(branchcode='100', dest_branchcode='160', kind=P.KIND_HQ_TO_BRANCH,
                                    route_tag='dist:130', status=P.STATUS_PROPOSED, linked_push=self.feeder,
                                    lines_snapshot=_lines([('A', 2)]))
        P.objects.filter(pk=self.leg.pk).update(created_at=long_ago)

    def test_not_expired_while_waiting(self):
        self.assertEqual(G.expire_drafts(), [])

    def test_clock_runs_from_the_receipt(self):
        from apps.transits.models import InTransitTransfer
        t = InTransitTransfer.objects.create(
            erp_doc_number='9100', erp_supplying_branch_code='130', erp_receiving_branch_code='100',
            issue_date=timezone.localdate() - datetime.timedelta(days=11), transit_status='received',
            erp_received_date=timezone.localdate() - datetime.timedelta(days=3), items_snapshot=[{'itemcode': 'A'}])
        self.assertEqual(G.expire_drafts(), [])                         # received 3 days ago
        t.erp_received_date = timezone.localdate() - datetime.timedelta(days=8)
        t.save(update_fields=['erp_received_date'])
        self.assertEqual(G.expire_drafts(), [self.leg.pk])               # received 8 days ago


class PlanViewTests(TestCase):
    def setUp(self):
        _, _, self.admin = make_admin('dist_view_admin')
        _, _, self.sales = make_salesperson('dist_view_sales')

    def test_empty_then_build_generate_export(self):
        r = self.admin.get('/api/purchasing/isr/distribution/plan/')
        self.assertEqual((r.status_code, r.json()['plan']), (200, None))
        fake = DistributionPlan.objects.create(totals={}, documents=[])
        with mock.patch.object(DP, 'build', return_value=fake) as b:
            r = self.admin.post('/api/purchasing/isr/distribution/plan/build/', {}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        b.assert_called_once()
        with mock.patch.object(DP, 'generate', return_value={'created': [], 'skipped': []}):
            r = self.admin.post(f'/api/purchasing/isr/distribution/plan/{fake.pk}/generate/', {}, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        r = self.admin.get(f'/api/purchasing/isr/distribution/plan/{fake.pk}/export/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type'])

    def test_build_and_generate_need_write_rights(self):
        fake = DistributionPlan.objects.create(totals={}, documents=[])
        for url in ('/api/purchasing/isr/distribution/plan/build/',
                    f'/api/purchasing/isr/distribution/plan/{fake.pk}/generate/'):
            r = self.sales.post(url, {}, format='json')
            self.assertIn(r.status_code, (403,), url)
