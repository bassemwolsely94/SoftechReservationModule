"""
apps/supply/cases.py — SupplyCase lifecycle, daily follow-up queue, and alerts (§16/§26).

A case is the durable operational record of one unresolved need (item @ branch, or item @
network). This service:

  • evaluate_case  — runs the Phase-3 recommender and opens / refreshes / auto-resolves the
                     case from its snapshot (never recomputing anything itself)
  • transition     — human status moves, validated against an explicit map, audited
  • sweep_cases    — the daily job: evaluate every pair that has open demand or an open case
  • queue helpers  — the follow-up buckets (zero-stock, customer waiting, availability found
                     but not actioned, pending transfer/order, overdue …)
  • alerts         — actionable-only notifications through the EXISTING Notification system,
                     once per case (dedup_once), capped per sweep, gated by a setting

Rules that keep a case honest:
  • the engine may move a case ONLY among AUTO_STATUSES; once a human sets transfer_pending /
    ordered / partially_fulfilled / received, re-evaluation refreshes the numbers but never
    overwrites that status
  • a case auto-closes ONLY when a real demand run shows the net requirement is gone —
    processing today's WhatsApp list never makes a shortage disappear (§16)
  • every open/close/status/assign change is written to the existing AuditLog (§27)
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .engine import recommend
from .ingest import AUTO_MATCH_SINGLE
from .models import AvailabilityBatch, AvailabilityLine, DemandSignal, SupplyCase

logger = logging.getLogger('elrezeiky.supply')

S = SupplyCase

# Supplier availability counts as "found" only while fresh and only for a trustworthy match
# (confirmed by a human, or an auto-match at the single-add confidence bar).
AVAILABILITY_FRESH_DAYS = 7
OVERDUE_THRESHOLDS_DAYS = (3, 7)

# Company-wide (market-shortage) case scope — owner decision 2026-09-28: a network case
# opens only if a person CONFIRMED the item as a market shortage (Item.in_shortage, set on
# the «نواقص السوق» screen) OR the detector's estimated lost sales ≥ this many EGP/month
# (admin-editable SystemSetting). Everything else stays on the detector's watchlist.
NETWORK_CASE_MIN_LOST_SETTING = 'supply_network_case_min_lost_egp'
NETWORK_CASE_MIN_LOST_DEFAULT = 2000
SCOPE_CLOSE_REASON = 'خارج نطاق المتابعة'     # prefix — kept out of the "cancelled" KPI
NOTIFY_ROLES = ['admin', 'supervisor', 'purchasing']
MAX_NOTIFY_PER_KIND = 30

# Human transition map (§16). Any open case may also be fulfilled or cancelled by a human.
_HUMAN_TARGETS_FROM_AUTO = {S.STATUS_TRANSFER_PENDING, S.STATUS_ORDERED}
TRANSITIONS: dict[str, set] = {
    **{s: set(_HUMAN_TARGETS_FROM_AUTO) for s in S.AUTO_STATUSES},
    S.STATUS_TRANSFER_PENDING:    {S.STATUS_ORDERED, S.STATUS_PARTIALLY_FULFILLED, S.STATUS_RECEIVED},
    S.STATUS_ORDERED:             {S.STATUS_TRANSFER_PENDING, S.STATUS_PARTIALLY_FULFILLED, S.STATUS_RECEIVED},
    S.STATUS_PARTIALLY_FULFILLED: {S.STATUS_TRANSFER_PENDING, S.STATUS_ORDERED, S.STATUS_RECEIVED},
    S.STATUS_RECEIVED:            set(),
}
for _open in S.OPEN_STATUSES:
    TRANSITIONS.setdefault(_open, set()).update({S.STATUS_FULFILLED, S.STATUS_CANCELLED})


class CaseTransitionError(ValueError):
    pass


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def _notify_enabled(explicit=None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return bool(getattr(settings, 'SUPPLY_CASE_NOTIFY', False))


def _audit(action, case, *, staff=None, changes=None, note='', extra=None, request=None):
    try:
        from apps.audit.models import AuditLog
        AuditLog.log(action, user=staff, obj=case, changes=changes,
                     note=(note or '')[:255], extra=extra, request=request)
    except Exception:  # audit is never allowed to break the workflow
        logger.warning('supply audit log failed for case %s', getattr(case, 'pk', None))


# ── Availability matching ─────────────────────────────────────────────────────

def matching_availability(item_id):
    """Fresh, trustworthy supplier offers for this item from the availability inbox."""
    since = timezone.now() - timedelta(days=AVAILABILITY_FRESH_DAYS)
    lines = (AvailabilityLine.objects
             .filter(item_id=item_id, created_at__gte=since,
                     batch__status__in=[AvailabilityBatch.STATUS_OPEN, AvailabilityBatch.STATUS_REVIEWED])
             .filter(Q(is_confirmed=True) | Q(match_score__gte=AUTO_MATCH_SINGLE))
             .select_related('batch', 'batch__supplier'))
    # An unconfirmed match the safety guard flagged is not trustworthy availability.
    return [ln for ln in lines
            if ln.is_confirmed or not (ln.match_reason or {}).get('review_flags')]


# ── Evaluate (open / refresh / auto-resolve) ──────────────────────────────────

def _open_case_qs(item_id, branch_id):
    qs = SupplyCase.objects.filter(item_id=item_id, status__in=list(S.OPEN_STATUSES))
    return qs.filter(branch_id=branch_id) if branch_id is not None else qs.filter(branch__isnull=True)


def _auto_status(case, *, created: bool) -> str:
    if case.has_availability:
        return S.STATUS_AVAILABILITY_FOUND
    if _f(case.internal_cover) > 0:
        return S.STATUS_AWAITING_DECISION
    return S.STATUS_DETECTED if created else S.STATUS_SEARCHING


def evaluate_case(item_id, branch_id=None, *, scope_reason: str = '') -> dict:
    """Evaluate one (item, branch) need and open / refresh / auto-resolve its case.
    ``scope_reason`` (company-wide cases) says WHY the item is followed up at all — it is
    shown first among the case's reasons.

    Returns {'case': SupplyCase|None, 'event': 'opened'|'updated'|'closed'|'none',
             'status_from': str|None, 'status_to': str|None}."""
    item_id = int(item_id)
    offers = matching_availability(item_id)
    rec = recommend(item_id, branch_id=branch_id, availability_lines=offers)
    L = rec['quantity_ledger']
    required = _f(L['required'])
    now = timezone.now()

    with transaction.atomic():
        case = _open_case_qs(item_id, branch_id).select_for_update().first()

        if case is None:
            if required <= 0:
                return {'case': None, 'event': 'none', 'status_from': None, 'status_to': None}
            case = SupplyCase(item_id=item_id, branch_id=branch_id, status=S.STATUS_DETECTED)
            created = True
        else:
            created = False
            # Auto-resolve ONLY on real data: the need is gone on an actual demand run.
            if rec['has_run'] and required <= 0:
                prev = case.status
                case.status = S.STATUS_FULFILLED
                case.closed_at = now
                case.status_changed_at = now
                case.close_reason = 'تمت تلبية الاحتياج (الاحتياج الصافي = 0 في آخر تشغيل للمحرك)'
                _apply_snapshot(case, rec, offers, now, scope_reason)
                case.save()
                case.availability_lines.set(offers)
                _settle_orders(case, case.status)
                _audit('supply_case_closed', case, changes={'status': [prev, case.status]},
                       note='auto: need resolved')
                return {'case': case, 'event': 'closed', 'status_from': prev,
                        'status_to': case.status}

        prev = None if created else case.status
        _apply_snapshot(case, rec, offers, now, scope_reason)
        if created or case.status in S.AUTO_STATUSES:
            new_status = _auto_status(case, created=created)
            if new_status != case.status or created:
                case.status = new_status
                case.status_changed_at = now
        case.save()
        case.availability_lines.set(offers)

    if created:
        _audit('supply_case_opened', case, extra={'status': case.status, **_audit_ledger(L)},
               note='auto: need detected')
        return {'case': case, 'event': 'opened', 'status_from': None, 'status_to': case.status}
    if prev != case.status:
        _audit('supply_case_status_changed', case, changes={'status': [prev, case.status]},
               note='auto: re-evaluated')
    return {'case': case, 'event': 'updated', 'status_from': prev, 'status_to': case.status}


def _apply_snapshot(case, rec, offers, now, scope_reason=''):
    L = rec['quantity_ledger']
    sc = rec['scarcity']
    case.required_qty = L['required']
    case.residual_gap = L['residual_gap']
    case.internal_cover = L['internally_allocated']
    case.customer_demand = L['customer_demand']
    case.current_stock = L['current_stock']
    case.scarcity_score = int(sc['score'])
    case.is_urgent = bool(sc['urgent'])
    case.has_availability = bool(offers)
    case.last_ledger = L
    case.last_reasons = ([scope_reason] if scope_reason else []) + list(rec['reasons'])
    case.last_evaluated_at = now


def _audit_ledger(L) -> dict:
    return {k: L.get(k) for k in ('required', 'residual_gap', 'internally_allocated',
                                  'customer_demand', 'current_stock')}


# ── Human transitions ─────────────────────────────────────────────────────────

def allowed_targets(case) -> list:
    return sorted(TRANSITIONS.get(case.status, set()))


def transition(case, new_status, *, staff=None, reason='', request=None) -> SupplyCase:
    """Move a case to ``new_status`` if the transition map allows it. Cancelling requires a
    reason (§40). Row-locked so two operators can't race the same case (§31)."""
    reason = (reason or '').strip()
    with transaction.atomic():
        case = SupplyCase.objects.select_for_update().get(pk=case.pk)
        if new_status not in TRANSITIONS.get(case.status, set()):
            raise CaseTransitionError(
                f'لا يمكن الانتقال من «{case.get_status_display()}» إلى «{new_status}».')
        if new_status == S.STATUS_CANCELLED and not reason:
            raise CaseTransitionError('يجب ذكر سبب الإلغاء.')
        prev = case.status
        now = timezone.now()
        case.status = new_status
        case.status_changed_at = now
        if new_status in S.TERMINAL_STATUSES:
            case.closed_at = now
            case.close_reason = reason[:255]
        case.save(update_fields=['status', 'status_changed_at', 'closed_at', 'close_reason', 'updated_at'])
        _settle_orders(case, new_status)
    action = 'supply_case_closed' if new_status in S.TERMINAL_STATUSES else 'supply_case_status_changed'
    _audit(action, case, staff=staff, changes={'status': [prev, new_status]},
           note=reason or 'manual', request=request)
    return case


