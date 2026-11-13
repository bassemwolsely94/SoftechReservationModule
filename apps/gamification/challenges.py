"""
apps/gamification/challenges.py — تحديات الفروع (branch team challenges).

Management sets a shared goal for a period; every branch in scope races for it, and each
branch that meets the target when the period ends earns `bonus_per_member` points for
every active member (role not excluded from titles, see champions.excluded_roles()).

Metrics are deterministic reads of data the platform already keeps:
  left_behind_max   Σ DailyScore.left_behind of the branch's members  (lower is better)
  clean_day_rate    clean days ÷ finalized days × 100
  fast_reply_rate   other branches' transfer requests answered within the
                    transfer_request_fast grace ÷ requests received × 100
  daily_count_rate  daily-count items counted ÷ items assigned × 100
  avg_points        net points (bonus categories excluded) ÷ active members
  pic_capture_rate  sale invoices on a (non-excluded) customer code ÷ all sale invoices × 100
  new_pics_per_member  new customers (pic_new events) ÷ active members
A branch with no data for the metric (e.g. no incoming requests) is "not applicable":
no bonus, never a failure.

evaluate_due() runs from the nightly day close (engine.run, finalize=True) for challenges
whose end date has passed, exactly once each (evaluated_at + a unique result row per
branch + a unique ledger source per member). Bonuses use the `team` category: counted
for XP and the reward wallet, never for rankings.
"""
import logging
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from . import engine
from .models import (RANKING_EXCLUDED_CATEGORIES, DailyScore, GamificationChange, PointEvent,
                     PointRule, TeamChallenge, TeamChallengeResult)

logger = logging.getLogger(__name__)

TWO = Decimal('0.01')


def _q(v):
    return None if v is None else Decimal(v).quantize(TWO, rounding=ROUND_HALF_UP)


def _branches(ch):
    from apps.branches.models import Branch
    qs = Branch.objects.live()
    if ch.branch_ids:
        qs = qs.filter(id__in=ch.branch_ids)
    return list(qs.order_by('name'))


def members(branch_id):
    from apps.users.models import StaffProfile
    from .champions import excluded_roles
    return list(StaffProfile.objects.filter(is_active=True, branch_id=branch_id)
                .exclude(role__in=excluded_roles()))


def metric_value(ch, branch, start, end, member_ids):
    """Value of the challenge metric for one branch over [start, end]; None = no data."""
    m = ch.metric
    if m in (TeamChallenge.METRIC_LEFT_BEHIND, TeamChallenge.METRIC_CLEAN_DAYS):
        agg = DailyScore.objects.filter(staff_id__in=member_ids, day__gte=start, day__lte=end,
                                        finalized=True).aggregate(
            n=Count('id'), clean=Count('id', filter=Q(clean_day=True)), left=Sum('left_behind'))
        if not agg['n']:
            return None
        if m == TeamChallenge.METRIC_LEFT_BEHIND:
            return _q(agg['left'] or 0)
        return _q(Decimal(agg['clean']) * 100 / agg['n'])
    if m == TeamChallenge.METRIC_FAST_REPLY:
        from apps.transfers.models import TransferRequest
        rule = PointRule.objects.filter(key='transfer_request_fast').first()
        grace = timedelta(hours=(rule.grace_hours if rule and rule.grace_hours else 2))
        total = fast = 0
        for t in TransferRequest.objects.filter(
                supplying_branch=branch, submitted_at__date__gte=start,
                submitted_at__date__lte=end).exclude(status='draft') \
                .values('submitted_at', 'reviewed_at'):
            total += 1
            if t['reviewed_at'] and t['reviewed_at'] - t['submitted_at'] <= grace:
                fast += 1
        return _q(Decimal(fast) * 100 / total) if total else None
    if m == TeamChallenge.METRIC_DAILY_COUNT:
        from apps.stockcount.models import DailyCountPick
        picks = DailyCountPick.objects.filter(
            session__mode='daily', session__branch_code=str(branch.softech_branch_id or ''),
            session__count_date__gte=start, session__count_date__lte=end)
        total = picks.count()
        if not total:
            return None
        done = picks.exclude(status__in=('pending', 'missed')).count()
        return _q(Decimal(done) * 100 / total)
    if m == TeamChallenge.METRIC_PIC_CAPTURE:
        from .pic import branch_capture_rate
        total, on_pic = branch_capture_rate(branch, start, end)
        return _q(Decimal(on_pic) * 100 / total) if total else None
    if m == TeamChallenge.METRIC_NEW_PICS:
        if not member_ids:
            return None
        n = PointEvent.objects.filter(staff_id__in=member_ids, rule_key='pic_new',
                                      day__gte=start, day__lte=end).count()
        return _q(Decimal(n) / len(member_ids))
    if m == TeamChallenge.METRIC_AVG_POINTS:
        if not member_ids:
            return None
        net = PointEvent.objects.filter(staff_id__in=member_ids, day__gte=start, day__lte=end) \
            .exclude(category__in=RANKING_EXCLUDED_CATEGORIES).aggregate(s=Sum('points'))['s'] or 0
        return _q(Decimal(net) / len(member_ids))
    raise ValueError(f'unknown metric {m}')


def achieved(ch, value):
    if value is None:
        return False
    if ch.metric in TeamChallenge.LOWER_IS_BETTER:
        return value <= ch.target
    return value >= ch.target


