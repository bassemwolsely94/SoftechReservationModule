"""
apps/rider_payouts/views.py — /api/delivery/payouts/ (C22 / P-48 rider payout ledger).

  GET  rides/                        ledger rows (filters: month, date_from, date_to, branch, driver, include_void)
  POST rides/                        the branch records a ride (driver, branch, ride_date, deliveries, …)
  POST rides/<id>/void/              void a ride with a reason (open period only)
  GET  periods/                      rider × branch × month summaries (filters: month, branch, driver, finalized)
  GET  periods/<id>/                 one period: rides, days, adjustments, audit trail
  POST periods/<id>/finalize/        lock it (reason)
  POST periods/<id>/unlock/          admin only, reason (D-16)
  POST periods/<id>/adjustments/     an extra (+) or deduction (−) with a reason
  POST adjustments/<id>/remove/      remove an adjustment with a reason
  POST build/                        add the delivered orders of a date range (idempotent)
  GET  rule/                         the payout rule numbers in force
  GET  periods/export/               the period summaries as xlsx (also as a job: periods/export/jobs/)

Permissions: apps/rider_payouts/access.py. No SOFTECH, cash or payroll write anywhere.
"""
from __future__ import annotations

import datetime as dt
import io
import uuid
from decimal import Decimal, InvalidOperation

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core import branch_scope
from core.multi_filter import multi_ids
from core.permissions import IsAdminRole, matrix_permission

from . import access, ledger
from .models import RiderPayoutAdjustment, RiderPayoutPeriod, RiderPayoutRide
from .rule import PayoutRule, current_rule

READ = matrix_permission('delivery', get=('view',), post=('create',))
EDIT = matrix_permission('delivery', post=('edit',))
MONEY = matrix_permission('delivery', post=('finalize', 'approve'))

PAGE_SIZE = 100
MAX_BUILD_DAYS = 93
DENIED = {'detail': 'ليس لديك صلاحية لهذا الإجراء في أجور الطيارين'}
LOCKED = {'detail': 'الفترة مُعتمدة ومقفولة — لا تعديل عليها إلا بعد فتح الاعتماد من مدير النظام بسبب مكتوب'}


def _forbidden():
    return Response(DENIED, status=status.HTTP_403_FORBIDDEN)


def _locked():
    return Response(LOCKED, status=status.HTTP_409_CONFLICT)


def _bad(text):
    return Response({'detail': str(text)}, status=status.HTTP_400_BAD_REQUEST)


def _date(value, name):
    try:
        return dt.date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ledger.LedgerError(f'{name}: تاريخ غير صالح (YYYY-MM-DD)')


def _month(value):
    try:
        y, m = str(value).strip().split('-')[:2]
        return dt.date(int(y), int(m), 1)
    except (TypeError, ValueError):
        raise ledger.LedgerError('month: شهر غير صالح (YYYY-MM)')


def branch_label(branch) -> str:
    if branch is None:
        return ''
    name = branch.name_ar or branch.name
    return f'{branch.softech_branch_id} · {name}' if name else branch.softech_branch_id


def _money(v):
    return None if v is None else str(v)


def ride_json(r: RiderPayoutRide) -> dict:
    return {
        'id': r.pk, 'period': r.period_id, 'ride_date': r.ride_date.isoformat(), 'source': r.source,
        'source_label': r.get_source_display(), 'driver': r.driver_id, 'driver_name': r.driver.full_name,
        'branch': r.branch_id, 'branch_label': branch_label(r.branch), 'order': r.order_id,
        'order_refs': r.order_refs, 'deliveries': r.deliveries, 'distance_km': _money(r.distance_km),
        'zone': r.zone, 'flat_amount': _money(r.flat_amount), 'distance_amount': _money(r.distance_amount),
        'amount': _money(r.amount), 'note': r.note, 'is_void': r.is_void, 'void_reason': r.void_reason,
        'period_finalized': r.period.is_finalized,
    }


