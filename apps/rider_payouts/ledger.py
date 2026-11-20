"""
apps/rider_payouts/ledger.py — build, recalculate, finalize and unlock the rider payout ledger.

All writes go through here so every money change is deterministic (rule.py) and audited
(RiderPayoutAuditEvent). Nothing here touches SOFTECH, cash collection or payroll.

The lock (D-16): a finalized period is never changed. build_from_orders() skips (and counts as
`held`) a delivered order whose period is finalized; recalculate(), add_ride(), void_ride() and the
adjustment calls refuse it with PeriodLocked. Only unlock() — an admin, with a reason — reopens it.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from .models import RiderPayoutAdjustment, RiderPayoutAuditEvent, RiderPayoutPeriod, RiderPayoutRide
from .rule import ZERO, PayoutRule, current_rule, money

MIN_REASON = 5


class PeriodLocked(Exception):
    """The period is finalized: unlock it first (admin, with a reason)."""


class LedgerError(ValueError):
    """A refusal the user may read."""


def month_of(day: dt.date) -> dt.date:
    return day.replace(day=1)


def _actor_name(profile) -> str:
    if profile is None:
        return 'system'
    return (getattr(profile, 'full_name', '') or getattr(getattr(profile, 'user', None), 'username', '') or '')[:150]


def audit(action, *, actor=None, period=None, ride=None, adjustment=None, reason='', before=None, after=None):
    return RiderPayoutAuditEvent.objects.create(
        action=action, period=period, ride=ride, adjustment=adjustment, actor=actor,
        actor_name=_actor_name(actor), reason=reason or '', before=before or {}, after=after or {})


def snapshot(period: RiderPayoutPeriod) -> dict:
    return {
        'rides_count': period.rides_count, 'deliveries_count': period.deliveries_count,
        'days_count': period.days_count, 'distance_km': str(period.distance_km),
        'rides_amount': str(period.rides_amount), 'minimum_topup': str(period.minimum_topup),
        'adjustments_total': str(period.adjustments_total), 'total_payout': str(period.total_payout),
        'is_finalized': period.is_finalized,
        'finalized_at': period.finalized_at.isoformat() if period.finalized_at else None,
        'finalized_by': period.finalized_by_id, 'rule': period.rule,
    }


def ride_snapshot(ride: RiderPayoutRide) -> dict:
    return {'id': ride.pk, 'ride_date': ride.ride_date.isoformat(), 'source': ride.source,
            'order': ride.order_id, 'order_refs': ride.order_refs, 'deliveries': ride.deliveries,
            'distance_km': None if ride.distance_km is None else str(ride.distance_km),
            'flat_amount': str(ride.flat_amount), 'distance_amount': str(ride.distance_amount),
            'amount': str(ride.amount), 'is_void': ride.is_void}


def get_period(driver, branch, day: dt.date) -> RiderPayoutPeriod:
    period, _ = RiderPayoutPeriod.objects.get_or_create(driver=driver, branch=branch, month=month_of(day))
    return period


def _price(ride: RiderPayoutRide, rule: PayoutRule) -> None:
    ride.flat_amount, ride.distance_amount, ride.amount = rule.ride_amounts(ride.deliveries, ride.distance_km)


# ── recalculation ────────────────────────────────────────────────────────────

def recalculate(period: RiderPayoutPeriod, rule: PayoutRule | None = None) -> RiderPayoutPeriod:
    """Re-price every live ride with the current rule and rebuild the period totals. Refuses a
    finalized period. Call inside a transaction that holds the period row (select_for_update)."""
    if period.is_finalized:
        raise PeriodLocked(period.pk)
    rule = rule or current_rule()
    rides = list(period.rides.filter(is_void=False).order_by('ride_date', 'id'))
    by_day: dict[dt.date, Decimal] = defaultdict(lambda: ZERO)
    deliveries = 0
    distance = ZERO
    for ride in rides:
        old = (ride.flat_amount, ride.distance_amount, ride.amount)
        _price(ride, rule)
        if (ride.flat_amount, ride.distance_amount, ride.amount) != old:
            ride.save(update_fields=['flat_amount', 'distance_amount', 'amount', 'updated_at'])
        by_day[ride.ride_date] += ride.amount
        deliveries += ride.deliveries
        if ride.distance_km is not None:
            distance += ride.distance_km
    vehicle = period.driver.vehicle_type
    topup = sum((rule.day_topup(vehicle, total) for total in by_day.values()), ZERO)
    adjustments = sum((a.amount for a in period.adjustments.filter(is_removed=False)), ZERO)
    rides_amount = sum(by_day.values(), ZERO)

    period.rides_count = len(rides)
    period.deliveries_count = deliveries
    period.days_count = len(by_day)
    period.distance_km = money(distance)
    period.rides_amount = money(rides_amount)
    period.minimum_topup = money(topup)
    period.adjustments_total = money(adjustments)
    period.total_payout = money(rides_amount + topup + adjustments)
    period.rule = rule.snapshot()
    period.recalculated_at = timezone.now()
    period.save()
    return period


def _locked_period(pk) -> RiderPayoutPeriod:
    return RiderPayoutPeriod.objects.select_for_update().select_related('driver').get(pk=pk)


def recalculate_open(periods) -> int:
    """Recalculate each open period of `periods`; finalized ones are left alone. → count done."""
    rule = current_rule()
    done = 0
    for pk in [p.pk if hasattr(p, 'pk') else p for p in periods]:
        with transaction.atomic():
            period = _locked_period(pk)
            if period.is_finalized:
                continue
            recalculate(period, rule)
            done += 1
    return done


# ── build from delivered orders (idempotent) ────────────────────────────────

PAID_STATUSES = ('delivered', 'partial_delivery')


def _ride_day(order) -> dt.date:
    when = order.delivered_at or order.ordered_at
    return timezone.localdate(when) if timezone.is_aware(when) else when.date()


def build_from_orders(date_from: dt.date, date_to: dt.date, *, branch_ids=None, actor=None) -> dict:
    """One app ride per delivered order with a rider and a branch, in [date_from, date_to].

    Idempotent: an order that already has its ride is skipped (and the OneToOne key refuses a
    second row from a concurrent run). An order whose period is finalized is not added — it is
    counted as `held` and joins the ledger only after an admin unlocks that period and the build
    runs again. Open periods touched are recalculated. `branch_ids` None = every branch."""
    from apps.delivery.models import DeliveryOrder

    start = timezone.make_aware(dt.datetime.combine(date_from, dt.time.min))
    end = timezone.make_aware(dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min))
    qs = (DeliveryOrder.objects
          .filter(Q(status__in=PAID_STATUSES) | Q(status='closed', delivered_at__isnull=False))
          .filter(assigned_driver__isnull=False, branch__isnull=False, payout_ride__isnull=True)
          .filter(Q(delivered_at__gte=start, delivered_at__lt=end)
                  | Q(delivered_at__isnull=True, ordered_at__gte=start, ordered_at__lt=end))
          .select_related('assigned_driver', 'branch')
          .order_by('id'))
    if branch_ids is not None:
        qs = qs.filter(branch_id__in=branch_ids)

    created, held, duplicate = 0, 0, 0
    touched: set[int] = set()
    periods: dict[tuple, RiderPayoutPeriod] = {}
    for order in qs.iterator(chunk_size=500):
        day = _ride_day(order)
        key = (order.assigned_driver_id, order.branch_id, month_of(day))
        period = periods.get(key)
        if period is None:
            period = periods[key] = get_period(order.assigned_driver, order.branch, day)
        if period.is_finalized:
            held += 1
            continue
        zone = ' — '.join(x for x in (order.delivery_governorate, order.delivery_area) if x)
        try:
            with transaction.atomic():
                RiderPayoutRide.objects.create(
                    period=period, driver_id=order.assigned_driver_id, branch_id=order.branch_id,
                    ride_date=day, source=RiderPayoutRide.SOURCE_APP, order=order, deliveries=1,
                    distance_km=order.delivery_distance_km, zone=zone[:200],
                    order_refs=(order.order_number or '')[:500])
        except IntegrityError:
            duplicate += 1                      # a concurrent run made it first
            continue
        created += 1
        touched.add(period.pk)
    recalculated = recalculate_open(sorted(touched))
    result = {'date_from': date_from.isoformat(), 'date_to': date_to.isoformat(), 'created': created,
              'held_finalized': held, 'already_built': duplicate, 'periods_recalculated': recalculated}
    if created or held:
        audit('ledger_built', actor=actor, after=result)
    return result


# ── branch entry ─────────────────────────────────────────────────────────────

def add_ride(*, driver, branch, ride_date, deliveries, distance_km=None, zone='', order_refs='', note='',
             client_ref=None, actor=None) -> tuple[RiderPayoutRide, bool]:
    """A ride the branch records at shift end. → (ride, created). A repeated client_ref returns the
    first row instead of a duplicate."""
    if client_ref:
        existing = RiderPayoutRide.objects.filter(client_ref=client_ref).first()
        if existing is not None:
            return existing, False
    with transaction.atomic():
        period = get_period(driver, branch, ride_date)
        period = _locked_period(period.pk)
        if period.is_finalized:
            raise PeriodLocked(period.pk)
        ride = RiderPayoutRide(period=period, driver=driver, branch=branch, ride_date=ride_date,
                               source=RiderPayoutRide.SOURCE_BRANCH, deliveries=deliveries,
                               distance_km=distance_km, zone=zone[:200], order_refs=order_refs[:500],
                               note=note[:500], client_ref=client_ref or None, created_by=actor)
        _price(ride, current_rule())
        try:
            with transaction.atomic():
                ride.save()
        except IntegrityError:
            return RiderPayoutRide.objects.get(client_ref=client_ref), False
        before = snapshot(period)
        recalculate(period)
        audit('ride_added', actor=actor, period=period, ride=ride, before=before,
              after={**snapshot(period), 'ride': ride_snapshot(ride)})
    return ride, True


def void_ride(ride: RiderPayoutRide, *, reason: str, actor=None) -> RiderPayoutRide:
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON:
        raise LedgerError('اكتب سبب إلغاء الرحلة (5 أحرف على الأقل)')
    with transaction.atomic():
        period = _locked_period(ride.period_id)
        if period.is_finalized:
            raise PeriodLocked(period.pk)
        ride = RiderPayoutRide.objects.select_for_update().get(pk=ride.pk)
        if ride.is_void:
            raise LedgerError('الرحلة ملغاة بالفعل')
        before = {**snapshot(period), 'ride': ride_snapshot(ride)}
        ride.is_void, ride.void_reason, ride.voided_at, ride.voided_by = True, reason, timezone.now(), actor
        ride.save(update_fields=['is_void', 'void_reason', 'voided_at', 'voided_by', 'updated_at'])
        recalculate(period)
        audit('ride_voided', actor=actor, period=period, ride=ride, reason=reason, before=before,
              after={**snapshot(period), 'ride': ride_snapshot(ride)})
    return ride


# ── adjustments ──────────────────────────────────────────────────────────────

MAX_ADJUSTMENT = Decimal('10000')


def add_adjustment(period: RiderPayoutPeriod, *, amount: Decimal, reason: str, adj_date: dt.date,
                   actor=None) -> RiderPayoutAdjustment:
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON:
        raise LedgerError('اكتب سبب الإضافة أو الخصم (5 أحرف على الأقل)')
    amount = money(amount)
    if amount == 0 or abs(amount) > MAX_ADJUSTMENT:
        raise LedgerError('المبلغ لازم يكون غير صفر وفي حدود 10000 ج.م')
    if month_of(adj_date) != period.month:
        raise LedgerError('تاريخ الإضافة لازم يكون داخل شهر الفترة')
    with transaction.atomic():
        period = _locked_period(period.pk)
        if period.is_finalized:
            raise PeriodLocked(period.pk)
        before = snapshot(period)
        adj = RiderPayoutAdjustment.objects.create(period=period, amount=amount, reason=reason,
                                                   adj_date=adj_date, created_by=actor)
        recalculate(period)
        audit('adjustment_added', actor=actor, period=period, adjustment=adj, reason=reason, before=before,
              after={**snapshot(period), 'adjustment': {'id': adj.pk, 'amount': str(amount),
                                                        'adj_date': adj_date.isoformat()}})
    return adj


def remove_adjustment(adj: RiderPayoutAdjustment, *, reason: str, actor=None) -> RiderPayoutAdjustment:
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON:
        raise LedgerError('اكتب سبب الحذف (5 أحرف على الأقل)')
    with transaction.atomic():
        period = _locked_period(adj.period_id)
        if period.is_finalized:
            raise PeriodLocked(period.pk)
        adj = RiderPayoutAdjustment.objects.select_for_update().get(pk=adj.pk)
        if adj.is_removed:
            raise LedgerError('محذوفة بالفعل')
        before = {**snapshot(period), 'adjustment': {'id': adj.pk, 'amount': str(adj.amount)}}
        adj.is_removed, adj.removed_reason, adj.removed_at, adj.removed_by = True, reason, timezone.now(), actor
        adj.save(update_fields=['is_removed', 'removed_reason', 'removed_at', 'removed_by'])
        recalculate(period)
        audit('adjustment_removed', actor=actor, period=period, adjustment=adj, reason=reason, before=before,
              after=snapshot(period))
    return adj


# ── finalize / unlock (D-16) ─────────────────────────────────────────────────

def finalize(period: RiderPayoutPeriod, *, reason: str, actor=None) -> RiderPayoutPeriod:
    """Recalculate once more with the current rule, then lock. The numbers the manager saw are
    the numbers stored: the period keeps its rule snapshot."""
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON:
        raise LedgerError('اكتب ملاحظة الاعتماد (5 أحرف على الأقل)')
    with transaction.atomic():
        period = _locked_period(period.pk)
        if period.is_finalized:
            raise PeriodLocked(period.pk)
        before = snapshot(period)
        recalculate(period)
        period.is_finalized, period.finalized_at, period.finalized_by = True, timezone.now(), actor
        period.finalize_reason = reason
        period.save(update_fields=['is_finalized', 'finalized_at', 'finalized_by', 'finalize_reason', 'updated_at'])
        audit('period_finalized', actor=actor, period=period, reason=reason, before=before, after=snapshot(period))
    return period


def unlock(period: RiderPayoutPeriod, *, reason: str, actor=None) -> RiderPayoutPeriod:
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON:
        raise LedgerError('اكتب سبب فتح الاعتماد (5 أحرف على الأقل)')
    with transaction.atomic():
        period = _locked_period(period.pk)
        if not period.is_finalized:
            raise LedgerError('الفترة غير مُعتمدة — لا يوجد ما يُفتح')
        before = snapshot(period)
        period.is_finalized, period.finalized_at, period.finalized_by = False, None, None
        period.save(update_fields=['is_finalized', 'finalized_at', 'finalized_by', 'updated_at'])
        audit('period_unlocked', actor=actor, period=period, reason=reason, before=before, after=snapshot(period))
    return period
