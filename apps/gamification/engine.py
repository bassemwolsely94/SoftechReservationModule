"""
apps/gamification/engine.py — turns work already recorded in the platform into points.

READ-ONLY over every other module (and never touches SOFTECH: sales come from the
PostgreSQL mirror `customers.PurchaseHistory`). The only writes are this app's own
ledger and caches.

  score_day(day)      — award points for the work done on `day` (safe to re-run any
                        number of times: each event carries a unique source_key).
  finalize_day(day)   — day close: penalties for what was left behind, the clean-day
                        bonus and the streak. Penalties judge the CURRENT state of open
                        items, so they are only applied for the most recent closed day.
  refresh_players()   — rebuild XP / net / level / badges from the ledger.
  run(days=…)         — what the scheduler calls.
"""
import logging
import math
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.utils import timezone

from .defaults import ensure_defaults
from .models import (Badge, DailyScore, Level, LevelHistory, PlayerProfile, PointEvent,
                     PointRule, StaffBadge)

logger = logging.getLogger(__name__)

CASH_CHANNEL = '91'          # PurchaseHistory.sales_channel — كاش
OPEN_RESERVATION = ('pending', 'available', 'contacted', 'confirmed')
OPEN_TASK = ('open', 'in_progress', 'on_hold')
OPEN_DEMAND = ('new', 'assigned', 'follow_up')
DISCIPLINE_PENALTIES = ('reservation_overdue', 'task_overdue', 'demand_sla_breach',
                        'demand_followup_missed', 'followup_missed')


# ── helpers ───────────────────────────────────────────────────────────────────

def day_bounds(day):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def _local_day(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return timezone.localdate(dt) if timezone.is_aware(dt) else dt.date()
    return dt


def _at(d):
    """A date → aware noon of that day (for DateField sources)."""
    if isinstance(d, datetime):
        return d
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(d, time(12, 0)), tz)


class Scorer:
    """Holds the rules and staff lookups for one engine pass."""

    def __init__(self):
        ensure_defaults()
        from apps.users.models import StaffProfile
        self.rules = {r.key: r for r in PointRule.objects.all()}
        staff = list(StaffProfile.objects.filter(is_active=True).select_related('user'))
        self.staff = {s.id: s for s in staff}
        self.by_code = {}
        for s in staff:
            code = (s.softech_user_id or '').strip()
            if code:
                self.by_code[code] = s
        self.by_user = {s.user_id: s for s in staff}
        self.touched = set()
        self.awarded = 0
        # Per-day caches so a 30-minute re-run does not query once per invoice:
        #   seen  — (staff_id, rule_key, source_key) already in the ledger
        #   used  — (staff_id, rule_key, day) → points already given (daily caps)
        self._loaded_days = set()
        self.seen = set()
        self.used = {}

    def load_day(self, day):
        if day in self._loaded_days:
            return
        self._loaded_days.add(day)
        for sid, rk, src, pts in PointEvent.objects.filter(day=day).values_list(
                'staff_id', 'rule_key', 'source_key', 'points'):
            self.seen.add((sid, rk, src))
            self.used[(sid, rk, day)] = self.used.get((sid, rk, day), 0) + pts

    def award(self, staff, rule_key, source_key, at, branch_id=None, meta=None,
              points=None, reason='', created_by=None):
        """Insert one ledger event. Returns the event or None (inactive rule, role not
        covered, daily cap reached, or already awarded for this source)."""
        if staff is None:
            return None
        if isinstance(staff, int):
            staff = self.staff.get(staff)
            if staff is None:
                return None
        rule = self.rules.get(rule_key)
        if rule is None or not rule.is_active or not rule.applies_to(staff.role):
            return None
        pts = rule.points if points is None else int(points)
        if pts == 0:
            return None
        day = _local_day(at)
        self.load_day(day)
        source_key = source_key[:120]
        if (staff.id, rule_key, source_key) in self.seen:
            return None
        if rule.daily_cap is not None:
            used = self.used.get((staff.id, rule_key, day), 0)
            cap = rule.daily_cap
            if pts > 0:
                pts = min(pts, abs(cap) - used)
                if pts <= 0:
                    return None
            else:
                pts = max(pts, -abs(cap) - used)
                if pts >= 0:
                    return None
        try:
            with transaction.atomic():
                ev = PointEvent.objects.create(
                    staff=staff, rule_key=rule_key, category=rule.category, points=pts,
                    day=day, occurred_at=at, source_key=source_key,
                    branch_id=branch_id if branch_id is not None else staff.branch_id,
                    meta=meta or {}, reason=reason, created_by=created_by)
        except IntegrityError:          # same source on an earlier day (e.g. a re-dated record)
            self.seen.add((staff.id, rule_key, source_key))
            return None
        self.seen.add((staff.id, rule_key, source_key))
        self.used[(staff.id, rule_key, day)] = self.used.get((staff.id, rule_key, day), 0) + pts
        self.touched.add(staff.id)
        self.awarded += 1
        return ev

    def top_up(self, staff, rule_key, day, target_points, meta=None):
        """For a daily aggregate (sales value / profit): add only the difference between
        what the day is worth now and what was already given. Deterministic source keys
        keep it idempotent."""
        if staff is None or target_points <= 0:
            return None
        self.load_day(day)
        already = self.used.get((staff.id, rule_key, day), 0)
        delta = int(target_points) - already
        if delta <= 0:
            return None
        return self.award(staff, rule_key, f'day:{day}:+{already}', _at(day),
                          meta=meta, points=delta)


