"""
Call-count from Issabel CDR  (doc 16, Phase 5)
==============================================
Decoded + validated against the owner's Call-Center-KPIs workbook (CDR Report sheet,
re-verified 2026-10-08 vs 7 complete months Feb–Aug 2026 — EXACT match):

  outgoing answered calls, counted as UNIQUE customers reached in the MONTH:
    • disposition == 'ANSWERED'
    • src ∈ call-center agent extensions (e.g. 10, 12, 15)
    • dst → an 11-digit Egyptian mobile: strip the 2-digit GoIP prefix
      (dst like '8201063650014' → last 11 digits '01063650014', must start with '01')
    • metric = COUNT(DISTINCT mobile) over the whole month   ← whole-month distinct

This is the owner's pivot "Grand Total" (a distinct-count grand total dedupes across
the whole column, NOT the sum of the per-day/per-extension cells). Our per-(day,ext)
distinct reproduces the sheet's visible cells exactly, and the whole-month distinct
reproduces its Grand Total exactly (Feb 677 / May 1,851 / Jul 1,849 / Aug 1,961 …).
Same logic feeds the CSV importer and the live MySQL connector. Pass per_day_distinct=
True only for the (larger) sum-of-per-day-distinct variant.
"""
import re

CDR_COLUMNS = ['calldate', 'clid', 'src', 'dst', 'dcontext', 'channel', 'dstchannel',
               'lastapp', 'lastdata', 'duration', 'billsec', 'disposition', 'amaflags',
               'accountcode', 'uniqueid', 'userfield']


def extract_mobile(dst: str):
    """Return the 11-digit Egyptian mobile ('01xxxxxxxxx') from a dst, else None.
    GoIP prepends a 2-digit prefix (81/82/83…) → take the last 11 digits."""
    digits = re.sub(r'\D', '', dst or '')
    if len(digits) < 11:
        return None
    tail = digits[-11:]
    return tail if tail.startswith('01') else None


def count_calls(rows, extensions, *, per_day_distinct=False):
    """
    rows: iterable of dicts with at least src/dst/disposition/calldate.
    extensions: iterable of agent phone extensions (strings).
    Default (per_day_distinct=False) = whole-month distinct unique mobiles — matches the
    owner's CDR-Report Grand Total exactly. per_day_distinct=True = Σ per-day distinct.
    """
    ext = {str(e) for e in extensions}
    if per_day_distinct:
        from collections import defaultdict
        by_day = defaultdict(set)
        for r in rows:
            if r.get('disposition') != 'ANSWERED' or str(r.get('src')) not in ext:
                continue
            mob = extract_mobile(r.get('dst'))
            if mob:
                by_day[str(r.get('calldate'))[:10]].add(mob)
        return sum(len(v) for v in by_day.values())
    # global distinct
    seen = set()
    for r in rows:
        if r.get('disposition') != 'ANSWERED' or str(r.get('src')) not in ext:
            continue
        mob = extract_mobile(r.get('dst'))
        if mob:
            seen.add(mob)
    return len(seen)


def count_calls_from_csv(path, extensions, *, per_day_distinct=False):
    """Parse an Issabel CDR CSV export and return the call-count (whole-month distinct)."""
    import csv
    with open(path, encoding='utf-8', errors='replace', newline='') as f:
        rows = list(csv.DictReader(f))
    return count_calls(rows, extensions, per_day_distinct=per_day_distinct)
