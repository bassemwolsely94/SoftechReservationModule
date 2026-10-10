"""
apps/gamification/services.py — read side: my profile, leaderboards, branch ranking,
the "nothing left behind" list, and the executive report. Pure queries.
"""
from datetime import date, timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import (CATEGORY_CHOICES, Badge, DailyScore, Level, LevelHistory, PlayerProfile,
                     PointEvent, PointRule, StaffBadge)

PERIODS = ('day', 'week', 'month', 'quarter', 'year', 'all')
NETWORK_TOP = 10


def period_range(period, today=None, date_from=None, date_to=None):
    """Inclusive (start, end) dates. The work week starts on Saturday (Egypt)."""
    today = today or timezone.localdate()
    if date_from or date_to:
        return (date_from or date(2000, 1, 1)), (date_to or today)
    if period == 'day':
        return today, today
    if period == 'week':
        return today - timedelta(days=(today.weekday() - 5) % 7), today
    if period == 'quarter':
        q = (today.month - 1) // 3
        return date(today.year, q * 3 + 1, 1), today
    if period == 'year':
        return date(today.year, 1, 1), today
    if period == 'all':
        return date(2000, 1, 1), today
    return today.replace(day=1), today            # month (default)


def _level_payload(level, lang_both=True):
    if not level:
        return None
    return {'number': level.number, 'min_xp': level.min_xp, 'title_ar': level.title_ar,
            'title_en': level.title_en, 'icon': level.icon, 'color': level.color}


def level_progress(xp):
    levels = list(Level.objects.order_by('min_xp'))
    current = None
    nxt = None
    for lv in levels:
        if lv.min_xp <= xp:
            current = lv
        elif nxt is None:
            nxt = lv
    if nxt and current:
        span = nxt.min_xp - current.min_xp
        pct = round((xp - current.min_xp) * 100 / span, 1) if span else 100
    else:
        pct = 100
    return {'current': _level_payload(current), 'next': _level_payload(nxt),
            'progress_pct': pct, 'xp_to_next': (nxt.min_xp - xp) if nxt else 0}


def _staff_row(staff):
    return {'staff_id': staff.id, 'name': staff.full_name, 'role': staff.role,
            'role_label': staff.get_role_display(),
            'branch': staff.branch.name if staff.branch_id and staff.branch else '',
            'branch_id': staff.branch_id}


def ranking(start, end, branch_id=None, role=None, limit=None):
    """[{rank, staff…, net, earned, lost, events, level}] ordered by net desc."""
    from apps.users.models import StaffProfile
    qs = PointEvent.objects.filter(day__gte=start, day__lte=end, staff__is_active=True)
    if branch_id:
        qs = qs.filter(staff__branch_id=branch_id)
    if role:
        qs = qs.filter(staff__role=role)
    rows = list(qs.values('staff_id').annotate(
        net=Sum('points'), earned=Sum('points', filter=Q(points__gt=0)),
        lost=Sum('points', filter=Q(points__lt=0)), events=Count('id'),
    ).order_by('-net', '-earned', 'staff_id'))
    if limit:
        rows = rows[:limit]
    staff = {s.id: s for s in StaffProfile.objects.filter(id__in=[r['staff_id'] for r in rows])
             .select_related('user', 'branch')}
    players = {p.staff_id: p for p in PlayerProfile.objects.filter(
        staff_id__in=staff.keys()).select_related('level')}
    out = []
    for i, r in enumerate(rows, 1):
        s = staff.get(r['staff_id'])
        if not s:
            continue
        p = players.get(s.id)
        out.append({'rank': i, **_staff_row(s), 'net': r['net'] or 0,
                    'earned': r['earned'] or 0, 'lost': r['lost'] or 0, 'events': r['events'],
                    'level': _level_payload(p.level) if p else None,
                    'streak': p.current_streak if p else 0})
    return out


def rank_of(staff, start, end, branch_id=None, role=None):
    rows = ranking(start, end, branch_id=branch_id, role=role)
    for r in rows:
        if r['staff_id'] == staff.id:
            return {'rank': r['rank'], 'of': len(rows), 'net': r['net']}
    return {'rank': None, 'of': len(rows), 'net': 0}


