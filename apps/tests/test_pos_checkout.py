"""
apps/tests/test_pos_checkout.py — D-18 server-side POS checkout (docs/architecture/39_POS_SERVER_CHECKOUT.md).

API, switch, permissions, Phase A all-or-nothing, the client_token replay rules, exactly one post on a
live checkout, and old-path / new-path parity. SOFTECH is never contacted: the live push is mocked at
the writer's own connection boundary (get_branch_connection / _execute_write).
"""
import copy
import uuid
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings

from apps.pos_orders import writer
from apps.pos_orders.models import SoftechSalesOrder
from .factories import make_branch, make_branch2, make_call_center, make_user

BASE = '/api/pos-orders/'
CHECKOUT = BASE + 'checkout/'
PREVIEW = BASE + 'checkout/preview/'
NET = Decimal('275.40')          # 108 × 0.85 + 216 × 0.85


def _basket(branch_id, channel='cash', **extra):
    body = {
        'branch': branch_id, 'channel': channel, 'doc_kind': 'sale', 'customer_name': 'TEST',
        'lines': [
            {'softech_itemcode': '107295', 'item_name': 'I1', 'qty': 1, 'item_sale_price': 108, 'cust_discp': 15},
            {'softech_itemcode': '94965',  'item_name': 'I2', 'qty': 1, 'item_sale_price': 216, 'cust_discp': 15},
        ],
    }
    body.update(extra)
    return body


def _checkout(branch_id, *, token=None, mode='dry_run', expected='275.40', intent=None, confirm=None,
              **extra):
    body = _basket(branch_id, **extra)
    body['client_token'] = token or str(uuid.uuid4())
    body['checkout'] = {'mode': mode, 'expected_due': expected,
                        'tender_intent': intent or {'kind': 'default'}}
    if confirm is not None:
        body['checkout']['confirm'] = confirm
    return body


def _sum(rows):
    return sum((Decimal(r['amount']) for r in rows), Decimal('0'))


class CheckoutSwitchTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, _, self.cc = make_call_center('cc_ck_switch')

    def test_switch_off_answers_404_and_saves_nothing(self):
        for url in (CHECKOUT, PREVIEW):
            r = self.cc.post(url, _checkout(self.branch.id), format='json')
            self.assertEqual(r.status_code, 404, r.data)
            self.assertEqual(r.data, {'detail': 'disabled'})
        self.assertFalse(SoftechSalesOrder.objects.exists())

    def test_reference_reports_switch_off(self):
        r = self.cc.get(BASE + 'reference/')
        self.assertEqual(r.data['server_checkout_branch_ids'], [])

    @override_settings(POS_SERVER_CHECKOUT=True, POS_SERVER_CHECKOUT_BRANCHES=['ZZZ'])
    def test_branch_not_in_the_rollout_list_answers_404(self):
        r = self.cc.post(CHECKOUT, _checkout(self.branch.id), format='json')
        self.assertEqual(r.status_code, 404, r.data)
        self.assertEqual(self.cc.get(BASE + 'reference/').data['server_checkout_branch_ids'], [])

    @override_settings(POS_SERVER_CHECKOUT=True)
    def test_reference_reports_every_branch_when_no_list(self):
        self.assertIsNone(self.cc.get(BASE + 'reference/').data['server_checkout_branch_ids'])

    def test_one_branch_rollout_lists_that_branch(self):
        with override_settings(POS_SERVER_CHECKOUT=True,
                               POS_SERVER_CHECKOUT_BRANCHES=[self.branch.softech_branch_id]):
            ids = self.cc.get(BASE + 'reference/').data['server_checkout_branch_ids']
            self.assertEqual(ids, [self.branch.id])
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id), format='json')
            self.assertEqual(r.status_code, 200, r.data)


