"""
apps/hr/attendance/lg_ingest.py — storing the Linked Gates rows the agent sends.

A Linked Gates check row is evidence, stored as VERSIONS: a new check id is version 1; if the portal
later shows a different time / enroll number / machine for a known id, the current version is marked
superseded and version n+1 is added. A full re-read also marks current rows that vanished from the
source (lg_removed). Nothing is ever deleted or rewritten. Logs hold counts only.
"""
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.hr.models import AttendanceDevice, LinkedGatesDevice, LinkedGatesEmployee, LinkedGatesPunch

from . import ingest as ingest_module
from .ingest import FLAG_BAD_DATE, Malformed, is_bad_date, is_storable_text

MAX_LG_ROWS_PER_REQUEST = 5000
_INT_MIN, _INT_MAX = -2147483648, 2147483647
_BIGINT_MAX = 2 ** 63 - 1


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _opt_int(value):
    if value is None:
        return None
    if not _is_int(value) or not _INT_MIN <= value <= _INT_MAX:
        raise Malformed('int')
    return value


def _moment(value):
    """Naive Cairo time from the agent -> aware datetime, or None when it is NULL or unreadable."""
    if not isinstance(value, str):
        return None
    try:
        parsed = parse_datetime(value)
    except ValueError:
        return None
    if parsed is None:
        return None
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


def _clean_row(row):
    """A usable row, or None when its check_time is NULL or unreadable (the caller counts it as
    skipped). A wrong JSON type anywhere else breaks the contract: Malformed, whole request."""
    if not isinstance(row, dict):
        raise Malformed('lg row')
    check_id, enroll = row.get('lg_check_id'), row.get('enroll_no')
    if not _is_int(check_id) or not 0 <= check_id <= _BIGINT_MAX:
        raise Malformed('lg_check_id')
    if not _is_int(enroll) or not _INT_MIN <= enroll <= _INT_MAX:
        raise Malformed('enroll_no')
    mode = row.get('in_out_mode', 0)
    raw_time = row.get('check_time')
    if raw_time is not None and not isinstance(raw_time, str):
        raise Malformed('check_time')
    check_time = _moment(raw_time)
    if check_time is None:
        return None
    return {
        'lg_check_id': check_id, 'enroll_no': enroll,
        'in_out_mode': _opt_int(mode) if mode is not None else 0,
        'check_time': check_time,
        'lg_device_id': _opt_int(row.get('lg_device_id')),
        'created_by_lg': _opt_int(row.get('created_by')),
        'edit_by_lg': _opt_int(row.get('edit_by')),
        'edit_on_lg': _moment(row.get('edit_on')),
    }


def _same(current, clean) -> bool:
    return (current.check_time == clean['check_time'] and current.enroll_no == clean['enroll_no']
            and current.lg_device_id == clean['lg_device_id']
            and current.in_out_mode == clean['in_out_mode'])


def _clean_window(window):
    """A re-read says which slice of the source it covers: ids above from_id (exclusive) up to
    to_id (inclusive; None = no upper bound, the final batch) and check times from `since`."""
    if not isinstance(window, dict):
        raise Malformed('window')
    from_id, to_id = window.get('from_id'), window.get('to_id')
    if not _is_int(from_id) or from_id < 0 or not (to_id is None or (_is_int(to_id) and to_id >= from_id)):
        raise Malformed('window')
    since = _moment(window.get('since'))
    if since is None:
        raise Malformed('window')
    return from_id, to_id, since


