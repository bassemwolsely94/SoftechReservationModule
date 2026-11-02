"""
apps/pic_analytics/queries/frequency.py — A/B/C frequency of PICs as of the report's to-date (doc 33 §4/§10).

Over the 12 calendar months ending at `end`, chain-wide. When `end` is yesterday (Cairo) the nightly
PicRollup already holds exactly that; for any other to-date it is computed from PicDayFact sale days
(invoices > 0, day <= end) through `rules`, so the figures follow the report, not the last build.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Max
from django.utils import timezone

from apps.pic_analytics import rules
from apps.pic_analytics.build import _window_start
from apps.pic_analytics.models import PicDayFact, PicRollup


def _is_yesterday(end):
    return end == timezone.localdate() - timedelta(days=1)


def _computed(pics, end):
    """{pic: {...}} from PicDayFact; `pics` None = every PIC with a sale day <= end."""
    base = PicDayFact.objects.filter(invoices__gt=0, day__lte=end).exclude(pic='')
    if pics is not None:
        base = base.filter(pic__in=pics)
    days = defaultdict(set)
    for pic, day in base.filter(day__gte=_window_start(end)).values_list('pic', 'day').distinct():
        days[pic].add(day)
    out = {}
    for r in base.values('pic').annotate(last=Max('day')):
        win = sorted(days.get(r['pic'], ()))
        cyc = rules.cycle_days(win)
        out[r['pic']] = {'months_a': rules.months_bought(win, end), 'streak_b': rules.longest_streak(win, end),
                         'cycle_days': cyc, 'cycle_bucket': rules.cycle_bucket(cyc), 'last_visit': r['last']}
    return out


def _from_rollup(qs):
    return {r.pic: {'months_a': r.months_a, 'streak_b': r.streak_b,
                    'cycle_days': None if r.cycle_days is None else float(r.cycle_days),
                    'cycle_bucket': r.cycle_bucket, 'last_visit': r.last_purchase} for r in qs}


def pic_frequency(pics, end) -> dict:
    """Per PIC {'months_a','streak_b','cycle_days','cycle_bucket','last_visit'} as of `end`."""
    pics = set(pics)
    if _is_yesterday(end):
        return _from_rollup(PicRollup.objects.filter(pic__in=pics))
    return _computed(pics, end)


def pics_in_bucket(bucket, end):
    """PICs whose cycle bucket at `end` is `bucket` — a queryset (rollup) or a list (computed)."""
    if _is_yesterday(end):
        return PicRollup.objects.filter(cycle_bucket=bucket).values('pic')
    return [p for p, v in _computed(None, end).items() if v['cycle_bucket'] == bucket]