def period_json(p: RiderPayoutPeriod) -> dict:
    return {
        'id': p.pk, 'month': p.month.strftime('%Y-%m'), 'driver': p.driver_id, 'driver_name': p.driver.full_name,
        'vehicle_type': p.driver.vehicle_type, 'branch': p.branch_id, 'branch_label': branch_label(p.branch),
        'rides_count': p.rides_count, 'deliveries_count': p.deliveries_count, 'days_count': p.days_count,
        'distance_km': _money(p.distance_km), 'rides_amount': _money(p.rides_amount),
        'minimum_topup': _money(p.minimum_topup), 'adjustments_total': _money(p.adjustments_total),
        'total_payout': _money(p.total_payout), 'rule': p.rule,
        'recalculated_at': p.recalculated_at.isoformat() if p.recalculated_at else None,
        'is_finalized': p.is_finalized, 'finalized_at': p.finalized_at.isoformat() if p.finalized_at else None,
        'finalized_by_name': p.finalized_by.full_name if p.finalized_by else '',
        'finalize_reason': p.finalize_reason,
    }


def _page(request, qs, to_json):
    try:
        page = max(int(request.query_params.get('page') or 1), 1)
    except ValueError:
        page = 1
    count = qs.count()
    start = (page - 1) * PAGE_SIZE
    rows = [to_json(o) for o in qs[start:start + PAGE_SIZE]]
    return {'count': count, 'page': page, 'page_size': PAGE_SIZE, 'results': rows}


# ── rides ────────────────────────────────────────────────────────────────────

def _rides(request):
    qs = access.scoped(RiderPayoutRide.objects.select_related('driver', 'branch', 'period'), request)
    p = request.query_params
    if p.get('month'):
        m = _month(p['month'])
        qs = qs.filter(period__month=m)
    if p.get('date_from'):
        qs = qs.filter(ride_date__gte=_date(p['date_from'], 'date_from'))
    if p.get('date_to'):
        qs = qs.filter(ride_date__lte=_date(p['date_to'], 'date_to'))
    branches = multi_ids(p, 'branch')
    if branches:
        qs = qs.filter(branch_id__in=branches)
    if p.get('driver'):
        qs = qs.filter(driver_id=p['driver'])
    if p.get('period'):
        qs = qs.filter(period_id=p['period'])
    if (p.get('include_void') or '').lower() not in ('1', 'true', 'yes'):
        qs = qs.filter(is_void=False)
    return qs.order_by('-ride_date', '-id')


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, READ])
def rides(request):
    if request.method == 'GET':
        try:
            return Response(_page(request, _rides(request), ride_json))
        except ledger.LedgerError as e:
            return _bad(e)
    if not access.may_write(request, 'create'):
        return _forbidden()
    from apps.delivery.models import DeliveryDriver
    from apps.branches.models import Branch
    d = request.data
    try:
        ride_date = _date(d.get('ride_date'), 'ride_date')
        if ride_date > timezone.localdate():
            raise ledger.LedgerError('تاريخ الرحلة في المستقبل')
        try:
            deliveries = int(d.get('deliveries') or 1)
        except (TypeError, ValueError):
            raise ledger.LedgerError('عدد التوصيلات غير صالح')
        if not 1 <= deliveries <= 50:
            raise ledger.LedgerError('عدد التوصيلات من 1 إلى 50')
        distance = d.get('distance_km')
        if distance in (None, ''):
            distance = None
        else:
            try:
                distance = Decimal(str(distance)).quantize(Decimal('0.01'))
            except InvalidOperation:
                raise ledger.LedgerError('المسافة غير صالحة')
            if not Decimal('0') <= distance <= Decimal('200'):
                raise ledger.LedgerError('المسافة من 0 إلى 200 كم')
    except ledger.LedgerError as e:
        return _bad(e)
    branch_id = d.get('branch')
    branch_scope.require(request.user, branch_id)          # 403 outside the user's branches
    branch = Branch.objects.filter(pk=branch_id).first()
    driver = DeliveryDriver.objects.filter(pk=d.get('driver')).first()
    if branch is None or driver is None:
        return _bad('اختر الفرع والطيار')
    try:
        client_ref = uuid.UUID(str(d.get('client_ref'))) if d.get('client_ref') else None
    except ValueError:
        client_ref = None                    # not a UUID: no retry protection, still one ride per click
    try:
        ride, created = ledger.add_ride(
            driver=driver, branch=branch, ride_date=ride_date, deliveries=deliveries, distance_km=distance,
            zone=str(d.get('zone') or ''), order_refs=str(d.get('order_refs') or ''), note=str(d.get('note') or ''),
            client_ref=client_ref, actor=access.profile_of(request))
    except ledger.PeriodLocked:
        return _locked()
    ride = RiderPayoutRide.objects.select_related('driver', 'branch', 'period').get(pk=ride.pk)
    return Response(ride_json(ride), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAuthenticated, EDIT])
