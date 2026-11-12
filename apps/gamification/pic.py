"""
apps/gamification/pic.py — customer-code (PIC) gamification.

Reuses the PIC Analytics definitions (docs/architecture/33_PIC_ANALYTICS.md) instead of
inventing new ones:
  • a sale is "on a PIC" when the invoice header carries `softech_phcode` (blank = walk-in);
  • new / reactivated come from pic_analytics.rules.classify_pic — first purchase ever on
    the day AND SOFTECH created the code no earlier than 30 days before (custdate), so an old
    customer whose history predates our mirror is never "new"; reactivated = previous visit
    365+ days earlier;
  • credit for a new / reactivated PIC goes to the salesperson of that day's FIRST invoice
    (doc 33 attribution);
  • excluded PICs (pic_analytics.PicExclusion — shared / house codes) never count.
Anti-gaming: a visit is a distinct customer per day (splitting a sale earns nothing), a new
PIC must have a phone, be a person (not an account placeholder / entity / merged code) and
its first invoice must be a positive sale; every rule has a daily cap; the customer-code day
bonus is judged only at day close, never on a partial day.

Reads our PostgreSQL mirror only (customers.PurchaseHistory / Customer). Never SOFTECH.
"""
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Max, Q
from django.utils import timezone

CHUNK = 2000


def _excluded():
    try:
        from apps.pic_analytics.exclusions import excluded_pics
        return excluded_pics()
    except Exception:                       # pic_analytics not installed / not migrated
        return frozenset()


def capture_pct():
    return int(getattr(settings, 'GAMIFICATION_PIC_CAPTURE_PCT', 70))


def capture_min():
    return int(getattr(settings, 'GAMIFICATION_PIC_CAPTURE_MIN_INVOICES', 10))


def _chunks(seq, n=CHUNK):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def collect(sc, day, start, end):
    """Engine collector: new PICs, reactivated PICs and customers served on their code."""
    from apps.customers.models import Customer, PurchaseHistory
    from apps.pic_analytics.rules import classify_pic

    excluded = _excluded()
    rows = (PurchaseHistory.objects
            .filter(invoice_date__gte=start, invoice_date__lt=end, doc_code='115')
            .exclude(softech_phcode='')
            .order_by('trans_time', 'id')
            .values('id', 'softech_phcode', 'softech_user', 'branch_id', 'invoice_date',
                    'trans_time', 'total_amount'))
    first = {}                                   # pic -> first invoice of the day
    served = set()                               # (staff_id, pic)
    for r in rows:
        pic = (r['softech_phcode'] or '').strip()
        if not pic or pic in excluded:
            continue
        first.setdefault(pic, r)
        staff = sc.by_code.get((r['softech_user'] or '').strip())
        if staff and (staff.id, pic) not in served:
            served.add((staff.id, pic))
            sc.award(staff, 'pic_visit', f'picv:{pic}:{day}', r['trans_time'] or r['invoice_date'],
                     branch_id=r['branch_id'], meta={'pic': pic})
    if not first:
        return

    last_before = {}
    for part in _chunks(first):
        for x in (PurchaseHistory.objects
                  .filter(softech_phcode__in=part, doc_code='115', invoice_date__lt=start)
                  .values('softech_phcode').annotate(last=Max('invoice_date'))):
            last_before[x['softech_phcode']] = x['last']
    customers = {}
    for part in _chunks(first):
        for c in Customer.objects.filter(softech_pic__in=part).values(
                'softech_pic', 'softech_created_at', 'phone', 'phone_alt', 'is_account_placeholder',
                'softech_locked', 'merged_into_pic'):
            customers[c['softech_pic']] = c

    for pic, r in first.items():
        staff = sc.by_code.get((r['softech_user'] or '').strip())
        if staff is None:
            continue
        at = r['trans_time'] or r['invoice_date']
        prev = last_before.get(pic)
        prev_day = timezone.localdate(prev) if prev and timezone.is_aware(prev) else (
            prev.date() if prev else None)
        cust = customers.get(pic)
        label = classify_pic(first_purchase=prev_day or day,
                             created_at=cust['softech_created_at'] if cust else None,
                             prev_visit=prev_day, period_start=day, period_end=day,
                             first_visit_in_period=day)
        if label == 'new' and prev_day is None:
            person = cust and not cust['is_account_placeholder'] and not cust['softech_locked'] \
                and not cust['merged_into_pic']
            has_phone = cust and ((cust['phone'] or '').strip() or (cust['phone_alt'] or '').strip())
            if person and has_phone and (r['total_amount'] or 0) > 0:
                sc.award(staff, 'pic_new', f'picnew:{pic}', at, branch_id=r['branch_id'],
                         meta={'pic': pic})
        elif label == 'reactivated':
            sc.award(staff, 'pic_reactivated', f'picback:{pic}:{day}', at, branch_id=r['branch_id'],
                     meta={'pic': pic, 'away_days': (day - prev_day).days})


