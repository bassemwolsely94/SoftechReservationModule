"""
apps/tests/test_pos_d11_d12.py — owner money rules of 2026-11-19.

D-11 «Allow + flag»: a failed live branch read (discount authority at /ready, points rate at push)
never blocks the sale or changes a discount; it leaves exactly ONE review record per order+kind, shown
to supervisors, and the missing points are credited ONCE after recovery (claim + SOFTECH tag guard).
D-12: an order posted from the offline queue consumes its offer uses like a live push — once.

No SOFTECH connection anywhere: every branch read / writer is mocked.
"""
import threading
import time
from decimal import Decimal
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from apps.offers.models import Offer, OfferApplication
from apps.offers.usage import committed_uses
from apps.pos_orders import live_checks, writer
from apps.pos_orders.models import PosLiveCheckGap as Gap, SoftechSalesOrder as S, SoftechSalesOrderLine
from apps.pos_orders.offer_uses import consume_after_post
from apps.users.models import RoleModuleAccess
from core.middleware import module_access
from .factories import make_branch, make_item, make_user


def _order(branch, **kw):
    d = dict(branch=branch, softech_branchcode=branch.softech_branch_id, store_code='130',
             channel='cash', doc_kind='sale', seller_usercode='7', softech_pic='PIC9',
             doc_value=Decimal('90'), doc_value_gross=Decimal('100'))
    d.update(kw)
    return S.objects.create(**d)


# ── D-11: discount-authority read fails at /ready ──────────────────────────────────────────────

class DiscountAuthorityFailOpenTests(TestCase):
    def setUp(self):
        self.br = make_branch()
        self.user, self.staff, self.client = make_user('d11_cashier', role='pharmacist', branch=self.br)
        self.order = _order(self.br, status=S.STATUS_READY)

    def _ready(self):
        return self.client.post(f'/api/pos-orders/{self.order.pk}/ready/', {}, format='json')

    @mock.patch('apps.pos_orders.discount_authority.validate_contract_discount_role', return_value=[])
    @mock.patch('apps.pos_orders.views.validate_order')
    @mock.patch('apps.pos_orders.views.writer.prepare_order')
    @mock.patch('apps.pos_orders.views.writer.writer_enabled', return_value=True)
    @mock.patch('apps.pos_orders.views.validate_discount_authority', side_effect=TimeoutError('branch down'))
    def test_sale_proceeds_and_one_review_record(self, *_):
        r1 = self._ready()
        r2 = self._ready()                                   # the cashier presses again
        self.assertEqual(r1.status_code, 200, r1.content)    # never blocked
        self.assertEqual(r2.status_code, 200, r2.content)
        gaps = Gap.objects.filter(order_ref=self.order.pk)
        self.assertEqual(gaps.count(), 1)
        g = gaps.get()
        self.assertEqual(g.kind, Gap.KIND_DISCOUNT)
        self.assertEqual(g.status, Gap.STATUS_OPEN)
        self.assertEqual(g.discount_given, Decimal('10.00'))   # copied, never recomputed
        self.assertEqual(g.branch_id, self.br.pk)
        self.assertEqual(g.cashier_id, self.staff.pk)
        self.assertNotIn('branch down', g.detail)              # no raw error text kept

    @mock.patch('apps.pos_orders.discount_authority.validate_contract_discount_role', return_value=[])
    @mock.patch('apps.pos_orders.views.validate_order')
    @mock.patch('apps.pos_orders.views.writer.prepare_order')
    @mock.patch('apps.pos_orders.views.writer.writer_enabled', return_value=True)
    def test_later_successful_read_closes_the_record(self, *_):
        with mock.patch('apps.pos_orders.views.validate_discount_authority', side_effect=OSError('x')):
            self._ready()
        with mock.patch('apps.pos_orders.views.validate_discount_authority', return_value=[]):
            self.assertEqual(self._ready().status_code, 200)
        self.assertEqual(Gap.objects.get(order_ref=self.order.pk).status, Gap.STATUS_RECHECKED)


# ── D-11: points rate read fails at push ───────────────────────────────────────────────────────

