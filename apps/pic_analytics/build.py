"""Nightly fact build for PIC Analytics: PicDayFact (day-replace) and PicRollup (replace-all).
Reads the invoice mirror only; writes only our own tables. Deterministic — no estimates.

Return sign convention: PurchaseHistory.total_amount / line_total of doc 30 are stored POSITIVE
(forecasting/kpi.py computes sale - return), so returns are taken as abs() and subtracted.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Count, ExpressionWrapper, F, DecimalField, Min, Q, Sum
from django.db.models.functions import TruncDate

from apps.customers.models import Customer, PurchaseHistory, PurchaseHistoryLine
from apps.pic_analytics import rules
from apps.pic_analytics.models import PicDayFact, PicRollup

CAIRO = ZoneInfo('Africa/Cairo')
CHUNK_DAYS = 7
BATCH = 2000
SALE, RETURN = '115', '30'
ZERO = Decimal('0')


def channel_bucket_map() -> dict[str, str]:
    """sales_channel -> bucket; cash splits into its subtype (delivery/regular) like KpiResolver."""
    from apps.forecasting.models import ChannelBucketMap
    out = {}
    for r in ChannelBucketMap.objects.filter(active=True):
        out[r.channel] = r.subtype if (r.bucket == ChannelBucketMap.BUCKET_CASH and r.subtype) else r.bucket
    return out


def excluded_pics() -> set[str]:
    """PIC codes that must never count as a person: placeholders and merged-away customers."""
    return set(Customer.objects.filter(Q(is_account_placeholder=True) | ~Q(merged_into_pic=''))
               .exclude(softech_pic='').values_list('softech_pic', flat=True))


def _resolve_pic(raw, excluded) -> str:
    p = (raw or '').strip()
    return '' if (not p or p.startswith('ACCT-') or p in excluded) else p


def _start_dt(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=CAIRO)


def _local_day(dt) -> date:
    return dt.astimezone(CAIRO).date()


def _earliest_sale_days(excluded) -> dict[str, date]:
    """Earliest-ever doc-115 day per resolved PIC (all history, one aggregate query)."""
    out = {}
    qs = (PurchaseHistory.objects.filter(doc_code=SALE, invoice_date__isnull=False)
          .exclude(softech_phcode='').values('softech_phcode').annotate(first=Min('invoice_date')))
    for r in qs.iterator(chunk_size=5000):
        pic = _resolve_pic(r['softech_phcode'], excluded)
        if not pic:
            continue
        d = _local_day(r['first'])
        if pic not in out or d < out[pic]:
            out[pic] = d
    return out


def _new_row():
    return {'invoices': 0, 'returns': 0, 'net': ZERO, 'cost': ZERO, 'units': ZERO, 'lines': 0,
            'cats': defaultdict(lambda: ZERO)}


def _build_chunk(start: date, end: date, excluded, buckets, first_days) -> int:
    lo, hi = _start_dt(start), _start_dt(end + timedelta(days=1))
    hdr = (PurchaseHistory.objects.filter(invoice_date__gte=lo, invoice_date__lt=hi, doc_code__in=[SALE, RETURN])
           .annotate(day=TruncDate('invoice_date', tzinfo=CAIRO))
           .values('softech_phcode', 'day', 'branch_id', 'softech_user', 'sales_channel', 'doc_code')
           .annotate(n=Count('id'), net=Sum('total_amount')))
    cost_expr = ExpressionWrapper(F('cost_at_sale') * F('quantity'),
                                  output_field=DecimalField(max_digits=18, decimal_places=5))
    ln = (PurchaseHistoryLine.objects.filter(purchase__invoice_date__gte=lo, purchase__invoice_date__lt=hi,
                                             purchase__doc_code__in=[SALE, RETURN])
          .annotate(day=TruncDate('purchase__invoice_date', tzinfo=CAIRO),
                    softech_phcode=F('purchase__softech_phcode'), branch_id=F('purchase__branch_id'),
                    softech_user=F('purchase__softech_user'), sales_channel=F('purchase__sales_channel'),
                    doc_code=F('purchase__doc_code'), mt=F('item__medicine_type'))
          .values('softech_phcode', 'day', 'branch_id', 'softech_user', 'sales_channel', 'doc_code', 'mt')
          .annotate(n=Count('id'), qty=Sum('quantity'), val=Sum('line_total'), cost=Sum(cost_expr)))
    rows = defaultdict(_new_row)

    def key(r):
        return (_resolve_pic(r['softech_phcode'], excluded), r['day'], r['branch_id'],
                (r['softech_user'] or '').strip(), buckets.get(r['sales_channel'], 'other'))

    for r in hdr:
        row = rows[key(r)]
        if r['doc_code'] == SALE:
            row['invoices'] += r['n']
            row['net'] += r['net'] or ZERO
        else:
            row['returns'] += r['n']
            row['net'] -= abs(r['net'] or ZERO)
    for r in ln:
        row = rows[key(r)]
        sign = 1 if r['doc_code'] == SALE else -1
        row['cost'] += sign * abs(r['cost'] or ZERO)
        row['units'] += sign * abs(r['qty'] or ZERO)
        row['cats'][r['mt'] or '00'] += sign * abs(r['val'] or ZERO)
        if sign == 1:
            row['lines'] += r['n']

    objs = [PicDayFact(
        pic=k[0], day=k[1], branch_id=k[2], salesperson=k[3], channel_bucket=k[4],
        invoices=v['invoices'], returns=v['returns'], net=v['net'], cost=round(v['cost'], 2),
        units=v['units'], lines=v['lines'], net_by_category={c: str(a) for c, a in v['cats'].items()},
        is_first_purchase=bool(k[0] and v['invoices'] and first_days.get(k[0]) == k[1]),
    ) for k, v in rows.items()]
    with transaction.atomic():
        PicDayFact.objects.filter(day__gte=start, day__lte=end).delete()
        PicDayFact.objects.bulk_create(objs, batch_size=BATCH)
    return len(objs)


def build_day_facts(start: date, end: date) -> int:
    """Delete + rebuild PicDayFact for days in [start, end]; returns rows written."""
    excluded, buckets = excluded_pics(), channel_bucket_map()
    first_days = _earliest_sale_days(excluded)
    total, cur = 0, start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=CHUNK_DAYS - 1), end)
        total += _build_chunk(cur, chunk_end, excluded, buckets, first_days)
        cur = chunk_end + timedelta(days=1)
    return total


def _window_start(as_of: date) -> date:
    m = as_of.year * 12 + as_of.month - 1 - 11
    return date(m // 12, m % 12 + 1, 1)


def _rollup_for(pic, rows, as_of, wstart):
    visits = sorted({d for d, inv, _, _ in rows if inv > 0})
    if not visits:
        return None
    win = [d for d in visits if d >= wstart]
    bcount = defaultdict(int)
    seen = set()
    for d, inv, br, _ in rows:
        if inv > 0 and d >= wstart and (d, br) not in seen:
            seen.add((d, br))
            if br is not None:
                bcount[br] += 1
    home = min(bcount, key=lambda b: (-bcount[b], b)) if bcount else None
    cyc = rules.cycle_days(win)
    return PicRollup(
        pic=pic, as_of=as_of, first_purchase=visits[0], last_purchase=visits[-1],
        prev_visit_before_last=visits[-2] if len(visits) > 1 else None, visits_12m=len(win),
        months_a=rules.months_bought(win, as_of), streak_b=rules.longest_streak(win, as_of),
        cycle_days=None if cyc is None else round(Decimal(str(cyc)), 2),
        cycle_bucket=rules.cycle_bucket(cyc), lifetime_net=sum((n for _, _, _, n in rows), ZERO),
        home_branch_id=home)


def build_rollups(as_of: date) -> int:
    """Replace all PicRollup rows from PicDayFact (days <= as_of only); returns rows written."""
    wstart = _window_start(as_of)
    qs = (PicDayFact.objects.filter(day__lte=as_of).exclude(pic='')
          .order_by('pic', 'day').values_list('pic', 'day', 'invoices', 'branch_id', 'net'))
    out, cur_pic, cur_rows = [], None, []
    for pic, d, inv, br, net in qs.iterator(chunk_size=20000):
        if pic != cur_pic:
            if cur_rows:
                r = _rollup_for(cur_pic, cur_rows, as_of, wstart)
                if r:
                    out.append(r)
            cur_pic, cur_rows = pic, []
        cur_rows.append((d, inv, br, net))
    if cur_rows:
        r = _rollup_for(cur_pic, cur_rows, as_of, wstart)
        if r:
            out.append(r)
    with transaction.atomic():
        PicRollup.objects.all().delete()
        PicRollup.objects.bulk_create(out, batch_size=BATCH)
    return len(out)