def branch_ranking(start, end):
    from apps.branches.models import Branch
    ev = (PointEvent.objects.filter(day__gte=start, day__lte=end, staff__is_active=True,
                                    staff__branch__isnull=False)
          .values('staff__branch_id')
          .annotate(net=Sum('points'), earned=Sum('points', filter=Q(points__gt=0)),
                    lost=Sum('points', filter=Q(points__lt=0)),
                    players=Count('staff_id', distinct=True)))
    days = (DailyScore.objects.filter(day__gte=start, day__lte=end, finalized=True,
                                      branch__isnull=False)
            .values('branch_id')
            .annotate(n=Count('id'), clean=Count('id', filter=Q(clean_day=True)),
                      left=Sum('left_behind')))
    days = {d['branch_id']: d for d in days}
    names = dict(Branch.objects.values_list('id', 'name'))
    rows = []
    for r in ev:
        bid = r['staff__branch_id']
        players = r['players'] or 1
        d = days.get(bid, {})
        rows.append({
            'branch_id': bid, 'branch': names.get(bid, str(bid)),
            'players': r['players'], 'net': r['net'] or 0, 'earned': r['earned'] or 0,
            'lost': r['lost'] or 0,
            'avg_per_player': round((r['net'] or 0) / players, 1),
            'clean_day_rate': round(d['clean'] * 100 / d['n'], 1) if d.get('n') else None,
            'left_behind': d.get('left') or 0,
        })
    # Fair comparison between big and small branches: average per active player.
    rows.sort(key=lambda x: (-x['avg_per_player'], -x['net']))
    for i, r in enumerate(rows, 1):
        r['rank'] = i
    return rows


def open_items(staff):
    """What this person (and their branch) still has open — «لا تترك شيئاً خلفك»."""
    today = timezone.localdate()
    now = timezone.now()
    items = []

    def add(key, ar, en, count, route, penalty=False):
        if count:
            items.append({'key': key, 'label_ar': ar, 'label_en': en, 'count': count,
                          'route': route, 'penalty': penalty})

    from apps.reservations.models import Reservation
    from apps.tasks.models import OperationalTask
    from apps.demand.models import DemandFollowUp, DemandRecord
    from apps.followups.models import FollowUpTask
    from apps.transfers.models import TransferRequest
    from apps.transits.models import InTransitTransfer
    from .engine import OPEN_DEMAND, OPEN_RESERVATION, OPEN_TASK

    add('reservations_overdue', 'حجوزات فات موعد متابعتها', 'Reservations past follow-up',
        Reservation.objects.filter(assigned_to=staff, status__in=OPEN_RESERVATION,
                                   follow_up_date__lt=today).count(), '/reservations', True)
    add('reservations_today', 'حجوزات متابعتها اليوم', 'Reservations to follow up today',
        Reservation.objects.filter(assigned_to=staff, status__in=OPEN_RESERVATION,
                                   follow_up_date=today).count(), '/reservations')
    add('tasks_overdue', 'مهام متأخرة', 'Overdue tasks',
        OperationalTask.objects.filter(assigned_to=staff, status__in=OPEN_TASK,
                                       due_date__lt=now).count(), '/tasks', True)
    add('demand_open', 'طلبات ضائعة مسندة إليك', 'Lost-sale requests assigned to you',
        DemandRecord.objects.filter(assigned_to=staff, status__in=OPEN_DEMAND).count(),
        '/demand')
    add('demand_followups', 'متابعات طلبات مستحقة', 'Demand follow-ups due',
        DemandFollowUp.objects.filter(assigned_to=staff, status='pending',
                                      due_date__lte=now).count(), '/demand')
    add('followups_due', 'متابعات عملاء مستحقة', 'Customer follow-ups due',
        FollowUpTask.objects.filter(assigned_to=staff, status='pending',
                                    due_date__lte=today).count(), '/followups')
    if staff.branch_id:
        add('branch_requests', 'طلبات فروع أخرى تنتظر ردّ فرعك', 'Other branches waiting on your branch',
            TransferRequest.objects.filter(supplying_branch_id=staff.branch_id,
                                           status='pending').count(), '/transfers')
        add('transfers_to_receive', 'تحويلات في الطريق لفرعك', 'Transfers on the way to your branch',
            InTransitTransfer.objects.filter(receiving_branch_id=staff.branch_id,
                                             transit_status='in_transit').count(), '/transits')
    return items