class PointsRateFailOpenPushTests(TestCase):
    def setUp(self):
        self.br = make_branch()
        self.br.db_host = '10.0.0.1'                     # never contacted: the connection is mocked
        self.br.save(update_fields=['db_host'])
        self.order = _order(self.br, status=S.STATUS_READY)
        SoftechSalesOrderLine.objects.create(order=self.order, softech_itemcode='1', qty=1, item_sale_price=100)

    @mock.patch('apps.pos_orders.stock.enabled', return_value=False)
    @mock.patch('apps.pos_orders.stock.check_item_restrictions', return_value=[])
    @mock.patch('apps.pos_orders.writer.build_payload', return_value={})
    @mock.patch('apps.pos_orders.writer._pending_docnumber_by_vf2', return_value=None)
    @mock.patch('config.sybase.get_branch_connection')
    @mock.patch('apps.pos_orders.writer.writer_enabled', return_value=True)
    @mock.patch('apps.pos_orders.writer._execute_write',
                return_value={'ok': True, 'docnumber': 5001, 'points_rate_unread': True})
    def test_posted_with_one_review_record(self, *_):
        res = writer.push_order(self.order, dry_run=False)
        self.assertTrue(res['ok'])                                       # the sale still posts
        self.order.refresh_from_db()
        res2 = writer.push_order(self.order, dry_run=False)              # a retry: idempotent
        self.assertTrue(res2['already_pushed'])
        gaps = Gap.objects.filter(order_ref=self.order.pk)
        self.assertEqual(gaps.count(), 1)
        self.assertEqual(gaps.get().kind, Gap.KIND_POINTS)

    @mock.patch('apps.pos_orders.stock.enabled', return_value=False)
    @mock.patch('apps.pos_orders.stock.check_item_restrictions', return_value=[])
    @mock.patch('apps.pos_orders.writer.build_payload', return_value={})
    @mock.patch('apps.pos_orders.writer._pending_docnumber_by_vf2', return_value=None)
    @mock.patch('config.sybase.get_branch_connection')
    @mock.patch('apps.pos_orders.writer.writer_enabled', return_value=True)
    @mock.patch('apps.pos_orders.writer._execute_write',
                return_value={'ok': True, 'docnumber': 5002, 'points_rate_unread': False})
    def test_no_record_when_rate_was_read(self, *_):
        writer.push_order(self.order, dry_run=False)
        self.assertFalse(Gap.objects.filter(order_ref=self.order.pk).exists())


# ── D-11: credit the missing points once ───────────────────────────────────────────────────────

