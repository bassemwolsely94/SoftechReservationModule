"""
apps/hr/attendance/health.py — alerts for the HR head about the fingerprint collection itself.

Four checks, all on our own tables (CollectionRun and the device / agent rows the ingest keeps
current). Nothing here talks to a machine or to SOFTECH:

  • a machine silent for more than 24 hours          (kind 'silent_device')
  • the collection agent silent for more than 3 hours (kind 'silent_agent')
  • a machine clock off by more than 5 minutes        (kind 'drift')
  • a machine's log count FELL since the last good run (kind 'log_fall'): the machine holds
    its whole log, so a fall is evidence that logs were cleared.

Only admins and 'manage' grantees are told (access.manager_recipients). Alert text names the
machine, its place and the agent, never an employee. Alerts are in-app only.
"""
import datetime as _dt
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = 'attendance_alert'
MACHINE_SILENT = _dt.timedelta(hours=24)
AGENT_SILENT = _dt.timedelta(hours=3)
DRIFT_WARNING_SECONDS = 300
SPOOL_WAITING = _dt.timedelta(hours=3)


def _spool_waiting(run):
    """Files the agent still had waiting to upload at the end of this run, or None when the run
    doesn't say (an older agent)."""
    return run.spool_waiting


def _device_label(device):
    place = f' ({device.location_label})' if device.location_label else ''
    return f'{device.name}{place}'


def _alerts_for(now):
    """[{kind, key, title, body}] for everything wrong right now. `key` is the dedup identity."""
    from apps.hr.models import AttendanceAgent, AttendanceDevice, CollectionRun
    day = timezone.localtime(now).date().isoformat()
    found = []

    for dev in AttendanceDevice.objects.filter(is_active=True):
        label = _device_label(dev)
        silent = bool(dev.last_contact_at and now - dev.last_contact_at > MACHINE_SILENT)
        if silent:
            hours = int((now - dev.last_contact_at).total_seconds() // 3600)
            found.append({
                'kind': 'silent_device', 'key': f'silent_device:{dev.pk}:{day}',
                'title': f'ماكينة البصمة صامتة: {dev.name}',
                'body': f'لم تصل بصمات أو اتصال من {label} منذ حوالي {hours} ساعة.',
            })
        # A silent machine keeps its last drift reading; repeating it daily would be noise.
        if not silent and dev.last_drift_seconds is not None and abs(dev.last_drift_seconds) > DRIFT_WARNING_SECONDS:
            minutes = round(abs(dev.last_drift_seconds) / 60)
            found.append({
                'kind': 'drift', 'key': f'drift:{dev.pk}:{day}',
                'title': f'ساعة الماكينة غير مضبوطة: {dev.name}',
                'body': f'ساعة {label} تختلف عن ساعة السيرفر بحوالي {minutes} دقيقة.',
            })
        # Last two SUCCESSFUL runs that read a count; a failed run says nothing about the log.
        last_two = list(CollectionRun.objects.filter(
            device=dev, status='success', device_log_count__isnull=False,
        ).order_by('-started_at', '-pk')[:2])
        if len(last_two) == 2 and last_two[0].device_log_count < last_two[1].device_log_count:
            now_run, before = last_two
            found.append({
                # One alert per fall (the run), not per day: the pair stays the latest until the
                # next good run, and repeating it daily would say nothing new.
                'kind': 'log_fall', 'key': f'log_fall:{dev.pk}:{now_run.pk}',
                'title': f'انخفض عدد سجلات البصمة: {dev.name}',
                'body': (f'عدد السجلات في {label} كان {before.device_log_count} وأصبح '
                         f'{now_run.device_log_count}. قد يكون السجل قد مُسح من الماكينة.'),
            })

        # A file the ERP refuses stays in the agent's spool while every run looks healthy: alert
        # when the newest runs have all reported files waiting, going back 3 hours or more.
        streak_start = None
        for run in CollectionRun.objects.filter(device=dev).order_by('-started_at', '-pk')[:30]:
            waiting = _spool_waiting(run)
            if not waiting:          # 0 = cleared, None = not reported: either ends the streak
                break
            streak_start = run.started_at
        if streak_start is not None and now - streak_start >= SPOOL_WAITING:
            found.append({
                'kind': 'spool_waiting', 'key': f'spool_waiting:{dev.pk}:{day}',
                'title': f'بصمات لم تصل السيرفر: {dev.name}',
                'body': (f'برنامج التجميع يحتفظ بملفات بصمات من {label} لم يقبلها السيرفر منذ '
                         f'أكثر من 3 ساعات. راجع سجل البرنامج على الجهاز.'),
            })

    for agent in AttendanceAgent.objects.filter(revoked_at__isnull=True, last_seen_at__isnull=False):
        if now - agent.last_seen_at > AGENT_SILENT:
            hours = int((now - agent.last_seen_at).total_seconds() // 3600)
            found.append({
                'kind': 'silent_agent', 'key': f'silent_agent:{agent.pk}:{day}',
                'title': f'برنامج تجميع البصمات صامت: {agent.name}',
                'body': f'لم يتصل «{agent.name}» بالسيرفر منذ حوالي {hours} ساعة، فلا تُجمع البصمات.',
            })
    return found


def _notify(recipients, alert):
    from apps.notifications.models import Notification
    sent = 0
    for staff in recipients:
        made = Notification.send_to_user(
            staff, NOTIFICATION_TYPE, alert['title'], alert['body'],
            dedup_key=f"att:{alert['key']}", bypass_role_gate=True, dedup_once=True,
        )
        sent += 1 if made else 0
    return sent


def check_attendance_health(now=None) -> dict:
    """Run the four checks and tell the managers. Returns {'alerts': [...], 'sent': n}."""
    if not getattr(settings, 'HR_ATTENDANCE_ENABLED', False):
        return {'alerts': [], 'sent': 0}
    from apps.hr.attendance.access import manager_recipients
    now = now or timezone.now()
    alerts = _alerts_for(now)
    recipients = manager_recipients() if alerts else []
    sent = sum(_notify(recipients, a) for a in alerts)
    if alerts:
        logger.info('attendance health: %d alert(s), %d notification(s) sent', len(alerts), sent)
    return {'alerts': [{'kind': a['kind'], 'key': a['key']} for a in alerts], 'sent': sent}
