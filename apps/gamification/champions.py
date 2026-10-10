"""
apps/gamification/champions.py — بطل الشهر (monthly champions).

crown(month) runs once per month (scheduler, 1st of the month 01:05, for the month
that just ended) and is idempotent: ChampionMonth.month is UNIQUE, so a second call
returns the existing result.

  • Branch champion  — #1 of each role inside each branch (group needs ≥ MIN_PLAYERS
                       players) → +champion_branch
  • Network podium   — top 3 of each role across all branches → #1 +champion_network,
                       #2/#3 +podium_network
  • Branch of the month — #1 of the branch ranking (average per active player, branches
                       with ≥ MIN_BRANCH_PLAYERS players); recognition only
Eligible: active staff (not in GAMIFICATION_CHAMPION_EXCLUDED_ROLES — admin, viewer by
default) with a positive month score and NO escalated audit flag
(`abuse_flag` deduction) that month. Ranking points exclude champion bonuses, so the
bonus from last month never decides this month.

Results: one pinned, network-wide announcement (apps.notifications.Announcement, fanned
out to the bell) + a personal notification to each winner. revoke() withdraws a title
with a written reason and reverses its bonus (XP, wallet) through the ledger.
"""
import logging
from calendar import monthrange
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import engine, services
from .models import Champion, ChampionMonth, GamificationChange, PointEvent

logger = logging.getLogger(__name__)

MONTHS_AR = ['يناير', 'فبراير', 'مارس', 'أبريل', 'مايو', 'يونيو', 'يوليو', 'أغسطس',
             'سبتمبر', 'أكتوبر', 'نوفمبر', 'ديسمبر']
MONTHS_EN = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
             'September', 'October', 'November', 'December']
ROLE_AR = {'salesperson': 'مندوبو البيع', 'pharmacist': 'الصيادلة', 'call_center': 'الكول سنتر',
           'delivery': 'التوصيل', 'purchasing': 'المشتريات', 'supervisor': 'المشرفون',
           'quality_manager': 'الجودة', 'admin': 'الإدارة', 'viewer': 'المشاهدون'}


def min_players():
    return int(getattr(settings, 'GAMIFICATION_CHAMPION_MIN_PLAYERS', 2))


def min_branch_players():
    return int(getattr(settings, 'GAMIFICATION_BRANCH_OF_MONTH_MIN_PLAYERS', 3))


def excluded_roles():
    """Roles that never compete for a title (management judges, it does not compete)."""
    return set(getattr(settings, 'GAMIFICATION_CHAMPION_EXCLUDED_ROLES', ['admin', 'viewer']))


def month_label(m):
    return f'{MONTHS_AR[m.month - 1]} {m.year}', f'{MONTHS_EN[m.month - 1]} {m.year}'


def month_bounds(m):
    m = m.replace(day=1)
    return m, m.replace(day=monthrange(m.year, m.month)[1])


def previous_month(today=None):
    today = today or timezone.localdate()
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def _excluded(start, end):
    """Staff with an escalated audit flag in the month — not eligible for a title."""
    return set(PointEvent.objects.filter(day__gte=start, day__lte=end, rule_key='abuse_flag')
               .values_list('staff_id', flat=True))


def standings(start, end):
    """Ranked rows grouped for crowning: {'network': {role: [...]},
    'branch': {(branch_id, role): [...]}, 'players': {...}}. Pure read."""
    skip = excluded_roles()
    rows = [r for r in services.ranking(start, end) if r['role'] not in skip]
    out = {'network': {}, 'branch': {}, 'branch_players': {}}
    excluded = _excluded(start, end)
    for r in rows:
        key = (r['branch_id'], r['role'])
        out['branch_players'][key] = out['branch_players'].get(key, 0) + 1
        if r['staff_id'] in excluded or r['net'] <= 0:
            continue
        out['network'].setdefault(r['role'], []).append(r)
        if r['branch_id']:
            out['branch'].setdefault(key, []).append(r)
    out['network_players'] = {}
    for r in rows:
        out['network_players'][r['role']] = out['network_players'].get(r['role'], 0) + 1
    return out