@override_settings(POS_SERVER_CHECKOUT=True)
class CheckoutFlowTests(TestCase):
    def setUp(self):
        self.branch = make_branch()
        _, _, self.cc = make_call_center('cc_ck_flow')

    def test_preview_returns_server_totals_and_saves_nothing(self):
        r = self.cc.post(PREVIEW, _checkout(self.branch.id), format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['totals']['due'], '275.40')
        self.assertEqual(r.data['totals']['gross'], '324.00')
        self.assertEqual(r.data['tenders'], [{'pay_type': 'cash', 'amount': '275.40'}])
        self.assertIsNone(r.data['ready_errors'])
        self.assertNotIn('order_id', r.data)
        self.assertFalse(SoftechSalesOrder.objects.exists())

    def test_preview_reports_ready_errors_without_saving(self):
        body = _checkout(self.branch.id, intent={'kind': 'credit_portion', 'credit': '10'})
        r = self.cc.post(PREVIEW, body, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertIn('آجل', r.data['ready_errors']['detail'])
        self.assertFalse(SoftechSalesOrder.objects.exists())

    def test_dry_run_checkout_prices_splits_and_returns_the_plan(self):
        r = self.cc.post(CHECKOUT, _checkout(self.branch.id), format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['status'], 'ready')
        self.assertFalse(r.data['replayed'])
        self.assertEqual(r.data['softech']['mode'], 'dry_run')
        self.assertFalse(r.data['softech']['wrote_to_softech'])
        self.assertIn('plan', r.data)
        self.assertEqual(r.data['totals']['due'], '275.40')
        self.assertEqual(_sum(r.data['tenders']), NET)
        o = SoftechSalesOrder.objects.get(pk=r.data['order_id'])
        self.assertEqual(len(o.checkout_request_hash or ''), 64)
        self.assertEqual(o.doc_value, NET)

    def test_change_discount_reconciles_to_the_piaster(self):
        body = _checkout(self.branch.id, expected='275.00', change_discount='0.40')
        r = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['tenders'], [{'pay_type': 'cash', 'amount': '275.00'}])
        o = SoftechSalesOrder.objects.get(pk=r.data['order_id'])
        paid = sum((p.amount for p in o.payments.all()), Decimal('0'))
        self.assertEqual(paid, o.doc_value - o.change_discount)          # zero tolerance

    def test_credit_portion_on_a_named_channel(self):
        body = _checkout(self.branch.id, channel='permanent', softech_pic='130HD9668',
                         intent={'kind': 'credit_portion', 'credit': '100.00'})
        r = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['tenders'], [{'pay_type': 'cash', 'amount': '175.40'},
                                             {'pay_type': 'credit', 'amount': '100.00'}])

    def test_patient_copay_on_a_contract(self):
        body = _checkout(self.branch.id, channel='contract', softech_pic='130HD9668',
                         intent={'kind': 'patient_copay', 'patient': '50'})
        r = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['tenders'], [{'pay_type': 'cash', 'amount': '50.00'},
                                             {'pay_type': 'credit', 'amount': '225.40'}])
        self.assertEqual(r.data['totals']['patient_pays'], '50.00')
        self.assertEqual(r.data['totals']['claim_amount'], '225.40')

    def test_client_token_is_required(self):
        body = _checkout(self.branch.id)
        body.pop('client_token')
        r = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(SoftechSalesOrder.objects.exists())

    def test_live_mode_requires_the_total_the_cashier_saw(self):
        r = self.cc.post(CHECKOUT, _checkout(self.branch.id, mode='live', expected=None), format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertFalse(SoftechSalesOrder.objects.exists())

    def test_foreign_currency_tender_refused(self):
        body = _checkout(self.branch.id)
        body['checkout']['tender_extras'] = {'currency': 'USD', 'exchange_rate': 50}
        r = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r.status_code, 400, r.data)


