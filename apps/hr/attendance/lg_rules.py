"""Linked Gates' own day rules, recomputed by us from the copied punches (design 2026-11-20 §2, §5.4).

Pure functions, no ORM. This reproduces Linked Gates' SQL views exactly, including their known
losses, so HR can see during the trial why its figures differ from ours. Nothing here decides pay.

``mod`` below is the minute of the day (hour * 60 + minute; seconds ignored), on Cairo local time.

- CheckIn: per (calendar date, device, in/out mode) the earliest punch with
  type 1: 420 <= mod <= 840 (07:00-14:00), type 2: 480 <= mod <= 1260 (08:00-21:00).
- CheckOut: per (calendar date, device) the latest punch with type 1: mod > 840, type 2: mod > 1260,
  or any type: 0 < mod < 120. If that latest punch itself has 0 < mod < 120 it is the previous
  date's out; otherwise it stays on its date. (So a later punch that same date hides it.)
- A person with no shift type (or any value other than 1 or 2) gets no days at all.

Linked Gates lists one row per in-group, so a day may carry several ``in_times``. Where several
out-groups land on one date we keep the latest as ``out_time``.
"""
import datetime
from dataclasses import dataclass, field
from typing import Optional

from django.utils import timezone

IN_WINDOWS = {1: (420, 840), 2: (480, 1260)}
OUT_AFTER = {1: 840, 2: 1260}
AFTER_MIDNIGHT = (0, 120)          # exclusive both ends: 00:01-01:59
MATCH_SECONDS = 120

REASON_CODES = ('lg_night_split', 'lg_window_ignored', 'lg_out_hidden', 'lg_no_shifttype',
                'lg_multi_in', 'missing_punch')


@dataclass
class LgDay:
    work_date: datetime.date
    in_times: list = field(default_factory=list)
    out_time: Optional[datetime.datetime] = None

    @property
    def first_in(self) -> Optional[datetime.datetime]:
        return min(self.in_times) if self.in_times else None

    @property
    def minutes(self) -> int:
        """Linked Gates' worked time: its out minus its (earliest) in, when it has both."""
        if not self.in_times or self.out_time is None:
            return 0
        return max(0, int((self.out_time - self.first_in).total_seconds() // 60))


def local_naive(value: datetime.datetime) -> datetime.datetime:
    """An aware time as naive Cairo local time; a naive one is already local."""
    if timezone.is_aware(value):
        return timezone.localtime(value, timezone.get_current_timezone()).replace(tzinfo=None)
    return value


def mod(value: datetime.datetime) -> int:
    return value.hour * 60 + value.minute


def _is_in(m: int, shift_type) -> bool:
    lo, hi = IN_WINDOWS[shift_type]
    return lo <= m <= hi


def _after_midnight(m: int) -> bool:
    return AFTER_MIDNIGHT[0] < m < AFTER_MIDNIGHT[1]


def _is_out(m: int, shift_type) -> bool:
    return m > OUT_AFTER[shift_type] or _after_midnight(m)


def in_any_window(value: datetime.datetime, shift_type) -> bool:
    """True when Linked Gates uses the punch at all (as an in, an out or an after-midnight out)."""
    if shift_type not in IN_WINDOWS:
        return False
    m = mod(value)
    return _is_in(m, shift_type) or _is_out(m, shift_type)


def lg_days(punches, shift_type) -> dict:
    """{work date: LgDay} from LinkedGatesPunch-like objects (check_time, lg_device_id, in_out_mode)."""
    if shift_type not in IN_WINDOWS:
        return {}
    ins: dict = {}       # (date, mode, device) -> earliest in
    outs: dict = {}      # (date, device) -> latest out candidate
    for p in punches:
        at = local_naive(p.check_time)
        m = mod(at)
        if _is_in(m, shift_type):
            key = (at.date(), getattr(p, 'in_out_mode', 0), p.lg_device_id)
            if key not in ins or at < ins[key]:
                ins[key] = at
        if _is_out(m, shift_type):
            key = (at.date(), p.lg_device_id)
            if key not in outs or at > outs[key]:
                outs[key] = at

    result: dict = {}

    def day(d):
        if d not in result:
            result[d] = LgDay(work_date=d)
        return result[d]

    for (d, _mode, _device), at in ins.items():
        day(d).in_times.append(at)
    for (d, _device), at in outs.items():
        work_date = d - datetime.timedelta(days=1) if _after_midnight(mod(at)) else d
        row = day(work_date)
        if row.out_time is None or at > row.out_time:
            row.out_time = at
    for row in result.values():
        row.in_times.sort()
    return result


def near(a, b) -> bool:
    return a is not None and b is not None and abs((a - b).total_seconds()) <= MATCH_SECONDS


def same_day(our, lg) -> bool:
    """Our figures and Linked Gates' agree: one in, same in and out (within 2 minutes each) and the
    same worked time (within the two 2-minute tolerances)."""
    if lg is None:
        return our.punch_count == 0
    if len(lg.in_times) > 1:
        return False
    if (our.first_in is None) != (lg.first_in is None) or (our.last_out is None) != (lg.out_time is None):
        return False
    if our.first_in is not None and not near(our.first_in, lg.first_in):
        return False
    if our.last_out is not None and not near(our.last_out, lg.out_time):
        return False
    return abs(our.worked_minutes - lg.minutes) <= 4


def reason_codes(our, lg, punches, shift_type) -> list:
    """Why Linked Gates' day differs from ours. ``our`` is our DayRow for the date, ``lg`` Linked Gates'
    recomputed LgDay (or None), ``punches`` the merged Stamps involved: our day's plus those Linked
    Gates used for this date. A day may carry several codes; an empty list means unexplained."""
    if shift_type not in IN_WINDOWS:
        return ['lg_no_shifttype']
    codes = []
    ours_at = {r['at'] for r in our.raw}

    if any(st.at not in ours_at for st in punches):
        codes.append('lg_night_split')          # a stamp Linked Gates uses here is on another of our dates
    elif our.first_in is not None and our.first_in.date() > our.work_date:
        codes.append('lg_night_split')          # our session started after midnight
    if our.last_out is not None and our.last_out.date() > our.work_date:
        if _after_midnight(mod(our.last_out)):
            if lg is None or not near(lg.out_time, our.last_out):
                codes.append('lg_out_hidden')
        elif 'lg_night_split' not in codes:
            codes.append('lg_night_split')

    if any('lg' in st.sources and not in_any_window(st.at, shift_type) for st in punches):
        codes.append('lg_window_ignored')
    if lg is not None and len(lg.in_times) > 1:
        codes.append('lg_multi_in')
    if our.needs_review or any('lg' not in st.sources for st in punches):
        codes.append('missing_punch')
    return codes