def recent_events(staff, limit=20):
    rules = {r.key: r for r in PointRule.objects.all()}
    out = []
    for e in PointEvent.objects.filter(staff=staff).order_by('-occurred_at', '-id')[:limit]:
        r = rules.get(e.rule_key)
        out.append({'id': e.id, 'rule_key': e.rule_key, 'category': e.category,
                    'name_ar': r.name_ar if r else e.rule_key,
                    'name_en': r.name_en if r else e.rule_key,
                    'points': e.points, 'day': e.day, 'occurred_at': e.occurred_at,
                    'reason': e.reason, 'meta': e.meta})
    return out


def badges_for(staff):
    earned = {sb.badge_id: sb.earned_at for sb in StaffBadge.objects.filter(staff=staff)}
    player = PlayerProfile.objects.filter(staff=staff).first()
    counts = dict(PointEvent.objects.filter(staff=staff).values('rule_key')
                  .annotate(n=Count('id')).values_list('rule_key', 'n'))
    out = []
    for b in Badge.objects.filter(is_active=True):
        if b.criteria == Badge.CRITERIA_RULE_COUNT:
            have = counts.get(b.rule_key, 0)
        elif b.criteria == Badge.CRITERIA_STREAK:
            have = player.best_streak if player else 0
        else:
            have = player.xp if player else 0
        out.append({'key': b.key, 'icon': b.icon, 'name_ar': b.name_ar, 'name_en': b.name_en,
                    'desc_ar': b.desc_ar, 'desc_en': b.desc_en, 'threshold': b.threshold,
                    'progress': min(have, b.threshold), 'earned': b.id in earned,
                    'earned_at': earned.get(b.id)})
    out.sort(key=lambda x: (not x['earned'], -(x['progress'] / (x['threshold'] or 1))))
    return out


def _wallet(staff):
    from .rewards import wallet
    return wallet(staff)


def rewards_summary(start, end, branch_id=None):
    from .models import Redemption
    qs = Redemption.objects.filter(created_at__date__gte=start, created_at__date__lte=end)
    if branch_id:
        qs = qs.filter(staff__branch_id=branch_id)
    by_status = dict(qs.values('status').annotate(n=Count('id')).values_list('status', 'n'))
    spent = qs.filter(status__in=('approved', 'fulfilled')).aggregate(n=Sum('cost'))['n'] or 0
    top = [{'reward_id': r['reward_id'], 'name_ar': r['reward__name_ar'],
            'name_en': r['reward__name_en'], 'icon': r['reward__icon'], 'requests': r['n'],
            'points': r['p'] or 0}
           for r in qs.exclude(status__in=('rejected', 'cancelled'))
           .values('reward_id', 'reward__name_ar', 'reward__name_en', 'reward__icon')
           .annotate(n=Count('id'), p=Sum('cost')).order_by('-n')[:10]]
    waiting = Redemption.objects.filter(status='approved')
    if branch_id:
        waiting = waiting.filter(staff__branch_id=branch_id)
    return {'requests': sum(by_status.values()), 'by_status': by_status,
            'points_redeemed': spent, 'top': top,
            'awaiting_fulfilment': waiting.count()}


