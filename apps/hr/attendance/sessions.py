"""Work sessions: group an employee's stamps into shifts without a fixed day cut-off.

Pure functions, no ORM. A stamp is one de-duplicated time clock event from any source (a fingerprint
machine, or Linked Gates). Rules (design 2026-11-20 §5.3):

- Stamps within 120 s of each other are one stamp (sources united, earliest time kept).
- Pair-aware split: an open "in" is closed by the next stamp within ``max_shift_hours``, else it stays
  unpaired; after a closed pair a gap over ``gap_hours`` starts a new session.
- A session belongs to the date of its first stamp, except a first stamp between 00:00 and 03:59,
  which belongs to the previous date (a late shift's start punch after midnight).
- Worked time = the sum of consecutive pairs (1st-2nd, 3rd-4th, ...). An odd count needs review and
  the last unpaired stamp adds nothing. A single pair longer than ``long_pair_hours`` (default 12)
  also needs review: most likely a missed punch paired two unrelated stamps.
"""
import datetime
from dataclasses import dataclass
from typing import NamedTuple, Optional

from apps.hr.attendance.days import DUPLICATE_WINDOW_SECONDS

EARLY_MORNING_END = datetime.time(4, 0)


class Stamp(NamedTuple):
    at: datetime.datetime
    machine: str
    sources: frozenset          # 'machine' and / or 'lg'


@dataclass
class Session:
    work_date: datetime.date
    stamps: list
    first_in: datetime.datetime
    last_out: Optional[datetime.datetime]
    worked_minutes: int
    needs_review: bool


def merge_stamps(stamps) -> list:
    """Sort, then fold stamps within 120 s of the first of their cluster into one."""
    merged: list = []
    anchor = None
    for s in sorted(stamps, key=lambda s: s.at):
        if merged and (s.at - anchor).total_seconds() <= DUPLICATE_WINDOW_SECONDS:
            kept = merged[-1]
            merged[-1] = kept._replace(sources=kept.sources | s.sources)
            continue
        merged.append(s)
        anchor = s.at
    return merged


def _session(stamps, long_pair) -> Session:
    first = stamps[0].at
    work_date = first.date()
    if first.time() < EARLY_MORNING_END:
        work_date -= datetime.timedelta(days=1)
    pairs = [stamps[i + 1].at - stamps[i].at for i in range(0, len(stamps) - 1, 2)]
    worked = sum(int(p.total_seconds() // 60) for p in pairs)
    return Session(work_date=work_date, stamps=stamps, first_in=first,
                   last_out=stamps[-1].at if len(stamps) > 1 else None,
                   worked_minutes=worked,
                   needs_review=len(stamps) % 2 == 1 or any(p > long_pair for p in pairs))


def build_sessions(stamps, gap_hours: int = 6, max_shift_hours: int = 16,
                   long_pair_hours: int = 12) -> list:
    """Pair-aware grouping. With an open "in" (odd count) the next stamp closes it if it is within
    ``max_shift_hours``; otherwise the "in" stays unpaired and the next stamp starts a new session.
    With the session closed (even count) a gap over ``gap_hours`` starts a new session; a shorter one
    continues it as a new "in". A pair longer than ``long_pair_hours`` marks its session for review."""
    merged = merge_stamps(stamps)
    gap = datetime.timedelta(hours=gap_hours)
    longest = datetime.timedelta(hours=max_shift_hours)
    groups: list = []
    for s in merged:
        if groups:
            delta = s.at - groups[-1][-1].at
            is_open = len(groups[-1]) % 2 == 1
            if (is_open and delta <= longest) or (not is_open and delta <= gap):
                groups[-1].append(s)
                continue
        groups.append([s])
    long_pair = datetime.timedelta(hours=long_pair_hours)
    return [_session(g, long_pair) for g in groups]
