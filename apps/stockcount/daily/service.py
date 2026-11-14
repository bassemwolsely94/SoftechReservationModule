"""
apps/stockcount/daily/service.py — the daily-count workflow (business rules live here, not in React).

  generate(branch, day)   one blind list per salesperson on the branch roster (approved leave skipped)
  record_count(...)       one immutable attempt; expected read LIVE from SOFTECH for that one item at
                          that moment (falls back to the ItemStock mirror, flagged); auto-escalation
  request_recount / accept / escalate   branch manager → central auditor review
  close_day(branch, day)  unfinished picks → «لم يُنجز»; sessions closed
  run_job(now)            scheduler entry: generate after job_hour, close after the branch closes

Never writes to SOFTECH. Stock corrections stay a manual step in SOFTECH (needs_softech_adjustment
is only a reminder).
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings as dj_settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.stockcount.engine import fetch_stock_balance
from core.threads import ContextThreadPoolExecutor
from . import picker

logger = logging.getLogger(__name__)

REVIEW_REASONS = {
    'loss':        'فقد / سرقة',
    'entry_error': 'خطأ إدخال في SOFTECH',
    'no_invoice':  'صرف بدون فاتورة',
    'damaged':     'تالف',
    'transfer':    'تحويل لم يُسجل',
    'count_error': 'خطأ في العد',
    'other':       'سبب آخر',
}
OPEN_FOR_COUNT = ('pending', 'recount')
ROUNDING = Decimal('0.002')
# The live SOFTECH read happens while the phone waits: past this many seconds the count is stored
# against the local mirror instead (a hung SOFTECH must not turn into a gateway timeout).
LIVE_READ_TIMEOUT = 6
_live_pool = ContextThreadPoolExecutor(max_workers=4, thread_name_prefix='daily-count-live')


class DailyCountError(Exception):
    """A rule refused the action — message is Arabic and safe to show."""


def enabled() -> bool:
    return bool(getattr(dj_settings, 'DAILY_COUNT_ENABLED', False))


def cairo_today() -> dt.date:
    return now_local().date()


def now_local():
    return timezone.localtime()


def branch_enabled(branch) -> bool:
    from apps.branches.models import BranchSettings
    if not (branch and branch.is_active and getattr(branch, 'is_operational', True)):
        return False
    return BranchSettings.for_branch(branch).daily_count_enabled


def _audit(action, user, obj, **kw):
    from apps.audit.models import AuditLog
    AuditLog.log(action, user=user, obj=obj, **kw)


# ── Generation ────────────────────────────────────────────────────────────────

def roster(branch, s):
    from apps.users.models import StaffProfile
    roles = ['salesperson'] + (['pharmacist'] if s.include_pharmacists else [])
    return list(StaffProfile.objects.filter(branch=branch, is_active=True, user__is_active=True, role__in=roles)
                .order_by('pk'))


def on_leave_ids(profile_ids, day) -> set:
    from apps.hr.models import LeaveRequest
    return set(LeaveRequest.objects.filter(staff_id__in=profile_ids, status=LeaveRequest.STATUS_APPROVED,
                                           start_date__lte=day, end_date__gte=day)
               .values_list('staff_id', flat=True))


def generate(branch, day: dt.date, by=None) -> int:
    """Create today's lists for this branch. Idempotent: people who already have a list keep it,
    items already picked today are not drawn again. Returns the number of picks created."""
    from apps.stockcount.models import DailyCountPick, DailyCountSettings, StockCountSession
    if not branch_enabled(branch):
        return 0
    s = DailyCountSettings.get()
    code = branch.softech_branch_id
    people = roster(branch, s)
    away = on_leave_ids([p.pk for p in people], day)
    have = set(StockCountSession.objects.filter(mode='daily', branch_code=code, count_date=day)
               .values_list('assigned_to_id', flat=True))
    people = [p for p in people if p.pk not in away and p.pk not in have]
    if not people:
        return 0
    taken = set(DailyCountPick.objects.filter(session__mode='daily', session__branch_code=code,
                                              session__count_date=day).values_list('item_code', flat=True))
    cands = [c for c in picker.candidates(branch, day, s) if c.item_code not in taken]
    dealt = picker.draw(cands, [p.pk for p in people], s.items_per_person, seed=f'{code}|{day.isoformat()}')
    created = 0
    for p in people:
        mine = dealt.get(p.pk) or []
        try:
            with transaction.atomic():
                session = StockCountSession.objects.create(
                    name=f'جرد يومي — {p.full_name} — {day.isoformat()}', mode='daily', status='snapshot_taken',
                    branch_code=code, assigned_to=p, count_date=day, created_by=by,
                    item_codes_filter=[c.item_code for c in mine], item_count=len(mine))
                DailyCountPick.objects.bulk_create([
                    DailyCountPick(session=session, item_code=c.item_code, item_name=c.item_name,
                                   reasons=c.reasons, weight=Decimal(str(c.weight)), ask_expiry=c.ask_expiry)
                    for c in mine])
        except IntegrityError:          # a concurrent run created it first
            continue
        created += len(mine)
    _audit('daily_count_generated', by, branch,
           extra={'date': day.isoformat(), 'people': [p.pk for p in people], 'picks': created,
                  'on_leave': sorted(away)})
    return created


# ── Counting ──────────────────────────────────────────────────────────────────

def parse_qty(value) -> Decimal:
    try:
        q = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        raise DailyCountError('كمية غير صالحة')
    if not q.is_finite() or q < 0:
        raise DailyCountError('الكمية يجب ألا تكون سالبة')
    return q.quantize(Decimal('0.001'))


def session_open(session, now=None) -> bool:
    """A daily list is open until its branch closes that business day (lists of branches that
    close after midnight stay open past midnight)."""
    from apps.branches.models import Branch
    if session.status == 'closed':
        return False
    branch = Branch.objects.filter(softech_branch_id=session.branch_code).first()
    return bool(branch) and (now or now_local()) < close_at(branch, session.count_date)


def counter_sessions(profile, now=None):
    """The counter's open daily lists (today's, or yesterday's while the branch is still open)."""
    from apps.stockcount.models import StockCountSession
    now = now or now_local()
    rows = (StockCountSession.objects.filter(mode='daily', assigned_to=profile,
                                             count_date__gte=now.date() - dt.timedelta(days=1))
            .exclude(status='closed'))
    return [x for x in rows if session_open(x, now)]