@override_settings(POS_SERVER_CHECKOUT=True)
class CheckoutPhaseAIsAtomicTests(TestCase):
    """Doc 39 §4.3 case 6: a failure at any Phase A step leaves no order, no lines, no payments."""

    def setUp(self):
        self.branch = make_branch()
        _, _, self.cc = make_call_center('cc_ck_atomic')

    def _assert_nothing_saved(self):
        from apps.pos_orders.models import SoftechSalesOrderLine, SoftechSalesOrderPayment
        self.assertFalse(SoftechSalesOrder.objects.exists())
        self.assertFalse(SoftechSalesOrderLine.objects.exists())
        self.assertFalse(SoftechSalesOrderPayment.objects.exists())

    def test_serializer_error(self):
        body = _checkout(self.branch.id)
        body['lines'] = [{'item_name': 'no code', 'qty': 'abc'}]
        r = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self._assert_nothing_saved()

    def test_validation_error_after_pricing(self):
        body = _checkout(self.branch.id, expected='0.00')
        body['lines'][0]['qty'] = 0
        r = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self._assert_nothing_saved()

    def test_tender_intent_out_of_range(self):
        body = _checkout(self.branch.id, channel='permanent', softech_pic='130HD9668',
                         intent={'kind': 'credit_portion', 'credit': '999.00'})
        r = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self._assert_nothing_saved()

    def test_total_changed_since_the_preview_is_refused_with_the_new_total(self):
        r = self.cc.post(CHECKOUT, _checkout(self.branch.id, expected='270.00'), format='json')
        self.assertEqual(r.status_code, 409, r.data)
        self.assertTrue(r.data['totals_changed'])
        self.assertEqual(r.data['totals']['due'], '275.40')
        self.assertEqual(r.data['tenders'], [{'pay_type': 'cash', 'amount': '275.40'}])
        self._assert_nothing_saved()

    def test_blocked_contract_item_rolls_back(self):
        with mock.patch.object(writer, 'prepare_order',
                               side_effect=ValueError('الأصناف التالية غير مسموح صرفها لهذا التعاقد: 107295')):
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id), format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self._assert_nothing_saved()

    def test_discount_authority_refusal_rolls_back(self):
        with override_settings(WRITER_INSTANCE=True, POS_WRITER_ENABLED=True), \
             mock.patch('apps.pos_orders.views.validate_discount_authority', return_value=['خصم زائد']):
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id), format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn('discount_authority', r.data['errors'])
        self._assert_nothing_saved()

    @override_settings(WRITER_INSTANCE=True, POS_OFFERS_EXECUTION_ENABLED=True)
    def test_offers_error_with_offers_on_aborts_instead_of_posting_without_the_offer(self):
        with mock.patch('apps.offers.order_attach.apply_offers_to_order', side_effect=RuntimeError('boom')):
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id), format='json')
        self.assertEqual(r.status_code, 400, r.data)
        self.assertIn('offers', r.data['errors'])
        self._assert_nothing_saved()

    def test_offers_error_with_offers_off_is_ignored_as_today(self):
        with mock.patch('apps.offers.order_attach.apply_offers_to_order', side_effect=RuntimeError('boom')):
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id), format='json')
        self.assertEqual(r.status_code, 200, r.data)

    @override_settings(WRITER_INSTANCE=True, POS_OFFERS_EXECUTION_ENABLED=True)
    def test_offer_needing_approval_keeps_a_draft_and_never_pushes(self):
        res = {'enabled': True, 'attached': True, 'requires_approval': True, 'approval_request_id': 5}
        with mock.patch('apps.offers.order_attach.apply_offers_to_order', return_value=res), \
             mock.patch.object(writer, 'push_order') as push:
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id, mode='live', confirm=True), format='json')
        self.assertEqual(r.status_code, 409, r.data)
        self.assertTrue(r.data['requires_offer_approval'])
        push.assert_not_called()
        self.assertEqual(SoftechSalesOrder.objects.get(pk=r.data['order_id']).status, 'draft')


