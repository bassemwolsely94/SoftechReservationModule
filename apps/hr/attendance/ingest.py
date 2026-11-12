"""
apps/hr/attendance/ingest.py — storing what the agent sends.

Punches are evidence. Identity is (device, user_code, raw_stamp, state), so a date the machine got
wrong is stored flagged and never lost, and resending is safe. Only a request that breaks the
agent's contract (no usable identity on a row) is refused, whole: the agent keeps that file.
Logs here hold counts and class names only, never names or user codes.
"""
import datetime as _dt
import logging

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.hr.models import AttendanceDevice, AttendancePunch, CollectionRun, DeviceUser
from core.errors import redact

from . import resolve

logger = logging.getLogger('elrezeiky.hr_attendance')

MAX_PUNCHES_PER_REQUEST = 2000
MAX_ROSTER_USERS = 20000   # far above any machine's capacity; the agent sends a roster in one request
FLAG_BAD_DATE = 'bad_date'
EARLIEST_GOOD_DATE = _dt.date(2015, 1, 1)
MAX_FUTURE_DAYS = 1

_MAX_CODE = AttendancePunch._meta.get_field('user_code').max_length
_MAX_NAME = DeviceUser._meta.get_field('device_name').max_length
_MAX_ERROR = CollectionRun._meta.get_field('error').max_length
_SMALLINT_MIN, _SMALLINT_MAX = -32768, 32767
_BIGINT_MAX = 2 ** 63 - 1
_INT_MIN, _INT_MAX = -2147483648, 2147483647


class Malformed(ValueError):
    """The whole request breaks the contract. The text is fixed and holds no sent value."""


def is_bad_date(d, today) -> bool:
    """No date, before 2015, or more than 1 day in the future."""
    if d is None:
        return True
    return d < EARLIEST_GOOD_DATE or d > today + _dt.timedelta(days=MAX_FUTURE_DAYS)


def is_storable_text(value) -> bool:
    """PostgreSQL refuses NUL and text that isn't valid UTF-8 (a lone surrogate from JSON)."""
    if not isinstance(value, str) or chr(0) in value:
        return False
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def _storable(text) -> str:
    return text.replace(chr(0), '').encode('utf-8', 'ignore').decode('utf-8')


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_date(value):
    """A date, or None when it can't be one (Feb 31, junk): the caller flags it."""
    if isinstance(value, str):
        try:
            return _dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _parse_time(value):
    if isinstance(value, str):
        try:
            parsed = _dt.time.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is None else None
    return None


def _clean_code(value) -> str:
    if not is_storable_text(value) or len(value) > _MAX_CODE:
        raise Malformed('user_code')
    return value


def _punch_from_row(device, row, today):
    if not isinstance(row, dict):
        raise Malformed('punch row')
    raw_stamp, state, verify_mode = row.get('raw_stamp'), row.get('state'), row.get('verify_mode')
    if not _is_int(raw_stamp) or not 0 <= raw_stamp <= _BIGINT_MAX:
        raise Malformed('raw_stamp')
    for value in (state, verify_mode):
        if not _is_int(value) or not _SMALLINT_MIN <= value <= _SMALLINT_MAX:
            raise Malformed('state or verify_mode')
    punch_date, punch_time = _parse_date(row.get('date')), _parse_time(row.get('time'))
    bad = is_bad_date(punch_date, today) or punch_time is None
    return AttendancePunch(
        device=device, user_code=_clean_code(row.get('user_code')), raw_stamp=raw_stamp,
        punch_date=punch_date, punch_time=punch_time, state=state, verify_mode=verify_mode,
        flag=FLAG_BAD_DATE if bad else '')


def _resolve_all(codes) -> None:
    """Resolution is derived and is recalculated on the next resend, so its failure must never
    refuse punches that are already safely stored."""
    for code in codes:
        try:
            with transaction.atomic():
                resolve.resolve_user_code(code)
        except Exception as exc:  # the punches are stored; see the docstring
            logger.error('attendance resolve failed: %s', type(exc).__name__)


def store_punches(device, rows, today=None) -> tuple[int, int]:
    """Store a batch, all or nothing. Returns (accepted, duplicate), which add up to len(rows)."""
    today = today or timezone.localdate()
    punches = {}
    for row in rows:
        punch = _punch_from_row(device, row, today)
        punches.setdefault((punch.user_code, punch.raw_stamp, punch.state), punch)
    with transaction.atomic():
        # One batch per machine at a time, so the pre-query below stays true until the insert.
        AttendanceDevice.objects.select_for_update().get(pk=device.pk)
        stamps = {punch.raw_stamp for punch in punches.values()}
        existing = set(AttendancePunch.objects.filter(device=device, raw_stamp__in=stamps)
                       .values_list('user_code', 'raw_stamp', 'state'))
        new = [punch for key, punch in punches.items() if key not in existing]
        AttendancePunch.objects.bulk_create(new, ignore_conflicts=True)
    # Duplicates too: the agent resends the whole log hourly, so an ID added since heals by itself.
    _resolve_all({punch.user_code for punch in punches.values()})
    return len(new), len(rows) - len(new)


