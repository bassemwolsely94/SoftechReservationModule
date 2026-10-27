"""
apps/help/digest.py — weekly training digest for supervisors.

Every person allowed to supervise training (RBAC help/edit — admins, and by default
supervisors + quality managers) gets one notification a week about the people in the
branches they can see:
  ✅ finished their training path this week
  ⏳ stuck — no training activity for STUCK_DAYS+ days (incl. never started)
  ❌ failed a quiz (best attempt on the current version below the pass mark)
  ⟳ must retake a quiz that changed after they passed it
  📝 the «what changed» one-liners trainers / developers wrote this week (same for all)
Names are capped per line; the full list is in «دليل الاستخدام» ← «للمدربين».
Delivered through apps.notifications (same as every other module); never raises.
"""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

from .onboarding_views import STUCK_DAYS  # noqa: E402 — one rule for digest, team view, «تذكير»
MAX_NAMES = 5
MAX_NOTES = 3


def enabled():
    try:
        from apps.config.models import SystemSetting
        return str(SystemSetting.get('help_training_digest_enabled', 'true')).lower() in ('1', 'true', 'yes')
    except Exception:
        return True


def recipients():
    from apps.users.models import StaffProfile
    return [p for p in StaffProfile.objects.filter(is_active=True, user__is_active=True).select_related('user')
            if p.can_do('help', 'edit')]


def week_notes(now=None):
    """The «what changed» notes of the last 7 days (onboarding_views.recent_notes)."""
    from .onboarding_views import recent_notes
    return recent_notes(days=7, now=now)


def summary_for(supervisor, now=None, notes=None):
    """→ dict with the four lists (rows from onboarding_views.team_rows), scoped to
    the supervisor's branches; the supervisor is left out of their own digest."""
    from apps.users.models import StaffProfile
    from .onboarding_views import team_rows
    now = now or timezone.now()
    week_ago = now - timezone.timedelta(days=7)
    staff = StaffProfile.objects.filter(is_active=True, user__is_active=True).exclude(pk=supervisor.pk)
    allowed = supervisor.accessible_branch_ids
    if allowed is not None:
        staff = staff.filter(branch_id__in=allowed)
    rows = team_rows(staff, limit=2000)
    done = [r for r in rows if r['progress']['percent'] >= 100]
    return {
        'team': len(rows),
        'complete': len(done),
        'finished_this_week': [r for r in done if r['last_activity'] and r['last_activity'] >= week_ago],
        'stuck': [r for r in rows if r['stuck']],
        'failed': [r for r in rows if r['failed_quizzes']],
        'retake': [r for r in rows if r['retake_quizzes']],
        'notes': week_notes(now) if notes is None else notes,
    }


def _names(rows, detail=None):
    shown = [r['name'] + (f' ({detail(r)})' if detail else '') for r in rows[:MAX_NAMES]]
    more = len(rows) - MAX_NAMES
    return '، '.join(shown) + (f' و{more} غيرهم' if more > 0 else '')


def render(s):
    """→ (title, body) in Arabic, short enough for a notification."""
    from . import registry
    modules, _ = registry.load()
    mod = lambda keys: '، '.join(modules.get(k, {}).get('title', {}).get('ar', k) for k in keys)
    lines = [f"الفريق: {s['team']} — أنهوا التدريب: {s['complete']}."]
    if s['finished_this_week']:
        lines.append(f"✅ خلّصوا الأسبوع ده ({len(s['finished_this_week'])}): {_names(s['finished_this_week'])}")
    if s['stuck']:
        lines.append(f"⏳ واقفين من {STUCK_DAYS}+ أيام ({len(s['stuck'])}): "
                     f"{_names(s['stuck'], lambda r: str(r['progress']['percent']) + '%')}")
    if s['failed']:
        lines.append(f"❌ رسبوا في اختبار ({len(s['failed'])}): {_names(s['failed'], lambda r: mod(r['failed_quizzes']))}")
    if s['retake']:
        lines.append(f"⟳ محتاجين يعيدوا اختبار اتغيّر ({len(s['retake'])}): {_names(s['retake'], lambda r: mod(r['retake_quizzes']))}")
    if s.get('notes'):
        shown = '؛ '.join(f"{n['title']['ar']}: «{n['note']}»" for n in s['notes'][:MAX_NOTES])
        more = len(s['notes']) - MAX_NOTES
        lines.append(f"📝 اتحدّث في التدريب ({len(s['notes'])}): {shown}" + (f' و{more} غيرها' if more > 0 else ''))
    lines.append('التفاصيل وزر «🔔 تذكير»: دليل الاستخدام ← للمدربين ← تقدّم الفريق في التدريب.')
    return '📊 ملخص التدريب الأسبوعي', '\n'.join(lines)


def send_weekly(now=None, dry_run=False):
    """Send each supervisor their digest (once per ISO week). → list of (supervisor, title, body)."""
    out = []
    if not enabled():
        return out
    now = now or timezone.now()
    year, week, _ = timezone.localtime(now).isocalendar()
    try:
        notes = week_notes(now)
    except Exception as exc:
        logger.warning('help training digest notes skipped: %s', exc)
        notes = []
    for sup in recipients():
        try:
            s = summary_for(sup, now, notes)
            if not s['team']:
                continue
            title, body = render(s)
            out.append((sup, title, body))
            if dry_run:
                continue
            from apps.notifications.models import Notification
            Notification.send_to_user(sup, 'system', title, body,
                                      dedup_key=f'help_training_digest_{sup.pk}_{year}w{week}', dedup_once=True)
        except Exception as exc:
            logger.warning('help training digest for %s skipped: %s', sup.pk, exc)
    return out