@override_settings(POS_SERVER_CHECKOUT=True)
class CheckoutReplayTests(TestCase):
    """Doc 39 §2.5: the client_token replay rules."""

    def setUp(self):
        self.branch = make_branch()
        _, _, self.cc = make_call_center('cc_ck_replay')
        self.token = str(uuid.uuid4())
        r = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=self.token), format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.order = SoftechSalesOrder.objects.get(pk=r.data['order_id'])

    def test_same_basket_reruns_on_the_same_order(self):
        r = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=self.token), format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['replayed'])
        self.assertEqual(r.data['order_id'], self.order.pk)
        self.assertEqual(SoftechSalesOrder.objects.count(), 1)
        self.assertEqual(self.order.payments.count(), 1)

    def test_same_token_other_basket_is_refused_and_the_first_is_untouched(self):
        body = _checkout(self.branch.id, token=self.token)
        body['lines'][0]['qty'] = 3
        r = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r.status_code, 409, r.data)
        self.assertTrue(r.data['token_reused'])
        self.assertEqual(self.order.lines.order_by('id').first().qty, 1)
        self.assertEqual(SoftechSalesOrder.objects.count(), 1)

    def test_a_posted_order_is_answered_from_the_record_without_the_writer(self):
        SoftechSalesOrder.objects.filter(pk=self.order.pk).update(status='pushed', softech_docnumber=7901)
        with mock.patch.object(writer, 'push_order') as push:
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=self.token), format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertTrue(r.data['replayed'])
        self.assertEqual(r.data['softech']['docnumber'], 7901)
        push.assert_not_called()

    def test_pushing_answers_busy(self):
        SoftechSalesOrder.objects.filter(pk=self.order.pk).update(status='pushing')
        with mock.patch.object(writer, 'push_order') as push:
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=self.token), format='json')
        self.assertEqual(r.status_code, 202, r.data)
        self.assertTrue(r.data['busy'])
        push.assert_not_called()

    def test_outcome_unknown_is_never_repushed_from_checkout(self):
        SoftechSalesOrder.objects.filter(pk=self.order.pk).update(
            status='push_failed', erp_error=writer.OUTCOME_UNKNOWN + 'socket closed')
        with mock.patch.object(writer, 'push_order') as push, \
             mock.patch.object(writer, '_execute_write') as ew:
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=self.token), format='json')
        self.assertEqual(r.status_code, 409, r.data)
        self.assertTrue(r.data['outcome_unknown'])
        push.assert_not_called()
        ew.assert_not_called()

    def test_cancelled_order_token_is_not_reused(self):
        SoftechSalesOrder.objects.filter(pk=self.order.pk).update(status='cancelled')
        r = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=self.token), format='json')
        self.assertEqual(r.status_code, 409, r.data)
        self.assertTrue(r.data['token_reused'])

    def test_an_old_path_order_is_never_taken_over(self):
        """Doc 39 §4.3 case 8: an order made by the old path (no basket hash) under the same token."""
        old_token = str(uuid.uuid4())
        r = self.cc.post(BASE, {**_basket(self.branch.id), 'client_token': old_token}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.cc.post(f'{BASE}{r.data["id"]}/ready/', {'tenders': [{'pay_type': 'cash', 'amount': '275.40'}]},
                     format='json')
        with mock.patch.object(writer, 'push_order') as push:
            r2 = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=old_token), format='json')
        self.assertEqual(r2.status_code, 409, r2.data)
        self.assertTrue(r2.data['token_reused'])
        push.assert_not_called()

    def test_another_branchs_token_is_refused(self):
        b2 = make_branch2()
        other = SoftechSalesOrder.objects.create(branch=b2, softech_branchcode=b2.softech_branch_id,
                                                 store_code='1', client_token=uuid.uuid4())
        _, _, ph = make_user('ph_ck_replay', role='pharmacist', branch=self.branch)
        r = ph.post(CHECKOUT, _checkout(self.branch.id, token=str(other.client_token)), format='json')
        self.assertEqual(r.status_code, 409, r.data)