# ── collectors: work done on `day` ───────────────────────────────────────────

def _collect_sales(sc, day, start, end):
    from apps.customers.models import PurchaseHistory, PurchaseHistoryLine
    codes = list(sc.by_code)
    if not codes:
        return
    qs = PurchaseHistory.objects.filter(invoice_date__gte=start, invoice_date__lt=end,
                                        softech_user__in=codes)
    totals = {}
    for row in qs.filter(doc_code__in=('115', '30')).values(
            'id', 'softech_user', 'branch_id', 'invoice_date', 'doc_code', 'total_amount'):
        staff = sc.by_code.get((row['softech_user'] or '').strip())
        if not staff:
            continue
        amt = abs(row['total_amount'] or Decimal('0'))
        if row['doc_code'] == '115':
            sc.award(staff, 'sale_invoice', f"ph:{row['id']}", row['invoice_date'],
                     branch_id=row['branch_id'])
            totals[staff.id] = totals.get(staff.id, Decimal('0')) + amt
        else:
            sc.award(staff, 'return_processed', f"ph:{row['id']}", row['invoice_date'],
                     branch_id=row['branch_id'])
            totals[staff.id] = totals.get(staff.id, Decimal('0')) - amt

    rule = sc.rules.get('sale_value')
    if rule and rule.unit_value:
        for sid, net in totals.items():
            if net > 0:
                sc.top_up(sc.staff[sid], 'sale_value', day,
                          math.floor(net / rule.unit_value) * rule.points,
                          meta={'net_sales': float(net)})

    rule = sc.rules.get('sale_profit')
    if rule and rule.unit_value:
        gp = ExpressionWrapper(F('line_total') - F('cost_at_sale') * F('quantity'),
                               output_field=DecimalField(max_digits=18, decimal_places=4))
        rows = (PurchaseHistoryLine.objects
                .filter(purchase__in=qs.filter(doc_code='115'), cost_at_sale__isnull=False)
                .values('purchase__softech_user', 'purchase__sales_channel')
                .annotate(gp=Sum(gp)))
        weighted = {}
        for r in rows:
            staff = sc.by_code.get((r['purchase__softech_user'] or '').strip())
            if not staff or not r['gp']:
                continue
            mult = rule.cash_multiplier if r['purchase__sales_channel'] == CASH_CHANNEL else 1
            w = weighted.setdefault(staff.id, {'gp': Decimal('0'), 'cash_gp': Decimal('0'),
                                               'score': Decimal('0')})
            w['gp'] += r['gp']
            if r['purchase__sales_channel'] == CASH_CHANNEL:
                w['cash_gp'] += r['gp']
            w['score'] += r['gp'] * Decimal(mult)
        for sid, w in weighted.items():
            if w['score'] > 0:
                sc.top_up(sc.staff[sid], 'sale_profit', day,
                          math.floor(w['score'] / rule.unit_value) * rule.points,
                          meta={'gross_profit': float(w['gp']), 'cash_gp': float(w['cash_gp'])})


def _collect_reservations(sc, day, start, end):
    from apps.reservations.models import Reservation
    for r in Reservation.objects.filter(created_at__gte=start, created_at__lt=end,
                                        created_by__isnull=False) \
            .values('id', 'created_by_id', 'branch_id', 'created_at'):
        sc.award(r['created_by_id'], 'reservation_created', f"res:{r['id']}",
                 r['created_at'], branch_id=r['branch_id'])
    for r in Reservation.objects.filter(status='fulfilled', updated_at__gte=start,
                                        updated_at__lt=end) \
            .values('id', 'assigned_to_id', 'created_by_id', 'branch_id', 'updated_at'):
        sc.award(r['assigned_to_id'] or r['created_by_id'], 'reservation_fulfilled',
                 f"res:{r['id']}", r['updated_at'], branch_id=r['branch_id'])


