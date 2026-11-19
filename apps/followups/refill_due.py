"""
apps/followups/refill_due.py — who is due (or overdue) for a refill, from their own buying behaviour
(Top-10 C08 / backlog P-46). Feeds the «💊 موعد إعادة الصرف» call-list criterion; nothing is sent.

Deterministic rule (no AI, no catalog "chronic" label — it matches only 80 of 4,539 pairs):
  1. Synced SOFTECH sales (PurchaseHistory doc 115) of the last WINDOW_DAYS, named customers only
     (not walk-in / account placeholders, not guests), in the sales channels CHANNELS.
  2. Per (customer, item): buying episodes = distinct sale dates, buys within 7 days merged
     (services._episodes — the same rule the chronic-profile inference uses).
  3. Regular = at least MIN_PURCHASES episodes. Usual interval = MEDIAN of the gaps between the last
     LAST_N episodes, kept only when it is within [MIN_INTERVAL, MAX_INTERVAL] days.
  4. Due date = last episode + interval. Listed when today >= due date + OVERDUE_DAYS_MIN − DUE_AHEAD_DAYS
     and the last episode is at most MAX_LAPSE_DAYS ago (longer = probably gone / therapy changed).
  5. Expected value of the call = Σ over the customer's due items of their average spend per episode.
     Ranked by expected value, then most overdue, then customer id (stable).

Settings (getattr defaults): FOLLOWUPS_REFILL_DUE_<NAME>. Owner questions (PR body): MIN_PURCHASES / WINDOW_DAYS
(= "regular"), OVERDUE_DAYS_MIN, CHANNELS, CONSENT ('opt_in' = a recorded yes to refill calls;
'not_withdrawn' = everyone who has not said no, as outbound call lists do today).
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal
from statistics import median

from django.conf import settings
from django.utils import timezone

DEFAULTS = {
    'WINDOW_DAYS': 365, 'MIN_PURCHASES': 3, 'LAST_N': 6, 'MIN_INTERVAL': 7, 'MAX_INTERVAL': 120,
    'OVERDUE_DAYS_MIN': 0, 'DUE_AHEAD_DAYS': 3, 'MAX_LAPSE_DAYS': 180, 'CHANNELS': '91,90',
    'CONSENT': 'opt_in', 'RECALL_GAP_DAYS': 30,
}
MERGE_DAYS = 7
CONSENT_MODES = ('opt_in', 'not_withdrawn')


def cfg(name):
    return getattr(settings, f'FOLLOWUPS_REFILL_DUE_{name}', DEFAULTS[name])


def channels() -> tuple:
    raw = cfg('CHANNELS')
    if isinstance(raw, (list, tuple)):
        return tuple(str(c).strip() for c in raw if str(c).strip())
    return tuple(c.strip() for c in str(raw).split(',') if c.strip())


# ── the interval rule (pure) ─────────────────────────────────────────────────
def usual_interval(dates, *, min_purchases=None, last_n=None, min_interval=None, max_interval=None):
    """Sale dates of one (customer, item) → (interval_days, episodes) or (None, episodes) when not regular."""
    from .services import _episodes
    min_purchases = int(min_purchases if min_purchases is not None else cfg('MIN_PURCHASES'))
    last_n = int(last_n if last_n is not None else cfg('LAST_N'))
    lo = int(min_interval if min_interval is not None else cfg('MIN_INTERVAL'))
    hi = int(max_interval if max_interval is not None else cfg('MAX_INTERVAL'))
    eps = _episodes(dates, merge_days=MERGE_DAYS)
    if len(eps) < max(min_purchases, 2):
        return None, eps
    tail = eps[-max(last_n, 2):]
    gaps = [(b - a).days for a, b in zip(tail, tail[1:])]
    interval = int(round(median(gaps)))
    if interval < lo or interval > hi:
        return None, eps
    return interval, eps


def due_state(last, interval, today, *, overdue_min=None, ahead=None, max_lapse=None):
    """(listed: bool, due_date, days_overdue). days_overdue < 0 = due in that many days."""
    overdue_min = int(overdue_min if overdue_min is not None else cfg('OVERDUE_DAYS_MIN'))
    ahead = int(ahead if ahead is not None else cfg('DUE_AHEAD_DAYS'))
    max_lapse = int(max_lapse if max_lapse is not None else cfg('MAX_LAPSE_DAYS'))
    due = last + dt.timedelta(days=interval)
    overdue = (today - due).days
    listed = overdue >= overdue_min - ahead and (today - last).days <= max_lapse
    return listed, due, overdue


# ── the list ─────────────────────────────────────────────────────────────────
def _sales(customer_ids, since):
    """[(customer_id, item_id, sale_date, line_total)] — synced SOFTECH sales, named customers, our channels."""
    from apps.customers.models import PurchaseHistoryLine
    qs = (PurchaseHistoryLine.objects
          .filter(purchase__doc_code='115', purchase__invoice_date__gte=since, item__isnull=False,
                  purchase__customer__is_account_placeholder=False, purchase__customer__is_guest=False,
                  purchase__sales_channel__in=channels()))
    if customer_ids is not None:
        qs = qs.filter(purchase__customer_id__in=customer_ids)
    for cid, iid, when, total in qs.values_list('purchase__customer_id', 'item_id',
                                                 'purchase__invoice_date', 'line_total').iterator(chunk_size=5000):
        if when is not None:
            yield cid, iid, timezone.localtime(when).date(), total or Decimal('0')


CACHE_SECONDS = 300


def due_customers_cached(today=None) -> dict:
    """due_customers() for everyone, cached a few minutes (the scan takes seconds; the call-list form
    re-previews on every change). The key carries the day, the newest sale line and the rule settings,
    so a new sale or a settings change is never served stale."""
    from django.core.cache import cache
    from django.db.models import Max
    from apps.customers.models import PurchaseHistoryLine
    today = today or timezone.localdate()
    newest = PurchaseHistoryLine.objects.aggregate(m=Max('pk'))['m']
    key = 'followups:refill_due:' + ':'.join(
        str(x) for x in (today, newest, *(cfg(n) for n in sorted(DEFAULTS) if n not in ('CONSENT', 'RECALL_GAP_DAYS'))))
    hit = cache.get(key)
    if hit is None:
        hit = due_customers(today=today)
        cache.set(key, hit, CACHE_SECONDS)
    return hit


def due_customers(customer_ids=None, today=None) -> dict:
    """{customer_id: {'value', 'max_overdue', 'items': [ {item_id, interval, last, due, overdue, value, episodes} ]}}
    for every customer with at least one listed (due / overdue) regular item. `customer_ids` narrows the
    scan (the call-list candidates); None = all."""
    today = today or timezone.localdate()
    since = timezone.now() - dt.timedelta(days=int(cfg('WINDOW_DAYS')))
    dates, spend = defaultdict(list), defaultdict(Decimal)
    for cid, iid, d, total in _sales(customer_ids, since):
        dates[(cid, iid)].append(d)
        spend[(cid, iid)] += total
    out = {}
    for (cid, iid), ds in dates.items():
        interval, eps = usual_interval(ds)
        if interval is None:
            continue
        listed, due, overdue = due_state(eps[-1], interval, today)
        if not listed:
            continue
        value = (spend[(cid, iid)] / len(eps)).quantize(Decimal('0.01'))
        row = out.setdefault(cid, {'value': Decimal('0'), 'max_overdue': overdue, 'items': []})
        row['items'].append({'item_id': iid, 'interval': interval, 'last': eps[-1], 'due': due,
                             'overdue': overdue, 'value': value, 'episodes': len(eps)})
        row['value'] += value
        row['max_overdue'] = max(row['max_overdue'], overdue)
    for row in out.values():
        row['items'].sort(key=lambda r: (-r['value'], -r['overdue'], r['item_id']))
    return out


def rank(due: dict) -> list:
    """Customer ids, highest expected value first; ties → most overdue, then id."""
    return sorted(due, key=lambda cid: (-due[cid]['value'], -due[cid]['max_overdue'], cid))


def consent_filter(qs):
    """Narrow a Customer queryset to who may get a refill call (account state always; consent by mode)."""
    from apps.customers import account_state, consent
    mode = cfg('CONSENT')
    if mode not in CONSENT_MODES:
        raise ValueError(f'FOLLOWUPS_REFILL_DUE_CONSENT must be one of {CONSENT_MODES}')
    if mode == 'opt_in':
        return consent.filter_allowed(qs, consent.REFILL, 'call')
    return consent.exclude_withdrawn(qs, consent.REFILL, 'call').filter(account_state.outreach_q())


def recently_called_ids(today=None):
    """Customers already put on a refill-due call list in the last RECALL_GAP_DAYS (one call a month, P-46)."""
    from .models import FollowUpTask
    today = today or timezone.localdate()
    since = today - dt.timedelta(days=int(cfg('RECALL_GAP_DAYS')))
    return (FollowUpTask.objects.filter(call_list__criteria__refill_due=True, created_at__date__gte=since,
                                        customer__isnull=False)
            .values('customer_id'))


def task_note(row, item_names) -> str:
    parts = []
    for it in row['items'][:5]:
        late = f'متأخر {it["overdue"]} يوم' if it['overdue'] > 0 else (
            'مستحق اليوم' if it['overdue'] == 0 else f'مستحق بعد {-it["overdue"]} يوم')
        parts.append(f'{item_names.get(it["item_id"], it["item_id"])}: كل ~{it["interval"]} يوم، '
                     f'آخر شراء {it["last"]} — {late}')
    more = len(row['items']) - 5
    if more > 0:
        parts.append(f'+ {more} صنف آخر')
    return 'موعد إعادة صرف (من سلوك الشراء): ' + ' · '.join(parts)