def can_count(pick, profile) -> bool:
    """Once counted, an item is done for the counter (no silent re-counts); a reviewer's recount
    reopens it for the person it was handed to."""
    if profile is None or not profile.is_active:
        return False
    session = pick.session
    if pick.status == 'recount':
        return pick.recount_by_id == profile.pk or (pick.recount_by_id is None and session.assigned_to_id == profile.pk)
    return pick.status == 'pending' and session.assigned_to_id == profile.pk and session_open(session)


def read_expected(branch_code: str, item_code: str):
    """(qty, source). Live SOFTECH balance for this one item; the local mirror if SOFTECH can't answer."""
    try:
        live = _live_pool.submit(fetch_stock_balance, branch_code, [item_code]).result(timeout=LIVE_READ_TIMEOUT)
        return Decimal(live.get(item_code, Decimal('0'))), 'live'
    except Exception as exc:          # SOFTECH down / slow (incl. the timeout) — never lose the count
        logger.warning('daily count: live balance failed for %s/%s: %s', branch_code, item_code, exc)
    from django.db.models import Sum
    from apps.catalog.models import ItemStock
    qty = (ItemStock.objects.filter(branch__softech_branch_id=branch_code, item__softech_id=item_code)
           .exclude(softech_store_code__in=picker.QUARANTINE_STORES)
           .aggregate(t=Sum('quantity_on_hand'))['t']) or Decimal('0')
    return Decimal(qty), 'mirror'


def is_branch_manager(profile, branch_code: str) -> bool:
    from apps.stock_audit.access import active_grant, own_branch_codes
    return bool(profile and active_grant(profile) and branch_code in own_branch_codes(profile))


