"""
apps/hr/attendance/health.py — alerts for the HR head about the fingerprint collection itself.

Checks, all on our own tables (CollectionRun and the device / agent rows the ingest keeps
current). Nothing here talks to a machine or to SOFTECH:

  • a machine with no successful collection for more than 24 hours (kind 'silent_device'); one
    that never succeeded counts from its oldest run
  • the collection agent silent for more than 3 hours (kind 'silent_agent')
  • a machine clock off by more than 5 minutes from the server, as the agent measured it
    against the server's time                          (kind 'drift')
  • the agent PC's own clock off by more than 5 minutes (kind 'pc_clock')
  • a machine's log count FELL between successive good runs (kind 'log_fall'): the machine
    holds its whole log, so a fall is evidence that logs were cleared.
  • files left behind on the agent for 3 hours or more (kind 'spool_waiting')

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


LOG_FALL_LOOKBACK = 30   # successful runs examined for a fall; after an outage many arrive at once


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
        # No success since this moment. A machine that has never succeeded counts from its
        # oldest run, so one failing hourly from day one is caught; one with no agent assigned,
        # or no run at all, stays quiet.
        never_succeeded = dev.last_contact_at is None
        since = dev.last_contact_at
        if never_succeeded and dev.agent_id:
            since = (CollectionRun.objects.filter(device=dev).order_by('started_at')
                     .values_list('started_at', flat=True).first())
        silent = bool(since and now - since > MACHINE_SILENT)
        if silent:
            hours = int((now - since).total_seconds() // 3600)
            body = (f'لم ينجح أي تجميع للبصمات من {label} منذ حوالي {hours} ساعة.' if never_succeeded
                    else f'لم تصل بصمات أو اتصال من {label} منذ حوالي {hours} ساعة.')
            found.append({
                'kind': 'silent_device', 'key': f'silent_device:{dev.pk}:{day}',
                'title': f'ماكينة البصمة صامتة: {dev.name}',
                'body': body,
            })
        # A silent machine keeps its last drift reading; repeating it daily would be noise.
        if not silent and dev.last_drift_seconds is not None and abs(dev.last_drift_seconds) > DRIFT_WARNING_SECONDS:
            minutes = round(abs(dev.last_drift_seconds) / 60)
            found.append({
                'kind': 'drift', 'key': f'drift:{dev.pk}:{day}',
                'title': f'ساعة الماكينة غير مضبوطة: {dev.name}',
                'body': f'ساعة {label} تختلف عن ساعة السيرفر بحوالي {minutes} دقيقة.',
            })
        # Recent SUCCESSFUL runs that read a count (a failed run says nothing about the log),
        # newest first. Every adjacent fall alerts, because after an outage hours of runs arrive
        # together and the fall may be in the middle.
        recent = list(CollectionRun.objects.filter(
            device=dev, status='success', device_log_count__isnull=False,
        ).order_by('-started_at', '-pk')[:LOG_FALL_LOOKBACK])
        for now_run, before in zip(recent, recent[1:]):
            if now_run.device_log_count < before.device_log_count:
                found.append({
                    # One alert per fall (the run), not per day: repeating it daily would say
                    # nothing new.
                    'kind': 'log_fall', 'key': f'log_fall:{dev.pk}:{now_run.pk}',
                    'title': f'انخفض عدد سجلات البصمة: {dev.name}',
                    'body': (f'عدد السجلات في {label} كان {before.device_log_count} وأصبح '
                             f'{now_run.device_log_count}. قد يكون السجل قد مُسح من الماكينة.'),
                })

        # A file the ERP refuses stays in the agent's spool while every run looks healthy: alert
        # when the newest runs have all reported files waiting, going back 3 hours or more.
        streak_start = None
        for run in CollectionRun.objects.filter(device=dev).order_by('-started_at', '-pk')[:30]:
            if not run.spool_waiting:         # 0 = cleared, None = not reported: either ends the streak
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
            continue    # its last clock reading is stale; the silence alert says what matters
        # The PC's own clock, as the agent measured it against the server at its last visit.
        offset = (CollectionRun.objects.filter(agent=agent, pc_offset_seconds__isnull=False)
                  .order_by('-pk').values_list('pc_offset_seconds', flat=True).first())
        if offset is not None and abs(offset) > DRIFT_WARNING_SECONDS:
            minutes = round(abs(offset) / 60)
            found.append({
                'kind': 'pc_clock', 'key': f'pc_clock:{agent.pk}:{day}',
                'title': f'ساعة جهاز برنامج التجميع غير مضبوطة: {agent.name}',
                'body': (f'ساعة الجهاز الذي يعمل عليه «{agent.name}» تختلف عن ساعة السيرفر بحوالي '
                         f'{minutes} دقيقة. اضبط التاريخ والوقت على ذلك الجهاز.'),
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
