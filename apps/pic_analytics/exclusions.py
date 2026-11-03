"""
apps/pic_analytics/exclusions.py — the changeable list of PICs left out of the analytics (doc 33 §15).

An excluded PIC is not a real individual customer (a running account, a doctor's code, junk phones...).
It is removed from every customer count / average / ranking / frequency / cohort / PIC list / group row /
retention and per-PIC call figure; its sales stay visible as ONE line («عملاء مستبعدون») so the overview
still reconciles with the sales dashboard. Applied at QUERY time: `excluded_pics()` is the single source,
read by Filters.facts() and by the few queries that touch PicDayFact / CdrCall directly. Every change is
audited (who / what / when / why). Suggestions are deterministic rules; nothing is ever auto-excluded.
"""
import re
from datetime import timedelta
from decimal import Decimal
from statistics import median

from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.customers.models import Customer
from apps.pic_analytics.models import PicDayFact, PicExclusion

ZERO = Decimal('0')
MAX_REASON = 255
SUGGESTION_LIMIT = 20
MIN_VISITS = 20                 # suggestion rules
MIN_INVOICES_PER_VISIT = 5
NET_MULTIPLE = 50
MIN_DISTINCT_DIGITS = 7
RULE_LABELS = {
    'visits': 'زيارات كثيرة (20 أو أكثر)',
    'invoices_per_visit': 'فواتير كثيرة في الزيارة (5 أو أكثر)',
    'junk_phone': 'رقم هاتف غير حقيقي',
    'net': 'صافي المبيعات 50 ضعف الوسيط',
}


class ExclusionError(ValueError):
    """A bad add/remove request — the message is Arabic and safe to show."""


def excluded_pics(memo=None) -> frozenset:
    """The active excluded PIC codes. `memo` (Filters.memo) caches it for one request."""
    if memo is not None and 'excluded_pics' in memo:
        return memo['excluded_pics']
    pics = frozenset(PicExclusion.objects.filter(removed_at__isnull=True).values_list('pic', flat=True))
    if memo is not None:
        memo['excluded_pics'] = pics
    return pics


def _json(x, ctx):
    c = ctx.get(x.pic, {})
    return {'id': x.pk, 'pic': x.pic, 'customer_name': c.get('name', ''), 'reason': x.reason,
            'added_by': x.added_by.full_name if x.added_by_id else '', 'added_at': x.added_at,
            'net_12m': c.get('net', ZERO), 'visits_12m': c.get('visits', 0)}


def _context(pics):
    """{pic: {name, net, visits}} — last 12 months, all branches (management only sees this)."""
    since = timezone.localdate() - timedelta(days=365)
    out = {p: {'name': '', 'net': ZERO, 'visits': 0} for p in pics}
    for c in Customer.objects.filter(softech_pic__in=list(pics)).order_by('-pk'):
        out[c.softech_pic]['name'] = c.name          # lowest pk wins (iterated last)
    for r in (PicDayFact.objects.filter(pic__in=list(pics), day__gte=since).values('pic')
              .annotate(s=Sum('net'), v=Count('day', distinct=True, filter=Q(invoices__gt=0)))):
        out[r['pic']].update(net=r['s'] or ZERO, visits=r['v'])
    return out


def exclusion_rows() -> list:
    rows = list(PicExclusion.objects.filter(removed_at__isnull=True).select_related('added_by__user'))
    ctx = _context([x.pic for x in rows])
    return [_json(x, ctx) for x in rows]


def exclusion_json(x) -> dict:
    return _json(x, _context([x.pic]))


