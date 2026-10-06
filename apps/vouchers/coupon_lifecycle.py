"""
apps/vouchers/coupon_lifecycle.py

Gift-coupon lifecycle tracking — READ-ONLY from SOFTECH.
Spec: docs/architecture/SOFTECH_GIFT_VOUCHER_STOCKING.md (doc types from `transdoc`).

Every movement of a coupon item carries the serial in stktrans.item_partno:
    10  شراء من مورد              stocked at HQ (both legs) — already in the archive
    170 صرف أصناف مصروفات          POINTS coupon (102230) issued to a customer; header phcode = PIC
    125 / 25 تبادل بين الفروع      SERVED coupon (118639) HQ → branch / received at the branch
    115 مبيعات لعميل               SERVED coupon redeemed on a sale at −50 EGP; header phcode = PIC
    30  (customer return)         redemption reversed
sync_events() mirrors those lines into CouponEvent (a date window is replaced, so re-runs
are idempotent); rebuild_summaries() recomputes each CouponSerial's lifecycle + anomaly
flags deterministically from its events. Nothing is ever written to SOFTECH.
"""
import datetime as dt
import logging
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction

from . import coupons

logger = logging.getLogger('elrezeiky.vouchers')

_DB = 'SOFTECHDB9.dbo'

# Every doccode that moves a coupon item, named from SOFTECH `transdoc` (probe --doctypes,
# 2026-10-06). Unlisted codes fall back to the transdoc name (تبادل = transfer), else 'other'.
_KIND_BY_DOCCODE = {
    '170': 'issue',            # صرف أصناف مصروفات — points coupon issued to a customer
    '70':  'issue_return',     # إستلام أصناف مصروفات — issue reversed
    '125': 'transfer_out',     # صرف - تبادل بين الفروع
    '110': 'transfer_out',     # صرف من الرئيسي إلى الفرع (older pair)
    '130': 'transfer_out',     # صرف من الفرع إلى الرئيسي
    '25':  'transfer_in',      # إستلام - تبادل بين الفروع
    '15':  'transfer_in',      # إستلام في الفرع من الرئيسي
    '20':  'transfer_cancel',  # إلغاء صرف - تبادل بين الفروع — back at the sender
    '115': 'redeem',           # مبيعات لعميل
    '180': 'redeem',           # تسليم حجز بضاعة غير موجودة — reservation delivered (a sale)
    '30':  'redeem_return',    # مرتجع من عميل
    '81':  'redeem_return',    # مرتجع تسليم حجز بضاعة
    '80':  'reservation',      # حجز بضاعة غير موجودة — booking only, no coupon used
    '181': 'reservation',      # إلغاء حجز بضاعة
    '150': 'stock_count',      # عجز جرد
    '50':  'stock_count',      # فائض جرد
    '120': 'supplier_return',  # مرتجع للمورد
}
_POINTS_ONLY = {'issue', 'issue_return'}
_SERVED_ONLY = {'redeem', 'redeem_return'}

# Serial-level flags compare movement QUANTITIES with the quantity stocked under the serial
# (early-2025 "lot" lines stocked many coupons under one serial). Customer-level misuse is
# reported separately (report()['customers']) because SOFTECH staff pick a stock row by serial
# at each step, so the serial on a sale is not always the physical coupon's.
ANOMALY_LABELS = {
    'redeemed_twice':            'استُخدم أكثر من الكمية المُدخلة بهذا السريال',
    'issued_twice':              'صُرف لعملاء أكثر من الكمية المُدخلة بهذا السريال',
    'redeemed_not_issued':       'استُخدم دون صرفه لعميل مقابل نقاط',
    'redeemed_not_stocked':      'استُخدم ولم يُدخل في المخزن على صنف الاستحقاق',
    'redeemed_at_unsent_branch': 'استُخدم في فرع لم يُرسل إليه',
    'lot_serial':                'سريال مشترك لعدة كوبونات (أُدخل بكمية أكبر من 1)',
}