def _collect_demand(sc, day, start, end):
    from apps.demand.models import DemandFollowUp, DemandRecord
    for d in DemandRecord.objects.filter(created_at__gte=start, created_at__lt=end,
                                         created_by__isnull=False) \
            .values('id', 'created_by_id', 'branch_id', 'created_at'):
        sc.award(d['created_by_id'], 'demand_created', f"dem:{d['id']}", d['created_at'],
                 branch_id=d['branch_id'])
    for d in DemandRecord.objects.filter(status='fulfilled', fulfilled_at__gte=start,
                                         fulfilled_at__lt=end) \
            .values('id', 'assigned_to_id', 'created_by_id', 'branch_id', 'fulfilled_at'):
        sc.award(d['assigned_to_id'] or d['created_by_id'], 'demand_fulfilled',
                 f"dem:{d['id']}", d['fulfilled_at'], branch_id=d['branch_id'])

    # SLA: assigned → contacted within DemandRecord.SLA_MINUTES['assigned'].
    sla = timedelta(minutes=DemandRecord.SLA_MINUTES.get('assigned', 20))
    now = timezone.now()
    for d in DemandRecord.objects.filter(assigned_at__gte=start, assigned_at__lt=end,
                                         assigned_to__isnull=False) \
            .values('id', 'assigned_to_id', 'branch_id', 'assigned_at', 'contacted_at',
                    'status'):
        deadline = d['assigned_at'] + sla
        late = (d['contacted_at'] > deadline) if d['contacted_at'] else \
            (now > deadline and d['status'] == 'assigned')
        if late:
            sc.award(d['assigned_to_id'], 'demand_sla_breach', f"dem_sla:{d['id']}",
                     deadline, branch_id=d['branch_id'])

    for f in DemandFollowUp.objects.filter(status='done', completed_at__gte=start,
                                           completed_at__lt=end) \
            .values('id', 'completed_by_id', 'assigned_to_id', 'completed_at', 'due_date'):
        if f['due_date'] and f['completed_at'] > f['due_date'] + timedelta(hours=1):
            continue      # done, but late — no reward (and not a penalty either)
        sc.award(f['completed_by_id'] or f['assigned_to_id'], 'demand_followup_done',
                 f"dfu:{f['id']}", f['completed_at'])
    for f in DemandFollowUp.objects.filter(status='missed', due_date__gte=start,
                                           due_date__lt=end, assigned_to__isnull=False) \
            .values('id', 'assigned_to_id', 'due_date'):
        sc.award(f['assigned_to_id'], 'demand_followup_missed', f"dfu:{f['id']}",
                 f['due_date'])


def _collect_followups(sc, day, start, end):
    from apps.followups.models import FollowUpTask
    for f in FollowUpTask.objects.filter(status__in=('done', 'called'),
                                         completed_at__gte=start, completed_at__lt=end) \
            .values('id', 'completed_by_id', 'assigned_to_id', 'branch_id', 'completed_at'):
        sc.award(f['completed_by_id'] or f['assigned_to_id'], 'followup_call_done',
                 f"fu:{f['id']}", f['completed_at'], branch_id=f['branch_id'])
    for f in FollowUpTask.objects.filter(status='missed', due_date=day,
                                         assigned_to__isnull=False) \
            .values('id', 'assigned_to_id', 'branch_id', 'due_date'):
        sc.award(f['assigned_to_id'], 'followup_missed', f"fu:{f['id']}", _at(f['due_date']),
                 branch_id=f['branch_id'])


