"""
Regression tests for the low-risk fixes made during the full project audit (2026-11-15).
Each class names the finding id from docs/full-project-audit/11_BUG_FIX_REGISTER.md.
"""
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.catalog.models import Item
from apps.tests.factories import make_admin, make_category


class PurchasingFilterOptionsDistinctTests(TestCase):
    """PERF-5: the code→label lists must be DISTINCT per code, not per item name."""

    def test_family_list_query_does_not_select_item_name(self):
        cat = make_category()
        for i, name in enumerate(['A item', 'B item', 'C item']):
            Item.objects.create(softech_id=f'F{i}', name=name, category=cat, is_active=True,
                                family_code='07', family_name='Antibiotics')
        _, _, client = make_admin()
        with CaptureQueriesContext(connection) as ctx:
            r = client.get('/api/purchasing/filter-options/')
        self.assertEqual(r.status_code, 200)
        fam_sql = [q['sql'] for q in ctx.captured_queries
                   if 'DISTINCT' in q['sql'] and '"family_code"' in q['sql']]
        self.assertTrue(fam_sql, 'family list query not found')
        for sql in fam_sql:
            self.assertNotIn('"catalog_item"."name"', sql)
        self.assertEqual([f['code'] for f in r.data['families']], ['07'])


class VoucherVerifyLocksVoucherTests(TestCase):
    """BE-5: verify-otp locks the voucher row, so a single-use voucher can't be redeemed twice."""

    def setUp(self):
        import datetime
        from apps.vouchers.models import Voucher
        self.Voucher = Voucher
        _, _, self.client = make_admin('audit_voucher_admin')
        self.voucher = Voucher.objects.create(
            code=Voucher.generate_code(), title='قسيمة', voucher_type='discount_pct', discount_pct=10,
            status='active', max_uses=1, valid_from=datetime.date.today())

    def _verify(self, phone):
        from apps.vouchers.models import VoucherOTP
        _, _, plain = VoucherOTP.create_for_voucher(self.voucher, phone)
        return self.client.post(f'/api/vouchers/vouchers/{self.voucher.id}/verify-otp/',
                                {'code': plain, 'phone': phone}, format='json')

    def test_voucher_row_is_locked(self):
        with CaptureQueriesContext(connection) as ctx:
            r = self._verify('01000000001')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertTrue(any('FOR UPDATE' in q['sql'] and '"vouchers_voucher"' in q['sql']
                            and '"vouchers_voucherotp"' not in q['sql'] for q in ctx.captured_queries))

    def test_second_otp_on_single_use_voucher_is_refused(self):
        self.assertEqual(self._verify('01000000001').status_code, 200)
        self.assertEqual(self._verify('01000000002').status_code, 400)
        self.voucher.refresh_from_db()
        self.assertEqual(self.voucher.times_used, 1)


