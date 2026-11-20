"""
C22 / P-48 rider payout ledger (apps/rider_payouts): the payout rule to the piaster, an idempotent
ledger build, the finalize lock and the admin unlock (D-16), the audit rows, and permissions with
branch scope (a rider sees only their own rows; a manager only their branch). Cash collection is
never touched.
"""
import datetime as dt
from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from apps.config.models import SystemSetting
from apps.delivery.models import DeliveryDriver, DeliveryOrder
from apps.rider_payouts import ledger
from apps.rider_payouts.models import RiderPayoutAuditEvent, RiderPayoutPeriod, RiderPayoutRide
from apps.rider_payouts.rule import PayoutRule, current_rule
from apps.tests.factories import make_admin, make_branch, make_branch2, make_user
from apps.users.models import RoleModuleAccess
from core.middleware import module_access

D = Decimal
DAY = dt.date(2026, 10, 5)
MONTH = '2026-10'
BASE = '/api/delivery/payouts/'

GRANTS = {
    'viewer': {'view'},
    'pharmacist': {'view', 'create', 'edit', 'approve', 'finalize'},
    'delivery': {'view', 'create', 'edit', 'approve', 'finalize'},
}


def _setting(key, value):
    SystemSetting.objects.update_or_create(key=key, defaults={'value': value, 'label': key,
                                                              'value_type': 'decimal', 'category': 'delivery'})
    cache.clear()


def _at(day, hour=12):
    return timezone.make_aware(dt.datetime.combine(day, dt.time(hour)))


class PayoutRuleTests(TestCase):
    """The rule, to the piaster."""

    def test_flat_fee_only_when_distance_unknown(self):
        rule = PayoutRule(flat_fee=D('10.00'), per_km=D('3.00'))
        self.assertEqual(rule.ride_amounts(1, None), (D('10.00'), D('0.00'), D('10.00')))
        self.assertEqual(rule.ride_amounts(3, None), (D('30.00'), D('0.00'), D('30.00')))

    def test_per_km_component(self):
        rule = PayoutRule(flat_fee=D('10.00'), per_km=D('3.00'))
        self.assertEqual(rule.ride_amounts(3, D('2.35')), (D('30.00'), D('7.05'), D('37.05')))

    def test_rounding_half_up_to_the_piaster(self):
        rule = PayoutRule(flat_fee=D('10.00'), per_km=D('2.333'))
        # 2.333 × 1.5 = 3.4995 → 3.50
        self.assertEqual(rule.ride_amounts(1, D('1.5'))[1], D('3.50'))
        rule = PayoutRule(flat_fee=D('12.345'), per_km=D('0'))
        self.assertEqual(rule.ride_amounts(1, None)[0], D('12.35'))

    def test_daily_minimum_topup(self):
        rule = PayoutRule(flat_fee=D('10.00'), daily_minimum=D('50.00'), minimum_vehicles=('motorcycle',))
        self.assertEqual(rule.day_topup('motorcycle', D('37.05')), D('12.95'))
        self.assertEqual(rule.day_topup('motorcycle', D('60.00')), D('0.00'))
        self.assertEqual(rule.day_topup('car', D('10.00')), D('0.00'))
        self.assertEqual(PayoutRule().day_topup('motorcycle', D('0')), D('0.00'))   # minimum off by default

    def test_settings_and_safe_fallbacks(self):
        cache.clear()
        rule = current_rule()                       # nothing configured → flat 10, no per-km, no minimum
        self.assertEqual((rule.flat_fee, rule.per_km, rule.daily_minimum), (D('10.00'), D('0.00'), D('0.00')))
        self.assertIn('delivery_driver_fee_per_km', rule.fallbacks)
        _setting('delivery_driver_fee_base', '12.5')
        _setting('delivery_driver_fee_per_km', '-3')          # negative → refused, default kept
        _setting('delivery_payout_daily_minimum', 'abc')      # unreadable → default kept
        rule = current_rule()
        self.assertEqual(rule.flat_fee, D('12.50'))
        self.assertEqual(rule.per_km, D('0.00'))
        self.assertEqual(rule.daily_minimum, D('0.00'))
        self.assertIn('delivery_driver_fee_per_km', rule.fallbacks)
        self.assertIn('delivery_payout_daily_minimum', rule.fallbacks)
        self.assertNotIn('delivery_driver_fee_base', rule.fallbacks)