@override_settings(POS_SERVER_CHECKOUT=True)
class CheckoutPermissionTests(TestCase):
    """Doc 39 §4.3 case 9."""

    def setUp(self):
        self.branch = make_branch()
        self.other = make_branch2()

    def test_anonymous_denied(self):
        from rest_framework.test import APIClient
        r = APIClient().post(CHECKOUT, _checkout(self.branch.id), format='json')
        self.assertIn(r.status_code, (401, 403))

    def test_viewer_denied(self):
        _, _, viewer = make_user('viewer_ck', role='viewer', branch=self.branch)
        for url in (CHECKOUT, PREVIEW):
            self.assertEqual(viewer.post(url, _checkout(self.branch.id), format='json').status_code, 403)
        self.assertFalse(SoftechSalesOrder.objects.exists())

    def test_other_branch_refused(self):
        _, _, ph = make_user('ph_ck_branch', role='pharmacist', branch=self.branch)
        r = ph.post(CHECKOUT, _checkout(self.other.id), format='json')
        self.assertEqual(r.status_code, 403, r.data)
        self.assertFalse(SoftechSalesOrder.objects.exists())

    def test_channel_not_allowed_refused(self):
        _, prof, sp = make_user('sp_ck_channel', role='salesperson', branch=self.branch)
        prof.allowed_pos_channels = ['cash']
        prof.save()
        body = _checkout(self.branch.id, channel='contract', softech_pic='130HD9668')
        for url in (CHECKOUT, PREVIEW):
            self.assertEqual(sp.post(url, body, format='json').status_code, 403)
        self.assertFalse(SoftechSalesOrder.objects.exists())

    def test_prepare_without_push_right_gets_the_order_prepared_and_a_403(self):
        _, _, cc = make_call_center('cc_ck_noperm')
        with mock.patch('apps.pos_orders.permissions.CanPushPosOrders.has_permission', return_value=False), \
             mock.patch.object(writer, 'push_order') as push:
            r = cc.post(CHECKOUT, _checkout(self.branch.id), format='json')
        self.assertEqual(r.status_code, 403, r.data)
        self.assertEqual(r.data['status'], 'ready')
        push.assert_not_called()


def _live_patches(docnumber=470001, **execute):
    """The writer's live path with SOFTECH replaced at its connection boundary."""
    return [
        override_settings(WRITER_INSTANCE=True, POS_WRITER_ENABLED=True, POS_BLOCK_POINTS_SALES=False),
        mock.patch('config.sybase.get_branch_connection', return_value=mock.MagicMock()),
        mock.patch.object(writer, '_pending_docnumber_by_vf2', return_value=None),
        mock.patch('apps.pos_orders.stock.check_item_restrictions', return_value=[]),
        mock.patch('apps.pos_orders.stock.enabled', return_value=False),
        mock.patch('apps.pos_orders.views.validate_discount_authority', return_value=[]),
    ]