def add_exclusion(pic, reason, staff, request=None) -> PicExclusion:
    pic = str(pic or '').strip()
    reason = str(reason or '').strip()
    if not pic:
        raise ExclusionError('رمز العميل (PIC) مطلوب')
    if not reason:
        raise ExclusionError('سبب الاستبعاد مطلوب')
    if len(reason) > MAX_REASON:
        raise ExclusionError(f'السبب أطول من {MAX_REASON} حرف')
    if pic.startswith('ACCT-') or not Customer.objects.filter(softech_pic=pic).exists():
        raise ExclusionError('رمز العميل (PIC) غير موجود')
    try:
        with transaction.atomic():
            if PicExclusion.objects.filter(pic=pic, removed_at__isnull=True).exists():
                raise ExclusionError('العميل مستبعد بالفعل')
            x = PicExclusion.objects.create(pic=pic, reason=reason, added_by=staff)
            from apps.audit.models import AuditLog
            AuditLog.log('pic_analytics_pic_excluded', user=staff, obj=x, request=request, note=reason,
                         extra={'pic': pic, 'before': 'included', 'after': 'excluded', 'reason': reason})
    except IntegrityError:                    # a concurrent add won the unique constraint
        raise ExclusionError('العميل مستبعد بالفعل')
    return x


def remove_exclusion(pk, staff, request=None, note=''):
    """Soft-delete one active exclusion; None when it does not exist (or is already removed)."""
    with transaction.atomic():
        x = PicExclusion.objects.select_for_update().filter(pk=pk, removed_at__isnull=True).first()
        if x is None:
            return None
        x.removed_at, x.removed_by = timezone.now(), staff
        x.save(update_fields=['removed_at', 'removed_by'])
        from apps.audit.models import AuditLog
        AuditLog.log('pic_analytics_pic_included', user=staff, obj=x, request=request, note=str(note or '')[:255],
                     extra={'pic': x.pic, 'before': 'excluded', 'after': 'included', 'reason': x.reason})
    return x


# ── suggestions ─────────────────────────────────────────────────────────────────────────────────

def junk_phone(phone) -> bool:
    """A phone that cannot belong to a person: letters/symbols, fewer than 7 digits or distinct digits,
    or one short group of digits repeated (0101010101...). An empty phone is NOT junk."""
    raw = str(phone or '').strip()
    if not raw:
        return False
    digits = re.sub(r'\D', '', raw)
    if len(digits) < 7 or re.search(r'[^\d\s+\-()]', raw):
        return True
    if len(set(digits)) < MIN_DISTINCT_DIGITS:
        return True
    return any(len(digits) % n == 0 and digits == digits[:n] * (len(digits) // n) for n in range(1, 5))


def suggestions(f, access) -> list:
    """Top PICs in the range that look non-individual, with the rule(s) that flagged each.
    Already-excluded PICs are skipped (f.facts leaves them out). Never returns a phone."""
    stats = {r['pic']: r for r in f.facts(access, pic_filters=False).exclude(pic='').values('pic').annotate(
        s_net=Sum('enet'), s_inv=Sum('invoices'), visits=Count('day', distinct=True, filter=Q(invoices__gt=0)))
        .filter(visits__gt=0)}
    if not stats:
        return []
    med = Decimal(str(median([r['s_net'] or ZERO for r in stats.values()])))
    phones = {}
    for pic, phone in Customer.objects.filter(softech_pic__in=list(stats)).values_list('softech_pic', 'phone'):
        phones.setdefault(pic, []).append(phone)
    out = []
    for pic, r in stats.items():
        rules = []
        if r['visits'] >= MIN_VISITS:
            rules.append('visits')
        if r['s_inv'] and r['s_inv'] / r['visits'] >= MIN_INVOICES_PER_VISIT:
            rules.append('invoices_per_visit')
        if any(junk_phone(p) for p in phones.get(pic, ())):
            rules.append('junk_phone')
        if med > 0 and (r['s_net'] or ZERO) >= NET_MULTIPLE * med:
            rules.append('net')
        if rules:
            out.append({'pic': pic, 'rules': rules, 'rule_labels': [RULE_LABELS[x] for x in rules],
                        'visits': r['visits'], 'invoices': r['s_inv'] or 0, 'net': r['s_net'] or ZERO})
    out.sort(key=lambda x: (-len(x['rules']), -x['net'], x['pic']))
    out = out[:SUGGESTION_LIMIT]
    names = {}
    for c in Customer.objects.filter(softech_pic__in=[x['pic'] for x in out]).order_by('-pk'):
        names[c.softech_pic] = c.name
    for x in out:
        x['customer_name'] = names.get(x['pic'], '')
    return out