def crown(month, by=None):
    """Crown `month` (any date in it). Returns (ChampionMonth, created)."""
    start, end = month_bounds(month)
    if end >= timezone.localdate():
        raise ValueError('لا يمكن تتويج شهر لم ينته بعد — the month has not ended yet')
    with transaction.atomic():
        cm, created = ChampionMonth.objects.select_for_update().get_or_create(
            month=start, defaults={'crowned_by': by})
        if not created:
            return cm, False
        st = standings(start, end)
        sc = engine.Scorer()
        now = timezone.now()
        made = []

        def add(kind, r, rank, players, rule=None):
            bonus = 0
            if rule:
                ev = sc.award(r['staff_id'], rule,
                              f"champ:{start:%Y-%m}:{kind}:{r['role']}:{r['branch_id'] or 0}:{rank}",
                              now, meta={'month': f'{start:%Y-%m}', 'rank': rank, 'kind': kind})
                bonus = ev.points if ev else 0
            made.append(Champion.objects.create(
                champion_month=cm, month=start, kind=kind, role=r['role'],
                branch_id=r['branch_id'], staff_id=r['staff_id'], rank=rank, net=r['net'],
                players=players, bonus=bonus))

        for role, rows in st['network'].items():
            for rank, r in enumerate(rows[:3], 1):
                add(Champion.KIND_NETWORK, r, rank, st['network_players'].get(role, 0),
                    'champion_network' if rank == 1 else 'podium_network')
        for (branch_id, role), rows in st['branch'].items():
            players = st['branch_players'].get((branch_id, role), 0)
            if players >= min_players():
                add(Champion.KIND_BRANCH, rows[0], 1, players, 'champion_branch')

        branches = [b for b in services.branch_ranking(start, end)
                    if b['players'] >= min_branch_players()]
        if branches:
            b = branches[0]
            made.append(Champion.objects.create(
                champion_month=cm, month=start, kind=Champion.KIND_BRANCH_OF_MONTH,
                branch_id=b['branch_id'], rank=1, net=b['net'], players=b['players']))

        cm.summary = {'network': sum(1 for c in made if c.kind == Champion.KIND_NETWORK),
                      'branch': sum(1 for c in made if c.kind == Champion.KIND_BRANCH),
                      'branch_of_month': next((c.branch_id for c in made
                                               if c.kind == Champion.KIND_BRANCH_OF_MONTH), None)}
        cm.save(update_fields=['summary'])
        if by is not None:
            GamificationChange.objects.create(actor=by, action='crown', target=f'month:{start:%Y-%m}',
                                              after=cm.summary)
    engine.refresh_players({c.staff_id for c in made if c.staff_id})
    _announce(cm, made)
    _notify_winners(cm, made)
    return cm, True


def _name(c):
    return c.staff.full_name if c.staff_id else ''


def _announce(cm, made):
    if not made:
        return
    try:
        from apps.notifications.models import Announcement
        ar, en = month_label(cm.month)
        lines = [f'🏆 أبطال الشبكة — {ar}']
        for c in sorted((c for c in made if c.kind == Champion.KIND_NETWORK),
                        key=lambda c: (c.role, c.rank)):
            medal = {1: '🥇', 2: '🥈', 3: '🥉'}[c.rank]
            lines.append(f'{medal} {ROLE_AR.get(c.role, c.role)}: {_name(c)} '
                         f'({c.branch.name if c.branch_id else ""}) — {c.net:,} نقطة')
        champs = [c for c in made if c.kind == Champion.KIND_BRANCH]
        if champs:
            lines.append('')
            lines.append('👑 أبطال الفروع:')
            for c in sorted(champs, key=lambda c: (c.branch.name if c.branch_id else '', c.role)):
                lines.append(f'• {c.branch.name if c.branch_id else ""} — '
                             f'{ROLE_AR.get(c.role, c.role)}: {_name(c)}')
        bom = next((c for c in made if c.kind == Champion.KIND_BRANCH_OF_MONTH), None)
        if bom:
            lines += ['', f'🏢 فرع الشهر: {bom.branch.name if bom.branch_id else ""}']
        lines += ['', f'Congratulations to the {en} champions! Full list: /gamification?tab=champions']
        ann = Announcement.objects.create(
            title=f'🏆 أبطال شهر {ar} — {en} champions', body='\n'.join(lines),
            priority=Announcement.PRIORITY_HIGH, is_pinned=True,
            expires_at=timezone.now() + timedelta(days=10))
        cm.announcement = ann
        cm.save(update_fields=['announcement'])
        ann.fan_out()
    except Exception as exc:
        logger.warning('champion announcement failed: %s', exc)