def _settle_orders(case, new_status):
    """Once goods are received (or the case is cancelled), the case's open purchase
    decisions must stop counting as pending incoming in net_demand."""
    if new_status in (S.STATUS_RECEIVED, S.STATUS_FULFILLED, S.STATUS_CANCELLED):
        from .execution import close_open_orders_for_case   # local: execution imports cases
        close_open_orders_for_case(case, received=(new_status != S.STATUS_CANCELLED))


def assign(case, assignee, *, staff=None, request=None) -> SupplyCase:
    prev = case.assigned_to_id
    case.assigned_to = assignee
    case.save(update_fields=['assigned_to', 'updated_at'])
    _audit('supply_case_assigned', case, staff=staff,
           changes={'assigned_to': [prev, getattr(assignee, 'pk', None)]}, request=request)
    return case


# ── Daily sweep ───────────────────────────────────────────────────────────────

def network_case_threshold() -> float:
    """Min estimated lost sales (EGP/month) for an UNconfirmed market-shortage item to get
    a company-wide case. Admin-editable SystemSetting, default 2,000."""
    try:
        from apps.config.models import SystemSetting
        return float(SystemSetting.get(NETWORK_CASE_MIN_LOST_SETTING, NETWORK_CASE_MIN_LOST_DEFAULT))
    except Exception:
        return float(NETWORK_CASE_MIN_LOST_DEFAULT)