def branch_has_manager(branch_code: str) -> bool:
    from apps.stock_audit.access import own_branch_codes
    from apps.stock_audit.models import StockAuditAccess
    for g in StockAuditAccess.objects.filter(revoked_at__isnull=True, staff__is_active=True).select_related('staff'):
        if branch_code in own_branch_codes(g.staff):
            return True
    return False


def _is_reviewer(profile, branch_code) -> bool:
    from apps.stock_audit.access import Access
    return is_branch_manager(profile, branch_code) or Access(profile.user).management


def _escalation_reason(pick, attempt, profile, s) -> str:
    from apps.stockcount.models import DailyCountAttempt
    code = pick.session.branch_code
    if attempt.value_egp >= s.escalate_value_egp:
        return f'قيمة الفرق {attempt.value_egp} ج.م ≥ {s.escalate_value_egp} ج.م'
    since = timezone.now() - dt.timedelta(days=s.escalate_repeat_days)
    repeats = (DailyCountAttempt.objects.filter(pick__session__branch_code=code, pick__item_code=pick.item_code,
                                                created_at__gte=since)
               .exclude(difference__gte=-s.match_tolerance, difference__lte=s.match_tolerance)
               .values('pick_id').distinct().count())
    if repeats >= s.escalate_repeat_count:
        return f'فروق متكررة على الصنف ({repeats} خلال {s.escalate_repeat_days} يوم)'
    if is_branch_manager(profile, code):
        return 'جرد مدير الفرع نفسه — يراجعه المراجع المركزي'
    if not branch_has_manager(code):
        return 'لا يوجد مدير فرع مُعيَّن للمراجعة'
    return ''


def record_count(pick, profile, counted_qty, physical_expiry=None, client_token=None):
    """One immutable attempt. Same client_token twice (double tap / offline replay) → the first one."""
    from apps.catalog.models import Item
    from apps.stockcount.models import DailyCountAttempt, DailyCountPick, DailyCountSettings, StockCountSnapshot

    if client_token:
        prior = DailyCountAttempt.objects.filter(client_token=client_token).select_related('pick').first()
        if prior:
            if prior.pick_id != pick.pk:
                raise DailyCountError('رمز إرسال مكرر')
            return prior
    if not can_count(pick, profile):
        raise DailyCountError('هذا الصنف ليس متاحاً للجرد الآن')
    qty = parse_qty(counted_qty)
    expiry = None
    if physical_expiry:
        try:
            expiry = dt.date.fromisoformat(str(physical_expiry)[:10])
        except ValueError:
            raise DailyCountError('تاريخ صلاحية غير صالح')

    s = DailyCountSettings.get()
    session = pick.session
    expected, source = read_expected(session.branch_code, pick.item_code)
    diff = qty - expected
    cost = Item.objects.filter(softech_id=pick.item_code).values_list('cost_price', flat=True).first() or Decimal('0')
    now = timezone.now()
    with transaction.atomic():
        pick = DailyCountPick.objects.select_for_update().select_related('session').get(pk=pick.pk)
        session = pick.session
        if not can_count(pick, profile):      # the day closed / a reviewer acted while we read SOFTECH
            raise DailyCountError('هذا الصنف ليس متاحاً للجرد الآن')
        try:
            with transaction.atomic():
                attempt = DailyCountAttempt.objects.create(
                    pick=pick, counted_by=profile, counted_qty=qty, expected_qty=expected,
                    expected_source=source, expected_read_at=now, difference=diff,
                    value_egp=(abs(diff) * cost).quantize(Decimal('0.01')),
                    physical_expiry=expiry, client_token=client_token or None)
        except IntegrityError:
            if not client_token:
                raise
            return DailyCountAttempt.objects.get(client_token=client_token)
        old = pick.status
        match = abs(diff) <= max(s.match_tolerance, ROUNDING)   # strips → packs rounds to 0.001
        reason = '' if match else _escalation_reason(pick, attempt, profile, s)
        if not reason and old == 'recount' and _is_reviewer(profile, session.branch_code):
            # a reviewer who has seen the expected quantity recounting it themselves is not blind
            reason = 'إعادة جرد بواسطة مراجع — يراجعها المراجع المركزي'
        if reason or (pick.escalated and not match):
            pick.escalated = True
            pick.escalation_reason = reason or pick.escalation_reason
            pick.status = 'escalated'
        else:
            pick.status = 'counted'
        pick.latest_attempt = attempt
        pick.save(update_fields=['status', 'escalated', 'escalation_reason', 'latest_attempt', 'updated_at'])
        # The variance screens + stock-audit check read the snapshot row: it mirrors the latest attempt.
        StockCountSnapshot.objects.update_or_create(
            session=session, item_code=pick.item_code,
            defaults={'item_name': pick.item_name, 'branch_code': session.branch_code, 'expected_qty': expected,
                      'counted_qty': qty, 'difference': diff,
                      'variance_type': 'ok' if match else ('surplus' if diff > 0 else 'deficit'),
                      **({'physical_expiry': expiry} if expiry else {})})
        fields = ['status', 'uploaded_at', 'uploaded_by', 'variance_at', 'updated_at']
        if session.snapshot_at is None:
            session.snapshot_at = now
            fields.append('snapshot_at')
        session.uploaded_at, session.uploaded_by, session.variance_at = now, profile, now
        if session.status != 'closed':
            session.status = 'uploaded'
        session.save(update_fields=fields)
    _audit('daily_count_counted', profile, pick,
           old_data={'status': old},
           new_data={'status': pick.status, 'counted': str(qty), 'expected': str(expected), 'source': source,
                     'difference': str(diff), 'value_egp': str(attempt.value_egp)},
           note=pick.escalation_reason if pick.status == 'escalated' else '')
    return attempt