def _notify_winners(cm, made):
    from apps.notifications.models import Notification
    ar, en = month_label(cm.month)
    for c in made:
        if not c.staff_id:
            continue
        if c.kind == Champion.KIND_NETWORK:
            what = {1: '🥇 بطل الشبكة', 2: '🥈 الثاني على الشبكة', 3: '🥉 الثالث على الشبكة'}[c.rank]
        else:
            what = '👑 بطل فرعك'
        try:
            Notification.objects.create(
                recipient=c.staff, notification_type='gamification_champion',
                title=f'{what} لشهر {ar}!',
                body=f'+{c.bonus:,} نقطة مكافأة. Congratulations — {en}.',
                dedup_key=f'gam_champ_{c.id}')
        except Exception as exc:
            logger.warning('champion notify failed: %s', exc)


def revoke(champion, by, reason):
    """Withdraw a title (e.g. a confirmed abuse found later). Reverses the bonus."""
    if champion.revoked:
        raise ValueError('اللقب مسحوب بالفعل — already revoked')
    with transaction.atomic():
        c = Champion.objects.select_for_update().get(pk=champion.pk)
        c.revoked, c.revoked_by, c.revoked_at = True, by, timezone.now()
        c.revoke_reason = reason[:300]
        c.save(update_fields=['revoked', 'revoked_by', 'revoked_at', 'revoke_reason'])
        if c.staff_id and c.bonus:
            engine.Scorer().award(c.staff_id, 'champion_revoked', f'revoke:{c.id}',
                                  timezone.now(), points=-c.bonus, reason=reason[:300],
                                  created_by=by)
        GamificationChange.objects.create(actor=by, action='champion_revoke',
                                          target=f'champion:{c.id}', before={'bonus': c.bonus},
                                          after={'revoked': True}, reason=reason[:300])
    if c.staff_id:
        from .models import Badge, StaffBadge
        # badges that depended on this title and are no longer earned
        for sb in StaffBadge.objects.filter(staff_id=c.staff_id,
                                            badge__criteria=Badge.CRITERIA_CHAMPION).select_related('badge'):
            if engine._titles(c.staff, sb.badge.rule_key) < sb.badge.threshold:
                sb.delete()
        engine.refresh_players([c.staff_id])
    return c


def champion_json(c):
    return {'id': c.id, 'month': c.month, 'kind': c.kind, 'role': c.role,
            'branch_id': c.branch_id, 'branch': c.branch.name if c.branch_id else '',
            'staff_id': c.staff_id, 'name': _name(c), 'rank': c.rank, 'net': c.net,
            'players': c.players, 'bonus': c.bonus, 'revoked': c.revoked,
            'revoke_reason': c.revoke_reason}


def board(month=None):
    """Hall of fame for a crowned month (default: the latest) + the list of months."""
    months = list(ChampionMonth.objects.values_list('month', flat=True)[:24])
    cm = None
    if month:
        cm = ChampionMonth.objects.filter(month=month.replace(day=1)).first()
    elif months:
        cm = ChampionMonth.objects.filter(month=months[0]).first()
    data = {'months': months, 'month': cm.month if cm else None, 'champions': []}
    if cm:
        ar, en = month_label(cm.month)
        data.update(label_ar=ar, label_en=en,
                    announcement_id=cm.announcement_id,
                    champions=[champion_json(c) for c in cm.champions.select_related(
                        'staff__user', 'branch')])
    return data


def race(staff, today=None):
    """The current month, live: who leads each role on the network and in my branch."""
    today = today or timezone.localdate()
    start = today.replace(day=1)
    st = standings(start, today)
    def top3(rows):     # rank inside the group, not in the overall list
        return [{'rank': i, 'staff_id': r['staff_id'], 'name': r['name'],
                 'branch': r['branch'], 'net': r['net']} for i, r in enumerate(rows[:3], 1)]
    network = {role: top3(rows) for role, rows in st['network'].items()}
    mine = {role: top3(rows) for (bid, role), rows in st['branch'].items()
            if staff.branch_id and bid == staff.branch_id}
    days_left = month_bounds(today)[1].day - today.day
    return {'from': start, 'to': today, 'days_left': days_left,
            'network': network, 'my_branch': mine}


def titles_for(staff, limit=12):
    return [champion_json(c) for c in Champion.objects.filter(staff=staff, revoked=False)
            .select_related('staff__user', 'branch')[:limit]]
