"""
apps/branches/hours.py — branch working hours (BranchSettings.is_24h / working_hours).

working_hours is a list of windows, local Cairo time, the same every day:

    [{"from": "08:00", "to": "01:00"}]                                   # closes after midnight
    [{"from": "08:00", "to": "21:00", "label": "المخزن"},
     {"from": "09:00", "to": "24:00", "label": "الكول سنتر",
      "doccodes": ["115", "30", "80", "180", "181", "81"]}]             # a window for some documents only

A window without `doccodes` applies to every document; `to` earlier than `from` crosses midnight;
"24:00" means midnight. Used by the stock audit's after-hours check (doc 32, check 9).
"""
import re

_HHMM = re.compile(r'^(\d{2}):(\d{2})$')
DAY = 1440


class HoursError(ValueError):
    pass


def _minutes(v, allow_24=False):
    m = _HHMM.match(str(v or ''))
    if not m:
        raise HoursError(f'وقت غير صحيح «{v}» — use HH:MM')
    h, mi = int(m.group(1)), int(m.group(2))
    if mi > 59 or h > 24 or (h == 24 and (mi or not allow_24)):
        raise HoursError(f'وقت غير صحيح «{v}»')
    return h * 60 + mi


def validate_windows(windows):
    """Clean list of windows or HoursError."""
    if windows in (None, ''):
        return []
    if not isinstance(windows, list) or len(windows) > 10:
        raise HoursError('working_hours must be a list of up to 10 windows')
    out = []
    for w in windows:
        if not isinstance(w, dict) or set(w) - {'from', 'to', 'label', 'doccodes'}:
            raise HoursError('each window needs from / to (and optional label, doccodes)')
        start, end = _minutes(w.get('from')), _minutes(w.get('to'), allow_24=True)
        if start == end:
            raise HoursError('from and to must differ — use is_24h for a branch that never closes')
        clean = {'from': w['from'], 'to': w['to']}
        if w.get('label'):
            clean['label'] = str(w['label'])[:60]
        codes = w.get('doccodes') or []
        if not isinstance(codes, list) or not all(str(c).strip().isdigit() for c in codes):
            raise HoursError('doccodes must be a list of document codes')
        if codes:
            clean['doccodes'] = [str(c).strip() for c in codes]
        out.append(clean)
    return out


def _spans(window, grace):
    start = _minutes(window['from'])
    end = _minutes(window['to'], allow_24=True)
    if end <= start:
        end += DAY                                          # crosses midnight
    for shift in (-DAY, 0, DAY):
        yield start - grace + shift, end + grace + shift


def minutes_outside(windows, minute_of_day, doccode, grace=0):
    """0 when the time falls inside a window that applies to `doccode` (± grace); otherwise the
    distance in minutes to the nearest such window. None when no window applies to the document."""
    best = None
    for w in windows:
        codes = w.get('doccodes')
        if codes and doccode not in codes:
            continue
        for a, b in _spans(w, grace):
            d = 0 if a <= minute_of_day <= b else (a - minute_of_day if minute_of_day < a else minute_of_day - b)
            best = d if best is None else min(best, d)
    return best


def describe(windows):
    """'08:00–01:00' / '08:00–21:00 · 09:00–24:00 (الكول سنتر)' for messages."""
    return ' · '.join(f"{w['from']}–{w['to']}" + (f" ({w['label']})" if w.get('label') else '') for w in windows)