# ── Review ────────────────────────────────────────────────────────────────────

def _check_reviewable(pick, acc):
    if pick.session.status == 'closed' and pick.status == 'missed':
        raise DailyCountError('هذا الصنف لم يُجرد')
    if pick.latest_attempt_id is None:
        raise DailyCountError('لم يُجرد الصنف بعد')
    if pick.escalated and not acc.management:
        raise PermissionError('هذا الفرق محال للمراجع المركزي')


def request_recount(pick, acc, assignee=None, note=''):
    from apps.users.models import StaffProfile
    _check_reviewable(pick, acc)
    if pick.status not in ('counted', 'escalated', 'accepted'):
        raise DailyCountError('لا يمكن طلب إعادة الجرد في هذه الحالة')
    if assignee is not None and acc.profile is not None and assignee.pk == acc.profile.pk:
        raise DailyCountError('لا يمكن أن تعيد جرد فرق بتراجعه بنفسك — اختر موظفاً آخر')
    if assignee is not None:
        ok = StaffProfile.objects.filter(pk=assignee.pk, is_active=True,
                                         branch__softech_branch_id=pick.session.branch_code).exists()
        if not ok:
            raise DailyCountError('الموظف ليس من هذا الفرع')
    old = pick.status
    pick.status, pick.recount_by = 'recount', assignee or pick.session.assigned_to
    pick.review_note = note or pick.review_note
    pick.save(update_fields=['status', 'recount_by', 'review_note', 'updated_at'])
    _audit('daily_count_recount', acc.profile, pick, old_data={'status': old},
           new_data={'status': 'recount', 'recount_by': pick.recount_by_id}, note=note[:255])
    return pick


def accept(pick, acc, reason, note='', needs_softech_adjustment=False):
    _check_reviewable(pick, acc)
    if reason not in REVIEW_REASONS:
        raise DailyCountError('اختر سبب الفرق')
    if pick.status not in ('counted', 'escalated'):
        raise DailyCountError('لا يمكن اعتماد الصنف في هذه الحالة')
    old = pick.status
    pick.status, pick.review_reason, pick.review_note = 'accepted', reason, note
    pick.needs_softech_adjustment = bool(needs_softech_adjustment)
    pick.reviewed_by, pick.reviewed_at = acc.profile, timezone.now()
    pick.save(update_fields=['status', 'review_reason', 'review_note', 'needs_softech_adjustment',
                             'reviewed_by', 'reviewed_at', 'updated_at'])
    _audit('daily_count_accepted', acc.profile, pick, old_data={'status': old},
           new_data={'status': 'accepted', 'reason': reason, 'needs_softech_adjustment': pick.needs_softech_adjustment},
           note=note[:255])
    return pick


