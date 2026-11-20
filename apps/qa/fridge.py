"""
apps/qa/fridge.py — C31 (audit doc 08, P-53): the fridge temperature log EDA asks for on every visit.

Rules (deterministic, tested):
  * Two readings a day per active fridge: «صباحاً» (am, due by AM_DUE) and «مساءً» (pm, due by PM_DUE),
    Cairo time. One reading per fridge per slot (DB unique) — a reading is never edited or deleted
    through the API; a correction is a note on the next reading.
  * A reading may be entered for today, or for yesterday (late entry); its recorded_at keeps the real
    time and the month sheet marks it «متأخر».
  * Out of range = the current, min-seen or max-seen value outside the fridge's [min_c, max_c]
    (default 2–8 °C, an owner question). It raises an in-app alert to the branch at once.
  * Missed reading = no reading for a slot once its due time has passed. The scheduled check
    (`check_missed`, after each due time) alerts the branch once per fridge/day/slot (dedup_once).
Alerts are in-app only (no WhatsApp/SMS). Nothing fires until someone registers a fridge.
"""
import calendar
import datetime as dt
import logging

from django.utils import timezone

logger = logging.getLogger('elrezeiky.qa')

AM_DUE = dt.time(12, 0)    # owner question: when must the morning reading be in?
PM_DUE = dt.time(20, 0)    # owner question: when must the evening reading be in?
NOTIF_TYPE = 'qa_fridge_alert'


def slot_for(now=None):
    """The slot a reading taken now belongs to: before 14:00 → am, else pm (Cairo local time)."""
    local = timezone.localtime(now or timezone.now())
    return 'am' if local.time() < dt.time(14, 0) else 'pm'


def allowed_days(now=None):
    today = timezone.localdate(now or timezone.now())
    return (today - dt.timedelta(days=1), today)


def notify_out_of_range(reading):
    from apps.notifications.models import Notification
    f = reading.fridge
    title = f'🌡️ {f.name}: {reading.temp_c}°م خارج النطاق ({f.min_c}–{f.max_c})'
    body = (f'قراءة {reading.get_slot_display()} يوم {reading.day:%Y-%m-%d}: الحالية {reading.temp_c}، '
            f'أقل {reading.min_seen_c if reading.min_seen_c is not None else "—"}، '
            f'أعلى {reading.max_seen_c if reading.max_seen_c is not None else "—"}. '
            'افحص الثلاجة وانقل الأصناف لو لزم، واكتب الإجراء في ملاحظة القراءة الجاية.')
    try:
        Notification.send_to_branch(branch=f.branch, notification_type=NOTIF_TYPE, title=title, body=body,
                                    dedup_key=f'qa_fridge_oor_{reading.pk}', dedup_once=True)
    except Exception as exc:   # an alert failure must not lose the reading
        logger.warning('[fridge] out-of-range alert failed for reading %s: %s', reading.pk, exc)


def check_missed(now=None) -> int:
    """Alert the branch for every active fridge whose due slot today has no reading. Returns alerts sent
    (a re-run sends nothing new: dedup_once on fridge/day/slot)."""
    from apps.notifications.models import Notification
    from .models import FridgeReading, FridgeUnit

    local = timezone.localtime(now or timezone.now())
    today = local.date()
    due = [s for s, t in (('am', AM_DUE), ('pm', PM_DUE)) if local.time() >= t]
    if not due:
        return 0
    have = set(FridgeReading.objects.filter(day=today, slot__in=due).values_list('fridge_id', 'slot'))
    sent = 0
    for f in FridgeUnit.objects.filter(is_active=True).select_related('branch'):
        for s in due:
            if (f.pk, s) in have:
                continue
            label = 'الصباحية' if s == 'am' else 'المسائية'
            try:
                n = Notification.send_to_branch(
                    branch=f.branch, notification_type=NOTIF_TYPE,
                    title=f'🌡️ قراءة {label} لـ{f.name} لم تُسجَّل',
                    body=f'لا توجد قراءة {label} لثلاجة «{f.name}» اليوم {today:%Y-%m-%d}. سجّلها من «سجل الثلاجة».',
                    dedup_key=f'qa_fridge_missed_{f.pk}_{today:%Y%m%d}_{s}', dedup_once=True)
                sent += 1 if n else 0
            except Exception as exc:   # one branch's failure must not stop the others
                logger.warning('[fridge] missed alert failed for fridge %s: %s', f.pk, exc)
    return sent


def month_sheet(fridge, year: int, month: int, now=None) -> dict:
    """The printable month: one row per day with the am / pm readings, and the completeness figure
    (readings present ÷ slots already due). Future slots are not counted as missing."""
    from .models import FridgeReading

    local = timezone.localtime(now or timezone.now())
    days_in = calendar.monthrange(year, month)[1]
    first, last = dt.date(year, month, 1), dt.date(year, month, days_in)
    readings = {(r.day, r.slot): r for r in FridgeReading.objects.filter(
        fridge=fridge, day__gte=first, day__lte=last).select_related('recorded_by')}
    rows, due_slots, present = [], 0, 0
    for d in range(1, days_in + 1):
        day = dt.date(year, month, d)
        row = {'day': day.isoformat()}
        for s, t in (('am', AM_DUE), ('pm', PM_DUE)):
            r = readings.get((day, s))
            is_due = day < local.date() or (day == local.date() and local.time() >= t)
            if is_due:
                due_slots += 1
            if r is not None:
                present += 1 if is_due else 0
                row[s] = {
                    'id': r.id, 'temp_c': r.temp_c, 'min_seen_c': r.min_seen_c, 'max_seen_c': r.max_seen_c,
                    'initials': r.initials, 'note': r.note, 'out_of_range': r.out_of_range,
                    'late': timezone.localdate(r.recorded_at) != day,
                    'recorded_by': getattr(r.recorded_by, 'full_name', ''),
                }
            else:
                row[s] = {'missing': is_due}
        rows.append(row)
    return {
        'fridge': {'id': fridge.id, 'name': fridge.name, 'branch_id': fridge.branch_id,
                   'branch_name': getattr(fridge.branch, 'name_ar', '') or getattr(fridge.branch, 'name', ''),
                   'min_c': fridge.min_c, 'max_c': fridge.max_c},
        'month': f'{year:04d}-{month:02d}', 'rows': rows,
        'due_slots': due_slots, 'present': present,
        'completeness_pct': round(present / due_slots * 100, 1) if due_slots else None,
        'out_of_range': sum(1 for r in readings.values() if r.out_of_range),
    }