def network_scope(item_ids) -> dict:
    """{item_id: why it is followed up} for the company-wide items that QUALIFY for a case:
    confirmed on the «نواقص السوق» screen, OR the detector's estimated lost sales ≥ threshold.
    Reuses the market-shortage detector (apps.purchasing.shortage) — no recomputation."""
    from apps.catalog.models import Item
    ids = {int(i) for i in item_ids if i}
    if not ids:
        return {}
    threshold = network_case_threshold()
    confirmed = set(Item.objects.filter(pk__in=ids, in_shortage=True).values_list('id', flat=True))
    try:
        from apps.purchasing.shortage import compute_shortage_candidates
        lost = {c.item_id: c.lost_monthly for c in compute_shortage_candidates() if c.item_id in ids}
    except Exception as exc:
        logger.warning('network_scope: detector unavailable (%s) — confirmed items only', exc)
        lost = {}
    out = {}
    for i in ids:
        if i in confirmed:
            out[i] = 'سبب المتابعة: الصنف مؤكَّد كنقص سوق (شاشة نواقص السوق)'
        elif lost.get(i, 0) >= threshold:
            out[i] = (f'سبب المتابعة: مبيعات ضائعة مقدّرة ~{lost[i]:,.0f} ج.م/شهر '
                      f'(الحد {threshold:,.0f})')
    return out