class _LedgerBase(TestCase):
    def setUp(self):
        cache.clear()
        module_access.clear_cache()
        for role, actions in GRANTS.items():
            for a in actions:
                RoleModuleAccess.objects.create(role=role, module='delivery', action=a)
        self.branch = make_branch()
        self.branch2 = make_branch2()
        _, self.rider_profile, self.rider = make_user('payout_rider_a', role='delivery', branch=self.branch)
        _, other_profile, self.other_rider = make_user('payout_rider_b', role='delivery', branch=self.branch)
        self.driver = DeliveryDriver.objects.create(full_name='طيار أ', mobile='0100000101', branch=self.branch,
                                                    staff_profile=self.rider_profile, vehicle_type='motorcycle')
        self.other_driver = DeliveryDriver.objects.create(full_name='طيار ب', mobile='0100000102',
                                                          branch=self.branch, staff_profile=other_profile)
        self.driver2 = DeliveryDriver.objects.create(full_name='طيار فرع 2', mobile='0100000103', branch=self.branch2)
        _, self.manager_profile, self.manager = make_user('payout_mgr', role='pharmacist', branch=self.branch)
        _, _, self.manager2 = make_user('payout_mgr2', role='pharmacist', branch=self.branch2)
        _, self.admin_profile, self.admin = make_admin('payout_admin')
        _setting('delivery_driver_fee_base', '10')
        _setting('delivery_driver_fee_per_km', '3')

    def tearDown(self):
        module_access.clear_cache()
        cache.clear()

    def _order(self, driver=None, day=DAY, branch=None, status=DeliveryOrder.STATUS_DELIVERED, km=None,
               collected=None):
        return DeliveryOrder.objects.create(
            branch=branch or self.branch, customer_name='عميل', status=status, assigned_driver=driver,
            ordered_at=_at(day, 10), delivered_at=_at(day) if status == DeliveryOrder.STATUS_DELIVERED else None,
            delivery_distance_km=km, collected_amount=collected)

    def _build(self, day=DAY):
        return ledger.build_from_orders(day.replace(day=1), day)


class LedgerBuildTests(_LedgerBase):
    def test_build_is_idempotent(self):
        self._order(self.driver)
        self._order(self.driver, km=D('2.35'))
        self._order(self.other_driver)
        first = self._build()
        self.assertEqual(first['created'], 3)
        second = self._build()
        self.assertEqual(second['created'], 0)
        self.assertEqual(RiderPayoutRide.objects.count(), 3)
        period = RiderPayoutPeriod.objects.get(driver=self.driver)
        self.assertEqual(period.rides_count, 2)
        self.assertEqual(period.rides_amount, D('27.05'))           # 10 + (10 + 3 × 2.35)
        self.assertEqual(period.total_payout, D('27.05'))
        self.assertEqual(period.month, dt.date(2026, 10, 1))

    def test_only_delivered_orders_with_a_rider(self):
        self._order(None)                                                      # no rider
        self._order(self.driver, status=DeliveryOrder.STATUS_CANCELLED)
        self._order(self.driver, status=DeliveryOrder.STATUS_OUT)
        self.assertEqual(self._build()['created'], 0)
        self.assertFalse(RiderPayoutRide.objects.exists())

    def test_cash_collection_untouched(self):
        o = self._order(self.driver, collected=D('123.45'))
        self._build()
        o.refresh_from_db()
        self.assertEqual(o.collected_amount, D('123.45'))
        self.assertEqual(o.status, DeliveryOrder.STATUS_DELIVERED)

    def test_daily_minimum_topup_in_period(self):
        _setting('delivery_payout_daily_minimum', '50')
        self._order(self.driver)
        self._order(self.driver)
        self._order(self.driver, day=DAY + dt.timedelta(days=1))
        self._build(DAY + dt.timedelta(days=1))
        period = RiderPayoutPeriod.objects.get(driver=self.driver)
        self.assertEqual(period.rides_amount, D('30.00'))
        self.assertEqual(period.minimum_topup, D('70.00'))        # day 1: 50 − 20, day 2: 50 − 10
        self.assertEqual(period.total_payout, D('100.00'))
        self.assertEqual(period.days_count, 2)


