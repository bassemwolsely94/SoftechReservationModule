"""
apps/batches/return_window.py

P-29: the supplier return window — one pure function, no DB access. P-28 (near-expiry worklist)
imports it; nothing else re-implements the rule.

    window_for(date(2026, 12, 15), today)  →  opens 2026-10-01, closes 2027-01-31, state …

opens  = first day of (expiry month + open_offset)   default −2
closes = last day of (expiry month + close_offset)   default +1
"""
import calendar
import datetime as dt

DEFAULT_OPEN_OFFSET = -2
DEFAULT_CLOSE_OFFSET = 1

STATE_LABELS = {
    'opens_next_month':  'تفتح الشهر القادم',
    'open':              'داخل النافذة',
    'closes_this_month': 'تُغلق هذا الشهر',
    'missed':            'فاتت النافذة',
    'later':             '',
}
SHOWN_STATES = ('opens_next_month', 'open', 'closes_this_month', 'missed')


def _shift(year, month, offset):
    n = year * 12 + (month - 1) + offset
    return n // 12, n % 12 + 1


def window_for(expiry_date, today, open_offset=DEFAULT_OPEN_OFFSET, close_offset=DEFAULT_CLOSE_OFFSET):
    oy, om = _shift(expiry_date.year, expiry_date.month, open_offset)
    cy, cm = _shift(expiry_date.year, expiry_date.month, close_offset)
    opens = dt.date(oy, om, 1)
    closes = dt.date(cy, cm, calendar.monthrange(cy, cm)[1])
    ny, nm = _shift(today.year, today.month, 1)
    if closes < today:
        state = 'missed'
    elif opens > today:
        state = 'opens_next_month' if (opens.year, opens.month) == (ny, nm) else 'later'
    elif (closes.year, closes.month) == (today.year, today.month):
        state = 'closes_this_month'
    else:
        state = 'open'
    return {'opens': opens, 'closes': closes, 'state': state}
