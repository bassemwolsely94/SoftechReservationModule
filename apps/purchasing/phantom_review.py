"""
apps/purchasing/phantom_review.py

C30 (docs/full-project-audit/08_BUSINESS_OPTIMIZATION_OPPORTUNITIES.md §C30): the monthly review list of
phantom-substitution flags. Detection already exists (apps.purchasing.phantom, /phantom-sales); this only
lists the items that BECAME phantom in a month (Item.phantom_flagged_at) with their review state and the
EGP at stake, and sends one monthly digest of the previous month's new flags to the owner.

EGP = buy-back units in the detection window × current cost — the same «قيمة التخفيض» the screen shows.
Read-only: no stock reduction (that stays dormant behind PHANTOM_APPLY_REDUCTION), no SOFTECH read or
write. Company-level (items, not branches), so the digest goes to all-branch users only.
"""
import datetime as dt
import logging
import re

from django.utils import timezone

logger = logging.getLogger(__name__)

RECIPIENTS_SETTING = 'phantom_review_recipients'
TOP_IN_DIGEST = 5
_MONTH = re.compile(r'^(\d{4})-(\d{2})$')


def parse_month(raw, today=None):
    """'YYYY-MM' → first day of that month; empty → this month; anything else → None."""
    if not raw:
        return (today or timezone.localdate()).replace(day=1)
    m = _MONTH.match(str(raw).strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return dt.date(int(m.group(1)), int(m.group(2)), 1)


def next_month(month):
    return (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def _bounds(month):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(dt.datetime.combine(month, dt.time.min), tz)
    end = timezone.make_aware(dt.datetime.combine(next_month(month), dt.time.min), tz)
    return start, end


def state_of(override):
    return override if override in ('confirmed', 'excluded') else 'pending'


def monthly_review(month, qs=None):
    """Items whose phantom flag turned on in `month` (a date on the 1st). `qs` lets the view pass its
    filtered Item queryset. Pending first, then by EGP."""
    from apps.catalog.models import Item
    from .phantom_views import _FIELDS, _row
    start, end = _bounds(month)
    qs = (qs if qs is not None else Item.objects.all()).filter(
        phantom_flagged_at__gte=start, phantom_flagged_at__lt=end).only(*_FIELDS)
    rows = []
    for it in qs:
        r = _row(it)
        r['state'] = state_of(it.phantom_override)
        r['egp'] = round(r['buyback_qty'] * r['cost'], 2)
        rows.append(r)
    rows.sort(key=lambda r: (r['state'] != 'pending', -r['egp']))
    pending = [r for r in rows if r['state'] == 'pending']
    return {
        'month': month.strftime('%Y-%m'),
        'count': len(rows),
        'pending': len(pending),
        'reviewed': len(rows) - len(pending),
        'egp_total': round(sum(r['egp'] for r in rows), 2),
        'egp_pending': round(sum(r['egp'] for r in pending), 2),
        'items': rows,
    }


def digest_body(data):
    top = [r for r in data['items'] if r['state'] == 'pending'][:TOP_IN_DIGEST]
    lines = [f"{i}. {r['name']} ({r['code']}) — {round(r['egp']):,} ج" for i, r in enumerate(top, 1)]
    head = (f"{data['count']} صنف جديد اتعلّم «وهمي» في {data['month']}، منهم {data['pending']} بانتظار قرارك "
            f"بقيمة {round(data['egp_pending']):,} ج.")
    return head + ('\n' + '\n'.join(lines) if lines else '') + \
        '\nافتح «🩹 مبيعات وهمية» ← «جديد الشهر» للتأكيد أو «ليست وهمية». لا يُخفَّض أي طلب تلقائيًا.'


def send_monthly(today=None):
    """1st of the month: one digest of LAST month's new flags to the owner (SystemSetting
    phantom_review_recipients, else the HQ digest roles), once per month. Nothing pending → no send."""
    from apps.insights.hq_exceptions import digest_recipients
    from apps.notifications.models import Notification
    today = today or timezone.localdate()
    month = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    data = monthly_review(month)
    if not data['pending']:
        return 0
    title = f"🩹 مبيعات وهمية جديدة — {data['month']}: {data['pending']} للمراجعة"
    body = digest_body(data)
    sent = 0
    for staff in digest_recipients(RECIPIENTS_SETTING):
        n = Notification.send_to_user(staff, 'monthly_report', title, body,
                                      dedup_key=f"phantom_review_{data['month']}", dedup_once=True)
        sent += int(n is not None)
    logger.info('[PHANTOM] monthly review %s: %s new, %s pending, sent=%s',
                data['month'], data['count'], data['pending'], sent)
    return sent