def store_roster(device, users) -> int:
    """Update this machine's roster. Entries missing from it stay. Returns the rows received."""
    clean = []
    for user in users:
        if not isinstance(user, dict):
            raise Malformed('roster row')
        name = user.get('name')
        name = _storable(name)[:_MAX_NAME] if isinstance(name, str) else ''
        clean.append((_clean_code(user.get('user_code')), name, bool(user.get('is_admin'))))
    now = timezone.now()
    changed = set()
    with transaction.atomic():
        AttendanceDevice.objects.select_for_update().get(pk=device.pk)
        known = dict(DeviceUser.objects.filter(device=device).values_list('user_code', 'device_name'))
        for code, name, is_admin in clean:
            if known.get(code) != name:
                changed.add(code)
            DeviceUser.objects.update_or_create(
                device=device, user_code=code,
                defaults={'device_name': name, 'is_admin': is_admin, 'last_seen_at': now})
    # A changed name can start or end a conflict for that ID.
    _resolve_all(changed)
    return len(clean)


def _parse_moment(value):
    """A timezone-aware datetime, or None. The agent sends naive local time (Africa/Cairo)."""
    if not isinstance(value, str):
        return None
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _range_date(value, today):
    parsed = _parse_date(value)
    return None if is_bad_date(parsed, today) else parsed


def _count_or_none(value):
    return value if _is_int(value) and 0 <= value <= _INT_MAX else None


def _drift(value):
    # A clock decades off passes what the column holds; it must still read as a huge drift.
    return max(_INT_MIN, min(_INT_MAX, value)) if _is_int(value) else None


def _update_device(device, run, finished_at, now) -> None:
    """Device state follows the latest report to arrive. Comparing started_at would trust the
    agent PC's clock, and one wrong date would freeze this state. Only a success counts as contact,
    so a machine that keeps failing still looks silent to the health check. On a success the drift
    is written even when null: an unknown clock must not keep showing the last good value."""
    fields = {'last_status': run.status}
    if run.status == 'success':
        contact = min(finished_at or run.started_at, now)
        if device.last_contact_at is None or contact > device.last_contact_at:
            fields['last_contact_at'] = contact
        fields['last_drift_seconds'] = run.drift_seconds
        if run.device_log_count is not None:
            fields['last_log_count'] = run.device_log_count
    AttendanceDevice.objects.filter(pk=device.pk).update(**fields)


def store_run(agent, device, body, today=None) -> bool:
    """Store one run report. Returns False when this device + started_at was already stored: a
    repeat changes nothing, so an old report can't cancel a newer collect-now request."""
    today = today or timezone.localdate()
    started_at = _parse_moment(body.get('started_at'))
    status = body.get('status')
    if started_at is None:
        raise Malformed('started_at')
    if not isinstance(status, str) or status not in dict(CollectionRun.STATUS_CHOICES):
        raise Malformed('status')
    finished_at = _parse_moment(body.get('finished_at'))
    error = body.get('error')
    with transaction.atomic():
        locked = AttendanceDevice.objects.select_for_update().get(pk=device.pk)
        run, created = CollectionRun.objects.get_or_create(
            device=device, started_at=started_at,
            defaults={
                'agent': agent, 'finished_at': finished_at, 'status': status,
                'records_read': _count_or_none(body.get('records_read')) or 0,
                'oldest_date': _range_date(body.get('oldest_date'), today),
                'newest_date': _range_date(body.get('newest_date'), today),
                'drift_seconds': _drift(body.get('drift_seconds')),
                'device_log_count': _count_or_none(body.get('device_log_count')),
                'spool_waiting': _count_or_none(body.get('spool_waiting')),
                'pc_offset_seconds': _drift(body.get('pc_offset_seconds')),
                'error': _storable(redact(error))[:_MAX_ERROR] if isinstance(error, str) else '',
            })
        if created:
            _update_device(locked, run, finished_at, timezone.now())
            if body.get('collect_done') is True:
                type(agent).objects.filter(pk=agent.pk).update(collect_requested_at=None)
    return created