def since_default():
    return str(getattr(settings, 'COUPON_LIFECYCLE_SINCE', '2021-01-01'))


def classify(doccode, leg, doc_name=''):
    """(kind, direction) of a coupon movement line."""
    code = str(doccode).strip()
    kind = _KIND_BY_DOCCODE.get(code)
    if kind is None and 'تبادل' in (doc_name or ''):
        kind = 'transfer_in' if ('استلام' in doc_name or 'إستلام' in doc_name) else 'transfer_out'
    if (kind in _POINTS_ONLY and leg != 'points') or (kind in _SERVED_ONLY and leg != 'served'):
        kind = 'other'
    try:
        direction = 'in' if int(code) < 99 else 'out'
    except ValueError:
        direction = 'out'
    return kind or 'other', direction


def _dec(v):
    try:
        return Decimal(str(v if v is not None else 0))
    except (InvalidOperation, ValueError):
        return Decimal('0')


def _s(v):
    return '' if v is None else str(v).strip()


# ── SOFTECH reads (SELECT only) ────────────────────────────────────────────────
def read_doc_names(conn):
    cur = conn.cursor()
    cur.execute(f'SELECT doccode, docdescr FROM {_DB}.transdoc')
    return {_s(r[0]): _s(r[1]) for r in cur.fetchall()}


def read_movements(conn, itemcode, start, end):
    """All non-purchase lines of one coupon item with start ≤ docdate < end, joined to
    their header (party + customer PIC)."""
    cur = conn.cursor()
    timeout = int(getattr(settings, 'SYBASE_SYNC_QUERY_TIMEOUT', 300))
    cur.execute(f"""
        SELECT t.branchcode, t.doccode, t.docnumber, t.docdate, t.storecode, t.dblitemflag,
               t.transqty, t.itemsaleprice, t.item_partno, t.usercode,
               m.cust_branch_code, m.phcode
        FROM {_DB}.stktrans t, {_DB}.stktransm m
        WHERE t.itemcode = ? AND t.doccode <> '10' AND t.docdate >= ? AND t.docdate < ?
          AND m.branchcode = t.branchcode AND m.doccode = t.doccode AND m.docnumber = t.docnumber
    """, [itemcode, start.isoformat(), end.isoformat()], timeout=timeout)
    keys = ('branchcode', 'doccode', 'docnumber', 'docdate', 'storecode', 'dblitemflag', 'transqty',
            'itemsaleprice', 'item_partno', 'usercode', 'cust_branch_code', 'phcode')
    return [dict(zip(keys, r)) for r in cur.fetchall()]


def _windows(start, end, days=31):
    d = start
    while d < end:
        nxt = min(d + dt.timedelta(days=days), end)
        yield d, nxt
        d = nxt