class LoyaltyRedemptionAndReferralTests(TestCase):
    """BE-6: a failed approval leaves the request pending and deducts nothing; a second approval is
    refused. BE-8: a negative referral delta is refused instead of adding points."""

    def setUp(self):
        from apps.loyalty.models import LoyaltyAccount, RedemptionRequest, RewardCatalog
        from apps.tests.factories import make_customer
        self.customer = make_customer()
        self.account = LoyaltyAccount.objects.create(customer=self.customer, points_balance=100)
        self.reward = RewardCatalog.objects.create(name='R', reward_type='voucher', points_cost=80)
        self.Req = RedemptionRequest
        _, _, self.client = make_admin('audit_loyalty_admin')

    def _request(self):
        return self.Req.objects.create(account=self.account, reward=self.reward, points_spent=80)

    def test_approve_twice_deducts_once(self):
        req = self._request()
        self.assertEqual(self.client.post(f'/api/loyalty/redemptions/{req.pk}/approve/').status_code, 200)
        self.assertEqual(self.client.post(f'/api/loyalty/redemptions/{req.pk}/approve/').status_code, 404)
        self.account.refresh_from_db()
        self.assertEqual(self.account.points_balance, 20)

    def test_insufficient_balance_keeps_request_pending(self):
        self.account.points_balance = 10
        self.account.save(update_fields=['points_balance'])
        req = self._request()
        r = self.client.post(f'/api/loyalty/redemptions/{req.pk}/approve/')
        self.assertEqual(r.status_code, 400)
        req.refresh_from_db()
        self.account.refresh_from_db()
        self.assertEqual(req.status, 'pending')
        self.assertEqual(self.account.points_balance, 10)

    def test_negative_referral_adjustment_never_adds_points(self):
        # D-14 (owner 2026-11-19) opened a deduction lane: with no reason it is refused, and with a
        # reason it DEDUCTS. Either way a negative delta never adds points (the BE-8 bug).
        url = f'/api/loyalty/customers/{self.customer.pk}/adjust/'
        r = self.client.post(url, {'points': -50, 'reason': '', 'adjust_type': 'referral'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.account.refresh_from_db()
        self.assertEqual(self.account.points_balance, 100)
        r = self.client.post(url, {'points': -50, 'reason': 'x', 'adjust_type': 'referral'}, format='json')
        self.assertEqual(r.status_code, 200)
        self.account.refresh_from_db()
        self.assertEqual(self.account.points_balance, 50)


class ChatterPostBranchScopeTests(TestCase):
    """SEC-3: posting into a record's chatter follows the same branch scope as reading it."""

    def setUp(self):
        from apps.reservations.models import Reservation
        from apps.tests.factories import make_branch, make_branch2, make_item, make_pharmacist
        b1, b2 = make_branch(), make_branch2()
        item = make_item()
        _, p1, self.c1 = make_pharmacist('audit_chat_1', branch=b1)
        _, _, self.c2 = make_pharmacist('audit_chat_2', branch=b2)
        self.res = Reservation.objects.create(item=item, branch=b1, quantity_requested=1,
                                              contact_name='عميل', contact_phone='01011111111', created_by=p1)

    def _post(self, client):
        return client.post(f'/api/notifications/chatter/reservation/{self.res.pk}/post/',
                           {'message': 'رسالة'}, format='json')

    def test_other_branch_cannot_post(self):
        from apps.notifications.models import ChatterMessage
        self.assertEqual(self._post(self.c2).status_code, 403)
        self.assertFalse(ChatterMessage.objects.filter(model_name='reservation', record_id=self.res.pk).exists())

    def test_own_branch_can_post(self):
        self.assertEqual(self._post(self.c1).status_code, 201)


class SybaseLongParamBindingTests(TestCase):
    """S-10: ints outside the 32-bit range are bound with setLong (no SOFTECH connection: a fake one)."""

    def test_big_int_uses_set_long_small_uses_set_int(self):
        from unittest import mock
        from config.sybase import CursorWrapper
        stmt = mock.MagicMock()
        stmt.execute.return_value = False
        conn = mock.MagicMock()
        conn.prepareStatement.return_value = stmt
        CursorWrapper(conn)._execute('SELECT 1 WHERE a = ? AND b = ?', [7, 22112026 * 100], None)
        stmt.setInt.assert_called_once_with(1, 7)
        stmt.setLong.assert_called_once_with(2, 2211202600)


class PosPushDocdateIsCairoDateTests(TestCase):
    """S-13: a push at 23:30 UTC (01:30 Cairo, next day) records the Cairo date SOFTECH stamps."""

    def test_docdate_is_local_date(self):
        import datetime
        from unittest import mock
        from django.test import override_settings
        from django.utils import timezone
        from apps.pos_orders import writer
        from apps.pos_orders.models import SoftechSalesOrder
        from apps.tests.factories import make_branch
        br = make_branch()
        br.db_host = '10.0.0.9'
        br.save()
        o = SoftechSalesOrder.objects.create(branch=br, softech_branchcode=br.softech_branch_id,
                                             channel='cash', status=SoftechSalesOrder.STATUS_READY)
        utc_night = datetime.datetime(2026, 11, 15, 23, 30, tzinfo=datetime.timezone.utc)
        with override_settings(POS_WRITER_ENABLED=True), \
             mock.patch('config.sybase.get_branch_connection', return_value=mock.MagicMock()), \
             mock.patch.object(writer, 'build_payload', return_value={}), \
             mock.patch.object(writer, '_pending_docnumber_by_vf2', return_value=None), \
             mock.patch.object(writer, '_execute_write', return_value={'ok': True, 'docnumber': 470001}), \
             mock.patch.object(timezone, 'now', return_value=utc_night):
            writer.push_order(o, dry_run=False)
        o.refresh_from_db()
        self.assertEqual(o.status, SoftechSalesOrder.STATUS_PUSHED)
        self.assertEqual(o.softech_docdate, datetime.date(2026, 11, 16))


class PosOrderDeleteLockTests(TestCase):
    """BE-1: an order that left this system (or may have) cannot be deleted; draft/ready still can."""

    def setUp(self):
        from apps.pos_orders.models import SoftechSalesOrder
        from apps.tests.factories import make_branch
        self.Order = SoftechSalesOrder
        self.br = make_branch()
        _, _, self.client = make_admin('audit_pos_admin')

    def _order(self, status):
        return self.Order.objects.create(branch=self.br, softech_branchcode=self.br.softech_branch_id,
                                         status=status)

    def test_sent_or_unknown_outcome_orders_are_refused(self):
        O = self.Order
        for st in (O.STATUS_QUEUED, O.STATUS_PUSHING, O.STATUS_PUSHED, O.STATUS_PUSH_FAILED,
                   O.STATUS_SETTLED, O.STATUS_CANCELLED):
            order = self._order(st)
            r = self.client.delete(f'/api/pos-orders/{order.pk}/')
            self.assertEqual(r.status_code, 409, st)
            self.assertTrue(O.objects.filter(pk=order.pk).exists(), st)

    def test_draft_and_ready_can_still_be_deleted(self):
        O = self.Order
        for st in (O.STATUS_DRAFT, O.STATUS_READY):
            order = self._order(st)
            r = self.client.delete(f'/api/pos-orders/{order.pk}/')
            self.assertEqual(r.status_code, 204, st)
            self.assertFalse(O.objects.filter(pk=order.pk).exists(), st)