def _collect_transfers(sc, day, start, end):
    from apps.transfers.models import TransferRequest
    base = TransferRequest.objects.exclude(status='draft')
    for t in base.filter(Q(submitted_at__gte=start, submitted_at__lt=end) |
                         Q(submitted_at__isnull=True, created_at__gte=start, created_at__lt=end),
                         created_by__isnull=False) \
            .values('id', 'created_by_id', 'requesting_branch_id', 'submitted_at', 'created_at'):
        sc.award(t['created_by_id'], 'transfer_request_created', f"tr:{t['id']}",
                 t['submitted_at'] or t['created_at'], branch_id=t['requesting_branch_id'])

    fast = sc.rules.get('transfer_request_fast')
    grace = timedelta(hours=(fast.grace_hours if fast and fast.grace_hours else 2))
    for t in base.exclude(status__in=('pending',)) \
            .filter(reviewed_at__gte=start, reviewed_at__lt=end, reviewed_by__isnull=False) \
            .values('id', 'reviewed_by_id', 'supplying_branch_id', 'reviewed_at',
                    'submitted_at', 'created_at'):
        sc.award(t['reviewed_by_id'], 'transfer_request_answered', f"tr:{t['id']}",
                 t['reviewed_at'], branch_id=t['supplying_branch_id'])
        asked = t['submitted_at'] or t['created_at']
        if asked and t['reviewed_at'] - asked <= grace:
            sc.award(t['reviewed_by_id'], 'transfer_request_fast', f"tr:{t['id']}",
                     t['reviewed_at'], branch_id=t['supplying_branch_id'],
                     meta={'minutes': int((t['reviewed_at'] - asked).total_seconds() // 60)})
    for t in base.filter(dispatched_at__gte=start, dispatched_at__lt=end,
                         dispatched_by__isnull=False) \
            .values('id', 'dispatched_by_id', 'supplying_branch_id', 'dispatched_at'):
        sc.award(t['dispatched_by_id'], 'transfer_dispatched', f"tr:{t['id']}",
                 t['dispatched_at'], branch_id=t['supplying_branch_id'])


def _collect_transits(sc, day, start, end):
    from apps.transits.models import InTransitTransfer
    for t in InTransitTransfer.objects.filter(issue_date=day).exclude(erp_user_code='') \
            .values('id', 'erp_user_code', 'supplying_branch_id', 'issue_date'):
        staff = sc.by_code.get((t['erp_user_code'] or '').strip())
        if staff:
            sc.award(staff, 'transfer_sent_erp', f"125:{t['id']}", _at(t['issue_date']),
                     branch_id=t['supplying_branch_id'])
    for t in InTransitTransfer.objects.filter(manually_received_at__gte=start,
                                              manually_received_at__lt=end,
                                              manually_received_by__isnull=False) \
            .values('id', 'manually_received_by_id', 'receiving_branch_id',
                    'manually_received_at'):
        sc.award(t['manually_received_by_id'], 'transfer_received', f"125:{t['id']}",
                 t['manually_received_at'], branch_id=t['receiving_branch_id'])


def _collect_isr(sc, day, start, end):
    from apps.purchasing.models import IsrPush
    for p in IsrPush.objects.filter(created_at__gte=start, created_at__lt=end,
                                    created_by__isnull=False).exclude(status='cancelled') \
            .values('id', 'created_by_id', 'branch_id', 'created_at'):
        sc.award(sc.by_user.get(p['created_by_id']), 'isr_created', f"isr:{p['id']}",
                 p['created_at'], branch_id=p['branch_id'])
    for p in IsrPush.objects.filter(approved_at__gte=start, approved_at__lt=end,
                                    approved_by__isnull=False) \
            .values('id', 'approved_by_id', 'branch_id', 'approved_at'):
        sc.award(sc.by_user.get(p['approved_by_id']), 'isr_approved', f"isr:{p['id']}",
                 p['approved_at'], branch_id=p['branch_id'])


def _collect_inventory(sc, day, start, end):
    from apps.shortage.models import ShortageList
    from apps.stockcount.models import StockCountSession
    for s in StockCountSession.objects.filter(status__in=('variance_ready', 'closed'),
                                              variance_at__gte=start, variance_at__lt=end) \
            .values('id', 'uploaded_by_id', 'created_by_id', 'variance_at'):
        sc.award(s['uploaded_by_id'] or s['created_by_id'], 'stockcount_completed',
                 f"sc:{s['id']}", s['variance_at'])
    for s in ShortageList.objects.filter(status__in=('submitted', 'resolved'),
                                         updated_at__gte=start, updated_at__lt=end,
                                         created_by__isnull=False) \
            .values('id', 'created_by_id', 'branch_id', 'updated_at'):
        sc.award(s['created_by_id'], 'shortage_submitted', f"sh:{s['id']}", s['updated_at'],
                 branch_id=s['branch_id'])


def _collect_tasks(sc, day, start, end):
    from apps.tasks.models import OperationalTask
    for t in OperationalTask.objects.filter(status='completed', completed_at__gte=start,
                                            completed_at__lt=end) \
            .values('id', 'completed_by_id', 'assigned_to_id', 'branch_id', 'completed_at',
                    'due_date'):
        on_time = t['due_date'] is None or t['completed_at'] <= t['due_date']
        sc.award(t['completed_by_id'] or t['assigned_to_id'],
                 'task_on_time' if on_time else 'task_late', f"task:{t['id']}",
                 t['completed_at'], branch_id=t['branch_id'])


def _collect_audit(sc, day, start, end):
    from apps.audit.models import AbuseFlag
    for f in AbuseFlag.objects.filter(status='escalated', reviewed_at__gte=start,
                                      reviewed_at__lt=end) \
            .values('id', 'staff_id', 'reviewed_at', 'flag_type'):
        sc.award(f['staff_id'], 'abuse_flag', f"abuse:{f['id']}", f['reviewed_at'],
                 meta={'flag_type': f['flag_type']})


COLLECTORS = [_collect_sales, _collect_reservations, _collect_demand, _collect_followups,
              _collect_transfers, _collect_transits, _collect_isr, _collect_inventory,
              _collect_tasks, _collect_audit]


def score_day(day, scorer=None):
    sc = scorer or Scorer()
    start, end = day_bounds(day)
    for fn in COLLECTORS:
        try:
            fn(sc, day, start, end)
        except Exception as exc:          # one broken source must not stop the others
            logger.exception('gamification collector %s failed for %s: %s',
                             fn.__name__, day, exc)
    return sc


# ── day close ─────────────────────────────────────────────────────────────────

def _penalise_open_items(sc, day):
    """Items still open at the close of `day` that were already due. Judged on the
    current state, so only meaningful for the day that just closed."""
    from apps.reservations.models import Reservation
    from apps.tasks.models import OperationalTask
    _, end = day_bounds(day)
    for r in Reservation.objects.filter(status__in=OPEN_RESERVATION, assigned_to__isnull=False,
                                        follow_up_date__lt=day) \
            .values('id', 'assigned_to_id', 'branch_id'):
        sc.award(r['assigned_to_id'], 'reservation_overdue', f"res_overdue:{r['id']}:{day}",
                 end - timedelta(seconds=1), branch_id=r['branch_id'])
    for t in OperationalTask.objects.filter(status__in=OPEN_TASK, assigned_to__isnull=False,
                                            due_date__lt=end) \
            .values('id', 'assigned_to_id', 'branch_id'):
        sc.award(t['assigned_to_id'], 'task_overdue', f"task_overdue:{t['id']}:{day}",
                 end - timedelta(seconds=1), branch_id=t['branch_id'])


def _write_daily(staff, day):
    agg = PointEvent.objects.filter(staff=staff, day=day).aggregate(
        earned=Sum('points', filter=Q(points__gt=0)),
        lost=Sum('points', filter=Q(points__lt=0)),
        n=Count('id'),
        left=Count('id', filter=Q(rule_key__in=DISCIPLINE_PENALTIES)),
    )
    earned, lost = agg['earned'] or 0, agg['lost'] or 0
    ds, _ = DailyScore.objects.update_or_create(
        staff=staff, day=day,
        defaults=dict(branch_id=staff.branch_id, earned=earned, lost=lost, net=earned + lost,
                      events=agg['n'] or 0, left_behind=agg['left'] or 0))
    return ds


def finalize_day(day, scorer=None, penalties=True):
    sc = scorer or Scorer()
    if penalties:
        _penalise_open_items(sc, day)

    worked_ids = set(PointEvent.objects.filter(day=day, points__gt=0)
                     .exclude(category__in=('discipline', 'manual'))
                     .values_list('staff_id', flat=True))
    penal_ids = set(PointEvent.objects.filter(day=day, points__lt=0)
                    .values_list('staff_id', flat=True))
    for sid in worked_ids | penal_ids:
        staff = sc.staff.get(sid)
        if staff is None:
            continue
        player, _ = PlayerProfile.objects.get_or_create(staff=staff)
        if player.last_scored_day and player.last_scored_day >= day:
            _write_daily(staff, day)
            continue
        clean = sid in worked_ids and sid not in penal_ids
        if clean:
            sc.award(staff, 'clean_day', f'clean:{day}', _at(day))
            prev = player.last_clean_day
            player.current_streak = player.current_streak + 1 \
                if prev and (day - prev).days <= 1 else 1
            player.last_clean_day = day
            player.best_streak = max(player.best_streak, player.current_streak)
            if player.current_streak % 7 == 0:
                sc.award(staff, 'streak_week', f'streak:{day}', _at(day),
                         meta={'streak': player.current_streak})
        elif sid in penal_ids:
            player.current_streak = 0
        player.last_scored_day = day
        player.save(update_fields=['current_streak', 'best_streak', 'last_clean_day',
                                   'last_scored_day', 'updated_at'])
        ds = _write_daily(staff, day)
        ds.clean_day = clean
        ds.finalized = True
        ds.save(update_fields=['clean_day', 'finalized'])
        sc.touched.add(sid)
    return sc


# ── totals, levels, badges ───────────────────────────────────────────────────

def _notify(staff, ntype, title, body, dedup):
    try:
        from apps.notifications.models import Notification
        if not Notification.objects.filter(recipient=staff, dedup_key=dedup).exists():
            Notification.objects.create(recipient=staff, notification_type=ntype,
                                        title=title, body=body, dedup_key=dedup)
    except Exception as exc:
        logger.warning('gamification notify failed: %s', exc)


def refresh_players(staff_ids=None):
    from apps.users.models import StaffProfile
    levels = list(Level.objects.order_by('min_xp'))
    badges = list(Badge.objects.filter(is_active=True))
    qs = StaffProfile.objects.filter(is_active=True)
    if staff_ids is not None:
        qs = qs.filter(id__in=list(staff_ids))
    promoted = 0
    for staff in qs:
        agg = PointEvent.objects.filter(staff=staff).aggregate(
            xp=Sum('points', filter=Q(points__gt=0)), net=Sum('points'))
        xp, net = agg['xp'] or 0, agg['net'] or 0
        player, _ = PlayerProfile.objects.get_or_create(staff=staff)
        reached = [lv for lv in levels if lv.min_xp <= xp]
        new_level = reached[-1] if reached else (levels[0] if levels else None)
        old_num = player.level.number if player.level else 0
        player.xp, player.net_points = xp, net
        # Levels never drop: keep the highest one ever reached.
        if new_level and new_level.number > old_num:
            player.level = new_level
        player.save(update_fields=['xp', 'net_points', 'level', 'updated_at'])
        for lv in reached:
            if lv.number <= 1:
                continue
            _, made = LevelHistory.objects.get_or_create(staff=staff, level=lv,
                                                         defaults={'xp': xp})
            if made:
                promoted += 1
                _notify(staff, 'gamification_level_up',
                        f'{lv.icon} ترقية! أصبحت «{lv.title_ar}» — المستوى {lv.number}',
                        f'Promotion! You are now "{lv.title_en}" (level {lv.number}). '
                        f'رصيد خبرتك {xp:,} نقطة.',
                        f'gam_level_{staff.id}_{lv.number}')
        _award_badges(staff, player, badges)
    return promoted


def _award_badges(staff, player, badges):
    have = set(StaffBadge.objects.filter(staff=staff).values_list('badge_id', flat=True))
    for b in badges:
        if b.id in have:
            continue
        if b.criteria == Badge.CRITERIA_RULE_COUNT:
            ok = PointEvent.objects.filter(staff=staff, rule_key=b.rule_key).count() >= b.threshold
        elif b.criteria == Badge.CRITERIA_STREAK:
            ok = player.best_streak >= b.threshold
        elif b.criteria == Badge.CRITERIA_XP:
            ok = player.xp >= b.threshold
        else:
            ok = False
        if ok:
            StaffBadge.objects.get_or_create(staff=staff, badge=b)
            _notify(staff, 'gamification_badge',
                    f'{b.icon} شارة جديدة: {b.name_ar}', f'New badge: {b.name_en} — {b.desc_ar}',
                    f'gam_badge_{staff.id}_{b.key}')


# ── entry point ───────────────────────────────────────────────────────────────

def run(days=1, today=None, finalize=True):
    """Score today and the previous `days` days; close yesterday."""
    today = today or timezone.localdate()
    sc = Scorer()
    for i in range(days, -1, -1):
        score_day(today - timedelta(days=i), sc)
    if finalize:
        yesterday = today - timedelta(days=1)
        # older days: clean-day/streak only (their open items are no longer knowable)
        for i in range(days, 1, -1):
            finalize_day(today - timedelta(days=i), sc, penalties=False)
        finalize_day(yesterday, sc, penalties=True)
    for sid in sc.touched:
        staff = sc.staff.get(sid)
        if staff:
            _write_daily(staff, today)
    promoted = refresh_players(sc.touched)
    return {'awarded': sc.awarded, 'players': len(sc.touched), 'promotions': promoted}