def store_lg_punches(rows, reread, today=None, window=None) -> dict:
    """Store a batch, all or nothing. A re-read must carry its window (see _clean_window)."""
    today = today or timezone.localdate()
    bounds = _clean_window(window) if reread else None
    batch, skipped = {}, 0
    for row in rows:
        clean = _clean_row(row)
        if clean is None:
            skipped += 1
            continue
        batch[clean['lg_check_id']] = clean          # a repeated id inside one batch: the last wins
    counts = {'new': 0, 'versioned': 0, 'unchanged': 0, 'removed': 0, 'skipped': skipped}
    with transaction.atomic():
        ids = list(batch)
        current = {p.lg_check_id: p for p in
                   LinkedGatesPunch.objects.filter(lg_check_id__in=ids, superseded_at__isnull=True)}
        latest = {}
        for check_id, version in (LinkedGatesPunch.objects.filter(lg_check_id__in=ids)
                                  .order_by('lg_check_id', 'version').values_list('lg_check_id', 'version')):
            latest[check_id] = version
        new_rows, supersede, revive = [], [], []
        for check_id, clean in batch.items():
            cur = current.get(check_id)
            if cur is not None and _same(cur, clean):
                counts['unchanged'] += 1
                if cur.lg_removed:
                    revive.append(cur.pk)        # it is back at the source
                continue
            if cur is not None:
                supersede.append(cur.pk)
                counts['versioned'] += 1
            else:
                counts['new'] += 1
            bad = is_bad_date(timezone.localtime(clean['check_time']).date(), today)
            new_rows.append(LinkedGatesPunch(
                version=latest.get(check_id, 0) + 1, flag=FLAG_BAD_DATE if bad else '', **clean))
        # Only bookkeeping fields are ever bulk-updated; the model guard covers the rest.
        if supersede:
            LinkedGatesPunch.objects.filter(pk__in=supersede).update(superseded_at=timezone.now())
        if revive:
            LinkedGatesPunch.objects.filter(pk__in=revive).update(lg_removed=False)
        LinkedGatesPunch.objects.bulk_create(new_rows)
        if bounds is not None:
            from_id, to_id, since = bounds
            gone = (LinkedGatesPunch.objects
                    .filter(superseded_at__isnull=True, lg_removed=False,
                            lg_check_id__gt=from_id, check_time__gte=since)
                    .exclude(lg_check_id__in=ids))
            if to_id is not None:
                gone = gone.filter(lg_check_id__lte=to_id)
            counts['removed'] = gone.update(lg_removed=True)
    # The employee link is derived: the shared resolver (employment dates included) sets it.
    ingest_module._resolve_all({str(c['enroll_no']) for c in batch.values()})
    return counts


def _text(value, limit) -> str:
    return value[:limit] if is_storable_text(value) else ''


def store_lg_reference(body) -> dict:
    """Upsert the portal's machines and employees. A machine is tied to ours by IP only when
    exactly one Linked Gates machine has that IP (and one of ours); an existing tie is kept."""
    devices = body.get('devices', [])
    employees = body.get('employees', [])
    departments = body.get('departments', [])
    if not all(isinstance(x, list) for x in (devices, employees, departments)):
        raise Malformed('reference')
    dept_names = {}
    for dept in departments:
        if isinstance(dept, dict) and _is_int(dept.get('department_id')):
            dept_names[dept['department_id']] = _text(dept.get('name'), 120)
    with transaction.atomic():
        for dev in devices:
            if not isinstance(dev, dict) or not _is_int(dev.get('lg_device_id')):
                raise Malformed('device')
            LinkedGatesDevice.objects.update_or_create(
                lg_device_id=dev['lg_device_id'],
                defaults={'name': _text(dev.get('name'), 120), 'ip': _text(dev.get('ip'), 64),
                          'lg_status': bool(dev.get('status', True))})
        for emp in employees:
            if not isinstance(emp, dict) or not _is_int(emp.get('lg_employee_id')):
                raise Malformed('employee')
            dept_id = emp.get('department_id') if _is_int(emp.get('department_id')) else None
            LinkedGatesEmployee.objects.update_or_create(
                lg_employee_id=emp['lg_employee_id'],
                defaults={'enroll_no': _opt_int(emp.get('enroll_no')) or 0,
                          'hr_code': _text(emp.get('hr_code'), 30),
                          'first_name': _text(emp.get('first_name'), 120),
                          'last_name': _text(emp.get('last_name'), 120),
                          'lg_department_id': dept_id, 'department_name': dept_names.get(dept_id, ''),
                          'shift_type': _opt_int(emp.get('shift_type')),
                          'is_manager': bool(emp.get('is_manager', False)),
                          'lg_status': bool(emp.get('status', True))})
        mapped = _automap()
    return {'devices': len(devices), 'employees': len(employees), 'mapped': mapped}


def _automap() -> int:
    mapped = 0
    ips = {}
    for lg in LinkedGatesDevice.objects.exclude(ip=''):
        ips.setdefault(lg.ip, []).append(lg)
    for ip, group in ips.items():
        if len(group) != 1 or group[0].device_id is not None:
            continue
        ours = list(AttendanceDevice.objects.filter(ip=ip)[:2])
        if len(ours) == 1:
            LinkedGatesDevice.objects.filter(pk=group[0].pk).update(device=ours[0])
            mapped += 1
    return mapped
