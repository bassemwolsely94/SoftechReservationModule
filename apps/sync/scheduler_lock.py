"""
apps/sync/scheduler_lock.py — only ONE scheduler process may run (round 2, owner OK 2026-11-05).

APScheduler's `max_instances=1` only stops a job overlapping itself inside one process. Two
`run_scheduler` processes (a service restart that left the old one alive, a second terminal, the
laptop and the VPS pointed at one database) each run every job: alerts and briefs go out twice,
engines run twice, and a few jobs have only a racy "already done?" check (see
apps/tests/test_scheduler_locks.py).

`acquire()` takes a PostgreSQL session advisory lock on a connection of its own, held for the
life of the process (the lock goes when the process or its connection dies). A second process
does not get it: it starts NO jobs, alerts the admins in the app (once per day per host) and
exits non-zero, so the service manager shows the failure.
"""
from __future__ import annotations

import logging
import os
import socket

logger = logging.getLogger(__name__)

SCHEDULER_LOCK_KEY = 7_301_100          # pg advisory key, next to the 7_301_0xx SOFTECH write locks
OWNER_SETTING = 'scheduler_lock_owner'   # SystemSetting: which host / pid holds the lock

_held = None                             # the raw connection that holds the lock


def _who() -> str:
    return f'{socket.gethostname()} pid {os.getpid()}'


def _raw_connection():
    """A database connection outside Django's per-thread pool, so no job or close_old_connections
    can close it (closing it would silently release the lock)."""
    from django.db import connections
    wrapper = connections['default']
    conn = wrapper.get_new_connection(wrapper.get_connection_params())
    conn.autocommit = True
    return conn


def acquire() -> bool:
    """True when this process now holds the single-scheduler lock (idempotent within a process)."""
    global _held
    if _held is not None:
        return True
    conn = _raw_connection()
    with conn.cursor() as cur:
        cur.execute('SELECT pg_try_advisory_lock(%s)', [SCHEDULER_LOCK_KEY])
        got = bool(cur.fetchone()[0])
    if not got:
        conn.close()
        return False
    _held = conn
    _record_owner()
    return True


def release() -> None:
    global _held
    if _held is None:
        return
    try:
        with _held.cursor() as cur:
            cur.execute('SELECT pg_advisory_unlock(%s)', [SCHEDULER_LOCK_KEY])
    except Exception:
        pass
    try:
        _held.close()
    except Exception:
        pass
    _held = None


def _record_owner() -> None:
    try:
        from django.utils import timezone
        from apps.config.models import SystemSetting
        SystemSetting.objects.update_or_create(
            key=OWNER_SETTING,
            defaults={'value': f'{_who()} since {timezone.now().isoformat(timespec="seconds")}',
                      'value_type': 'string', 'label': 'المجدول الذي يعمل الآن', 'category': 'general'})
    except Exception:
        logger.warning('scheduler lock: could not record the owner', exc_info=True)


def current_owner() -> str:
    try:
        from apps.config.models import SystemSetting
        return str(SystemSetting.get(OWNER_SETTING, '') or '')
    except Exception:
        return ''


def alert_second_scheduler() -> None:
    """In-app alert to admins: a second scheduler tried to start and was stopped."""
    owner = current_owner() or 'غير معروف'
    me = _who()
    logger.error('scheduler lock: another scheduler already runs (%s) — %s is NOT starting jobs', owner, me)
    try:
        from django.utils import timezone
        from apps.notifications.models import Notification
        Notification.send_to_roles(
            roles=['admin'], notification_type='system',
            title='⚠️ محاولة تشغيل مجدول ثانٍ — تم إيقافها',
            body=(f'حاول «{me}» تشغيل المجدول بينما مجدول آخر يعمل ({owner}). '
                  'لم يبدأ أي مهمة حتى لا تتكرر الرسائل والمزامنة. لو المجدول الأول متوقف فعلاً، '
                  'أوقفه نهائياً ثم أعد التشغيل.'),
            dedup_key=f'scheduler-second:{socket.gethostname()}:{timezone.localdate().isoformat()}',
            dedup_once=True)
    except Exception:
        logger.warning('scheduler lock: could not send the in-app alert', exc_info=True)
