"""
Call-count from Issabel CDR  (doc 16, Phase 5)
==============================================
Decoded + validated (2026-07-29) against the owner's Call-Center-KPIs workbook:

  outgoing answered calls to customers, counted as UNIQUE customers reached per day:
    • disposition == 'ANSWERED'
    • src ∈ call-center agent extensions (e.g. 10, 12, 15)
    • dst → an 11-digit Egyptian mobile: strip the 2-digit GoIP prefix
      (dst like '8201063650014' → last 11 digits '01063650014', must start with '01')
    • metric = Σ over days of (distinct mobiles reached that day)   ← per-day distinct

Same logic feeds both the CSV importer and the live MySQL connector, so the number
matches whether pulled from an export or the DB. May-2026 CSV → 1,905 (sheet ≈ 1,887).
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


def count_calls(rows, extensions, *, per_day_distinct=True):
    """
    rows: iterable of dicts with at least src/dst/disposition/calldate.
    extensions: iterable of agent phone extensions (strings).
    Returns int call-count (unique customers reached), per-day-distinct summed.
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


def count_calls_from_csv(path, extensions, *, per_day_distinct=True):
    """Parse an Issabel CDR CSV export and return the call-count."""
    import csv
    with open(path, encoding='utf-8', errors='replace', newline='') as f:
        rows = list(csv.DictReader(f))
    return count_calls(rows, extensions, per_day_distinct=per_day_distinct)