@override_settings(POS_POINTS_RECOVERY_ENABLED=True)
@mock.patch('config.writers.writer_allowed', return_value=True)
@mock.patch('apps.pos_orders.points.is_enrolled', return_value=True)
@mock.patch('apps.pos_orders.live_checks.missing_points', return_value=37)
class PointsRecreditTests(TestCase):
    def setUp(self):
        self.br = make_branch()
        self.user, self.staff, _ = make_user('d11_sup', role='supervisor', branch=self.br)
        self.order = _order(self.br, status=S.STATUS_SETTLED, softech_docnumber=7001)
        self.gap = live_checks.record_gap(self.order, Gap.KIND_POINTS)

    def test_credited_once_and_retry_credits_nothing(self, *_):
        with mock.patch('apps.pos_orders.live_checks._tag_in_softech', side_effect=[False, True]), \
             mock.patch('apps.loyalty.pic_bridge.adjust_softech_points', return_value=137) as adj:
            res = live_checks.credit_missing_points(self.gap, actor=self.user, commit=True)
            self.assertEqual(res['points'], 37)
            self.assertTrue(res['wrote_to_softech'])
            again = live_checks.credit_missing_points(self.gap, actor=self.user, commit=True)
        self.assertTrue(again['already_credited'])
        self.assertFalse(again['wrote_to_softech'])
        adj.assert_called_once()
        self.assertEqual(adj.call_args.args[:2], ('PIC9', 37))
        self.assertEqual(adj.call_args.kwargs['reason'], live_checks.credit_tag(self.order.pk))
        self.gap.refresh_from_db()
        self.assertEqual(self.gap.status, Gap.STATUS_CREDITED)
        self.assertEqual(self.gap.points_credited, 37)

    def test_lost_reply_then_retry_finds_tag_and_writes_nothing(self, *_):
        with mock.patch('apps.pos_orders.live_checks._tag_in_softech', side_effect=[False, True]), \
             mock.patch('apps.loyalty.pic_bridge.adjust_softech_points',
                        side_effect=RuntimeError('reply lost')) as adj:
            with self.assertRaises(live_checks.CreditRefused):
                live_checks.credit_missing_points(self.gap, actor=self.user, commit=True)
            self.gap.refresh_from_db()
            self.assertEqual(self.gap.status, Gap.STATUS_OPEN)           # released, not lost
            res = live_checks.credit_missing_points(self.gap, actor=self.user, commit=True)
        self.assertTrue(res['found_in_softech'])
        self.assertEqual(adj.call_count, 1)                              # the retry did not INSERT
        self.gap.refresh_from_db()
        self.assertEqual(self.gap.status, Gap.STATUS_CREDITED)

    def test_concurrent_claim_writes_nothing(self, *_):
        Gap.objects.filter(pk=self.gap.pk).update(status=Gap.STATUS_CREDITING)   # another run holds it
        with mock.patch('apps.loyalty.pic_bridge.adjust_softech_points') as adj:
            with self.assertRaises(live_checks.CreditRefused):
                live_checks.credit_missing_points(self.gap, actor=self.user, commit=True)
        adj.assert_not_called()

    def test_tag_read_failure_writes_nothing(self, *_):
        with mock.patch('apps.pos_orders.live_checks._tag_in_softech', side_effect=OSError('down')), \
             mock.patch('apps.loyalty.pic_bridge.adjust_softech_points') as adj:
            with self.assertRaises(live_checks.CreditRefused):
                live_checks.credit_missing_points(self.gap, actor=self.user, commit=True)
        adj.assert_not_called()
        self.gap.refresh_from_db()
        self.assertEqual(self.gap.status, Gap.STATUS_OPEN)

    def test_not_settled_is_refused(self, *_):
        S.objects.filter(pk=self.order.pk).update(status=S.STATUS_PUSHED)
        self.gap.refresh_from_db()
        with mock.patch('apps.loyalty.pic_bridge.adjust_softech_points') as adj:
            with self.assertRaises(live_checks.CreditRefused):
                live_checks.credit_missing_points(self.gap, actor=self.user, commit=True)
        adj.assert_not_called()

    def test_dry_run_by_default(self, *_):
        with mock.patch('apps.loyalty.pic_bridge.adjust_softech_points') as adj:
            res = live_checks.credit_missing_points(self.gap, actor=self.user)
        self.assertTrue(res['dry_run'])
        self.assertEqual(res['points'], 37)
        adj.assert_not_called()

    @override_settings(POS_POINTS_RECOVERY_ENABLED=False)
    def test_switch_off_refuses(self, *_):
        with mock.patch('apps.loyalty.pic_bridge.adjust_softech_points') as adj:
            with self.assertRaises(live_checks.CreditRefused):
                live_checks.credit_missing_points(self.gap, actor=self.user, commit=True)
        adj.assert_not_called()


# ── D-11: review list permission ───────────────────────────────────────────────────────────────