# ── mirror + rebuild ───────────────────────────────────────────────────────────
@transaction.atomic
def store_events(rows, start, end, doc_names=None):
    """Replace every CouponEvent with start ≤ docdate < end by ``rows`` (dicts from
    read_movements, plus 'itemcode'). Returns counts. Idempotent for a given window."""
    from apps.customers.models import Customer
    from .models import CouponEvent, CouponSerial

    doc_names = doc_names or {}
    CouponEvent.objects.filter(docdate__gte=start, docdate__lt=end).delete()
    serial_ids = dict(CouponSerial.objects.values_list('serial', 'id'))
    pics = {_s(r.get('phcode')) for r in rows if _s(r.get('phcode'))}
    customers = dict(Customer.objects.filter(softech_pic__in=pics).values_list('softech_pic', 'id'))

    events, seen = [], set()
    stats = {'lines': 0, 'linked': 0, 'no_serial': 0, 'unknown_serial': 0}
    for r in rows:
        leg = coupons.leg_for_item(r.get('itemcode'))
        docdate = coupons.to_date(r.get('docdate'))
        docnumber = coupons.to_docnumber(r.get('docnumber'))
        if not leg or docdate is None or docnumber is None:
            continue
        key = (_s(r.get('branchcode')), _s(r.get('doccode')), docnumber, _s(r.get('itemcode')),
               int(_dec(r.get('dblitemflag'))))
        if key in seen:
            continue
        seen.add(key)
        stats['lines'] += 1
        raw = _s(r.get('item_partno'))
        parsed = coupons.parse_serial(raw)
        sid = serial_ids.get(parsed[2]) if parsed else None
        if sid:
            stats['linked'] += 1
        elif parsed:
            stats['unknown_serial'] += 1
        else:
            stats['no_serial'] += 1
        doccode = _s(r.get('doccode'))
        name = doc_names.get(doccode, '')
        kind, _ = classify(doccode, leg, name)
        pic = _s(r.get('phcode'))
        events.append(CouponEvent(
            serial_id=sid, raw_serial=raw[:40], leg=leg, itemcode=key[3], kind=kind,
            doccode=doccode, doc_name=name[:100], branchcode=key[0], storecode=_s(r.get('storecode')),
            docnumber=docnumber, docdate=docdate, line_no=key[4], qty=_dec(r.get('transqty')),
            price=_dec(r.get('itemsaleprice')), party_code=_s(r.get('cust_branch_code'))[:10],
            customer_pic=pic[:30], customer_id=customers.get(pic), usercode=_s(r.get('usercode'))[:10]))
    CouponEvent.objects.bulk_create(events, batch_size=2000)
    return stats


def summarise(serial, events):
    """Pure: the lifecycle fields + anomaly codes of one serial from its events
    (objects with kind/leg/branchcode/party_code/docdate/docnumber/customer_pic/qty)."""
    hq = coupons.hq_branch()
    order = {'transfer_out': 0, 'transfer_cancel': 1, 'transfer_in': 2}
    ev = sorted(events, key=lambda e: (e.docdate, order.get(e.kind, 3), e.docnumber))

    def total(kind):
        return sum((Decimal(str(e.qty or 0)) for e in ev if e.kind == kind), Decimal('0'))

    issued = total('issue') - total('issue_return')
    redeemed = total('redeem') - total('redeem_return')
    points_cap = max(Decimal(str(serial.points_qty or 0)), Decimal('1'))
    served_cap = max(Decimal(str(serial.served_qty or 0)), Decimal('1'))
    is_lot = points_cap > 1 or served_cap > 1
    issues = [e for e in ev if e.kind == 'issue']
    redeems = [e for e in ev if e.kind == 'redeem']

    out = {
        'issue_count': int(issued), 'redeem_count': int(redeemed),
        'issued_at': None, 'issued_doc': None, 'issued_branch': '', 'issued_pic': '',
        'sent_branch': '', 'sent_at': None,
        'redeemed_at': None, 'redeemed_doc': None, 'redeemed_branch': '', 'redeemed_pic': '',
    }
    if issues and issued > 0:
        e = issues[0]
        out.update(issued_at=e.docdate, issued_doc=e.docnumber, issued_branch=e.branchcode,
                   issued_pic=e.customer_pic)
    sent_to = set()
    for e in ev:                       # location = destination of the latest transfer step
        if e.kind == 'transfer_out':
            dest = e.party_code
        elif e.kind == 'transfer_in':
            dest = e.branchcode
        elif e.kind == 'transfer_cancel':
            dest = e.branchcode
        else:
            continue
        sent_to.add(dest)
        out.update(sent_branch=dest, sent_at=e.docdate)
    if out['sent_branch'] == hq:
        out.update(sent_branch='', sent_at=None)
    if redeems and redeemed > 0:
        e = redeems[-1]
        out.update(redeemed_at=e.docdate, redeemed_doc=e.docnumber, redeemed_branch=e.branchcode,
                   redeemed_pic=e.customer_pic)

    if redeemed > 0 and redeemed >= served_cap:
        stage = 'redeemed'
    elif out['sent_branch']:
        stage = 'at_branch'
    elif issued > 0:
        stage = 'issued'
    elif serial.points_docnumber or serial.served_docnumber:
        stage = 'stocked'
    elif redeemed > 0:
        stage = 'redeemed'
    else:
        stage = ''
    out['stage'] = stage

    flags = []
    if is_lot:
        flags.append('lot_serial')
    if redeemed > served_cap:
        flags.append('redeemed_twice')
    if issued > points_cap:
        flags.append('issued_twice')
    if redeemed > 0 and not is_lot:
        if issued <= 0:
            flags.append('redeemed_not_issued')
        if not serial.served_docnumber:
            flags.append('redeemed_not_stocked')
        if out['redeemed_branch'] not in sent_to | {hq}:
            flags.append('redeemed_at_unsent_branch')
    out['anomalies'] = flags
    return out


