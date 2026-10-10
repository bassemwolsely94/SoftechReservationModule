"""
apps/customers/account_state.py — what a customer's SOFTECH account state allows (B7, owner 2026-10-08).

The ONE place that turns the mirrored HQ flags (Customer.softech_status / softech_locked /
softech_deceased / points_enrolled, refreshed by sync_customers) into decisions. Deterministic.

  phcodestatus '0'  → file closed (blocked, e.g. a drug-addicted patient) → no sale, no reservation,
                      no reminder. SOFTECH's POS refuses it with the same message.
  phcodestatus '5' or picdied → deceased → same as closed.
  piclock = 1       → entity, not a person → may still buy, but no points / coupons / reminders.
  picpoints = 0     → removed from the points system → no points / coupons.
  '' or '1'         → active.
"""
CLOSED_MSG = 'غير مسموح بتنفيذ المطلوب لمريض داخلي تم غلق ملفه !'      # SOFTECH POS's own wording
DECEASED_MSG = 'العميل متوفى (مسجل في SOFTECH) — لا يمكن تنفيذ طلب على هذا الكود.'
NO_POINTS_MSG = 'العميل مستبعد من نظام النقاط — لا يحق له استخدام كوبونات الهدايا.'

MERGED_MSG = 'تم دمج هذا الكود في الكود {main} — استخدم الكود {main}.'

LABELS = {'active': 'نشط', 'closed': 'ملف مغلق', 'deceased': 'متوفى', 'entity': 'جهة (ليس شخصاً)'}


def state(c):
    """{code, label, blocked, points, reminders, message} for a Customer (None → active)."""
    if c is None:
        return {'code': 'active', 'label': LABELS['active'], 'blocked': False, 'points': True,
                'reminders': True, 'message': '', 'merged_into': ''}
    status = (c.softech_status or '').strip()
    merged = (getattr(c, 'merged_into_pic', '') or '').strip()
    if status == '0':
        code, msg = 'closed', (MERGED_MSG.format(main=merged) if merged else CLOSED_MSG)
    elif status == '5' or c.softech_deceased:
        code, msg = 'deceased', DECEASED_MSG
    elif c.softech_locked:
        code, msg = 'entity', ''
    else:
        code, msg = 'active', ''
    blocked = code in ('closed', 'deceased')
    points = code == 'active' and bool(c.points_enrolled)
    return {'code': code, 'label': LABELS[code], 'blocked': blocked, 'points': points,
            'reminders': code == 'active', 'message': msg,
            'points_enrolled': bool(c.points_enrolled), 'merged_into': merged}


def for_pic(pic):
    """state() for a SOFTECH PIC, or None when we do not mirror that code."""
    from .models import Customer
    pic = (pic or '').strip()
    if not pic:
        return None
    c = (Customer.objects.filter(softech_pic=pic)
         .only('softech_status', 'softech_locked', 'softech_deceased', 'points_enrolled', 'merged_into_pic').first())
    return state(c) if c else None