class ReviewListPermissionTests(TestCase):
    def setUp(self):
        self.br = make_branch()
        for role, actions in (('supervisor', ('view', 'create', 'edit')),
                              ('pharmacist', ('view', 'create'))):
            for a in actions:
                RoleModuleAccess.objects.update_or_create(role=role, module='pos', action=a,
                                                          defaults={'is_allowed': True})
        # the cashier must NOT hold pos/edit, whatever a data migration seeded
        RoleModuleAccess.objects.filter(role='pharmacist', module='pos', action='edit').update(is_allowed=False)
        module_access.clear_cache()
        self.addCleanup(module_access.clear_cache)
        _, _, self.sup = make_user('d11_sup2', role='supervisor', branch=self.br, access_all=True)
        _, _, self.cashier = make_user('d11_cash2', role='pharmacist', branch=self.br)
        self.order = _order(self.br, status=S.STATUS_PUSHED)
        self.gap = live_checks.record_gap(self.order, Gap.KIND_DISCOUNT)

    def test_supervisor_sees_the_list(self):
        r = self.sup.get('/api/pos-orders/live-check-gaps/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual([row['id'] for row in r.json()['results']], [self.gap.pk])
        self.assertNotIn('PIC9', r.content.decode())                 # PIC not exposed in the list

    def test_cashier_is_refused(self):
        self.assertEqual(self.cashier.get('/api/pos-orders/live-check-gaps/').status_code, 403)
        r = self.cashier.post(f'/api/pos-orders/live-check-gaps/{self.gap.pk}/review/',
                              {'note': 'x'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_supervisor_review_closes_it(self):
        r = self.sup.post(f'/api/pos-orders/live-check-gaps/{self.gap.pk}/review/',
                          {'note': 'الخصم مسموح للعميل'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.gap.refresh_from_db()
        self.assertEqual(self.gap.status, Gap.STATUS_REVIEWED)
        r2 = self.sup.post(f'/api/pos-orders/live-check-gaps/{self.gap.pk}/review/',
                           {'note': 'again'}, format='json')
        self.assertEqual(r2.status_code, 409)

    def test_review_needs_a_note(self):
        r = self.sup.post(f'/api/pos-orders/live-check-gaps/{self.gap.pk}/review/', {}, format='json')
        self.assertEqual(r.status_code, 400)


# ── D-12: queued orders consume offer uses once ────────────────────────────────────────────────

class QueuedOrderOfferUseTests(TestCase):
    def setUp(self):
        self.br = make_branch()
        it = make_item(name='A', softech_id='A1')
        self.offer = Offer.objects.create(name='O', offer_type='percent', status='active', target_all=True,
                                          authorization_source='item_card', value=100, max_uses_total=5)
        self.order = _order(self.br, status=S.STATUS_QUEUED, softech_pic='')
        SoftechSalesOrderLine.objects.create(
            order=self.order, item=it, softech_itemcode='A1', qty=1, item_sale_price=100,
            cust_discp=100, discount_source='offer', applied_offer=self.offer)
        OfferApplication.objects.create(offer=self.offer, pos_order=self.order, branch=self.br,
                                        was_applied=False, discount_amount=100)

    @mock.patch('apps.pos_orders.writer.writer_enabled', return_value=True)
    def test_flush_command_consumes_once_across_retries(self, _):
        with mock.patch('apps.pos_orders.writer.push_order',
                        return_value={'ok': True, 'docnumber': 9001, 'wrote_to_softech': True}):
            call_command('flush_pos_orders', stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.assertEqual(committed_uses(self.offer)[0], 1)
        self.assertTrue(OfferApplication.objects.get(pos_order=self.order).was_applied)
        # retry: the order is picked again (mocked push left it queued) and reports already pushed
        with mock.patch('apps.pos_orders.writer.push_order',
                        return_value={'already_pushed': True, 'docnumber': 9001, 'wrote_to_softech': False}):
            call_command('flush_pos_orders', stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.assertEqual(committed_uses(self.offer)[0], 1)

    @mock.patch('apps.pos_orders.writer.writer_enabled', return_value=True)
    def test_still_queued_consumes_nothing(self, _):
        with mock.patch('apps.pos_orders.writer.push_order', return_value={'queued': True, 'ok': False}):
            call_command('flush_pos_orders', stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.assertEqual(committed_uses(self.offer)[0], 0)

    @mock.patch('apps.access.softech_gate.require_write', return_value=None)
    @mock.patch('apps.pos_orders.views.writer.writer_enabled', return_value=True)
    def test_flush_now_consumes_once(self, *_):
        _, _, sup = make_user('d12_sup', role='supervisor', branch=self.br, access_all=True)
        with mock.patch('apps.pos_orders.views.writer.push_order',
                        return_value={'ok': True, 'docnumber': 9002, 'wrote_to_softech': True}):
            r1 = sup.post('/api/pos-orders/flush/', {}, format='json')
            r2 = sup.post('/api/pos-orders/flush/', {}, format='json')
        self.assertEqual(r1.status_code, 200, r1.content)
        self.assertEqual(r1.json()['pushed'], 1)
        self.assertEqual(r2.status_code, 200, r2.content)
        self.assertEqual(committed_uses(self.offer)[0], 1)

    def test_helper_is_idempotent(self):
        self.assertEqual(consume_after_post(self.order), {'offer_uses_consumed': 1})
        self.assertEqual(consume_after_post(self.order), {})
        self.assertEqual(committed_uses(self.offer)[0], 1)


# ── D-11: the credit amount is per batch slice, exactly as the live writer (owner 2026-11-19) ──

class SliceRoundingTests(TestCase):
    def test_floor_per_slice_not_per_line(self):
        # one order line split over two FEFO batches: 1 + 1 at 15 EGP, rate 10 % →
        # per slice floor(1.5) + floor(1.5) = 2 (a per-line floor(3.0) would credit 3)
        slices = [{'itemcode': 'X', 'transqty': 1, 'transprice': 15, 'custdiscp': 0},
                  {'itemcode': 'X', 'transqty': 1, 'transprice': 15, 'custdiscp': 0}]
        self.assertEqual(live_checks.points_from_slices(slices, lambda c: 10.0), 2)

    def test_discounted_slice_earns_nothing(self):
        slices = [{'itemcode': 'X', 'transqty': 2, 'transprice': 50, 'custdiscp': 5},
                  {'itemcode': 'Y', 'transqty': 1, 'transprice': 50, 'custdiscp': 0}]
        self.assertEqual(live_checks.points_from_slices(slices, lambda c: 10.0), 5)

    def test_missing_points_reads_the_settled_invoice(self):
        br = make_branch()
        o = _order(br, status=S.STATUS_SETTLED, softech_docnumber=7001, softech_final_docnumber=88001)
        slices = [{'itemcode': 'X', 'transqty': 0.5, 'transprice': 33, 'custdiscp': 0},
                  {'itemcode': 'X', 'transqty': 1.5, 'transprice': 33, 'custdiscp': 0},
                  {'itemcode': 'Z', 'transqty': 1, 'transprice': 99, 'custdiscp': 0}]
        rdr = mock.MagicMock()
        rdr.customer_personcode.return_value = 'CASHREP'
        rdr.item_alt3.side_effect = lambda code: {'X': 'A1', 'Z': None}[code]
        rdr.contracted.return_value = (10, 1)
        with mock.patch('apps.pos_orders.writer.read_finalized_sale',
                        return_value=('2026-11-19', slices, [])) as rf, \
             mock.patch('apps.pos_orders.discount_authority.DiscountAuthorityReader', return_value=rdr):
            pts = live_checks.missing_points(o)
        rf.assert_called_once_with(o.branch, o.softech_branchcode, o.softech_final_docnumber)
        self.assertEqual(pts, 1 + 4)                      # floor(1.65) + floor(4.95); Z has no class → 0
        rdr.close.assert_called_once()

    def test_missing_points_needs_the_final_invoice(self):
        o = _order(make_branch(), status=S.STATUS_SETTLED, softech_docnumber=7002)
        with self.assertRaises(live_checks.CreditRefused):
            live_checks.missing_points(o)

    def test_read_failure_is_never_zero(self):
        o = _order(make_branch(), status=S.STATUS_SETTLED, softech_docnumber=7003,
                   softech_final_docnumber=88003)
        with mock.patch('apps.pos_orders.writer.read_finalized_sale', side_effect=OSError('down')):
            with self.assertRaises(OSError):
                live_checks.missing_points(o)


# ── D-11: two runs at the same moment credit once ──────────────────────────────────────────────

class PointsRecreditConcurrencyTests(TransactionTestCase):
    reset_sequences = False

    @override_settings(POS_POINTS_RECOVERY_ENABLED=True)
    def test_double_run_credits_once(self):
        br = make_branch()
        order = _order(br, status=S.STATUS_SETTLED, softech_docnumber=7101, softech_final_docnumber=88101)
        gap = live_checks.record_gap(order, Gap.KIND_POINTS)
        results, calls = {}, []
        gate = threading.Barrier(2)

        def slow_write(pic, delta, **kw):
            calls.append(delta)
            time.sleep(0.3)                               # hold the claim while the other run tries
            return 100 + delta

        def worker(key):
            try:
                gate.wait()
                g = Gap.objects.get(pk=gap.pk)
                res = live_checks.credit_missing_points(g, actor=None, commit=True)
                results[key] = 'wrote' if res.get('wrote_to_softech') else 'noop'
            except live_checks.CreditRefused:
                results[key] = 'refused'
            finally:
                connection.close()

        with mock.patch('config.writers.writer_allowed', return_value=True), \
             mock.patch('apps.pos_orders.points.is_enrolled', return_value=True), \
             mock.patch('apps.pos_orders.live_checks.missing_points', return_value=12), \
             mock.patch('apps.pos_orders.live_checks._tag_in_softech', return_value=False), \
             mock.patch('apps.loyalty.pic_bridge.adjust_softech_points', side_effect=slow_write):
            threads = [threading.Thread(target=worker, args=(k,)) for k in ('a', 'b')]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(calls, [12])                     # exactly one INSERT
        # the loser is refused while the claim is held, or (if it came later) finds it credited
        self.assertEqual(list(results.values()).count('wrote'), 1)
        self.assertEqual(len(results), 2)
        gap.refresh_from_db()
        self.assertEqual(gap.status, Gap.STATUS_CREDITED)
        self.assertEqual(gap.points_credited, 12)