def standings(ch, today=None):
    """Live (or final) value per branch. Final rows come from TeamChallengeResult."""
    today = today or timezone.localdate()
    if ch.evaluated_at:
        return [{'branch_id': r.branch_id, 'branch': r.branch.name,
                 'value': float(r.value) if r.value is not None else None,
                 'achieved': r.achieved, 'members': r.members, 'bonus': r.bonus, 'final': True}
                for r in ch.results.select_related('branch').order_by('-achieved', 'branch__name')]
    end = min(ch.end, today)
    rows = []
    if end < ch.start:
        return rows
    for b in _branches(ch):
        mem = members(b.id)
        v = metric_value(ch, b, ch.start, end, [s.id for s in mem])
        rows.append({'branch_id': b.id, 'branch': b.name,
                     'value': float(v) if v is not None else None,
                     'achieved': achieved(ch, v), 'members': len(mem),
                     'bonus': 0, 'final': False})
    lower = ch.metric in TeamChallenge.LOWER_IS_BETTER
    rows.sort(key=lambda r: (r['value'] is None,
                             (r['value'] or 0) if lower else -(r['value'] or 0), r['branch']))
    return rows


def evaluate(ch, by=None):
    """Final judgement of an ended challenge. Returns the number of branches that won.
    Idempotent: a challenge is evaluated once (row lock + evaluated_at)."""
    today = timezone.localdate()
    if ch.end >= today:
        raise ValueError('لم تنته فترة التحدي بعد — the challenge period has not ended')
    winners, awarded_staff = 0, set()
    with transaction.atomic():
        ch = TeamChallenge.objects.select_for_update().get(pk=ch.pk)
        if ch.evaluated_at:
            return ch.results.filter(achieved=True).count()
        sc = engine.Scorer()
        for b in _branches(ch):
            mem = members(b.id)
            v = metric_value(ch, b, ch.start, ch.end, [s.id for s in mem])
            ok = achieved(ch, v) and len(mem) >= ch.min_members
            bonus = ch.bonus_per_member if ok else 0
            TeamChallengeResult.objects.create(challenge=ch, branch=b, value=v, achieved=ok,
                                               members=len(mem), bonus=bonus)
            if ok:
                winners += 1
                for s in mem:
                    ev = sc.award(s, 'team_challenge', f'team:{ch.id}', timezone.now(),
                                  points=bonus, branch_id=b.id,
                                  meta={'challenge': ch.id, 'value': float(v)})
                    if ev:
                        awarded_staff.add(s.id)
        ch.evaluated_at = timezone.now()
        ch.save(update_fields=['evaluated_at'])
        if by is not None:
            GamificationChange.objects.create(actor=by, action='challenge_evaluate',
                                              target=f'challenge:{ch.id}', after={'winners': winners})
    if awarded_staff:
        engine.refresh_players(awarded_staff)
        _notify(ch, awarded_staff)
    return winners


def evaluate_due(today=None):
    """Evaluate every active challenge whose period has ended. Returns how many."""
    today = today or timezone.localdate()
    n = 0
    for ch in TeamChallenge.objects.filter(is_active=True, evaluated_at__isnull=True,
                                           end__lt=today):
        try:
            evaluate(ch)
            n += 1
        except Exception as exc:     # one bad challenge must not block the others
            logger.exception('team challenge %s evaluation failed: %s', ch.pk, exc)
    return n


def _notify(ch, staff_ids):
    from apps.notifications.models import Notification
    for sid in staff_ids:
        try:
            Notification.objects.create(
                recipient_id=sid, notification_type='gamification_team',
                title=f'🤝 فرعك حقق التحدي «{ch.name_ar}»!',
                body=f'+{ch.bonus_per_member:,} نقطة لكل عضو. Your branch met "{ch.name_en}".',
                dedup_key=f'gam_team_{ch.id}_{sid}')
        except Exception as exc:
            logger.warning('team challenge notify failed: %s', exc)


def challenge_json(ch, my_branch_id=None, with_standings=True):
    data = {'id': ch.id, 'name_ar': ch.name_ar, 'name_en': ch.name_en, 'desc_ar': ch.desc_ar,
            'desc_en': ch.desc_en, 'icon': ch.icon, 'metric': ch.metric,
            'metric_label': ch.get_metric_display(), 'target': float(ch.target),
            'lower_is_better': ch.metric in TeamChallenge.LOWER_IS_BETTER,
            # ISO strings: this dict is also stored in the GamificationChange audit (JSONField)
            'start': ch.start.isoformat(), 'end': ch.end.isoformat(), 'branch_ids': ch.branch_ids,
            'bonus_per_member': ch.bonus_per_member, 'min_members': ch.min_members,
            'is_active': ch.is_active,
            'evaluated_at': ch.evaluated_at.isoformat() if ch.evaluated_at else None}
    if with_standings:
        rows = standings(ch)
        data['standings'] = rows
        data['mine'] = next((r for r in rows if r['branch_id'] == my_branch_id), None)
    return data


def board(staff, days_back=90, include_inactive=False):
    """Running + upcoming + recently finished challenges, with each branch's progress.
    Editors also see switched-off ones (so they can switch them back on)."""
    since = timezone.localdate() - timedelta(days=days_back)
    qs = TeamChallenge.objects.filter(end__gte=since)
    if not include_inactive:
        qs = qs.filter(is_active=True)
    return [challenge_json(ch, staff.branch_id) for ch in qs]