@override_settings(POS_SERVER_CHECKOUT=True)
class CheckoutLivePushTests(TestCase):
    """A live checkout reaches the SAME writer once; a replay never writes again."""

    def setUp(self):
        self.branch = make_branch()
        self.branch.db_host = '10.0.0.9'
        self.branch.save()
        _, _, self.cc = make_call_center('cc_ck_live')

    def _enter(self, patches):
        for p in patches:
            p.start() if hasattr(p, 'start') else p.enable()
            self.addCleanup(p.stop if hasattr(p, 'stop') else p.disable)

    def test_one_post_then_replay_returns_the_docnumber(self):
        self._enter(_live_patches())
        with mock.patch.object(writer, '_execute_write', return_value={'ok': True, 'docnumber': 470001}) as ew:
            token = str(uuid.uuid4())
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=token, mode='live', confirm=True),
                             format='json')
            self.assertEqual(r.status_code, 200, r.data)
            self.assertEqual(r.data['status'], 'pushed')
            self.assertTrue(r.data['softech']['wrote_to_softech'])
            self.assertEqual(r.data['softech']['docnumber'], 470001)
            r2 = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=token, mode='live', confirm=True),
                              format='json')
            self.assertEqual(r2.status_code, 200, r2.data)
            self.assertTrue(r2.data['replayed'])
            self.assertEqual(r2.data['softech']['docnumber'], 470001)
            o = SoftechSalesOrder.objects.get(pk=r.data['order_id'])
            self.assertEqual(writer.push_order(o, dry_run=False)['already_pushed'], True)   # flush job too
        self.assertEqual(ew.call_count, 1)

    def test_live_without_confirm_is_refused_before_anything_is_saved(self):
        self._enter(_live_patches())
        with mock.patch.object(writer, '_execute_write') as ew:
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id, mode='live'), format='json')
        self.assertEqual(r.status_code, 409, r.data)
        self.assertTrue(r.data['requires_confirm'])
        ew.assert_not_called()
        self.assertFalse(SoftechSalesOrder.objects.exists())

    def test_pending_found_by_vf2_is_adopted_not_reinserted(self):
        self._enter(_live_patches())
        with mock.patch.object(writer, '_pending_docnumber_by_vf2', return_value=470555), \
             mock.patch.object(writer, '_execute_write') as ew:
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id, mode='live', confirm=True), format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['softech']['mode'], 'idempotent_recovered')
        self.assertEqual(r.data['softech']['docnumber'], 470555)
        ew.assert_not_called()

    def test_commit_sent_reply_lost_is_never_reposted_by_a_retry(self):
        self._enter(_live_patches())
        conn = mock.MagicMock()
        conn.commit.side_effect = RuntimeError('socket closed after commit')
        token = str(uuid.uuid4())
        self.cc.raise_request_exception = False
        with mock.patch('config.sybase.get_branch_connection', return_value=conn), \
             mock.patch.object(writer, '_execute_write', return_value={'ok': True, 'docnumber': 1}) as ew:
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=token, mode='live', confirm=True),
                             format='json')
            self.assertGreaterEqual(r.status_code, 500)                       # as /push/ today
            o = SoftechSalesOrder.objects.get(client_token=token)
            self.assertTrue(writer.is_outcome_unknown(o))
            r2 = self.cc.post(CHECKOUT, _checkout(self.branch.id, token=token, mode='live', confirm=True),
                              format='json')
        self.assertEqual(r2.status_code, 409, r2.data)
        self.assertTrue(r2.data['outcome_unknown'])
        self.assertEqual(ew.call_count, 1)

    def test_branch_unreachable_queues_as_today(self):
        self._enter(_live_patches())
        with mock.patch('config.sybase.get_branch_connection',
                        side_effect=Exception('java.net.ConnectException: Connection refused')):
            r = self.cc.post(CHECKOUT, _checkout(self.branch.id, mode='live', confirm=True), format='json')
        self.assertEqual(r.status_code, 202, r.data)
        self.assertTrue(r.data['queued'])
        self.assertEqual(r.data['status'], 'queued')