@transaction.atomic
def rebuild_summaries():
    """Recompute every CouponSerial's lifecycle from its events. Deterministic."""
    from .models import CouponEvent, CouponSerial

    by_serial = defaultdict(list)
    for e in CouponEvent.objects.exclude(serial_id=None).only(
            'serial_id', 'kind', 'leg', 'branchcode', 'docdate', 'docnumber', 'customer_pic',
            'party_code', 'qty'):
        by_serial[e.serial_id].append(e)
    fields = ['stage', 'issued_at', 'issued_doc', 'issued_branch', 'issued_pic', 'sent_branch',
              'sent_at', 'redeemed_at', 'redeemed_doc', 'redeemed_branch', 'redeemed_pic',
              'issue_count', 'redeem_count', 'anomalies']
    rows = list(CouponSerial.objects.all())
    for c in rows:
        for k, v in summarise(c, by_serial.get(c.id, [])).items():
            setattr(c, k, v)
    CouponSerial.objects.bulk_update(rows, fields, batch_size=1000)
    return len(rows)


def sync(conn, *, since=None, until=None, full=False, progress=None):
    """Mirror coupon movements from SOFTECH (read-only) and rebuild summaries.
    Default window: from 7 days before the latest mirrored event (or since_default()
    when empty / full) to tomorrow."""
    from .models import CouponEvent

    until = until or (dt.date.today() + dt.timedelta(days=1))
    if since is None:
        last = None if full else CouponEvent.objects.order_by('-docdate').values_list('docdate', flat=True).first()
        since = (last - dt.timedelta(days=7)) if last else dt.date.fromisoformat(since_default())
    names = read_doc_names(conn)
    totals = defaultdict(int)
    for start, end in _windows(since, until):
        rows = []
        for item in (coupons.points_item(), coupons.served_item()):
            for r in read_movements(conn, item, start, end):
                r['itemcode'] = item
                rows.append(r)
        for k, v in store_events(rows, start, end, names).items():
            totals[k] += v
        if progress:
            progress(start, end, len(rows))
    totals['serials'] = rebuild_summaries()
    totals['since'], totals['until'] = since.isoformat(), until.isoformat()
    return dict(totals)