def ride_void(request, pk):
    if not access.may_write(request, 'edit'):
        return _forbidden()
    ride = branch_scope.get_or_404(RiderPayoutRide, request.user, pk=pk)
    try:
        ledger.void_ride(ride, reason=request.data.get('reason'), actor=access.profile_of(request))
    except ledger.PeriodLocked:
        return _locked()
    except ledger.LedgerError as e:
        return _bad(e)
    ride = RiderPayoutRide.objects.select_related('driver', 'branch', 'period').get(pk=pk)
    return Response(ride_json(ride))


# ── periods ──────────────────────────────────────────────────────────────────

def _periods(request):
    qs = access.scoped(RiderPayoutPeriod.objects.select_related('driver', 'branch', 'finalized_by__user'),
                       request)
    p = request.query_params
    if p.get('month'):
        qs = qs.filter(month=_month(p['month']))
    branches = multi_ids(p, 'branch')
    if branches:
        qs = qs.filter(branch_id__in=branches)
    if p.get('driver'):
        qs = qs.filter(driver_id=p['driver'])
    fin = (p.get('finalized') or '').lower()
    if fin in ('true', 'false'):
        qs = qs.filter(is_finalized=(fin == 'true'))
    return qs.order_by('-month', 'branch__softech_branch_id', 'driver__full_name')


@api_view(['GET'])
@permission_classes([IsAuthenticated, READ])
def periods(request):
    try:
        return Response(_page(request, _periods(request), period_json))
    except ledger.LedgerError as e:
        return _bad(e)


def _get_period(request, pk):
    from django.shortcuts import get_object_or_404
    qs = access.scoped(RiderPayoutPeriod.objects.select_related('driver', 'branch', 'finalized_by__user'), request)
    return get_object_or_404(qs, pk=pk)


@api_view(['GET'])
@permission_classes([IsAuthenticated, READ])
def period_detail(request, pk):
    period = _get_period(request, pk)
    rides_qs = period.rides.select_related('driver', 'branch', 'period').order_by('ride_date', 'id')
    days: dict[str, dict] = {}
    for r in rides_qs:
        if r.is_void:
            continue
        day = days.setdefault(r.ride_date.isoformat(), {'date': r.ride_date.isoformat(), 'rides': 0,
                                                         'deliveries': 0, 'amount': Decimal('0')})
        day['rides'] += 1
        day['deliveries'] += r.deliveries
        day['amount'] += r.amount
    rule = PayoutRule(**_rule_from_snapshot(period.rule))
    for day in days.values():
        day['topup'] = str(rule.day_topup(period.driver.vehicle_type, day['amount']))
        day['amount'] = str(day['amount'])
    adjustments = [{'id': a.pk, 'adj_date': a.adj_date.isoformat(), 'amount': str(a.amount), 'reason': a.reason,
                    'is_removed': a.is_removed, 'removed_reason': a.removed_reason,
                    'created_by_name': a.created_by.full_name if a.created_by else ''}
                   for a in period.adjustments.select_related('created_by__user').order_by('adj_date', 'id')]
    events = [{'id': e.pk, 'action': e.action, 'action_label': e.get_action_display(), 'actor_name': e.actor_name,
               'reason': e.reason, 'before': e.before, 'after': e.after, 'created_at': e.created_at.isoformat()}
              for e in period.audit_events.order_by('-created_at', '-id')[:100]]
    return Response({**period_json(period), 'rides': [ride_json(r) for r in rides_qs],
                     'days': sorted(days.values(), key=lambda x: x['date']),
                     'adjustments': adjustments, 'audit': events})


