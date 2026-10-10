"""
apps/help/notify.py — tell people when their training changes.

  path_changed  — a role's training path gained screens → everyone in that role
  quiz_changed  — a module quiz changed → everyone who had passed it (their pass no
                  longer counts until they retake it)

Reuses apps.notifications (WebSocket + push + persistence + dedup) like the other
modules. Never raises: a notification failure must not break the trainer's save.
"""
import logging

logger = logging.getLogger(__name__)


def _send(staff_qs, title, body, dedup_key):
    from apps.notifications.models import Notification
    sent = 0
    for sp in staff_qs:
        if Notification.send_to_user(sp, 'system', title, body, dedup_key=dedup_key):
            sent += 1
    return sent


def path_changed(role, before, after, revision_id):
    """→ number notified. Only screens ADDED to the path are news; removals are not."""
    try:
        from apps.users.models import StaffProfile
        from . import registry
        added = [k for k in after if k not in set(before or [])]
        if not added:
            return 0
        _, screens = registry.load()
        names = '، '.join(screens[k]['title']['ar'] for k in added[:5] if k in screens)
        more = f' و{len(added) - 5} غيرها' if len(added) > 5 else ''
        return _send(
            StaffProfile.objects.filter(role=role, is_active=True, user__is_active=True),
            '🎓 شاشات جديدة في مسارك التدريبي',
            f'اتضاف لمسارك: {names}{more}. افتح «دليل الاستخدام» ← «مساري التدريبي».',
            dedup_key=f'help_path_{role}_{revision_id}')
    except Exception as exc:
        logger.warning('help path_changed notify skipped: %s', exc)
        return 0


def quiz_changed(module_key, old_version, new_version, revision_id):
    """→ number notified: people who passed the old version of this quiz."""
    try:
        if old_version == new_version:
            return 0
        from apps.users.models import StaffProfile
        from . import registry
        from .models import HelpQuizAttempt
        ids = (HelpQuizAttempt.objects.filter(module_key=module_key, version=old_version, passed=True)
               .values_list('staff_id', flat=True).distinct())
        modules, _ = registry.load()
        title = modules.get(module_key, {}).get('title', {}).get('ar', module_key)
        return _send(
            StaffProfile.objects.filter(id__in=list(ids), is_active=True, user__is_active=True),
            '📝 اختبار اتحدّث — أعد الاختبار',
            f'اختبار «{title}» اتغيّر بعد ما نجحت فيه. ادخل «مساري التدريبي» وأعد الاختبار عشان يتحسب.',
            dedup_key=f'help_quiz_{module_key}_{revision_id}')
    except Exception as exc:
        logger.warning('help quiz_changed notify skipped: %s', exc)
        return 0