@override_settings(POS_SERVER_CHECKOUT=True)
class OldPathUnchangedTests(TestCase):
    """The 4-request browser path keeps working while the switch is on (and off)."""

    def setUp(self):
        self.branch = make_branch()
        _, _, self.cc = make_call_center('cc_ck_old')

    def test_create_ready_push_still_work(self):
        r = self.cc.post(BASE, _basket(self.branch.id), format='json')
        self.assertEqual(r.status_code, 201, r.data)
        oid = r.data['id']
        r = self.cc.post(f'{BASE}{oid}/ready/', {'tenders': [{'pay_type': 'cash', 'amount': '275.40'}]},
                         format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['status'], 'ready')
        self.assertEqual(r.data['doc_value'], '275.40')
        r = self.cc.post(f'{BASE}{oid}/push/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['mode'], 'dry_run')
        self.assertIsNone(SoftechSalesOrder.objects.get(pk=oid).checkout_request_hash)

    def test_old_path_keeps_its_one_piaster_tolerance(self):
        r = self.cc.post(BASE, _basket(self.branch.id), format='json')
        r = self.cc.post(f'{BASE}{r.data["id"]}/ready/', {'tenders': [{'pay_type': 'cash', 'amount': '275.39'}]},
                         format='json')
        self.assertEqual(r.status_code, 200, r.data)

    def test_old_path_live_push_needs_confirm_as_before(self):
        r = self.cc.post(BASE, _basket(self.branch.id), format='json')
        oid = r.data['id']
        self.cc.post(f'{BASE}{oid}/ready/', {'tenders': [{'pay_type': 'cash', 'amount': '275.40'}]}, format='json')
        with override_settings(WRITER_INSTANCE=True, POS_WRITER_ENABLED=True):
            r = self.cc.post(f'{BASE}{oid}/push/', {'dry_run': False}, format='json')
        self.assertEqual(r.status_code, 409, r.data)
        self.assertTrue(r.data['requires_confirm'])


def _norm_plan(plan):
    """build_payload output minus what differs by order id (vf2 = 'POS<pk>')."""
    p = copy.deepcopy(plan)
    p['header'].pop('vf2', None)
    return p


@override_settings(POS_SERVER_CHECKOUT=True)
class OldNewParityTests(TestCase):
    """Doc 39 §4.4 + §4.3 case 10: the same basket through the old path and the new path gives the same
    build_payload, payment rows and money fields — per channel. The gate before any person-run probe."""

    def setUp(self):
        self.branch = make_branch()
        _, _, self.cc = make_call_center('cc_ck_parity')

    def _old(self, basket, tenders):
        r = self.cc.post(BASE, basket, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        oid = r.data['id']
        r = self.cc.post(f'{BASE}{oid}/ready/', {'tenders': tenders}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        r = self.cc.post(f'{BASE}{oid}/push/', {}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        return SoftechSalesOrder.objects.get(pk=oid), r.data['plan']

    def _new(self, basket, intent, expected):
        body = {**basket, 'client_token': str(uuid.uuid4()),
                'checkout': {'mode': 'dry_run', 'expected_due': expected, 'tender_intent': intent}}
        r = self.cc.post(CHECKOUT, body, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        return SoftechSalesOrder.objects.get(pk=r.data['order_id']), r.data['plan']

    def _same(self, basket, tenders, intent, expected):
        old, old_plan = self._old(basket, tenders)
        new, new_plan = self._new(basket, intent, expected)
        self.assertEqual(_norm_plan(old_plan), _norm_plan(new_plan))
        for f in ('doc_value', 'doc_value_gross', 'doc_value_cogs', 'doc_value_tax', 'doc_value_pay',
                  'patient_payment', 'change_discount'):
            self.assertEqual(getattr(old, f), getattr(new, f), f)
        self.assertEqual([(p.pay_type, p.amount) for p in old.payments.order_by('id')],
                         [(p.pay_type, p.amount) for p in new.payments.order_by('id')])

    def test_cash(self):
        self._same(_basket(self.branch.id), [{'pay_type': 'cash', 'amount': '275.40'}],
                   {'kind': 'default'}, '275.40')

    def test_cash_with_change_discount(self):
        b = _basket(self.branch.id, change_discount='0.40')
        self._same(b, [{'pay_type': 'cash', 'amount': '275.00'}], {'kind': 'default'}, '275.00')

    def test_cash_strip_quantity(self):
        b = _basket(self.branch.id)
        b['lines'][0]['qty'] = '0.33333'
        net = (Decimal('91.80') * Decimal('0.33333')).quantize(Decimal('0.01')) + Decimal('183.60')
        self._same(b, [{'pay_type': 'cash', 'amount': str(net)}], {'kind': 'default'}, str(net))

    def test_delivery(self):
        b = _basket(self.branch.id, channel='delivery', softech_pic='130HD9668')
        self._same(b, [{'pay_type': 'cash', 'amount': '275.40'}], {'kind': 'default'}, '275.40')

    def test_permanent_split(self):
        b = _basket(self.branch.id, channel='permanent', softech_pic='130HD9668')
        self._same(b, [{'pay_type': 'cash', 'amount': '175.40'}, {'pay_type': 'credit', 'amount': '100.00'}],
                   {'kind': 'credit_portion', 'credit': '100'}, '275.40')

    def test_contract_copay(self):
        b = _basket(self.branch.id, channel='contract', softech_pic='130HD9668')
        self._same(b, [{'pay_type': 'cash', 'amount': '68.85'}, {'pay_type': 'credit', 'amount': '206.55'}],
                   {'kind': 'patient_copay', 'patient': '68.85'}, '275.40')

    def test_contract_default_all_credit(self):
        b = _basket(self.branch.id, channel='contract', softech_pic='130HD9668')
        self._same(b, [], {'kind': 'default'}, '275.40')

    def test_employee_all_credit(self):
        b = _basket(self.branch.id, channel='employee', softech_pic='130HD9668')
        self._same(b, [{'pay_type': 'credit', 'amount': '275.40'}], {'kind': 'default'}, '275.40')