def _statistical_items() -> set:
    return set(DemandSignal.objects
               .filter(status=DemandSignal.STATUS_OPEN, item__isnull=False,
                       provenance_class=DemandSignal.CLASS_STATISTICAL)
               .values_list('item_id', flat=True).distinct())


def candidate_pairs(*, scope=None) -> list:
    """Every (item_id, branch_id) worth evaluating: open branch/customer demand at a branch
    (always), company-wide market-shortage items that QUALIFY (network_scope) and have no
    branch-level need, and every open case (so an open case is re-checked and can resolve)."""
    branch_pairs = set(
        DemandSignal.objects
        .filter(status=DemandSignal.STATUS_OPEN, item__isnull=False, branch__isnull=False,
                provenance_class__in=[DemandSignal.CLASS_CUSTOMER, DemandSignal.CLASS_BRANCH])
        .values_list('item_id', 'branch_id').distinct()
    )
    items_with_branch_need = {i for i, _ in branch_pairs}
    stat = _statistical_items()
    if scope is None:
        scope = network_scope(stat)
    network_pairs = {(i, None) for i in stat
                     if i in scope and i not in items_with_branch_need}
    open_pairs = set(SupplyCase.objects.filter(status__in=list(S.OPEN_STATUSES))
                     .values_list('item_id', 'branch_id'))
    return sorted(branch_pairs | network_pairs | open_pairs,
                  key=lambda p: (p[0], p[1] if p[1] is not None else -1))


def close_out_of_scope(scope) -> int:
    """Close open company-wide cases whose item no longer qualifies (not confirmed and below
    the lost-sales threshold). Only cases still in a SYSTEM status — anything a person has
    moved on (ordered / transfer pending / …) is never closed automatically. Each closure is
    a normal audited transition with a recorded reason (nothing is deleted)."""
    threshold = network_case_threshold()
    reason = (f'{SCOPE_CLOSE_REASON}: نقص سوق غير مؤكَّد وخسارة مقدّرة أقل من '
              f'{threshold:,.0f} ج.م/شهر — يبقى في قائمة مراقبة نواقص السوق')
    closed = 0
    for case in SupplyCase.objects.filter(branch__isnull=True, status__in=list(S.AUTO_STATUSES)):
        if case.item_id not in scope:
            transition(case, S.STATUS_CANCELLED, reason=reason)
            closed += 1
    return closed


def sweep_cases(*, notify=None, limit=None) -> dict:
    """Close out-of-scope company-wide cases, then evaluate every candidate pair.
    Returns counts. Alerts only if enabled."""
    counts = {'evaluated': 0, 'opened': 0, 'updated': 0, 'closed': 0, 'errors': 0,
              'out_of_scope': 0, 'notified': 0}
    open_network = set(SupplyCase.objects.filter(branch__isnull=True,
                                                 status__in=list(S.OPEN_STATUSES))
                       .values_list('item_id', flat=True))
    scope = network_scope(_statistical_items() | open_network)
    counts['out_of_scope'] = close_out_of_scope(scope)

    results = []
    for n, (item_id, branch_id) in enumerate(candidate_pairs(scope=scope)):
        if limit and n >= limit:
            break
        try:
            r = evaluate_case(item_id, branch_id,
                              scope_reason=scope.get(item_id, '') if branch_id is None else '')
        except Exception as exc:
            counts['errors'] += 1
            logger.exception('supply sweep failed for item=%s branch=%s: %s', item_id, branch_id, exc)
            continue
        counts['evaluated'] += 1
        if r['event'] in counts:
            counts[r['event']] += 1
        results.append(r)

    if _notify_enabled(notify):
        counts['notified'] = notify_actionable(results)
    return counts


# ── Follow-up queue ───────────────────────────────────────────────────────────