def _rule_from_snapshot(snap: dict) -> dict:
    """The PayoutRule fields stored on a period (falls back to the defaults for a missing one)."""
    out = {}
    try:
        if snap.get('flat_fee') is not None:
            out['flat_fee'] = Decimal(snap['flat_fee'])
        if snap.get('per_km') is not None:
            out['per_km'] = Decimal(snap['per_km'])
        if snap.get('daily_minimum') is not None:
            out['daily_minimum'] = Decimal(snap['daily_minimum'])
        if snap.get('minimum_vehicles') is not None:
            out['minimum_vehicles'] = tuple(snap['minimum_vehicles'])
    except (InvalidOperation, TypeError, AttributeError):
        return {}
    return out


@api_view(['POST'])
@permission_classes([IsAuthenticated, MONEY])
def period_finalize(request, pk):
    if not access.may_write(request, 'finalize', 'approve'):
        return _forbidden()
    period = _get_period(request, pk)
    if access.own_period(request, period):
        return _forbidden()
    try:
        period = ledger.finalize(period, reason=request.data.get('reason'), actor=access.profile_of(request))
    except ledger.PeriodLocked:
        return _locked()
    except ledger.LedgerError as e:
        return _bad(e)
    return Response(period_json(_get_period(request, pk)))


@api_view(['POST'])
@permission_classes([IsAuthenticated, MONEY, IsAdminRole])
def period_unlock(request, pk):
    period = _get_period(request, pk)
    if not period.is_finalized:
        return Response({'detail': 'الفترة غير مُعتمدة — لا يوجد ما يُفتح'}, status=status.HTTP_409_CONFLICT)
    try:
        ledger.unlock(period, reason=request.data.get('reason'), actor=access.profile_of(request))
    except ledger.LedgerError as e:
        return _bad(e)
    return Response(period_json(_get_period(request, pk)))


@api_view(['POST'])
@permission_classes([IsAuthenticated, MONEY])
def period_adjustments(request, pk):
    if not access.may_write(request, 'finalize', 'approve'):
        return _forbidden()
    period = _get_period(request, pk)
    if access.own_period(request, period):
        return _forbidden()
    d = request.data
    try:
        try:
            amount = Decimal(str(d.get('amount')))
        except InvalidOperation:
            raise ledger.LedgerError('المبلغ غير صالح')
        adj_date = _date(d.get('adj_date') or timezone.localdate().isoformat(), 'adj_date')
        adj = ledger.add_adjustment(period, amount=amount, reason=d.get('reason'), adj_date=adj_date,
                                    actor=access.profile_of(request))
    except ledger.PeriodLocked:
        return _locked()
    except ledger.LedgerError as e:
        return _bad(e)
    return Response({**period_json(_get_period(request, pk)), 'adjustment_id': adj.pk}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAuthenticated, MONEY])
def adjustment_remove(request, pk):
    if not access.may_write(request, 'finalize', 'approve'):
        return _forbidden()
    from django.shortcuts import get_object_or_404
    visible = access.scoped(RiderPayoutPeriod.objects.all(), request)
    adj = get_object_or_404(RiderPayoutAdjustment.objects.select_related('period').filter(period__in=visible), pk=pk)
    if access.own_period(request, adj.period):
        return _forbidden()
    try:
        ledger.remove_adjustment(adj, reason=request.data.get('reason'), actor=access.profile_of(request))
    except ledger.PeriodLocked:
        return _locked()
    except ledger.LedgerError as e:
        return _bad(e)
    return Response(period_json(_get_period(request, adj.period_id)))