class FinalizeLockTests(_LedgerBase):
    def _finalized_period(self):
        self._order(self.driver)
        self._build()
        period = RiderPayoutPeriod.objects.get(driver=self.driver)
        r = self.manager.post(f'{BASE}periods/{period.pk}/finalize/', {'reason': 'مراجعة الشهر'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        period.refresh_from_db()
        self.assertTrue(period.is_finalized)
        return period

    def test_finalize_needs_a_reason(self):
        self._order(self.driver)
        self._build()
        period = RiderPayoutPeriod.objects.get(driver=self.driver)
        r = self.manager.post(f'{BASE}periods/{period.pk}/finalize/', {'reason': ''}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_finalized_period_is_never_recalculated(self):
        period = self._finalized_period()
        _setting('delivery_driver_fee_base', '15')          # the rule changes after the lock
        self._order(self.driver)                            # a late order in the same month
        result = self._build()
        self.assertEqual(result['created'], 0)
        self.assertEqual(result['held_finalized'], 1)
        self.assertEqual(ledger.recalculate_open([period.pk]), 0)
        period.refresh_from_db()
        self.assertEqual(period.total_payout, D('10.00'))
        self.assertEqual(period.rides.get().amount, D('10.00'))
        # nor changed by a ride entry or an adjustment
        r = self.manager.post(f'{BASE}rides/', {'driver': self.driver.pk, 'branch': self.branch.pk,
                                                'ride_date': DAY.isoformat(), 'deliveries': 2}, format='json')
        self.assertEqual(r.status_code, 409)
        r = self.manager.post(f'{BASE}periods/{period.pk}/adjustments/',
                              {'amount': '40', 'reason': 'تحويل لفرع آخر', 'adj_date': DAY.isoformat()}, format='json')
        self.assertEqual(r.status_code, 409)
        with self.assertRaises(ledger.PeriodLocked):
            ledger.recalculate(period)
        period.refresh_from_db()
        self.assertEqual(period.total_payout, D('10.00'))

    def test_unlock_is_admin_only_with_reason_and_audited(self):
        period = self._finalized_period()
        self.assertEqual(self.manager.post(f'{BASE}periods/{period.pk}/unlock/', {'reason': 'خطأ في العدد'},
                                           format='json').status_code, 403)
        self.assertEqual(self.admin.post(f'{BASE}periods/{period.pk}/unlock/', {'reason': ''},
                                         format='json').status_code, 400)
        r = self.admin.post(f'{BASE}periods/{period.pk}/unlock/', {'reason': 'خطأ في العدد'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        period.refresh_from_db()
        self.assertFalse(period.is_finalized)
        ev = RiderPayoutAuditEvent.objects.get(action='period_unlocked')
        self.assertEqual(ev.period_id, period.pk)
        self.assertEqual(ev.actor_id, self.admin_profile.pk)
        self.assertEqual(ev.reason, 'خطأ في العدد')
        self.assertTrue(ev.before['is_finalized'])
        self.assertFalse(ev.after['is_finalized'])
        # once open again, the held order joins and the current rule applies
        _setting('delivery_driver_fee_base', '15')
        self._order(self.driver)
        self.assertEqual(self._build()['created'], 1)
        period.refresh_from_db()
        self.assertEqual(period.total_payout, D('30.00'))
        # a second unlock of an open period is refused
        self.assertEqual(self.admin.post(f'{BASE}periods/{period.pk}/unlock/', {'reason': 'مرة تانية'},
                                         format='json').status_code, 409)

    def test_finalize_audit_row(self):
        period = self._finalized_period()
        ev = RiderPayoutAuditEvent.objects.get(action='period_finalized')
        self.assertEqual(ev.actor_id, self.manager_profile.pk)
        self.assertEqual(ev.reason, 'مراجعة الشهر')
        self.assertFalse(ev.before['is_finalized'])
        self.assertTrue(ev.after['is_finalized'])
        self.assertEqual(ev.after['total_payout'], '10.00')
        self.assertEqual(period.finalized_by_id, self.manager_profile.pk)


class AdjustmentAndRideEntryTests(_LedgerBase):
    def test_adjustment_with_reason_is_audited(self):
        self._order(self.driver)
        self._build()
        period = RiderPayoutPeriod.objects.get(driver=self.driver)
        url = f'{BASE}periods/{period.pk}/adjustments/'
        self.assertEqual(self.manager.post(url, {'amount': '40', 'reason': ''}, format='json').status_code, 400)
        self.assertEqual(self.manager.post(url, {'amount': '0', 'reason': 'لا شيء هنا'}, format='json').status_code, 400)
        r = self.manager.post(url, {'amount': '40', 'reason': 'تحويل لفرع 140', 'adj_date': DAY.isoformat()},
                              format='json')
        self.assertEqual(r.status_code, 201, r.content)
        period.refresh_from_db()
        self.assertEqual(period.adjustments_total, D('40.00'))
        self.assertEqual(period.total_payout, D('50.00'))
        ev = RiderPayoutAuditEvent.objects.get(action='adjustment_added')
        self.assertEqual(ev.before['total_payout'], '10.00')
        self.assertEqual(ev.after['total_payout'], '50.00')
        self.assertEqual(ev.reason, 'تحويل لفرع 140')
        # remove it again, with a reason
        adj_id = r.data['id']
        r = self.manager.post(f'{BASE}adjustments/{adj_id}/remove/', {'reason': 'أُدخلت بالخطأ'}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        period.refresh_from_db()
        self.assertEqual(period.total_payout, D('10.00'))
        self.assertTrue(RiderPayoutAuditEvent.objects.filter(action='adjustment_removed').exists())

    def test_branch_ride_entry_priced_by_rule_and_idempotent(self):
        body = {'driver': self.driver.pk, 'branch': self.branch.pk, 'ride_date': DAY.isoformat(),
                'deliveries': 3, 'distance_km': '4.10', 'order_refs': '1201, 1202, 1203', 'client_ref': 'abc-1'}
        r = self.manager.post(f'{BASE}rides/', body, format='json')
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data['amount'], '42.30')                  # 3 × 10 + 3 × 4.10
        r2 = self.manager.post(f'{BASE}rides/', body, format='json')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.data['id'], r.data['id'])
        self.assertEqual(RiderPayoutRide.objects.count(), 1)
        self.assertTrue(RiderPayoutAuditEvent.objects.filter(action='ride_added', ride_id=r.data['id']).exists())
        # void it with a reason
        self.assertEqual(self.manager.post(f'{BASE}rides/{r.data["id"]}/void/', {'reason': ''},
                                           format='json').status_code, 400)
        r3 = self.manager.post(f'{BASE}rides/{r.data["id"]}/void/', {'reason': 'رحلة مكررة'}, format='json')
        self.assertEqual(r3.status_code, 200, r3.content)
        period = RiderPayoutPeriod.objects.get(driver=self.driver)
        self.assertEqual(period.total_payout, D('0.00'))

    def test_future_ride_refused(self):
        r = self.manager.post(f'{BASE}rides/', {'driver': self.driver.pk, 'branch': self.branch.pk,
                                                'ride_date': (timezone.localdate() + dt.timedelta(days=1)).isoformat()},
                              format='json')
        self.assertEqual(r.status_code, 400)


class PayoutPermissionTests(_LedgerBase):
    def setUp(self):
        super().setUp()
        self._order(self.driver)
        self._order(self.other_driver)
        self._order(self.driver2, branch=self.branch2)
        self._build()

    def _ids(self, client, path='rides/'):
        r = client.get(f'{BASE}{path}', {'month': MONTH})
        self.assertEqual(r.status_code, 200, r.content)
        return {row['driver'] for row in r.data['results']}

    def test_rider_sees_only_own_rows(self):
        self.assertEqual(self._ids(self.rider), {self.driver.pk})
        self.assertEqual(self._ids(self.rider, 'periods/'), {self.driver.pk})
        other = RiderPayoutPeriod.objects.get(driver=self.other_driver)
        self.assertEqual(self.rider.get(f'{BASE}periods/{other.pk}/').status_code, 404)

    def test_rider_changes_nothing(self):
        own = RiderPayoutPeriod.objects.get(driver=self.driver)
        self.assertEqual(self.rider.post(f'{BASE}rides/', {'driver': self.driver.pk, 'branch': self.branch.pk,
                                                           'ride_date': DAY.isoformat()}, format='json').status_code, 403)
        self.assertEqual(self.rider.post(f'{BASE}periods/{own.pk}/finalize/', {'reason': 'اعتماد ذاتي'},
                                         format='json').status_code, 403)
        self.assertEqual(self.rider.post(f'{BASE}periods/{own.pk}/adjustments/',
                                         {'amount': '100', 'reason': 'زيادة لنفسي'}, format='json').status_code, 403)
        self.assertEqual(self.rider.post(f'{BASE}build/', {}, format='json').status_code, 403)
        own.refresh_from_db()
        self.assertFalse(own.is_finalized)
        self.assertEqual(own.adjustments_total, D('0.00'))

    def test_manager_sees_only_their_branch(self):
        self.assertEqual(self._ids(self.manager), {self.driver.pk, self.other_driver.pk})
        self.assertEqual(self._ids(self.manager2), {self.driver2.pk})
        p2 = RiderPayoutPeriod.objects.get(driver=self.driver2)
        self.assertEqual(self.manager.get(f'{BASE}periods/{p2.pk}/').status_code, 404)
        self.assertEqual(self.manager.post(f'{BASE}periods/{p2.pk}/finalize/', {'reason': 'فرع غير فرعي'},
                                           format='json').status_code, 404)

    def test_manager_cannot_record_into_another_branch(self):
        r = self.manager.post(f'{BASE}rides/', {'driver': self.driver2.pk, 'branch': self.branch2.pk,
                                                'ride_date': DAY.isoformat()}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_viewer_reads_but_cannot_write(self):
        _, _, viewer = make_user('payout_viewer', role='viewer', branch=self.branch)
        self.assertEqual(viewer.get(f'{BASE}rides/').status_code, 200)
        period = RiderPayoutPeriod.objects.get(driver=self.driver)
        self.assertEqual(viewer.post(f'{BASE}periods/{period.pk}/finalize/', {'reason': 'مراجعة الشهر'},
                                     format='json').status_code, 403)
        self.assertEqual(viewer.post(f'{BASE}rides/', {}, format='json').status_code, 403)
        self.assertEqual(viewer.get(f'{BASE}periods/export/').status_code, 403)

    def test_no_delivery_grant_no_read(self):
        _, _, sales = make_user('payout_sales', role='salesperson', branch=self.branch)
        self.assertEqual(sales.get(f'{BASE}rides/').status_code, 403)
        self.assertEqual(sales.get(f'{BASE}periods/').status_code, 403)

    def test_build_is_narrowed_to_the_managers_branches(self):
        self._order(self.driver2, branch=self.branch2, day=DAY + dt.timedelta(days=2))
        r = self.manager.post(f'{BASE}build/', {'date_from': DAY.isoformat(),
                                                'date_to': (DAY + dt.timedelta(days=3)).isoformat()}, format='json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data['created'], 0)                       # branch 2's order is not theirs to build

    def test_export_for_managers(self):
        r = self.manager.get(f'{BASE}periods/export/', {'month': MONTH})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r['Content-Type'].startswith('application/vnd.openxmlformats'))