def me(staff):
    player, _ = PlayerProfile.objects.get_or_create(staff=staff)
    today = timezone.localdate()
    totals = {}
    for p in ('day', 'week', 'month'):
        s, e = period_range(p, today)
        totals[p] = PointEvent.objects.filter(staff=staff, day__gte=s, day__lte=e) \
            .aggregate(n=Sum('points'))['n'] or 0
    m_start, m_end = period_range('month', today)
    by_cat = dict(PointEvent.objects.filter(staff=staff, day__gte=m_start, day__lte=m_end)
                  .values('category').annotate(n=Sum('points')).values_list('category', 'n'))
    cat_labels = dict(CATEGORY_CHOICES)
    return {
        **_staff_row(staff),
        'xp': player.xp, 'net_points': player.net_points,
        'level': level_progress(player.xp),
        'streak': {'current': player.current_streak, 'best': player.best_streak,
                   'last_clean_day': player.last_clean_day},
        'points': totals,
        'categories': [{'key': k, 'label_ar': cat_labels.get(k, k), 'points': v}
                       for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])],
        'rank': {
            'branch': rank_of(staff, m_start, m_end, branch_id=staff.branch_id)
            if staff.branch_id else None,
            'network_role': rank_of(staff, m_start, m_end, role=staff.role),
        },
        'badges': badges_for(staff),
        'recent': recent_events(staff),
        'open_items': open_items(staff),
        'wallet': _wallet(staff),
        'promotions': [{'level': _level_payload(h.level), 'reached_at': h.reached_at}
                       for h in LevelHistory.objects.filter(staff=staff)
                       .select_related('level')[:5]],
    }


def report(start, end, branch_id=None):
    """Executive overview for admins / managers."""
    ev = PointEvent.objects.filter(day__gte=start, day__lte=end, staff__is_active=True)
    ds = DailyScore.objects.filter(day__gte=start, day__lte=end, finalized=True)
    if branch_id:
        ev = ev.filter(staff__branch_id=branch_id)
        ds = ds.filter(branch_id=branch_id)
    agg = ev.aggregate(earned=Sum('points', filter=Q(points__gt=0)),
                       lost=Sum('points', filter=Q(points__lt=0)),
                       players=Count('staff_id', distinct=True), events=Count('id'))
    d = ds.aggregate(n=Count('id'), clean=Count('id', filter=Q(clean_day=True)),
                     left=Sum('left_behind'))
    cat_labels = dict(CATEGORY_CHOICES)
    cats = [{'key': r['category'], 'label_ar': cat_labels.get(r['category'], r['category']),
             'earned': r['earned'] or 0, 'lost': r['lost'] or 0, 'events': r['n']}
            for r in ev.values('category').annotate(
                earned=Sum('points', filter=Q(points__gt=0)),
                lost=Sum('points', filter=Q(points__lt=0)), n=Count('id')).order_by('category')]
    rules = {r.key: r for r in PointRule.objects.all()}
    by_rule = [{'key': r['rule_key'],
                'name_ar': rules[r['rule_key']].name_ar if r['rule_key'] in rules else r['rule_key'],
                'name_en': rules[r['rule_key']].name_en if r['rule_key'] in rules else r['rule_key'],
                'points': r['p'] or 0, 'events': r['n']}
               for r in ev.values('rule_key').annotate(p=Sum('points'), n=Count('id'))
               .order_by('-n')]
    staff_rows = ranking(start, end, branch_id=branch_id)
    level_dist = [{'level': _level_payload(lv),
                   'players': PlayerProfile.objects.filter(
                       level=lv, staff__is_active=True,
                       **({'staff__branch_id': branch_id} if branch_id else {})).count()}
                  for lv in Level.objects.order_by('number')]
    promos = LevelHistory.objects.filter(reached_at__date__gte=start, reached_at__date__lte=end)
    if branch_id:
        promos = promos.filter(staff__branch_id=branch_id)
    promotions = [{**_staff_row(h.staff), 'level': _level_payload(h.level),
                   'reached_at': h.reached_at}
                  for h in promos.select_related('staff__user', 'staff__branch', 'level')[:50]]
    return {
        'from': start, 'to': end,
        'kpis': {'players': agg['players'] or 0, 'events': agg['events'] or 0,
                 'earned': agg['earned'] or 0, 'lost': agg['lost'] or 0,
                 'clean_day_rate': round(d['clean'] * 100 / d['n'], 1) if d['n'] else None,
                 'left_behind': d['left'] or 0, 'promotions': promos.count()},
        'categories': cats,
        'rules': by_rule,
        'top': staff_rows[:10],
        'bottom': list(reversed(staff_rows[-10:])) if len(staff_rows) > 10 else [],
        'staff': staff_rows,
        'branches': [] if branch_id else branch_ranking(start, end),
        'levels': level_dist,
        'promotions': promotions,
        'rewards': rewards_summary(start, end, branch_id),
    }