def capture_by_user(start, end, codes=None, excluded=None):
    """{softech_user: (sale_invoices, invoices_on_a_pic)} over [start, end)."""
    from apps.customers.models import PurchaseHistory
    excluded = _excluded() if excluded is None else excluded
    qs = PurchaseHistory.objects.filter(invoice_date__gte=start, invoice_date__lt=end, doc_code='115')
    if codes is not None:
        qs = qs.filter(softech_user__in=list(codes))
    out = defaultdict(lambda: [0, 0])
    for r in qs.values('softech_user', 'softech_phcode'):
        u = (r['softech_user'] or '').strip()
        out[u][0] += 1
        pic = (r['softech_phcode'] or '').strip()
        if pic and pic not in excluded:
            out[u][1] += 1
    return {u: tuple(v) for u, v in out.items()}


def judge_capture_day(sc, day):
    """Day close: +pic_capture_day for each salesperson whose day had ≥ capture_pct()% of at
    least capture_min() sale invoices on a customer code."""
    from .engine import day_bounds, _at
    if not sc.by_code:
        return
    start, end = day_bounds(day)
    for code, (total, on_pic) in capture_by_user(start, end, sc.by_code).items():
        staff = sc.by_code.get(code)
        if staff and total >= capture_min() and on_pic * 100 >= capture_pct() * total:
            sc.award(staff, 'pic_capture_day', f'piccap:{day}', _at(day),
                     meta={'invoices': total, 'on_pic': on_pic,
                           'pct': round(on_pic * 100 / total, 1)})


def summary(staff):
    """«عملائي» panel for one employee: today / this month, plus the next milestones."""
    from apps.customers.models import PurchaseHistory
    from .engine import day_bounds
    from .models import Badge, PointEvent
    code = (staff.softech_user_id or '').strip()
    if not code:
        return {'linked': False}
    today = timezone.localdate()
    t_start, t_end = day_bounds(today)
    m_start, _ = day_bounds(today.replace(day=1))
    excluded = _excluded()

    def block(start, end, first_day, last_day):
        total, on_pic = capture_by_user(start, end, [code], excluded).get(code, (0, 0))
        visits = (PurchaseHistory.objects
                  .filter(softech_user=code, doc_code='115', invoice_date__gte=start,
                          invoice_date__lt=end).exclude(softech_phcode='')
                  .exclude(softech_phcode__in=list(excluded))
                  .values('softech_phcode', 'invoice_date__date').distinct().count())
        counts = dict(PointEvent.objects.filter(
            staff=staff, rule_key__in=('pic_new', 'pic_reactivated', 'pic_capture_day'),
            day__gte=first_day, day__lte=last_day)
            .values('rule_key').annotate(n=Count('id')).values_list('rule_key', 'n'))
        return {'invoices': total, 'invoices_on_pic': on_pic,
                'capture_pct': round(on_pic * 100 / total, 1) if total else None,
                'customers_served': visits, 'new_pics': counts.get('pic_new', 0),
                'reactivated': counts.get('pic_reactivated', 0),
                'capture_days': counts.get('pic_capture_day', 0)}

    have = dict(PointEvent.objects.filter(staff=staff, rule_key__startswith='pic_')
                .values('rule_key').annotate(n=Count('id')).values_list('rule_key', 'n'))
    milestones = []
    for rule_key in ('pic_new', 'pic_visit', 'pic_reactivated', 'pic_capture_day'):
        nxt = (Badge.objects.filter(is_active=True, criteria=Badge.CRITERIA_RULE_COUNT,
                                    rule_key=rule_key, threshold__gt=have.get(rule_key, 0))
               .order_by('threshold').first())
        if nxt:
            milestones.append({'badge': nxt.key, 'icon': nxt.icon, 'name_ar': nxt.name_ar,
                               'name_en': nxt.name_en, 'rule_key': rule_key,
                               'progress': have.get(rule_key, 0), 'threshold': nxt.threshold})
    return {'linked': True, 'capture_target_pct': capture_pct(),
            'capture_min_invoices': capture_min(),
            'today': block(t_start, t_end, today, today),
            'month': block(m_start, t_end, today.replace(day=1), today),
            'milestones': milestones}


def branch_capture_rate(branch, start, end):
    """Team-challenge metric: % of the branch's sale invoices on a (non-excluded) PIC."""
    from apps.customers.models import PurchaseHistory
    from .engine import day_bounds
    s, _ = day_bounds(start)
    _, e = day_bounds(end)
    excluded = list(_excluded())
    qs = PurchaseHistory.objects.filter(branch=branch, doc_code='115', invoice_date__gte=s,
                                        invoice_date__lt=e)
    agg = qs.aggregate(total=Count('id'),
                       on_pic=Count('id', filter=~Q(softech_phcode='') & ~Q(softech_phcode__in=excluded)))
    return (agg['total'], agg['on_pic'])