# ── build + rule ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated, EDIT])
def build(request):
    if not access.may_write(request, 'edit'):
        return _forbidden()
    d = request.data
    try:
        date_to = _date(d.get('date_to') or timezone.localdate().isoformat(), 'date_to')
        date_from = _date(d.get('date_from') or (date_to - dt.timedelta(days=6)).isoformat(), 'date_from')
        if date_from > date_to:
            raise ledger.LedgerError('من بعد إلى')
        if (date_to - date_from).days >= MAX_BUILD_DAYS:
            raise ledger.LedgerError(f'الفترة أطول من {MAX_BUILD_DAYS} يوماً')
    except ledger.LedgerError as e:
        return _bad(e)
    ids = branch_scope.narrow_ids(request.user, multi_ids(d, 'branch'))
    result = ledger.build_from_orders(date_from, date_to, branch_ids=ids, actor=access.profile_of(request))
    return Response(result)


@api_view(['GET'])
@permission_classes([IsAuthenticated, READ])
def rule(request):
    r = current_rule()
    return Response({**r.snapshot(), 'can_record': access.may_write(request, 'create'),
                     'can_build': access.may_write(request, 'edit'),
                     'can_finalize': access.may_write(request, 'finalize', 'approve'),
                     'can_unlock': getattr(access.profile_of(request), 'role', '') == 'admin',
                     'can_export': access.export_allowed(request.user),
                     'is_rider': access.rider_of(access.profile_of(request)) is not None})


# ── export ───────────────────────────────────────────────────────────────────

EXPORT_COLUMNS = [
    ('month', 'الشهر'), ('branch_label', 'الفرع'), ('driver_name', 'الطيار'), ('vehicle_type', 'المركبة'),
    ('days_count', 'أيام العمل'), ('rides_count', 'الرحلات'), ('deliveries_count', 'التوصيلات'),
    ('distance_km', 'المسافة (كم)'), ('rides_amount', 'أجر الرحلات'), ('minimum_topup', 'استكمال الحد الأدنى'),
    ('adjustments_total', 'إضافات / خصومات'), ('total_payout', 'الإجمالي المستحق'), ('status', 'الحالة'),
    ('finalized_by_name', 'اعتمد بواسطة'),
]
MAX_EXPORT = 20000


@api_view(['GET'])
@permission_classes([IsAuthenticated, READ])
def periods_export(request):
    if not access.export_allowed(request.user):
        return _forbidden()
    import openpyxl
    from core.export_safety import neutralise_formulas
    try:
        qs = _periods(request)
    except ledger.LedgerError as e:
        return _bad(e)
    count = qs.count()
    if count > MAX_EXPORT:
        return _bad(f'النتيجة {count} صفاً؛ ضيّق الفترة (الحد {MAX_EXPORT})')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'أجور الطيارين'
    ws.sheet_view.rightToLeft = True
    ws.append([label for _, label in EXPORT_COLUMNS])
    money_cols = {'distance_km', 'rides_amount', 'minimum_topup', 'adjustments_total', 'total_payout'}
    for p in qs.iterator(chunk_size=2000):
        row = period_json(p)
        row['status'] = 'مُعتمد' if p.is_finalized else 'مفتوح'
        ws.append([float(row[k]) if k in money_cols and row[k] is not None else row.get(k)
                   for k, _ in EXPORT_COLUMNS])
    buf = io.BytesIO()
    neutralise_formulas(wb).save(buf)
    out = HttpResponse(buf.getvalue(),
                       content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    out['Content-Disposition'] = 'attachment; filename="rider-payouts.xlsx"'
    return out