BUCKETS = {
    'urgent':             lambda qs: qs.filter(is_urgent=True),
    'zero_stock':         lambda qs: qs.filter(current_stock__lte=0),
    'customer_waiting':   lambda qs: qs.filter(customer_demand__gt=0),
    'availability_found': lambda qs: qs.filter(status=S.STATUS_AVAILABILITY_FOUND),
    'awaiting_decision':  lambda qs: qs.filter(status=S.STATUS_AWAITING_DECISION),
    'transfer_pending':   lambda qs: qs.filter(status=S.STATUS_TRANSFER_PENDING),
    'ordered':            lambda qs: qs.filter(status=S.STATUS_ORDERED),
    'partially_fulfilled': lambda qs: qs.filter(status=S.STATUS_PARTIALLY_FULFILLED),
    'searching':          lambda qs: qs.filter(status__in=[S.STATUS_DETECTED, S.STATUS_SEARCHING]),
    'overdue':            lambda qs: qs.filter(
        first_detected_at__lte=timezone.now() - timedelta(days=OVERDUE_THRESHOLDS_DAYS[0])),
}


def open_queue(*, bucket=None, branch_id=None):
    """Open cases in follow-up priority order: urgent → scarcity → oldest → biggest gap."""
    qs = (SupplyCase.objects.filter(status__in=list(S.OPEN_STATUSES))
          .select_related('item', 'branch', 'assigned_to__user'))
    if branch_id:
        qs = qs.filter(branch_id=branch_id)
    if bucket:
        fn = BUCKETS.get(bucket)
        if fn is None:
            raise ValueError(f'unknown bucket: {bucket}')
        qs = fn(qs)
    return qs.order_by('-is_urgent', '-scarcity_score', 'first_detected_at', '-residual_gap')


def queue_summary(*, branch_id=None) -> dict:
    base = open_queue(branch_id=branch_id)
    return {'total': base.count(), **{k: fn(base).count() for k, fn in BUCKETS.items()}}


# ── Actionable alerts (existing Notification system, no spam) ─────────────────

def _send(title, body, dedup_key) -> int:
    from apps.notifications.models import Notification
    return Notification.send_to_roles(roles=NOTIFY_ROLES, notification_type='system',
                                      title=title, body=body, dedup_key=dedup_key,
                                      dedup_once=True)


def _label(case) -> str:
    where = (case.branch.name_ar or case.branch.name) if case.branch_id else 'الشبكة'
    return f'{case.item.softech_id} — {case.item.name} @ {where}'


def notify_actionable(results) -> int:
    """Send only ACTIONABLE alerts, once per case per kind (dedup_once), capped per sweep:
       • a newly opened URGENT case (zero stock + waiting customer / market shortage)
       • supplier availability found for a case with waiting customers
       • a case unresolved for 3 / 7 days"""
    sent = 0
    urgent = [r['case'] for r in results if r['event'] == 'opened' and r['case'].is_urgent]
    for c in urgent[:MAX_NOTIFY_PER_KIND]:
        sent += _send('🚨 صنف حرج بلا رصيد',
                      f'{_label(c)} · احتياج {_f(c.required_qty):.0f}'
                      + (f' · {_f(c.customer_demand):.0f} لعملاء منتظرين' if _f(c.customer_demand) else ''),
                      f'supply_case_urgent_{c.pk}')

    found = [r['case'] for r in results
             if r['case'] is not None and r['status_to'] == S.STATUS_AVAILABILITY_FOUND
             and r['status_from'] != S.STATUS_AVAILABILITY_FOUND and _f(r['case'].customer_demand) > 0]
    for c in found[:MAX_NOTIFY_PER_KIND]:
        sent += _send('📦 توفّر لدى مورد يطابق طلب عملاء',
                      f'{_label(c)} · {_f(c.customer_demand):.0f} لعملاء منتظرين',
                      f'supply_case_avail_{c.pk}')

    overdue_sent = 0
    for c in open_queue(bucket='overdue'):
        if overdue_sent >= MAX_NOTIFY_PER_KIND:
            break
        days = c.days_open
        threshold = max((t for t in OVERDUE_THRESHOLDS_DAYS if days >= t), default=None)
        if threshold is None:
            continue
        n = _send(f'⏳ نقص لم يُحلّ منذ {threshold} أيام',
                  f'{_label(c)} · الحالة: {c.get_status_display()}',
                  f'supply_case_overdue_{c.pk}_{threshold}')
        sent += n
        overdue_sent += 1 if n else 0
    return sent