def escalate(pick, acc, note=''):
    _check_reviewable(pick, acc)
    if pick.status != 'counted':
        raise DailyCountError('لا يمكن إحالة الصنف في هذه الحالة')
    pick.status, pick.escalated = 'escalated', True
    pick.escalation_reason = f'إحالة يدوية: {note}'[:255] if note else 'إحالة يدوية من مدير الفرع'
    pick.save(update_fields=['status', 'escalated', 'escalation_reason', 'updated_at'])
    _audit('daily_count_escalated', acc.profile, pick, old_data={'status': 'counted'},
           new_data={'status': 'escalated'}, note=note[:255])
    return pick


# ── Day end ───────────────────────────────────────────────────────────────────

def close_at(branch, day: dt.date) -> dt.datetime:
    """When the branch's day ends (Cairo time): the latest window end in BranchSettings.working_hours
    (a window ending before it starts crosses midnight); 24-hour / no hours → midnight."""
    from apps.branches.hours import HoursError, _minutes
    from apps.branches.models import BranchSettings
    bs = BranchSettings.for_branch(branch)
    tz = timezone.get_current_timezone()
    midnight = timezone.make_aware(dt.datetime.combine(day + dt.timedelta(days=1), dt.time()), tz)
    if bs.is_24h or not bs.working_hours:
        return midnight
    ends = []
    for w in bs.working_hours:
        if w.get('doccodes'):
            continue
        try:
            a, b = _minutes(w.get('from')), _minutes(w.get('to'), allow_24=True)
        except HoursError:
            continue
        ends.append(b + (1440 if b <= a else 0))
    if not ends:
        return midnight
    start = timezone.make_aware(dt.datetime.combine(day, dt.time()), tz)
    return start + dt.timedelta(minutes=max(ends))


def close_day(branch, day: dt.date) -> int:
    """The branch closed: not-counted items → «لم يُنجز», sessions closed. A recount a reviewer asked
    for AFTER the close (reviewing yesterday's differences) is left open for its counter — it lives on
    the pick, not the closed session."""
    from apps.stockcount.models import DailyCountPick, StockCountSession
    now = timezone.now()
    cutoff = close_at(branch, day)
    sessions = StockCountSession.objects.filter(mode='daily', branch_code=branch.softech_branch_id,
                                                count_date=day).exclude(status='closed')
    missed = DailyCountPick.objects.filter(session__in=sessions).filter(
        Q(status='pending') | Q(status='recount', updated_at__lt=cutoff))
    ids = list(missed.values_list('pk', flat=True))
    n = DailyCountPick.objects.filter(pk__in=ids, status__in=OPEN_FOR_COUNT).update(status='missed', updated_at=now)
    sessions.update(status='closed', variance_at=now)
    if n:
        _audit('daily_count_closed', None, branch,
               note='إغلاق اليوم — أصناف لم تُجرد', extra={'date': day.isoformat(), 'missed': ids})
    return n


def run_job(now=None):
    """Hourly scheduler entry. OFF unless DAILY_COUNT_ENABLED."""
    if not enabled():
        return
    from apps.branches.models import Branch
    from apps.stockcount.models import DailyCountSettings, StockCountSession
    now = timezone.localtime(now or timezone.now())
    s = DailyCountSettings.get()
    for branch in Branch.objects.live().filter(settings__daily_count_enabled=True):
        try:
            for day in (now.date() - dt.timedelta(days=1), now.date()):
                open_ = StockCountSession.objects.filter(mode='daily', branch_code=branch.softech_branch_id,
                                                         count_date=day).exclude(status='closed').exists()
                if open_ and now >= close_at(branch, day):
                    close_day(branch, day)
            if now.hour >= s.job_hour and now < close_at(branch, now.date()):
                generate(branch, now.date())
        except Exception:
            logger.exception('daily count job failed for branch %s', branch.pk)