# ── reporting ──────────────────────────────────────────────────────────────────
def report():
    from django.db.models import Count, Sum
    from .models import CouponEvent, CouponSerial

    flags = defaultdict(int)
    for lst in CouponSerial.objects.exclude(anomalies=[]).values_list('anomalies', flat=True):
        for f in lst:
            flags[f] += 1
    no_serial = (CouponEvent.objects.filter(serial_id=None, kind='redeem')
                 .values('branchcode').annotate(n=Count('id'), qty=Sum('qty')).order_by('-n'))
    from django.db.models.functions import ExtractYear
    by_year = (CouponEvent.objects.filter(serial_id=None, kind='redeem')
               .annotate(y=ExtractYear('docdate')).values('y').annotate(n=Count('id')).order_by('y'))
    recent = (CouponEvent.objects.filter(serial_id=None, kind='redeem',
                                         docdate__gte=dt.date.today() - dt.timedelta(days=365))
              .values('branchcode').annotate(n=Count('id'), qty=Sum('qty')).order_by('-n'))
    flagged_by_year = defaultdict(lambda: defaultdict(int))
    for lst, d in (CouponSerial.objects.exclude(anomalies=[])
                   .values_list('anomalies', 'redeemed_at')):
        for f in lst:
            flagged_by_year[f][d.year if d else '—'] += 1
    kinds = (CouponEvent.objects.filter(kind='other')
             .values('leg', 'doccode', 'doc_name').annotate(n=Count('id')).order_by('-n'))
    return {
        'customers': customer_balances(),
        'no_serial_redeems_by_year': [(r['y'], r['n']) for r in by_year],
        'no_serial_redeems_last_365d_by_branch': [(r['branchcode'], r['n'], float(r['qty'] or 0)) for r in recent],
        'anomalies_by_redeem_year': {k: dict(v) for k, v in flagged_by_year.items()},
        'unclassified_movements': [(r['leg'], r['doccode'], r['doc_name'], r['n']) for r in kinds],
        'stages': dict(CouponSerial.objects.values_list('stage').annotate(n=Count('id')).values_list('stage', 'n')),
        'anomalies': dict(flags),
        'redeemed_without_valid_serial_by_branch': [(r['branchcode'], r['n'], float(r['qty'] or 0)) for r in no_serial],
        'redeemed_by_branch': list(CouponSerial.objects.filter(stage='redeemed')
                                   .values('redeemed_branch').annotate(n=Count('id')).order_by('-n')
                                   .values_list('redeemed_branch', 'n')),
    }


def customer_balances(redeemed_since=None, limit=20):
    """Per customer PIC: coupons issued to them (170 − 70, all synced history, with or without
    a serial) vs coupons redeemed on their sales (115/180 − 30/81) since ``redeemed_since``
    (default COUPON_CUSTOMER_CHECK_SINCE, 2022-01-01 — issues need a lead time). A customer who
    redeemed more than they were ever issued is the robust misuse signal."""
    from django.db.models import Max, Q, Sum
    from .models import CouponEvent

    since = redeemed_since or dt.date.fromisoformat(
        str(getattr(settings, 'COUPON_CUSTOMER_CHECK_SINCE', '2022-01-01')))
    qs = CouponEvent.objects.exclude(customer_pic='')
    issued = dict(qs.filter(kind__in=('issue', 'issue_return')).values('customer_pic').annotate(
        n=Sum('qty', filter=Q(kind='issue'), default=0) - Sum('qty', filter=Q(kind='issue_return'), default=0))
        .values_list('customer_pic', 'n'))
    red = (qs.filter(kind__in=('redeem', 'redeem_return'), docdate__gte=since).values('customer_pic')
           .annotate(n=Sum('qty', filter=Q(kind='redeem'), default=0)
                     - Sum('qty', filter=Q(kind='redeem_return'), default=0),
                     last=Max('docdate')))
    over = []
    for r in red:
        got = issued.get(r['customer_pic']) or 0
        if (r['n'] or 0) > got:
            over.append({'pic': r['customer_pic'], 'issued': float(got), 'redeemed': float(r['n']),
                         'excess': float(r['n'] - got), 'last': r['last']})
    over.sort(key=lambda x: -x['excess'])
    blank = CouponEvent.objects.filter(customer_pic='', kind='redeem', docdate__gte=since).aggregate(
        n=Sum('qty'))['n'] or 0
    return {'since': since, 'customers_over': len(over),
            'excess_total': sum(x['excess'] for x in over), 'top': over[:limit],
            'redeemed_without_customer': float(blank)}


def no_serial_redeems(branch, days=365):
    """Redemption lines at ``branch`` in the last ``days`` whose serial is blank / not a coupon
    serial — what the item card forbids («يجب ارفاق سيريال الكوبون»)."""
    from .models import CouponEvent
    return list(CouponEvent.objects.filter(
        serial_id=None, kind='redeem', branchcode=str(branch),
        docdate__gte=dt.date.today() - dt.timedelta(days=days)).order_by('-docdate', '-docnumber'))
